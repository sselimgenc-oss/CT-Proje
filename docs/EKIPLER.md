# Ekipler (sistemin "organizasyon şeması") — kullanıcı tanımı 2026-11-05

Kullanıcı sistemi bir şirket gibi görür. Her ekibin kodda/işte neye karşılık geldiği ve **ne kadar otomatik** olduğu:

| Ekip | Gerçekte ne | Otomatik mi? |
|---|---|---|
| **Makam odası** | Pano (`canli-durum:pano/index.html` → Cloudflare `sg-pano`) + Telegram komutları (`/dur /devam /kapat /durum`) | Evet (15 dk) |
| **Laboratuvar / Ar-Ge** | Radar (`radar.yml`, `copytrade/radar/`): günde bir 300 aday, R0/R1/R2, İlk 11 kadro | Evet (günlük) |
| **Haberleşme** | `copytrade/canli/telegram.py`: emir özeti (15 dk), alarm, günlük özet, komutlar | Evet |
| **Finans** | `copytrade/canli/risk.py` + `mutabakat`: kasa sınırı, günlük kayıp, zirveden düşüş, defter ↔ borsa mutabakatı | Evet (gerçek zamanlı) |
| **İdari İşler** | Veri dalları `canli-durum` (kayıt 14 gün), `radar` (90 gün), `canli-durum-deneme` | Evet (15 dk) |
| **Sekreterya** | `docs/KARARLAR.md`, `DURUM.md`, `docs/sonnet_durum_*.md`, devir belgeleri | Elle (Sonnet/Lider) |
| **Bilgi İşlem** | Testler + CI (`ci.yml`, `pytest`) **ve sağlık kontrolü** (`saglik.yml`, `copytrade/saglik.py`) | Test: her PR; sağlık: saatlik |
| **Denetim** | Lider (Opus) incelemesi; haftalık denetim rutini | Elle / haftalık rutin |

## Sağlık kontrolü (Bilgi İşlem + Denetim; kullanıcı kararı 2026-11-05 "kritik bulgu")
Eksik bulunmuştu: arka planda çalışan sistemde bir şey ters giderse kimse fark etmiyordu. Şimdi:
- **Pano ÖZET → "Sağlık" kutusu** (her 15 dk): motor ve radar yaşı, kapanış eksik, motor durdu, Telegram/bağlantı hataları, radar geçen sayısı (8–20 dışı uyarı).
- **`saglik.yml` (saatlik, salt okur):** aynı kontrol + veri dalındaki pano yaşı + **Cloudflare'deki canlı sayfa** erişilebilir mi / bayat mı. KRİTİK bulguda iş kırmızı biter ve Telegram'a `ALARM` gider; UYARI 3 saatte bir.
- Seviyeler: `KRITIK` (acil: vardiya durdu, kapanış eksik, radar çok eski, kadro/özet yok), `UYARI`, `BILGI`. Eşikler `copytrade/saglik.py` başındaki sabitlerdir (strateji eşiği değildir).
- Sınır: GitHub cron'u bazen geç/hiç tetiklenir; panodaki tarayıcı "VERİ BAYAT" uyarısı ikinci güvenlik ağıdır.

## Vardiya zinciri (G3, 2026-11-06)
- GitHub cron geç kalıyor/kaçırıyor (05.11: 157 dk boşluk). Çare: `canli_vardiya.yml` içinde AYRI `zincir` işi (`needs: vardiya`, yalnız main ve yalnız vardiya başarılıysa, checkout yok) bir sonrakini `gh workflow run canli_vardiya.yml --ref main` ile tetikler; aynı işte vardiya sonu bir kez `saglik.yml` de tetiklenir (saglik.yml kendi saatlik cron'unu korur). Dal denemeleri zincirlemez. Cron (7 ve 37. dk) yedek olarak durur.
- Actions yazma izni yalnız `zincir` işindedir; vardiya/kontrol işleri (pip, wrangler, motor) bu yetkiyi görmez.
- Çift vardiya olmaz: dispatch koşusu `zamanlama_kontrol.sh` içinde taze kilitte (20 dk nabız) atlar; `concurrency` yeni koşuyu eski koşu (zincir işi dahil) TAMAMEN bitene kadar bekletir; fazla bekleyen koşu iptal olur (`cancelled`; G2 (#559) birleşince sağlık bunu bilgi sayar).
- Dispatch başarısızsa `::warning` + Telegram uyarısı; yedek cron ve vardiya hata alarmı sürer.
