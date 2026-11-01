# Faz 2 — 14 Oda Kararları

Bu belge Faz 2 boyunca her odanın görev ve yetki sınırlarını kaydeder. Kararlar kullanıcıyla konuşularak eklenir; açık olmayan davranışlar varsayılmaz.

## Organizasyon kararı

- Ofis **14 odalı** yapı olarak ele alınacaktır; Kontrol odası kaldırılmıştır.
- Bağımsız kontrol grubu operasyonu, pano/ofis odası, kadro veya kasa etkisi oluşturmaz.
- Varsa pasif karşılaştırma deneyinin ham verisi yalnız Arşivde tutulabilir; seçim, takım, risk veya işlem kararlarını etkilemez.
- **Bilgi İşlem (IT)** ve **Denetim** birbirinden bağımsız birimlerdir.
- **Bilgi İşlem (IT):** Veri/API/altyapı sürekliliği ve teknik sağlık kapsamındadır.
- **Denetim:** Strateji, trader seçimi, takım geçişi, PAPER işlem/karar kuralı uyumu ve bunların kanıtlarını denetler.
- IT kaynaklı arıza, Denetim tarafından bağımsız olarak raporlanabilir.
- Bu aşamada bu birimlerin ayrıntılı iş akışı veya ek yetkileri belirlenmemiştir.

## Karar kaydı şablonu

Her oda için aşağıdaki alanlar doldurulur:

- **Oda:**
- **Amaç:**
- **Girdi:**
- **Çıktı:**
- **Yetki:**
- **Yasak:**
- **Açık karar:**

## 1. Çay Ocağı

- **Oda:** Çay Ocağı
- **Amaç:** Ofis görünümünde dekoratif ve atmosfer oluşturan bir alan olmak.
- **Girdi:** İşlevsel veri girdisi yok.
- **Çıktı:** Yalnız görsel/dekoratif gösterim.
- **Yetki:** Karar, veri, uyarı veya işlem yetkisi yok.
- **Yasak:** Sistem kararlarını, verileri, uyarıları veya işlemleri etkilemek.
- **Açık karar:** Faz 4 görünümünde atmosfer gösteriminin biçimi.

## 2. Arşiv

- **Oda:** Arşiv
- **Amaç:** İşlem geçmişini ve işlemlerin karar bağlamını saklamak; istatistiklerin yeniden üretilebilmesini sağlamak.
- **Girdi:**
  1. Ham kaynak olayları/dolum verileri; kaynak kimliği ve zaman bilgisiyle.
  2. PAPER işlem defteri olayları.
  3. Her işlemle ilişkili karar bağlamı.
- **Çıktı:** Değişmez geçmiş kayıtları ve bu kayıtlardan yeniden üretilebilir istatistikler.
- **Yetki:** Kayıtları eklemek ve geçmişten ölçüm üretmek.
- **Yasak:** Kayıt silmek veya mevcut kaydı değiştirmek. Düzeltmeler yeni bir kayıt olarak eklenir. Faz 3'te gerçek işlem modu açılırsa gerçek ve PAPER kayıtları aynı şemada zorunlu olarak ayrı modlarla tutulur.
- **Açık karar:** Yok.

### Arşiv kayıt katmanları

1. **Ham kaynak olayları/fill verisi:** Kaynağın olay kimliği ve olay zamanı korunur; kayıt değişmez.
2. **PAPER işlem defteri:** Giriş, ekleme, azaltma ve çıkış; fiyat, miktar, ücret/funding, PnL, çıkış nedeni ve zaman tutulur.
3. **Karar bağlamı:** `snapshot_id`, takım, kural/politika sürümü ve uygulama ya da ret gerekçesi tutulur.

## 3. Haberleşme

