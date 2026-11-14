# Futbol yapısı sınaması (geniş kadro + yedek) — geçmiş veri, T1–T11

**Kısa özet (teknik olmayan okuyucu için; K‑56/K‑57 eşiklerine göre okuma, karar değildir)**
1. **11 kişilik takım için kasa:** sınanan slotlar 100, 150 ve 200 $. Bunlar içinde yuvarlamanın en az olduğu slot 200 $; 11 × 200 = **2.200 $** bu yüzden bir *alt sınır*, yeterli kasa olduğu gösterilmiş değil. 250 $ ve üstü sınanmadı. Bugünkü 1.000 $ üst sınırıyla 11 kişi, kişi başı yaklaşık 90 $ eder. Bu boyut ölçülmedi; 100 $'daki sonuca bakılırsa açılışların aşağı yukarı yarısı 11 $'a yuvarlanır.
2. **Yuvarlama (pozisyon düzeyi):**
   - **100 $:** her havuzda K‑56 alarmı olan %30'un üstünde (%45–54).
   - **150 $:** yansız havuzda %20–24, geniş havuzda %35–38.
   - **200 $:** yansız havuzda %22–25; geniş havuzda (%31–33) ve kontrolde (%39) alarmın üstünde.
   - K‑57'nin büyüme koşulu (yuvarlanan + atlanan < %20) **hiçbir slotta** sağlanmıyor; 200 $'da bu toplam %29–43.
   - Slot büyüdükçe kopyanın trader'a sadakati artıyor; getiri toplamda neredeyse değişmiyor.
