"""Sunucu ortam dosyası denetimi (G-9, G-22): `/etc/sg-canli.env`, `/etc/sg-canli-telegram.env`, `/etc/sg-canli-yayim.env`. DEĞER ASLA BASILMAZ (yalnız satır no + ad + sorun).

systemd `EnvironmentFile` kuralı: yalnız `#` / `;` ile BAŞLAYAN satır açıklamadır; satır sonundaki `# …` DEĞERE KARIŞIR (`CANLI_KASA_USD=300  # not` → motor açılmaz). Bu yüzden:
her satır ya boş, ya tam satır açıklama, ya da `AD=değer` (eşittir çevresinde boşluk yok, değerde `#` yok, baş/son boşluk yok, tırnak yok).

Kullanım (sunucuda, değerleri göstermeden): `sudo /opt/sg-arge/.venv/bin/python -m copytrade.canli.ortam_dosyasi motor /etc/sg-canli.env`
(tür: motor | telegram | yayim). Çıkış 0 = sorun yok, 1 = sorun var (liste stdout'ta, değersiz).
"""
from __future__ import annotations

import argparse
import math
import os
import re
import stat
import sys
from pathlib import Path

AD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ADRES_RE = re.compile(r"0x[0-9a-fA-F]{40}")
ANAHTAR_RE = re.compile(r"(0x)?[0-9a-fA-F]{64}")
KASA_UST_USD = 1000.0                     # $ (AGENTS.md K‑22; kurallar.yaml canli_kasa_ust_usd ile aynı — test denetler)

TURLER: dict[str, dict[str, set[str]]] = {
    "motor": {"zorunlu": {"HL_API_CUZDAN_ANAHTARI", "HL_HESAP_ADRESI"}, "izinli": {"HL_API_CUZDAN_ANAHTARI", "HL_HESAP_ADRESI", "CANLI_KIP", "CANLI_KASA_USD", "TELEGRAM_KOMUT"}},
    "telegram": {"zorunlu": {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"}, "izinli": {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"}},
    "yayim": {"zorunlu": set(), "izinli": {"GERCEK_YAYIM_HEDEF", "GERCEK_YAYIM_TOKEN"}},
}


def ayristir(metin: str) -> tuple[dict[str, str], list[str]]:
    """Döner (ad -> değer, sorunlar). Sorun metinleri DEĞER İÇERMEZ."""
    degerler: dict[str, str] = {}
    sorunlar: list[str] = []
    for no, ham in enumerate(metin.splitlines(), 1):
        satir = ham.rstrip("\r")
        if not satir.strip() or satir.lstrip().startswith(("#", ";")):
            continue
        if satir != satir.strip():
            sorunlar.append(f"satır {no}: baş/son boşluk var (değere karışır)")
        if "=" not in satir:
            sorunlar.append(f"satır {no}: AD=değer biçiminde değil")
            continue
        ad, deger = satir.strip().split("=", 1)
        if ad.startswith("export "):
            sorunlar.append(f"satır {no}: 'export' kullanılmaz")
            ad = ad[len("export "):]
        if not AD_RE.fullmatch(ad):
            sorunlar.append(f"satır {no}: değişken adı geçersiz ya da '=' çevresinde boşluk var")
            continue
        if deger != deger.strip() or deger[:1] in (" ", "\t"):
            sorunlar.append(f"satır {no}: {ad} değerinde baş/son boşluk var")
        if "#" in deger:
            sorunlar.append(f"satır {no}: {ad} değerinde '#' var — satır sonu açıklama systemd'de DEĞERE KARIŞIR; açıklamayı ayrı satıra yazın")
        if deger[:1] in ("'", '"'):
            sorunlar.append(f"satır {no}: {ad} değeri tırnaklı; tırnaksız yazın")
        if ad in degerler:
            sorunlar.append(f"satır {no}: {ad} iki kez tanımlı")
        degerler[ad] = deger.strip()
    return degerler, sorunlar


