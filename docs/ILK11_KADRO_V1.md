# İlk 11 kadro v1 — Faz 1 karar belgesi

Bu belge Faz 1 kararlarını ve veri modelini kaydeder. Kaynak karşılaştırması için Etre v2'nin `f3f5cff92d6db2fff62b6f7753c45343e00583ba` commit'i salt okunur referanstır. İlk 11 şu aşamada canlı fiyatlarla PAPER izlenir; gerçek emir ve sıcak cüzdan Faz 3 hedefidir ve bu fazın kapsamı dışındadır.

## Yol haritası

1. **Faz 1 — Karar belgesi ve veri modeli:** kadro kuralları, puanlama kararları ve verinin nasıl temsil edileceği.
2. **Faz 2 — 14 oda iç kararları:** oda üyeliği ve kadro içi yönetim kararları.
3. **Faz 3 — Canlı hesap/cüzdan ve HL işlem hattı:** ayrı güvenlik ve onay kapıları gerekir. Şu an PAPER modunda kalınır; gerçek emir ve sıcak cüzdan bu fazın hedefidir.
4. **Faz 4 — Pano ve ofis görünümü:** kadro, durum ve işlem hattı sonuçlarının kullanıcı arayüzleri.

## Kullanıcı kararları

- **Evren:** Yalnız Hyperliquid (HL).
- **Başlangıç:** Pazar 13:00 Türkiye saati. Başarısız olursa aynı dondurulmuş girdi ve snapshot ile iki saatte bir yeniden denenir; yeni veriyle girdi yenilenmez.
- **Kadro:** 50 kapıdan; İlk 11 = 11, Yedek 11 = 11, PAF = 28. PAF kadro dışıdır; bu üç grubun üyesi sayılmaz.
- **İlk dağıtım:** Kapı sıralamasına göre ilk 11 İlk 11'e, sonraki 11 Yedek 11'e, sonraki 28 PAF'a atanır. Başlangıç dağıtımı sonrası terfi/düşme kuralları uygulanır.
- **Eşikler:** 60 üstü yükselmeye uygun, 40 altı düşmeye adaydır. Bunlar tek başına otomatik işlem değildir; aşağıdaki ardışık geçerli gözlem şartı da uygulanır.
- **Düşüş:** İki ardışık Pazar geçerli HL işlemi yoksa düşüş uygulanır.
- **Terfi eşitliği:** Önce form puanı; eşitse geçmiş kapı puanı; o da eşitse geçerli gözlem süresi daha uzun olan öne geçer.
- **Yedek → İlk 11 kapısı:** Etre HL'nin son 6 geçerli PAPER işlemi; toplam sonuç pozitif, kazanma oranı en az %40 ve en iyi işlem çıkarıldığında kalan toplam da pozitif olmalı. İşlem sayısı altıya ulaşmayan aday geçemez.
- **Düşüş zinciri:** Form veya iki Pazar hareketsizlik nedeniyle her kademe yalnız bir altına iner: İlk 11→Yedek 11→PAF→kadro dışı. PAF işlem yapan kadro değildir.

## Etre kaynağı ve Faz 1 uyarlaması

| Konu | Etre v2 referansı | Faz 1 kararı / uyarlama |
|---|---|---|
| Puan | `etre2/puan.py`: 10 alanı ayrı ayrı yüzdelik sıraya çevirir (0–100), ağırlıklı ortalama alır; veri yoksa alan puanı 35 olur. | `copytrade/ilk11.py` uygunluk kapısından geçen tüm HL evreninde sıralar; kaynak kaldıraç ağırlıkları korunur. |
| Puan alanları | `etre2/puan.py`: spot P1–P10 ve kaldıraç K1–K10. | HL-only kararı nedeniyle yalnız kaldıraç dalı başlangıç referansıdır. |
| Kadro geçişi | `etre2/kadro.py`: aday eşiği, kapasiteye göre ayarlanır; oda testi ve ardışık zarar ile geçişler vardır. | 11/11/28 takım büyüklükleri, 50 kapı başlangıcı, Pazar ritmi, 60/40 eşikleri, iki Pazar hareketsizlik kuralı ve İlk 11→Yedek 11→kadro dışı zinciri bu projeye ait açık uyarlamalardır; Etre'nin oda/aday kapasite ve zaman kuralı olarak sunulmaz. |
| HL PAPER terfi testi | `etre2/puan.py:oda_testi` ve `etre2/kadro.py:test`: son N canlı gölge işlemi, kırpık toplam, kazanma oranı ve en iyi hariç sonuç birlikte incelenir. | Son 6 **geçerli HL PAPER işlemi**, pozitif toplam, kazanma ≥%40 ve en iyi işlem hariç pozitif toplam kararı; İlk 11/Yedek 11 yapısına uyarlanmıştır. |