3. **Sıralamasız geniş kadro rastgeleden iyi mi? İyi olduğu gösterilemedi.**
   - Yansız örneklemde T başına ortalama yalnız 1,5 temiz aday var. 11 kişilik takım kurulamıyor: N=11'de koltukların ortalama %86'sı boş (N=3'te %52).
   - Dolu koltukların getirisi rastgele kadroların %79–82'sini geçiyor. Önceden belirlenen geçme çizgisi %90 ve sonuç yalnız 7 adresten (17 gözlem) geliyor. Tek bir +%20,7 gözlemi çıkarılınca bu oran ≈ %53'e düşüyor.
4. **Geniş (yanlı) havuz:** aday sayısı için ayrıca denendi. Takım çoğunlukla doluyor, ama işaret kötü yönde:
   - Rastgele kadroların yalnız %5–35'ini geçiyor; dolu koltukta %7–21.
   - 4 haftalık ortanca getiri −%1 ile −%2,4 arası.
   - N=3/5'te T'lerin %18–27'sinde kayıp −%5'ten büyük.
   - Yaklaşık 3,5 bağımsız dönem ve 36 adresle bu fark anlamlı sayılamaz.
5. N büyüdükçe kötü haftalar seyreliyor. Bu kısmen nakit etkisi: boş koltuklar getiriyi sıfıra çekiyor. Ortanca getiri yine negatif. Bu bir gözlem, kanıt değil.
6. Bu çalışma yeni bir eşik önermiyor ve canlı sisteme dokunmuyor. Sonuçlar örneklem içi ve ön bilgidir. Kesin hüküm Revizyon 1'in T12–T16 ileri sınavında verilecek (son olgunlaşma 09.12).
7. Getiriler 4 haftalık; maliyet (taker + kayma) ve funding düşülmüş. Getiri kasa oranıdır; boş koltuk nakit, getirisi 0.
8. Ham sonuçlar: `ham_sonuclar.csv` (havuz × N × slot × T), `hucre_ozet.csv` (24 hücre), `uye_getiri.csv` (adres × T × slot).
9. Kod `futbol.py`, testler `test_futbol.py`. Slot 200'de yeniden oynatma, önceki koşunun önbelleğiyle 30/30 örnekte birebir aynı.
10. İki bağımsız denetimin bulguları ve yapılanlar §6–§7'de.

---

## 1. Yöntem
- **Veri:** `secim_dogrulama.yml` iş akışının son başarılı koşusundaki önbellek (run 43567103296, artifact `secim-dogrulama-durum`, 14.11 06:36Z). HL'den yeniden veri çekilmedi. Tarihler T1 (29.07) – T11 (07.10); her biri için pencere [T, T+28 g). T12 (14.10) ve sonrası okunmadı (kodda kilit var).
- **Seçim (her T'de):** hesap ≥ 50.000 $ ∧ T'den önceki 30 g perp pnl > 0 ∧ `KURALLAR_DONDURULDU.md` kapıları 3–7 (aynen, slot 200 ile) ∧ iki veto (ömür boyu perp pnl ≤ 0; zarara ekleme). Kural 2 ve t sıralaması yok. Bu, Revizyon 1 seçim kuralının aynısıdır.
- **Kadro:** temiz adaylar adrese göre sıralanır ve `default_rng([20261111, T_ms])` ile karıştırılır. İlk N kişi kadroya girer, kalanlar yedektir. Kadrolar iç içedir: 3 ⊂ 5 ⊂ 8 ⊂ 11. Ağırlıklar eşittir. Kasa = N × slot; boş koltuk nakittir. Kadro getirisi = Σ üye slot getirisi / N. Ek olarak "dolu koltuk" getirisi de hesaplandı: yalnız dolu koltukların ortalaması.
- **Kopya oynatması:** `olcum.oynat` yolunun aynısıdır (`kopya_v5`). Gecikme yoktur. Taker %0,045 + kayma %0,05 ve funding düşülür. Pencere başında kopya boştur. Minimum emir 11 $; 5,5 $ altı açılmaz, [5,5; 11) arası 11 $'a yuvarlanır. Slot tavanı 1,5×. Slotu değiştirmek için yalnız bellekteki kural kopyasında `canli_kasa_usd` = 5 × slot ve `radar_canli_slot_min_usd` = slot yapıldı; `kurallar.yaml` değişmedi.
- **Kontrol:** Dondurulmuş kontrol kullanıldı: sabit tohumlu 700 adres; her T'de ≥ 50k ∧ 30 g pnl > 0 olanlar ve dolum verisi yetenler (T başına 176–293 adres). Her T'de bu havuzdan yerine koymadan 1.000 rastgele N kişilik kadro çekildi; çekilişin getirisi üyelerin ortalamasıdır. Çekiliş tohumu slottan bağımsızdır, böylece slotlar eşli karşılaştırılır. **Yüzdelik** = P(çekiliş < kadro) + ½·P(eşit). **Birleşik yüzdelik:** kadronun T ortalaması, her çekilişin T ortalamasıyla karşılaştırılır (KURALLAR §3 şart 1'e *benzer*: §3 T başına ortanca kullanır, burada kadro getirisi üyelerin ortalamasıdır; %90 çizgisi yalnız referans). Dolu koltuk sürümü, k kişilik çekilişlerle (k = dolu koltuk sayısı) karşılaştırılır.
- **Yuvarlama ölçüleri:**
  - **Pozisyon düzeyi (ana ölçü):** trader'ın coin başına her düz → açık epizodu ele alınır. *yuvarlanan* = ilk açılışı 11 $'a yuvarlanan epizot / kopyanın açıldığı epizot. *atlanan* = kopyanın hiç açılmadığı epizot / tüm epizotlar.
  - **Karar düzeyi (ek ölçü):** her "aç" kararı sayılır. Bu ölçü şişkindir: atlanan bir açılıştan sonra gelen her ekleme yeniden sayılır.

## 2. Havuzlar
- **ornek700 (birincil, yansız):** dondurulmuş 700'lük rastgele örneklem. Dolum verisi yalnız bu örneklemde eksiksiz. T başına 1–4 temiz aday çıktı (ortalama 1,5); T1–T11 boyunca toplam 7 adres.
- **genis (ikincil, YANLI, yalnız bilgi):** önbellekte dolum verisi olan 3.033 adresin tümü. Bunların 700'ü ornek50, 285'i s10 örneklemi; 2.048'i "herhangi bir T'de (bugün, 11.11 dahil) ≥ 10k ∧ kural 2" ile seçilmiş. Bu üyelik **ileriye bakar**: T'den sonraki bilgiyle belirleniyor. Kapıları önbellekte olmayan satırlar için kapılar yeniden hesaplandı; yeniden hesap, önbellekte zaten olan 60 satırda önbellekle aynı sonucu verdi. T başına 4–12 aday çıktı (ortalama 8,3), toplam 36 adres. Kontrol olarak yine ornek700 kontrolü kullanıldı.
- **Tam evren neden yok:** kural 2'yi hiçbir T'de geçmeyen ve örneklem dışında kalan hesapların dolumları önbellekte yok. Kullanıcı talimatı gereği veri yeniden çekilmedi.

## 3. Sonuçlar (hücre özeti; 11 T; maliyet sonrası 4 hafta)
Sütunlar:
- **BK:** boş koltuk oranı, yani aday < N olan T'lerin payı.
- **kadro ort./ortalama:** kasa getirisinin ortancası ve ortalaması.
- **<−%5:** kasa getirisinin −%5'in altında kaldığı T'lerin payı.
- **dolu ort.:** dolu koltuk getirisinin ortancası.
- **yüzd.:** birleşik yüzdelik (kasa).
- **dolu yüzd.:** birleşik yüzdelik (dolu koltuk).
- **yuv./atl.:** pozisyon düzeyi yuvarlanan / atlanan payı.

**ornek700 (yansız)**

| N | slot | BK | kadro ort. | ortalama | <−%5 | dolu ort. | yüzd. | dolu yüzd. | yuv. | atl. |
|---|---|---|---|---|---|---|---|---|---|---|
| 3 | 100 | 0,91 | +0,4% | +0,7% | 0 | +1,2% | 0,70 | 0,81 | 0,54 | 0,15 |
| 3 | 150 | 0,91 | +0,5% | +0,6% | 0 | +1,0% | 0,70 | 0,82 | 0,24 | 0,12 |
| 3 | 200 | 0,91 | +0,5% | +0,7% | 0 | +1,2% | 0,70 | 0,81 | 0,25 | 0,08 |
| 5 | 100 | 1,00 | +0,2% | +0,3% | 0 | +0,4% | 0,61 | 0,79 | 0,45 | 0,15 |
| 5 | 200 | 1,00 | +0,2% | +0,3% | 0 | +0,4% | 0,61 | 0,79 | 0,22 | 0,09 |
| 8 | 200 | 1,00 | +0,1% | +0,2% | 0 | +0,4% | 0,57 | 0,79 | 0,22 | 0,09 |
| 11 | 100 | 1,00 | +0,1% | +0,1% | 0 | +0,4% | 0,61 | 0,79 | 0,45 | 0,15 |
| 11 | 150 | 1,00 | +0,0% | +0,1% | 0 | +0,2% | 0,60 | 0,79 | 0,20 | 0,13 |
| 11 | 200 | 1,00 | +0,1% | +0,1% | 0 | +0,4% | 0,59 | 0,79 | 0,22 | 0,09 |

- Kasa yüzdeliği 0,57–0,70; bunun önemli kısmı nakdin etkisi. Kontrol havuzu ortancası her T'de %0: slot 200'de kontrol satırlarının ≈ %40'ında kopya hiç pozisyon açmıyor (getiri 0; %31'inde pencerede dolum yok). Koltuk düzeyinde boş pay: N=3 %52, N=5 %69, N=8 %81, N=11 %86.
- N ≥ 5'te üyeler aynı 1–4 kişi olduğu için dolu koltuk sonuçları N'den bağımsız. **Bu havuzda N'nin etkisi ölçülemiyor.**
- Dolu koltuk ortalaması (+%1,7–1,9) ortancadan (+%0,2–1,2) yüksek; ortalamayı tek bir büyük kazanç (+%20,7) yukarı çekiyor. Tur 1'deki C kolunun aynı 17 gözlemi bunlar; bu gözlem çıkarılınca dolu yüzdelik ≈ 0,53.

**genis (yanlı; bilgi)**

| N | slot | BK | kadro ort. | ortalama | <−%5 | dolu ort. | yüzd. | dolu yüzd. | yuv. | atl. |
|---|---|---|---|---|---|---|---|---|---|---|
| 3 | 100 | 0,00 | −1,1% | −2,7% | 0,27 | −1,1% | 0,10 | 0,09 | 0,51 | 0,28 |
| 3 | 200 | 0,00 | −1,0% | −2,8% | 0,27 | −1,0% | 0,08 | 0,08 | 0,33 | 0,18 |
| 5 | 100 | 0,18 | −2,4% | −2,2% | 0,18 | −2,4% | 0,07 | 0,08 | 0,45 | 0,25 |
| 5 | 150 | 0,18 | −2,4% | −2,3% | 0,18 | −2,4% | 0,05 | 0,08 | 0,35 | 0,18 |
| 5 | 200 | 0,18 | −2,4% | −2,3% | 0,18 | −2,4% | 0,05 | 0,07 | 0,31 | 0,17 |
| 8 | 200 | 0,45 | −1,7% | −1,5% | 0 | −2,7% | 0,11 | 0,11 | 0,31 | 0,16 |
| 11 | 100 | 0,64 | −1,2% | −0,5% | 0 | −1,3% | 0,35 | 0,21 | 0,46 | 0,26 |
| 11 | 150 | 0,64 | −1,2% | −0,6% | 0 | −1,4% | 0,33 | 0,19 | 0,36 | 0,18 |
| 11 | 200 | 0,64 | −1,2% | −0,6% | 0 | −1,5% | 0,32 | 0,19 | 0,31 | 0,17 |

- Bu havuzun üyeliği ileriye bakıyor, yani kadroyu iyimser yönde yanlı kılmalıydı. Buna rağmen kadro rastgeleden kötü çıktı.
- N=11'de kasa yüzdeliği 0,32–0,35'e çıkıyor. Bu iyileşme değil, nakit etkisi: T'lerin %64'ünde en az bir koltuk boş, koltukların ortalama %28'i boş. Dolu koltuk yüzdeliği 0,19–0,21.
- **Belirsizlik:**
  - T başına yüzdelik ortancası 0,34–0,52; birleşik değer bundan sert görünüyor.
  - Aday gözlemlerinin ortancası +%0,2'dir ve %58'i ≥ 0. Negatif ortalamayı birkaç büyük kayıp taşıyor (en kötüsü −%28); 36 adres 91 gözlemde tekrar ediyor.
  - Kontrol yalnız getirisi ≠ 0 olan hesaplardan çekilince dolu yüzdelik N=3'te 0,16, N=11'de 0,26.
  - N=3/5 kadroları tek bir kura tohumuna dayanıyor; tohum oynaklığı ölçülmedi.
  - Hüküm: rastgeleden iyi değil, işaret kötü yönde; anlamlılık iddia edilemez.
- Ayrıntılı satırlar (150 $ dahil) `hucre_ozet.csv`'de.

**Slot etkisi:** üye getirisi slotla *toplamda* neredeyse değişmiyor (tek adreste fark ±20 puana çıkabiliyor; |fark| p90 1,4 puan). 2.528 (adres, T) satırında ortalama −%0,2, ortanca %0, aralık −%89 … +%146; üç slotta da aynı. Değişen yalnız sadakat. Kontrol havuzunda (ölçek için) pozisyon düzeyi değerler:

| slot | yuvarlanan | atlanan |
|---|---|---|
| 100 $ | %48 | %53 |
| 150 $ | %44 | %47 |
| 200 $ | %39 | %43 |

Olası neden (ölçülmedi): kontrol hesapları büyük olduğu için küçük açılışlar minimum emrin altında kalıyor.

## 4. Sorulara yanıt (K‑56/K‑57 eşiklerine göre okuma; karar değildir)
- **Ölçü farkı:** K‑56/K‑57 canlıda "açılış payı" ölçer. Burada ana ölçü epizot düzeyi; payda hiç açılmayanları içermez. Karar düzeyinde aynı hücreler %7–16 çıkıyor (`yuvarlanan_ac_pay`; şişkin payda). Kıyas yaklaşık.
- **Kasa (11 kişi):** sınanan slotlar içinde yuvarlaması en düşük olan 200 $. Yine de geniş havuzda (%31–33) ve kontrolde (%39) K‑56 alarmının (> %30) üstünde. Yansız havuzda 150 $ da alarmın altında (%20–24), ama orada yalnız 27–32 epizot var.
  - 11 × 200 = 2.200 $ yalnız bir **alt sınır**.
  - K‑56'nın > %30 için yazılı tepkisi "4 × 250 $"; 250 $ sınanmadı.
  - Kasa üst sınırı 1.000 $ (K‑22/K‑50) ve yalnız kullanıcı kararıyla değişir.
- **Yuvarlama:**
  - 100 $ her havuzda alarmın üstünde (%45–54). 150 $ ve 200 $ havuza bağlı (%20–38).
  - Hiç açılmayan pozisyon payı 200 $'da %8–18, 100 $'da %15–28.
  - K‑57 artış koşulu (yuvarlanan + atlanan < %20) hiçbir hücrede sağlanmıyor (200 $'da %29–43).
- **Sıralamasız geniş kadro:**
  - Rastgeleden iyi olduğu gösterilemedi. Yansız havuz takım kuracak kadar aday üretmiyor; yanlı havuzda işaret kötü yönde.
  - N büyüdükçe dolu koltukta < −%5 payı 3/11 → 2/11 → 1/11 → 1/11 iniyor. Bu, örtüşen iki pencerelik bir fark; ortanca getiri yine negatif.

## 5. Sınırlamalar
- **Örtüşen pencereler:** 11 haftalık tarih × 28 günlük pencere ≈ **3,5 bağımsız dönem** (T1 29.07 → T11 + 28 g = 04.11, 98 g / 28). Yüzdelikler ve oranlar bu yüzden olduğundan daha kesin görünür.
- **Hayatta kalma yanlılığı:** evren 11.11 lider tablosundan kuruldu. Pencerede batıp tablodan düşen hesaplar eksik; bu, sonuçları iyimser yönde etkiler.
- **Örneklem içi:** T1–T11, Revizyon 1'in tasarlandığı veridir (kural 2 ve t sıralaması bu veriye bakılarak kaldırıldı). Burada iyi görünen bir şey kanıt sayılmaz. Ayrıca T9–T11 ileri pencereleri (04.11'e dek) takvimde Revizyon 1'in T12–T15 pencereleriyle çakışır.
- **Örneklem küçük:** ornek700'de 7 adres / 17 gözlem var; tek bir +%20,7 gözlemi çıkarılınca dolu yüzdelik 0,79 → ≈ 0,53.
- **Tek kura tohumu:** N < aday olan hücrelerde (genis N=3/5) sonuç tek bir karıştırmaya bağlı; tohum oynaklığı ölçülmedi.
- **250 $ ve üstü slotlar** ile 90 $ (1.000 $ / 11) ölçülmedi.
- **Dolum eksikliği (dondurulmuş hattan miras):** her T'de kontrol havuzundaki hesapların 65–93'ü (≈ %25) "dolum geçmişi yetmez" diye çıkarıldı. Adres başına en yeni 10.000 dolum tutulduğu için bu çıkarma ileriye bakar ve çok işlem yapan hesapları dışarıda bırakır. Seçim ve kontrol grubuna aynı biçimde uygulandı.
- **Kontrolde atıl hesaplar:** kontrol ortancası %0: satırların ≈ %40'ında kopya hiç pozisyon açmıyor (sıfırlar ortayı kaplıyor). Kasa yüzdeliği bu yüzden nakitle şişer; dolu koltuk yüzdeliği daha adil bir karşılaştırmadır.
- **Gecikme yok:** kopya, trader'ın dolum fiyatından oynatıldı. Gerçek kopyada gecikme getiriyi daha da düşürür.
- **Seçim kapıları slot 200 ile hesaplandı.** Daha küçük slotta kural 6 (atlanan hacim ≤ %20) daha çok adayı elerdi; bu etki ölçülmedi.

## 6. Bağımsız denetim (1) — kod, tam koşudan önce
Kritik bulgu yok. Denetçi şunları kendi betikleriyle doğruladı: seçim tanıma uyuyor; ileriye bakma ve T12 sızıntısı yok; slot değişikliği oynatmayı slot ölçeği dışında değiştirmiyor (minimum emir yarıya indirilmiş slot 100 koşusu, slot 200 ile bit bit aynı çıktı); birimler (kasa → slot ×5) doğru.

| bulgu | önem | yapılan |
|---|---|---|
| Yuvarlama sayımı karar düzeyinde ve şişkin (atlanandan sonraki her ekleme yeniden sayılıyor; payda tavan kararlarını da içeriyor) | orta | Pozisyon (epizot) düzeyi ölçü eklendi ve ana ölçü yapıldı; neden kodları ayrı sütunlarda; altın test eklendi |
| Birincil havuz kadro kurmaya yetmiyor; kasa yüzdeliği nakitle seyreliyor | orta | Dolu koltuk getirisi ve yüzdeliği eklendi; raporda "N etkisi ölçülemiyor" yazıldı |
| `dolum_gecmisi_yetmez` çıkarması ileriye bakıyor (miras) | orta | Kod değişmedi (dondurulmuş). T başına çıkarılan sayısı `ham_sonuclar.csv`'ye eklendi; §5'te yazıldı |
| İşçi hatası sessizce düşüyordu | düşük | Örneklem ya da aday adreste hata olursa çıkış kodu 2. Tam koşuda hata 0 |
| Önbellek anahtarı bayat kalabilirdi | düşük | Anahtara slot listesi ve `kurallar.yaml` sha256 eklendi; tam koşu temiz önbellekle yapıldı |
| T9–T11 ile Revizyon 1 pencereleri takvimde çakışıyor | düşük | §5'e yazıldı |
| genis tanımı s10 örneklemini de içeriyor | düşük | §2'de düzeltildi |
| `tasfiye` / `fiyatsiz` alanları çıktıda yoktu | düşük | `uye_getiri.csv`'ye eklendi (fiyatsız 0) |

## 7. Bağımsız denetim (2) — rapor taslağı
Kritik bulgu yok. Denetçi tabloları `ham_sonuclar.csv`'den yeniden hesapladı ve tuttuğunu doğruladı; yüzdelikleri kendi çekilişiyle benzetti. Bulguların hepsi rapora işlendi:

| bulgu | önem | yapılan |
|---|---|---|
| "Koltukların %91–100'ü boş" yanlış: bu, aday < N olan T payı; koltuk payı %52–86 (genis N=11 %28) | orta | Özet ve §3 düzeltildi |
| "Kontrolün yarıdan fazlası işlem yapmıyor" desteklenmiyor | orta | "≈ %40'ında kopya hiç açmıyor; %31'inde dolum yok" |
| "Rastgeleden kötü" fazla kesin | orta | "İşaret kötü yönde, anlamlılık yok"; T başına yüzdelik, ≠ 0 kontrol, tek tohum notları eklendi |
| "2.200 $" ve "200 $ tek düzgün slot" abartı | orta | Alt sınır diye yazıldı; 150 $ (yansız) ve 250 $ sınanmadığı eklendi; 90 $ tahmin diye etiketlendi |
| K‑56 ile ölçü tanımı farkı; K‑57 ölçütü eksik | orta | §4'e ölçü farkı ve K‑57 (< %20 hiçbir yerde sağlanmıyor) eklendi |
| Kuyruk kaybı azalması kısmen mekanik | düşük | Gözlem olarak yazıldı, dolu koltuk sayıları verildi |
| %79–81 → %79–82; +%20,7 çıkınca ≈ 0,53 | düşük | Düzeltildi |
| §3 şart 1 ile ortanca/ortalama sapması | düşük | §1'e yazıldı |
| Slot etkisi yalnız toplamda küçük | düşük | Kayıt eklendi |
| 3,8 → 3,5 bağımsız dönem; tarih yazımı | düşük | Düzeltildi |
| "Kontrol hesapları büyük" ölçülmemiş açıklama | düşük | "Olası neden (ölçülmedi)" |

**Düzeltilemeyen (açık):** tek kura tohumu, 250 $+ slotlar, tam evren dolumları (veri yok), `dolum_gecmisi_yetmez` ileriye bakması (dondurulmuş hattan miras).

## 8. Yeniden üretim
```
WF_VERI=<durum klasörü> python arastirma/futbol_sinama/futbol.py --isci 4      # ≈ 2 dk
python -m pytest -q arastirma/futbol_sinama                                     # 9 geçti
python arastirma/futbol_sinama/dogrula_slot200.py                               # slot 200 = önbellek (30/30, fark 0)
```
- Tam test paketi: 1.261 geçti, 1 atlandı, 1 hata. Hata, ortamda `websockets` modülü olmadığı için bu işle ilgisiz `test_g17a_ws_baglan_protokol_pingi_acik` testinde.
- Deneme: önce küçük gerçek veriyle koşuldu (T1, 95 adres), çıktı gözle kontrol edildi, sonra tam koşu yapıldı.
