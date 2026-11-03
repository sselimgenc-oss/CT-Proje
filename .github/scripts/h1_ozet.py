"""H1 deneme özeti (geçici iş akışı `gecikme_kar_deneme.yml`): tablo, sütun min/medyan/maks, mevcut izleme v3 ↔ H1 yan yana."""
import json
import statistics

iz = {t["id"]: t for t in json.load(open("izleme_h1/durum.json"))["traderlar"]}
yuzde = lambda x: "—" if x is None else f"{x * 100:+.3f}%"
for ad in ("h1_dakika", "h1_tam"):
    d = json.load(open(f"{ad}/gecikme_kar.json"))
    print(f"\n### {ad} (pencere={d['pencere']}, uretildi={d['uretildi']}, maliyet={d['maliyet']})\n")
    print(open(f"{ad}/gecikme_kar.md").read())
    if d["hatalar"]:
        print("HATALAR:", d["hatalar"])
    satirlar = [(t["id"], g, h) for t in d["traderlar"] for g, h in t["gecikmeler"].items()]
    print("\nsütun özeti (min / medyan / maks), trader x gecikme satırları:")
    print(f"- satır sayısı: {len(satirlar)} (trader {len(d['traderlar'])} x gecikme 5)")
    for alan in ("net", "islem", "fiyatsiz", "bekleyen", "yaklasik"):
        v = [h[alan] for _, _, h in satirlar if h[alan] is not None]
        print(f"- {alan}: min {min(v):.6g} / medyan {statistics.median(v):.6g} / maks {max(v):.6g} (n={len(v)})" if v else f"- {alan}: veri yok")
    if ad == "h1_tam":
        print("\n#### mevcut izleme v3 (durum.json) ↔ H1 mevcut gecikme neti (aynı t0 penceresi; okuma anları arası küçük sapma beklenir)\n")
        print("| id | tarz | mevcut gecikme dk | izleme v3 getiri | H1 net | fark |\n|---|---|---|---|---|---|")
        for t in d["traderlar"]:
            v3 = (iz.get(t["id"]) or {}).get("sanal_kopya_v3") or {}
            a, b = v3.get("getiri"), t["mevcut_net"]
            print(f"| {t['id']} | {t['tarz']} | {t['mevcut_gecikme_dk']} | {yuzde(a)} | {yuzde(b)} | {yuzde(None if a is None or b is None else b - a)} |")
