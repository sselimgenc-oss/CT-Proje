"""v1.1 aday sınaması — kayıtlı havuzlarla geriye dönük karşılaştırma (YALNIZ BİLGİ; DENETIM_SECIM_2026-11-08 §3, K‑47).

Kurallar DEĞİŞMEZ; motor, kadro ve kurallar.yaml'a dokunmaz; veri dallarına yazmaz. Her kayıtlı gün (D) için:
1. Günün İLK kadrosu + havuzu (`radar_isabet.gun_oku`; motor bunu uygular).
2. Seçim varyantları — İlk 11 aynı form sırasından, yalnız aday kuralı değişerek kurulur:
   `v1` (fiili İlk 11), `h_siz` (H'siz form sırası), `kopya_islem_5` (kopya kapanan işlem ≥ 5), `t_2` (G t‑istatistiği ≥ 2),
   `karli_gun_3` (kopya kârlı gün ≥ 3/7, pürüzsüz ölçü vekili). Kural boş koltuk bırakırsa koltuk NAKİTTE kalır (getiri 0).
3. `kopya_islem_sayisi` / `g_t_istat` havuzda yoksa (09.11 öncesi) D penceresi yeniden oynatılır (aynı `kopya_v5` + `kopya_olculeri`).
4. İleri getiri: D koşusundan şimdiye kadar, R1 ile AYNI kopya oynatması (`radar_isabet.olc` ile aynı yol, 1 dk gecikme + maliyet, B8 payda).
5. Nedene bağlı çıkış: D'de kadrodan çıkanlar neden grubuna göre (`r0_disi` = yalnız ilk 300'den düştü → v1.1'de kalırdı; `r1:*` = gerçek kötüleşme) ileri getirileri.

Kasa getirisi = Σ seçilenlerin ileri getirisi / 11 (her koltuk kasanın 1/11'i; boş koltuk 0). Örneklem çok küçük: sonuç YÖN gösterir, karar vermez.

    python -m copytrade.v11_sinama --veri-dali radar --tarih 2026-11-05 2026-11-06 2026-11-07 2026-11-08 --ozet-md v11.md
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

from copytrade import radar_form, radar_isabet, radar_kadro, radar_tarama
from copytrade.kurallar import load_rules
from copytrade.olcut import perp_fills

VARYANTLAR = ("v1", "h_siz", "kopya_islem_5", "t_2", "karli_gun_3")
ACIKLAMA = {"v1": "Şimdiki kural (fiili İlk 11)", "h_siz": "H çıkarılmış form sırası", "kopya_islem_5": "Kopya işlem ≥ 5",
            "t_2": "t ≥ 2 (sıkı şans testi)", "karli_gun_3": "Kopya kârlı gün ≥ 3/7"}
ESIK_ISLEM, ESIK_T, ESIK_KARLI = 5, 2.0, 3 / 7          # aday eşikleri (DENETIM_SECIM §3); kurallar.yaml'a GİRMEZ (bilgi sınaması)


# ------------------------------------------------------------------------------------------------------------------------------ saf fonksiyonlar
def varyant_sec(kadro: dict, olcu: dict[str, dict], rules: dict, ilk: int = 11) -> dict[str, list[str]]:
    """Kadro satırları (form sırası) + aday ölçüleri {adres: {kis, t, karli}} → {varyant: İlk 11 adresleri}. Ölçü yoksa (None) aday kuralı GEÇMEZ (temkinli)."""
    sirali = sorted(kadro.get("satirlar", []), key=lambda s: s["sira"])
    v1 = [s["adres"] for s in sirali if s.get("katman") == "ilk11"][:ilk]
    hsiz = {s["adres"]: (s["form_h_siz"] if s.get("form_h_siz") is not None else radar_form.form_h_siz(s["bilesenler"], rules)) for s in sirali}

    def filtre(kosul: Callable[[dict], bool]) -> list[str]:
        return [s["adres"] for s in sirali if kosul(olcu.get(s["adres"], {}))][:ilk]

    def ge(anahtar: str, esik: float) -> Callable[[dict], bool]:
        return lambda o: o.get(anahtar) is not None and o[anahtar] >= esik - 1e-12

    return {"v1": v1, "h_siz": sorted(hsiz, key=lambda a: (-hsiz[a], a))[:ilk], "kopya_islem_5": filtre(ge("kis", ESIK_ISLEM)),
            "t_2": filtre(ge("t", ESIK_T)), "karli_gun_3": filtre(ge("karli", ESIK_KARLI))}


def kasa_getirisi(secilen: list[str], ileri: dict[str, float | None], ilk: int = 11) -> tuple[float | None, int, int]:
    """(kasa getirisi = Σ ölçülen / ilk, ölçülen sayısı, ölçülemeyen sayısı). Ölçülemeyen varsa getiri yine yazılır (0 sayılmaz, atlanır) ama sayısı raporlanır; hiç seçilen yoksa 0."""
    olculen = [ileri[a] for a in secilen if ileri.get(a) is not None]
    eksik = len(secilen) - len(olculen)
    if secilen and not olculen:
        return None, 0, eksik
    return sum(olculen) / ilk, len(olculen), eksik


def ozet(gunler: list[dict]) -> dict:
    """Günlük sonuçlardan varyant başına: ortalama kasa getirisi, v1'e fark (gün gün eşli), v1'den iyi gün sayısı; çıkış nedeni grupları."""
    var = {}
    for v in VARYANTLAR:
        degerler = [(g["varyant"][v]["kasa"], g["varyant"]["v1"]["kasa"]) for g in gunler if g["varyant"][v]["kasa"] is not None and g["varyant"]["v1"]["kasa"] is not None]
        farklar = [a - b for a, b in degerler]
        var[v] = {"gun": len(degerler), "ort_kasa": statistics.fmean(a for a, _ in degerler) if degerler else None,
                  "ort_fark_v1": statistics.fmean(farklar) if farklar else None, "iyi_gun": sum(1 for f in farklar if f > 1e-12),
                  "kotu_gun": sum(1 for f in farklar if f < -1e-12), "ort_koltuk": statistics.fmean(len(g["varyant"][v]["secilen"]) for g in gunler) if gunler else None}
    cikis: dict[str, list[float]] = {}
    for g in gunler:
        for c in g["cikanlar"]:
            if c["ileri"] is not None:
                cikis.setdefault(c["grup"], []).append(c["ileri"])
    return {"varyant": var, "cikis": {k: {"n": len(v), "ort": statistics.fmean(v), "pozitif": sum(1 for x in v if x > 0)} for k, v in sorted(cikis.items())}}


def _yuzde(x: float | None, isaret: bool = False) -> str:
    return "—" if x is None else (f"{x * 100:+.2f}%" if isaret else f"{x * 100:.2f}%")


def ozet_md(gunler: list[dict], oz: dict) -> str:
    s = ["## v1.1 aday sınaması (geriye dönük, yalnız bilgi)", "",
         "Kasa getirisi = seçilenlerin kopya getirisi toplamı / 11 (boş koltuk nakit). Pencere: havuz koşusundan ölçüm anına.", "",
         "| Gün | Pencere (gün) | " + " | ".join(VARYANTLAR) + " |", "|---|---|" + "---|" * len(VARYANTLAR)]
    for g in gunler:
        s.append(f"| {g['tarih']} | {g['pencere_gun']:.1f} | " + " | ".join(
            f"{_yuzde(g['varyant'][v]['kasa'], True)} ({len(g['varyant'][v]['secilen'])})" for v in VARYANTLAR) + " |")
    s += ["", "| Varyant | Açıklama | Ort. kasa | v1'e fark | v1'den iyi / kötü gün | Ort. koltuk |", "|---|---|---|---|---|---|"]
    for v in VARYANTLAR:
        o = oz["varyant"][v]
        s.append(f"| {v} | {ACIKLAMA[v]} | {_yuzde(o['ort_kasa'], True)} | {_yuzde(o['ort_fark_v1'], True)} | {o['iyi_gun']} / {o['kotu_gun']} | "
                 f"{'—' if o['ort_koltuk'] is None else f'{o['ort_koltuk']:.1f}'} |")
    s += ["", "**Kadrodan çıkanlar — ileri kopya getirisi (nedene göre):**", "", "| Neden | n | Ortalama | Pozitif |", "|---|---|---|---|"]
    for k, o in oz["cikis"].items():
        s.append(f"| {k} | {o['n']} | {_yuzde(o['ort'], True)} | {o['pozitif']}/{o['n']} |")
    return "\n".join(s) + "\n"


# ------------------------------------------------------------------------------------------------------------------------------ ağ
def _dolumlar(client: Any, adres: str, bas: int, bit: int, rules: dict) -> list[dict] | None:
    d = client.fills(adres, bas, max_rows=int(rules["radar_dolum_tavan"]), end_ms=bit)
    if len(d) >= int(rules["radar_dolum_tavan"]):
        return None
    return [f for f in perp_fills(d) if bas <= int(f["time"]) < bit]


def gecmis_olcu(client: Any, havuz: dict, adresler: list[str], rules: dict, log: Callable[[str], None]) -> dict[str, dict]:
    """D penceresi için {adres: {kis, t, karli}}. Havuzda dolu ise oradan (09.11+); değilse pencere yeniden oynatılır."""
    satir = {r["adres"]: r for r in havuz["satirlar"]}
    olcu: dict[str, dict] = {}
    gerek = [a for a in adresler if satir.get(a, {}).get("kopya_islem_sayisi") is None]
    for a in adresler:
        r = satir.get(a, {})
        olcu[a] = {"kis": r.get("kopya_islem_sayisi"), "t": r.get("g_t_istat"), "karli": r.get("kopya_kazanc_gun_orani"), "kaynak": "havuz"}
    if not gerek:
        return olcu
    bas, bit = int(havuz["pencere_bas_ms"]), int(havuz["kosu_ms"])
    b = radar_tarama.Baglam(client, bit, bas, rules)
    b.piyasa_oku()
    for a in gerek:
        try:
            d = _dolumlar(client, a, bas, bit, rules)
            if d is None:
                continue
            payda, _ = radar_tarama.payda_oku(client, a, float(satir[a]["hesap_usd"]), bas, bit, rules)
            m = radar_tarama.kopya_olculeri(b.kopya_oynat(d, payda), a, rules)
            olcu[a].update({"kis": m["kopya_islem_sayisi"], "t": m["g_t_istat"], "kaynak": "yeniden", "kopya_getiri_yeniden": m["kopya_getiri_7g"],
                            "kopya_getiri_havuz": satir[a].get("kopya_getiri_7g")})
        except radar_tarama.HATALAR as h:
            log(f"UYARI: {a[:10]}… geçmiş oynatma {type(h).__name__}")
        log(f"geçmiş {a[:10]}… kis {olcu[a]['kis']} t {olcu[a]['t']}")
    return olcu


def ileri_getiri(client: Any, havuz: dict, adresler: list[str], bit: int, rules: dict, log: Callable[[str], None]) -> dict[str, float | None]:
    """D koşusundan `bit`'e kopya getirisi (radar_isabet.olc ile aynı yol: pencerede dolum yok → 0; dolum_fazla / payda yok → None)."""
    bas = int(havuz["kosu_ms"])
    b = radar_tarama.Baglam(client, bit, bas, rules)
    b.piyasa_oku()
    hesap = {r["adres"]: float(r["hesap_usd"]) for r in havuz["satirlar"]}
    sonuc: dict[str, float | None] = {}
    for a in adresler:
        g = None
        try:
            d = _dolumlar(client, a, bas, bit, rules)
            if d is not None:
                if not d:
                    g = 0.0
                else:
                    payda, bilgi = radar_tarama.payda_oku(client, a, hesap.get(a, 0.0), bas, bit, rules)
                    if a in hesap or bilgi["payda_kaynak"] == "portfolio":
                        g = radar_isabet.getiri_al(b.kopya_oynat(d, payda))
        except radar_tarama.HATALAR as h:
            log(f"UYARI: {a[:10]}… ileri {type(h).__name__}")
        sonuc[a] = g
        log(f"ileri {a[:10]}… {g}")
    return sonuc


