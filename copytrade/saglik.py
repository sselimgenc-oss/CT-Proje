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
# G2 (2026-11-06): kalıcı durum + kayıt olayları + iş akışı koşusu + veri dalı commit yaşı
KAYIT_PENCERE = 2 * SAAT                   # kayıt olayları (kayit/<tarih>.jsonl) için bakılan son pencere
VERI_DALI_COMMIT_UYARI = 45 * DAKIKA       # veri dalının SON commit'i (ozet.yazildi_ms'den bağımsız ikinci ölçü)
VERI_DALI_COMMIT_KRITIK = 90 * DAKIKA
KRITIK_KAYIT_OLAYLARI = {"vardiya_baslamadi": "Vardiya BAŞLAMADI (başka vardiya kilidi tutuyordu)", "vardiya_boslugu": "Vardiyalar arasında boşluk oldu (kesinti)"}
UYARI_KAYIT_OLAYLARI = {"kuyruk_tasti": "Olay kuyruğu taştı (açılış olayları düştü)", "kadro_bayat": "Kadro bayat (motor eski kadroyla çalıştı)"}
HATA_SAYACLARI = ("adim_hata", "olay_hata", "defter_hata")      # ozet.kayit_sayac (vardiya başına)
VARDIYA_IS_AKISI = "canli_vardiya.yml"
KOSU_API = "https://api.github.com/repos/sselimgenc-oss/sg-arge/actions/workflows/{wf}/runs?branch=main&per_page=5"


@dataclass(frozen=True)
class Bulgu:
    seviye: str          # KRITIK | UYARI | BILGI
    kod: str
    mesaj: str           # sade Türkçe


def _yas_dk(simdi_ms: int, ms: int | float | None) -> float | None:
    return None if ms is None else (simdi_ms - float(ms)) / DAKIKA


def _sa(dk: float) -> str:
    return f"{dk / 60:.1f} saat" if dk >= 120 else f"{dk:.0f} dk"


