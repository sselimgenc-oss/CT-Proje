"""Canlı motor (T4; K‑29): tek süreç, iki kip (sanal / gerçek), TEK kod yolu. docs/GOREV_T4_CANLI_MOTOR.md, docs/RADAR_V1.md §5–§6.

Akış: `dinleyici.py` WebSocket (trades + userFills; İlk 11'in sahadaki adresleri) → tekilleştirilmiş dolum (`Olay`) → trader pozisyon izleyicisi → `boyut.hedef_emir` (tek boyutlandırma) → risk (`risk.py`)
→ yürütücü (`yurutucu.py`: sanal l2Book yürüyüşü / gerçek HL SDK) → hesap (`hesap.py`) → kayıt JSONL + Telegram. Saha kararları `kadro.py` (kadro.json, her 5 dk).

Kip güvencesi: varsayılan SANAL. `gercek` yalnız `kurallar.yaml canli_kip: gercek` + `HL_API_CUZDAN_ANAHTARI`/`HL_HESAP_ADRESI` ile ve ASLA GitHub Actions'ta (`GITHUB_ACTIONS=true` → ret).
Kasa `canli_kasa_usd` (kullanıcı ayarı, üst sınır 1.000 $ — AGENTS.md): sınır aşılırsa yeni açılış yok + alarm. Funding hesaba girmez (v1 kararı, T2 ile aynı).
`DUR` dosyası varken motor başlamaz (elle silinmeden yeniden açılmaz).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from copytrade import boyut
from copytrade.canli import telegram as tg
from copytrade.canli.hesap import Hesap
from copytrade.canli.kadro import Karar, Saha, kadro_taze_mi
from copytrade.canli.mutabakat import poz_farki, sanal_tutarlilik
from copytrade.canli.risk import Risk, gun
from copytrade.canli.yurutucu import AnahtarYok, Dolum, SanalYurutucu, Yurutucu, gercek_yurutucu_olustur
from copytrade.dinleyici import Ayar, Dinleyici, Izlenen, Olay, clearinghouse_ayristir, clearinghouse_pozisyonlari, clearinghouse_yuk, coin_listesi, rest_dolumlar, rest_post_fabrikasi, ws_baglan
from copytrade.hl_ortak import spot_usdc
from copytrade.izleme_liste import perp_dex_names
from copytrade.kurallar import load_rules
from copytrade.tarama import KAPI_YENIDEN_BEKLEME, PublicClient, RateLimiter

EPS = 1e-12
DAKIKA = 60_000


AGIRLIK = {"allMids": 2, "l2Book": 2, "clearinghouseState": 2, "perpDexs": 2, "meta": 20, "userFillsByTime": 20}          # HL info istek ağırlıkları (belge); bilinmeyen 20


class GuvenliLimiter(RateLimiter):
    """Birden çok iş parçacığı (olay işleme, dakikalık bakım, dinleyici REST) aynı hız sınırını paylaşır: `acquire` kilitli (sıraya girer)."""

    def __init__(self, *a: Any, **k: Any) -> None:
        super().__init__(*a, **k)
        self._kilit = threading.Lock()

    def acquire(self, weight: int) -> None:
        with self._kilit:
            super().acquire(weight)


def rest_post_olustur(rules: dict, istemci: PublicClient | None = None) -> Callable[[dict], Any]:
    """Motorun TÜM REST istekleri (kural 7: `tarama.PublicClient`): ortak ağırlık sınırı `canli_api_agirlik_dk`, 429 (5 yeniden deneme, `Retry-After`) ve 5xx / ağ hatasında 3 yeniden deneme.
    Duman testinde (gerçek HL) açılışta ardışık `clearinghouseState` okumaları HTTP 429 aldı → bu sınırlayıcı eklendi."""
    c = istemci or PublicClient(limiter=GuvenliLimiter(limit=int(rules["canli_api_agirlik_dk"])), yeniden_bekleme=KAPI_YENIDEN_BEKLEME)

    def post(yuk: dict) -> Any:
        return c.info(yuk, weight=AGIRLIK.get(str(yuk.get("type")), 20))
    post.stats = getattr(c, "stats", None)                 # type: ignore[attr-defined] — rapor için istek / 429 sayaçları (T6 §3)
    return post


def hesap_degeri_oku(post: Callable[[dict], Any], adres: str, dexler: list[str]) -> float:
    """Hesap değeri ($) = TÜM perp dex'lerin `marginSummary.accountValue` toplamı + spot USDC (`hl_ortak.spot_usdc`; K‑35 tek payda). Radar lider tablosu `accountValue` ile aynı tanım. Herhangi bir okuma
    başarısızsa istisna (kısmi toplam dönmez: oran paydası eksik olursa emirler şişer)."""
    toplam = 0.0
    for dex in ["", *dexler]:
        toplam += float(post(clearinghouse_yuk(adres, dex))["marginSummary"]["accountValue"])
    return toplam + spot_usdc(type("_Istemci", (), {"info": staticmethod(lambda yuk, weight=2: post(yuk))})(), adres)


def etkin_kasa(rules: dict, kip: str, post: Callable[[dict], Any], ortam: dict | None = None) -> tuple[float, float | None]:
    """Kullanılan kasa: sanal kip `canli_kasa_usd`; GERÇEK kip min(`canli_kasa_usd`, HL hesap değeri) (K‑35; hesapta daha fazla olsa da ayarın üstü kullanılmaz). Döner (etkin kasa, HL hesap değeri | None)."""
    ortam = os.environ if ortam is None else ortam
    kasa = float(rules["canli_kasa_usd"])
    if kip != "gercek":
        return kasa, None
    try:
        dexler = perp_dex_names(post({"type": "perpDexs"}))
        hl = hesap_degeri_oku(post, ortam["HL_HESAP_ADRESI"], dexler)
    except Exception as hata:                              # noqa: BLE001
        raise KipHatasi(f"HL hesap değeri okunamadı ({type(hata).__name__}): gerçek kipte kasa belirlenemez") from hata
    return min(kasa, hl), hl


class KipHatasi(RuntimeError):
    """Kip kuralı ihlali (gerçek kip Actions'ta / ayar yok): motor BAŞLAMAZ."""


def kip_belirle(rules: dict, istenen: str | None = None, ortam: dict | None = None) -> str:
    """`sanal` (varsayılan) | `gercek`. `gercek`: kurallar.yaml `canli_kip: gercek` + anahtarlar + GitHub Actions DEĞİL. Aksi halde KipHatasi (sessizce sanala DÜŞMEZ: yanlış beklenti)."""
    ortam = os.environ if ortam is None else ortam
    kip = (istenen or str(rules.get("canli_kip", "sanal"))).strip().lower()
    if kip not in ("sanal", "gercek"):
        raise KipHatasi(f"bilinmeyen kip: {kip}")
    if kip == "gercek":
        if ortam.get("GITHUB_ACTIONS") == "true":
            raise KipHatasi("gercek kip GitHub Actions'ta çalışmaz")
        if str(rules.get("canli_kip", "sanal")) != "gercek":
            raise KipHatasi("gercek kip için kurallar.yaml canli_kip: gercek gerekli")
        if not (ortam.get("HL_API_CUZDAN_ANAHTARI") and ortam.get("HL_HESAP_ADRESI")):
            raise AnahtarYok("HL_API_CUZDAN_ANAHTARI ve HL_HESAP_ADRESI gerekli")
    return kip


def eylem_belirle(once: float, sonra: float, biz_sz: float) -> list[str]:
    """Trader dolumu (işaretli pozisyon önce → sonra) ve bizim pozisyonumuz → yürütülecek eylem sırası (`boyut.hedef_emir` eylemleri): kapat | azalt | ac | artir.
    Ters dönüş = [kapat (varsa), ac]. Bizde pozisyon yokken trader azaltıyorsa eylem yok."""
    if abs(sonra) < EPS:
        return ["kapat"] if abs(biz_sz) > EPS else []
    if once * sonra < 0:
        return (["kapat"] if abs(biz_sz) > EPS else []) + ["ac"]
    if abs(sonra) > abs(once) + EPS:
        return ["ac"] if abs(biz_sz) < EPS else ["artir"]
    return ["azalt"] if abs(biz_sz) > EPS else []


@dataclass
class Sonuc:
    adres: str
    coin: str
    eylem: str
    karar: str                 # emir | atlandi | engel | red
    neden: str = ""
    dolum: Dolum | None = None


class Kayit:
    """Günlük JSONL (`kayit/<tarih>.jsonl`): her olay tek satır; yazma hatası motoru durdurmaz."""

    def __init__(self, dizin: Path, saat_ms: Callable[[], int]) -> None:
        self.dizin, self.saat_ms = dizin, saat_ms
        self.sayac: dict[str, int] = {}

    def __call__(self, olay: dict) -> None:
        ms = self.saat_ms()
        olay = {"zaman_ms": ms, **olay}
        self.sayac[olay.get("olay", "?")] = self.sayac.get(olay.get("olay", "?"), 0) + 1
        try:
            self.dizin.mkdir(parents=True, exist_ok=True)
            with (self.dizin / f"{gun(ms)}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(olay, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
        except OSError:
            self.sayac["yazma_hatasi"] = self.sayac.get("yazma_hatasi", 0) + 1


def _yaz(yol: Path, veri: Any) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(yol.suffix + ".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    gecici.replace(yol)


def _oku(yol: Path) -> dict | None:
    try:
        return json.loads(yol.read_text(encoding="utf-8")) if yol.is_file() else None
    except (OSError, ValueError):
        return None


class Motor:
    """Olay işleme + periyodik görevler. `post`: HL info (REST); `yurutucu`: emir arka ucu; `kadro_oku()`: kadro.json sözlüğü ya da None; `saat_ms`: enjekte (testte sahte)."""

    def __init__(self, rules: dict, yurutucu: Yurutucu, post: Callable[[dict], Any], telegram: tg.Telegram, durum_dizin: Path, kayit_dizin: Path,
                 kadro_oku: Callable[[], dict | None], saat_ms: Callable[[], int] | None = None, vardiya_id: str = "yerel") -> None:
        self.rules, self.yurutucu, self.post, self.tg = rules, yurutucu, post, telegram
        self.durum_dizin, self.kadro_oku = durum_dizin, kadro_oku
        self.saat_ms = saat_ms or (lambda: int(time.time() * 1000))
        self.kayit = Kayit(kayit_dizin, self.saat_ms)
        self.tg.kayit = self.kayit
        self.kip = yurutucu.kip
        self.vardiya_id = vardiya_id
        self.kasa = float(rules["canli_kasa_usd"])
        self.dur_dosyasi = durum_dizin / "DUR"
        m = _oku(durum_dizin / "motor.json") or {}
        h = _oku(durum_dizin / "hesap.json")
        self.hesap = Hesap.from_json(h) if h else Hesap(self.kasa, float(rules["canli_marj_kaldirac"]))
        self.hesap.kasa_usd = self.kasa                          # kasa ayarı/etkin kasa değişmiş olabilir (gerçek kip: min(ayar, HL değeri)); pozisyon/K‑Z kaydı KORUNUR
        self.saha = Saha(rules, self.kasa, _oku(durum_dizin / "saha.json"))
        self.risk = Risk(rules, self.kasa, _oku(durum_dizin / "risk.json"))
        self.islenen: list[str] = list(m.get("islenen", []))
        self._islenen_set = set(self.islenen)
        self.poz_tr: dict[str, dict[str, float]] = {a: dict(c) for a, c in (m.get("poz_tr") or {}).items()}       # trader işaretli pozisyonları (coin birimi)
        self.hesap_tr: dict[str, dict] = dict(m.get("hesap_tr") or {})                                              # adres -> {deger, ms}
        self.son_olay_ms: int = int(m.get("son_olay_ms", 0))
        self.baslama_ms: int = self.saat_ms()
        self.marks: dict[str, float] = {}
        self.mark_ms: dict[str, int] = {}
        self.sayac = {"emir": 0, "dolu": 0, "kismi": 0, "dolmadi": 0, "red": 0, "atlandi": 0, "engel": 0, "gec_goruldu": 0}
        self.kayma_trader: list[float] = []
        self.kayma_ref: list[float] = []
        self.dur_istendi = False
        self._son: dict[str, float] = {}
        self._ozet_gunu: str | None = m.get("ozet_gunu")
        self.kor_kirpildi: list[dict] = []
        self.neden_say: dict[str, int] = {}          # boyut / risk nedenleri sayacı (slot_tavani, marj_yok, coin_tavani …)
        self._lock = threading.RLock()            # olay işleme (tüketici iş parçacığı) ile dakikalık bakım aynı durumu değiştirir: tek seferde biri

    # ------------------------------------------------------------------ kilit (vardiya devri: çift emir yok)
    def kilit_al(self) -> None:
        """`durum/kilit.json`: başka bir vardiya `canli_kilit_dk` içinde nabız attıysa BAŞLAMAZ (çift emir yok). Temiz kapanışta bırakılır; çökme/zaman aşımında nabız eskir ve sonraki vardiya devralır."""
        k = _oku(self.durum_dizin / "kilit.json") or {}
        if k.get("vardiya") not in (None, self.vardiya_id) and not k.get("birakildi") and self.saat_ms() - int(k.get("nabiz_ms", 0)) < float(self.rules["canli_kilit_dk"]) * DAKIKA:
            raise KipHatasi(f"başka vardiya aktif ({k.get('vardiya')}); kilit {self.rules['canli_kilit_dk']} dk içinde nabız attı")
        self.kilit_yaz(False)

    def kilit_yaz(self, birakildi: bool) -> None:
        _yaz(self.durum_dizin / "kilit.json", {"vardiya": self.vardiya_id, "nabiz_ms": self.saat_ms(), "birakildi": birakildi})

    # ------------------------------------------------------------------ kalıcılık
    def durum_yaz(self) -> None:
        d = self.durum_dizin
        if not getattr(self, "_kilit_birakildi", False):
            self.kilit_yaz(False)
        _yaz(d / "hesap.json", self.hesap.to_json())
        _yaz(d / "saha.json", self.saha.to_json())
        _yaz(d / "risk.json", self.risk.to_json())
        _yaz(d / "motor.json", {"islenen": self.islenen[-int(self.rules["canli_islenen_sakla"]):], "poz_tr": self.poz_tr, "hesap_tr": self.hesap_tr, "son_olay_ms": self.son_olay_ms,
                                "ozet_gunu": self._ozet_gunu, "kip": self.kip, "kasa_usd": self.kasa, "vardiya": self.vardiya_id, "yazildi_ms": self.saat_ms()})

    def _gorulduysa_isaretle(self, kimlik: str) -> bool:
        """Dolum kimliği daha önce işlendiyse True (çift emir yok: yeniden başlatmada da). Kimliksiz (dolgu) olaylar zaten dinleyicide tekilleştirilir."""
        if not kimlik:
            return False
        if kimlik in self._islenen_set:
            return True
        self._islenen_set.add(kimlik)
        self.islenen.append(kimlik)
        if len(self.islenen) > 2 * int(self.rules["canli_islenen_sakla"]):
            self.islenen = self.islenen[-int(self.rules["canli_islenen_sakla"]):]
            self._islenen_set = set(self.islenen)
        return False

    # ------------------------------------------------------------------ yardımcılar
    def mark(self, coin: str, yedek: float | None = None) -> float | None:
        return self.marks.get(coin) or yedek

    def trader_hesap_usd(self, adres: str, simdi_ms: int, zorla: bool = False) -> float | None:
        """Trader hesap değeri (oran paydası, K‑35): tüm perp dex `accountValue` toplamı + spot USDC (`hesap_degeri_oku`). Önbellekteki değer kullanılır (yenileme `dakika()` içinde kilit dışında,
        `canli_hesap_okuma_sn`); önbellek yoksa ya da `zorla` ise burada okunur. Okunamazsa önceki değer; hiç yoksa None (açılış atlanır)."""
        c = self.hesap_tr.get(adres)
        if c and not zorla:
            return float(c["deger"])
        try:
            deger = hesap_degeri_oku(self.post, adres, self._dexler())
            self.hesap_tr[adres] = {"deger": deger, "ms": simdi_ms}
            return deger
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "hesap_okuma_hata", "adres": adres, "tur": type(hata).__name__})
            return float(c["deger"]) if c else None

    def hesap_oku(self) -> dict[str, float]:
        """Saha + inen adreslerin hesap değerleri (REST; kilitsiz). Okunamayan adres atlanır (önceki önbellek kalır)."""
        sonuc: dict[str, float] = {}
        for adres in [*self.saha.uyeler, *self.saha.inen]:
            try:
                sonuc[adres] = hesap_degeri_oku(self.post, adres, self._dexler())
            except Exception as hata:                      # noqa: BLE001
                self.kayit({"olay": "hesap_okuma_hata", "adres": adres, "tur": type(hata).__name__})
        return sonuc

    def hesap_uygula(self, degerler: dict[str, float], simdi: int) -> None:
        for adres, d in degerler.items():
            self.hesap_tr[adres] = {"deger": d, "ms": simdi}

    def trader_pozlari_oku(self, adres: str, dexler: list[str] | None = None) -> bool:
        try:
            self.poz_tr[adres] = clearinghouse_pozisyonlari(self.post, adres, dexler if dexler is not None else self._dexler())
            return True
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "poz_okuma_hata", "adres": adres, "tur": type(hata).__name__})
            return False

    def _dexler(self) -> list[str]:
        if not hasattr(self, "_dex_adlari"):
            try:
                self._dex_adlari = perp_dex_names(self.post({"type": "perpDexs"}))
            except Exception:                              # noqa: BLE001
                self._dex_adlari = []
        return self._dex_adlari

    # ------------------------------------------------------------------ olay işleme (çekirdek)
    def olay_isle(self, o: Olay, canli: bool = True) -> list[Sonuc]:
        with self._lock:
            return self._olay_isle(o, canli)

    def _olay_isle(self, o: Olay, canli: bool = True) -> list[Sonuc]:
        """Tekilleştirilmiş trader dolumu → emir(ler). `canli=False` (snapshot / abonelik öncesi): yalnız trader pozisyon izleyicisi güncellenir. SENKRON (ağ I/O içerir); motor tek tüketiciyle sırayla çağırır."""
        adres = o.adres
        sonuclar: list[Sonuc] = []
        if not adres or not o.coin or o.sz is None or o.px is None or o.yon not in ("B", "A"):
            return sonuclar
        if self._gorulduysa_isaretle(o.kimlik):
            return sonuclar
        simdi = self.saat_ms()
        once = o.bas_poz if o.bas_poz is not None else self.poz_tr.get(adres, {}).get(o.coin, 0.0)
        sonra = once + (o.sz if o.yon == "B" else -o.sz)
        self.poz_tr.setdefault(adres, {})[o.coin] = 0.0 if abs(sonra) < 1e-9 else sonra
        if abs(sonra) < 1e-9:
            self.poz_tr[adres].pop(o.coin, None)
        self.son_olay_ms = max(self.son_olay_ms, o.zaman_ms)
        if adres in self.saha.uyeler:
            self.saha.islem_gordu(adres, o.zaman_ms)
        if not canli or (adres not in self.saha.uyeler and adres not in self.saha.inen):
            return sonuclar
        gec = o.kaynak in ("dolgu", "rest") or simdi - o.zaman_ms > float(self.rules["canli_olay_stale_sn"]) * 1000
        if simdi - o.zaman_ms > float(self.rules["canli_kacan_pencere_dk"]) * DAKIKA:        # çok eski kaçan dolum: yalnız izleyici (emir yok)
            self.kayit({"olay": "eski_dolum_atlandi", "adres": adres, "coin": o.coin, "yas_dk": (simdi - o.zaman_ms) / DAKIKA})
            return sonuclar
        if gec:
            self.sayac["gec_goruldu"] += 1
        biz_sz = self.hesap.sz(adres, o.coin)
        for eylem in eylem_belirle(once, sonra, biz_sz):
            s = self._emir_isle(o, adres, eylem, once, sonra, biz_sz, simdi, gec)
            sonuclar.append(s)
            biz_sz = self.hesap.sz(adres, o.coin)
            once = 0.0 if eylem == "kapat" and once * sonra < 0 else once          # ters dönüşte açılış parçası sıfırdan
        return sonuclar

    def _emir_isle(self, o: Olay, adres: str, eylem: str, once: float, sonra: float, biz_sz: float, simdi: int, gec: bool) -> Sonuc:
        acilis = eylem in ("ac", "artir")
        inen = adres in self.saha.inen and adres not in self.saha.uyeler
        if acilis and inen:
            return self._atla(o, adres, eylem, "engel", "inen_trader")
        yeni_coin = eylem == "ac" and abs(biz_sz) < EPS            # bizim için taze pozisyon (patlama freni sayacı)
        if acilis:
            izin, neden = self.risk.acilis_izni(adres, o.coin, yeni_coin, simdi)
            if not izin:
                return self._atla(o, adres, eylem, "engel", neden)
        slot = self.hesap.slot_bas.get(adres, self.saha.slot)
        mk = self.mark(o.coin, o.px)
        biz_usd = abs(biz_sz) * (mk or o.px)
        hesap_usd = self.trader_hesap_usd(adres, simdi) if eylem in ("ac", "artir") else 0.0          # K‑36: artırma da hedef tabanlı → trader hesap paydası gerekir
        if eylem in ("ac", "artir") and not hesap_usd:
            return self._atla(o, adres, eylem, "atlandi", "trader_hesap_yok")
        trader_once, trader_sonra = (0.0, sonra) if eylem == "ac" else ((once, 0.0) if eylem == "kapat" else (once, sonra))
        slot_toplam = sum(abs(p.sz) * (self.mark(c, p.giris) or p.giris) for c, p in self.hesap.poz.get(adres, {}).items())       # trader'ın TÜM coinlerdeki kopya nosyoneli (K‑35)
        emir_usd, neden = boyut.hedef_emir(eylem, trader_once, trader_sonra, hesap_usd or 0.0, biz_usd, slot, o.px, self.rules, slot_toplam)
        if emir_usd <= 0:
            return self._atla(o, adres, eylem, "atlandi", neden)
        if acilis:
            emir_usd, kn = self.risk.coin_tavani(emir_usd, self.hesap.brut_coin(o.coin, self.marks))
            if emir_usd <= 0:
                return self._atla(o, adres, eylem, "engel", kn)
            neden = kn or neden
            emir_usd, mn = self.risk.marj_kirp(emir_usd, self.hesap.marj_toplam(), self.ozsermaye())                      # K‑35 toplam marj tavanı
            if emir_usd <= 0:
                return self._atla(o, adres, eylem, "engel", mn)
            neden = mn or neden
        yon = ("B" if sonra > 0 else "A") if acilis else ("A" if biz_sz > 0 else "B")
        return self._yurut(o, adres, eylem, yon, emir_usd, not acilis, abs(biz_sz) if not acilis else None, neden, gec, simdi)

    def _say_neden(self, neden: str) -> None:
        if neden and neden not in ("tamam", "tam_kapanis"):
            self.neden_say[neden] = self.neden_say.get(neden, 0) + 1

    def _atla(self, o: Olay, adres: str, eylem: str, karar: str, neden: str) -> Sonuc:
        self.sayac[karar] += 1
        self._say_neden(neden)
        self.kayit({"olay": "emir_yok", "adres": adres, "coin": o.coin, "eylem": eylem, "karar": karar, "neden": neden, "trader_dolum_ms": o.zaman_ms, "gorme_ms": o.alma_ms})
        return Sonuc(adres, o.coin, eylem, karar, neden)

    def _yurut(self, o: Olay, adres: str, eylem: str, yon: str, usd: float, reduce_only: bool, acik_sz: float | None, neden: str, gec: bool, simdi: int) -> Sonuc:
        self._say_neden(neden)
        emir_ms = self.saat_ms()
        d = self.yurutucu.emir(o.coin, yon, usd, reduce_only, acik_sz)
        dolum_ms = self.saat_ms()
        self.sayac["emir"] += 1
        self.sayac[d.durum if d.durum in self.sayac else "red"] += 1
        kayma_trader = None
        if d.px and o.px:
            ham = (d.px - o.px) / o.px
            kayma_trader = ham if yon == "B" else -ham
        if d.dolu_mu:
            try:
                self.hesap.uygula(adres, o.coin, yon, d.sz, d.px, d.ucret, dolum_ms)
            except ValueError as hata:                      # defter reddi: kayda geçer, motor çökmez
                self.kayit({"olay": "defter_hata", "adres": adres, "coin": o.coin, "hata": str(hata)[:120]})
            if kayma_trader is not None:
                self.kayma_trader.append(kayma_trader)
            if d.kayma_oran is not None:
                self.kayma_ref.append(d.kayma_oran)
        self.kayit({"olay": "emir", "kip": self.kip, "adres": adres, "coin": o.coin, "eylem": eylem, "yon": yon, "usd_istenen": usd, "usd_dolan": d.usd_dolan, "sz": d.sz,
                    "reduce_only": reduce_only, "durum": d.durum, "red_neden": d.neden, "boyut_neden": neden, "trader_px": o.px, "trader_dolum_ms": o.zaman_ms, "gorme_ms": o.alma_ms,
                    "emir_ms": emir_ms, "dolum_ms": dolum_ms, "referans_px": d.referans_px, "dolum_px": d.px, "kayma_ref": d.kayma_oran, "kayma_trader": kayma_trader, "ucret": d.ucret,
                    "gec_goruldu": gec, "kaynak": o.kaynak})
        self.tg.gonder(tg.msg_emir(adres, o.coin, yon, d.usd_dolan or usd, d.px, kayma_trader, d.durum, self.kip))
        return Sonuc(adres, o.coin, eylem, "emir" if d.dolu_mu else "red", d.neden or neden, d)

    # ------------------------------------------------------------------ saha kararlarının uygulanması
    def karar_uygula(self, kararlar: list[Karar], simdi: int) -> None:
        for k in kararlar:
            if k.tur == "giris":
                self.hesap.slot_ac(k.adres, self.saha.slot)
                self.trader_pozlari_oku(k.adres)
                self.trader_hesap_usd(k.adres, simdi, zorla=True)
                self.kayit({"olay": "saha_giris", "adres": k.adres, "neden": k.neden, "yerine": k.yerine, "slot_usd": self.saha.slot})
                self.tg.gonder(tg.msg_saha("giriş", k.adres, k.neden + (f" (yerine {tg.kisa(k.yerine)})" if k.yerine else "")))
            elif k.tur == "dus":
                self.kayit({"olay": "saha_dus", "adres": k.adres, "neden": k.neden, "sonuc": k.sonuc})
                self.tg.gonder(tg.msg_saha("çıkış", k.adres, f"{k.neden}{' (sonuçla, 14 gün bekleme)' if k.sonuc else ' (sonuç dışı)'}"))
            elif k.tur == "inen_kapat":
                self._adres_kapat(k.adres, "inen_24sa", simdi)
                self.hesap.slot_kapat(k.adres)
            elif k.tur == "giris_atlandi":
                self.kor_kirpildi.append({"adres": k.adres, "uyeler": k.kor_kirpildi})
                self.kayit({"olay": "kor_kirpildi", "adres": k.adres, "uyeler": k.kor_kirpildi})

    def _adres_kapat(self, adres: str, neden: str, simdi: int) -> int:
        """Adresin tüm açık kopya pozisyonlarını reduce‑only kapatır. Döner: kapatılan coin sayısı."""
        sayi = 0
        for coin, p in list(self.hesap.poz.get(adres, {}).items()):
            mk = self.mark(coin, p.giris) or p.giris
            fake = Olay("", adres, adres, simdi, simdi, "kapat", False, "", coin, mk, abs(p.sz), "A" if p.sz > 0 else "B", None)
            self._yurut(fake, adres, "kapat", "A" if p.sz > 0 else "B", abs(p.sz) * mk * 1.0001, True, abs(p.sz), neden, False, simdi)
            sayi += 1
        return sayi

    def dur_tetikle(self, neden: str) -> None:
        """Tüm pozisyonları reduce‑only kapat, `DUR` yaz, alarm; motor döngüsü biter (elle silinmeden yeniden açılmaz)."""
        simdi = self.saat_ms()
        self.risk.dur_ver(neden)
        self.dur_istendi = True
        try:
            self.dur_dosyasi.parent.mkdir(parents=True, exist_ok=True)
            self.dur_dosyasi.write_text(json.dumps({"neden": neden, "ms": simdi}) + "\n", encoding="utf-8")
        except OSError:
            pass
        kapatilan = sum(self._adres_kapat(a, f"dur:{neden}", simdi) for a in list(self.hesap.poz))
        self.kayit({"olay": "dur", "neden": neden, "kapatilan": kapatilan})
        self.tg.gonder(f"DUR: {neden}. {kapatilan} pozisyon reduce-only kapatıldı; motor durdu. Elle `durum/DUR` silinmeden yeniden açılmaz.")
        self.durum_yaz()

    # ------------------------------------------------------------------ periyodik görevler
    def mids_al(self) -> dict[str, float] | None:
        """Ana dex + her HIP‑3 dex `allMids` (ağ; kilitsiz çağrılır). Hata: None (önceki markalar kalır, `mark_eski` mutabakatı yakalar)."""
        sonuc: dict[str, float] = {}
        try:
            for dex in ["", *self._dexler()]:
                mids = self.post({"type": "allMids", **({"dex": dex} if dex else {})})
                for coin, v in mids.items():
                    try:
                        x = float(v)
                    except (TypeError, ValueError):
                        continue
                    if x > 0:
                        sonuc[coin] = x
            return sonuc
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "mark_okuma_hata", "tur": type(hata).__name__})
            return sonuc or None

    def mids_uygula(self, mids: dict[str, float] | None, simdi: int) -> None:
        for coin, x in (mids or {}).items():
            self.marks[coin], self.mark_ms[coin] = x, simdi

    def piyasa_oku(self, simdi: int) -> None:
        self.mids_uygula(self.mids_al(), simdi)

    def senkron_oku(self) -> dict[str, dict[str, float]]:
        """Saha + inen adreslerin gerçek açık pozisyonları (REST; kilitsiz). Okunamayan adres atlanır."""
        sonuc: dict[str, dict[str, float]] = {}
        for adres in [*self.saha.uyeler, *self.saha.inen]:
            try:
                sonuc[adres] = clearinghouse_pozisyonlari(self.post, adres, self._dexler())
            except Exception as hata:                      # noqa: BLE001
                self.kayit({"olay": "poz_okuma_hata", "adres": adres, "tur": type(hata).__name__})
        return sonuc

    def senkron_uygula(self, okunan: dict[str, dict[str, float]]) -> int:
        """Trader pozisyon izleyicisini REST gerçeğine eşitler (WS kaçırması / kayma düzeltme); fark `poz_senkron` olarak kaydedilir. Döner: düzeltilen adres sayısı."""
        duzeltilen = 0
        for adres, gercek in okunan.items():
            izlenen = self.poz_tr.get(adres, {})
            fark = {c: (izlenen.get(c, 0.0), gercek.get(c, 0.0)) for c in {*izlenen, *gercek} if abs(izlenen.get(c, 0.0) - gercek.get(c, 0.0)) > 1e-9 * max(1.0, abs(gercek.get(c, 0.0)))}
            if fark:
                self.kayit({"olay": "poz_senkron", "adres": adres, "fark": {c: list(v) for c, v in list(fark.items())[:10]}})
                duzeltilen += 1
            self.poz_tr[adres] = dict(gercek)
        return duzeltilen

    def ozsermaye(self) -> float:
        return self.hesap.ozsermaye(self.marks)

    def dakika(self) -> None:
        """Dakikalık bakım: mark, tasfiye (sanal), özsermaye riski, anlık saha kuralları, inen kapama, mutabakat, kadro, trader pozisyon senkronu, Telegram komutları, günlük özet.
        Ağ okumaları (allMids, kadro, pozisyon) KİLİT DIŞINDA yapılır (olay işleme gecikmesin); durum değişimi kilit altında. Bir adımın hatası diğerlerini atlatmaz."""
        simdi = self.saat_ms()
        mids = self.mids_al()
        kadro = self._kadro_al(simdi)
        yenile = self._aralik_mi("senkron", simdi, float(self.rules["canli_hesap_okuma_sn"]))
        senkron = self.senkron_oku() if yenile else None
        hesaplar = self.hesap_oku() if yenile else {}
        komutlar = self.tg.komutlari_al()                      # ağ: kilitsiz
        with self._lock:
            self.mids_uygula(mids, simdi)
            adimlar: list[tuple[str, Callable[[], None]]] = [
                ("tasfiye", lambda: self._tasfiye(simdi)), ("risk", lambda: self._risk(simdi)), ("anlik_saha", lambda: self._anlik(simdi)),
                ("inen", lambda: self.karar_uygula(self.saha.inenleri_kapat(simdi), simdi)), ("mutabakat", lambda: self._mutabakat(simdi)),
                ("kadro", lambda: self._kadro_uygula(kadro, simdi)), ("senkron", lambda: (self.senkron_uygula(senkron), self.hesap_uygula(hesaplar, simdi)) if senkron is not None else None),
                ("telegram", lambda: self._komutlar(komutlar)), ("ozet", lambda: self._gunluk_ozet(simdi)),
            ]
            for ad, f in adimlar:
                try:
                    f()
                except Exception as hata:                  # noqa: BLE001
                    self.kayit({"olay": "adim_hata", "adim": ad, "tur": type(hata).__name__, "mesaj": str(hata)[:160]})
            self.durum_yaz()

    def _aralik_mi(self, ad: str, simdi: int, sn: float) -> bool:
        if simdi - self._son.get(ad, 0) >= sn * 1000:
            self._son[ad] = simdi
            return True
        return False

    def _tasfiye(self, simdi: int) -> None:
        if self.kip != "sanal":
            return                                         # gerçek kipte tasfiyeyi HL yapar; mutabakat farkı yakalar
        for e in self.hesap.tasfiye_kontrol(self.marks, simdi):
            self.kayit({"olay": "tasfiye", **e})
            self.tg.gonder(f"TASFİYE (sanal): {tg.kisa(e['adres'])} {e['coin']} @{e['tasfiye_px']:.6g} (mark {e['mark']:.6g})")

    def _risk(self, simdi: int) -> None:
        oz = self.ozsermaye()
        if self.risk.kasa_siniri_asildi(self.kasa):
            if self._aralik_mi("kasa_alarm", simdi, 3600):
                self.tg.gonder(f"ALARM: kasa {self.kasa:.0f}$ > sınır {self.rules['canli_kasa_ust_usd']}$ — yeni açılış yok")
        for ev in self.risk.ozsermaye_isle(oz, simdi):
            self.kayit({"olay": "risk", "tur": ev, "ozsermaye": oz})
            if ev == "zirve_dusus":
                self.dur_tetikle("zirve_dusus")
            else:
                self.tg.gonder(f"ALARM: günlük kayıp ≥ %{float(self.rules['canli_gunluk_kayip_oran']) * 100:.0f} (özsermaye {oz:.2f}$) — bugün yeni açılış yok")

    def _anlik(self, simdi: int) -> None:
        self.karar_uygula(self.saha.anlik(simdi, lambda a: self.hesap.slot_ozsermaye(a, self.marks), self._son_kadro), simdi)

    _son_kadro: dict | None = None

    def _mutabakat(self, simdi: int) -> None:
        if not self._aralik_mi("mutabakat", simdi, float(self.rules["canli_mutabakat_sn"])):
            return
        if self.kip == "gercek":
            adres = os.environ.get("HL_HESAP_ADRESI", "")
            hl = clearinghouse_pozisyonlari(self.post, adres, self._dexler())
            bizim: dict[str, float] = {}
            for coinler in self.hesap.poz.values():
                for c, p in coinler.items():
                    bizim[c] = bizim.get(c, 0.0) + p.sz
            sorunlar = poz_farki(bizim, hl, self.marks, self.kasa, float(self.rules["canli_mutabakat_oran"]))
        else:
            sorunlar = sanal_tutarlilik(self.hesap, self.marks, self.mark_ms, simdi, float(self.rules["canli_mark_stale_sn"]))
        onceki = bool(self.risk.acilis_durdu.get("mutabakat"))
        self.risk.bayrak("mutabakat", bool(sorunlar))
        if sorunlar and not onceki:
            self.kayit({"olay": "mutabakat_alarm", "sorunlar": sorunlar[:10]})
            self.tg.gonder(f"ALARM mutabakat [{self.kip}]: {len(sorunlar)} sorun ({sorunlar[0].get('neden')}); yeni açılış durdu")
        elif not sorunlar and onceki:
            self.kayit({"olay": "mutabakat_duzeldi"})
            self.tg.gonder("mutabakat düzeldi: yeni açılışlar yeniden serbest")

    def _kadro_al(self, simdi: int) -> tuple[bool, dict | None]:
        """Aralık dolduysa `kadro.json` okunur (ağ; kilitsiz). Döner (okundu, kadro|None)."""
        if not self._aralik_mi("kadro", simdi, float(self.rules["canli_kadro_aralik_sn"])):
            return False, None
        try:
            return True, self.kadro_oku()
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "kadro_okuma_hata", "tur": type(hata).__name__})
            return True, None

    def _kadro_uygula(self, okuma: tuple[bool, dict | None], simdi: int) -> None:
        okundu, kadro = okuma
        if not okundu:
            return
        if kadro is not None:
            self._son_kadro = kadro
        kararlar, durum = self.saha.degerlendir(self._son_kadro, simdi)
        if durum != "ok":
            self.kayit({"olay": "kadro_" + durum})
            if self.saha.alarm_gunu != gun(simdi):
                self.saha.alarm_gunu = gun(simdi)
                self.tg.gonder(f"ALARM: {durum} — saha olduğu gibi kalır, yeni giriş yok")
        self.karar_uygula(kararlar, simdi)

    def _kadro(self, simdi: int) -> None:
        self._kadro_uygula(self._kadro_al(simdi), simdi)

    def _komutlar(self, komutlar: list[str]) -> None:
        for k in komutlar:
            if k == "/dur":
                self.dur_tetikle("komut")
            elif k == "/durum":
                self.tg.gonder(self.durum_metni())

    def durum_metni(self) -> str:
        oz = self.ozsermaye()
        return (f"DURUM [{self.kip}] özsermaye {oz:.2f}$ ({(oz / self.kasa - 1) * 100:+.2f}%) · saha {len(self.saha.uyeler)}/{self.saha.n} · inen {len(self.saha.inen)} · "
                f"emir {self.sayac['emir']} · risk {'DUR' if self.risk.dur else 'ok'}")

    def pano_ek(self) -> dict[str, Any]:
        """`ozet.json`a rapor (`pano/OZET.md`, T6 §3) için eklenen alanlar: açık pozisyonlar (mark'lı; K/Z = sz × (mark − giriş)) ve REST istek / 429 sayaçları. Yeni hesap değil: defter + mark biçimi."""
        acik = []
        for adres, coinler in self.hesap.poz.items():
            for coin, p in coinler.items():
                mk = self.marks.get(coin) or p.giris
                acik.append({"adres": adres, "coin": coin, "sz": p.sz, "giris": p.giris, "mark": mk, "usd": abs(p.sz) * mk, "kz_usd": p.sz * (mk - p.giris)})
        stats = getattr(self.post, "stats", None) or {}
        return {"acik": acik, "rest_istek": stats.get("istek"), "rest_429": stats.get("429")}

    def _gunluk_ozet(self, simdi: int) -> None:
        d = datetime.fromtimestamp(simdi / 1000, UTC)
        if d.hour < int(self.rules["canli_ozet_saat_utc"]) or self._ozet_gunu == d.date().isoformat():
            return
        self._ozet_gunu = d.date().isoformat()
        oz = self.ozsermaye()
        acik = [f"{tg.kisa(a)} {c} {p.sz:+.4g}" for a, cs in self.hesap.poz.items() for c, p in cs.items()]
        self.tg.gonder(tg.msg_gunluk(self.kip, self.kasa, oz, (oz - self.risk.gun_basi) / self.kasa, oz / self.kasa - 1, len(self.saha.uyeler), self.saha.n, acik))

    # ------------------------------------------------------------------ özet
    def ozet(self) -> dict[str, Any]:
        ort = lambda x: (sum(x) / len(x)) if x else None            # noqa: E731
        simdi = self.saat_ms()
        oz = self.ozsermaye()
        return {"kip": self.kip, "vardiya": self.vardiya_id, "sure_dk": (simdi - self.baslama_ms) / DAKIKA, "kasa_usd": self.kasa, "ozsermaye_usd": oz, "getiri": oz / self.kasa - 1,
                "saha": len(self.saha.uyeler), "saha_n": self.saha.n, "inen": len(self.saha.inen), "slot_usd": self.saha.slot, "emir": dict(self.sayac),
                "ortalama_kayma_trader": ort(self.kayma_trader), "ortalama_kayma_ref": ort(self.kayma_ref), "kayma_n": len(self.kayma_trader), "acik_pozisyon": sum(len(c) for c in self.hesap.poz.values()),
                "brut_usd": self.hesap.brut_toplam(self.marks), "tasfiye": len(self.hesap.tasfiyeler), "dur": self.risk.dur, "kayit_sayac": dict(self.kayit.sayac), "telegram_hata": self.tg.hata_sayisi,
                "kor_kirpildi": len(self.kor_kirpildi), "neden_say": dict(sorted(self.neden_say.items())), "slot_tavani": self.neden_say.get("slot_tavani", 0),
                "marj_yok": self.neden_say.get("marj_yok", 0), "uyeler": sorted(self.saha.uyeler)}

    # ------------------------------------------------------------------ açılış
    def baslat(self) -> None:
        """Açılış: DUR varsa BAŞLAMAZ; kasa sınırı; kadro ilk okuması (saha kurulumu); saha üyelerinin pozisyon/hesap okuması; markları al."""
        if self.dur_dosyasi.exists():
            raise KipHatasi("DUR dosyası var: elle silinmeden yeniden açılmaz")
        if self.kasa > float(self.rules["canli_kasa_ust_usd"]) + 1e-9:
            raise KipHatasi(f"kasa {self.kasa} $ > sınır {self.rules['canli_kasa_ust_usd']} $ (AGENTS.md)")
        self.kilit_al()
        simdi = self.saat_ms()
        self.piyasa_oku(simdi)
        self._son["kadro"] = 0
        self._kadro(simdi)
        for adres in [*self.saha.uyeler, *self.saha.inen]:
            if adres not in self.poz_tr:
                self.trader_pozlari_oku(adres)
        self.durum_yaz()

    def kacanlari_tamamla(self, bas_ms: int | None = None) -> int:
        """Açılışta REST ile kaçan dolumları tamamlar (`gec_goruldu`): her saha/inen adresi için `bas_ms`'den şimdiye. Pencere `canli_kacan_pencere_dk` ile sınırlıdır."""
        simdi = self.saat_ms()
        baslangic = max(bas_ms or self.son_olay_ms or simdi, simdi - int(self.rules["canli_kacan_pencere_dk"]) * DAKIKA)
        sayi = 0
        for adres in [*self.saha.uyeler, *self.saha.inen]:
            try:
                dolumlar = rest_dolumlar(self.post, adres, baslangic, simdi)
            except Exception as hata:                      # noqa: BLE001
                self.kayit({"olay": "kacan_okuma_hata", "adres": adres, "tur": type(hata).__name__})
                continue
            for f in sorted(dolumlar, key=lambda x: int(x["time"])):
                coin = str(f.get("coin", ""))
                if coin.startswith("@") or "/" in coin or f.get("tid") is None:
                    continue
                o = Olay(f"{adres}:{f['tid']}", adres, adres, int(f["time"]), simdi, "rest", False, "", coin, float(f["px"]), float(f["sz"]), str(f["side"]),
                         float(f["startPosition"]) if f.get("startPosition") is not None else None)
                if self.olay_isle(o, True):
                    sayi += 1
        self.kayit({"olay": "kacan_tamamlandi", "adet": sayi, "bas_ms": baslangic})
        return sayi


