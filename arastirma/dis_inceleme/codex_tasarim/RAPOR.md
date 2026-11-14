# CT-Proje: seçim ve ölçüm tasarımı incelemesi

## Teknik olmayan okuyucu için altı sonuç
1. **Sharpe benzeri seçim kısmen sınandı:** aynı 12 haftalık veriyle t-sırası ve haftalık Sharpe sırası aynıdır. Fakat Sharpe’ın tek başına katkısı veya makaledeki yöntemin aynısı sınanmadı.
2. Ana başarısızlık hükmü, ilk beşin sıralamasından çok **bütün seçim kapılarının birlikte** sonucudur; t-sıralamasını tek başına mahkûm etmez.
3. Darwinex benzeri risk hedefleme uygulanmadı. Bazı risk kapıları var; bunlar her trader’ın kopyasını aynı risk düzeyine getirmiyor.
4. Yuvarlama, nakitte kalan kontroller ve boş başlangıç, bazı trader türlerini diğerlerinden farklı etkileyebilir. Etkinin büyüklüğü bu incelemede ölçülmedi.
5. Tarihler örtüşüyor; geçmiş veriler görülerek tasarlanan revizyon tamamen bağımsız sınav sayılamaz. Yeni yöntem önerileri de sonuç sonrası öneridir.
6. **Kod/test çalıştırılmadı, sonuç yeniden üretilmedi.** Aşağıdaki eşikler gelecekteki ayrı araştırma için öneridir; dondurulmuş kurallar veya canlı sistem değiştirilmedi.

**Kapsam:** 14.11.2026; incelenen `main`: `098ea0767ae7ed4f9e9829398fea3e26bbdfa204`. İstenen belgeler yanında çağrılan hesaplama/boyutlandırma kodu, rapor üreticisi ve `dis_inceleme/risk_secim/RAPOR.md` okundu. Ham koşu önbelleği bu checkout’ta yok; veri üzerindeki hata sıklığı doğrulanamadı.

## 1. T-istatistiği, Sharpe ve makaledeki seçim

`copytrade/secim_d.py:120–152` her T için **[T−84 gün,T]** içindeki 12 haftayı kullanıyor:

`r_w = (perp_PnL(b) − perp_PnL(a)) / toplam_hesap_değeri(a)`

` t = ortalama(r_w) / (örneklem_standart_sapması(r_w)/√n) `

- Gözlem **işlem veya gün değil, haftadır**; PnL kümülatif perp serisinden, payda toplam hesap değerinin hafta başındaki/öncesindeki son noktasından gelir. Eksik haftalar atlanır; A/B/D kural 2’si 12 ölçülebilir hafta ister.
- Risksiz getiri çıkarılmıyor. Aynı 12 hafta ve sıfır risksiz getiriyle `t = √12 × haftalık_Sharpe`; yıllıklaştırma da ortak sabittir, sıralamayı değiştirmez. Eksik hafta sayıları farklıysa eşdeğerlik koşulsuz değildir. Seri bağımlılığında bu formülün varlığı t-dağılımıyla geçerli anlamlılık testi yapıldığı anlamına gelmez.
- Sıralama **trader’ın kendi PnL/hesap serisine** dayanır; bizim ücret, kayma ve funding giderlerimiz bu puana ayrıca uygulanmaz. Trader’ın API PnL’sinde hangi kalemlerin zaten bulunduğu burada ayrıştırılmıyor. Dolayısıyla önceki “funding yok” ifadesi, API sözleşmesi incelenmeden “trader funding’i kesin hariç” diye okunmamalı.
- Hafta içi para hareketleri için alt dönemli zaman-ağırlıklı getiri hesabı yapılmıyor. PnL farkını doğrudan para yatırma saymak da doğru değildir; sorun, değişen sermayenin hafta başı paydayla ölçülmesidir.

Buna karşılık kapılar **28/56 günlük**, ileri başarı **[T,T+28 gün)** maliyetli kopya getirisiyle ölçülür (`olcum.py:119–143,243–253`). İşlem sayısı kapıdır; performans sıralamasının örneklem birimi değildir.

`rapor.py:74–126` önce geçenlerin **tamamının** ortancasını karşılaştırır; t’ye göre ilk beşi ayrıca gösterir. Üç geçme şartı tüm geçenlere uygulanır. A/B/D’de ilk-beş üzerinden Sharpe-eşdeğer sıra incelenmiştir; “yalnız Sharpe seçimi” ile aynı havuzun sıralamasız hali arasında kontrollü fark ölçülmemiştir. C hem kural 2’yi hem sıralamayı kaldırır, ayrıca örneklem kapsamı farklıdır: tek başına sıralamanın etkisini ayırmaz.