- **Oda:** Haberleşme
- **Amaç:** Sistemden insana bildirim ve insan iletişimi sağlamak.
- **Girdi:** Olay kimliği, zaman, önem derecesi ve varsa `snapshot_id`/işlem bağlantısı taşıyan sistem bildirimleri.
- **Çıktı:** Telegram ve telefon üzerinden kritik bildirimler.
- **Yetki:** Kritik olayları insana iletmek. Bildirim türleri: veri hattı kesintisi veya gecikme, PAPER risk limiti, Pazar kadro sonucu, hata ve Faz 3'te gerçek işlem/risk uyarısı.
- **Yasak:** Otomatik işlem veya kadro değişimi başlatmak. Rutin durumlar bildirim göndermez; yinelenen hata bildirimleri bastırılır.
- **Açık karar:** Yok.

## 4. Sekreterlik

- **Oda:** Sekreterlik
- **Amaç:** Sistemin tek resmî karar kaydını tutmak.
- **Girdi:** Pazar kadro sonuçları; terfi/düşüş, istisna, politika ve manuel onay kararları.
- **Çıktı:** Zamanı, karar vereni, gerekçeyi, etkilenen trader/kadroyu ve ilgili `snapshot_id`/kural sürümünü içeren resmî kayıt.
- **Yetki:** Kararı kaydetmek ve kayıt bütünlüğünü korumak; kendi başına karar vermez.
- **Yasak:** Kayıtları değiştirmek veya silmek; düzeltmeler yeni kayıt olarak eklenir. Onaysız taslak uygulanmış karar olarak gösterilmez. Faz 3 işlemleri için talep ve açık onay ayrı aşamalar olarak kaydedilir.
- **Açık karar:** Yok.

## 5. Bilgi İşlem (IT)

- **Oda:** Bilgi İşlem (IT)
- **Amaç:** Veri ve teknik altyapı hatlarının sürekliliğini sağlamak.
- **Girdi:** Hyperliquid veri erişimi/API, Worker, arşiv yazımı, zaman senkronu ve pano yayını hatlarının çalışma bilgileri.
- **Çıktı:** Her hat için son başarı zamanı, gecikme, hata oranı ve güncel durum. Bayat veri yeniymiş gibi yayımlanmaz. Sorunlarda Haberleşme bildirimleri üretilir.
- **Yetki:** Kontrollü yeniden deneme ve yeniden başlatma yapmak. Faz 3'te teknik anahtar, izin ve imzalama güvenliğini işletmek.
- **Yasak:** Trader seçimi, kadro, risk veya işlem kararı vermek. Gerçek emir onayı IT yetkisinde değildir; Makam ve Sekreterlik kayıt zincirinden geçer.
- **Açık karar:** Yok.

## 6. Denetim

- **Oda:** Denetim
- **Amaç:** Trader seçimi, Pazar snapshotı, takım geçişi, PAPER işlemi ve istisnaların kurala uygunluğunu ve kanıt zincirini denetlemek.
- **Girdi:** İlgili kural ve veri sürümleri, onay kayıtları, olay/işlem kayıtları ve sonuçlar.
- **Çıktı:** Bilgi, uyarı veya kritik önem seviyesinde; bulgu, dayanak kayıt ve etkiyi belirten denetim sonucu. Kritik bulgular Haberleşme üzerinden iletilir.
- **Yetki:** Eksik olay kaydı, tutarsız PnL, yanlış trader/takım ataması ve kural dışı geçiş gibi bulguları raporlamak. IT teknik olaylarını etki ve kayıt bütünlüğü yönünden bağımsız incelemek; teknik çözüm IT'nin sorumluluğundadır. Gerekirse durdurma önermek.
- **Yasak:** Tek başına trader düşürmek, kural değiştirmek veya pozisyon açıp kapatmak.
- **Açık karar:** Yok.

## 7. Finans

- **Oda:** Finans
- **Amaç:** PAPER kasasının ve takım sonuçlarının finansal kayıtları için tek kaynak olmak.
- **Girdi:** PAPER defteri ve kasa olayları.
- **Çıktı:** PAPER başlangıç sermayesi, kullanılabilir nakit, açık teminat, brüt/net maruziyet, gerçekleşmiş/gerçekleşmemiş PnL, ücret ve funding. Her rakam defter kaydı ve zaman iziyle ilişkilendirilir. Takım sonuçları ayrı tutulur; ana PAPER kasa yalnız İlk 11'i kapsar.
- **Yetki:** Finansal toplamları kaydetmek, hesaplamak ve mutabakat için sunmak. Faz 3'te gerçek cüzdan ve pozisyon kayıtlarını mutabakat amacıyla izlemek.
- **Yasak:** Risk limitlerini değiştirmek; Faz 3'te anahtar veya emir yetkisi taşımak. Negatif bakiye, tutarsız teminat veya limit aşımı Risk ve Denetim için olay oluşturur.
- **Açık karar:** Yok.