# ---------------------------------------------------------------------------------------------------- dinleyici köprüsü
class CanliDinleyici(Dinleyici):
    """`dinleyici.Dinleyici` (kural 7: WS, tekilleştirme, kopma → REST dolgu) + motor kuyruğu. Taban sınıfın risk kancası (`risk_isle`) motor kuyruğuna bağlanır; dinamik adres ekleme (`izle_ekle`)."""

    def __init__(self, kuyruk: asyncio.Queue, *a: Any, **k: Any) -> None:
        super().__init__(*a, **k)
        self.kuyruk = kuyruk
        self.ad_adres = {i.ad: i.adres for i in self.liste}

    def izle_ekle(self, adres: str) -> None:
        if adres in self.izlenen:
            return
        i = Izlenen(adres[:12], adres)
        self.izlenen[adres] = i
        self.liste.append(i)
        self.ad_adres[i.ad] = adres
        from copytrade.dinleyici import TraderOlcum
        self.olcum.adlar.append(i.ad)
        self.olcum.toplam[i.ad], self.olcum.saat[i.ad] = TraderOlcum(), TraderOlcum()

    def risk_isle(self, o: Olay, canli: bool, simdi_ms: int, kaynak: str | None = None) -> None:       # type: ignore[override]
        adres = o.adres or self.ad_adres.get(o.ad, "")
        self.kuyruk.put_nowait((replace(o, adres=adres), bool(canli and not self.olcum.snapshot_mi(o))))


