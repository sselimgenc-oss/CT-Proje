"""`BinanceKagitYurutucu` (K-81, Aşama A; docs/binance-plan.md §4): `Yurutucu` arayüzüne uyar; emir GÖNDERMEZ, anahtar YOK. Dolum fiyatı = Binance public derinliği (alışta ask tarafı, satışta bid tarafı yürünür;
boyuta göre kayma defter yürüyüşünden gelir). Motor bunu `SanalYurutucu` yerine kullanır: defter/K-74/K-75/K-76/K-77/stoplar/tasfiye/risk kapıları AYNI sanal yoldan işler (kâğıtta her özellik AÇIK ve işleme etkili).

Modelin parçaları (hepsi `kurallar.yaml` `binance_*`; "DOĞRULANMADI" işaretliler resmi dokümandan teyit bekler):
- Eşleme: `binance_eslesme.yaml`; eşlemesiz / doğrulanmamış coinde AÇILIŞ yok (`binance_eslesme_yok` / `binance_eslesme_dogrulanmadi`; motor `acilis_kapisi` ile `_atla` yoluna sokar, kapanış serbest).
- Gecikme: `binance_kagit_gecikme_ms` kadar beklenip defter ondan sonra okunur (varsayım 250 ms; ölçülmedi).
- IOC bandı: çağıran `bant` vermediyse majör `binance_kagit_ioc_bant_major`, diğerleri `..._alt` (Fable F3 önerisi; 5a p95 ile kesinleşecek). Kapanış/azaltma band içinde dolmazsa reduceOnly MARKET gibi bantsız yürür.
- Yuvarlama: miktar `stepSize`'a (açılışta AŞAĞI, kapanışta en yakın; pozisyonu aşmaz), limit fiyat `tickSize`'a İÇE; `minNotional` altı AÇILIŞ atlanır (`binance_min_nosyonel`); reduceOnly muaf (`binance_reduce_min_nosyonel_muaf`, DOĞRULANMADI).
- Ücret: taker `binance_taker` (VIP0 %0,05; DOĞRULANMADI; kâğıtta BNB indirimi yok sayılır).
- `binance_kagit_fark_bp`: null = düzeltme yok (doğrudan Binance fiyatı). Sayı = HL<->Binance ölçülen fark/kayma düzeltmesi (bp, + = bizim aleyhimize): dolum fiyatına alışta +, satışta − uygulanır.
Birimler `yurutucu.py` ile aynı ve HL birimidir: Dolum.sz = Binance miktarı / carpan, Dolum.px = Binance fiyatı × carpan (nosyonel $ aynı)."""
from __future__ import annotations

import math
import time
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any, Callable

from copytrade.canli.binance_eslesme import EslemeTablosu
from copytrade.canli.binance_piyasa import BinanceErisimYok, BinancePiyasa
from copytrade.canli.yurutucu import Dolum, SanalYurutucu, kayma
from copytrade.kurallar import load_rules

AD = "binance_kagit"
NEDEN_ISLEM_YOK = "binance_islem_yok"
NEDEN_MIN_NOSYONEL = "binance_min_nosyonel"
NEDEN_ERISIM_YOK = "binance_erisim_yok"
MAJORLER = ("BTC", "ETH", "SOL", "XRP", "BNB", "DOGE")      # IOC bandı sınıfı: bu coinler `..._major`, diğerleri (altcoin / TradFi) `..._alt` (öneri)


def adim_yuvarla(x: float, adim: float, yon: str = "asagi") -> float:
    """`adim` (stepSize/tickSize) katına yuvarlar: 'asagi' | 'yukari' | 'yakin'. Decimal (kayan nokta artığı bir adım kaydırmasın)."""
    a = Decimal(repr(round(float(adim), 12)))
    q = Decimal(repr(round(float(x), 12))) / a
    n = q.to_integral_value(rounding={"asagi": ROUND_FLOOR, "yakin": ROUND_HALF_UP}.get(yon, ROUND_CEILING))
    return float(n * a)