def kalici_kontrol(simdi_ms: int, motor: dict[str, Any] | None, risk: dict[str, Any] | None, dur_dosyasi: bool, olaylar: list[dict[str, Any]] | None, kayit_sayac: dict[str, Any] | None,
                   vardiya_kosulari: list[dict[str, Any]] | None, veri_dali_commit_ms: int | None, ozet_yazildi_ms: int | float | None = None) -> list[Bulgu]:
    """G2: kalıcı durum (`motor.json` kapanış kuyruğu, `risk.json` bayrakları, `DUR` dosyası), kayıt olayları, hata sayaçları, son vardiya koşusu, veri dalı commit yaşı.
    Okunamayan girdi (None) bulgu ÜRETMEZ (ağ/okuma hatası yanlış alarm olmasın; yokluk zaten `ozet_yok` vb. ile görünür)."""
    b: list[Bulgu] = []
    risk = risk or {}
    yas_c = _yas_dk(simdi_ms, veri_dali_commit_ms)
    veri_taze = None if yas_c is None else yas_c * DAKIKA < VERI_DALI_COMMIT_UYARI        # veri dalı taze mi (None: ölçülemedi)
    kuyruk = (motor or {}).get("kapanis_kuyrugu") or {}
    eksikler = [(k, v) for k, v in kuyruk.items() if isinstance(v, dict) and v.get("eksik")]
    if eksikler:
        en_eski = min((float(v["ms"]) for _, v in eksikler if v.get("ms")), default=None)
        yas = f", en eskisi {_sa((simdi_ms - en_eski) / DAKIKA)}dir" if en_eski else ""
        b.append(Bulgu("KRITIK", "kapanis_kuyrugu_eksik", f"Kalıcı kapanış kuyruğunda {len(eksikler)} EKSİK girdi{yas}: {', '.join(k.split('|')[-1] for k, _ in eksikler[:5])} borsada kapanmadı."))
    ad = risk.get("acilis_durdu") or {}
    if ad.get("mutabakat"):
        b.append(Bulgu("KRITIK", "mutabakat_bayragi", "Mutabakat bayrağı AÇIK: bizim kayıt ile borsa uyuşmuyor, yeni işlem kapalı."))
    if risk.get("dur") or dur_dosyasi:
        neden = f": {risk['dur_neden']}" if risk.get("dur_neden") else ""
        b.append(Bulgu("KRITIK", "risk_dur", f"Motor DUR durumunda ({'risk.dur' if risk.get('dur') else 'DUR dosyası'}{neden}): elle müdahale gerekir."))
    if (motor or {}).get("dur_bekliyor"):
        b.append(Bulgu("BILGI", "dur_bekliyor", "Motor DUR bekliyor: pozisyonlar kapanınca duracak."))
    if ad.get("gunluk_kayip"):
        b.append(Bulgu("UYARI", "gunluk_kayip", "Günlük kayıp freni açık: bugün yeni işlem yok."))
    if ad.get("elle_dur"):
        b.append(Bulgu("UYARI", "elle_dur", "Yeni işlem elle duraklatıldı (/devam ile açılır)."))
    if ad.get("kasa_siniri"):
        b.append(Bulgu("UYARI", "kasa_siniri", "Kasa sınırı bayrağı açık: yeni işlem kapalı."))
    if ad.get("kapanis_eksik") and not eksikler:
        b.append(Bulgu("UYARI", "kapanis_eksik_bayragi", "Risk kaydında kapanış-eksik bayrağı açık ama kuyrukta eksik girdi yok (bayrak temizlenmemiş olabilir)."))
    # kayıt olayları (son KAYIT_PENCERE)
    sayim: dict[str, list[dict[str, Any]]] = {}
    for o in olaylar or []:
        if o.get("zaman_ms") is not None and 0 <= simdi_ms - float(o["zaman_ms"]) <= KAYIT_PENCERE:
            sayim.setdefault(str(o.get("olay")), []).append(o)
    for kod, aciklama in KRITIK_KAYIT_OLAYLARI.items():
        if kod in sayim:
            son = sayim[kod][-1]
            ek = f" ({son['dk']} dk)" if son.get("dk") is not None else ""
            if veri_taze and ozet_yazildi_ms is not None and float(ozet_yazildi_ms) > float(son["zaman_ms"]):     # olaydan SONRA vardiya yeniden başladı ve veri taze: kurtarılmış
                b.append(Bulgu("UYARI", kod, f"{aciklama}{ek}: son 2 saatte {len(sayim[kod])} kez; sonrasında vardiya sürüyor, veri taze (kurtarıldı)."))
            else:
                b.append(Bulgu("KRITIK", kod, f"{aciklama}{ek}: son 2 saatte {len(sayim[kod])} kez."))
    for kod, aciklama in UYARI_KAYIT_OLAYLARI.items():
        if kod in sayim:
            b.append(Bulgu("UYARI", kod, f"{aciklama}: son 2 saatte {len(sayim[kod])} kez."))
    for sayac in HATA_SAYACLARI:
        n = int((kayit_sayac or {}).get(sayac) or 0)
        if n > 0:
            b.append(Bulgu("KRITIK", sayac, f"Motor kaydında {sayac} = {n} (bu vardiyada; hata ayıklanmalı)."))
    k = vardiya_kosu_bulgusu(vardiya_kosulari, veri_taze)
    if k:
        b.append(k)
    if veri_dali_commit_ms is not None:
        yas = _yas_dk(simdi_ms, veri_dali_commit_ms)
        if yas is not None and yas * DAKIKA >= VERI_DALI_COMMIT_KRITIK:
            b.append(Bulgu("KRITIK", "veri_dali_durdu", f"Veri dalında {_sa(yas)}dir yeni commit yok: yayım durmuş olabilir."))
        elif yas is not None and yas * DAKIKA >= VERI_DALI_COMMIT_UYARI:
            b.append(Bulgu("UYARI", "veri_dali_bayat", f"Veri dalının son commit'i {_sa(yas)} eski."))
    return b


