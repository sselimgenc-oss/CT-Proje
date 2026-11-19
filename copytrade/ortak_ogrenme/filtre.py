# Kaynak: sselimgenc-oss/SG-Github-AB-proje trader/paket/ortak_ogrenme/filtre.py @ 84f6cad (kopya; değiştirme, güncelleme kaynaktan)
"""Ortak filtre (spec parca 2 bolum 2): ridge-lojistik egitimi, JSON paket (hash, son kullanma), puan.

Bu modul numpy ister; paketteki tek numpy icerigi budur. Filtre yalniz puan verir; islem engellemez.
ML karsiligi: trader_ml/setup_filter/train.py -> fit_logistic, RIDGE, THR_FRAC; paket: TreeModel 'logistic'.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .kayit import Aday

RIDGE = 5.0
ITERS = 40
THR_FRAC = 0.9
AZAMI = 50000
SON_KULLANMA_GUN = 21
PAKET_SURUMU = 1
TUR = "ortak_filtre"
_LOGIT_LIMIT = 35


class PaketHatasi(ValueError):
    """Paket okunamadi, butunluk (hash) veya gecerlilik (surum, son kullanma) denetimini gecemedi."""


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -_LOGIT_LIMIT, _LOGIT_LIMIT)))


def fit_logistic(X, y, ridge: float = RIDGE, iters: int = ITERS) -> dict:
    """Ridge lojistik (Newton/IRLS; kesisim cezasiz). NaN ortalamayla doldurulur; std<1e-12 -> 1.
    Donus: {kind:'logistic', n_features, coef, intercept, mean, std, fill} (ML TreeModel bicimi)."""
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n, k = X.shape
    finite = np.isfinite(X)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # tamamen NaN kolonda nanmean uyarisi; np.where 0 secer
        fill = np.where(finite.any(axis=0), np.nanmean(np.where(finite, X, np.nan), axis=0), 0.0) if n else np.zeros(k)
    fill = np.nan_to_num(fill)
    Xf = np.where(finite, X, fill)
    mean = Xf.mean(axis=0)
    std = Xf.std(axis=0)
    std = np.where(std < 1e-12, 1.0, std)
    Z = (Xf - mean) / std
    A = np.hstack([Z, np.ones((n, 1))])
    w = np.zeros(k + 1)
    w[-1] = np.log((y.mean() + 1e-3) / (1 - y.mean() + 1e-3))
    P = np.diag(np.r_[np.full(k, ridge), 0.0])
    for _ in range(iters):
        p = _sigmoid(A @ w)
        g = A.T @ (p - y) + P @ w
        H = (A * (p * (1 - p))[:, None]).T @ A + P + 1e-9 * np.eye(k + 1)
        step = np.linalg.solve(H, g)
        w -= step
        if np.max(np.abs(step)) < 1e-7:
            break
    return {"kind": "logistic", "n_features": int(k), "coef": [float(v) for v in w[:-1]],
            "intercept": float(w[-1]), "mean": [float(v) for v in mean], "std": [float(v) for v in std],
            "fill": [float(v) for v in fill]}


def _sayi(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def ozellik_adlari(adaylar: Iterable[Aday]) -> list[str]:
    """Adaylarin ozellik anahtarlarinin sirali birlesimi; sayi olmayan (ve sonlu olmayan) degerler yok sayilir."""
    ad: set[str] = set()
    for a in adaylar:
        for k, v in a.ozellikler.items():
            if _sayi(v):
                ad.add(k)
    return sorted(ad)


def matris(adlar: Sequence[str], adaylar: Sequence[Aday]) -> np.ndarray:
    """(len(adaylar), len(adlar)) matris; eksik ya da sayi olmayan deger NaN."""
    X = np.full((len(adaylar), len(adlar)), np.nan, dtype=np.float64)
    for i, a in enumerate(adaylar):
        for j, ad in enumerate(adlar):
            v = a.ozellikler.get(ad)
            if _sayi(v):
                X[i, j] = float(v)
    return X


def _utc(dt: datetime) -> datetime:
    if dt.utcoffset() is None:
        raise ValueError("zaman tz'li (aware) olmali")
    return dt.astimezone(timezone.utc)


def _kilitte(ts: datetime, kilit: Sequence[tuple[datetime, datetime]]) -> bool:
    return any(b <= ts <= e for b, e in kilit)


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(metin: str) -> str:
    return hashlib.sha256(metin.encode("utf-8")).hexdigest()


def _model_hash(model: Mapping[str, Any], esik: float) -> str:
    return _sha256(_canon({"model": model, "esik": esik}))


def _ozellik_hash(adlar: Sequence[str]) -> str:
    return _sha256("\n".join(adlar))


def egit(kurulum: str, adaylar: Iterable[Aday], *, olusturma: datetime | None = None,
         kilit: Sequence[tuple[datetime, datetime]] = (), azami: int = AZAMI) -> dict | None:
    """Kurulum icin filtre paketi ya da None (veri yok ya da tek sinif).

    Egitime yalniz bu kurulumun alinmis ve r'si bilinen adaylari girer. kilit: [(baslangic, bitis)] tz'li
    aralikler (uc noktalar dahil); ts bu aralikta kalan satir egitimden dusurulur ve meta.kilit_dusen sayilir.
    Son `azami` satir (ts sirali) egitilir. Etiket r > 0; esik = THR_FRAC * taban_oran."""
    if azami < 1:
        raise ValueError("azami pozitif olmali")
    kilit = [(_utc(b), _utc(e)) for b, e in kilit]
    for b, e in kilit:
        if b > e:
            raise ValueError("kilit aralik baslangici bitisten buyuk")
    kilit_dusen = 0
    secili: list[Aday] = []
    for a in adaylar:
        if a.kurulum != kurulum or not a.alindi or a.r is None:
            continue
        if _kilitte(_utc(a.ts), kilit):
            kilit_dusen += 1
            continue
        secili.append(a)
    secili.sort(key=lambda a: a.ts)  # sort kararlidir
    secili = secili[-azami:]
    if not secili:
        return None
    y = np.array([1.0 if float(a.r) > 0 else 0.0 for a in secili])
    if y.min() == y.max():
        return None
    adlar = ozellik_adlari(secili)
    X = matris(adlar, secili)
    model = fit_logistic(X, y)
    taban = float(y.mean())
    esik = float(THR_FRAC * taban)
    olus = _utc(olusturma or datetime.now(timezone.utc))
    meta = {
        "paket_surumu": PAKET_SURUMU, "tur": TUR, "kurulum": kurulum,
        "olusturma": olus.isoformat(),
        "son_kullanma": (olus + timedelta(days=SON_KULLANMA_GUN)).isoformat(),
        "ozellikler": list(adlar), "ozellik_hash": _ozellik_hash(adlar),
        "n_egitim": len(secili), "n_pozitif": int(y.sum()), "taban_oran": taban,
        "kilit_dusen": kilit_dusen, "model_hash": _model_hash(model, esik),
    }
    return {"meta": meta, "model": model, "esik": esik}


def _guvenli_ad(kurulum: str) -> str:
    ad = re.sub(r"[^A-Za-z0-9._@-]", "_", str(kurulum))
    if not ad or ad.startswith("."):
        raise ValueError(f"guvenli dosya adi uretilemedi: {kurulum!r}")
    return ad


def _dogrula(paket: Any, simdi: datetime | None, sure_kontrol: bool) -> None:
    if not isinstance(paket, dict) or not isinstance(paket.get("meta"), dict):
        raise PaketHatasi("paket bicimi gecersiz")
    meta, model, esik = paket["meta"], paket.get("model"), paket.get("esik")
    if meta.get("paket_surumu") != PAKET_SURUMU or meta.get("tur") != TUR:
        raise PaketHatasi("paket surumu/turu uyusmuyor")
    if not isinstance(model, dict) or model.get("kind") != "logistic" or not _sayi(esik):
        raise PaketHatasi("model ya da esik gecersiz")
    adlar = meta.get("ozellikler")
    if not isinstance(adlar, list):
        raise PaketHatasi("ozellikler listesi yok")
    for alan in ("coef", "mean", "std", "fill"):
        if not isinstance(model.get(alan), list) or len(model[alan]) != len(adlar):
            raise PaketHatasi(f"model.{alan} ozellik sayisiyla uyusmuyor")
    if meta.get("ozellik_hash") != _ozellik_hash(adlar):
        raise PaketHatasi("ozellik hash'i tutmuyor (paket degistirilmis)")
    try:
        if meta.get("model_hash") != _model_hash(model, float(esik)):
            raise PaketHatasi("model hash'i tutmuyor (paket degistirilmis)")
        if sure_kontrol:
            son = datetime.fromisoformat(meta["son_kullanma"])
            if son.utcoffset() is None:
                raise PaketHatasi("son_kullanma tz'siz")
            now = _utc(simdi or datetime.now(timezone.utc))
            if now >= son.astimezone(timezone.utc):
                raise PaketHatasi("paket suresi dolmus")
    except (KeyError, TypeError, ValueError) as e:
        raise PaketHatasi(f"paket denetimi basarisiz: {e}") from e


def kaydet(paket: Mapping[str, Any], klasor: str | os.PathLike) -> Path:
    """<guvenli_ad>.json olarak atomik yazar; eskisi <guvenli_ad>.prev.json olur.
    Yazmadan once gecici dosya yukle ile dogrulanir (surum ve son kullanma denetlenmez: kayit, kullanim degildir)."""
    ad = _guvenli_ad(paket["meta"]["kurulum"])
    d = Path(klasor)
    d.mkdir(parents=True, exist_ok=True)
    hedef = d / f"{ad}.json"
    onceki = d / f"{ad}.prev.json"
    metin = json.dumps(paket, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False)
    fd, tmp = tempfile.mkstemp(dir=str(d), prefix=".filtre-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(metin)
            fh.flush()
            os.fsync(fh.fileno())
        if yukle(tmp, sure_kontrol=False) != json.loads(metin):
            raise PaketHatasi("gidis-donus dogrulamasi basarisiz")
        if hedef.exists():
            os.replace(hedef, onceki)
        os.replace(tmp, hedef)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return hedef


def yukle(yol_ya_da_sozluk: str | os.PathLike | Mapping[str, Any], *, simdi: datetime | None = None,
          sure_kontrol: bool = True) -> dict:
    """Paketi okur ve denetler. Hash ya da ozellik hash'i tutmazsa, surum yanlissa ya da (sure_kontrol ve
    simdi >= son_kullanma) PaketHatasi (ValueError alt sinifi) firlatir."""
    if isinstance(yol_ya_da_sozluk, Mapping):
        try:
            paket = json.loads(_canon(yol_ya_da_sozluk))
        except (TypeError, ValueError) as e:
            raise PaketHatasi(f"paket JSON uyumlu degil: {e}") from e
    else:
        try:
            paket = json.loads(Path(yol_ya_da_sozluk).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise PaketHatasi(f"paket okunamadi: {e}") from e
    _dogrula(paket, simdi, sure_kontrol)
    return paket


def puan(paket: Mapping[str, Any], ozellikler: Mapping[str, float]) -> float:
    """Olasilik benzeri puan in [0, 1]: standartlastirma + sigmoid (z [-35, 35] kirpilir).
    Eksik ya da sayi olmayan ozellik modeldeki fill degeriyle doldurulur."""
    meta, model = paket["meta"], paket["model"]
    adlar = meta["ozellikler"]
    fill = np.asarray(model["fill"], dtype=np.float64)
    x = np.empty(len(adlar), dtype=np.float64)
    for i, ad in enumerate(adlar):
        v = ozellikler.get(ad)
        x[i] = float(v) if _sayi(v) else fill[i]
    mean = np.asarray(model["mean"], dtype=np.float64)
    std = np.asarray(model["std"], dtype=np.float64)
    coef = np.asarray(model["coef"], dtype=np.float64)
    z = float(((x - mean) / std) @ coef + float(model["intercept"]))
    z = min(max(z, -_LOGIT_LIMIT), _LOGIT_LIMIT)
    return 1.0 / (1.0 + math.exp(-z))