def tick_limit(en_iyi: float, bant: float, yon: str, tick: float) -> float:
    """IOC limit fiyatı: en iyi karşı fiyat ± bant, tick'e İÇE (alış aşağı, satış yukarı); alış ≥ en iyi ask, satış ≤ en iyi bid (IOC dolabilsin; yerel `limit_yuvarla` Y-7 ile aynı kural)."""
    if yon == "B":
        return max(adim_yuvarla(en_iyi * (1 + bant), tick, "asagi"), en_iyi)
    return min(adim_yuvarla(en_iyi * (1 - bant), tick, "yukari"), en_iyi)


def _hl_post_yok(_yuk: dict) -> Any:
    raise RuntimeError("BinanceKagitYurutucu HL post kullanmaz")


def _yuru(seviyeler: list[tuple[float, float]], yon: str, hedef_q: float, sinir: float | None, adim: float) -> tuple[float, float, list[tuple[float, float]]]:
    """Karşı defteri `hedef_q` miktarı kadar yürür; alışta px > sinir, satışta px < sinir dolmaz (None = bantsız/MARKET). Döner (q, usd, tüketilen [(px, q)])."""
    q = usd = 0.0
    tuketim: list[tuple[float, float]] = []
    kalan = hedef_q
    for px, sz in seviyeler:
        if kalan <= adim * 1e-6:
            break
        if sinir is not None and ((yon == "B" and px > sinir + 1e-12) or (yon == "A" and px < sinir - 1e-12)):
            break
        al = min(sz, kalan)
        q += al
        usd += al * px
        kalan -= al
        tuketim.append((px, al))
    q = adim_yuvarla(q, adim, "yakin")                      # seviye miktarları adım katıdır; kayan nokta artığını at
    return q, usd, tuketim


