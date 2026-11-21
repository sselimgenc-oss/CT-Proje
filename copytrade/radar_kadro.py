"""Kadro, K-85 sade seçim (kullanıcı kararı 21.11): `havuz.json` (radar_tarama) + önceki kadro → `kadro.json`. Motor kadroyu okur (`copytrade/canli/kadro.py`).

Kurallar (tümü `kurallar.yaml` radar_* anahtarları):
- 5 trader (`radar_kadro_n`), eşit slot, YEDEK YOK. Kuralları geçen 5'ten azsa slotlar BOŞ kalır (geçmeyen asla doldurulmaz).
- İlk kurulum: kadro dosyası yok / dönem (`copytrade/canli/DONEM`) değişti / hiç üye yok → sıradaki en iyi ≤5 hemen girer (tarama o gün yapılır).
- Sonra değişiklik YALNIZ kontrol günlerinde (`radar_kontrol_gunleri`: UTC Pazartesi ve Perşembe; aynı gün ikinci koşu kontrol yapmaz): süzgeçten düşen YA DA girişten beri kopya sonucu ≤ `radar_cikis_kopya_esigi`
  olan üye çıkar (en çok `radar_degisim_azami`; önce süzgeçten düşenler, sonra en kötü sonuç); çıkan `radar_yasak_gun` gün geri giremez; boş slotlar sıralı listeden dolar.
  Veri hatası (`veri_hatasi`, `zaman_yok`) çıkış nedeni DEĞİLDİR.
- Kontrol günü değilse tarama yapılmaz; kadro aynen sürer (yalnız `kosu_ms` tazelenir, motor 36 saatten eski kadroyu bayat sayar).

`kadro.json` (motorun okuduğu biçim korundu): {sema "radar-kadro-v1", radar_surum, kosu_ms, kasa_usd, slot_usd, saha_n, gecti_sayisi, soguyan[], satirlar[{adres, sira, katman, form, bilesenler, ...}], korelasyon, elenenler[],
eski_uye_neden{}, huni{}, olusturma_ms} + K-85 alanları: `sade` true, `donem`, `kontrol_gun` (son kontrolün UTC günü), `yasak` {adres: bitiş_ms}, `degisim[]` (bu koşunun giriş/çıkışları),
`cikanlar` [{adres, cikis_ms}] (son `radar_cikanlar_saat` saatte çıkarılanlar; motor açık pozisyonlarını yönetir; eski dosyada yoksa boş sayılır).

    python -m copytrade.radar_kadro --havuz radar/2026-11-21/havuz.json [--onceki-kadro onceki/kadro.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from copytrade import boyut
from copytrade.kurallar import load_rules

SEMA = "radar-kadro-v1"
HAVUZ_SEMA = "radar-havuz-v2"
VERI_NEDENLERI = ("veri_hatasi", "zaman_yok")       # çıkış / sonuç nedeni DEĞİL (okuma / bütçe)
SAAT = 3_600_000
GUN = 24 * SAAT
DONEM_DOSYA = Path(__file__).with_name("canli") / "DONEM"


def donem_oku(yol: Path = DONEM_DOSYA) -> str | None:
    """`copytrade/canli/DONEM` (UTC ISO). Yok / boş → None."""
    try:
        metin = yol.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return metin or None


def _gun(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()


def aktif_onceki(onceki: dict | None, donem: str | None, rules: dict) -> dict | None:
    """Önceki kadro bu kuralların ve bu dönemin kadrosuysa kendisi, değilse None (eski sürüm / eski dönem kadrosu devralınmaz)."""
    if not onceki or onceki.get("sema") != SEMA or not onceki.get("sade") or str(onceki.get("radar_surum")) != str(rules["radar_surum"]):
        return None
    if donem is not None and onceki.get("donem") != donem:
        return None
    return onceki


def aktif_uyeler(onceki: dict | None, donem: str | None, rules: dict) -> list[dict]:
    a = aktif_onceki(onceki, donem, rules)
    return [dict(s) for s in (a or {}).get("satirlar") or []]


def tarama_gerekli(onceki: dict | None, donem: str | None, kosu_ms: int, rules: dict) -> tuple[bool, str]:
    """(gerekli mi, sebep): ilk kurulum / yeni dönem / üye yok → her gün; aksi halde yalnız kontrol günü (UTC) ve o gün kontrol yapılmadıysa."""
    a = aktif_onceki(onceki, donem, rules)
    if a is None:
        return True, "ilk_kurulum"
    if not a.get("satirlar"):
        return True, "kadro_bos"
    if a.get("kontrol_gun") == _gun(kosu_ms):
        return False, "bugun_kontrol_yapildi"
    if datetime.fromtimestamp(kosu_ms / 1000, UTC).weekday() in {int(x) for x in rules["radar_kontrol_gunleri"]}:
        return True, "kontrol_gunu"
    return False, "kontrol_gunu_degil"


def kosu_tam_mi(havuz: dict, rules: dict | None = None) -> tuple[bool, str | None]:
    """Koşu tam mı: tarama yapıldıysa `zaman_yok` satırı yok, lider tablosu boş değil ve `veri_hatasi` payı ≤ `radar_veri_hatasi_pay_max`. Tarama yapılmadıysa (kadro aynen sürer) her zaman tam."""
    rules = rules or load_rules()
    if not havuz.get("tarama"):
        return True, None
    satirlar = havuz["satirlar"]
    if int(havuz.get("evren_toplam") or 0) <= 0:
        return False, "lider tablosu boş"
    zaman_yok = sum(1 for s in satirlar if s.get("neden") == "zaman_yok")
    if zaman_yok:
        return False, f"{zaman_yok} aday zaman_yok (zaman bütçesi aşıldı)"
    hatali = sum(1 for s in satirlar if s.get("neden") == "veri_hatasi")
    esik = float(rules["radar_veri_hatasi_pay_max"])
    if satirlar and hatali / len(satirlar) > esik + 1e-12:
        return False, f"{hatali}/{len(satirlar)} satır veri_hatasi (pay {hatali / len(satirlar):.3f} > {esik:g})"
    return True, None


def _uye(s: dict, giris_ms: int, sira: int) -> dict:
    return {"adres": s["adres"], "sira": sira, "katman": "ilk11", "form": s.get("skor"), "bilesenler": {}, "kopya_getiri_7g": None, "kopya_getiri_30g": s.get("kopya_getiri_30g"),
            "getiri_30g": s.get("getiri_30g"), "dusus_30g": s.get("dusus_30g"), "skor": s.get("skor"), "max_kaldirac": s.get("max_kaldirac"), "medyan_tutma_saat": s.get("medyan_tutma_saat"),
            "giris_ms": giris_ms, "tutma": False}


def kadro_olustur(havuz: dict, rules: dict | None = None, onceki: dict | None = None, donem: str | None = None, kasa_usd: float | None = None) -> dict:
    """Havuz + önceki kadro → kadro (saf fonksiyon)."""
    rules = rules or load_rules()
    if havuz.get("sema") != HAVUZ_SEMA:
        raise ValueError(f"havuz şeması {HAVUZ_SEMA} olmalı: {havuz.get('sema')!r}")
    donem = donem if donem is not None else havuz.get("donem")
    kosu = int(havuz["kosu_ms"])
    a = aktif_onceki(onceki, donem, rules)
    uyeler = [dict(s) for s in (a or {}).get("satirlar") or []]
    yasak = {k: int(v) for k, v in ((a or {}).get("yasak") or {}).items() if int(v) > kosu}
    cikanlar = [c for c in ((a or {}).get("cikanlar") or (onceki or {}).get("cikanlar") or []) if kosu - int(c["cikis_ms"]) <= float(rules["radar_cikanlar_saat"]) * SAAT]
    kontrol_gun = (a or {}).get("kontrol_gun")
    degisim: list[dict] = []
    n = int(rules["radar_kadro_n"])
    satir = {s["adres"]: s for s in havuz["satirlar"]}
    if havuz.get("tarama"):
        kontrol_gun = _gun(kosu)
        ilk = a is None or not uyeler
        if not ilk:
            adaylar = []
            for u in uyeler:
                s = satir.get(u["adres"])
                if s is None:
                    continue
                dustu = not s.get("gecti") and s.get("neden") not in VERI_NEDENLERI
                kayip = s.get("giris_getiri") is not None and s["giris_getiri"] <= float(rules["radar_cikis_kopya_esigi"]) + 1e-12
                if dustu or kayip:
                    adaylar.append((0 if dustu else 1, s.get("giris_getiri") if s.get("giris_getiri") is not None else 0.0, u["adres"], f"suzgec:{s.get('neden')}" if dustu else "kopya_kayip"))
            for _, _, adres, neden in sorted(adaylar)[:int(rules["radar_degisim_azami"])]:
                uyeler = [u for u in uyeler if u["adres"] != adres]
                yasak[adres] = kosu + int(rules["radar_yasak_gun"]) * GUN
                cikanlar.append({"adres": adres, "cikis_ms": kosu})
                degisim.append({"tur": "cikis", "adres": adres, "neden": neden})
        sirali = sorted((s for s in havuz["satirlar"] if s.get("gecti")), key=lambda s: (-(s.get("skor") or 0.0), s["adres"]))
        mevcut = {u["adres"] for u in uyeler}
        for s in sirali:
            if len(uyeler) >= n:
                break
            if s["adres"] in mevcut or s["adres"] in yasak:
                continue
            uyeler.append(_uye(s, kosu, 0))
            mevcut.add(s["adres"])
            degisim.append({"tur": "giris", "adres": s["adres"], "neden": "ilk_kurulum" if ilk else "bos_slot"})
    for u in uyeler:                                                          # yenilenen ölçüler (yalnız bilgi); giriş zamanı korunur
        s = satir.get(u["adres"])
        if s and havuz.get("tarama"):
            u.update({k: s.get(k) for k in ("kopya_getiri_30g", "getiri_30g", "dusus_30g", "skor", "max_kaldirac", "medyan_tutma_saat")})
            u["form"] = s.get("skor")
    uyeler.sort(key=lambda u: (-(u.get("skor") if u.get("skor") is not None else -1e9), u["adres"]))
    for i, u in enumerate(uyeler, 1):
        u["sira"], u["katman"] = i, "ilk11"
    kasa = boyut.radar_kasa(rules, kasa_usd if kasa_usd is not None else havuz.get("kasa_usd"))
    sayilar: dict[str, int] = {}
    for s in havuz["satirlar"]:
        if not s.get("gecti"):
            sayilar[str(s.get("neden"))] = sayilar.get(str(s.get("neden")), 0) + 1
    return {"sema": SEMA, "radar_surum": str(rules["radar_surum"]), "sade": True, "donem": donem, "kosu_ms": kosu, "kasa_usd": kasa, "slot_usd": boyut.slot_usd(kasa, rules), "saha_n": n,
            "gecti_sayisi": sum(1 for s in havuz["satirlar"] if s.get("gecti")) if havuz.get("tarama") else (a or {}).get("gecti_sayisi", 0), "soguyan": [], "satirlar": uyeler,
            "korelasyon": {"adresler": [], "matris": []}, "elenenler": [], "eski_uye_neden": {}, "h_siz_girenler": [], "onceki_kosu_ms": (onceki or {}).get("kosu_ms"),
            "kontrol_gun": kontrol_gun, "yasak": yasak, "cikanlar": cikanlar, "degisim": degisim,
            "huni": {"evren": havuz.get("evren_toplam"), "aday": len(havuz["satirlar"]), "gecen": sum(1 for s in havuz["satirlar"] if s.get("gecti")), "kadro": len(uyeler),
                     "neden": dict(sorted(sayilar.items(), key=lambda kv: (-kv[1], kv[0])))}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--havuz", type=Path, required=True)
    ap.add_argument("--cikti", type=Path, default=None, help="varsayılan: havuz.json'ın yanına kadro.json")
    ap.add_argument("--onceki-kadro", type=Path, default=None, help="önceki kadro.json (üyeler, yasak listesi, çıkanlar); yoksa ilk kurulum")
    ap.add_argument("--donem", default=None, help="dönem başı (UTC ISO); varsayılan copytrade/canli/DONEM")
    args = ap.parse_args(argv)
    rules = load_rules()
    havuz = json.loads(args.havuz.read_text(encoding="utf-8"))
    tam, neden = kosu_tam_mi(havuz, rules)
    if not tam:
        print(f"EKSİK KOŞU: {neden}; kadro yazılmadı", file=sys.stderr)
        return 2
    onceki = json.loads(args.onceki_kadro.read_text(encoding="utf-8")) if args.onceki_kadro else None
    kadro = {**kadro_olustur(havuz, rules, onceki, args.donem or donem_oku()), "olusturma_ms": int(time.time() * 1000)}
    cikti = args.cikti or args.havuz.with_name("kadro.json")
    gecici = cikti.with_suffix(".json.tmp")
    gecici.write_text(json.dumps(kadro, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    gecici.replace(cikti)
    print(f"kadro: {len(kadro['satirlar'])}/{kadro['saha_n']} kişi, tarama {'evet' if havuz.get('tarama') else 'hayır'}, değişim {kadro['degisim']}, gecti {kadro['gecti_sayisi']} → {cikti}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
