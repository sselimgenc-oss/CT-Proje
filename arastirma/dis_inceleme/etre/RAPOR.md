# Dış inceleme: ismailkaraabc/etre-trading-office (salt okuma)

**Kısa özet (teknik olmayan okuyucu için)**
1. ETRE, bizimkine benzer bir kopya botu. İki bölümü var: Solana'da meme token alım kopyası (spot) ve Hyperliquid'de kaldıraçlı işlem kopyası. Yalnız **kâğıt üstünde (simülasyon)** çalışıyor; gerçek para hiç kullanılmamış.
2. Trader seçerken puan yalnız aday listesine girişi belirliyor. Para ayırma kararını **seçimden sonraki canlı "gölge" denemesi** veriyor: trader izlemeye alındıktan sonra yaptığı son 6 işlem kâğıt üstünde kopyalanıyor ve bu deneme tutarlı biçimde kârlıysa trader kopyalanmaya başlıyor.
3. Trader, gölge sonucu bozulunca, uzun süre işlem yapmayınca ya da art arda iki büyük zararda çıkarılıyor. Yerine, gölge testini en iyi geçen aday giriyor. Testi geçen yoksa koltuk boş kalıyor.
4. Yazarın kendi ölçümleri bizimkiyle aynı yönde: **hiçbir kopya kuralının kâr ettiği kanıtlanamamış.** İzlenen trader'ların izlemeye alınmadan önceki pozisyonları +%0,34 getiri gösterirken, sonrakiler −%0,02 gösteriyor; yazar bu farkı hayatta kalma yanlılığına bağlıyor. Canlı seçim kuralının kendi sonucu da belirsiz: trader başına eşit ağırlıkla −%0,62.
5. Bizim bulgumuzla birlikte okununca bu, "geçmişte parlak trader'ı seçmek işe yaramıyor" sonucunu ikinci bir bağımsız yerden destekliyor.
6. Test edilmeye değer üç fikir (aday azlığı yüzünden ölçme gücü düşük):
   - para koymadan önce seçilen trader'ın **ileriye dönük gölge denemesi**;
   - çok trader'ın aynı coinde aynı yöne girmesine dayanan **uzlaşı sinyali**;
   - "en iyi işlem çıkarılınca da kârlı mı" türünden **kırılganlık kapıları**.
7. Muhtemelen işe yaramayacaklar: getiri ve ROI ağırlıklı sıralama puanı; aday azken eşiği kendiliğinden düşürmek; az veriyle ağırlıkları "öğrenmek".
8. Depo GPL‑3.0 lisanslı. Kod kopyalanmadı ve çalıştırılmadı; yalnız mantık kendi cümlelerimizle özetlendi.

---

İnceleme 14.11.2026'da, varsayılan dalın son commit'i (`532968b`, 14.11 09:39 +03) üzerinde yapıldı. Kaynaklar `etre2/` altındadır. Satır numaraları yaklaşıktır.

## 1. Genel yapı
- **İki masa.** Spot masası Solana meme token'larında çalışıyor: izlenen cüzdanların alımını kopyalıyor, takası Jupiter üzerinden yapıyor. Kaldıraç masası Hyperliquid perp'lerinde çalışıyor, kaldıraç 2–5x. Masaların kasası, defteri ve modu (`sim` / `gercek`) ayrı (`kasa.py`, `ayar.py`).
- **Kaldıraç masasında üç yol var** (`kaldirac/masa.py`):
  - birebir trader kopyası;
  - "seçimli kopya": yalnız seçilmiş trader'lar ve en hacimli 60 coin; BTC, ETH, SOL, HYPE, BNB ve XRP hariç;
  - "uzlaşı" (`kaldirac/uzlasi.py`): son 6 saatte ≥ N farklı izlenen trader aynı coinde aynı yöne girerse kendi sinyalini üretiyor.
  - Bunların dışında kendi trend kuralı da var (`kaldirac/trend.py`); varsayılanı kapalı.
