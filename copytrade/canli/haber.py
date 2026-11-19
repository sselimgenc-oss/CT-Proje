"""Haber / duygu etiketi: emir kaydına yazılır; K-73: SANALda motor bunlarla yeni açılışı atlatır (haber_ters, duygu_ters), GERÇEK kipte yalnız kayıt (kullanıcı kararı 19.11.2026).

Kaynaklar (ücretsiz, anahtarsız):
- Piyasa duygusu: alternative.me Crypto Fear & Greed Index (`/fng/?limit=1`) -> `{deger 0-100, sinif}`.
- Haber: herkese açık RSS (CoinDesk, Cointelegraph); stdlib `xml.etree`, yeni bağımlılık yok. Son 24 saatte coin'i anan başlık sayısı.

UYARI: ton etiketi KABA bir anahtar kelime sayımıdır (İngilizce başlık, bağlam/olumsuzlama anlaşılmaz). Gerçek kipte yalnız bilgidir (karar yoluna girmez); sanalda `_sanal_acilis_filtresi` kullanır.
Her hata (ağ, zaman aşımı, bozuk XML/JSON) sessizce yutulur: son önbellek korunur; fonksiyonlar istisna fırlatmaz.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any, Callable

ZAMAN_ASIMI_SN = 5
TOPLAM_BUTCE_SN = 12                      # bir okumadaki tüm ağ çağrıları için üst sınır; aşılırsa kalan kaynaklar atlanır
PENCERE_MS = 24 * 3600 * 1000
SAKLA_MS = 25 * 3600 * 1000
EN_FAZLA_BASLIK = 150
DUYGU_BAYAT_MS = 26 * 3600 * 1000         # endeks günlüktür; bundan eski okuma kayda yazılmaz

POZITIF = ("surge", "rally", "soar", "gain", "jump", "record", "approv", "bullish", "adopt", "rise", "rebound", "breakout", "inflow")
NEGATIF = ("crash", "plunge", "hack", "exploit", "drop", "fall", "ban", "lawsuit", "bearish", "sell-off", "selloff", "liquidat", "fraud", "outflow", "slump", "sue")

# Yaygın isimler (sembol dışında); sembol büyük harfle tam kelime eşleşir.
ISIMLER = {"BTC": ("bitcoin",), "ETH": ("ethereum", "ether"), "SOL": ("solana",)}

Getir = Callable[[str], Any]


def _getir_json(url: str) -> Any:
    import requests

    r = requests.get(url, timeout=ZAMAN_ASIMI_SN, headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def _getir_metin(url: str) -> Any:
    import requests

    r = requests.get(url, timeout=ZAMAN_ASIMI_SN, headers={"Accept": "application/rss+xml, application/xml, text/xml"})
    r.raise_for_status()
    return r.content


def duygu_coz(veri: Any) -> dict | None:
    """alternative.me yanıtı -> `{"deger": int 0-100, "sinif": str}` ya da None."""
    try:
        k = veri["data"][0]
        d = int(float(k["value"]))
        s = str(k["value_classification"]).strip()
        return {"deger": d, "sinif": s} if 0 <= d <= 100 and s else None
    except Exception:  # noqa: BLE001
        return None


def ton(baslik: str) -> str:
    """KABA ton: pozitif/negatif anahtar kelime sayısı farkının işareti (eşitse 'notr')."""
    b = baslik.lower()
    skor = sum(1 for k in POZITIF if k in b) - sum(1 for k in NEGATIF if k in b)
    return "pozitif" if skor > 0 else "negatif" if skor < 0 else "notr"


def rss_coz(icerik: Any, simdi_ms: int) -> list[dict]:
    """RSS -> `[{"t": ms, "b": başlık(≤120), "ton": ...}]`; tarihsiz/25 saatten eski/ileri tarihli öğeler atılır. Bozuk XML -> `[]`.
    DTD/ENTITY içeren belge reddedilir (genişleme saldırısı)."""
    try:
        ham = icerik if isinstance(icerik, (bytes, bytearray)) else str(icerik).encode("utf-8")
        if b"<!DOCTYPE" in ham.upper() or b"<!ENTITY" in ham.upper():
            return []
        kok = ET.fromstring(ham)
        cikti = []
        for oge in kok.iter("item"):
            baslik = (oge.findtext("title") or "").strip()
            tarih = (oge.findtext("pubDate") or "").strip()
            if not baslik or not tarih:
                continue
            try:
                t = int(parsedate_to_datetime(tarih).timestamp() * 1000)
            except (TypeError, ValueError):
                continue
            if simdi_ms - t > SAKLA_MS or t > simdi_ms + 3600_000:
                continue
            cikti.append({"t": t, "b": baslik[:120], "ton": ton(baslik)})
        return cikti
    except Exception:  # noqa: BLE001
        return []


def _desen(coin: str) -> re.Pattern | None:
    sym = coin[1:] if len(coin) > 2 and coin[0] == "k" and coin[1].isupper() else coin      # HL "kPEPE" öneki
    if len(sym) < 2 or not sym.isalnum():
        return None
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(sym) + r"(?![A-Za-z0-9])")


def eslesir(baslik: str, coin: str) -> bool:
    """Coin sembolü büyük harfle TAM KELİME (SOL; 'solid' değil) ya da bilinen isim (bitcoin, ethereum, solana)."""
    d = _desen(coin)
    if d is not None and d.search(baslik):
        return True
    bl = baslik.lower()
    return any(re.search(r"(?<![a-z0-9])" + n + r"(?![a-z0-9])", bl) for n in ISIMLER.get(coin, ()))


def coin_haber(anlik: dict, coin: str, simdi_ms: int) -> dict | None:
    """`{coin: {"adet_24s": n, "ton": çoğunluk|None}}`; önbellek yoksa None."""
    try:
        basliklar = (anlik or {}).get("haberler")
        if basliklar is None or not anlik.get("haber_ms"):
            return None
        es = [h for h in basliklar if simdi_ms - h["t"] <= PENCERE_MS and eslesir(h["b"], coin)]
        sayac = {"pozitif": 0, "negatif": 0, "notr": 0}
        for h in es:
            sayac[h["ton"]] += 1
        t = None
        if es:
            t = "pozitif" if sayac["pozitif"] > sayac["negatif"] else "negatif" if sayac["negatif"] > sayac["pozitif"] else "notr"
        return {coin: {"adet_24s": len(es), "ton": t}}
    except Exception:  # noqa: BLE001
        return None


def duygu_ozet(anlik: dict, simdi_ms: int) -> dict | None:
    """Önbellekteki duygu `{deger, sinif}`; yok ya da bayatsa None."""
    try:
        d = (anlik or {}).get("duygu")
        if not d or simdi_ms - int(d["ms"]) > DUYGU_BAYAT_MS:
            return None
        return {"deger": d["deger"], "sinif": d["sinif"]}
    except Exception:  # noqa: BLE001
        return None


def emir_alanlari(anlik: dict, coin: str, simdi_ms: int) -> dict:
    """`emir` kaydına eklenecek alanlar (`duygu`, `haber`)."""
    return {"duygu": duygu_ozet(anlik, simdi_ms), "haber": coin_haber(anlik, coin, simdi_ms)}


def guncelle(kurallar: dict, anlik: dict, simdi_ms: int, getir_json: Getir | None = None, getir_metin: Getir | None = None) -> tuple[dict, list[dict]]:
    """Kaynakları okur; `(yeni_anlik, olaylar)` döner. Hata olan kaynakta eski önbellek korunur. İstisna fırlatmaz."""
    anlik = dict(anlik or {})
    olaylar: list[dict] = []
    try:
        gj, gm = getir_json or _getir_json, getir_metin or _getir_metin
        bas = time.monotonic()
        url = str(kurallar.get("duygu_kaynak_url") or "").strip()
        if url:
            try:
                d = duygu_coz(gj(url))
            except Exception:  # noqa: BLE001
                d = None
            if d:
                onceki = (anlik.get("duygu") or {}).get("sinif")
                anlik["duygu"] = {**d, "ms": simdi_ms}
                if onceki != d["sinif"]:
                    olaylar.append({"olay": "duygu_degisti", "onceki": onceki, "yeni": d["sinif"], "deger": d["deger"]})
        kaynaklar = [str(u).strip() for u in (kurallar.get("haber_kaynaklar") or []) if str(u).strip()]
        gelen: list[dict] = []
        tamam = False
        for u in kaynaklar:
            if time.monotonic() - bas > TOPLAM_BUTCE_SN:
                break
            try:
                ham = gm(u)
            except Exception:  # noqa: BLE001
                continue
            oge = rss_coz(ham, simdi_ms)
            if oge:
                gelen += oge
                tamam = True
        if tamam:
            birlesik = {h["b"]: h for h in (anlik.get("haberler") or []) if isinstance(h, dict) and simdi_ms - h["t"] <= SAKLA_MS}
            birlesik.update({h["b"]: h for h in gelen})
            anlik["haberler"] = sorted(birlesik.values(), key=lambda h: -h["t"])[:EN_FAZLA_BASLIK]
            anlik["haber_ms"] = simdi_ms
    except Exception:  # noqa: BLE001
        pass
    return anlik, olaylar
