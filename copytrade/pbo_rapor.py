"""PBO raporu (docs/HOLDOUT_PBO.md; yalnız RAPOR): CT'nin mevcut isabet verisinden aday "seçim yöntemleri" matrisi kurar ve `copytrade.pbo`yu uygular.

Dönem = isabet günü (havuz tarihi); değer = o günün seçiminin `sonraki_7g` kopya getirisi (isabet.json `gruplar.<ad>.ortalama`, maliyet sonrası, oran: 0,02 = %2).
Adaylar (sütunlar): `ilk11` (forma göre İlk 11), `havuz` (R1 havuzu ortalaması), `elenen` (rastgele kontrol: elenenlerden 30), `evren_ornek30` (rastgele kontrol: tüm evrenden 30),
`ilk11_fiili` (sahaya fiilen oturan İlk 11; her günde varsa) ve `--ek-aday` ile verilen ek sütunlar (örn. ML filtresi açık/kapalı; ML filtresi gelince {ad: {tarih: getiri}} JSON).
Yalnız TÜM dönemlerde değeri olan adaylar kullanılır; yalnız tam 7 günlük pencereler (`pencere_tam`) sayılır. UYARI: günlük pencereler 7 gün örtüşür (ardışık dönemler bağımlı) →
PBO iyimser/gürültülü okunmalı; bu bir alarm değil, bilgidir.

    python -m copytrade.pbo_rapor --kok radar --veri-dali radar --cikti radar --ozet-md radar/ISABET_OZET.md
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from copytrade import pbo as pbo_mod
from copytrade.kurallar import load_rules

SEMA = "pbo-v1"
CEKIRDEK = ("ilk11", "havuz", "elenen")
ADAYLAR = ("ilk11", "havuz", "elenen", "evren_ornek30", "ilk11_fiili")
UYARI = "günlük 7 günlük pencereler örtüşür (ardışık dönemler bağımlı); PBO yalnız bilgidir, karar kuralına girmez"


def aday_degeri(isabet: dict, ad: str) -> float | None:
    """Bir isabet gününde adayın `sonraki_7g` ortalaması (None = yok / ölçülemedi)."""
    kaynak = isabet.get("havuz") if ad == "havuz" else (isabet.get("gruplar") or {}).get(ad)
    if not isinstance(kaynak, dict) or not kaynak.get("n"):
        return None
    v = kaynak.get("ortalama")
    return float(v) if v is not None else None


def matris_kur(isabetler: list[dict], ek_aday: dict[str, dict[str, float]] | None = None) -> dict:
    """Döner {`gunler`, `adaylar`, `matris` (T×N liste), `atlanan_aday` {ad: neden}, `atlanan_gun`}. Tarih sırası artan; kısmi pencere ve çekirdek adayı eksik günler atılır;
    kalan günlerin TÜMÜNDE değeri olmayan aday sütunu atılır (neden yazılır)."""
    gunler = sorted({i["tarih"]: i for i in isabetler}.items())
    kalan, atlanan_gun = [], []
    for tarih, i in gunler:
        if not i.get("pencere_tam"):
            atlanan_gun.append(f"{tarih}: kısmi pencere")
        elif any(aday_degeri(i, c) is None for c in CEKIRDEK):
            atlanan_gun.append(f"{tarih}: çekirdek aday eksik")
        else:
            kalan.append((tarih, i))
    sutunlar: dict[str, list[float | None]] = {ad: [aday_degeri(i, ad) for _, i in kalan] for ad in ADAYLAR}
    for ad, seri in (ek_aday or {}).items():
        sutunlar[ad] = [seri.get(t) for t, _ in kalan]
    adaylar, atlanan = [], {}
    for ad, seri in sutunlar.items():
        if seri and all(v is not None for v in seri):
            adaylar.append(ad)
        else:
            atlanan[ad] = "tüm günlerde değer yok" if seri else "gün yok"
    matris = [[sutunlar[ad][k] for ad in adaylar] for k in range(len(kalan))]
    return {"gunler": [t for t, _ in kalan], "adaylar": adaylar, "matris": matris, "atlanan_aday": atlanan, "atlanan_gun": atlanan_gun}


def rapor_olustur(isabetler: list[dict], tarih: str, s: int = 8, ek_aday: dict | None = None) -> dict:
    """pbo.json içeriği. Veri azsa (T < 2·S ya da < 2 aday) `durum: "yetersiz veri"`; hata fırlatmaz."""
    m = matris_kur(isabetler, ek_aday)
    cikti = {"sema": SEMA, "tarih": tarih, "s": s, "gunler": [m["gunler"][0], m["gunler"][-1]] if m["gunler"] else [], "t": len(m["gunler"]), "adaylar": m["adaylar"],
             "atlanan_aday": m["atlanan_aday"], "atlanan_gun": m["atlanan_gun"], "uyari": UYARI}
    if len(m["gunler"]) < 2 * s or len(m["adaylar"]) < 2:
        return {**cikti, "durum": pbo_mod.YETERSIZ, "pbo": None, "dsr": None,
                "neden": f"T={len(m['gunler'])} (gerekli ≥ {2 * s}), aday={len(m['adaylar'])} (gerekli ≥ 2)"}
    x = np.array(m["matris"], dtype=float)
    sonuc = pbo_mod.pbo(x, s)
    ds = pbo_mod.deflated_sharpe_matris(x)
    en_iyi = m["adaylar"][ds["sutun"]] if ds["sutun"] is not None else None
    return {**cikti, "durum": sonuc["durum"], "pbo": sonuc["pbo"], "bolunme": sonuc["bolunme"], "kullanilan_t": sonuc["t"], "lambda_medyan": sonuc["lambda_medyan"],
            "oos_sira_ort": sonuc["oos_sira_ort"], "is_en_iyi_sayim": dict(zip(m["adaylar"], sonuc["is_en_iyi_sayim"])),
            "dsr": {"aday": en_iyi, "sr_donem": ds["sr"], "dsr": ds["dsr"], "n_deneme": ds["n_deneme"]}}


def ozet_satiri(r: dict) -> str:
    """Haftalık rapor / OZET tek satırı."""
    if r["durum"] != "tamam":
        return f"PBO (CSCV, S={r['s']}): yetersiz veri — {r.get('neden', '')}"
    d = r["dsr"]
    dsr = "—" if d["dsr"] is None else f"{d['dsr']:.2f}"
    yorum = "seçim yöntemi eğitimdeki üstünlüğü sınamada KORUYAMIYOR (≥ 0,5)" if r["pbo"] >= 0.5 else "eğitimdeki en iyi yöntem sınamada çoğunlukla medyanın üstünde (< 0,5)"
    return (f"PBO (CSCV, S={r['s']}, T={r['kullanilan_t']} gün, {len(r['adaylar'])} aday): **{r['pbo']:.2f}** — {yorum}; deflated Sharpe ({d['aday']}) {dsr}. "
            f"_Bilgi: günlük pencereler örtüşür._")


# ------------------------------------------------------------------------------------------------------------------------------ G/Ç
def git_isabetler(dal: str) -> list[dict]:
    ls = subprocess.run(["git", "ls-tree", "-r", "--name-only", f"origin/{dal}"], capture_output=True, text=True, check=False)
    cikti = []
    for y in sorted(y for y in ls.stdout.splitlines() if y.startswith("radar/") and y.endswith("/isabet.json")):
        s = subprocess.run(["git", "show", f"origin/{dal}:{y}"], capture_output=True, text=True, check=False)
        if s.returncode == 0 and s.stdout.strip():
            try:
                cikti.append(json.loads(s.stdout))
            except json.JSONDecodeError:
                continue
    return cikti


def yerel_isabetler(kok: Path) -> list[dict]:
    cikti = []
    for y in sorted(kok.glob("????-??-??/isabet.json")):
        try:
            cikti.append(json.loads(y.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return cikti


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kok", type=Path, default=Path("radar"), help="yerel radar klasörü (yerel isabet.json'lar veri dalındakini geçersiz kılar)")
    ap.add_argument("--veri-dali", default=None)
    ap.add_argument("--cikti", type=Path, default=Path("radar"))
    ap.add_argument("--tarih", default=None, help="pbo.json klasörü (varsayılan: yerel en son tarihli radar klasörü, yoksa bugün UTC)")
    ap.add_argument("--ozet-md", type=Path, default=None, help="özet satırı bu dosyaya EKLENİR (yoksa oluşturulur)")
    ap.add_argument("--ek-aday", type=Path, default=None, help='JSON {ad: {"YYYY-MM-DD": getiri}} (örn. ML filtresi açık/kapalı)')
    args = ap.parse_args(argv)
    try:
        gunler = sorted(d.name for d in args.kok.glob("????-??-??"))
        tarih = args.tarih or (gunler[-1] if gunler else datetime.now(UTC).date().isoformat())
        birlesik = {i["tarih"]: i for i in (git_isabetler(args.veri_dali) if args.veri_dali else [])}
        birlesik.update({i["tarih"]: i for i in yerel_isabetler(args.kok)})
        ek = json.loads(args.ek_aday.read_text(encoding="utf-8")) if args.ek_aday else None
        r = rapor_olustur(list(birlesik.values()), tarih, int(load_rules()["pbo_s"]), ek)
        klasor = args.cikti / tarih
        klasor.mkdir(parents=True, exist_ok=True)
        (klasor / "pbo.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
        satir = ozet_satiri(r)
        print(satir)
        if args.ozet_md:
            ayrac = "\n" if args.ozet_md.exists() and args.ozet_md.stat().st_size else ""
            with args.ozet_md.open("a", encoding="utf-8") as f:
                f.write(ayrac + satir + "\n")
    except Exception as hata:                                  # noqa: BLE001 — radar yayımı engellenmez (rapor); hata günlükte görünür
        print(f"::error::PBO RAPORU HATASI: {type(hata).__name__}: {str(hata)[:200]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
