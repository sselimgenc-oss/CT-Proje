"""Holdout mühürü (docs/HOLDOUT_PBO.md): `holdout_bas` (kurallar.yaml) tarihinden itibaren radar günlük çıktılarının (havuz_ilk, kadro_ilk, isabet) SHA-256 özetleri
`radar/holdout/manifest.json`'a yalnız EKLENEREK yazılır; sonradan değişen/silinen dosya `dogrula` ile yakalanır. Kural: her yeni strateji/ML değişikliği holdout'ta
YALNIZ BİR KEZ değerlendirilir; her kullanım `kullanim` listesine (tarih + amaç) kaydedilir.

Yalnız RAPOR/koruma: karar kodu, eşik ve ağırlık değişmez; ağ yok (veri dalı `git show` ile okunur).

Manifest (şema `holdout-muhur-v1`): `holdout_bas`, `muhurler` [{tarih, dosya, sha256, muhur_tarihi, onceki, zincir}], `ihlaller` [{...}], `kullanim` [{tarih, amac, not, tekrar, onceki, zincir}],
`kullanim_sayisi`. Her liste SHA-256 zinciridir (`zincir` = sha256(onceki + girdinin kanonik JSON'u)): geçmiş bir kaydı değiştirmek zinciri bozar; yeni manifest eskinin
devamı olmalıdır (`ekleme_mi`).

    python -m copytrade.holdout_muhur muhurla --kok radar --manifest radar/holdout/manifest.json --veri-dali radar [--kullanim-amac X --kullanim-not Y [--tekrar]]
    python -m copytrade.holdout_muhur dogrula --manifest radar/holdout/manifest.json --veri-dali radar     # sorun varsa çıkış 1
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from copytrade.kurallar import load_rules

SEMA = "holdout-muhur-v1"
MUHURLU_DOSYALAR = ("havuz_ilk.json", "kadro_ilk.json", "isabet.json")      # günlük tarama çıktıları + isabet sonucu; kadro.json/havuz.json gün içinde yeniden yazılır → mühürlenmez
SAKLAMA_GUN = 90                                                              # radar_yayimla.sh tarihli klasörleri bu kadar gün tutar; sonrası "saklama_disi" (ihlal değil)
LISTELER = ("muhurler", "ihlaller", "kullanim")


# ------------------------------------------------------------------------------------------------------------------------------ saf fonksiyonlar
def sha256_hex(veri: bytes) -> str:
    return hashlib.sha256(veri).hexdigest()


def bos_manifest(holdout_bas: str) -> dict:
    return {"sema": SEMA, "holdout_bas": holdout_bas, "muhurler": [], "ihlaller": [], "kullanim": [], "kullanim_sayisi": 0}


def _zincir(onceki: str, girdi: dict) -> str:
    govde = {k: v for k, v in girdi.items() if k not in ("onceki", "zincir")}
    return sha256_hex((onceki + json.dumps(govde, ensure_ascii=False, sort_keys=True, separators=(",", ":"))).encode("utf-8"))


def _ekle(liste: list[dict], girdi: dict) -> dict:
    onceki = liste[-1]["zincir"] if liste else ""
    girdi = {**girdi, "onceki": onceki}
    girdi["zincir"] = _zincir(onceki, girdi)
    liste.append(girdi)
    return girdi


def zincir_sorunlari(manifest: dict) -> list[str]:
    """Her listenin zincirini baştan hesaplar; kayıt değişmiş/silinmiş/araya eklenmişse açıklama döner (boş = sağlam)."""
    sorun = []
    for ad in LISTELER:
        onceki = ""
        for i, g in enumerate(manifest.get(ad, [])):
            if g.get("onceki") != onceki or g.get("zincir") != _zincir(onceki, g):
                sorun.append(f"{ad}[{i}] zinciri bozuk (kayıt sonradan değişmiş, silinmiş ya da araya eklenmiş)")
                break
            onceki = g["zincir"]
    if int(manifest.get("kullanim_sayisi", 0)) != len(manifest.get("kullanim", [])):
        sorun.append("kullanim_sayisi ile kullanim listesi uyuşmuyor")
    return sorun


def ekleme_mi(eski: dict, yeni: dict) -> bool:
    """Append-only denetimi: `yeni`nin her listesi `eski`nin listesiyle başlar (aynen) ve holdout_bas değişmemiştir."""
    if eski.get("holdout_bas") != yeni.get("holdout_bas"):
        return False
    return all(yeni.get(ad, [])[:len(eski.get(ad, []))] == eski.get(ad, []) for ad in LISTELER)


def muhurlenecek_mi(tarih: str, dosya: str, holdout_bas: str) -> bool:
    return dosya in MUHURLU_DOSYALAR and tarih >= holdout_bas


def muhurla(manifest: dict, dosyalar: dict[tuple[str, str], bytes], bugun: str) -> tuple[dict, dict]:
    """`dosyalar`: {(tarih, dosya): bayt}. Holdout'a giren (tarih ≥ holdout_bas, ad MUHURLU_DOSYALAR) ve henüz mühürsüz olanlar EKLENİR. Zaten mühürlü bir dosya farklı özetle gelirse
    mühür DEĞİŞMEZ; `ihlaller`e (aynı tarih+dosya+özet bir kez) eklenir. Girdi manifest değişmez; döner (yeni manifest, rapor {yeni, ihlal, atlanan})."""
    yeni = copy.deepcopy(manifest)
    bas = yeni["holdout_bas"]
    var = {(g["tarih"], g["dosya"]): g["sha256"] for g in yeni["muhurler"]}
    eski_ihlal = {(g["tarih"], g["dosya"], g["gelen_sha256"]) for g in yeni["ihlaller"]}
    rapor: dict = {"yeni": [], "ihlal": [], "atlanan": 0}
    for (tarih, dosya), veri in sorted(dosyalar.items()):
        if not muhurlenecek_mi(tarih, dosya, bas):
            rapor["atlanan"] += 1
            continue
        ozet = sha256_hex(veri)
        if (tarih, dosya) not in var:
            _ekle(yeni["muhurler"], {"tarih": tarih, "dosya": dosya, "sha256": ozet, "muhur_tarihi": bugun})
            var[(tarih, dosya)] = ozet
            rapor["yeni"].append(f"{tarih}/{dosya}")
        elif var[(tarih, dosya)] != ozet and (tarih, dosya, ozet) not in eski_ihlal:
            _ekle(yeni["ihlaller"], {"tarih": tarih, "dosya": dosya, "muhurlu_sha256": var[(tarih, dosya)], "gelen_sha256": ozet, "tur": "muhur_sonrasi_degisti", "tespit_tarihi": bugun})
            rapor["ihlal"].append(f"{tarih}/{dosya}")
    return yeni, rapor


def kullanim_kaydet(manifest: dict, tarih: str, amac: str, aciklama: str = "", tekrar: bool = False) -> dict:
    """Holdout kullanımını (tarih + amaç) kaydeder. Aynı `amac` daha önce kayıtlıysa ValueError (holdout aynı değişiklik için ikinci kez bakılamaz) — `tekrar=True` ile
    açıkça işaretlenerek kaydedilir. Girdi değişmez; yeni manifest döner."""
    amac = amac.strip()
    if not amac:
        raise ValueError("amaç boş olamaz")
    yeni = copy.deepcopy(manifest)
    onceki_var = any(g["amac"] == amac for g in yeni["kullanim"])
    if onceki_var and not tekrar:
        raise ValueError(f"holdout bu amaç için zaten kullanıldı: {amac!r} (tekrar açıkça işaretlenmeli)")
    _ekle(yeni["kullanim"], {"tarih": tarih, "amac": amac, "not": aciklama, "tekrar": bool(onceki_var)})
    yeni["kullanim_sayisi"] = len(yeni["kullanim"])
    return yeni


def kullanim_satirlari(metin: str) -> list[tuple[str, str, str, bool]]:
    """`HOLDOUT_KULLANIM.txt`: her satır `YYYY-MM-DD | amaç | not | tekrar` (not ve tekrar isteğe bağlı; `#` ile başlayan/boş satır atlanır). Döner [(tarih, amaç, not, tekrar)]."""
    cikti = []
    for ham in metin.splitlines():
        ham = ham.strip()
        if not ham or ham.startswith("#"):
            continue
        p = [x.strip() for x in ham.split("|")]
        if len(p) < 2 or len(p[0]) != 10 or not p[1]:
            raise ValueError(f"HOLDOUT_KULLANIM satırı geçersiz (YYYY-MM-DD | amaç | not | tekrar): {ham!r}")
        cikti.append((p[0], p[1], p[2] if len(p) > 2 else "", len(p) > 3 and p[3].lower() == "tekrar"))
    return cikti


def kullanim_isle(manifest: dict, satirlar: list[tuple[str, str, str, bool]]) -> tuple[dict, list[str]]:
    """Dosyadaki satırları manifest'e işler: (tarih, amaç) zaten kayıtlıysa sessizce atlanır (her koşu aynı dosyayı yeniden okur); aynı amaç başka tarihte ve `tekrar` işaretsiz ise
    reddedilir (döner listede). Girdi değişmez."""
    yeni, red = manifest, []
    for tarih, amac, aciklama, tekrar in satirlar:
        if any(g["tarih"] == tarih and g["amac"] == amac for g in yeni["kullanim"]):
            continue
        try:
            yeni = kullanim_kaydet(yeni, tarih, amac, aciklama, tekrar)
        except ValueError as hata:
            red.append(str(hata))
    return yeni, red


def dogrula(manifest: dict, oku: Callable[[str, str], bytes | None], bugun: str, saklama_gun: int = SAKLAMA_GUN) -> dict:
    """Mühürlü her dosyayı `oku(tarih, dosya)` (bayt | None) ile okuyup özetle karşılaştırır. Döner {`tamam`, `zincir`, `degisen`, `eksik`, `saklama_disi`, `kontrol`}.
    Eksik dosya: tarihi `saklama_gun`'den eskiyse `saklama_disi` (beklenen silinme, ihlal değil), değilse `eksik` (sorun). `tamam` = zincir, değişen ve eksik boş."""
    sinir = (datetime.fromisoformat(bugun).date() - timedelta(days=saklama_gun)).isoformat()
    degisen, eksik, saklama = [], [], []
    for g in manifest.get("muhurler", []):
        veri = oku(g["tarih"], g["dosya"])
        ad = f"{g['tarih']}/{g['dosya']}"
        if veri is None:
            (saklama if g["tarih"] < sinir else eksik).append(ad)
        elif sha256_hex(veri) != g["sha256"]:
            degisen.append(ad)
    zincir = zincir_sorunlari(manifest)
    return {"tamam": not (zincir or degisen or eksik), "zincir": zincir, "degisen": degisen, "eksik": eksik, "saklama_disi": saklama, "kontrol": len(manifest.get("muhurler", []))}


