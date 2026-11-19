"""ML Otonom rejim etiketi okuyucusu: YALNIZ KAYIT, işlem etkisi yok.

Kaynak: sibling projenin yayımladığı salt-okunur `rejim.json` (belirtim: sürüm 1, 19.11.2026).
Her hata (ağ, zaman aşımı, bozuk biçim, bayat veri, boş adres) sessizce "bilinmiyor" sayılır:
fonksiyonlar istisna fırlatmaz; bilinmeyen durumda `{}` ya da `None` döner.
"""
from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from typing import Any, Callable

DESTEKLENEN_SURUM = 1
ZAMAN_DILIMLERI = ("4h", "1d")
REJIMLER = frozenset({"trend_up", "trend_down", "range", "volatile", "unclear"})
ZAMAN_ASIMI_SN = 5

Getir = Callable[[str], Any]


def _getir_varsayilan(url: str) -> Any:
    import requests

    r = requests.get(url, timeout=ZAMAN_ASIMI_SN, headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def _zaman(metin: Any) -> datetime | None:
    """ISO-8601 UTC metni (`...Z` ya da offset'li). Saat dilimi yoksa geçersiz sayılır."""
    if not isinstance(metin, str):
        return None
    try:
        t = datetime.fromisoformat(metin.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        return None
    return t.astimezone(UTC)


def _pozitif_sayi(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
        return None
    return float(v)


def _rejim(obj: Any) -> str | None:
    """Zaman dilimi nesnesinden etiket; sözlük dışı ya da eksikse None (bilinmiyor)."""
    if not isinstance(obj, dict):
        return None
    r = obj.get("rejim")
    return r if isinstance(r, str) and r in REJIMLER else None


def _coz(veri: Any, simdi_ms: int) -> dict:
    if not isinstance(veri, dict):
        return {}
    surum = veri.get("surum")
    if isinstance(surum, bool) or surum != DESTEKLENEN_SURUM:
        return {}
    uretim = _zaman(veri.get("uretim_ts"))
    gecerlilik = _pozitif_sayi(veri.get("gecerlilik_dk"))
    varliklar = veri.get("varliklar")
    if uretim is None or gecerlilik is None or not isinstance(varliklar, dict):
        return {}
    gecerli_son_ms = int(uretim.timestamp() * 1000) + int(round(gecerlilik * 60_000))
    if simdi_ms > gecerli_son_ms:                       # bayat: uretim_ts + gecerlilik_dk geçti → bilinmiyor
        return {}
    rejimler: dict[str, dict[str, str | None]] = {}
    for varlik in varliklar.values():
        if not isinstance(varlik, dict):
            continue
        baz = varlik.get("baz")
        if not isinstance(baz, str) or not baz.strip():
            continue
        coin = baz.strip()                              # HL eşlemesi: baz olduğu gibi (1000SHIB gibi önekler dahil)
        if coin in rejimler:                            # aynı baz iki çiftte: ilk gelen kazanır
            continue
        rejimler[coin] = {zd: _rejim(varlik.get(zd)) for zd in ZAMAN_DILIMLERI}
    return {"gecerli_son_ms": gecerli_son_ms, "rejimler": rejimler}


def oku_tam(url: Any, getir: Getir | None = None, simdi_ms: int | None = None) -> dict:
    """Rejim dosyasını okur. Dönüş: `{"gecerli_son_ms": int, "rejimler": {coin: {"4h": r|None, "1d": r|None}}}`
    ya da hata/bayat/boş adres durumunda `{}`. Boş adreste ağ çağrısı yapılmaz."""
    try:
        if not isinstance(url, str) or not url.strip():
            return {}
        veri = (getir or _getir_varsayilan)(url.strip())
        return _coz(veri, int(time.time() * 1000) if simdi_ms is None else simdi_ms)
    except Exception:  # noqa: BLE001  (salt kayıt: hiçbir hata işlemi ya da motoru durdurmaz)
        return {}


def oku(url: Any, getir: Getir | None = None, simdi_ms: int | None = None) -> dict:
    """`{coin: {"4h": rejim, "1d": rejim}}` ya da `{}`. Ayrıntı için `oku_tam`."""
    return dict(oku_tam(url, getir, simdi_ms).get("rejimler", {}))


def coin_rejimi(anlik: dict, coin: str, simdi_ms: int) -> dict | None:
    """Önbellekteki okumadan coin'in rejimi; önbellek boş ya da şu an bayatsa None."""
    try:
        if not anlik or simdi_ms > anlik["gecerli_son_ms"]:
            return None
        z = anlik["rejimler"].get(coin)
        return dict(z) if z else None
    except Exception:  # noqa: BLE001
        return None
