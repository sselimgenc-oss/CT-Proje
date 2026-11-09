"""Kalıcılık testi (K-53 doğrulaması; YALNIZ BİLGİ, salt okur): "bir haftanın R1'i geçenleri, SONRAKİ hafta kopyada kazandırdı mı?"

Kurallar, motor, kadro ve veri dalları DEĞİŞMEZ. Önceden kayıtlı ölçüler (sonuç görülmeden, 09.11):
  (a) her ölçünün (kopya getirisi, bootstrap alt %20, t, kopya işlem sayısı) sonraki hafta getirisiyle Spearman'ı (hafta başına, sonra ortalama);
  (b) R1'i geçen − geçemeyen (dolum kurallarını geçip kopyası oynatılanlar arasında) sonraki hafta ortalama getiri farkı; v1 (kopya işlem kapısı yok) ve v1.1 (≥ 10);
  (c) v1 geçenler içinde kopya işlem ≥ 10 ile < 10 farkı.
  Haftalık farkların ortalaması + hafta bloklu bootstrap %80 aralık. Karar: alt sınır > 0 → "devam"; üst sınır < 0 → evren tasarımı değişmeli; arada → belirsiz.

Evren: kayıtlı radar havuzlarının (origin/radar) tüm adresleri — bugünün kazananları (SURVIVORSHIP: sonuç iyimser okunur; burada bile kalıcılık yoksa yöntemde yok).
Ölçek: 1.000 $ kasa, slot = kasa / 11 (kopya_v5, R1 ile aynı boyut). **Yaklaşık kopya:** eski haftalarda 1/5 dk mum yok; kopya = trader'ın dolum fiyatıyla (gecikmesiz)
+ tam maliyet (taker + kayma); hafta sonu işaret fiyatı ve tasfiye denetimi saatlik mumdan (hafta sonundan önceki son saat açılışı). Aynı yaklaşım tüm haftalara ve tüm gruplara
uygulanır (karşılaştırma adil; mutlak seviye gerçek 1 dk gecikmeli kopyadan biraz iyimser). Likit coin listesi ve azami kaldıraç bugünün değerleri (küçük yanlılık).

    python -m copytrade.kalicilik_testi olc --parca 1/4 --cikti k1.json      # Actions matris işi
    python -m copytrade.kalicilik_testi analiz k1.json k2.json …             # birleştir + özet
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

from copytrade import izleme_motoru as im
from copytrade import kopya_v2, kopya_v5, radar_isabet, radar_tarama
from copytrade.defter import HOUR
from copytrade.kurallar import load_rules
from copytrade.olcut import perp_fills

GUN = 24 * HOUR
HAFTA = 7 * GUN
HAFTA_SAYISI = 8
OLCULER = ("kopya_getiri_7g", "kopya_alt20", "g_t_istat", "kopya_islem_sayisi")
BOOT_TEKRAR, BOOT_TOHUM = 2000, 20261109


# ------------------------------------------------------------------------------------------------------------------------------ saatlik mum kaynağı
class SaatlikMum:
    """Yalnız saatlik mum (HL 5.000 saat ≈ 208 gün geriye verir). `1m`/`5m` istekleri de saatlikten yanıtlanır: aralıktaki saat açılışları; aralıkta yoksa bitişten önceki SON saat
    (işaret fiyatı). Gecikmesiz kopyada yürütme mumu kullanılmaz (dolum fiyatı)."""

    def __init__(self, client: Any, bas_ms: int, bit_ms: int):
        self.client, self.bas, self.bit = client, bas_ms // HOUR * HOUR, bit_ms
        self.seri: dict[str, list[tuple[int, float, float | None]]] = {}

    def _s(self, coin: str) -> list[tuple[int, float, float | None]]:
        if coin not in self.seri:
            rows = self.client.candles(coin, self.bas, self.bit, interval="1h")
            self.seri[coin] = sorted((int(c["t"]), float(c["o"]), radar_tarama._sayi(c.get("c"))) for c in rows if radar_tarama._sayi(c.get("o")) is not None)
        return self.seri[coin]

    def candles(self, coin: str, start_ms: int, end_ms: int, interval: str = "1h") -> list[dict]:
        s = self._s(coin)
        aralik = [(t, o, k) for t, o, k in s if start_ms <= t <= end_ms]
        if not aralik and interval in ("1m", "5m"):
            once = [x for x in s if x[0] <= end_ms]
            aralik = once[-1:]
        return [{"t": t, "o": o, **({"c": k} if k is not None else {})} for t, o, k in aralik]


# ------------------------------------------------------------------------------------------------------------------------------ bir adres, bir hafta
def hafta_satiri(adres: str, dolumlar: list[dict] | None, hesap: float, payda: Any, mum: SaatlikMum, t0: int, t1: int, likit: set[str], azami: dict | None, rules: dict) -> dict:
    """Bir haftanın R1 ölçüleri + kararı (v1 ve v1.1) + o haftanın yaklaşık kopya getirisi (`getiri`). Dolum yok → getiri 0 (ölçüldü), kopya ölçüleri yok."""
    if dolumlar is None:
        return {"durum": "dolum_fazla", "getiri": None}
    dolumlar = [f for f in perp_fills(dolumlar) if t0 <= int(f["time"]) < t1]
    if not dolumlar:
        return {"durum": "islem_yok", "getiri": 0.0}
    vlm = sum(abs(float(f["px"]) * float(f["sz"])) for f in dolumlar)
    satir: dict = {"hesap_usd": hesap, "devir_hafta": vlm / hesap if hesap > 0 else None, "hata": None}
    satir.update(radar_tarama.islem_olculeri(dolumlar, hesap, likit, rules))
    dolumlar = kopya_v5.hip3_ayikla(dolumlar, bool(rules.get("radar_hip3_kopya", True)))
    eylemler = im.copy_actions(dolumlar)
    isaret = im.mark_candles(mum, eylemler, t1)
    saatlik = kopya_v2.saatlik_mumlar(mum, {}, dolumlar, im.open_copy_coins(eylemler), t1)
    a, b = pd.Timestamp(t0, unit="ms", tz="UTC"), pd.Timestamp(t1, unit="ms", tz="UTC")
    sonuc = kopya_v5.hesapla(dolumlar, saatlik, isaret, {}, [], a, b, 0, radar_tarama.KOPYA_TARZ, rules, azami_kaldirac=azami, trader_hesap_usd=payda)
    sifir = {**rules, "maliyet_taker": 0.0, "maliyet_kayma": 0.0}
    sonuc["ayna"] = kopya_v5.hesapla(dolumlar, saatlik, isaret, {}, [], a, b, 0, radar_tarama.KOPYA_TARZ, sifir, azami_kaldirac=azami, trader_hesap_usd=payda)
    satir.update(radar_tarama.kopya_olculeri(sonuc, adres, rules))
    v1 = {**rules, "radar_min_kopya_islem": 0}
    satir["gecti_v1"], satir["neden_v1"] = radar_tarama.degerlendir(satir, v1)
    satir["gecti_v11"], satir["neden_v11"] = radar_tarama.degerlendir(satir, rules)
    satir["dolum_gecti"] = radar_tarama.degerlendir(satir, v1, yalniz_dolum=True)[0]
    satir["getiri"] = satir["kopya_getiri_7g"] if sonuc.get("durum") != "hesaplanamadi" else None
    satir["durum"] = "olculdu"
    return {k: satir.get(k) for k in ("durum", "getiri", "dolum_gecti", "gecti_v1", "neden_v1", "gecti_v11", "neden_v11", *OLCULER)}


def haftalar(bitis_ms: int, n: int = HAFTA_SAYISI) -> list[tuple[int, int]]:
    """[(baş, bit)] eskiden yeniye; son hafta `bitis_ms`'de biter (UTC gün başına yuvarlanır)."""
    son = bitis_ms // GUN * GUN
    return [(son - (n - i) * HAFTA, son - (n - i - 1) * HAFTA) for i in range(n)]


