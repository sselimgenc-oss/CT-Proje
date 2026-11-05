# Görev T6 — İsabet ölçümü, rapor, pano (K‑37 ekleri dahil)

Dal: `claude/t6-rapor-isabet` (main'den). Yeni hesap kodu altın örnek testle gelir; eşik ve ağırlık DEĞİŞMEZ (bu iş yalnız ölçer).
Önce küçük gerçek veri denemesi (AGENTS kalite 1), sonra tam koşu.

## 1. Seçim isabeti (RADAR_V1 §7b) — ilk ve en önemli madde
- `radar.yml` her gün, **7 gün önceki** `radar/<tarih>/havuz.json` + `kadro.json` için arada geçen 7 günün kopya getirisini hesaplar (`sonraki_7g`).
  Hesap R1/6'daki `kopya_v5` oynatmasıyla aynıdır: 1 dk gecikme + maliyet, aynı slot. Kural 7: yeni hesap yazılmaz, `kopya_v5` çağrılır.
- **Ölçülen gruplar:**
  - (i) o günün İlk 11'i;
  - (ii) R1 havuzunun geri kalanı (Yedek dahil);
  - (iii) kopya aşamasına varıp elenenler, en çok 30 kişi; sabit tohumla rastgele seçilir, tohum dosyaya yazılır.
- **Çıktı `radar/<tarih>/isabet.json`:**
  - form ↔ `sonraki_7g` Spearman IC;
  - İlk 11 ortalaması − havuz ortalaması;
  - İlk 11 ortalaması − elenenler ortalaması;
  - grup başına n / ortalama / medyan / kârda olanların oranı.
- **Kötü senaryo:** aynı ölçüm kayma 2× ve gecikme 3 dk ile tekrarlanır; sütun adı `_kotu` ekiyle biter (K‑37).
- Süre bütçesi: isabet adımı en çok 30 dk. Aşılırsa eksik yazılır ve işaretlenir; tarama işi bozulmaz.
- İlk ölçüm 2026-11-12'de (`radar` dalının ilk günü 2026-11-05). O zamana kadar `radar-deneme` geçmişiyle küçük deneme yapılır.

## 2. Trader para hareketi (K‑37)
- Havuzdaki herkes için pencere içi `userNonFundingLedgerUpdates` okunur. Hesaplananlar:
  - `net_yatirma_usd`: yatırma − çekme;
  - `yatirma_payi` = net yatırma / hafta başı sermaye.
- Yalnız bilgi amaçlıdır, kapıyı değiştirmez. Raporda `yatirma_payi` > 0,2 olanlar işaretlenir. Alan `VERI_SOZLESMESI`'ne birimiyle yazılır.

## 3. Günlük rapor (Markdown; telefondan GitHub'da okunur)
- `canli-durum` dalında `pano/OZET.md` her vardiya sonunda güncellenir. İçeriği:
  - kasa ve özsermaye, gün/hafta/toplam getiri, zirveden düşüş;
  - açık pozisyonlar: trader kısaltması, coin, $, K/Z;
  - son 24 saatte emir, dolum, kayma p50/max, funding, ücret;
  - saha değişiklikleri ve nedenleri;
  - risk olayları;
  - vardiya sağlığı: süre, kopma, boşluk, 429.
- Aynı sayfada son 7 isabet satırı yer alır (madde 1). Isabet yoksa "ilk ölçüm 2026-11-12" yazılır.
- Yalnız mevcut kayıt/durum dosyalarından üretilir (kural 7). Saf fonksiyon yazılır ve testle doğrulanır.

## 4. Zamanlama güvencesi
- 2026-11-05'te `radar.yml` cron'u hiç tetiklenmedi; koşu elle başlatıldı. 02:17 UTC'ye yedek cron eklenir: o günün `radar/<tarih>/` klasörü varsa iş hiçbir şey yapmadan biter.
- `canli_vardiya.yml` için de aynı yöntem kurulur: yedek cron, kilit taze ise başlamaz. Bu durumda "BAŞLAMADI" alarmı gönderilmez; bu beklenen bir durumdur, bilgi satırı olarak kayda geçer.

## Kabul
- Tam test sonucu PR açıklamasına yazılır.
- Gerçek veri koşusu yapılır: `radar-deneme` geçmişiyle en az 1 isabet dosyası üretilir. Sayılar PR'a eklenir (grup n, IC, farklar).
- `pano/OZET.md`'nin bir örneği PR açıklamasına konur.
- Belgede olmayan bir karar gerekirse iş durur ve soru `docs/sonnet_durum_t6.md`'ye yazılır.
