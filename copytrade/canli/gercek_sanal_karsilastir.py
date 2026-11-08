"""S-12 (docs/DENETIM_PROJE_2026-11-08.md §2): gerçek kipin ilk N (varsayılan 50) emrini sanal dolum modeliyle YAN YANA raporlar (kural 6). Çevrimdışı; ağ YOK, emir YOK.

Girdi: gerçek kip `kayit/<tarih>.jsonl` (olay `emir`, `kip` = "gercek"); isteğe bağlı aynı pencerenin sanal `kayit` dizini.
Her gerçek emir için sanal taraf şu sırayla bulunur (`sanal_kaynak`):
1. `defter`   — emir satırında defter kaydı varsa (`defter` ya da `l2Book` = {"levels": [bids, asks]}): `SanalYurutucu.emir` AYNI defterle çağrılır (formül tekrar yazılmaz).
2. `sanal_kayit` — sanal kayıtta aynı (`adres`, `coin`, `eylem`, `trader_dolum_ms`) emri varsa: o satırın sanal sonucu kullanılır.
3. `referans_tek_seviye` — yalnız `referans_px` varsa: `SanalYurutucu.emir`, `referans_px`'te tek ve yeterince derin seviyeli defterle çağrılır
   (motor bugün defteri kaydetmiyor; bu, sanal modelin iyimser hâlidir: kayma 0, sz yuvarlanmaz).
4. `veri_yok` — hiçbiri yok (ör. emir öncesi hata, `referans_px` = null): sanal sütunlar boş.

Birimler: `usd_*`, `ucret*` $ (kasa ölçeği); `*_1000` = × 1.000 / `kasa_usd` (1.000 $ kopya ölçeği); `sz` coin; `px` $/coin; kayma oran (pozitif = aleyhimize);
`*_fark` = gerçek − sanal. Ayrıntı: docs/VERI_SOZLESMESI.md "Gerçek ↔ sanal karşılaştırma raporu".

    python -m copytrade.canli.gercek_sanal_karsilastir --gercek-kayit /var/lib/sg-canli/kayit [--sanal-kayit DIZIN] [--n 50] [--kasa-usd 1000] \
        [--sz-decimals sz.json] [--md rapor.md] [--json rapor.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from copytrade.canli.yurutucu import SanalYurutucu
from copytrade.kurallar import load_rules

DERIN_SZ = 1e12                       # referans_tek_seviye: tek seviyenin derinliği (coin) — emri asla sınırlamaz


def kayit_oku(dizin: Path) -> list[dict]:
    """`dizin/*.jsonl` satırları (tarih sırasıyla). Bozuk satır atlanır."""
    satirlar: list[dict] = []
    for f in sorted(Path(dizin).glob("*.jsonl")):
        for satir in f.read_text(encoding="utf-8").splitlines():
            satir = satir.strip()
            if not satir:
                continue
            try:
                k = json.loads(satir)
            except json.JSONDecodeError:
                continue
            if isinstance(k, dict):
                satirlar.append(k)
    return satirlar


def _anahtar(e: dict) -> tuple:
    return (e.get("adres"), e.get("coin"), e.get("eylem"), e.get("trader_dolum_ms"))


def _sira(e: dict) -> tuple:
    return (e.get("emir_ms") or e.get("zaman_ms") or 0, e.get("zaman_ms") or 0)


def _f(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def sanal_hesapla(e: dict, rules: dict) -> dict | None:
    """Sanal modeli (`SanalYurutucu.emir`) bu emrin girdileriyle çağırır. Defter yoksa `referans_px`'te tek seviye. İkisi de yoksa None."""
    kitap = e.get("defter") or e.get("l2Book")
    ref = _f(e.get("referans_px"))
    if isinstance(kitap, dict) and isinstance(kitap.get("levels"), list) and len(kitap["levels"]) == 2:
        kaynak = "defter"
    elif ref and ref > 0:
        kaynak = "referans_tek_seviye"
        seviye = [{"px": str(ref), "sz": str(DERIN_SZ), "n": 1}]
        kitap = {"levels": [seviye, seviye]}
    else:
        return None
    reduce_only = bool(e.get("reduce_only"))
    acik_sz = None
    biz = _f(e.get("biz_poz_usd"))
    if reduce_only and biz and ref:
        acik_sz = abs(biz) / ref                      # yaklaşık: motor `acik_sz`'yi kaydetmiyor; emir anı mark'ıyla nosyonel ÷ referans
    yur = SanalYurutucu(lambda _istek: kitap, rules, saat_ms=lambda: int(e.get("emir_ms") or 0))     # emir başına taze yürütücü: önceki emirlerin tüketimi düşülmez
    d = yur.emir(str(e.get("coin")), str(e.get("yon")), float(e.get("usd_istenen") or 0.0), reduce_only, acik_sz, bant=_f(e.get("bant")))
    return {"kaynak": kaynak, "durum": d.durum, "neden": d.neden, "sz": d.sz, "usd_dolan": d.usd_dolan, "dolum_px": d.px,
            "referans_px": d.referans_px, "kayma": d.kayma_oran, "ucret": d.ucret}