def adres_olc(client: Any, adres: str, hesap_simdi: float, hf: list[tuple[int, int]], mum: SaatlikMum, likit: set[str], azami: dict | None, rules: dict) -> list[dict]:
    try:
        seri = kopya_v5.PaydaSerisi(radar_tarama.payda_noktalari(client.portfolio(adres), hf[-1][1]))
    except (*radar_tarama.HATALAR, AttributeError):
        seri = None
    cikti = []
    for t0, t1 in hf:
        hesap = seri(t1) if seri else hesap_simdi
        payda = seri if seri else hesap_simdi
        try:
            d = client.fills(adres, t0, max_rows=int(rules["radar_dolum_tavan"]), end_ms=t1)
            d = None if len(d) >= int(rules["radar_dolum_tavan"]) else d
            s = hafta_satiri(adres, d, hesap, payda, mum, t0, t1, likit, azami, rules)
        except radar_tarama.HATALAR as h:
            s = {"durum": "hata", "hata": type(h).__name__, "getiri": None}
        cikti.append({"hafta_bas": t0, **s})
    return cikti


def evren_adresleri(dal: str = "radar") -> dict[str, float]:
    """Veri dalındaki tüm havuz dosyalarının adresleri → en son hesap_usd (sabit payda yedeği)."""
    s = subprocess.run(["git", "ls-tree", "-r", "--name-only", f"origin/{dal}"], capture_output=True, text=True, check=True)
    adres: dict[str, float] = {}
    for yol in sorted(x for x in s.stdout.split() if x.endswith("/havuz.json") and "/son/" not in x):
        h = radar_isabet.git_oku(dal, yol) or {}
        for r in h.get("satirlar", []):
            adres[r["adres"]] = float(r.get("hesap_usd") or 0.0)
    return adres


