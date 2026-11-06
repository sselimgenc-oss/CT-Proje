> **KAPANDI (2026-11-06 18:05Z):** kullanıcı kararıyla liderlik Opus'a döndü. Bu belge kayıt olarak kalır; §4 yetkileri artık geçerli değil (AGENTS kural 8 geçerli).

# Lider devri: Claude (Opus) → Sonnet, 2026-11-05 → 2026-11-09 (Pazartesi) 14:00 TSİ

Kullanıcı kararı: lider (Opus) haftalık limitine yaklaştı. Pazartesi 14:00 TSİ'ye kadar **liderlik görevi Sonnet'te**. Bu belge o süre için
geçerli kuralları içerir. Pazartesi 14:00'te lider geri döner ve devir dönemindeki her birleştirmeyi denetler. Kullanıcı Selim'dir.
Türkçe yazar, teknik değildir, çoğunlukla telefondan bakar. Kısa, maddeli ve sade yaz.

## 1. Sistem tek bakışta
- **Strateji:** Form Radarı v1 (`docs/RADAR_V1.md`). R0 (HL lider tablosu, 7 gün getiri, ilk 300) → R1 kopyalanabilirlik kapısı →
  R2 form puanı → R3 kadro (İlk 11 + Yedek 19) → canlı motor İlk 11'i kopyalar.
- **Kararlar:** K‑19 … K‑37 (`docs/KARARLAR.md`). En yeniler:
  - K‑35: slot toplam tavanı, marj tavanı, tek payda;
  - K‑36: artırma hedef tabanlı;
  - K‑37: denetim sonrası T4b; gerçek kipe geçiş kullanıcı kararı.
- **Motor:** `copytrade/canli/`. Kip **sanal**: cüzdan yok, 1.000 $ yatırılmış gibi ("demo"). Gerçek kip yalnız sunucuda (T5) ve kullanıcı kararıyla açılır.
- **Akışlar:**
  - `radar.yml`: her gün 00:37 UTC, yedek 02:17. Veri dalı `radar`.
  - `canli_vardiya.yml`: 4 saatte bir, 4 sa 15 dk. main → `canli-durum`; deneme dalları → `canli-durum-deneme`.
  - `radar_deneme.yml` / `isabet_deneme.yml`: dal denemeleri, `CALISTIR` dosyasına satır eklenince tetiklenir.
  - CI: `ci.yml`.

## 2. Durum (2026-11-05 06:50 UTC)
- **main'de:** T2, T3, T4 (#504; K‑35 ve K‑36 dahil). Üretim sanal vardiyası main'de koşuyor (run 41971075707, `canli-durum`).
- **Açık PR'lar:**
  - **#510 T4b:** vardiya run 41971493275 ~09:17 UTC'de biter.
  - **#512 T6:** T4b'den sonra main alınıp çakışmalar çözülecek.
- **`radar` dalı:** 2026-11-05 kadrosunda 12 trader geçti. 05.11 gecesi cron tetiklenmedi, koşu elle başlatıldı; yedek cron T6'da.
- **İlk isabet ölçümü:** 2026-11-12 (devir döneminden sonra).

