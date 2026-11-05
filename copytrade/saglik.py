"""Sistem sağlık kontrolü ("Bilgi İşlem + Denetim ekibi"; kullanıcı kararı 2026-11-05): motor, radar, pano ve Cloudflare çalışıyor mu, sorun var mı?

Saf fonksiyon: girdi motor `ozet.json` + radar `kadro.json` (+ dış ölçümler), çıktı bulgu listesi. Yeni hesap yok; yalnız yaş ve sayaç karşılaştırması. Eşikler bilinçli sabittir
(strateji eşiği DEĞİL; `radar_*` kuralları değişmez). İki yerde kullanılır: pano ÖZET "Sağlık" kutusu (`canli/pano.py`, her 15 dk) ve saatlik iş akışı `saglik.yml` (Telegram alarmı, canlı Cloudflare sayfası kontrolü dahil).

Seviyeler: `KRITIK` (acil bak), `UYARI` (bak), `BILGI`. Bulgu yoksa sistem "sağlıklı".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DAKIKA = 60_000
SAAT = 60 * DAKIKA

# Eşikler (ms / sayı)
VARDIYA_YAZMA_UYARI = 30 * DAKIKA          # motor özeti 15 dk'da bir yazılır; 30 dk üstü: vardiya durmuş/yayım kopmuş olabilir
VARDIYA_YAZMA_KRITIK = 60 * DAKIKA
RADAR_UYARI = 30 * SAAT                    # günlük radar (00:37Z + yedek 02:17Z); 30 sa üstü: bugünkü radar gelmedi
RADAR_KRITIK = 54 * SAAT
PANO_UYARI = 45 * DAKIKA                   # veri dalındaki pano 15 dk'da bir; canlı Cloudflare sayfası en az bir yayın geride olabilir
GECTI_ALT = 8                              # RADAR_V1 günlük beklenti 8–20 (devir kontrol listesi)
GECTI_UST = 20
TELEGRAM_HATA_UYARI = 5
KOPMA_UYARI = 5


@dataclass(frozen=True)
class Bulgu:
    seviye: str          # KRITIK | UYARI | BILGI
    kod: str
    mesaj: str           # sade Türkçe


def _yas_dk(simdi_ms: int, ms: int | float | None) -> float | None:
    return None if ms is None else (simdi_ms - float(ms)) / DAKIKA


def _sa(dk: float) -> str:
    return f"{dk / 60:.1f} saat" if dk >= 120 else f"{dk:.0f} dk"


def kontrol(simdi_ms: int, ozet: dict[str, Any] | None, kadro: dict[str, Any] | None, *, pano_ms: int | None = None, canli_pano_ms: int | None = None, canli_pano_ulasildi: bool | None = None) -> list[Bulgu]:
    """Bulguları döndürür (boşsa sağlıklı). `pano_ms`: veri dalındaki pano dosyasının son güncelleme anı; `canli_pano_ms`: Cloudflare'deki sayfanın içindeki veri anı (`data-ms`);
    `canli_pano_ulasildi`: sayfa indirilebildi mi (None = bu ölçüm yapılmadı)."""
    b: list[Bulgu] = []

    # --- motor / vardiya
    if not ozet:
        b.append(Bulgu("KRITIK", "ozet_yok", "Motor özeti (durum/ozet.json) okunamadı: vardiya hiç yazmamış olabilir."))
    else:
        yas = _yas_dk(simdi_ms, ozet.get("yazildi_ms"))
        if yas is None:
            b.append(Bulgu("UYARI", "ozet_zaman_yok", "Motor özetinde yazılma zamanı yok; vardiya yaşı ölçülemedi."))
        elif yas * DAKIKA >= VARDIYA_YAZMA_KRITIK:
            b.append(Bulgu("KRITIK", "vardiya_durdu", f"Motor {_sa(yas)}dir veri yazmıyor: vardiya durmuş olabilir."))
        elif yas * DAKIKA >= VARDIYA_YAZMA_UYARI:
            b.append(Bulgu("UYARI", "vardiya_gecikti", f"Motor verisi {_sa(yas)} eski (normal: en çok 15-20 dk)."))
        if ozet.get("dur"):
            b.append(Bulgu("UYARI", "motor_dur", "Motor DURDURULMUŞ (/kapat ya da risk durdurması): yeni işlem açılmıyor."))
        eksik = int(ozet.get("kapanis_eksik") or 0)
        if eksik > 0:
            b.append(Bulgu("KRITIK", "kapanis_eksik", f"{eksik} pozisyon kapanamadı (kapanış teyidi yok); motor yeniden deniyor."))
        hata = int(ozet.get("telegram_hata") or 0)
        if hata >= TELEGRAM_HATA_UYARI:
            b.append(Bulgu("UYARI", "telegram_hata", f"Telegram mesajı {hata} kez gönderilemedi."))
        din = ozet.get("dinleyici") or {}
        kopma = int(din.get("kopma") or 0)
        if kopma >= KOPMA_UYARI:
            b.append(Bulgu("UYARI", "kopma", f"Hyperliquid bağlantısı {kopma} kez koptu."))
        if int(din.get("kapanis_atlanan") or 0) > 0:
            b.append(Bulgu("UYARI", "kapanis_atlanan", f"{din.get('kapanis_atlanan')} kapanış olayı atlandı (dinleyici)."))
        if int(din.get("gecikme_60sn_ustu") or 0) > 0:
            b.append(Bulgu("BILGI", "gecikme_60", f"{din.get('gecikme_60sn_ustu')} dolum 60 sn'den geç algılandı."))

    # --- radar / kadro
    if not kadro:
        b.append(Bulgu("KRITIK", "kadro_yok", "Radar kadrosu okunamadı (radar/son/kadro.json)."))
    else:
        yas = _yas_dk(simdi_ms, kadro.get("kosu_ms"))
        if yas is None:
            b.append(Bulgu("UYARI", "kadro_zaman_yok", "Kadroda koşu zamanı yok."))
        elif yas * DAKIKA >= RADAR_KRITIK:
            b.append(Bulgu("KRITIK", "radar_durdu", f"Radar {_sa(yas)}dir çalışmadı: kadro çok eski."))
        elif yas * DAKIKA >= RADAR_UYARI:
            b.append(Bulgu("UYARI", "radar_gecikti", f"Bugünkü radar henüz gelmedi (kadro {_sa(yas)} eski)."))
        gecti = kadro.get("gecti_sayisi")
        if gecti is not None and not (GECTI_ALT <= int(gecti) <= GECTI_UST):
            b.append(Bulgu("UYARI", "gecti_aralik_disi", f"Radarı geçen trader sayısı {int(gecti)} (beklenen {GECTI_ALT}–{GECTI_UST}); strateji/veri kontrol edilmeli."))
        n, satir = int(kadro.get("saha_n") or 0), kadro.get("satirlar") or []
        ilk11 = [s for s in satir if s.get("katman") == "ilk11"]
        if n and len(ilk11) < n:
            b.append(Bulgu("UYARI", "kadro_eksik", f"Kadroda {len(ilk11)}/{n} trader var."))

    # --- pano
    if pano_ms is not None:
        yas = _yas_dk(simdi_ms, pano_ms)
        if yas is not None and yas * DAKIKA >= PANO_UYARI:
            b.append(Bulgu("UYARI", "pano_bayat", f"Veri dalındaki pano {_sa(yas)} eski; 15 dakikada bir yenilenmesi gerekir."))
    if canli_pano_ulasildi is False:
        b.append(Bulgu("UYARI", "pano_ulasilmiyor", "Cloudflare pano sayfasına (sg-pano) ulaşılamadı."))
    elif canli_pano_ms is not None:
        yas = _yas_dk(simdi_ms, canli_pano_ms)
        if yas is not None and yas * DAKIKA >= 90 * DAKIKA:
            b.append(Bulgu("UYARI", "pano_cf_bayat", f"Cloudflare'deki pano {_sa(yas)} eski (yayın çalışmıyor olabilir)."))
    elif canli_pano_ulasildi is True:
        b.append(Bulgu("UYARI", "pano_cf_isaret_yok", "Cloudflare sayfası açıldı ama veri zamanı okunamadı (eski/yanlış sayfa olabilir)."))
    return b


def canli_sayfa_ms(html: str) -> int | None:
    """Pano HTML'indeki veri zamanı (`<div id="bayat" data-ms="…">`); yoksa None."""
    m = re.search(r'id="bayat"[^>]*data-ms="(\d+)"', html)
    return int(m.group(1)) if m else None