**Dorfleitner vd. (2018) açısından sınır:** Yerel literatür raporları açıkça **özetten** yararlanıyor; makalenin seçim penceresi, günlük/işlem bazlı seri, risksiz faiz ve seçim puanındaki maliyet tanımı verilmemiş. Birincil metne erişim denemesi ağ geçidinde 403 aldı. Bu ayrıntıları uydurup “aynı testi yaptık” diyemeyiz. Bildirilen bulgu, yüksek getiri seçimine karşı Sharpe iyileşmesidir; bizim rastgele kontrol karşılaştırmamız farklıdır. Özetlerde maliyet sonrası pozitif anormal getiri bulunmaması da aktarılıyor.

**Hüküm:** “Ham haftalık Sharpe-eşdeğer sıralamayı kapılarla birlikte kısmen sınadık; saf Sharpe yöntemini, günlük net kopya Sharpe’ını veya makalenin birebir uygulamasını sınamadık.”

## 2. Darwinex fikirleri: ne var, nasıl ayrıca araştırılır?

**Mevcut:** pozitif hafta sayısı, kaldıraç/devir/likidite, 90 günlük PnL düşüşü ve kopyalanabilirlik kapıları var. Ancak 90 günlük ölçü, kümülatif dolar PnL düşüşünün **T’deki** hesaba bölünmesidir; gerçek özsermaye eğrisinin zirveden yüzdesel düşüşü değildir (`secim_d.py:136–145`). Sabit slot ve 1,5× nominal tavan, volatilite/VaR eşitlemesi değildir. Risk istikrarının, risk hedeflemenin veya bu düşüş kapısının **tek başına** etkisi ayrıştırılmadı. Darwinex’in tescilli VaR/D-Score yönteminin aynısı mevcut veriyle üretildiği ileri sürülemez.

**Yeni veri toplamadan araştırma önerisi:** mevcut artifact’taki dolum, saatlik mum, funding ve hesap serilerini kullan; dolumu olmayan tam evreni var sayma. T1–T11’deki ortak kapsamlı örneklemle sınırlı kal; T12’yi ve Revizyon 1’i açma/değiştirme. Yeni seçim eski sonuçlar görüldükten sonra önerildiğinden bu çalışma **keşifseldir**, bağımsız kârlılık kanıtı değildir.

Aynı temel havuzda, aynı kapasite ve maliyetle dört önceden kayıtlı kol:

| Kol | Önceden sabitlenecek tanım |
|---|---|
| Baz | Aynı kapılar, eşit slot; risk değişikliği yok. |
| Normalizasyon | Son 56 tam UTC gününün ücret/kayma öncesi, funding dahil MTM kopya getirilerinden günlük σ; ileri 28 gün için çarpan `min(1, %1/σ)` sabit. Sıfır/ölçülemeyen σ veya eksik fiyat: veri yetersiz. Yalnız risk azaltılır. |
| İstikrar | Normalizasyona ek: aynı 56 günde ilk/son 28 günlük σ için büyük/küçük ≤2. Sıfır/bilinmeyen payda geçmez. |
| Düşüş | Normalizasyona ek: son 56 günlük MTM kopya özsermayesinde zirveden düşüş ≤%10. |

**Önerilen kabul eşikleri:** En az 20 farklı adres ve 11 tarihin en az sekizinde seçilen bulunmalı; yoksa “başarısız” değil **veri yetersiz**. Ekonomik adaylık için birlikte: maliyet sonrası birleşik yüzdelik ≥%90; 11 tarihin ≥8’inde kontrolden yüksek ortanca; tüm seçilen gözlemlerin net ortancası >0. Risk faydası ayrıca: bazla eşlenmiş 28 günlük düşüşlerin ortancası en az %20 azalmalı ve net ortalama getiri farkı ≥−0,5 yüzde puan olmalı. Bunlar literatürden kanıtlanmış eşikler değil, sonuç görülmeden yeni deney için kilitlenecek **tasarım tercihleridir**.

Çarpan emir **öncesi** uygulanıp minimum emir, tavan, ücret ve funding yeniden hesaplanmalı; bitmiş getiriyi çarpmak yeterli değildir. Nakit/risk düzeyi eşlenmiş rastgele kontrol de gösterilmeli: salt daha az risk almak, daha iyi trader seçmek değildir. Futbol raporundaki 7 adres/17 gözlem yeterlilik eşiğini sağlamaz. Dört kolun tamamı raporlanmalı; en iyiyi seçip tek deneymiş gibi sunmamalı. Adres ve dört haftalık zaman bloklarıyla belirsizlik gösterilmeli; yaklaşık 3,5 bağımsız dönem güçlü çıkarıma yetmez.