def ozet_satiri(manifest: dict, rapor: dict | None = None, sonuc: dict | None = None) -> str:
    c = [f"Holdout mührü (başlangıç {manifest['holdout_bas']}): {len(manifest['muhurler'])} dosya mühürlü · kullanım {manifest['kullanim_sayisi']} · ihlal {len(manifest['ihlaller'])}"]
    if rapor and rapor["yeni"]:
        c.append(f"bugün mühürlenen: {', '.join(rapor['yeni'])}")
    if sonuc:
        c.append("doğrulama " + ("TAMAM" if sonuc["tamam"] else f"SORUNLU (değişen {len(sonuc['degisen'])}, eksik {len(sonuc['eksik'])}, zincir {len(sonuc['zincir'])})"))
    return " · ".join(c)


# ------------------------------------------------------------------------------------------------------------------------------ G/Ç
def _git_oku_bayt(dal: str, yol: str) -> bytes | None:
    s = subprocess.run(["git", "show", f"origin/{dal}:{yol}"], capture_output=True, check=False)
    return s.stdout if s.returncode == 0 and s.stdout else None


def manifest_oku(yol: Path, dal: str | None, holdout_bas: str) -> dict:
    """Önce yerel dosya, yoksa veri dalı (`radar/holdout/manifest.json`), yoksa boş manifest."""
    if yol.is_file():
        return json.loads(yol.read_text(encoding="utf-8"))
    if dal:
        ham = _git_oku_bayt(dal, "radar/holdout/manifest.json")
        if ham:
            return json.loads(ham)
    return bos_manifest(holdout_bas)