class BinanceKagitYurutucu(SanalYurutucu):
    kip = "sanal"
    ad = AD

    def __init__(self, piyasa: BinancePiyasa, tablo: EslemeTablosu | None = None, rules: dict | None = None, saat_ms: Callable[[], int] | None = None,
                 uyku: Callable[[float], Any] | None = None) -> None:
        super().__init__(post=_hl_post_yok, rules=rules or load_rules(), saat_ms=saat_ms)
        self.piyasa = piyasa
        self.tablo = tablo or EslemeTablosu.yukle()
        self.uyku = uyku or time.sleep
        self.neden_say: dict[str, int] = {}
        self.kayma_bp: list[float] = []                       # son dolumların işaretli kaymaları (bp; + = aleyhimize)
        self.kapanis_say = 0                                  # TAM kapanan pozisyon sayısı (reduce-only, açık miktarın tamamı)
        self.dolum_say = 0

    # ------------------------------------------------------------------ motor kancaları
    def acilis_kapisi(self, coin: str) -> str | None:
        """Motor `_emir_isle` (yalnız AÇILIŞ/artırma): eşleme yok / doğrulanmadı / Binance'te işlem yok → atlama nedeni; yoksa None. Bilgi okunamazsa (ağ) kapı AÇIK kalır: emir 'red' olur."""
        esl, neden = self.tablo.coz(coin)
        if neden:
            self.neden_say[neden] = self.neden_say.get(neden, 0) + 1
            return neden
        try:
            b = self.piyasa.bilgi(esl.binance) if esl else None
        except Exception:                                      # noqa: BLE001
            return None
        if b is None or b["durum"] != "TRADING":
            self.neden_say[NEDEN_ISLEM_YOK] = self.neden_say.get(NEDEN_ISLEM_YOK, 0) + 1
            return NEDEN_ISLEM_YOK
        return None

    def mmr_ayari(self) -> dict:
        """K-74 Binance uyarlaması: defterin tasfiye hesabı için bakım marjı oranları (`hesap.mmr_*`). Varsayılan + varsa sembol kademe tablosu; DOĞRULANMADI (leverageBracket imzalı uçtur, anahtarsız okunamaz)."""
        return {"varsayilan": float(self.rules.get("binance_mmr_varsayilan", 0.005)), "kademe": dict(self.rules.get("binance_mmr_kademe") or {})}

    def ozet(self) -> dict:
        s = sorted(self.kayma_bp)
        return {"yurutucu": AD, "binance": {"dolum": self.dolum_say, "kapanan": self.kapanis_say, "neden_say": dict(sorted(self.neden_say.items())), "kayma_n": len(s),
                                            "kayma_bp_medyan": (s[len(s) // 2] if s else None), "kayma_bp_p90": (s[min(len(s) - 1, int(len(s) * 0.9))] if s else None),
                                            "fark_bp": self._fark_bp(), "piyasa": self.piyasa.durum(), "mmr_dogrulandi": bool(self.rules.get("binance_mmr_dogrulandi", False))}}

    # ------------------------------------------------------------------ yardımcılar
    def _fark_bp(self) -> float | None:
        v = self.rules.get("binance_kagit_fark_bp")
        try:
            x = float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
        return x if x is not None and math.isfinite(x) and abs(x) <= 200 else None

    def _red(self, d: Dolum, durum: str, neden: str) -> Dolum:
        d.durum, d.neden = durum, neden
        self.neden_say[neden] = self.neden_say.get(neden, 0) + 1
        return d

    def _bant(self, coin: str, bant: float | None) -> float:
        if bant is not None:
            return float(bant)
        anahtar = "binance_kagit_ioc_bant_major" if str(coin).split(":")[-1].upper() in MAJORLER else "binance_kagit_ioc_bant_alt"
        return float(self.rules.get(anahtar, self.rules.get("canli_ioc_bant", 0.005)))

    # ------------------------------------------------------------------ emir
    def emir(self, coin: str, yon: str, usd: float, reduce_only: bool = False, acik_sz: float | None = None, bant: float | None = None, cloid: str | None = None) -> Dolum:
        d = Dolum(coin, yon, float(usd), reduce_only=reduce_only)
        ek: dict[str, Any] = {"yurutucu": AD}
        d.ek = ek
        esl, neden = self.tablo.coz(coin)
        if esl is None or (neden and not reduce_only):          # kapanış/azaltma: tabloda satır varsa (doğrulanmamış olsa da) serbest
            return self._red(d, "red", neden or "binance_eslesme_yok")
        sembol, carpan = esl.binance, esl.carpan
        ek.update({"binance_sembol": sembol, "carpan": carpan})
        try:
            bilgi = self.piyasa.bilgi(sembol)
        except BinanceErisimYok:
            return self._red(d, "red", NEDEN_ERISIM_YOK)
        except Exception as hata:                              # noqa: BLE001
            return self._red(d, "red", f"binance_bilgi_okunamadi: {type(hata).__name__}")
        if bilgi is None or (bilgi["durum"] != "TRADING" and not reduce_only):
            return self._red(d, "red", NEDEN_ISLEM_YOK)
        gecikme_ms = float(self.rules.get("binance_kagit_gecikme_ms", 0) or 0)
        if gecikme_ms > 0:
            self.uyku(gecikme_ms / 1000.0)                      # emir yolu gecikmesi: defter "sinyal + gecikme" anında okunur (DOĞRULANMADI varsayım)
        try:
            kitap = self.piyasa.defter(sembol)
        except BinanceErisimYok:
            return self._red(d, "red", NEDEN_ERISIM_YOK)
        except Exception as hata:                              # noqa: BLE001 - defter okunamadı: emir YOK (uydurma fiyat yok)
            return self._red(d, "red", f"binance_defter_okunamadi: {type(hata).__name__}")
        simdi = self.saat_ms()
        seviyeler_ham = kitap["asks"] if yon == "B" else kitap["bids"]
        if kitap["bids"] and kitap["asks"]:
            ek.update({"binance_bid": kitap["bids"][0][0], "binance_ask": kitap["asks"][0][0], "kitap_ms": kitap.get("ms"), "gecikme_ms": gecikme_ms})
        if not seviyeler_ham:
            return self._red(d, "dolmadi", "band_disi_ya_da_bos_defter")
        seviyeler = [(float(s["px"]), float(s["sz"])) for s in self._derinlik_dus(sembol, yon, [{"px": p, "sz": q} for p, q in seviyeler_ham], simdi)]
        if not seviyeler:
            return self._red(d, "dolmadi", "band_disi_ya_da_bos_defter")
        en_iyi = seviyeler[0][0]
        d.referans_px = en_iyi * carpan
        tick, adim = float(bilgi["tick"]), float(bilgi["step"])
        # ---- miktar (Binance birimi)
        ham_q = float(usd) / en_iyi
        if reduce_only:
            hedef_q = adim_yuvarla(ham_q, adim, "yakin")
            if acik_sz is not None:
                hedef_q = min(hedef_q, adim_yuvarla(abs(float(acik_sz)) * carpan, adim, "yakin"))
        else:
            hedef_q = adim_yuvarla(ham_q, adim, "asagi")         # slot tavanı adım yarısı kadar aşılmaz (HL D-1 ile aynı)
        if hedef_q <= 0:
            return self._red(d, "red", "sz_sifir" if reduce_only else NEDEN_MIN_NOSYONEL)
        min_n = float(bilgi.get("min_nosyonel") or 0.0)
        muaf = reduce_only and bool(self.rules.get("binance_reduce_min_nosyonel_muaf", True))
        if not muaf and (hedef_q * en_iyi < min_n - 1e-9 or hedef_q < float(bilgi.get("min_qty") or 0.0) - 1e-12):
            self.neden_say[NEDEN_MIN_NOSYONEL] = self.neden_say.get(NEDEN_MIN_NOSYONEL, 0) + 1
            d.neden = NEDEN_MIN_NOSYONEL                         # durum "dolmadi": açılış yok (HL min_nosyonel ile aynı biçim)
            return d
        # ---- yürüyüş: önce IOC bandı; kapanış/azaltma dolmazsa bantsız (reduceOnly MARKET)
        bant_k = self._bant(coin, bant)
        sinir = tick_limit(en_iyi, bant_k, yon, tick)
        q, dolan_usd, tuketim = _yuru(seviyeler, yon, hedef_q, sinir, adim)
        if reduce_only and q < hedef_q - adim * 1e-6:
            q, dolan_usd, tuketim = _yuru(seviyeler, yon, hedef_q, None, adim)
            ek["market_yedek"] = True
        ek.update({"bant": bant_k, "limit_px": sinir})
        if q <= 0:
            return self._red(d, "dolmadi", "band_disi_ya_da_bos_defter")
        self._tuketim += [(simdi, sembol, yon, px, t) for px, t in tuketim]
        ort = dolan_usd / q
        fark = self._fark_bp()
        if fark is not None:
            ort *= 1 + (fark / 1e4 if yon == "B" else -fark / 1e4)
            dolan_usd = ort * q
        ek.update({"binance_dolum_px": ort, "fark_bp_uygulanan": fark})
        d.sz, d.px, d.usd_dolan = q / carpan, ort * carpan, dolan_usd
        d.ucret = dolan_usd * float(self.rules.get("binance_taker", 0.0005))
        d.kayma_oran = kayma(yon, en_iyi, ort)
        tam_kapanis = reduce_only and acik_sz is not None and q >= adim_yuvarla(abs(float(acik_sz)) * carpan, adim, "yakin") - adim * 1e-6
        d.durum = "dolu" if q >= hedef_q - adim * 1e-6 or tam_kapanis else "kismi"
        self.dolum_say += 1
        if tam_kapanis:
            self.kapanis_say += 1
        if d.kayma_oran is not None:
            self.kayma_bp = (self.kayma_bp + [d.kayma_oran * 1e4])[-500:]
        return d