- **Veri kaynakları.** Hyperliquid tarafında herkese açık lider tablosu ve info API'si. Spot tarafında FOMO / Kolscan lider listeleri, zincir akışı (Helius RPC), GeckoTerminal ve Jupiter.
- **"Lab" (gölge) katmanı.** Her sinyal ve kural paralel olarak kâğıt üstünde ölçülüyor. Seçim kararı bu katmana dayanıyor.
- **Mod.** Örnek ayar dosyasında iki masa da `sim` modunda. Günlüğe göre gerçek yürütme yolu zincirde hiç çalıştırılmamış (`docs/GELISIM_GUNLUGU.md` ≈ 1774–1800). Simülasyon kasaları 14.11'de 200 $ / 2 SOL ile sıfırlanmış.

## 2. Trader seçimi (kaldıraç tarafı ağırlıklı)
- **Aday filtresi** (`hl/lider.py` ≈ 49–56):
  - hesap ≥ 5.000 $;
  - aylık ve tüm zamanlar pnl > 0, haftalık pnl ≥ 0;
  - devir (hacim / hesap) ≤ 400, piyasa yapıcı ve yüksek frekanslı hesapları dışarıda tutmak için.
- **Ön sıralama puanı.** Ağırlıklı bir ROI karışımı:
  - aylık ROI %35, tüm zamanlar ROI %30, haftalık ROI %20;
  - kârlı pencere sayısı %15, artı küçük bir log(pnl) terimi;
  - genç hesaplarda tüm zamanlar ROI terimi sıfırlanıyor ve puan yarıya iniyor.
- **10 parametreli puan** (`puan.py`, `kadro.py`). Her ölçü havuz içinde yüzdeliğe çevriliyor; sonra ağırlıklı ortalama alınıyor.
  - Kaldıraç tarafının ölçüleri: gölge sonucu, aylık / haftalık ROI, hesap büyüklüğü, aylık en büyük düşüş, kazanma oranı, işlem sıklığı, tutma süresi, kaldıraç ve tutarlılık.
  - En yüksek önsel ağırlıklar: düşüş 2,0 ve tutarlılık 1,8.
  - Ortalama kaldıraç için ideal 4x kabul ediliyor; uzaklaştıkça puan düşüyor.
- **Eleme.**
  - Günde ≥ 150 işlem yapan, medyan tutma süresi < 2 dk olan ya da hesabı < 5.000 $ olan elenir.
  - Aday eşiği 60 puanla başlıyor. Aday sayısı hedefe yaklaşsın diye her turda en çok ±2 puan kayıyor; aralık 50–80.
- **Asıl karar: gölge "oda testi"** (`puan.py` `oda_testi`). Trader lab'a girdikten sonra **son 6 canlı gölge işlemine** bakılıyor:
  - kazançlar +%100'de kırpılınca toplam > 0;
  - kazanma oranı ≥ %40;
  - **en iyi işlem çıkarılınca da** toplam > 0;
  - geçmiş veriden yeniden oynatılan işlemler bu teste girmiyor.
- **Kaç trader, hangi ağırlıkla.**
  - Odada en çok 20 trader var.
  - Oda 10'un altına düşerse "deneme koltuğu" açılıyor. Deneme için 2–3 gölge işlem yetiyor; deneme trader'ı yarım boyutla kopyalanıyor.
  - Bunun dışında trader'lar arasında ağırlık farkı yok.
- **Uzun dönem kohortu** (`uzun.py`). Kaldıraç için ölçüt: 12 haftanın ≥ 6'sı ölçülmüş olacak, haftaların ≥ %70'i pozitif olacak, en kötü hafta ≥ −%20 olacak. Bu yalnız bir etiket; tek başına para açmıyor.
- **Seçimli kopya** (`kaldirac/secim.py`). Son 14 günde ≥ 5 kapanmış tur, medyan tutma ≥ 15 dk ve ücret + funding sonrası kırpık ortalama tur getirisi > %0,5 isteniyor.