def cikis_grubu(neden: str) -> str:
    return "r0_disi (v1.1'de kalırdı)" if neden == "r0_disi" else ("r1 (gerçek kötüleşme)" if neden.startswith("r1:") else neden)


def gun_sina(client: Any, dal: str, tarih: str, simdi: int, rules: dict, log: Callable[[str], None]) -> dict | None:
    havuz, kadro, kaynak = radar_isabet.gun_oku(dal, tarih, log)
    if not havuz or not kadro:
        log(f"{tarih}: havuz/kadro yok; atlandı")
        return None
    adresler = [s["adres"] for s in kadro["satirlar"]]
    onceki = radar_isabet.onceki_kadro_oku(dal, tarih)
    neden = kadro.get("eski_uye_neden") if isinstance(kadro.get("eski_uye_neden"), dict) else None
    if neden is None and onceki:
        puanli, soguyan = radar_form.form_puanla(havuz["satirlar"], rules)
        _, neden = radar_kadro.onceki_karsilastir(onceki, havuz, kadro["satirlar"], soguyan)
    cikan = {a: n for a, n in (neden or {}).items() if a not in set(adresler)}
    olcu = gecmis_olcu(client, havuz, adresler, rules, log)
    secim = varyant_sec(kadro, olcu, rules, int(rules["radar_kadro_ilk"]))
    ileri = ileri_getiri(client, havuz, adresler + sorted(cikan), simdi, rules, log)
    ilk = int(rules["radar_kadro_ilk"])
    varyant = {}
    for v, sec in secim.items():
        k, n, e = kasa_getirisi(sec, ileri, ilk)
        varyant[v] = {"secilen": sec, "kasa": k, "olculen": n, "eksik": e}
    return {"tarih": tarih, "kadro_kaynagi": kaynak, "pencere_gun": (simdi - int(havuz["kosu_ms"])) / 86_400_000, "olcu": olcu, "ileri": ileri, "varyant": varyant,
            "cikanlar": [{"adres": a, "neden": n, "grup": cikis_grubu(n), "ileri": ileri.get(a)} for a, n in sorted(cikan.items())]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--veri-dali", default="radar")
    ap.add_argument("--tarih", nargs="+", required=True)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--ozet-md", type=Path, default=None)
    a = ap.parse_args(argv)
    rules = load_rules()
    simdi = int(time.time() * 1000)
    client = radar_tarama.radar_istemcisi(rules=rules)
    gunler = [g for t in a.tarih if (g := gun_sina(client, a.veri_dali, t, simdi, rules, print))]
    oz = ozet(gunler)
    md = ozet_md(gunler, oz)
    print(md)
    print("V11_JSON " + json.dumps({"ozet": oz, "gunler": [{k: g[k] for k in ("tarih", "pencere_gun", "varyant", "cikanlar", "olcu")} for g in gunler]}, ensure_ascii=False, default=str))
    if a.json:
        a.json.write_text(json.dumps({"ozet": oz, "gunler": gunler}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if a.ozet_md:
        a.ozet_md.write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