def ozet_metin(bulgular: list[Bulgu]) -> str:
    """Telegram / iş akışı özeti (sade Türkçe)."""
    if not bulgular:
        return "✅ Sistem sağlıklı: motor, radar ve pano çalışıyor."
    ikon = {"KRITIK": "🚨", "UYARI": "⚠️", "BILGI": "ℹ️"}
    return "\n".join(f"{ikon[x.seviye]} {x.mesaj}" for x in sorted(bulgular, key=lambda x: ("KRITIK", "UYARI", "BILGI").index(x.seviye)))


def durum(bulgular: list[Bulgu]) -> str:
    """'KRITIK' | 'UYARI' | 'SAGLIKLI' (BILGI sağlıklı sayılır)."""
    if any(x.seviye == "KRITIK" for x in bulgular):
        return "KRITIK"
    if any(x.seviye == "UYARI" for x in bulgular):
        return "UYARI"
    return "SAGLIKLI"


# ---------------------------------------------------------------------------------------------- komut satırı (iş akışı `saglik.yml`)
def _git_oku(dal: str, yol: str) -> str | None:
    import subprocess
    s = subprocess.run(["git", "show", f"origin/{dal}:{yol}"], capture_output=True, text=True)
    return s.stdout if s.returncode == 0 and s.stdout.strip() else None


