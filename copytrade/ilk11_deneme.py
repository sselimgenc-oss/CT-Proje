"""Kural 1 küçük gerçek veri denemesi için yardımcılar (docs/ILK11_SECIM_SARTNAME.md §5.6); `ilk11_deneme.yml` iş akışı çağırır. Üretim verisine yazmaz.

- ``hazirla``: 28 Ekim kapı sonucundan 5 adres seçer (2 intraday, 2 swing + 1 başka `kopyalanabilir`; biri ≥ 1 M$, biri < 50 k$ hesap), ortak evren dosyasını
  (``kapi.py --evren-dosyasi``) ve 5 satırlık izleme listesini yazar.
- ``ozet``: kapı satırları, `ilk_alanlar` (İ) ve izleme `ilk11_form_ham` (F) alanlarını yan yana, her sütunun min / medyan / max'ını ve `kapanan_islemler`
  özetini markdown olarak basar.
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

from copytrade import ilk11_alanlar
from copytrade.ilk11 import KALDIRAC_ALANLARI
from copytrade.ilk11_pazar import KATMANLAR, pazar_as_of
from copytrade.kurallar import load_rules

BUYUK_USD, KUCUK_USD = 1_000_000.0, 50_000.0     # §5.6 deneme kapsamı (karar eşiği değil)


def sec(tablo: pd.DataFrame) -> list[dict]:
    """Deterministik seçim: en büyük hesap (≥ 1 M$) ve en küçük hesap (< 50 k$) önce; sonra tarz başına 2'ye tamamlanır (kalan adaylardan ortancaya
    en yakın hesap); beşinci = henüz seçilmemiş en yakın `kopyalanabilir`. Koşul sağlanamazsa ValueError."""
    aday = tablo[tablo["katman"].isin(KATMANLAR) & tablo["tarz"].isin(["intraday", "swing"])].copy()
    aday["address"] = aday["address"].astype(str).str.lower()
    aday["hesap"] = pd.to_numeric(aday["hesap_degeri_bugun"], errors="coerce")
    aday = aday.dropna(subset=["hesap"]).drop_duplicates("address").sort_values(["hesap", "address"])
    if aday.empty:
        raise ValueError("katman adayı yok")
    orta = float(aday["hesap"].median())
    secilen: list[dict] = []

    def al(satir) -> None:
        secilen.append({"address": satir["address"], "tarz": satir["tarz"], "katman": satir["katman"], "hesap": float(satir["hesap"])})

    def kalan():
        gorulen = {s["address"] for s in secilen}
        return aday[~aday["address"].isin(gorulen)].assign(uzak=lambda f: (f["hesap"] - orta).abs()).sort_values(["uzak", "address"])

    buyuk, kucuk = aday[aday["hesap"] >= BUYUK_USD], aday[aday["hesap"] < KUCUK_USD]
    if buyuk.empty or kucuk.empty:
        raise ValueError(f"≥ {BUYUK_USD:.0f} $ ({len(buyuk)}) ya da < {KUCUK_USD:.0f} $ ({len(kucuk)}) hesap yok")
    al(buyuk.iloc[-1])
    al(kucuk.iloc[0])
    for tarz in ("intraday", "swing"):
        while sum(s["tarz"] == tarz for s in secilen) < 2:
            havuz = kalan()[lambda f: f["tarz"] == tarz]
            if havuz.empty:
                raise ValueError(f"{tarz} adayı yetmiyor")
            al(havuz.iloc[0])
    havuz = kalan()[lambda f: f["katman"] == "kopyalanabilir"]
    if havuz.empty:
        raise ValueError("ek `kopyalanabilir` aday yok")
    al(havuz.iloc[0])
    return secilen


def hazirla(kapi_sonuc: Path, cikti: Path, simdi: datetime) -> dict:
    """Deneme girdilerini yazar. Kapı klasör tarihi = son Pazar'dan bir gün önce (``ilk11_pazar`` as_of öncesi + 7 gün tazelik kuralına uysun)."""
    secilen = sec(pd.read_csv(kapi_sonuc, low_memory=False))
    tarih = (pazar_as_of(simdi).date() - timedelta(days=1)).isoformat()
    t0 = (simdi - timedelta(days=int(load_rules()["ilk11_form_pencere_gun"]))).date().isoformat()
    cikti.mkdir(parents=True, exist_ok=True)
    (cikti / "evren.json").write_text(json.dumps({"liderler": [{"address": s["address"], "accountValue": s["hesap"], "kaynak": "dis_aday"} for s in secilen]}), encoding="utf-8")
    liste = [{"id": f"D{i}", "adres": s["address"], "takma_ad": s["address"][2:6], "tarz": s["tarz"], "durum": "izlemede", "t0": t0} for i, s in enumerate(secilen, 1)]
    (cikti / "izleme_listesi.yaml").write_text(yaml.safe_dump({"traderlar": liste}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (cikti / "tarih.txt").write_text(tarih + "\n", encoding="utf-8")
    (cikti / "secilen.json").write_text(json.dumps(secilen, indent=1), encoding="utf-8")
    return {"tarih": tarih, "secilen": secilen}


def _istatistik(ad: str, degerler: list) -> str:
    xs = [float(x) for x in degerler if x is not None and pd.notna(x)]
    if not xs:
        return f"| {ad} | 0 | — | — | — |"
    return f"| {ad} | {len(xs)} | {min(xs):.6g} | {statistics.median(xs):.6g} | {max(xs):.6g} |"


def ozet(kapi_sonuc: Path, durum: Path, pazar_alanlar: Path | None, sure_sn: float | None) -> str:
    satirlar = pd.read_csv(kapi_sonuc, low_memory=False).to_dict("records")
    ilk = {str(s["address"]).lower(): ilk11_alanlar.ilk_alanlar(s) for s in satirlar}
    d = json.loads(durum.read_text(encoding="utf-8"))
    out = [f"### Kapı satırları ({len(satirlar)})", "", "| adres | tarz | katman | sinif | hesap $ | hata | bilgi hatası |", "|---|---|---|---|---|---|---|"]
    out += [f"| `{str(s['address'])[:10]}…` | {s.get('tarz')} | {s.get('katman')} | {s.get('sinif')} | {s.get('hesap_degeri_bugun')} | {s.get('hata')} | {s.get('ilk11_bilgi_hatasi')} |"
            for s in satirlar]
    out += ["", "### 10 alan: İ (kapı satırı) ve F (izleme `ilk11_form_ham`)", "", "| adres | " + " | ".join(KALDIRAC_ALANLARI) + " |", "|---|" + "---|" * len(KALDIRAC_ALANLARI)]
    form = {str(t["adres"]).lower(): t.get("ilk11_form_ham", {}) for t in d["traderlar"]}
    for adres, (alanlar, kaynak) in ilk.items():
        out.append(f"| `{adres[:10]}…` İ | " + " | ".join(f"{alanlar[a]:.5g}" if alanlar[a] is not None else (f"**{kaynak[a]}**" if kaynak[a] else "—") for a in KALDIRAC_ALANLARI) + " |")
        f = form.get(adres, {})
        fa, fk = f.get("alanlar") or {}, f.get("alan_kaynagi") or {}
        out.append(f"| `{adres[:10]}…` F | " + " | ".join(f"{fa[a]:.5g}" if fa.get(a) is not None else (f"**{fk.get(a)}**" if fk.get(a) else "—") for a in KALDIRAC_ALANLARI)
                   + f" |  dolu_alan={f.get('dolu_alan', f.get('hata'))}")
    out += ["", "### Sütun min / medyan / max", "", "| sütun | n | min | medyan | max |", "|---|---|---|---|---|"]
    for a in KALDIRAC_ALANLARI:
        out.append(_istatistik(f"İ {a}", [v[0][a] for v in ilk.values()]))
        out.append(_istatistik(f"F {a}", [(f.get("alanlar") or {}).get(a) for f in form.values()]))
    if pazar_alanlar and pazar_alanlar.exists():
        tablo = pd.read_csv(pazar_alanlar)
        out += [f"", f"### Pazar `alanlar.csv` ({len(tablo)} satır)", "", "| sütun | n | min | medyan | max |", "|---|---|---|---|---|"]
        out += [_istatistik(c, tablo[c].tolist()) for c in tablo.columns if pd.api.types.is_numeric_dtype(tablo[c])]
    out += ["", "### İzleme (1 okuma)" + (f" — toplam {sure_sn:.0f} sn, trader başına ≈ {sure_sn / max(1, len(d['traderlar'])):.0f} sn → 50 trader ≈ {sure_sn / max(1, len(d['traderlar'])) * 50 / 60:.0f} dk" if sure_sn else ""),
            "", "| id | tarz | gecerli | hesap $ | kapanan işlem | geçerli | getiri min/medyan/max | fiyatsız eylem | son_perp_dolum | gecerli_saat |", "|---|---|---|---|---|---|---|---|---|---|"]
    for t in d["traderlar"]:
        v3 = t.get("sanal_kopya_v3") or {}
        islem = v3.get("kapanan_islemler") or []
        g = [x["getiri"] for x in islem if x.get("getiri") is not None]
        out.append(f"| {t['id']} | {t['tarz']} | {t['gecerli']} | {t.get('hesap_degeri'):.0f} | {len(islem)}/{v3.get('kapanan_islemler_toplam', len(islem))} | "
                   f"{sum(x.get('gecerli') is True for x in islem)} | " + (f"{min(g):.4g} / {statistics.median(g):.4g} / {max(g):.4g}" if g else "—")
                   + f" | {v3.get('fiyatsiz_eylem', '—')} | {t.get('son_perp_dolum')} | {(t.get('ilk11_gecerli_saat') or {}).get('saat')} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    alt = ap.add_subparsers(dest="komut", required=True)
    h = alt.add_parser("hazirla")
    h.add_argument("--kapi-sonuc", type=Path, required=True)
    h.add_argument("--cikti", type=Path, required=True)
    o = alt.add_parser("ozet")
    o.add_argument("--kapi-sonuc", type=Path, required=True)
    o.add_argument("--durum", type=Path, required=True)
    o.add_argument("--pazar-alanlar", type=Path, default=None)
    o.add_argument("--sure-sn", type=float, default=None)
    a = ap.parse_args(argv)
    if a.komut == "hazirla":
        print(json.dumps(hazirla(a.kapi_sonuc, a.cikti, datetime.now(UTC)), ensure_ascii=False, indent=1))
    else:
        print(ozet(a.kapi_sonuc, a.durum, a.pazar_alanlar, a.sure_sn))


if __name__ == "__main__":
    main()
