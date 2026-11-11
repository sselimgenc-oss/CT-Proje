"""Yürütücü: ortak arayüz `emir(coin, yon, usd, reduce_only, acik_sz) -> Dolum`; iki arka uç (K‑29, docs/GOREV_T4 §1).

- `SanalYurutucu`: cüzdan YOK. Emir anında HL `l2Book` alınır, bizim tutarımızla defter yürünür (IOC: en iyi karşı fiyat ± `canli_ioc_bant` bandı dışındaki kısım dolmaz), dolum fiyatı = yürünen
  ortalama, ücret = taker (`maliyet_taker`; kayma ayrıca eklenmez: defter yürüyüşü kaymayı zaten taşır).
- `GercekYurutucu`: HL resmi Python SDK; coin başına İZOLE 3x, IOC limit, azaltma/kapama reduce‑only; dolmayan kısım yeniden denenmez. Anahtar YALNIZ ortam değişkeninden; yoksa kurulamaz.
  Bu modül gerçek kipi KURAR ve testle (sahte `exchange`) sınar; ÇALIŞTIRMAZ (Actions'ta asla; T5'te sunucuda, kullanıcı onayıyla).

T4b (K‑37): `emir(..., bant=None, cloid=None)` — `bant` çağıranın IOC bandı (kapanış yeniden denemesinde %0,5 → %1 → %2), `cloid` deterministik istemci kimliği (gerçek kip: SDK `Cloid`; çift emir koruması).
Minimum emir değeri (`canli_min_nosyonel_usd`, HL: 10 $): yuvarlanmış `sz × en iyi fiyat` altındaysa emir VERİLMEZ (`min_nosyonel`); reduce‑only TAM kapanış istisnadır. Limit fiyat tick'e İÇE yuvarlanır (alış aşağı, satış yukarı); Y-7: yine de alış ≥ en iyi ask, satış ≤ en iyi bid (IOC dolabilsin; gerekirse bant bir tick aşılır).
Sanal defter derinliği: aynı coin ve yönde `canli_sanal_derinlik_sn` (5 sn) içindeki ardışık emirler, öncekilerin tükettiği seviyeleri düşerek yürür.

Birimler: `usd` kasa ölçeğinde $ (nosyonel), `sz` coin miktarı (işaretsiz; yön `yon`: `B` alış / `A` satış), `px` $/coin, `kayma_oran` = (dolum − referans) / referans, ALIŞTA pozitif = kötü (satışta işaret çevrilir).
"""
from __future__ import annotations

import math
import os
import time
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from copytrade.kurallar import load_rules

TIF_IOC = {"limit": {"tif": "Ioc"}}


@dataclass
class Dolum:
    coin: str
    yon: str                      # B | A
    usd_istenen: float
    usd_dolan: float = 0.0
    sz: float = 0.0
    px: float | None = None       # yürünen ortalama fiyat
    ucret: float = 0.0            # $ (taker)
    ucret_gercek: bool = False    # True: `ucret` HL `userFills.fee` (kesin); False: tahmin (`maliyet_taker` × nosyonel)
    referans_px: float | None = None      # en iyi karşı fiyat (emir anı)
    kayma_oran: float | None = None
    reduce_only: bool = False
    durum: str = "dolmadi"        # dolu | kismi | dolmadi | red | belirsiz (G-1: emir gönderildi, yanıt alınamadı; sonucu `orderStatus(cloid)` belirler)
    neden: str = ""
    ham: dict = field(default_factory=dict)
    defter: dict | None = None    # S-12: gerçek kipte emir anı l2Book (ilk 10 seviye, {"levels": [bids, asks]}); gerçek ↔ sanal raporu aynı defterle sanal modeli koşar

    @property
    def dolu_mu(self) -> bool:
        return self.sz > 0