## 8. LAB

- **Oda:** LAB
- **Amaç:** Hyperliquid trader/cüzdan keşfi ve gölge izleme hattını arka planda yürütmek.
- **Girdi:** HL aday/cüzdan verisi ve gölge izleme sonuçları.
- **Çıktı:** Kapıdan geçen adayları Pazar günü 50 kişilik seçim evrenine vermek; gölge verisiyle PAF ve Yedekler'in gelişim/form puanını beslemek.
- **Yetki:** Keşif, gölge izleme ve bu çıktıları ilgili seçim/form verisine aktarmak.
- **Yasak:** İlk 11 işlem, kasa veya risk kararı vermek. LAB pano/ofiste görünmez; kayıtları yalnız Denetim veya Makam gerektiğinde inceler.
- **Açık karar:** Yok.

## 9. Kapı

- **Oda:** Kapı
- **Amaç:** LAB'ın bulduğu adaylar için otomatik Hyperliquid uygunluk filtresi uygulamak.
- **Girdi:** LAB adayları ve güvenlik, veri yeterliliği, temel risk ölçütleri.
- **Çıktı:** Kapıyı geçen adaylar puanlama evrenine aktarılır; İlk 50 seçimi puan motoru yapar.
- **Yetki:** Tanımlı ve sürümlenmiş uygunluk filtrelerini çalıştırmak. Sonuç ve etkilenen Pazar snapshotı Arşiv ve Denetim için kanıtlanır.
- **Yasak:** İlk 11, Yedekler veya PAF takımına doğrudan seçim yapmak. Kapı pano/ofiste görünmez.
- **Açık karar:** Yok.

## 10. PAF Takım

- **Oda:** PAF Takım
- **Amaç:** 28 trader'a kadar gelişim adaylarını izlemek.
- **Girdi:** Onaylı haftalık kadro snapshotı, gölge işlem sonuçları, form/istikrar ve veri kalitesi ölçümleri.
- **Çıktı:** PAF'a özel gelişim ve performans kaydı; sonuçları İlk 11 performansına katılmaz.
- **Yetki:** Gölge performansı ölçmek. Geçerli Pazar formu ≥60 olduğunda ve Yedekler'de yer varsa Yedekler'e terfi adayı olmak.
- **Yasak:** Gerçek veya ana PAPER kasa işlemi yapmak; PAF'a manuel trader atamak. Pazar formu <40 veya iki ardışık Pazar hareketsizliği kadro dışı bırakılma nedenidir. PAF'a giriş yalnız o haftanın onaylı 50 kişilik snapshotı üzerinden olur.
- **Açık karar:** Yok.

## 11. Yedekler

- **Oda:** Yedekler
- **Amaç:** 11 kişilik canlı fiyatlı gölge takımı olarak İlk 11'e adayları izlemek.
- **Girdi:** Onaylı haftalık kadro snapshotı, geçerli Pazar formu ve son altı geçerli PAPER işlem sonucu.
- **Çıktı:** Yedek takım performans kaydı; sonucu İlk 11 kasasına karışmaz.
- **Yetki:** İlk 11'de boşluk varsa, form ≥60 ve son altı geçerli PAPER işlem toplamı >0, kazanma oranı ≥%40, en iyi işlem çıkarılınca kalan toplam >0 ise İlk 11'e terfi etmek. PAF'tan yalnız Pazar snapshotıyla ve boş Yedek yeri varsa üye alınır.
- **Yasak:** Ana PAPER kasaya dahil olmak. Form <40 veya iki ardışık Pazar hareketsizliği PAF'a düşüş nedenidir.
- **Açık karar:** Yok.

## 12. İlk 11