def vardiya_kosu_bulgusu(kosular: list[dict[str, Any]] | None, veri_taze: bool | None = None) -> Bulgu | None:
    """GitHub REST `workflow runs` listesinden (en yeni önce) üretim vardiya koşusu sonucu. Bakılan: en yeni TAMAMLANMIŞ koşu.
    `failure`/`timed_out`: KRITIK, ANCAK ardından başlamış çalışan/bekleyen koşu varsa ya da veri dalı taze ise (`veri_taze`) yalnız BILGI ("önceki koşu düştü, sonrakisi çalışıyor");
    ardından daha yeni tamamlanmış `success` zaten en yeni tamamlanmış koşu olur (bulgu yok). `cancelled` (concurrency/süre sınırı) yalnız BILGI. Liste yok/boş/okunamadı: bulgu yok."""
    sonra_calisan = False
    for r in kosular or []:
        if r.get("status") != "completed":
            sonra_calisan = True
            continue
        sonuc, no = r.get("conclusion"), r.get("run_number") or r.get("id")
        if sonuc in ("failure", "timed_out"):
            if sonra_calisan or veri_taze:
                return Bulgu("BILGI", "vardiya_kosusu_duzeldi", f"Önceki vardiya koşusu (#{no}) {sonuc} bitti, sonrakisi çalışıyor/veri taze (alarm yok).")
            return Bulgu("KRITIK", "vardiya_kosusu_basarisiz", f"Son üretim vardiya koşusu (#{no}) {sonuc} bitti, yenisi çalışmıyor: {r.get('html_url') or VARDIYA_IS_AKISI}")
        if sonuc == "cancelled":
            return Bulgu("BILGI", "vardiya_kosusu_iptal", f"Son vardiya koşusu (#{no}) iptal edildi (concurrency/süre sınırı olabilir; adımsız iptal normaldir).")
        return None
    return None


def kontrol(simdi_ms: int, ozet: dict[str, Any] | None, kadro: dict[str, Any] | None, *, pano_ms: int | None = None, canli_pano_ms: int | None = None, canli_pano_ulasildi: bool | None = None,
            motor: dict[str, Any] | None = None, risk: dict[str, Any] | None = None, dur_dosyasi: bool = False, olaylar: list[dict[str, Any]] | None = None,
            vardiya_kosulari: list[dict[str, Any]] | None = None, veri_dali_commit_ms: int | None = None) -> list[Bulgu]:
    """Bulguları döndürür (boşsa sağlıklı). `pano_ms`: veri dalındaki pano dosyasının son güncelleme anı; `canli_pano_ms`: Cloudflare'deki sayfanın içindeki veri anı (`data-ms`);
    `canli_pano_ulasildi`: sayfa indirilebildi mi (None = bu ölçüm yapılmadı)."""
    b: list[Bulgu] = []

    # --- motor / vardiya
    if not ozet:
        b.append(Bulgu("KRITIK", "ozet_yok", "Motor özeti (durum/ozet.json) okunamadı: vardiya hiç yazmamış olabilir."))
        b.extend(kalici_kontrol(simdi_ms, motor, risk, dur_dosyasi, olaylar, None, vardiya_kosulari, veri_dali_commit_ms))
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
        b.extend(kalici_kontrol(simdi_ms, motor, risk, dur_dosyasi, olaylar, ozet.get("kayit_sayac"), vardiya_kosulari, veri_dali_commit_ms, ozet.get("yazildi_ms")))
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
        elif gecti is not None and int(gecti) < 11:
            b.append(Bulgu("UYARI", "kadro_11den_az", f"Radarı geçen {int(gecti)} kişi: kadro 11'den az; saha dolmayabilir (otomatik true'ya dönülmez, lider karar verir)."))
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


def _git_var(dal: str, yol: str) -> bool:
    import subprocess
    return subprocess.run(["git", "cat-file", "-e", f"origin/{dal}:{yol}"], capture_output=True).returncode == 0


def _git_son_commit_ms(dal: str) -> int | None:
    import subprocess
    s = subprocess.run(["git", "log", "-1", "--format=%ct", f"origin/{dal}"], capture_output=True, text=True)
    return int(s.stdout.strip()) * 1000 if s.returncode == 0 and s.stdout.strip() else None


def _git_fetch(dallar: list[str]) -> bool:
    """CLI başında `git fetch origin <dal>`: bayat YEREL ref yanlış KRİTİK üretmesin (2026-11-06 gecesi). Başarısızsa False (bulgu üretilmez; yalnız bilgi satırı)."""
    import subprocess
    try:
        return subprocess.run(["git", "fetch", "origin", *dallar], capture_output=True, text=True, timeout=120).returncode == 0
    except Exception:                                                                        # noqa: BLE001
        return False