## 3. Değiştirme ve çıkarma
- **Çıkış koşulları** (`kadro.py` `_oda`):
  1. Belirli süre işlem yok: kaldıraçta 72 sa, spotta 24 sa.
  2. Son 6 gölge işlemin kırpık toplamı ≤ 0.
  3. Oda doluyken kırpık gölge toplamı (+%100 kırpmalı) en zayıf üyeden ≥ 0,10 daha iyi bir aday geliyor.
  4. Ana defterde art arda 2 işlem, her biri %3'ten fazla zararla kapanıyor.
- **Yerine kim geliyor.**
  - Her 15 dakikalık turda, testi geçenler arasında gölge toplamı en yüksek olan giriyor.
  - Ayrı bir yedek kuyruğu yok; aday havuzu fiilen yedek işlevi görüyor.
  - Testi geçen yoksa koltuk boş kalıyor. Bizde de K‑65 sonrası aynı kural var.
- **Bekleme.**
  - Sonuç yüzünden çıkan trader'ın test penceresi sıfırlanıyor; geri dönmek için 6 *yeni* gölge işlem gerekiyor. İşlemsizlik, "daha iyisi geldi" ya da tavan nedenli çıkışlarda pencere korunuyor (`koltuk_pencere_koru`); trader yeniden test geçmeden dönebiliyor.
  - Kapasite yüzünden çıkarılan trader için 3 günlük bir geri alınmama süresi okundu (`trader.py`), ancak denetimde doğrulanamadı; belirsiz.
  - Aşırı uç freni: 10 dakikada ≥ 8 açılış yapan, ya da açık işlemlerin %40'ından fazlasını tek başına tutan trader'a 30 dakika ara veriliyor.
- **Değişiklik sıklığı sınırı.** Açık bir günlük üst sınır bulunamadı. Gir‑çık döngüsünü giriş ile çıkış koşulları arasındaki asimetri (histerezis) frenliyor: girmek için üç şart, çıkmak için tek şart var.
- **Çıkanın açık pozisyonu.** Kendi kurallarıyla (stop, kâr, süre) kapanana dek yönetiliyor. Ayna satış çalışabilsin diye, açık pozisyonu olan trader izlemeden çıkarılmıyor.

## 4. Boyutlandırma ve risk
- **Boyut.**
  - Kaldıraçta teminat = oran × kasa. Seçimli kopyada oran = %50 / 10 pozisyon × risk çarpanı.
  - Hyperliquid'in en küçük emri 11 $; ana masada teminat bu sınıra yükseltiliyor.
  - Spotta işlem başına tavan 500 $, havuz likiditesinin en çok %1'i ve kasanın %25'i.
- **Kanıta bağlı boyut çarpanı** (`risk.py`, 14.11). Kapanmış kopya işlemlerinin sayısına ve güven aralığına göre boy değişiyor:
  - n < 30: ×0,5;
  - zayıf (%95 GA üst sınırı < 0): ×0,25;
  - aday (n ≥ 30, ortalama > 0, en iyi 3 hariç > 0): ×0,75;
  - kanıtlı (n ≥ 60, %95 GA alt sınırı > 0, en iyi 3 hariç > 0, tek işlemin payı ≤ %50): ×1,0;
  - kasa zirveden ≥ %10 aşağıdaysa ek olarak ×0,5.
  - Çarpan işlemi hiç durdurmuyor. Kod varsayılanı kapalı; `ayar.py` yorumuna göre canlı ayarda açık.
- **Stop.**
  - Kaldıraçta stop teminatın %50'sinde ya da likidasyon mesafesinin %70'inde. Seçimli kopyada fiyat stopu %10.
  - Süreye bağlı sıkılaşan stoplar da var.
  - Kaldıraç tavanı: trader'ın kaldıracı ile 5x'in küçüğü; seçimli kopyada 2x.
- **Günlük fren.** Yok; `risk.py` bunu "zarar freni değildir" diye açıkça söylüyor. Yalnız el ile durdurma anahtarı var.
- **Minimum emir.** En küçük emrin altında kalan azaltma tam kapanışa yükseltiliyor; spotta çok küçük kısmi ayna satış yapılmıyor. Bizdeki gibi açılışların yuvarlanmasına özel bir ölçüm görülmedi.