## 3. Devir döneminde yapılacaklar (sırayla)
1. **T4b vardiyası bitince (#510):** `canli-durum-deneme` `durum/ozet.json` ve `kayit/*.jsonl`'e bak. Kabul ölçütleri:
   - artırma emirleri çalışıyor, `hesap_yok` ≈ 0;
   - tek emir > 3 × slot (272,73 $) yok, 261 $ tipi "11 $ açılış → dev artırma" zinciri yok;
   - `kapanis_eksik` = 0 (sanal kipte);
   - `gec_acilis`, `min_nosyonel`, `funding_usd`, `kuyruk_gecikme_ms` raporlu ve makul;
   - 429 = 0 ya da çok az; vardiya ≥ 4 sa sürdü;
   - CI yeşil.
   Hepsi sağlanırsa: PR'ı ready yap, sayıları açıklamaya yaz, **tam SHA** ile squash birleştir.
2. **T6 (#512):** main'i al, T4b çakışmalarını çöz, tam test. PR açıklamasında şunlar olmalı:
   - para hareketi gerçek veri koşusu (20 aday) çıktısı;
   - `pano/OZET.md` örneği;
   - CI yeşil.
   Sonra birleştir. Birleşince bir sonraki main vardiyasından sonra `canli-durum:pano/OZET.md` oluştu mu kontrol et.
3. **Her gün (kısa kontrol):**
   - `radar.yml` koştu mu, `radar/<tarih>/kadro.json` var mı, gecti sayısı kaç (beklenen 8–20);
   - main vardiyaları birbirini izliyor mu (boşluk, BAŞLAMADI, kopma, 429);
   - kasa ve özsermaye makul mü (−%5 günlük / −%20 zirve kuralları çalışıyor mu).
   Kullanıcıya günde bir kısa özet ver.
4. **Kullanıcı "Telegram tamam" derse:** bir sonraki vardiyada "vardiya başladı" ve günlük özet mesajları gidiyor mu kontrol et. `telegram_hata` sayacına bak.
5. **Zaman kalırsa küçük temizlikler:**
   - `AGENTS.md` kalite kuralı 3 ve sadeleştirme 7'nin yarım kalan satırlarını tamamla (anlamı değiştirme);
   - kullanılmayan `sonnet_isci.yml` varsa kaldır (test listesini güncelle);
   - `copytrade-izleme` dalı: silme, lidere not bırak.

## 4. Yetkiler — bu dönemde Sonnet KARAR VEREBİLİR
- Kabul kanıtı (AGENTS: altın örnek, gerçek çıktı özeti, tam test) olan kendi PR'larını birleştirmek. Kural 8'in "tek denetçi" şartı bu dönemde
  **kendi kendini denetleme kontrol listesiyle** (§6) karşılanır. Her birleştirmeye "devir dönemi; lider 09.11'de denetleyecek" notu düşülür.
- Hata düzeltmesi, test ekleme, iş akışı ve zamanlama onarımı, belge düzeltmesi.
- Görev belgesinde yazmayan küçük uygulama kararları. Bunlar `docs/sonnet_durum_<iş>.md`'ye yazılır.

## 5. Yetkiler — bu dönemde YAPILMAZ (lidere / kullanıcıya bırak)
- `RADAR_V1.md` ve `kurallar.yaml` `radar_*` eşik, ağırlık ve yöntem değişikliği; yeni K‑kararı. Gerekirse öneriyi `docs/sonnet_durum_devir.md`'ye yaz.
- **Gerçek kip, cüzdan, API anahtarı, sunucu (T5), kasa artırımı.** Kullanıcı isterse bile: "lider dönünce birlikte" de. Kullanıcı ısrar ederse
  kararı onundur, ama kod tarafında T4b madde 1–5 ve 7 main'de olmadan gerçek kip açılmaz (K‑37).
- Geri dönülmez silme: dal, veri dalı, geçmiş.
- `main`'e doğrudan push, force push, test zayıflatma/atlama/silme.
- Herkese açık repoya anahtar, token ya da kişisel veri yazmak. Secret'ları kullanıcı kendisi GitHub Settings'ten ekler; değerleri sohbette asla isteme.

## 6. Kendi kendini denetleme listesi (birleştirmeden önce, PR'a işaretle)
- [ ] Tam test paketi geçti (sayı yazıldı); CI yeşil.
- [ ] Gerçek veri çıktısına baktım: sayılar akla yatkın, uç değer yok (getiri milyonlarca % olamaz, kasa 1.000 $ ölçeğinde).
- [ ] Eşik, ağırlık, yöntem değişmedi (ya da değişiklik görev belgesinde açıkça istendi).
- [ ] Hesap değiştiyse altın örnek testi var; eski ↔ yeni sayılar yan yana.
- [ ] Gerçek kip yolu Actions'ta çalışamaz (`GITHUB_ACTIONS` reddi testleri yeşil).
- [ ] Belgede olmayan kararlar `sonnet_durum_*.md`'de.

## 7. Bilinen tuzaklar
- Birleştirme tam 40 karakterlik SHA ister; taslak PR önce ready yapılır.
- `workflow_dispatch` / koşu iptali MCP'den 403 verir. Tetikleme `CALISTIR` dosyasına satır eklenerek yapılır. Koşuyu elle başlatma gerekirse
  kullanıcıdan iste: GitHub → Actions → iş akışı → "Run workflow".
- Artifact indirme proxy'de engelli. İş günlüklerini oku ya da veri dalını `git fetch` ile çek.
- Deneme dalları `canli-durum-deneme` kilidini paylaşır. Aynı anda iki deneme vardiyası olmaz, ikincisi "BAŞLAMADI" ile durur. Bu beklenen davranıştır.
- `test_dolgu_429` ara sıra zamanlama nedeniyle düşer (bilinen). Tek başına geçiyorsa not düş, testi değiştirme.
- HL 10 $ altı reduce-only kapanış muafiyeti doğrulanmadı (`sonnet_durum_t4b.md` #3). T5'te kullanıcı onayıyla denenir.

## 8. Pazartesi 14:00'te lidere teslim
`docs/sonnet_durum_devir.md` dosyasına şunlar yazılır:
- birleştirilen PR'lar ve kabul sayıları;
- açık sorunlar;
- kullanıcıya verilen sözler;
- önerilen kararlar (lider onayına);
- günlük kontrol tablosu: tarih, gecti, vardiya sayısı, kasa, olay.
