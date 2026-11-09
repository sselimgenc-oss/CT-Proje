"""Günlük kadro (docs/RADAR_V1.md §5; görev T3 §3): T2 `havuz.json` → R2 form puanı → sıra = form azalan; 1–11 `ilk11`, 12–30 `yedek`. Saha kararları (slot −%10, bekleme, günde 2 değişiklik) burada DEĞİL:
T4 motoru `kadro.json`'u okuyup §5 kurallarını uygular.

    python -m copytrade.radar_kadro --havuz radar/2026-11-05/havuz.json [--kasa 1000] [--onceki-kadro onceki/kadro.json]    # → radar/2026-11-05/kadro.json

`kadro.json` (docs/VERI_SOZLESMESI.md "Radar kadro"): {sema "radar-kadro-v1", kosu_ms, kasa_usd, slot_usd, saha_n, gecti_sayisi, soguyan[], satirlar[{adres, sira, katman, form, bilesenler{G,K,I1,I2,Y,H},
kopya_getiri_7g, max_kaldirac, form_h_siz, sira_h_siz}], korelasyon{adresler, gun_sayisi, matris}, h_siz_girenler[], onceki_kosu_ms, elenenler[], eski_uye_neden{}}.
`form_h_siz`/`sira_h_siz`/`h_siz_girenler`/`onceki_kosu_ms`/`elenenler`/`eski_uye_neden` YALNIZ BİLGİDİR: seçim, sıra ve eşikler değişmez (karar `form`'dadır). Eksik koşuda (zaman bütçesi aşıldı / satır eksik / `veri_hatasi` payı > `radar_veri_hatasi_pay_max`, R-2) kadro YAZILMAZ ve çıkış kodu 2 (`radar.yml` `son/` yayımlamaz)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from copytrade import boyut
from copytrade.kurallar import load_rules
from copytrade.radar_form import form_h_siz, form_puanla, korelasyon

SEMA = "radar-kadro-v1"
HAVUZ_SEMA = "radar-havuz-v1"


def kosu_tam_mi(havuz: dict, rules: dict | None = None) -> tuple[bool, str | None]:
    """Koşu tam mı: `zaman_yok` satırı yok, satır sayısı = min(`radar_aday_tavan`, evren_toplam) ve (R-2, 06.11 denetimi) `veri_hatasi` satırlarının payı ≤ `radar_veri_hatasi_pay_max`
    (HL kesintisinde küçük/boş kadro "taze" yayımlanmasın; tam sınır tamdır). Değilse (False, neden). Aday sayısı kurala göredir (deneme `--aday-sayisi` koşuları `radar.yml`'de yok)."""
    rules = rules or load_rules()
    satirlar = havuz["satirlar"]
    zaman_yok = sum(1 for s in satirlar if s.get("neden") == "zaman_yok")
    if zaman_yok:
        return False, f"{zaman_yok} aday zaman_yok (zaman bütçesi aşıldı)"
    beklenen = min(int(rules["radar_aday_tavan"]), int(havuz["evren_toplam"]))
    if len(satirlar) < beklenen:
        return False, f"satır {len(satirlar)} < beklenen {beklenen}"
    hatali = sum(1 for s in satirlar if s.get("neden") == "veri_hatasi")
    esik = float(rules["radar_veri_hatasi_pay_max"])
    if satirlar and hatali / len(satirlar) > esik + 1e-12:
        return False, f"{hatali}/{len(satirlar)} satır veri_hatasi (pay {hatali / len(satirlar):.3f} > {esik:g})"
    return True, None


def onceki_karsilastir(onceki: dict | None, havuz: dict, satirlar: list[dict], soguyan: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """BİLGİ AMAÇLI. Önceki kadronun (`onceki`, radar-kadro-v1) bugünkü kadroda OLMAYAN üyeleri için neden (bugünkü havuza göre):
    `soguyan` (R1'i geçti ama form sürmüyor) · `r1:<neden>` (havuzda, `gecti` false) · `r0_disi` (havuzda yok: 7 g getiri ilk `radar_aday_tavan`'dan düştü) · `sira_disi` (puanlandı, form sırası > kadro).
    `elenenler` = bunlardan R1'de elenenler [{adres, onceki_sira, neden}] (önceki sıra artan). `onceki` None → ([], {})."""
    if not onceki:
        return [], {}
    if onceki.get("sema") != SEMA:
        raise ValueError(f"önceki kadro şeması {SEMA} olmalı: {onceki.get('sema')!r}")
    bugun = {s["adres"] for s in satirlar}
    havuz_satiri = {s["adres"]: s for s in havuz["satirlar"]}
    soguyan_adres = {s["adres"] for s in soguyan}
    elenenler, neden = [], {}
    for u in sorted(onceki.get("satirlar") or [], key=lambda u: u["sira"]):
        a = u["adres"]
        if a in bugun:
            continue
        h = havuz_satiri.get(a)
        if h is None:
            neden[a] = "r0_disi"
        elif not h.get("gecti"):
            neden[a] = f"r1:{h.get('neden')}"
            elenenler.append({"adres": a, "onceki_sira": u["sira"], "neden": h.get("neden")})
        elif a in soguyan_adres:
            neden[a] = "soguyan"
        else:
            neden[a] = "sira_disi"
    return elenenler, neden


def sirala_v11(puanli: list[dict], havuz_satiri: dict[str, dict], rules: dict) -> list[dict]:
    """v1.1 (K-53, kullanıcı kararı 09.11) t önceliği: `g_t_istat` ≥ `radar_t_oncelik` olanlar ÖNCE (kendi içinde form sırası), kalan koltuklar form sırasıyla dolar (kasa boş kalmaz).
    `radar_t_oncelik` ≤ 0 → v1 (yalnız form sırası). Her satıra `t_oncelik` (bool) eklenir; eşitlikte adres."""
    esik = float(rules.get("radar_t_oncelik", 0) or 0)

    def oncelikli(p: dict) -> bool:
        t = havuz_satiri.get(p["adres"], {}).get("g_t_istat")
        return esik > 0 and t is not None and float(t) >= esik - 1e-12

    cikti = [{**p, "t_oncelik": oncelikli(p)} for p in puanli]
    cikti.sort(key=lambda p: (not p["t_oncelik"], -p["form"], p["adres"]))
    return cikti


def kadro_olustur(havuz: dict, rules: dict | None = None, kasa_usd: float | None = None, onceki: dict | None = None) -> dict:
    """Havuz → kadro (saf fonksiyon). `kasa_usd` verilmezse `canli_kasa_usd`; slot = kasa / N (`boyut`, K‑28). Havuzda 30'dan az `gecti` varsa kadro o kadardır.
    `onceki` (önceki günün kadrosu, isteğe bağlı) yalnız bilgi alanları `elenenler`/`eski_uye_neden` içindir; seçimi etkilemez."""
    rules = rules or load_rules()
    if havuz.get("sema") != HAVUZ_SEMA:
        raise ValueError(f"havuz şeması {HAVUZ_SEMA} olmalı: {havuz.get('sema')!r}")
    kasa = float(rules["canli_kasa_usd"] if kasa_usd is None else kasa_usd)
    n = boyut.saha_sayisi(kasa, rules)
    puanli, soguyan = form_puanla(havuz["satirlar"], rules)
    havuz_satiri = {h["adres"]: h for h in havuz["satirlar"]}
    puanli = sirala_v11(puanli, havuz_satiri, rules)
    toplam, ilk = int(rules["radar_kadro_toplam"]), int(rules["radar_kadro_ilk"])
    secilen = puanli[:toplam]
    # Bilgi: H'siz form ve tüm puanlı havuzdaki sırası (eşitlikte adres; karar sırası `form`'dur)
    hsiz = {p["adres"]: form_h_siz(p["bilesenler"], rules) for p in puanli}
    hsiz_sira = {a: i for i, a in enumerate(sorted(hsiz, key=lambda a: (-hsiz[a], a)), 1)}
    satirlar = [{"adres": p["adres"], "sira": i, "katman": "ilk11" if i <= ilk else "yedek", "form": p["form"], "bilesenler": p["bilesenler"],
                 "kopya_getiri_7g": p["kopya_getiri_7g"], "max_kaldirac": p["max_kaldirac"], "form_h_siz": hsiz[p["adres"]], "sira_h_siz": hsiz_sira[p["adres"]],
                 "g_t_istat": havuz_satiri[p["adres"]].get("g_t_istat"), "t_oncelik": p["t_oncelik"], "tutma": bool(havuz_satiri[p["adres"]].get("tutma"))}
                for i, p in enumerate(secilen, 1)]
    secilen_adres = {p["adres"] for p in secilen}
    h_siz_girenler = [{"adres": a, "sira_h_siz": hsiz_sira[a], "form_h_siz": hsiz[a]} for a in sorted(hsiz_sira, key=hsiz_sira.get)
                      if hsiz_sira[a] <= toplam and a not in secilen_adres]
    elenenler, eski_uye_neden = onceki_karsilastir(onceki, havuz, satirlar, soguyan)
    return {"sema": SEMA, "kosu_ms": havuz["kosu_ms"], "kasa_usd": kasa, "slot_usd": boyut.slot_usd(kasa, rules), "saha_n": n,
            "gecti_sayisi": sum(1 for s in havuz["satirlar"] if s.get("gecti")), "soguyan": soguyan, "satirlar": satirlar,
            "korelasyon": korelasyon([{"adres": p["adres"], "kopya_gunluk": p["kopya_gunluk"]} for p in secilen]),          # K-45 eki (08.11): tüm kadro (İlk 11 + Yedek); Yedek boş slota girebildiği için benzerlik denetimi onları da kapsar
            "h_siz_girenler": h_siz_girenler, "onceki_kosu_ms": (onceki or {}).get("kosu_ms"), "elenenler": elenenler, "eski_uye_neden": eski_uye_neden}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--havuz", type=Path, required=True)
    ap.add_argument("--cikti", type=Path, default=None, help="varsayılan: havuz.json'ın yanına kadro.json")
    ap.add_argument("--kasa", type=float, default=None, help="kasa $ (varsayılan kurallar.yaml canli_kasa_usd)")
    ap.add_argument("--onceki-kadro", type=Path, default=None, help="önceki günün kadro.json'u (yalnız bilgi: elenenler, eski_uye_neden); yoksa boş")
    args = ap.parse_args(argv)
    rules = load_rules()
    havuz = json.loads(args.havuz.read_text(encoding="utf-8"))
    tam, neden = kosu_tam_mi(havuz, rules)
    if not tam:
        print(f"EKSİK KOŞU: {neden}; kadro yazılmadı", file=sys.stderr)
        return 2
    onceki = json.loads(args.onceki_kadro.read_text(encoding="utf-8")) if args.onceki_kadro else None
    kadro = kadro_olustur(havuz, rules, args.kasa, onceki)
    cikti = args.cikti or args.havuz.with_name("kadro.json")
    gecici = cikti.with_suffix(".json.tmp")
    gecici.write_text(json.dumps(kadro, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    gecici.replace(cikti)
    print(f"kadro: {len(kadro['satirlar'])} kişi (ilk11 {sum(1 for s in kadro['satirlar'] if s['katman'] == 'ilk11')}, yedek {sum(1 for s in kadro['satirlar'] if s['katman'] == 'yedek')}), "
          f"gecti {kadro['gecti_sayisi']}, soğuyan {len(kadro['soguyan'])}, kasa {kadro['kasa_usd']:.0f} $, slot {kadro['slot_usd']:.2f} $ → {cikti}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