def _sanal_kayittan(s: dict) -> dict:
    return {"kaynak": "sanal_kayit", "durum": s.get("durum"), "neden": s.get("red_neden") or "", "sz": _f(s.get("sz")) or 0.0, "usd_dolan": _f(s.get("usd_dolan")) or 0.0,
            "dolum_px": _f(s.get("dolum_px")), "referans_px": _f(s.get("referans_px")), "kayma": _f(s.get("kayma_ref")), "ucret": _f(s.get("ucret")) or 0.0}


def _fark(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def karsilastir(gercek: list[dict], sanal: list[dict] | None = None, n: int = 50, kasa_usd: float | None = None, sz_decimals: dict[str, int] | None = None,
                rules: dict | None = None) -> dict:
    """Rapor sözlüğü: `satirlar` (emir başına) + `toplam` (özet tablo)."""
    rules = rules or load_rules()
    kasa = float(kasa_usd if kasa_usd is not None else rules.get("canli_kasa_usd", 1000))
    olcek = 1000.0 / kasa
    taker = float(rules["maliyet_taker"])
    sz_decimals = sz_decimals or {}
    emirler = sorted([k for k in gercek if k.get("olay") == "emir" and k.get("kip") == "gercek"], key=_sira)[: max(0, int(n))]
    tahmin_cloid = {k.get("cloid") for k in gercek if k.get("olay") == "ucret_tahmin" and k.get("cloid")}
    sanal_tablo: dict[tuple, dict] = {}
    for k in sorted([k for k in (sanal or []) if k.get("olay") == "emir" and k.get("kip") == "sanal"], key=_sira):
        sanal_tablo.setdefault(_anahtar(k), k)         # aynı anahtarda ilk sanal emir

    satirlar = []
    for e in emirler:
        s = None
        if e.get("defter") or e.get("l2Book"):
            s = sanal_hesapla(e, rules)
        if s is None and _anahtar(e) in sanal_tablo:
            s = _sanal_kayittan(sanal_tablo[_anahtar(e)])
        if s is None:
            s = sanal_hesapla(e, rules)
        g_sz, g_ucret, ref = _f(e.get("sz")) or 0.0, _f(e.get("ucret")) or 0.0, _f(e.get("referans_px"))
        dolu = g_sz > 0
        satir: dict[str, Any] = {
            "zaman_ms": e.get("emir_ms") or e.get("zaman_ms"), "coin": e.get("coin"), "yon": e.get("yon"), "eylem": e.get("eylem"), "reduce_only": bool(e.get("reduce_only")),
            "usd_istenen": _f(e.get("usd_istenen")), "referans_px": ref, "cloid": e.get("cloid"),
            "gercek_durum": e.get("durum"), "gercek_neden": e.get("red_neden") or "", "gercek_sz": g_sz, "gercek_usd_dolan": _f(e.get("usd_dolan")) or 0.0,
            "gercek_dolum_px": _f(e.get("dolum_px")), "gercek_kayma": _f(e.get("kayma_ref")), "gercek_ucret": g_ucret,
            "gercek_ucret_kesin": (e.get("cloid") not in tahmin_cloid) if dolu else None,       # G7: `ucret_tahmin` olayı yoksa ücret HL `fee`'dir
            "ucret_tahmini": (_f(e.get("usd_dolan")) or 0.0) * taker,                          # gerçek dolumun `maliyet_taker` tahmini ($)
            "sanal_kaynak": s["kaynak"] if s else "veri_yok",
        }
        if s:
            satir.update({"sanal_durum": s["durum"], "sanal_neden": s["neden"], "sanal_sz": s["sz"], "sanal_usd_dolan": s["usd_dolan"], "sanal_dolum_px": s["dolum_px"],
                          "sanal_kayma": s["kayma"], "sanal_ucret": s["ucret"], "durum_ayni": s["durum"] == e.get("durum"),
                          "sz_fark": g_sz - (s["sz"] or 0.0), "sz_fark_usd": (g_sz - (s["sz"] or 0.0)) * ref if ref else None,
                          "kayma_fark": _fark(satir["gercek_kayma"], s["kayma"]), "ucret_fark": g_ucret - (s["ucret"] or 0.0)})
        else:
            satir.update({k: None for k in ("sanal_durum", "sanal_neden", "sanal_sz", "sanal_usd_dolan", "sanal_dolum_px", "sanal_kayma", "sanal_ucret", "durum_ayni",
                                            "sz_fark", "sz_fark_usd", "kayma_fark", "ucret_fark")})
        dec = e.get("sz_decimals", sz_decimals.get(str(e.get("coin"))))
        usd = satir["usd_istenen"]
        if dec is not None and ref and usd:
            beklenen = round(usd / ref, int(dec))                      # GercekYurutucu.emir ile aynı yuvarlama: round(usd / en_iyi, szDecimals)
            satir["sz_decimals"] = int(dec)
            satir["yuvarlanmis_sz"] = beklenen
            satir["yuvarlama_kaynakli_kismi"] = (e.get("durum") == "kismi" and abs(g_sz - beklenen) < 0.5 * 10 ** -int(dec) and beklenen * ref < usd * 0.999)
        else:
            satir["sz_decimals"] = satir["yuvarlanmis_sz"] = satir["yuvarlama_kaynakli_kismi"] = None
        satirlar.append(satir)

    return {"n_istenen": int(n), "kasa_usd": kasa, "olcek_1000": olcek, "satirlar": satirlar, "toplam": _toplam(satirlar, olcek)}


def _oran(a: int, b: int) -> float | None:
    return a / b if b else None


def _toplam(satirlar: list[dict], olcek: float) -> dict:
    veri = [s for s in satirlar if s["sanal_kaynak"] != "veri_yok"]
    kfark = [s["kayma_fark"] for s in veri if s["kayma_fark"] is not None]
    ufark = sum(s["ucret_fark"] for s in veri)
    say = lambda liste, alan, deger: sum(1 for s in liste if s.get(alan) == deger)    # noqa: E731
    return {
        "emir": len(satirlar), "sanal_verili": len(veri), "veri_yok": len(satirlar) - len(veri),
        "sanal_kaynak": {k: say(satirlar, "sanal_kaynak", k) for k in ("defter", "sanal_kayit", "referans_tek_seviye", "veri_yok")},
        "gercek_red_orani": _oran(say(satirlar, "gercek_durum", "red"), len(satirlar)),
        "gercek_kismi_orani": _oran(say(satirlar, "gercek_durum", "kismi"), len(satirlar)),
        "gercek_dolmadi_orani": _oran(say(satirlar, "gercek_durum", "dolmadi"), len(satirlar)),
        "sanal_red_orani": _oran(say(veri, "sanal_durum", "red"), len(veri)),
        "sanal_kismi_orani": _oran(say(veri, "sanal_durum", "kismi"), len(veri)),
        "sanal_dolmadi_orani": _oran(say(veri, "sanal_durum", "dolmadi"), len(veri)),
        "durum_ayni_orani": _oran(say(veri, "durum_ayni", True), len(veri)),
        "yuvarlama_kaynakli_kismi": say(satirlar, "yuvarlama_kaynakli_kismi", True),
        "kayma_fark_n": len(kfark),
        "kayma_fark_medyan": statistics.median(kfark) if kfark else None,
        "kayma_fark_max": max(kfark) if kfark else None,
        "ucret_fark_toplam_usd": ufark if veri else None,
        "ucret_fark_toplam_1000": ufark * olcek if veri else None,
        "ucret_kesin_olmayan": say(satirlar, "gercek_ucret_kesin", False),
    }


def _s(v: Any, b: int = 6) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "evet" if v else "hayır"
    if isinstance(v, float):
        return f"{v:.{b}g}"
    return str(v)


def _y(v: float | None) -> str:
    return "—" if v is None else f"%{v * 100:.2f}"


def markdown(r: dict) -> str:
    t = r["toplam"]
    m = [f"# Gerçek ↔ sanal dolum karşılaştırması (S-12)", "",
         f"İlk {t['emir']} gerçek emir (istenen {r['n_istenen']}); kasa {r['kasa_usd']:g} $; 1.000 $ ölçek çarpanı {r['olcek_1000']:g}. Fark = gerçek − sanal; kayma oran, + = aleyhimize.", "",
         "## Özet", "", "| Ölçü | Gerçek | Sanal |", "|---|---|---|",
         f"| Emir (sanal verili / veri_yok) | {t['emir']} | {t['sanal_verili']} / {t['veri_yok']} |",
         f"| Red oranı | {_y(t['gercek_red_orani'])} | {_y(t['sanal_red_orani'])} |",
         f"| Kısmi oranı | {_y(t['gercek_kismi_orani'])} | {_y(t['sanal_kismi_orani'])} |",
         f"| Dolmadı oranı | {_y(t['gercek_dolmadi_orani'])} | {_y(t['sanal_dolmadi_orani'])} |",
         "", "| Fark ölçüsü | Değer |", "|---|---|",
         f"| Durum aynı (sanal verili) | {_y(t['durum_ayni_orani'])} |",
         f"| Yuvarlama kaynaklı kısmi (adet) | {t['yuvarlama_kaynakli_kismi']} |",
         f"| Kayma farkı medyan / max (n={t['kayma_fark_n']}) | {_s(t['kayma_fark_medyan'])} / {_s(t['kayma_fark_max'])} |",
         f"| Ücret farkı toplam ($, kasa) | {_s(t['ucret_fark_toplam_usd'])} |",
         f"| Ücret farkı toplam ($, 1.000 $ ölçek) | {_s(t['ucret_fark_toplam_1000'])} |",
         f"| Gerçek ücret tahmini (HL fee bulunamadı, adet) | {t['ucret_kesin_olmayan']} |",
         f"| Sanal kaynak | {', '.join(f'{k} {v}' for k, v in t['sanal_kaynak'].items())} |",
         "", "## Emirler", "",
         "| # | coin | yön | eylem | usd | durum G/S | sz G/S | sz farkı $ | yuv. kısmi | kayma G/S | ücret G/S | kaynak |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, s in enumerate(r["satirlar"], 1):
        m.append(f"| {i} | {s['coin']} | {s['yon']} | {s['eylem']} | {_s(s['usd_istenen'])} | {s['gercek_durum']} / {_s(s['sanal_durum'])} | {_s(s['gercek_sz'])} / {_s(s['sanal_sz'])} | "
                 f"{_s(s['sz_fark_usd'])} | {_s(s['yuvarlama_kaynakli_kismi'])} | {_s(s['gercek_kayma'])} / {_s(s['sanal_kayma'])} | {_s(s['gercek_ucret'])} / {_s(s['sanal_ucret'])} | {s['sanal_kaynak']} |")
    m += ["", "`referans_tek_seviye`: motor defteri kaydetmediği için sanal model `referans_px`'te sınırsız derinlikle koşuldu (iyimser üst sınır: kayma 0, sz yuvarlanmaz)."]
    return "\n".join(m) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gercek-kayit", type=Path, required=True, help="gerçek kip kayit dizini (*.jsonl)")
    ap.add_argument("--sanal-kayit", type=Path, help="aynı pencerenin sanal kayit dizini (isteğe bağlı)")
    ap.add_argument("--n", type=int, default=50, help="ilk N gerçek emir (varsayılan 50)")
    ap.add_argument("--kasa-usd", type=float, help="gerçek kasa $ (varsayılan kurallar.yaml canli_kasa_usd)")
    ap.add_argument("--sz-decimals", type=Path, help="JSON {coin: szDecimals} (HL meta); yoksa yuvarlama sütunları boş")
    ap.add_argument("--md", type=Path, help="Markdown çıktı dosyası (yoksa stdout)")
    ap.add_argument("--json", type=Path, help="JSON çıktı dosyası")
    a = ap.parse_args(argv)
    if not a.gercek_kayit.is_dir():
        print(f"dizin yok: {a.gercek_kayit}", file=sys.stderr)
        return 2
    sz_dec = json.loads(a.sz_decimals.read_text(encoding="utf-8")) if a.sz_decimals else None
    r = karsilastir(kayit_oku(a.gercek_kayit), kayit_oku(a.sanal_kayit) if a.sanal_kayit else None, a.n, a.kasa_usd, sz_dec)
    md = markdown(r)
    if a.md:
        a.md.write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)
    if a.json:
        a.json.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    if not r["satirlar"]:
        print("uyarı: gerçek kip emir satırı bulunamadı", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