def yerel_dosyalar(kok: Path) -> dict[tuple[str, str], bytes]:
    """`kok/<YYYY-MM-DD>/<mühürlü dosya>` (yalnız var olanlar)."""
    cikti: dict[tuple[str, str], bytes] = {}
    for d in sorted(kok.glob("????-??-??")):
        for ad in MUHURLU_DOSYALAR:
            if (d / ad).is_file():
                cikti[(d.name, ad)] = (d / ad).read_bytes()
    return cikti


def _yaz(yol: Path, manifest: dict) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(".json.tmp")
    gecici.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    gecici.replace(yol)


def _bugun() -> str:
    return datetime.now(UTC).date().isoformat()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("komut", choices=("muhurla", "dogrula"))
    ap.add_argument("--kok", type=Path, default=Path("radar"), help="yerel radar klasörü (muhurla: yeni dosyalar buradan)")
    ap.add_argument("--manifest", type=Path, default=Path("radar/holdout/manifest.json"))
    ap.add_argument("--veri-dali", default=None, help="mühürlü dosyaların doğrulandığı veri dalı (radar | radar-deneme); yoksa yalnız --kok")
    ap.add_argument("--bugun", default=None, help="YYYY-MM-DD (varsayılan: bugün UTC)")
    ap.add_argument("--kullanim-amac", default=None, help="muhurla ile: holdout kullanımını kaydet (amaç)")
    ap.add_argument("--kullanim-not", default="")
    ap.add_argument("--tekrar", action="store_true", help="aynı amaç ikinci kez kullanılıyorsa açıkça işaretle")
    ap.add_argument("--kullanim-dosya", type=Path, default=None, help="copytrade/radar/HOLDOUT_KULLANIM.txt: `YYYY-MM-DD | amaç | not | tekrar` satırları işlenir")
    args = ap.parse_args(argv)
    bugun = args.bugun or _bugun()
    bas = str(load_rules()["holdout_bas"])
    manifest = manifest_oku(args.manifest, args.veri_dali, bas)

    def oku(tarih: str, dosya: str) -> bytes | None:
        if args.veri_dali:
            v = _git_oku_bayt(args.veri_dali, f"radar/{tarih}/{dosya}")
            if v is not None:
                return v
        y = args.kok / tarih / dosya
        return y.read_bytes() if y.is_file() else None

    if args.komut == "dogrula":
        sonuc = dogrula(manifest, oku, bugun)
        print(json.dumps(sonuc, ensure_ascii=False, indent=1))
        print(ozet_satiri(manifest, None, sonuc))
        return 0 if sonuc["tamam"] else 1
    # muhurla: önce mevcut mühürleri doğrula (değişenler ihlal olarak kaydedilir), sonra yeni dosyaları ekle. Hata yayımı ENGELLEMEZ (isabet adımıyla aynı desen), ama ::error:: basılır.
    try:
        sonuc = dogrula(manifest, oku, bugun)
        dosyalar = yerel_dosyalar(args.kok)
        for ad in sonuc["degisen"]:
            t, d = ad.split("/", 1)
            v = oku(t, d)
            if v is not None:
                dosyalar[(t, d)] = v                           # ihlal kaydı için
        yeni, rapor = muhurla(manifest, dosyalar, bugun)
        if args.kullanim_amac:
            try:
                yeni = kullanim_kaydet(yeni, bugun, args.kullanim_amac, args.kullanim_not, args.tekrar)
            except ValueError as hata:                         # tekrar kullanım: kayıt eklenmez (mühürler yine yazılır), açık hata
                print(f"::error::HOLDOUT KULLANIMI REDDEDİLDİ: {hata}", file=sys.stderr)
        if args.kullanim_dosya and args.kullanim_dosya.is_file():
            yeni, red = kullanim_isle(yeni, kullanim_satirlari(args.kullanim_dosya.read_text(encoding="utf-8")))
            for r in red:
                print(f"::error::HOLDOUT KULLANIMI REDDEDİLDİ: {r}", file=sys.stderr)
        if not ekleme_mi(manifest, yeni):
            raise RuntimeError("yeni manifest eskinin devamı değil (append-only ihlali)")
        _yaz(args.manifest, yeni)
        print(ozet_satiri(yeni, rapor, sonuc))
        if sonuc["degisen"] or sonuc["eksik"] or sonuc["zincir"] or rapor["ihlal"]:
            print(f"::error::HOLDOUT İHLALİ: değişen {sonuc['degisen']} eksik {sonuc['eksik']} zincir {sonuc['zincir']}", file=sys.stderr)
    except ValueError as hata:                                 # tekrar kullanım vb.: mühür yazılmaz, açık hata
        print(f"::error::HOLDOUT HATASI: {hata}", file=sys.stderr)
        return 0
    except Exception as hata:                                  # noqa: BLE001 — radar yayımı engellenmez; hata günlükte görünür
        print(f"::error::HOLDOUT HATASI: {type(hata).__name__}: {str(hata)[:200]}", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