def denetle(metin: str, tur: str) -> list[str]:
    """`tur` (motor | telegram | yayim) dosyasının sorunları (değersiz). Boş liste = sorun yok."""
    kural = TURLER[tur]
    d, sorunlar = ayristir(metin)
    for ad in sorted(kural["zorunlu"] - {a for a, v in d.items() if v}):
        sorunlar.append(f"{ad} eksik ya da boş")
    for ad in sorted(set(d) - kural["izinli"]):
        if ad.startswith(("HL_", "CANLI_")) and tur != "motor":
            sorunlar.append(f"{ad} bu dosyada OLAMAZ (G-22: HL anahtarı ve kip yalnız /etc/sg-canli.env, yalnız motor birimi)")
        elif ad.startswith("TELEGRAM_") and tur == "motor" and ad != "TELEGRAM_KOMUT":
            sorunlar.append(f"{ad} /etc/sg-canli-telegram.env dosyasına taşınmalı (G-22)")
        else:
            sorunlar.append(f"{ad} bu dosyada beklenmiyor")
    if tur == "motor":
        if d.get("HL_HESAP_ADRESI") and not ADRES_RE.fullmatch(d["HL_HESAP_ADRESI"]):
            sorunlar.append("HL_HESAP_ADRESI biçimi geçersiz (0x + 40 onaltılık hane)")
        if d.get("HL_API_CUZDAN_ANAHTARI") and not ANAHTAR_RE.fullmatch(d["HL_API_CUZDAN_ANAHTARI"]):
            sorunlar.append("HL_API_CUZDAN_ANAHTARI biçimi geçersiz (64 onaltılık hane, isteğe bağlı 0x)")
        kip = d.get("CANLI_KIP", "")
        if kip not in ("", "sanal", "gercek"):
            sorunlar.append("CANLI_KIP yalnız sanal ya da gercek olabilir")
        if kip == "gercek" or d.get("CANLI_KASA_USD"):
            try:
                kasa = float(d.get("CANLI_KASA_USD", ""))
                if not math.isfinite(kasa) or kasa <= 0 or kasa > KASA_UST_USD:
                    sorunlar.append(f"CANLI_KASA_USD 0 < kasa <= {KASA_UST_USD:g} $ olmalı")
            except ValueError:
                sorunlar.append("CANLI_KASA_USD sayı değil" if d.get("CANLI_KASA_USD") else "gercek kipte CANLI_KASA_USD zorunlu")
        if d.get("TELEGRAM_KOMUT", "") not in ("", "kapali"):
            sorunlar.append("TELEGRAM_KOMUT sunucuda boş olmalı (motor komutları alır)")
    if tur == "telegram" and d.get("TELEGRAM_CHAT_ID") and not re.fullmatch(r"-?\d+", d["TELEGRAM_CHAT_ID"]):
        sorunlar.append("TELEGRAM_CHAT_ID sayı değil")
    return sorunlar


def izin_denetle(yol: Path) -> list[str]:
    """Dosya izni: grup/diğerleri okuyamamalı (600 ya da 400)."""
    try:
        kip = stat.S_IMODE(os.stat(yol).st_mode)
    except OSError as hata:
        return [f"dosya okunamadı ({type(hata).__name__})"]
    return [f"izin {kip:o}: grup/diğerleri erişebiliyor; 600 olmalı (sudo chmod 600 {yol})"] if kip & 0o077 else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tur", choices=sorted(TURLER))
    ap.add_argument("dosya", type=Path)
    a = ap.parse_args(argv)
    try:
        metin = a.dosya.read_text(encoding="utf-8")
    except OSError as hata:
        print(f"{a.dosya}: okunamadı ({type(hata).__name__})")
        return 1
    sorunlar = izin_denetle(a.dosya) + denetle(metin, a.tur)
    for s in sorunlar:
        print(f"{a.dosya}: {s}")
    if not sorunlar:
        print(f"{a.dosya}: tamam ({a.tur})")
    return 1 if sorunlar else 0


if __name__ == "__main__":
    sys.exit(main())
