# T3 durum notu (Sonnet) — belgede yazmayan, tahminle seçilen küçük kararlar (lider onayına)

Belgede açık olmayan ama ilerlemeyi engellemeyen noktalar; her biri kodda tek yerde ve testle sabit. Karar gerekirse lider değiştirir.

1. **Trader hesap paydası (boyut oranı):** `kopya_v5` oranın paydası olarak lider tablosundaki `accountValue` (koşu anı) kullanır; her dolumda ayrı hesap değeri okunmaz (canlı motor T4 dolum anındaki değeri okur).
2. **Artırmada tavan:** `boyut.hedef_emir('artir')` toplam pozisyonu `radar_slot_tavan_carpan × slot` (3,0 ×) ile sınırlar (RADAR §6 "slot başına pozisyon tavanı 3,0x"); belge yalnız açılış tavanını yazıyor.
3. **11 $ altı azaltma:** yalnız emir < 11 $ iken "kalan < 11 ise tamamı kapat" uygulanır (§5b metni birebir).
4. **Form sürüyor (72 sa):** aynı dolumlar `kopya_v5` ile oynatılır, pencere = son 72 sa ve pencere başında BOŞ (pencere öncesi açılan pozisyonlar kopyalanmaz). Ölçü yoksa (None) `soguyor` sayılır; hesaplanamayan (yürütülebilir dolum yok) = 0 getiri.
5. **İ1 aktif gün:** günlük kopya getirisi ≠ 0 olan gün; aktif gün yoksa İ1 = 0. **Y:** 1 − (en iyi tek işlem / kârlı işlemler toplamı); kâr yoksa 0.
6. **H brüt kâr:** trader'ın kârlı round trip `net_pnl` toplamı (açılışı pencere öncesi olan kârlı işlem toplama girer, erken sayılmaz). Trend coin eşiği: `numpy.quantile(|getiri|, 1 − 0,25)` (≥). Listelenme: ilk saatlik mum 30 günlük pencerenin başından 1 saatten sonra ise "yeni".
7. **`kopya_gunluk` yalnız `gecti` satırlarında** (korelasyon + İ1 için); diğer satırlarda `null` (sözleşme §12).
8. **Dal koşusu:** `radar.yml` push tetiği yalnız `copytrade/radar/CALISTIR` değişince; main dışı daldan koşan iş akışı gerçek `radar` dalına değil `radar-deneme` dalına yazar (`VERI_DALI`). Birleşince günlük koşu (cron) `radar` dalına yazar.
9. **Eksik koşu:** `zaman_yok` satırı var ya da satır sayısı < min(`radar_aday_tavan`, `evren_toplam`) ise `radar_kadro` çıkış kodu 2, `kadro.json` yazılmaz, `son/` güncellenmez. Tek `veri_hatasi` koşuyu eksik saymaz.
10. **5xx:** radar istemcisi `KAPI_YENIDEN_BEKLEME` (5/15/45 sn) ile 3 yeniden deneme yapar (`radar_istemcisi`); 429 ilkesi değişmedi.
