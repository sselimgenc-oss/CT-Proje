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
- **Kalıcı durum (G2, 2026-11-06):** kontrol ayrıca `durum/motor.json` (`kapanis_kuyrugu` içinde `eksik` girdi → KRİTİK; vardiya sayacından bağımsız), `durum/risk.json` + `DUR` dosyası (`mutabakat` bayrağı, `dur` → KRİTİK; `gunluk_kayip`, `elle_dur`, `kasa_siniri` → UYARI), son 2 saatin `kayit/<tarih>.jsonl` olayları (`vardiya_baslamadi`, `vardiya_boslugu` → KRİTİK; `kuyruk_tasti`, `kadro_bayat` → UYARI), `ozet.kayit_sayac` `adim_hata`/`olay_hata`/`defter_hata` > 0 (KRİTİK), son TAMAMLANMIŞ `canli_vardiya.yml` main koşusu (GitHub REST, herkese açık okuma, token yok; `failure`/`timed_out` → KRİTİK, `cancelled` yalnız BİLGİ; ağ hatasında bulgu yok) ve veri dalı son commit yaşı (> 45 dk UYARI, > 90 dk KRİTİK) okunur. Eşikler/kodlar `saglik.py` sabitleridir.
- **Bayat yerel ref koruması:** CLI başında `git fetch origin <veri-dalı> <kadro-dalı>` denenir; başarısızsa bulgu üretilmez, yalnız `BILGI:` satırı yazılır (elle koşuda `git fetch` unutulması yanlış KRİTİK üretmesin).
- Sınır: GitHub cron'u bazen geç/hiç tetiklenir; panodaki tarayıcı "VERİ BAYAT" uyarısı ikinci güvenlik ağıdır.