## 5. Kanıt
- **Yazarın kendi ölçümleri** (`docs/GELISIM_GUNLUGU.md` ≈ 1720–1730, README "Ölçümler ne diyor?"):
  - Spot ana masa: 56 kapanış, +0,166 SOL. En iyi 3 işlem çıkarılınca −0,313 SOL.
  - Kaldıraç kopyası: 115 kapanış, −4,13 $. 10.11'deki 36 kapanışlık +5,87 $ sonucu bu ölçümle tersine dönmüş.
  - Hyperliquid, izlenen trader'ların tüm pozisyonları (BTC hareketi çıkarılmış, maliyet %0,15, kırpılmış): izlemeye alınmadan önce açılanlar +%0,34 ± 0,07; izlemeye alındıktan sonra açılanlar n = 12.053, −%0,02 ± 0,05. Bu bir kuralın geri/ileri testi değil; izleme listesine girişteki hayatta kalma yanlılığını gösteriyor. Yazar da öyle yorumluyor.
  - Canlı seçim kuralının kendi sonucu (günlük ≈ 1729): n = 1.549, +%0,15 ± 0,21; trader başına eşit ağırlıkla −%0,62; en iyi 3 trader çıkarılınca −%0,15.
  - Yazarın sonucu: kâr üreten kural bulunamadı (README uyarı kutusu; günlük ≈ 1763–1770).
- **Yöntem.** Önceden yazılmış ölçütler ve ileri test pencereleri kayıtlı. Ağırlık öğrenmede "ileri dönem korelasyonu > 0,05 değilse uygulama" diye bir koruma var (`ogrenme.py`).
- **Tek kaynak.** Bu sayıları bağımsız olarak doğrulamadık; hepsi yazarın kendi raporu.

## 6. Karşılaştırma