Puan kaynağındaki HL/kaldıraç on alanı: (1) gölge sonucu, (2) aylık ROI, (3) haftalık ROI, (4) hesap büyüklüğü, (5) aylık azami düşüş (düşük iyi), (6) kazanma oranı, (7) işlem sıklığı, (8) tutma süresi, (9) kaldıraç kullanımı, (10) pozitif gün tutarlılığı. `ilk_kadro` içindeki dört ham alan Etre v2 ön dönüşümlerini uygular: hesap USD→`sqrt(clamp((hesap−5000)/500000, 0, 1))`; sıklık/gün→`siklik_puani` (Etre `hft_gunluk` varsayılanı 150); tutma dakika→`tutma_puani`; ortalama kaldıraç x→`max(0, 1−abs(x−4)/20)`. `agirlikli_puan` eski adapter uyumu için önceden dönüştürülmüş K1-K10 değerlerini bekler; ham değerler için `hazirla_kaldirac_alanlari` kullanılır. Eksik alan 35 yüzdelik puan alır. Gölge sonucu kırpma [-1, 3] ve k=8 büzülmesi `golge_ozeti`ndedir. Aylık/haftalık ROI, düşüş, kazanma ve tutarlılık alanlarının veri penceresi/mevcut HL kaynağı eşlemesi hâlâ sağlayıcıya aittir; modül bunları kendiliğinden uydurmaz.

## İlk11 İşlem Politikası v1 — kaynak referansı

Bu bölüm, Etre HL/kaldıraç varsayılanlarının sayılarını kısa referans olarak kaydeder; **Faz 1'de işlem motoru veya mevcut al-sat politikası değiştirilmez.** Kaynak: `etre2/kurallar.py`, `etre2/kasa.py`, `settings.example.json` (`kaldirac` ve `boyut` bölümleri), commit `f3f5cff92d6db2fff62b6f7753c45343e00583ba`.

- Giriş fiyat bandı: üst +%1, alt −%2; azami kaldıraç 5x.
- Marj bazlı stop: −%50. Ana para eşiğinde (%100 marj getirisi) pozisyonun %50'si alınır. Zirve marj getirisi %40'ı gördükten sonra zirveden %45 düşüşte kapat.
- Süreli stoplar: 12 saatte −%25, 24 saatte −%15, 48 saatte −%5. Süreli kâr alma: 24 saatte +%10, 48 saatte +%5. Azami pozisyon süresi 168 saat; trader satışı aynalanır.
- Kasa işlem tutarı eğrisi: `5,2 $ × (min(kasa, 10.000 $) / 200 $)^0,86`; 10.000 $ kasada yaklaşık 151 $, üstünde sabit. Etre varsayılanı olarak aktarılmıştır, Faz 1 motor değişikliği değildir.

## Faz 1 yürütme sınırı

İlk seçimde uygunluk kapısı yalnız evreni belirler; puan, uygun tüm HL adayları üzerinde yüzdelik sıralanır, en iyi 50 alınır. Eşit puanlarda form puanı, geçmiş kapı puanı, geçerli gözlem süresi, sonra sabit `id` kullanılır. Pazar geçişi yalnız plan döndürür; izleme listesine yazmaz. Geçerli tek Pazar snapshotında form ≥60 üst gruba yükselmeye uygunluk, <40 bir alt gruba düşüş adayıdır; eksik/geçersiz form hareket üretmez. İki ardışık Pazar aktivitesizliğinde de her grup yalnız bir alt gruba düşer: İlk11→Yedek→PAF→kadro dışı. Terfi yalnız komşu gruplar arasındadır: PAF→Yedek (≥60), Yedek→İlk11 (≥60 ve son 6 geçerli PAPER işlemi toplamı >0, kazanma oranı ≥0,40, en iyi işlem çıkarılınca toplam >0). Kod PAPER planıdır; cüzdan/emir yoktur.

İlgili mevcut alanların sözleşmesi `docs/VERI_SOZLESMESI.md` içindedir. Bu belge yeni veri alanı veya motor davranışı tanımlamaz.

## Pazar snapshot veri biçimi (Faz 1)

`copytrade/ilk11_veri.py` seçim ve izleme kayıtlarını forma yalnız tanımı açık eşleşmelerle aktarır: hesap değeri, günlük işlem sıklığı, medyan tutma (saat alanı Etre'nin dakika birimine ×60 çevrilir), medyan kaldıraç ve varsa kapıdaki `max_drawdown`. `form_ham.tutma` doğrudan dakika kabul edilir. `yonlu_dolum_iyi_orani` tamamlanmış işlem kazanma oranıyla aynı kabul edilmez. Gölge sonucu ve ROI ölçümleri mevcut eğrilerden kendiliğinden türetilmez; kaynağı açıkça `form_ham` olarak verilmedikçe alanlar `null` kalır.

Snapshot; Türkiye saatiyle Pazar 13:00 anını, kaynak sürümlerini, normalize edilmiş adayları ve ilk 50'nin `ilk11`/`yedek11`/`paf` dağılımını taşır. Kanonik JSON gövdesinin SHA-256 özeti `snapshot_id` olur; `snapshot_json` içerik değişimini hash ile doğrular. Bu aşamada snapshot oluşturma saf bir fonksiyondur; dosyaya yazma, kalıcı kayıt veya yeniden deneme orkestrasyonu yapmaz.

**Pazar planlayıcısı teknik notu:** Pazar planlayıcısı yan etkisizdir; ilk koşuyu `Europe/Istanbul` saat diliminde Pazar 13:00’te açar, başarısızlıktan sonra son başarısızlık zamanına iki saat ekleyerek tekrar zamanlar. Her tekrar aynı `snapshot_id` ile doğrulanır; kimlik uyuşmazlığı reddedilir. Başarı sonrası yeni deneme planlanmaz. Henüz snapshot yoksa `snapshot_hazirla` eylemi üretir.