# ------------------------------------------------------------------------------------------------------------------------------ analiz (saf)
def ciftler(kayit: dict[str, list[dict]]) -> list[dict]:
    """(adres, hafta t ölçüleri, hafta t+1 getirisi) çiftleri; t+1 getirisi None ise atlanır."""
    out = []
    for adres, hs in kayit.items():
        for a, b in zip(hs, hs[1:]):
            if a.get("durum") == "olculdu" and b.get("getiri") is not None:
                out.append({"adres": adres, "hafta": a["hafta_bas"], **{k: a.get(k) for k in ("dolum_gecti", "gecti_v1", "gecti_v11", *OLCULER)}, "sonraki": b["getiri"]})
    return out


def _ort(x: list[float]) -> float | None:
    return statistics.fmean(x) if x else None


def haftalik_fark(cs: list[dict], grup_a, grup_b) -> list[float]:
    """Hafta başına ort(sonraki | a) − ort(sonraki | b); iki grup da doluysa."""
    out = []
    for h in sorted({c["hafta"] for c in cs}):
        a = [c["sonraki"] for c in cs if c["hafta"] == h and grup_a(c)]
        b = [c["sonraki"] for c in cs if c["hafta"] == h and grup_b(c)]
        if a and b:
            out.append(statistics.fmean(a) - statistics.fmean(b))
    return out


def bootstrap_aralik(x: list[float], tekrar: int = BOOT_TEKRAR, tohum: int = BOOT_TOHUM) -> tuple[float | None, float | None]:
    """Hafta bloklu (hafta = blok) bootstrap ortalamanın %10–%90 aralığı."""
    if len(x) < 2:
        return None, None
    r = random.Random(tohum)
    ort = sorted(statistics.fmean(r.choices(x, k=len(x))) for _ in range(tekrar))
    return ort[int(0.10 * tekrar)], ort[int(0.90 * tekrar) - 1]


def spearman_haftalik(cs: list[dict], olcu: str) -> list[float]:
    out = []
    for h in sorted({c["hafta"] for c in cs}):
        g = [(c[olcu], c["sonraki"]) for c in cs if c["hafta"] == h and c.get("dolum_gecti") and c.get(olcu) is not None]
        if len(g) >= 5:
            r = radar_isabet.spearman([x for x, _ in g], [y for _, y in g])
            if r is not None:
                out.append(r)
    return out


def hukum(alt: float | None, ust: float | None) -> str:
    if alt is None:
        return "veri yetersiz"
    return "devam (kalıcılık var)" if alt > 0 else ("evren tasarımı değişmeli (ters)" if ust < 0 else "belirsiz")


def analiz(cs: list[dict]) -> dict:
    kopyali = lambda c: bool(c.get("dolum_gecti")) and c.get("kopya_getiri_7g") is not None     # noqa: E731
    testler = {
        "b_v1_gecen_eksi_gecmeyen": haftalik_fark(cs, lambda c: kopyali(c) and c["gecti_v1"], lambda c: kopyali(c) and not c["gecti_v1"]),
        "b_v11_gecen_eksi_gecmeyen": haftalik_fark(cs, lambda c: kopyali(c) and c["gecti_v11"], lambda c: kopyali(c) and not c["gecti_v11"]),
        "c_v1_gecen_islem10_eksi_az": haftalik_fark(cs, lambda c: c.get("gecti_v1") and (c.get("kopya_islem_sayisi") or 0) >= 10,
                                                    lambda c: c.get("gecti_v1") and (c.get("kopya_islem_sayisi") or 0) < 10),
    }
    sonuc: dict = {"cift": len(cs), "hafta": len({c["hafta"] for c in cs}), "test": {}, "spearman": {}, "grup_ort": {}}
    for k, x in testler.items():
        alt, ust = bootstrap_aralik(x)
        sonuc["test"][k] = {"hafta": len(x), "ort": _ort(x), "alt80": alt, "ust80": ust, "hukum": hukum(alt, ust)}
    for o in OLCULER:
        x = spearman_haftalik(cs, o)
        alt, ust = bootstrap_aralik(x)
        sonuc["spearman"][o] = {"hafta": len(x), "ort": _ort(x), "alt80": alt, "ust80": ust}
    for ad, f in (("v1_gecen", lambda c: c.get("gecti_v1")), ("v11_gecen", lambda c: c.get("gecti_v11")), ("kopyali_gecmeyen", lambda c: kopyali(c) and not c["gecti_v1"]),
                  ("tum_islemli", lambda c: c.get("dolum_gecti") is not None)):
        g = [c["sonraki"] for c in cs if f(c)]
        sonuc["grup_ort"][ad] = {"n": len(g), "ort_usd": None if not g else statistics.fmean(g) * 1000.0, "pozitif": sum(1 for v in g if v > 0)}
    return sonuc