async def _tuketici(motor: Motor, kuyruk: asyncio.Queue, durdur: asyncio.Event) -> None:
    while not durdur.is_set():
        try:
            o, canli = await asyncio.wait_for(kuyruk.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        try:
            await asyncio.to_thread(motor.olay_isle, o, canli)
        except Exception as hata:                          # noqa: BLE001 - tek dolum hatası motoru düşürmez
            motor.kayit({"olay": "olay_hata", "tur": type(hata).__name__, "mesaj": str(hata)[:160]})


async def _periyodik(motor: Motor, durdur: asyncio.Event, dinleyici: CanliDinleyici, aralik_sn: float = 30.0) -> None:
    while not durdur.is_set():
        await asyncio.to_thread(motor.dakika)
        for adres in motor.saha.uyeler:
            dinleyici.izle_ekle(adres)
        if motor.dur_istendi:
            dinleyici.durdur()
            durdur.set()
            return
        try:
            await asyncio.wait_for(durdur.wait(), timeout=aralik_sn)
        except asyncio.TimeoutError:
            pass


async def calis(motor: Motor, sure_sn: float | None = None, ws: Callable[[], Any] = ws_baglan, cikti: Path | None = None) -> dict:
    """Ana döngü: dinleyici + tüketici + periyodik görevler; `sure_sn` dolunca (vardiya) ya da DUR/SIGTERM ile biter. Son özet `kayit`'a ve `durum/ozet.json`'a yazılır."""
    oncelik = [*motor.saha.uyeler, *motor.saha.inen]                      # userFills aboneliği ilk `userfills_adet` adrese: önce saha/inen
    adaylar = [s["adres"] for s in ((motor._son_kadro or {}).get("satirlar") or [])]
    adresler = list(dict.fromkeys([*oncelik, *adaylar]))
    if not adresler:
        raise KipHatasi("izlenecek adres yok (kadro okunamadı, saha boş)")
    liste = [Izlenen(a[:12], a) for a in adresler]
    coinler = coin_listesi(motor.post)
    kuyruk: asyncio.Queue = asyncio.Queue()
    cikti = cikti or (motor.durum_dizin / "dinleyici")
    din = CanliDinleyici(kuyruk, liste, coinler, ws, motor.post, cikti, Ayar(userfills_adet=10, sure_sn=sure_sn), saat_ms=motor.saat_ms, dex_adlari=motor._dexler())
    durdur = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: (din.durdur(), durdur.set()))
    except (NotImplementedError, RuntimeError):
        pass
    motor.kacanlari_tamamla()
    gorevler = [asyncio.create_task(_tuketici(motor, kuyruk, durdur)), asyncio.create_task(_periyodik(motor, durdur, din))]
    try:
        await din.calis()
    finally:
        durdur.set()
        await asyncio.gather(*gorevler, return_exceptions=True)
        ozet = {**motor.ozet(), **motor.pano_ek(), "dinleyici": din.ozet()["genel"]}
        motor.kayit({"olay": "kapanis", "ozet": ozet})
        _yaz(motor.durum_dizin / "ozet.json", ozet)
        motor.durum_yaz()
        motor._kilit_birakildi = True
        motor.kilit_yaz(True)                              # temiz kapanış: sonraki vardiya hemen devralır
    return ozet