## 3. Yöntemi haksız gösterebilecek ölçüm tercihleri

**Doğrulanmış kod davranışı; sonuç etkisi ayrıca ölçülmeli:**

- **Somut düşüş ölçekleme hatası:** `rapor.py:75–77`, 1000 USD kasa getirisini ve düşüşünü aynı `OLCEK=5` ile çarpıyor. Getiri dönüşümü doğrudur; yüzdesel zirve düşüşünde payda değişir. Elle örnek: tek slotun net K/Z'si 0→40→0 USD ise kasa düşüşü 40/1040; beşle çarpılınca %19,23 çıkar. Gerçek 200 USD slot düşüşü 40/240=%16,67'dir. Doğru slot eğrisi yeniden kurulmalıdır (`kopya_v3.py:78–99`). Özellikle kâr tepesi yapan yöntemin riski abartılabilir; ana getiri temelli geçme şartı bundan doğrudan etkilenmez.
- **Nakit kontrol:** Hiç dolum yoksa veya yürütülebilir işlem üretilemiyorsa getiri sıfır (`olcum.py:123–140`). Futbol raporunda kontrolün yaklaşık %40’ı pozisyon açmıyor. İşlem yapan seçicinin ücretli getirisi nakitle karşılaşır; bu ekonomik olarak meşrudur, fakat aynı faaliyet düzeyindeki trader’lar arasındaki avantajla karıştırılamaz. Gelecekteki sıfır getirileri silmek yerine T öncesi aktiviteyle ikinci kontrol kurulmalı.
- **Geleceğe bağlı dışlama:** En yeni 10.000 dolumu tutma ve kapsam kontrolü (`calistir.py:251–276`; `olcum.py:190–199`) sonraki yoğun işlemlerin eski T’yi dışlamasına yol açabilir. İki gruba aynı uygulanması yanlılığı otomatik kaldırmaz. Farkın yönü bilinmiyor.
- **Maliyet/yuvarlama:** %0,045 taker + %0,05 kayma sabit nosyonel oranları; çok devirli yöntemleri daha fazla etkiler ama bu tek başına hata değildir. 5,5–11 USD açılışlar yukarı yuvarlanırken küçük artırmalar atlanır: küçük pozisyonlu/düşük riskli trader’larda risk ve sadakat bozulabilir. Slot ve maliyet duyarlılığı ayrı gösterilmeli. Gecikmesiz trader fiyatı ise genellikle iyimserdir; kötü sonucu tek başına açıklamaz.
- **Eksik veri:** Eksik funding dosyası boş listeye çevriliyor (`olcum.py:75–80`); “sıfır funding” ile “veri yok” ayrılmıyor. `fiyatsiz` sayılıyor ama tek başına dışlama şartı değil. Bu eksikliklerin hangi grupta olduğu ham kayıtla incelenmeli; yönü peşinen söylenemez.
- **Pencere ve kıyas:** Her 28 günlük kopya boş başlar; uzun süre taşınan pozisyonları sürekli kopyadan farklı ölçer. Haftalık başlayan pencereler örtüşür. Üye ortancası, eşit ağırlıklı yatırım portföyünün getirisi değildir; futbol çalışması ortalamayla başka soruyu yanıtlar. Bağımsız slot sonuçları ortak coin/marj kısıtlarını tam portföy olarak sınamaz.
- **“Tam örneklem dışı” iddiası fazla güçlü:** 11 Kasım evreniyle Ekim T12–T15’te seçim, o tarihte bilinmeyen evren üyeliğini kullanır. T12 daha önce okunmamış olsa bile komşu sonuçlarla örtüşme ve 14 Kasım’da revizyon dondurma ayrılmalı. “Evren dondu, hayatta kalma yanlılığı yok” hükmü bütün bu tarihler için geçerli değildir.

**Sonuç:** Mevcut olumsuz bulgular silinmez; fakat bunlardan “Sharpe veya risk normalizasyonu genel olarak işlemez” çıkarılamaz. Tek çıktı bu rapordur; önerilen deneylerin hiçbiri yapılmadı.

**Dış kaynak sınırı:** Dorfleitner vd., *QREF* 70 (2018), 160–171, DOI: `10.1016/j.qref.2018.04.009`; Darwinex özellikleri: `https://help.darwinex.com/what-are-investable-attributes`. Burada bağımsız tam-metin doğrulaması değil, yukarıda belirtilen yerel kaynak raporlarının sınırlı aktarımı kullanılmıştır.