def ozet_md(a: dict) -> str:
    y = lambda v: "—" if v is None else f"{v * 1000:+.2f} $"     # noqa: E731  (getiri oranı → 1.000 $ kasada $, trader başına bir hafta)
    s = ["## Kalıcılık testi (8 hafta, yalnız bilgi)", "", f"Çift (trader-hafta): {a['cift']}, hafta: {a['hafta']}", "",
         "| Test | Hafta | Ortalama fark | %80 aralık | Hüküm |", "|---|---|---|---|---|"]
    for k, t in a["test"].items():
        s.append(f"| {k} | {t['hafta']} | {y(t['ort'])} | {y(t['alt80'])} … {y(t['ust80'])} | {t['hukum']} |")
    s += ["", "| Ölçü → sonraki hafta | Hafta | Spearman ort. | %80 aralık |", "|---|---|---|---|"]
    for k, t in a["spearman"].items():
        f = lambda v: "—" if v is None else f"{v:+.3f}"     # noqa: E731
        s.append(f"| {k} | {t['hafta']} | {f(t['ort'])} | {f(t['alt80'])} … {f(t['ust80'])} |")
    s += ["", "| Grup (sonraki hafta) | n | Ort. $/trader-hafta | Pozitif |", "|---|---|---|---|"]
    for k, g in a["grup_ort"].items():
        s.append(f"| {k} | {g['n']} | {'—' if g['ort_usd'] is None else f'{g['ort_usd']:+.2f} $'} | {g['pozitif']}/{g['n']} |")
    return "\n".join(s) + "\n"


# ------------------------------------------------------------------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    alt = ap.add_subparsers(dest="komut", required=True)
    o = alt.add_parser("olc")
    o.add_argument("--parca", default="1/1", help="i/n: adres listesinin i. parçası (matris)")
    o.add_argument("--bitis-ms", type=int, default=None)
    o.add_argument("--cikti", type=Path, required=True)
    o.add_argument("--butce-dk", type=float, default=330.0)
    n = alt.add_parser("analiz")
    n.add_argument("dosyalar", nargs="+", type=Path)
    n.add_argument("--ozet-md", type=Path, default=None)
    a = ap.parse_args(argv)
    rules = load_rules()
    if a.komut == "olc":
        i, k = (int(x) for x in a.parca.split("/"))
        evren = evren_adresleri()
        adresler = sorted(evren)[i - 1::k]
        bitis = a.bitis_ms or int(time.time() * 1000)
        hf = haftalar(bitis)
        client = radar_tarama.radar_istemcisi(rules=rules)
        b = radar_tarama.Baglam(client, bitis, hf[0][0], rules)
        b.piyasa_oku()
        likit, mum = b.likit_coinler(), SaatlikMum(client, hf[0][0], hf[-1][1])
        print(f"kalıcılık: parça {i}/{k}, {len(adresler)}/{len(evren)} adres, haftalar {[pd.Timestamp(x, unit='ms').date().isoformat() for x, _ in hf]}")
        kayit, t0 = {}, time.monotonic()
        for j, adres in enumerate(adresler, 1):
            if time.monotonic() - t0 > a.butce_dk * 60:
                print(f"UYARI: süre bütçesi doldu; {len(adresler) - j + 1} adres ölçülmedi")
                break
            kayit[adres] = adres_olc(client, adres, evren[adres], hf, mum, likit, b.azami_kaldirac, rules)
            if j % 10 == 0:
                print(f"[{j}/{len(adresler)}] {(time.monotonic() - t0) / 60:.1f} dk")
        a.cikti.write_text(json.dumps({"parca": a.parca, "bitis_ms": bitis, "kayit": kayit}, ensure_ascii=False), encoding="utf-8")
        print(f"yazıldı: {a.cikti} ({len(kayit)} adres)")
        return 0
    kayit: dict = {}
    for d in a.dosyalar:
        kayit.update(json.loads(d.read_text(encoding="utf-8"))["kayit"])
    sonuc = analiz(ciftler(kayit))
    md = ozet_md(sonuc)
    print(md)
    print("KALICILIK_JSON " + json.dumps(sonuc, ensure_ascii=False))
    if a.ozet_md:
        a.ozet_md.write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