# ---------------------------------------------------------------------------------------------------- kontrol ve CLI
def kadro_url(rules: dict, dal: str | None = None) -> str:
    return f"https://raw.githubusercontent.com/{rules['canli_kadro_repo']}/{dal or rules['canli_kadro_dali']}/radar/son/kadro.json"


def http_kadro_oku(rules: dict, dal: str | None = None) -> dict | None:
    import requests
    r = requests.get(kadro_url(rules, dal), timeout=20)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def kontrol(rules: dict, kip: str, post: Callable[[dict], Any], kadro_oku: Callable[[], dict | None], tgram: tg.Telegram, ortam: dict | None = None) -> dict:
    """`--kontrol` (T5 açılış kontrolü): anahtar, bakiye, HL bağlantısı, kadro okuma, Telegram — EMİR GÖNDERMEZ. Döner rapor; `tamam` hepsi geçtiyse True."""
    ortam = os.environ if ortam is None else ortam
    r: dict[str, Any] = {"kip": kip, "kasa_usd": float(rules["canli_kasa_usd"])}
    r["kasa_siniri_ok"] = r["kasa_usd"] <= float(rules["canli_kasa_ust_usd"])
    r["anahtar"] = bool(ortam.get("HL_API_CUZDAN_ANAHTARI")) and bool(ortam.get("HL_HESAP_ADRESI"))        # değerler ASLA yazılmaz
    try:
        r["hl_baglanti"] = len(post({"type": "meta"})["universe"]) > 0
    except Exception as hata:                              # noqa: BLE001
        r["hl_baglanti"], r["hl_hata"] = False, type(hata).__name__
    r["bakiye_usd"] = r["hl_hesap_degeri"] = None
    r["etkin_kasa_usd"] = r["kasa_usd"]
    if r["anahtar"] and ortam.get("HL_HESAP_ADRESI"):
        try:
            hl = hesap_degeri_oku(post, ortam["HL_HESAP_ADRESI"], perp_dex_names(post({"type": "perpDexs"})))
            r["bakiye_usd"] = r["hl_hesap_degeri"] = hl                        # tüm perp dex + spot USDC (K‑35)
            r["etkin_kasa_usd"] = min(r["kasa_usd"], hl) if kip == "gercek" else r["kasa_usd"]      # gerçek kip: min(ayar, HL hesap değeri)
        except Exception as hata:                          # noqa: BLE001
            r["bakiye_hata"] = type(hata).__name__
    try:
        k = kadro_oku()
        r["kadro"] = {"var": k is not None, "taze": bool(k) and kadro_taze_mi(k, int(time.time() * 1000), rules)[0], "satir": len((k or {}).get("satirlar", [])), "kosu_ms": (k or {}).get("kosu_ms")}
    except Exception as hata:                              # noqa: BLE001
        r["kadro"] = {"var": False, "hata": type(hata).__name__}
    r["telegram"] = {"yapilandirildi": tgram.acik}
    r["emir_gonderildi"] = False
    zorunlu = [r["kasa_siniri_ok"], r["hl_baglanti"], r["kadro"].get("var")]
    if kip == "gercek":
        zorunlu += [r["anahtar"], r["bakiye_usd"] is not None, tgram.acik]
    r["tamam"] = all(bool(x) for x in zorunlu)
    return r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kontrol", action="store_true", help="emir göndermeden anahtar/bakiye/HL/kadro/Telegram kontrolü; rapor yazar")
    ap.add_argument("--kip", choices=["sanal", "gercek"], default=None, help="varsayılan kurallar.yaml canli_kip (sanal)")
    ap.add_argument("--durum-dizin", type=Path, default=Path(os.environ.get("STATE_DIRECTORY", "durum")))
    ap.add_argument("--kayit-dizin", type=Path, default=None)
    ap.add_argument("--sure-sn", type=float, default=None, help="vardiya süresi (sn); varsayılan sonsuz")
    ap.add_argument("--kadro-dali", default=None, help="kadro.json veri dalı (varsayılan canli_kadro_dali; dal doğrulamasında radar-deneme)")
    ap.add_argument("--vardiya", default="yerel")
    args = ap.parse_args(argv)
    rules = load_rules()
    kip = kip_belirle(rules, args.kip)
    post = rest_post_olustur(rules)
    kadro_oku = lambda: http_kadro_oku(rules, args.kadro_dali)          # noqa: E731
    tgram = tg.Telegram(arka_plan=not args.kontrol)
    if args.kontrol:
        rapor = kontrol(rules, kip, post, kadro_oku, tgram)
        args.durum_dizin.mkdir(parents=True, exist_ok=True)
        _yaz(args.durum_dizin / "kontrol.json", rapor)
        print(json.dumps(rapor, ensure_ascii=False, indent=1))
        return 0 if rapor["tamam"] else 1
    try:
        kasa, hl_deger = etkin_kasa(rules, kip, post)
        rules = {**rules, "canli_kasa_usd": kasa}
        boyut.saha_sayisi(kasa, rules)
    except (KipHatasi, ValueError) as hata:
        print(f"BAŞLAMADI: {hata}", file=sys.stderr)
        return 3
    yur: Yurutucu = gercek_yurutucu_olustur(post, rules) if kip == "gercek" else SanalYurutucu(post, rules)
    motor = Motor(rules, yur, post, tgram, args.durum_dizin, args.kayit_dizin or (args.durum_dizin / "kayit"), kadro_oku, vardiya_id=args.vardiya)
    try:
        motor.baslat()
    except KipHatasi as hata:
        print(f"BAŞLAMADI: {hata}", file=sys.stderr)
        return 3
    motor.tg.gonder(f"Motor başladı [{motor.kip}] kasa {motor.kasa:.0f}$ saha {len(motor.saha.uyeler)}/{motor.saha.n} vardiya {motor.vardiya_id}")
    ozet = asyncio.run(calis(motor, args.sure_sn))
    print(json.dumps(ozet, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