def _git_zaman_ms(dal: str, yol: str) -> int | None:
    import subprocess
    s = subprocess.run(["git", "log", "-1", "--format=%ct", f"origin/{dal}", "--", yol], capture_output=True, text=True)
    return int(s.stdout.strip()) * 1000 if s.returncode == 0 and s.stdout.strip() else None


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import sys
    import time
    import urllib.request
    ap = argparse.ArgumentParser(description="Sistem sağlık kontrolü: veri dallarını (origin/<dal>) ve canlı pano sayfasını okur; bulguları yazar, Telegram'a alarm gönderir.")
    ap.add_argument("--veri-dali", default="canli-durum")
    ap.add_argument("--kadro-dali", default="radar")
    ap.add_argument("--canli-url", default="", help="Cloudflare pano adresi (boşsa canlı sayfa kontrol edilmez)")
    ap.add_argument("--telegram", action="store_true", help="bulgu varsa Telegram alarmı gönder (KRITIK her koşuda, UYARI her 3 saatte bir)")
    args = ap.parse_args(argv)
    simdi = int(time.time() * 1000)
    ozet_ham, kadro_ham = _git_oku(args.veri_dali, "durum/ozet.json"), _git_oku(args.kadro_dali, "radar/son/kadro.json")
    ozet, kadro = (json.loads(ozet_ham) if ozet_ham else None), (json.loads(kadro_ham) if kadro_ham else None)
    canli_ms, ulasildi = None, None
    if args.canli_url:
        try:
            with urllib.request.urlopen(urllib.request.Request(args.canli_url, headers={"User-Agent": "sg-saglik/1"}), timeout=30) as r:
                canli_ms, ulasildi = canli_sayfa_ms(r.read().decode("utf-8", "replace")), True
        except Exception:                                                                    # noqa: BLE001 - ağ hatası: bulgu olarak raporlanır, kontrol çökmez
            ulasildi = False
    bulgular = kontrol(simdi, ozet, kadro, pano_ms=_git_zaman_ms(args.veri_dali, "pano/index.html"), canli_pano_ms=canli_ms, canli_pano_ulasildi=ulasildi)
    metin, st = ozet_metin(bulgular), durum(bulgular)
    print(f"DURUM: {st}\n{metin}")
    if args.telegram and st != "SAGLIKLI":
        saat_utc = int(time.strftime("%H", time.gmtime(simdi / 1000)))
        if st == "KRITIK" or saat_utc % 3 == 0:
            from copytrade.canli import telegram as tg
            t = tg.Telegram()
            if t.acik:
                t.gonder(tg.alarm("ALARM: sistem sağlık kontrolü" if st == "KRITIK" else "Sağlık uyarısı", metin))
            else:
                print("UYARI: Telegram anahtarı yok; alarm gönderilemedi", file=sys.stderr)
    return 2 if st == "KRITIK" else 0                                                       # KRITIK: iş kırmızı biter (Actions e-postası + görünür)


if __name__ == "__main__":
    raise SystemExit(main())