| konu | onlar | biz | test edilmeye değer mi |
|---|---|---|---|
| **Para öncesi ileri gölge testi** | puan yalnız aday listesi için; para kararı seçimden *sonraki* 6 canlı gölge işlemle | seçim T'ye kadarki veriyle; para hemen (sanal dönem yalnız sadakati ölçüyor) | **Evet, ama güç düşük.** T'de kapıları geçenlerden yalnız [T, T+14 g) kopya getirisi > 0 olanları T+14'te al, [T+14, T+28) aralığında kontrol çekilişlerine karşı ölç. Yalnız T1–T11 ve pencere ≤ 14.10 (Revizyon 1 sınav verisine taşmasın); yansız havuzda T başına ≈ 1,5 aday var, bu süzgeç onu daha da azaltır. Sonuç yalnız bilgi. |
| **Uzlaşı sinyali** | son 6 sa içinde ≥ N izlenen trader aynı coinde aynı yöne → kendi pozisyonu | yok | **Evet.** 700'lük örneklemin dolumlarından "≥ N hesap 6 saatte aynı coinde aynı yönde açtı" olaylarını çıkar; önbellekteki saatlik mumlarla 4 / 12 / 24 sa sonraki getiriyi (BTC hareketi çıkarılmış) rastgele saatlere karşı ölç. Onlarınki seçilmiş trader'larla çalışıyor, bu test rastgele hesaplarla; birebir aynı şeyi ölçmez. Olaylar örtüşür; `#` / `@` / `:` içeren coinler atılır; mumu olmayan coin sayılır. |
| **Kırılganlık kapısı** | kazançlar +%100'de kırpık; en iyi işlem hariç toplam > 0; kazanma oranı ≥ %40 | kural 7: 28 g kopya getirisi > 0 ve koruma ≥ 0,5; en iyi işlem hariç ölçüsü yok | **Evet, bilgi olarak (güç düşük: aday sayısı daha da azalır).** Kapı 7'ye "en iyi işlem hariç 28 g kopya getirisi > 0" eklenince T1–T11'de seçilenlerin ileri getirisi değişiyor mu, eski ↔ yeni yan yana ölç. Yeni eşik değil, var olan kapının sağlamlık sürümü. |
| **Kanıta bağlı boyut** | n < 30 ×0,5 … kanıtlı ×1,0; zirveden −%10'da ×0,5 | sabit slot; K‑65 büyütme kapıları kasaya bağlı | **Kısmen.** Oynatmada slotu ilk 30 kapanış boyunca yarıya indir; kadro getirisinin ve düşüşün dağılımı nasıl değişiyor, ölç. Seçim sorununu çözmez, yalnız riski düşürür. |
| **Uzun dönem tutarlılık** | 12 haftanın ≥ %70'i pozitif, en kötü hafta ≥ −%20 | kural 2 (12 haftanın ≥ 8'i pozitif + 90 g düşüş) | **Hayır.** Kural 2 bunun neredeyse aynısı; bizim testimizde ters yönde çalıştı. |
| **ROI ağırlıklı sıralama** | aylık / tüm / haftalık ROI karışımı | t‑istatistiği sıralaması | **Hayır.** Geçmiş getiriye dayalı sıralama bizde ters çalıştı. Yazarın izleme öncesi +%0,34 → sonrası −%0,02 sonucu sıralamayı değil, geçmiş görünüme bakarak seçmenin yanlılığını gösteriyor; o da aynı yönde. |
| **Eşiği doluluğa göre kaydırma** | aday azsa eşik 80 → 50 arası düşüyor | eşikler sabit; aday yoksa koltuk boş | **Hayır.** Aday sayısı bizde zaten çok düşük; eşiği düşürmek geniş, yanlı havuzdaki gibi rastgeleden kötü adayları alır (futbol sınaması). |
| **Ağırlık öğrenme** | gece ridge + Spearman, ileri korelasyon > 0,05 koşulu, önselle %50 harman | yok | **Hayır (şimdilik).** Bizde yaklaşık 3,5 bağımsız dönem var; öğrenilen ağırlık gürültüye uyar. |
| **Değiştirme histerezisi** | kırpık gölge toplamı en zayıf üyeden ≥ 0,10 iyiyse değiştir | K‑56 çıkışları ve 31 g bekleme | **Belki, düşük öncelik.** Önce ileri gölge testinin değeri gösterilmeli; gösterilmezse gölge toplamıyla değiştirmek de gürültü olur. |
| **Aşırı uç freni** | 10 dakikada ≥ 8 açılış ya da açık işlemlerin > %40'ı tek trader'da → 30 dk ara | slot tavanı 1,5×; devir kapısı ≤ 25x | **Hayır (seçim için).** İcra güvenliği önlemi; seçim sorusuyla ilgisi yok. |
| **Günlük fren** | yok | günlük −%5 ve zirveden −%20 kasa kilidi | — Bizde daha sıkı. |
| **Coin evreni** | seçimli kopyada en hacimli 60 coin, büyük 6 coin hariç | likidite kapısı (günlük ≥ 1M $) | **Belki.** Kontrol havuzunun ileri getirisini coin grubuna göre ayır (büyük 6 / diğer likit); fark var mı, bilgi olarak ölç. |

**Bizim bulguya göre tek yeni yön, ileri gölge testi; ama ölçme gücü düşük.**
- Bizim ölçtüğümüz şey "geçmiş görünüm iyi mi" idi ve bu ters çalıştı. Onların kararı ise trader izlemeye alındıktan *sonraki* kopya sonucuna dayanıyor.
- Yine de yazarın kendi sonuçları bunun da kâr ettiğini göstermiyor (115 kapanış, −4,13 $; trader başına eşit −%0,62). 6 işlemlik bir pencere istatistik olarak çok kısa.
- Bizim yansız havuzda da aday çok az. Ayrıca "en yeni 10.000 dolum" kesmesi ileriye bakıyor (futbol §5). Sonuç ancak ön bilgi olur.
- Bu yüzden önce ucuz bir geçmiş veri sınaması gerekli; ancak ondan sonra bir kural konuşulabilir.