- **Oda:** İlk 11
- **Amaç:** 11 kişilik ana PAPER takımını ve ana PAPER kasasını işletmek; ana kasa yalnız İlk 11 üyelerini kapsar.
- **Girdi:** Onaylı Pazar kadro snapshotı, Hyperliquid perpetual (perp) canlı fiyatı ve takım üyelerinin işlem olayları.
- **Çıktı:** Canlı fiyatla PAPER aynalama işlemleri; finansal sonuçlar Finans'a, karar/işlem izleri Arşiv'e aktarılır.
- **Yetki:** Yalnız İlk 11 takımında işlem simülasyonu yapmak. Terfi/düşüşler Pazar snapshotı kurallarına göre uygulanır. İşlem politikası Etre HL referansını izler: giriş sinyalinin tazeliği ve fiyat bandı, en çok 5x kaldıraç, ekleme/azaltma aynalama, stop, ana para koruma, kâr geri çekilmesi ve zaman tabanlı çıkışlar. Giriş retleri ve çıkış nedenleri arşivlenir.
- **Yasak:** Faz 3'e geçilene kadar cüzdan bağlamak veya gerçek emir göndermek.
- **Açık karar:** Yok.

## 13. Risk

- **Oda:** Risk
- **Amaç:** İlk 11 PAPER işlemlerinin risk ve çıkış kurallarını yönetmek.
- **Girdi:** Fiyat/sinyal tazeliği ve bandı, kaldıraç, açık pozisyonlar, Finans mutabakatı ve IT hat sağlığı.
- **Çıktı:** Etre HL referansındaki giriş tazeliği/fiyat bandı, en çok 5x kaldıraç, stop, ana para koruma, kâr geri çekilmesi ve süre tabanlı çıkışların kararları; engel ve çıkış neden kodları Arşiv ve Denetim incelemesine gider.
- **Yetki:** Veri bayatlığı, limit aşımı, Finans mutabakat bozukluğu veya kritik IT olayı halinde yeni girişleri engellemek. Açık işlem yalnız önceden onaylı otomatik çıkış kurallarına göre kapanır.
- **Yasak:** Keyfi/manuel pozisyon kapatma veya onaysız kural değişikliği. Kural değişikliği Makam ve Sekreterlik onayıyla, yeni sürüm olarak yapılır.
- **Açık karar:** Faz 3 acil durdurmanın kapsamı ayrı kararla belirlenecektir.

## 14. Makam

- **Oda:** Makam
- **Amaç:** Nihai politika ve istisna kararlarını vermek.
- **Girdi:** Denetim bulguları, takım yapısı, risk/Kapı/puanlama sürümü ve faz geçişi önerileri.
- **Çıktı:** Gerekçeli nihai politika veya istisna kararı; tüm kararlar Sekreterlik tarafından kaydedilir ve Denetimce incelenir.
- **Yetki:** Takım yapısı, risk politikası, Kapı, puanlama sürümü ve Faz geçişlerinde nihai onay. Kritik bulgu sonucunu karara bağlamak. Acil durumda yeni girişleri geçici olarak durdurmak. Faz 3 gerçek işlem, cüzdan bağlantısı ve günlük bütçe için açık Makam onayı vermek.
- **Yasak:** Günlük işlem veya trader seçimi yapmak. Değişiklik geçmiş snapshot veya işlemleri geriye dönük değiştiremez; ileri tarihli yeni sürüm olarak yürürlüğe girer. Acil durdurma kalıcı politika değişikliği değildir; kalıcı değişiklik Sekreterlik kaydı ve yeni sürüm gerektirir.
- **Açık karar:** Faz 3'e geçiş ve gerçek işlem/cüzdan/bütçe onayları zamanı geldiğinde ayrı ayrı karara bağlanacaktır.

## Onaylı 14 oda listesi

1. Çay Ocağı
2. Arşiv
3. Haberleşme
4. Sekreterlik
5. Bilgi İşlem (IT)
6. Denetim
7. Finans
8. LAB
9. Kapı
10. PAF Takım
11. Yedekler
12. İlk 11
13. Risk
14. Makam
