"""Günlük kadro (docs/RADAR_V1.md §5; görev T3 §3): T2 `havuz.json` → R2 form puanı → sıra = form azalan; 1–11 `ilk11`, 12–30 `yedek`. Saha kararları (slot −%10, bekleme, günde 2 değişiklik) burada DEĞİL:
T4 motoru `kadro.json`'u okuyup §5 kurallarını uygular.

    python -m copytrade.radar_kadro --havuz radar/2026-11-05/havuz.json [--kasa 1000]    # → radar/2026-11-05/kadro.json

`kadro.json` (docs/VERI_SOZLESMESI.md "Radar kadro"): {sema "radar-kadro-v1", kosu_ms, kasa_usd, slot_usd, saha_n, gecti_sayisi, soguyan[], satirlar[{adres, sira, katman, form, bilesenler{G,K,I1,I2,Y,H},
kopya_getiri_7g, max_kaldirac}], korelasyon{adresler, gun_sayisi, matris}}. Eksik koşuda (zaman bütçesi aşıldı / satır eksik) kadro YAZILMAZ ve çıkış kodu 2 (`radar.yml` `son/` yayımlamaz)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from copytrade import boyut
from copytrade.kurallar import load_rules
from copytrade.radar_form import form_puanla, korelasyon

SEMA = "radar-kadro-v1"
HAVUZ_SEMA = "radar-havuz-v1"


def kosu_tam_mi(havuz: dict, rules: dict | None = None) -> tuple[bool, str | None]:
    """Koşu tam mı: `zaman_yok` satırı yok ve satır sayısı = min(`radar_aday_tavan`, evren_toplam). Değilse (False, neden). Aday sayısı kurala göredir (deneme `--aday-sayisi` koşuları `radar.yml`'de yok)."""
    rules = rules or load_rules()
    satirlar = havuz["satirlar"]
    zaman_yok = sum(1 for s in satirlar if s.get("neden") == "zaman_yok")
    if zaman_yok:
        return False, f"{zaman_yok} aday zaman_yok (zaman bütçesi aşıldı)"
    beklenen = min(int(rules["radar_aday_tavan"]), int(havuz["evren_toplam"]))
    if len(satirlar) < beklenen:
        return False, f"satır {len(satirlar)} < beklenen {beklenen}"
    return True, None


def kadro_olustur(havuz: dict, rules: dict | None = None, kasa_usd: float | None = None) -> dict:
    """Havuz → kadro (saf fonksiyon). `kasa_usd` verilmezse `canli_kasa_usd`; slot = kasa / N (`boyut`, K‑28). Havuzda 30'dan az `gecti` varsa kadro o kadardır."""
    rules = rules or load_rules()
    if havuz.get("sema") != HAVUZ_SEMA:
        raise ValueError(f"havuz şeması {HAVUZ_SEMA} olmalı: {havuz.get('sema')!r}")
    kasa = float(rules["canli_kasa_usd"] if kasa_usd is None else kasa_usd)
    n = boyut.saha_sayisi(kasa, rules)
    puanli, soguyan = form_puanla(havuz["satirlar"], rules)
    toplam, ilk = int(rules["radar_kadro_toplam"]), int(rules["radar_kadro_ilk"])
    secilen = puanli[:toplam]
    satirlar = [{"adres": p["adres"], "sira": i, "katman": "ilk11" if i <= ilk else "yedek", "form": p["form"], "bilesenler": p["bilesenler"],
                 "kopya_getiri_7g": p["kopya_getiri_7g"], "max_kaldirac": p["max_kaldirac"]} for i, p in enumerate(secilen, 1)]
    return {"sema": SEMA, "kosu_ms": havuz["kosu_ms"], "kasa_usd": kasa, "slot_usd": boyut.slot_usd(kasa, rules), "saha_n": n,
            "gecti_sayisi": sum(1 for s in havuz["satirlar"] if s.get("gecti")), "soguyan": soguyan, "satirlar": satirlar,
            "korelasyon": korelasyon([{"adres": p["adres"], "kopya_gunluk": p["kopya_gunluk"]} for p in secilen])}          # K-45 eki (08.11): tüm kadro (İlk 11 + Yedek); Yedek boş slota girebildiği için benzerlik denetimi onları da kapsar


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--havuz", type=Path, required=True)
    ap.add_argument("--cikti", type=Path, default=None, help="varsayılan: havuz.json'ın yanına kadro.json")
    ap.add_argument("--kasa", type=float, default=None, help="kasa $ (varsayılan kurallar.yaml canli_kasa_usd)")
    args = ap.parse_args(argv)
    rules = load_rules()
    havuz = json.loads(args.havuz.read_text(encoding="utf-8"))
    tam, neden = kosu_tam_mi(havuz, rules)
    if not tam:
        print(f"EKSİK KOŞU: {neden}; kadro yazılmadı", file=sys.stderr)
        return 2
    kadro = kadro_olustur(havuz, rules, args.kasa)
    cikti = args.cikti or args.havuz.with_name("kadro.json")
    gecici = cikti.with_suffix(".json.tmp")
    gecici.write_text(json.dumps(kadro, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    gecici.replace(cikti)
    print(f"kadro: {len(kadro['satirlar'])} kişi (ilk11 {sum(1 for s in kadro['satirlar'] if s['katman'] == 'ilk11')}, yedek {sum(1 for s in kadro['satirlar'] if s['katman'] == 'yedek')}), "
          f"gecti {kadro['gecti_sayisi']}, soğuyan {len(kadro['soguyan'])}, kasa {kadro['kasa_usd']:.0f} $, slot {kadro['slot_usd']:.2f} $ → {cikti}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
