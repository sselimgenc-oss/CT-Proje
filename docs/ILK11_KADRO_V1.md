# İlk 11 kadro v1 — Faz 1 karar belgesi


## Yol haritası

1. **Faz 1 — Karar belgesi ve veri modeli:** kadro kuralları, puanlama kararları ve verinin nasıl temsil edileceği.
2. **Faz 2 — 14 oda iç kararları:** oda üyeliği ve kadro içi yönetim kararları.
3. **Faz 3 — Canlı hesap/cüzdan ve HL işlem hattı:** ayrı güvenlik ve onay kapıları gerekir. Şu an PAPER modunda kalınır; gerçek emir ve sıcak cüzdan bu fazın hedefidir.

## Kullanıcı kararları

- **Evren:** Yalnız Hyperliquid (HL).
- **Başlangıç:** Pazar 13:00 Türkiye saati. Başarısız olursa aynı dondurulmuş girdi ve snapshot ile iki saatte bir yeniden denenir; yeni veriyle girdi yenilenmez.
- **Kadro:** 50 kapıdan; İlk 11 = 11, Yedek 11 = 11, PAF = 28. PAF kadro dışıdır; bu üç grubun üyesi sayılmaz.
- **İlk dağıtım:** Kapı sıralamasına göre ilk 11 İlk 11'e, sonraki 11 Yedek 11'e, sonraki 28 PAF'a atanır. Başlangıç dağıtımı sonrası terfi/düşme kuralları uygulanır.
- **Eşikler:** 60 üstü yükselmeye uygun, 40 altı düşmeye adaydır. Bunlar tek başına otomatik işlem değildir; aşağıdaki ardışık geçerli gözlem şartı da uygulanır.
- **Düşüş:** İki ardışık Pazar geçerli HL işlemi yoksa düşüş uygulanır.
- **Terfi eşitliği:** Önce form puanı; eşitse geçmiş kapı puanı; o da eşitse geçerli gözlem süresi daha uzun olan öne geçer.
- **Düşüş zinciri:** Form veya iki Pazar hareketsizlik nedeniyle her kademe yalnız bir altına iner: İlk 11→Yedek 11→PAF→kadro dışı. PAF işlem yapan kadro değildir.


|---|---|---|


## İlk11 İşlem Politikası v1 — kaynak referansı


- Giriş fiyat bandı: üst +%1, alt −%2; azami kaldıraç 5x.
- Marj bazlı stop: −%50. Ana para eşiğinde (%100 marj getirisi) pozisyonun %50'si alınır. Zirve marj getirisi %40'ı gördükten sonra zirveden %45 düşüşte kapat.
- Süreli stoplar: 12 saatte −%25, 24 saatte −%15, 48 saatte −%5. Süreli kâr alma: 24 saatte +%10, 48 saatte +%5. Azami pozisyon süresi 168 saat; trader satışı aynalanır.

## Faz 1 yürütme sınırı

İlk seçimde uygunluk kapısı yalnız evreni belirler; puan, uygun tüm HL adayları üzerinde yüzdelik sıralanır, en iyi 50 alınır. Eşit puanlarda form puanı, geçmiş kapı puanı, geçerli gözlem süresi, sonra sabit `id` kullanılır. Pazar geçişi yalnız plan döndürür; izleme listesine yazmaz. Geçerli tek Pazar snapshotında form ≥60 üst gruba yükselmeye uygunluk, <40 bir alt gruba düşüş adayıdır; eksik/geçersiz form hareket üretmez. İki ardışık Pazar aktivitesizliğinde de her grup yalnız bir alt gruba düşer: İlk11→Yedek→PAF→kadro dışı. Terfi yalnız komşu gruplar arasındadır: PAF→Yedek (≥60), Yedek→İlk11 (≥60 ve son 6 geçerli PAPER işlemi toplamı >0, kazanma oranı ≥0,40, en iyi işlem çıkarılınca toplam >0). Kod PAPER planıdır; cüzdan/emir yoktur.

İlgili mevcut alanların sözleşmesi `docs/VERI_SOZLESMESI.md` içindedir. Bu belge yeni veri alanı veya motor davranışı tanımlamaz.

## Pazar snapshot veri biçimi (Faz 1)


Snapshot; Türkiye saatiyle Pazar 13:00 anını, kaynak sürümlerini, normalize edilmiş adayları ve ilk 50'nin `ilk11`/`yedek11`/`paf` dağılımını taşır. Kanonik JSON gövdesinin SHA-256 özeti `snapshot_id` olur; `snapshot_json` içerik değişimini hash ile doğrular. Bu aşamada snapshot oluşturma saf bir fonksiyondur; dosyaya yazma, kalıcı kayıt veya yeniden deneme orkestrasyonu yapmaz.

**Pazar planlayıcısı teknik notu:** Pazar planlayıcısı yan etkisizdir; ilk koşuyu `Europe/Istanbul` saat diliminde Pazar 13:00’te açar, başarısızlıktan sonra son başarısızlık zamanına iki saat ekleyerek tekrar zamanlar. Her tekrar aynı `snapshot_id` ile doğrulanır; kimlik uyuşmazlığı reddedilir. Başarı sonrası yeni deneme planlanmaz. Henüz snapshot yoksa `snapshot_hazirla` eylemi üretir.