class Yurutucu(Protocol):
    kip: str

    def emir(self, coin: str, yon: str, usd: float, reduce_only: bool = False, acik_sz: float | None = None, bant: float | None = None, cloid: str | None = None) -> Dolum: ...
    def hazirla(self, coin: str) -> None: ...


def _sayi(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def kayma(yon: str, referans: float | None, dolum_px: float | None) -> float | None:
    """İşaretli kayma: alışta (dolum − referans) / referans, satışta (referans − dolum) / referans → pozitif = bizim aleyhimize."""
    if not referans or not dolum_px:
        return None
    ham = (dolum_px - referans) / referans
    return ham if yon == "B" else -ham


def defter_yuru(seviyeler: list[dict], yon: str, usd: float, bant: float, acik_sz: float | None = None, tuketim: list | None = None) -> tuple[float, float, float]:
    """Karşı defteri yürür. `seviyeler`: karşı taraf (alışta ask artan, satışta bid azalan) [{px, sz}]. En iyi fiyattan ± `bant` dışındaki seviye dolmaz.
    Döner (sz, usd_dolan, referans_px = en iyi karşı fiyat). `acik_sz`: reduce‑only tavanı (coin; None = sınırsız). `tuketim` verilirse tüketilen (px, sz) çiftleri eklenir."""
    if not seviyeler:
        return 0.0, 0.0, 0.0
    en_iyi = float(seviyeler[0]["px"])
    sinir = en_iyi * (1 + bant) if yon == "B" else en_iyi * (1 - bant)
    kalan_usd = float(usd)
    sz_kalan = math.inf if acik_sz is None else max(0.0, float(acik_sz))
    toplam_sz = toplam_usd = 0.0
    for s in seviyeler:
        px, sz = float(s["px"]), float(s["sz"])
        if (yon == "B" and px > sinir + 1e-12) or (yon == "A" and px < sinir - 1e-12) or kalan_usd <= 1e-9 or sz_kalan <= 1e-15:
            break
        al = min(sz, kalan_usd / px, sz_kalan)
        toplam_sz += al
        if tuketim is not None and al > 0:
            tuketim.append((px, al))
        toplam_usd += al * px
        kalan_usd -= al * px
        sz_kalan -= al
    return toplam_sz, toplam_usd, en_iyi


class SanalYurutucu:
    """Cüzdansız yürütme: `post` = HL info (`l2Book`); defterin kendisi tüketilmez (yalnız hesap) — ama aynı coin/yönde kısa aralıktaki ardışık emirler öncekilerin seviyelerini düşer (T4b §9)."""
    kip = "sanal"

    def __init__(self, post: Callable[[dict], Any], rules: dict | None = None, saat_ms: Callable[[], int] | None = None) -> None:
        self.post = post
        self.rules = rules or load_rules()
        self.saat_ms = saat_ms or (lambda: int(time.time() * 1000))
        self._tuketim: list[tuple[int, str, str, float, float]] = []          # (ms, coin, yon, px, sz)

    def hazirla(self, coin: str) -> None:
        return None                                   # izole 3x marj hesabı defterde (hesap.py); borsa ayarı yok

    def _derinlik_dus(self, coin: str, yon: str, seviyeler: list[dict], simdi: int) -> list[dict]:
        pencere = float(self.rules.get("canli_sanal_derinlik_sn", 5)) * 1000
        self._tuketim = [t for t in self._tuketim if simdi - t[0] <= pencere]
        alinan: dict[float, float] = {}
        for _, c, y, px, sz in self._tuketim:
            if c == coin and y == yon:
                alinan[px] = alinan.get(px, 0.0) + sz
        if not alinan:
            return seviyeler
        sonuc = []
        for sv in seviyeler:
            kalan = float(sv["sz"]) - alinan.get(float(sv["px"]), 0.0)
            if kalan > 1e-12:
                sonuc.append({**sv, "sz": str(kalan)})
        return sonuc

    def emir(self, coin: str, yon: str, usd: float, reduce_only: bool = False, acik_sz: float | None = None, bant: float | None = None, cloid: str | None = None) -> Dolum:
        d = Dolum(coin, yon, float(usd), reduce_only=reduce_only)
        bant = float(self.rules["canli_ioc_bant"]) if bant is None else float(bant)
        try:
            kitap = self.post({"type": "l2Book", "coin": coin})
            bids, asks = kitap["levels"][0], kitap["levels"][1]
        except Exception as hata:                      # noqa: BLE001 - defter okunamadı: emir YOK (uydurma fiyat yok)
            d.durum, d.neden = "red", f"l2Book okunamadi: {type(hata).__name__}"
            return d
        simdi = self.saat_ms()
        seviyeler = self._derinlik_dus(coin, yon, asks if yon == "B" else bids, simdi)
        if seviyeler and not min_nosyonel_ok(float(usd) / float(seviyeler[0]["px"]), float(seviyeler[0]["px"]), reduce_only, acik_sz, float(self.rules.get("canli_min_nosyonel_usd", 10))):
            d.referans_px, d.neden = float(seviyeler[0]["px"]), "min_nosyonel"
            return d
        tuketim: list = []
        sz, dolan, referans = defter_yuru(seviyeler, yon, usd, bant, acik_sz if reduce_only else None, tuketim)
        d.referans_px = referans or None
        if sz <= 0:
            d.neden = "band_disi_ya_da_bos_defter"
            return d
        self._tuketim += [(simdi, coin, yon, px, t) for px, t in tuketim]
        d.sz, d.usd_dolan, d.px = sz, dolan, dolan / sz
        d.ucret = dolan * float(self.rules["maliyet_taker"])
        d.kayma_oran = kayma(yon, referans, d.px)
        tam_kapanis = reduce_only and acik_sz is not None and sz >= abs(float(acik_sz)) - 1e-12      # M-3: kapanış (kalan × mk × 1,05) pozisyonla kırpılır; pozisyonun tamamı kapandıysa DOLU
        d.durum = "dolu" if dolan >= usd - 1e-6 or tam_kapanis else "kismi"
        return d


def min_nosyonel_ok(sz: float, fiyat: float, reduce_only: bool, acik_sz: float | None, minimum: float) -> bool:
    """`sz × fiyat ≥ minimum` ya da reduce‑only TAM kapanış (sz ≥ açık pozisyon). HL: küçük kapanışa izin verir (reduce‑only emirlerde minimum değer aranmaz — bkz. docs/sonnet_durum_t4b.md)."""
    if reduce_only and acik_sz is not None and sz >= abs(float(acik_sz)) - 1e-12:
        return True
    return sz * fiyat >= minimum - 1e-9


class AnahtarYok(RuntimeError):
    """Gerçek kip için ortam değişkenleri eksik: motor BAŞLAMAZ."""


def tick_yuvarla(px: float, sz_decimals: int) -> float:
    """HL perp fiyat kuralı: en çok 5 anlamlı basamak ve en çok (6 − szDecimals) ondalık."""
    return round(float(f"{px:.5g}"), max(0, 6 - int(sz_decimals)))


def _izgara(px: float, sz_decimals: int, yukari: bool) -> float:
    """HL perp fiyat ızgarasına yuvarlama (`yukari`: tavana, değilse tabana). Adım = max(5 anlamlı basamak adımı, 10^−(6 − szDecimals)); tam sayı fiyat her zaman geçerli
    olduğundan 5 anlamlı basamak adımı en çok 1'dir (Y-7: 123.456 gibi ≥ 100.000 fiyatta adım 10 değil 1)."""
    x = Decimal(repr(round(float(px), 10)))              # 100,49999999999999 gibi kayan nokta artığı tick'i bir adım kaydırmasın
    adim_anlamli = min(Decimal(10) ** (x.adjusted() - 4), Decimal(1))
    adim = max(adim_anlamli, Decimal(10) ** -max(0, 6 - int(sz_decimals)))
    n = (x / adim).to_integral_value(rounding=ROUND_CEILING if yukari else ROUND_FLOOR)
    return float(n * adim)


def limit_yuvarla(px: float, sz_decimals: int, yon: str, en_iyi: float | None = None) -> float:
    """Limit fiyatı tick'e İÇE yuvarlar (alışta aşağı, satışta yukarı → bant hiç aşılmaz). Tick = max(5 anlamlı basamak adımı (≤ 1), 10^−(6 − szDecimals)).
    Y-7: `en_iyi` (en iyi karşı fiyat) verilirse IOC'nin dolabilmesi için alış limiti ≥ en iyi ask, satış limiti ≤ en iyi bid tutulur: içe yuvarlama en iyi fiyatın
    gerisine düşerse limit en iyi fiyatın ızgaradaki karşılığı olur (bant en çok bir tick aşılır; HL defter fiyatı zaten ızgaradadır)."""
    alis = yon == "B"
    limit = _izgara(px, sz_decimals, yukari=not alis)
    if en_iyi is not None and en_iyi > 0:
        if alis and limit < en_iyi:
            limit = _izgara(en_iyi, sz_decimals, yukari=True)
        elif not alis and limit > en_iyi:
            limit = _izgara(en_iyi, sz_decimals, yukari=False)
    return limit


def cloid_nesne(c: str) -> Any:
    try:
        from hyperliquid.utils.types import Cloid
        return Cloid.from_str(c)
    except ImportError:
        return c


class GercekYurutucu:
    """HL resmi SDK ile emir. `exchange`: `hyperliquid.exchange.Exchange` benzeri (`update_leverage`, `order`); `post`: info. Testte sahte nesneler verilir."""
    kip = "gercek"

    def __init__(self, exchange: Any, post: Callable[[dict], Any], rules: dict | None = None) -> None:
        self.exchange, self.post = exchange, post
        self.rules = rules or load_rules()
        self._sz_dec_dex: dict[str, dict[str, int]] = {}         # S-11: dex → {coin: szDecimals}
        self._ayarli: set[str] = set()

    def _meta_oku(self, dex: str) -> dict[str, int]:
        meta = self.post({"type": "meta", **({"dex": dex} if dex else {})})
        return {str(u["name"]): int(u["szDecimals"]) for u in meta["universe"]}

    def _sz_decimals(self, coin: str) -> int:
        """S-11: szDecimals önbelleği dex başına (ana dex ""; HIP-3 `dex:COIN` → o dex'in `meta`'sı, YALNIZ `canli_hip3_kopya` açıkken). Önbellekte olmayan coin → meta BİR KEZ yeniden okunur
        (açılıştan sonra listelenen coin yeniden başlatma beklemesin); yine yoksa açık metinli hata `bilinmeyen coin: X`."""
        dex = coin.split(":", 1)[0] if ":" in coin else ""
        if dex and not bool(self.rules.get("canli_hip3_kopya", False)):
            raise ValueError(f"bilinmeyen coin: {coin} (HIP-3 kapalı: canli_hip3_kopya=false)")
        tablo = self._sz_dec_dex.get(dex)
        if tablo is None or coin not in tablo:
            tablo = self._meta_oku(dex)                   # ilk okuma ya da bilinmeyen coin → bir kez tazele
            self._sz_dec_dex[dex] = tablo
        if coin not in tablo:
            raise ValueError(f"bilinmeyen coin: {coin}")
        return tablo[coin]

    def hazirla(self, coin: str) -> None:
        """Coin başına izole marj + `canli_marj_kaldirac`x (ilk AÇILIŞ/ARTIRMA emrinden önce, bir kez). G-4: reduce-only emirde çağrılmaz (kaldıraç reddi kapanışı engellemez)."""
        if coin in self._ayarli:
            return
        yanit = self.exchange.update_leverage(int(self.rules["canli_marj_kaldirac"]), coin, False)        # is_cross=False → izole
        if not isinstance(yanit, dict) or yanit.get("status") != "ok":
            raise RuntimeError(f"update_leverage reddedildi: {coin}")
        self._ayarli.add(coin)

    def _gercek_ucret(self, coin: str, oid: Any, cloid: str | None, baslangic_ms: int) -> float | None:
        """G7: bu emrin dolumlarının gerçek `fee` toplamı ($, HL hesabı; `userFillsByTime`, `oid` ya da `cloid` eşleşmesi). Bulunamaz / hata / ağ yok → None (çağıran tahmine düşer)."""
        adres = os.environ.get("HL_HESAP_ADRESI", "").strip()
        if not adres:
            return None
        try:
            satirlar = self.post({"type": "userFillsByTime", "user": adres, "startTime": max(0, int(baslangic_ms) - 5000)}) or []
            fee = [float(x["fee"]) for x in satirlar if x.get("coin") == coin and x.get("fee") is not None
                   and ((oid is not None and x.get("oid") == oid) or (cloid and str(x.get("cloid") or "").lower() == str(cloid).lower()))]
            return sum(fee) if fee else None
        except Exception:                              # noqa: BLE001 - ücret araması emri bozmaz
            return None

    def emir(self, coin: str, yon: str, usd: float, reduce_only: bool = False, acik_sz: float | None = None, bant: float | None = None, cloid: str | None = None) -> Dolum:
        d = Dolum(coin, yon, float(usd), reduce_only=reduce_only)
        emir_oncesi_ms = int(time.time() * 1000)
        try:
            if not reduce_only:                         # G-4: kaldıraç ayarı yalnız açılış/artırmada; reduce-only kapanış/azaltma kaldıraçtan bağımsız gider
                self.hazirla(coin)
            kitap = self.post({"type": "l2Book", "coin": coin})
            seviyeler = kitap["levels"][1 if yon == "B" else 0]
            en_iyi = float(seviyeler[0]["px"])
            d.defter = {"levels": [list(kitap["levels"][0])[:10], list(kitap["levels"][1])[:10]]}
            bant = float(self.rules["canli_ioc_bant"]) if bant is None else float(bant)
            dec = self._sz_decimals(coin)
            limit = limit_yuvarla(en_iyi * (1 + bant) if yon == "B" else en_iyi * (1 - bant), dec, yon, en_iyi)
            sz = round(float(usd) / en_iyi, dec)
            tavan_sz = round(abs(acik_sz), dec) if reduce_only and acik_sz is not None else None
            if tavan_sz is not None:
                sz = min(sz, tavan_sz)
            if sz <= 0:
                d.durum, d.neden = "red", "sz_sifir"
                return d
            d.referans_px = en_iyi
            if not min_nosyonel_ok(sz, en_iyi, reduce_only, round(abs(acik_sz), dec) if acik_sz is not None else None, float(self.rules.get("canli_min_nosyonel_usd", 10))):
                d.durum, d.neden = "red", "min_nosyonel"
                return d
        except Exception as hata:                      # noqa: BLE001 - emir ÖNCESİ (kaldıraç, defter, meta) hata: emir GİTMEDİ → red; motor çökmez
            d.durum, d.neden = "red", (str(hata)[:160] if isinstance(hata, ValueError) and str(hata).startswith("bilinmeyen coin") else f"sdk_hatasi: {type(hata).__name__}")
            d.ham = {"istisna": type(hata).__name__, "metin": str(hata)[:300]}          # G-19: hata metni kayda (red → motor `ham` yazar)
            return d
        try:
            if cloid:
                yanit = self.exchange.order(coin, yon == "B", sz, limit, TIF_IOC, reduce_only, cloid=cloid_nesne(cloid))
            else:
                yanit = self.exchange.order(coin, yon == "B", sz, limit, TIF_IOC, reduce_only)
        except Exception as hata:                      # noqa: BLE001 - G-1: emir isteği GÖNDERİLDİKTEN sonra hata (zaman aşımı, bağlantı, 5xx)
            # HL emri almış ve doldurmuş olabilir: "red" DEĞİL "belirsiz" → motor niyeti açık bırakır, `orderStatus(cloid)` ile çözer.
            # Yalnız HL'nin açıkça reddettiği istek (SDK `ClientError`, HTTP 4xx) kesin red sayılır.
            d.durum = "red" if type(hata).__name__ == "ClientError" else "belirsiz"
            d.neden = f"sdk_hatasi: {type(hata).__name__}"
            d.ham = {"istisna": type(hata).__name__, "metin": str(getattr(hata, "error_message", None) or hata)[:300]}      # G-19: HL'nin açıklaması kaybolmasın
            return d
        d.ham = yanit if isinstance(yanit, dict) else {"yanit": str(yanit)[:200]}
        if isinstance(yanit, dict) and yanit.get("status") == "err":                  # G-19: üst düzey HL hatası {"status":"err","response":"<metin>"} (ör. "Invalid nonce", agent yok)
            d.durum, d.neden = "red", f"hl_err: {str(yanit.get('response'))[:160]}"
            return d
        try:
            durum = yanit["response"]["data"]["statuses"][0]
        except (KeyError, IndexError, TypeError):
            d.durum, d.neden = "red", "yanit_bicimi"
            return d
        if "filled" in durum:
            d.sz, d.px = float(durum["filled"]["totalSz"]), float(durum["filled"]["avgPx"])
            d.usd_dolan = d.sz * d.px
            d.ucret = d.usd_dolan * float(self.rules["maliyet_taker"])             # tahmini; kesin ücret bulunursa (G7) aşağıda üzerine yazılır
            gercek = self._gercek_ucret(coin, durum["filled"].get("oid"), cloid, emir_oncesi_ms)
            if gercek is not None:
                d.ucret, d.ucret_gercek = gercek, True
            d.kayma_oran = kayma(yon, en_iyi, d.px)
            tam_kapanis = tavan_sz is not None and sz >= tavan_sz and d.sz >= tavan_sz - 0.5 * 10 ** -dec      # M-3: istek pozisyonla kırpıldı ve kırpılan miktarın tamamı doldu → TAM kapanış
            d.durum = "dolu" if d.usd_dolan >= usd * 0.999 or tam_kapanis else "kismi"
        elif "error" in durum:
            d.durum, d.neden = "red", str(durum["error"])[:160]
        else:
            d.durum, d.neden = "dolmadi", "dolmadi"                                  # IOC: resting olmamalı; yeniden denenmez
        return d


    def stop_koy(self, coin: str, long: bool, sz: float, tetik: float, cloid: str) -> tuple[Any, str, float]:
        """K-64: borsada duran felaket stopu. Reduce-only, piyasa tetikli (`tpsl: sl`): long için satış (tetik altta), short için alış (tetik üstte).
        Miktar szDecimals'e AŞAĞI, tetik ızgaraya pozisyondan UZAĞA yuvarlanır. Döner (oid | None, neden, yuvarlanmış tetik)."""
        try:
            dec = self._sz_decimals(coin)
            adim = 10 ** -dec
            sz_y = math.floor(float(sz) / adim + 1e-9) * adim
            sz_y = round(sz_y, dec)
            if sz_y <= 0:
                return None, "sz_sifir", tetik
            tetik_y = _izgara(tetik, dec, yukari=not long)
            limit = _izgara(tetik_y * (0.9 if long else 1.1), dec, yukari=not long)          # piyasa tetiğinde kayma sınırı (%10)
            tur = {"trigger": {"triggerPx": tetik_y, "isMarket": True, "tpsl": "sl"}}
            yanit = self.exchange.order(coin, not long, sz_y, limit, tur, True, cloid=cloid_nesne(cloid))
        except Exception as hata:                      # noqa: BLE001 - stop hatası motoru durdurmaz; motor alarm verir ve sonraki dakika yeniden dener
            return None, f"sdk_hatasi: {type(hata).__name__}: {str(hata)[:120]}", tetik
        if not isinstance(yanit, dict) or yanit.get("status") != "ok":
            return None, f"hl_err: {str((yanit or {}).get('response') if isinstance(yanit, dict) else yanit)[:160]}", tetik_y
        try:
            durum = yanit["response"]["data"]["statuses"][0]
        except (KeyError, IndexError, TypeError):
            return None, "yanit_bicimi", tetik_y
        if isinstance(durum, dict) and "error" in durum:
            return None, str(durum["error"])[:160], tetik_y
        for v in (durum.values() if isinstance(durum, dict) else []):
            if isinstance(v, dict) and v.get("oid") is not None:
                return v["oid"], "", tetik_y
        return None, f"oid_yok: {str(durum)[:120]}", tetik_y

    def stop_iptal(self, coin: str, oid: Any) -> bool:
        """K-64: stop emrini iptal eder. Başarı: True. Hata / ret: False (motor sonraki eşitlemede yeniden dener)."""
        try:
            yanit = self.exchange.cancel(coin, int(oid))
            durum = yanit["response"]["data"]["statuses"][0]
            return yanit.get("status") == "ok" and durum == "success"
        except Exception:                              # noqa: BLE001
            return False


def gercek_yurutucu_olustur(post: Callable[[dict], Any], rules: dict | None = None, ortam: dict | None = None) -> GercekYurutucu:
    """Anahtarları ortamdan okur (`HL_API_CUZDAN_ANAHTARI` = para çekme yetkisiz API cüzdanı, `HL_HESAP_ADRESI` = ana hesap, açık). Biri yoksa `AnahtarYok`. SDK içe aktarması burada (tembel):
    testte kullanılmaz. ANAHTAR ASLA günlüğe/ayrıntıya yazılmaz."""
    ortam = os.environ if ortam is None else ortam
    anahtar, hesap = (ortam.get("HL_API_CUZDAN_ANAHTARI") or "").strip(), (ortam.get("HL_HESAP_ADRESI") or "").strip()
    if not anahtar or not hesap:
        raise AnahtarYok("HL_API_CUZDAN_ANAHTARI ve HL_HESAP_ADRESI gerekli (gercek kip)")
    try:
        from eth_account import Account
        from hyperliquid.exchange import Exchange
        from hyperliquid.utils import constants
    except ImportError as hata:
        raise RuntimeError("hyperliquid-python-sdk kurulmalı: pip install -r requirements-canli.txt") from hata
    rules = rules or load_rules()
    zaman_asimi = float(rules.get("canli_emir_zaman_asimi_sn", 10))         # G-12a: SDK varsayılanı None (süresiz bekler, motor kilidi tutulur); `API.post` → `session.post(..., timeout=)`
    ek: dict[str, Any] = {}
    if bool(rules.get("canli_hip3_kopya", False)):                       # S-11 / K-42: HIP-3 (`dex:COIN`) SDK varlık tablosu YALNIZ HIP-3 kopyası açıkken (okunamazsa motor başlamaz)
        from copytrade.izleme_liste import perp_dex_names
        ek["perp_dexs"] = ["", *perp_dex_names(post({"type": "perpDexs"}))]
    url = constants.TESTNET_API_URL if (ortam.get("HL_AG") or "").strip().lower() == "testnet" else constants.MAINNET_API_URL      # K-64: yalnız deneme betiği testnet kullanır
    return GercekYurutucu(Exchange(Account.from_key(anahtar), url, account_address=hesap, timeout=zaman_asimi, **ek), post, rules)