## 7. Lisans
- GPL‑3.0 (`LICENSE`).
- Kod kopyalanmadı ve çalıştırılmadı; yalnız mantık kendi cümlelerimizle özetlendi.
- Bu fikirlerden biri kendi kodumuzla yeniden yazılırsa, kodlarını almadığımız sürece lisans yükümlülüğü doğmaz. Kod parçası alınırsa bizim depo da GPL uyumlu olmalı. Tavsiye: almayın.

## 8. Bağımsız denetim (Fable)
Bağımsız denetçi raporu dış depo kaynağıyla (commit `532968b`) örnekleyerek karşılaştırdı. Kritik bulgu yok. Filtre ve puan ağırlıkları, oda testi, çıkış koşulları, kanıt sayıları, fren yokluğu ve lisans kaynakla tuttu. Raporda kopyalanmış kod, anahtar ya da kişisel veri yok.

| bulgu | önem | yapılan |
|---|---|---|
| İleri gölge testinde [T+14, T+42) penceresi Revizyon 1 sınav verisine ve geleceğe taşıyor | orta | Pencere [T+14, T+28) yapıldı; sınır 14.10 yazıldı |
| Aday azlığı yüzünden güç yok; dolum kesmesi ileriye bakıyor | orta | Test cümlelerine ve özete eklendi; "en umutlu" ifadesi yumuşatıldı |
| +%0,34 / −%0,02 bir kuralın geri/ileri testi değil, izleme öncesi/sonrası karşılaştırması; canlı seçim kuralının sonucu eksikti | orta | §5, özet ve ROI satırı düzeltildi; n 1.549 sonucu eklendi |
| Risk çarpanında "aday ×0,75" düzeyi ve şartlar eksikti; canlıda açık olduğu yorumu | düşük | Eklendi |
| Test penceresi yalnız sonuç nedenli çıkışta sıfırlanıyor | düşük | Düzeltildi |
| "3 gün geri alınmaz" doğrulanamadı | düşük | "Belirsiz" diye işaretlendi |
| "Gölge toplamı" yerine kırpık toplam; genç hesapta tüm zamanlar terimi sıfırlanıyor | düşük | Düzeltildi |
| Uzlaşı testi onlarınkiyle aynı şeyi ölçmez; örtüşme, BTC hareketi, özel coin adları | düşük | Test cümlesine eklendi |
| Uzun dönem ölçütü kural 2 ile "neredeyse aynı" | düşük | Değişiklik gerekmedi |

Düzeltilemeyen: denetçi `uzlasi.py`, `secim.py`, `ogrenme.py` ile stop ve boyut ayrıntılarını denetlemedi (§9).

## 9. Sınırlamalar
- **Okunmayan dosyalar:** kaldıraç lab katmanı (`kaldirac/lab.py`, `kaldirac/gecmis.py`), `spot/lab.py`, `motor.py`, `kaldirac/trend.py` gövdesi, `spot/masa.py` çıkış kısmı, testlerin gövdeleri, `araclar/` ve `arsiv/` (yalnız klasör adları). Oda testinin dayandığı gölge sonuçlarının nasıl üretildiği bu yüzden doğrulanmadı.
- **Canlı ayarlar bilinmiyor:** gerçek ayar dosyası depoda yok; yalnız örnek dosyası ve kod varsayılanları okundu. Uzlaşı ve seçimli kopyanın canlıda açık olup olmadığı belirsiz. Risk çarpanının canlıda açık olduğu yalnız bir kod yorumundan biliniyor.
- **Denetlenmeyen kısımlar:** `kaldirac/uzlasi.py`, `kaldirac/secim.py`, `ogrenme.py`, stop ve boyut ayrıntıları yalnız bir kez okundu; denetimde ikinci kez bakılmadı.
- **Satır numaraları** yaklaşık; kaynaklar dosya düzeyinde verildi.
- **Kanıt tek kaynaklı:** bütün sayılar yazarın kendi raporları; kodla yeniden üretilmedi.
- **Güvenlik notu:** depo metinlerinde yapay zekâya ya da okuyucuya yönelik talimat benzeri bir ifade bulunmadı.