def kayit_olaylari(dal: str, simdi_ms: int) -> list[dict[str, Any]] | None:
    """Dünün ve bugünün (UTC; gece yarısı geçişi için) `kayit/<tarih>.jsonl` satırları; hiç dosya yoksa None."""
    import json
    import time
    out, bulundu = [], False
    for d in (1, 0):
        ham = _git_oku(dal, f"kayit/{time.strftime('%Y-%m-%d', time.gmtime((simdi_ms - d * 86_400_000) / 1000))}.jsonl")
        if ham is None:
            continue
        bulundu = True
        for satir in ham.splitlines():
            try:
                o = json.loads(satir)
            except ValueError:
                continue
            if isinstance(o, dict):
                out.append(o)
    return out if bulundu else None


def vardiya_kosulari_oku(url: str = "", timeout: int = 20) -> list[dict[str, Any]] | None:
    """GitHub REST (public repo: herkese açık okuma, token gerekmez). Ağ/ayrıştırma hatasında None (bulgu üretilmez)."""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url or KOSU_API.format(wf=VARDIYA_IS_AKISI), headers={"User-Agent": "sg-saglik/1", "Accept": "application/vnd.github+json"}), timeout=timeout) as r:
            return list(json.loads(r.read().decode("utf-8")).get("workflow_runs") or [])
    except Exception:                                                                        # noqa: BLE001
        return None


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
    if not _git_fetch([args.veri_dali, args.kadro_dali]):
        print("BILGI: git fetch başarısız; yerel ref'ler bayat olabilir (bu yüzden bulgu üretilmedi).")
    ozet_ham, kadro_ham = _git_oku(args.veri_dali, "durum/ozet.json"), _git_oku(args.kadro_dali, "radar/son/kadro.json")
    ozet, kadro = (json.loads(ozet_ham) if ozet_ham else None), (json.loads(kadro_ham) if kadro_ham else None)
    canli_ms, ulasildi = None, None
    if args.canli_url:
        try:
            with urllib.request.urlopen(urllib.request.Request(args.canli_url, headers={"User-Agent": "sg-saglik/1"}), timeout=30) as r:
                canli_ms, ulasildi = canli_sayfa_ms(r.read().decode("utf-8", "replace")), True
        except Exception:                                                                    # noqa: BLE001 - ağ hatası: bulgu olarak raporlanır, kontrol çökmez
            ulasildi = False
    motor_ham, risk_ham = _git_oku(args.veri_dali, "durum/motor.json"), _git_oku(args.veri_dali, "durum/risk.json")
    bulgular = kontrol(simdi, ozet, kadro, pano_ms=_git_zaman_ms(args.veri_dali, "pano/index.html"), canli_pano_ms=canli_ms, canli_pano_ulasildi=ulasildi,
                       motor=json.loads(motor_ham) if motor_ham else None, risk=json.loads(risk_ham) if risk_ham else None, dur_dosyasi=_git_var(args.veri_dali, "durum/DUR"),
                       olaylar=kayit_olaylari(args.veri_dali, simdi), vardiya_kosulari=vardiya_kosulari_oku(), veri_dali_commit_ms=_git_son_commit_ms(args.veri_dali))
    metin, st = ozet_metin(bulgular), durum(bulgular)
    print(f"DURUM: {st}\n{metin}")
    if args.telegram and st != "SAGLIKLI":
        saat_utc = int(time.strftime("%H", time.gmtime(simdi / 1000)))
        if st == "KRITIK" or saat_utc % 3 == 0:
            from copytrade.canli import telegram as tg
            t = tg.Telegram()
            if t.acik:
                if not t.gonder(tg.alarm("ALARM: sistem sağlık kontrolü" if st == "KRITIK" else "Sağlık uyarısı", metin)):
                    print("HATA: Telegram alarmı gönderilemedi", file=sys.stderr)                 # sessiz yutulmaz: iş kırmızı biter
                    return 2
            else:
                print("UYARI: Telegram anahtarı yok; alarm gönderilemedi", file=sys.stderr)
    return 2 if st == "KRITIK" else 0                                                       # KRITIK: iş kırmızı biter (Actions e-postası + görünür)


if __name__ == "__main__":
    raise SystemExit(main())
