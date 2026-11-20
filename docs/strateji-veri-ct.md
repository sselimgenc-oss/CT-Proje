# CT strateji verisi (salt okuma analiz)

Bu belge kod değiştirmez. Yalnız `origin/canli-durum` ve `origin/radar` verisinden sayım ve özet içerir. Yorum yok.

## Veri penceresi ve düzeltme durumu

| Kalem | Değer |
|---|---|
| Sanal başlangıç | 16.11 14:30 TSİ (11:30 UTC) |
| Veri anı (son kayıt) | 20.11 15:44 TSİ |
| Kayıt sayısı | 23.256 tekil satır (5 dosyada 4.352 tekrar satır çıkarıldı) |
| O1 + O3 birleşme | 20.11 15:15 TSİ |
| O1 + O3 canlıya alım | 20.11 16:04 TSİ |
| Bu belgedeki tüm veri | düzeltme öncesi (veri anı canlıya almadan önce) |

Etiket kuralı: "O1/O3'ten etkilenir" işaretli sayılar, azaltma çarpanı (O1) veya haber filtresi (O3) ile değişebilecek sayılardır. Düzeltme sonrası yeniden koşulacak.

Kaynak zamanları (TSİ): kadro formu 20.11 10:42; kural maliyeti 20.11 15:03; kopya seçimi 20.11 15:03; mutabakat v2 20.11 04:05; hesap özsermayesi 20.11 15:43 (`durum/ozet.json`).

Tanımlar: pozisyon = bir (trader, coin) döngüsü, büyüklük sıfıra inince kapanır. Pozisyon net = gerçekleşen K/Z − kapanış ücreti (`copytrade/canli/pano.py` `kapanan_islemler`). Kazanma oranı pozisyon bazındadır.

## Ortak 1: Sanal başlangıçtan beri sonuç

| Kalem | Değer | Veri anı | Etiket |
|---|---|---|---|
| Gerçekleşen K/Z (kapanış dolumları, net) | −23,09 $ (brüt −18,46 $) | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| Kapanan pozisyon sayısı | 24 | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| Kazanma oranı (pozisyon) | 8/24 = %33,3 | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| Ortalama kazanç / kayıp (pozisyon başı) | +14,44 $ / −7,89 $ | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| Yalnız kapanan pozisyonların net toplamı | −10,74 $ | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| Hesap özsermayesi | 9.990,05 $ (başlangıç 10.000 $: −9,95 $) | 20.11 15:43 TSİ | düzeltme öncesi |

Not: gerçekleşen K/Z (−23,09 $) ile kapanan pozisyon toplamı (−10,74 $) arasındaki fark (−12,35 $), hâlâ açık pozisyonların kısmi kapanışlarıdır.

## Ortak 2: Yoğunlaşma

| Kalem | Değer | Veri anı | Etiket |
|---|---|---|---|
| En iyi 1 pozisyon | +66,15 $ (HYPE, trader 0x6d2667) | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| En iyi 2 pozisyon toplamı | +96,69 $ (ikisi de 0x6d2667) | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| En iyi 2 / kazanan pozisyonların toplamı (115,51 $) | %83,7 | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| En iyi 2 / net K/Z | net negatif, oran anlamsız | — | — |
| En iyi 3 toplamı | +107,43 $ | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| En kötü 3 toplamı | −84,81 $ (ETH −49,87; SOL −19,68; BTC −15,26; üçü de 0xdebd49) | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| En iyi 3 ve en kötü 3 hariç, kalan 18 pozisyon | −33,35 $ | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |

## Ortak 3: Maliyetler

| Kalem | Değer | Veri anı | Etiket |
|---|---|---|---|
| Komisyon (ücret), toplam | 13,35 $ (açılış 8,72 $ + kapanış 4,63 $) | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| Fonlama (96 saatlik kayıt) | −0,59 $ (maliyet) | 20.11 15:44 TSİ | düzeltme öncesi |
| Kayma (dolum ↔ trader fiyatı, 261 dolum) | +0,87 $ (maliyet), ortalama 0,29 baz puan | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| Toplam maliyet | 14,81 $ | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| Maliyet / kazanan pozisyonların toplamı (115,51 $) | %12,8 | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |

Brüt K/Z negatif olduğu için "brüt kâr yüzdesi" tanımlı değil. Açılış ücreti ve fonlama dahil tahmini sonuç: −32,40 $ (kayma fiyatın içinde olduğu için ayrıca çıkarılmadı).

## Ortak 4: Hangi filtre en çok engelledi, alınsaydı sonucu

Olay sayısı, `emir_yok` kaydında açılış ve artırma (`ac`, `artir`) olayları. "Ayrı" sütunu aynı dakika-trader-coin sayısıdır. Alınsaydı sonuçları karşı-olgu verisidir: kapanan kısım 20.11 15:44 TSİ'ye kadar, açık kısım 20.11 15:03 TSİ anlık değerlemedir. Hayali pozisyon, ilk atlamadan sonra tek kez açılır; bu nedenle örnek alt sınırdır.

| Neden | Olay | Ayrı | Alınsaydı kapanan (n, $) | Alınsaydı açık (n, $) | Toplam $ | Etiket |
|---|---:|---:|---|---|---:|---|
| slot_tavani | 5.670 | 2.285 | 2, +0,68 | 17, −19,77 | −19,09 | O1/O3'ten etkilenir |
| bant_ici | 5.239 | 2.327 | karşı-olgu yok (tasarım gereği) | — | — | O1/O3'ten etkilenmez |
| hip3_atlandi | 3.578 | 1.556 | 4, −14,95 | 18, −10,70 | −25,65 | O1/O3'ten etkilenir |
| ters_netlesme | 1.261 | 657 | 5, +0,77 | 9, +1,83 | +2,60 | O1/O3'ten etkilenir |
| duygu_ters | 658 | 212 | 0 | 12, +8,96 | +8,96 | O1/O3'ten etkilenir |
| min_emir_atlandi | 113 | 62 | 1, −0,02 | 2, −0,12 | −0,14 | O1/O3'ten etkilenir |
| haber_ters | 8 | 4 | 0 | 2, +2,07 | +2,07 | O3 (düzeltme sonrası yeniden koşulacak) |
| rejim_ters, spot, gec_acilis, trader_hesap_yok, patlama_freni | 28 | — | 0 | 1, 0,00 | 0,00 | O1/O3'ten etkilenir |

En çok engelleyen: olay sayısına göre slot_tavani (5.670), ayrı dakika-trader-coin sayısına göre bant_ici (2.327). Alınsaydı P&L'de en büyük negatif hip3_atlandi (−25,65 $), en büyük pozitif duygu_ters (+8,96 $); bunlar hayali değerlerdir.

## Ortak 5: Ders ve ML etkisi

| Kalem | Değer | Veri anı | Etiket |
|---|---|---|---|
| Ders çarpanı = 1,0 (etkisiz) | 42 emir kaydı; 219 kayıtta alan boş | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenmez |
| Ders ile değişen işlem | 0 | 20.11 15:44 TSİ | düzeltme öncesi |
| ML "model yok ya da süresi dolmuş" olayı | 18 | 20.11 15:44 TSİ | düzeltme öncesi |
| ML ile atlanan açılış (`ml_filtre_atla`) | 0 | 20.11 15:44 TSİ | düzeltme öncesi |
| ML ile değişen işlem | 0 | 20.11 15:44 TSİ | düzeltme öncesi |
| Öğrenme adayı olayı | 9 (bilgi) | 20.11 15:44 TSİ | düzeltme öncesi |

Sonuç: ölçülebilir katkı yok, veri yetersiz (n=0 değişen işlem).

## Ortak 6: Rejime göre sonuç

Giriş anı bağlamı (`giris_ctx`) 24 kapanış dolumunun hiçbirinde dolu değil; coin bazlı rejim ölçülemedi. Bunun yerine BTC 1 günlük rejimi, pozisyonun açılış anına göre kullanıldı (BTC rejim verisi 19.11 20:41 TSİ'de başladı).

| BTC rejimi (açılış anı) | Pozisyon | Net $ | Kazanma | Veri anı | Etiket |
|---|---:|---:|---:|---|---|
| bilinmiyor (19.11 20:41 öncesi) | 23 | −10,41 | 8/23 | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| düşüş (trend_down) | 1 | −0,32 | 0/1 | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| yükseliş, yatay | 0 | — | — | — | — |

Sonuç: veri yetersiz (sınıflanmış pozisyon n=1).

## Ortak 7: Anlamlı karar için gereken sayı

Formül: n = z² · p(1−p) / E². z = 1,96 (%95 güven), p = kazanma oranı, E = istenen yarı genişlik.

Hız: 24 kapanan pozisyon / 4,05 gün = 5,9 pozisyon/gün ≈ 41,5 pozisyon/hafta (veri anı 20.11 15:44 TSİ). Gözlenen p = 0,333.

| Hedef | n (p = 0,333) | Hafta (41,5/hafta) | n (p = 0,5, en geniş) | Hafta |
|---|---:|---:|---:|---:|
| ±10 puan | 85 | 2,0 | 96 | 2,3 |
| ±5 puan | 342 | 8,2 | 385 | 9,3 |

Bu yalnız kazanma oranı içindir. Ortalama K/Z için dağılım (standart sapma) gerekir; hesaplanmadı. Etiket: O1/O3'ten etkilenir (pozisyon sayısı değişebilir).

## CT 18: Trader bazında kopya sonucu

Dönem: 16.11 14:30 TSİ → 20.11 15:44 TSİ. Trader sonucu Hyperliquid `userFillsByTime` (closedPnl − ücret) ile alındı. Hesap değeri `clearinghouseState` ile anlıktır. Kopya sütunu: gerçekleşen net K/Z; yüzde = kopya K/Z / 909,09 $ slot.

| Trader | Kopya emir | Kapanan poz. | Kazanma (poz.) | Kopya K/Z $ | Kopya % (slot) | Trader net $ (HL) | Trader hesap değeri (şu an) $ |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0x2d29c0… | 50 | 5 | %20 | −3,95 | −0,43 | −174 | 36.532 |
| 0x3d380a… | 2 | 0 | — | 0,00 | 0,00 | −1.116 | 28.849 |
| 0x6a8686… | 30 | 2 | %50 | −0,25 | −0,03 | 5.000 | 9.270 |
| 0x6d2667… | 23 | 2 | %100 | +96,69 | +10,64 | 1.945 | 1.461 |
| 0x76c2cd… | 41 | 2 | %50 | +5,56 | +0,61 | −67.263 | 597.556 |
| 0x9eb42f… | 1 | 0 | — | 0,00 | 0,00 | +34.746 | 0 |
| 0xc30c7e… | 22 | 3 | %33 | +0,33 | +0,04 | +132.697 | 1.036.412 |
| 0xc3602c… | 15 | 0 | — | −2,58 | −0,28 | +509 | 305.561 |
| 0xdebd49… | 75 | 9 | %11 | −119,17 | −13,11 | −1.325 | 1.505 |
| 0xe69acc… | 0 | 0 | — | 0,00 | 0,00 | +64.510 | 19.755 |
| 0xf83e8b… | 2 | 1 | %100 | +0,27 | +0,03 | +4.007 | 17.369 |
| Toplam | 261 dolum | 24 | %33 | −23,09 | — | — | — |

Kopya farkı (kopya % − trader %): hesaplanamadı. Trader'ın başlangıç hesap değeri bu sorguda yok; şu anki değer paydası kullanılırsa oranlar yanıltıcı olur (bazı hesaplar 1.500 $ civarında, bazıları 1 milyon $ üstünde). Etiket: düzeltme öncesi; O1/O3'ten etkilenir.

## CT 19 (öncelik): Form Radarı ve rastgele karşılaştırma

### a) Radar isabeti, rastgele örnekle karşılaştırma (radar, 7 günlük kopya getirisi ortalaması)

Bu veri 5–9 Kasım'a aittir; sanal dönemden önce. Veri anı: radar koşuları. "Evren" = radarın rastgele 30 kişilik örneği.

| Tarih | İlk 11 ort. (kar oranı, n) | Elenen ort. (kar oranı, n) | Evren örneği ort. (kar oranı, n) |
|---|---|---|---|
| 05.11 | −0,75% (%18, 11) | −0,80% (%25, 16) | −0,66% (%30, 27) |
| 06.11 | −0,82% (%27, 11) | −0,50% (%24, 17) | +0,01% (%21, 29) |
| 07.11 | −0,52% (%30, 10; eksik) | −0,40% (%27, 22) | −0,06% (%18, 28) |
| 08.11 | −0,31% (%50, 10; eksik) | −0,49% (%29, 14) | −0,15% (%17, 23) |
| 09.11 | −0,56% (%20, 10; eksik) | −0,43% (%44, 18) | +0,31% (%39, 28) |
| Ortalama | −0,59% | −0,52% | −0,11% |

İlk 11, evren örneğinin altında kaldı (5/5 gün). Veri anı: radar koşuları 05.11–09.11; etiket: sanal dönemden önce, düzeltme ile ilgisiz.

### b) Form puanı ile gerçek K/Z arasındaki Spearman ρ

Dosya değeri: `durum/paylasim/secim_gercek_v1.json` (üretim 20.11 15:03 TSİ).

| Kesit | n | ρ | p (tek yönlü) | Etiket |
|---|---:|---:|---:|---|
| 19.11 (dosya) | 4 | −0,80 | 0,958 | düzeltme öncesi; O1/O3'ten etkilenir |
| 20.11 (dosya) | 3 | −0,50 | 0,833 | düzeltme öncesi; O1/O3'ten etkilenir |
| İki gün ortalaması (dosya) | 2 gün | −0,65 | 0,925 | düzeltme öncesi |
| İki günün 7 çifti birlikte (hesaplandı) | 7 | −0,25 | — | düzeltme öncesi |
| Trader düzeyi: gün ortalama formu ↔ dönem kopya K/Z | 5 | −0,30 | — | düzeltme öncesi; O1/O3'ten etkilenir |

Doğrulama sonucu: ρ ≈ −0,63 birebir yeniden üretilmedi. Dosyadaki en yakın değer −0,65 (iki günün ortalaması). Tüm kesitlerde işaret negatif, ama n = 3–7 ve p > 0,8; sıfırdan ayırt edilemez.

Gün bazı veri (dosya, form ↔ net $):

| Gün | Trader (takma ad) | Form | Net $ |
|---|---|---:|---:|
| 19.11 | T_b4c6ee | 37,89 | −0,02 |
| 19.11 | T_e7ae5a | 35,16 | −2,73 |
| 19.11 | T_574595 | 20,70 | 0,00 |
| 19.11 | T_2e4035 | 18,75 | +0,32 |
| 20.11 | T_f6b664 | 61,34 | −0,44 |
| 20.11 | T_574595 | 50,00 | +0,27 |
| 20.11 | T_b4c6ee | 43,75 | +0,23 |

## CT 20: Atlanan açılışlar (368 / 456)

Mutabakat v2 (20.11 04:05 TSİ): 456 trader açılış/artış olayı, 368 bilerek atlandı, 75 kopyalandı, 2 kaçtı, 11 takip öncesi. Etiket: düzeltme öncesi; O1/O3'ten etkilenir (haber_ters dahil).

| Filtre | Mutabakat olay | Alınsaydı kapanan (n, $) | Alınsaydı açık (n, $) | Toplam $ |
|---|---:|---|---|---:|
| hip3_atlandi | 207 | 4, −14,95 | 18, −10,70 | −25,65 |
| slot_tavani | 67 | 2, +0,68 | 17, −19,77 | −19,09 |
| ters_netlesme | 63 | 5, +0,77 | 9, +1,83 | +2,60 |
| bant_ici | 21 | yok | yok | 0 |
| min_emir_atlandi | 3 | 1, −0,02 | 2, −0,12 | −0,14 |
| spot_atlandi | 2 | 0 | 0 | 0 |
| duygu_ters | 2 | 0 | 12, +8,96 | +8,96 |
| gec_acilis | 2 | 0 | 0 | 0 |
| trader_hesap_yok | 1 | 0 | 0 | 0 |
| haber_ters (mutabakatta yok) | 0 | 0 | 2, +2,07 | +2,07 |
| Toplam | 368 | — | — | — |

Karşı-olgu sayısı (kapanan + açık) mutabakat olay sayısından küçüktür, çünkü her adres|coin için tek hayali pozisyon açılır. Sayılar alt sınırdır.

## CT 21: Slot tavanı ve sermaye kullanımı

| Kalem | Değer | Veri anı | Etiket |
|---|---|---|---|
| Slot tavanı (`slot_usd`) | 909,09 $ (10.000 / 11) | 20.11 15:44 TSİ | düzeltme öncesi |
| "1.363 $" | veride bulunmadı; bu sayı yerine `biz_slot_toplam_usd` içinde 125 emir kaydında 909 $ üstü, 10'unda 1.363 $ üstü görülüyor (en yüksek 1.387 $); ölçüm tanımı kontrol edilmeli | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| slot_tavani engeli (açılış/artırma olayı) | 5.670 olay (2.285 dakika-trader-coin) | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| slot_tavani ile kırpılan dolu emir | 26 (5 trader) | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| Kırpılan tutar | ölçülemedi: `hedef_usd` emir değil pozisyon hedefi gibi davranıyor, fark güvenilir değil | — | — |
| Ortalama kullanım (zaman ağırlıklı, emir noktaları) | 5.449 $ / 10.000 $ = %54,5; boşta ortalama 4.551 $ | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| En yüksek toplam maruziyet | 8.534 $ | 20.11 15:44 TSİ | düzeltme öncesi |

Kullanım, emir olaylarında güncellenen değerden hesaplanır; fiyat hareketiyle değişen değerler arada görünmez (yaklaşık).

## CT 22: Haftalık kadro değişimi

| Kalem | Değer | Veri anı | Etiket |
|---|---|---|---|
| Kadro değişimi (16.11–20.11) | 1 çift: 19.11 12:20 TSİ | 20.11 15:44 TSİ | düzeltme öncesi |
| Çıkan | 0xc2dd65… (neden: işlem yok); kopya emir 0; net 0 $; HL dolum 0 | 20.11 15:44 TSİ | düzeltme öncesi |
| Giren | 0xf83e8b… (neden: kor gevşetildi); kopya emir 2; net +0,27 $ (1 kapanan poz., %100); HL closedPnl − ücret +4.007 $ | 20.11 15:44 TSİ | düzeltme öncesi; O1/O3'ten etkilenir |
| Haftalık sayı | veri 4 gün; hafta bazında sayı yok | — | — |

Dönemde 11 başlangıç üyesinin 7'si "ilk gün", 4'ü "kor gevşetildi" nedeniyle girdi; bu sayılar değişim sayılmadı. "kor_kirpildi" olayı 18 kez kaydedildi (saha değişimi değil).

## Veri notları

- `kayit/*.jsonl` dosyalarında 4.352 tekrar satır vardı; tekilleştirildi (23.256 satır).
- Kapanış ücreti pano tanımına göre pozisyon net'ine dahil; açılış ücreti ayrı (Ortak 3).
- Hesap özsermayesi iki kaynakta farklı: `tur` kaydı 20.11 15:32 TSİ'de 10.002,33 $, `durum/ozet.json` 15:43 TSİ'de 9.990,05 $. Mutabakat v2'de 9.937,75 $ (04:05 TSİ).
- HL sorgusu: `userFillsByTime` (sayfa sınırı 2.000 dolumdur; en çok 1.176 dolum, sayfalama gerekmedi) ve `clearinghouseState` (anlık).
- Radar isabet verisi yalnız 05–09 Kasım'da var; sanal dönemi kapsamaz.
- O1/O3 yeniden koşusu gerektiren sayılar yukarıda etiketli.
## CT 22a: Açılış sonrası artırma/azaltma kopyalaması kazandırıyor mu?

Veri anı: 20.11 15:44 TSİ (son kayıt). Dönem: 16.11 14:30 TSİ → 20.11 15:44 TSİ. Düzeltme durumu: düzeltme öncesi (O1 azaltma çarpanı düzeltmesi 20.11 16:04 TSİ canlıda). **Bu soru O1'den etkilenir — düzeltme sonrası yeniden koşulacak.**

Tanımlar: pozisyon = (trader, coin) için boyut sıfıra inene kadar olan dolumlar (tasfiye dahil). Kapalı = 24 tam kapanış + 1 tasfiye (VVV) + 1 sıfırlanmış kalıntı (ZEC) = 26; açık = `durum/ozet.json` açık listesi = 49. Karşı-olgu: ilk açılış dolumu (aynı boyut), ara artırma/azaltmalar (kopyalanan sayı kadar, sırayla), son kapanış fiyatıyla tam kapanış; açıksa `ozet.json` mark. Ücret oranı = toplam ücret / toplam nosyonel = %0,045, her kopya dolumuna uygulanır. Tam kopya (aynı yöntem) = tüm dolumlar; gerçek = kayıttaki net K/Z.

### 1) Pozisyon başına dolum sayısı

| Dolum sayısı | Kapalı (n) | Açık (n) |
|---|---:|---:|
| 1 | 0 | 29 |
| 2–4 | 12 | 17 |
| 5–10 | 9 | 2 |
| >10 | 5 | 1 |
| Toplam | 26 | 49 |

Veri anı: 20.11 15:44 TSİ. Etiket: düzeltme öncesi; O1'den etkilenir.

### 2) Karşı-olgu: ilk açılış + tam kapanış vs tam kopya ($, komisyon dahil)

| Kalem | Kapalı (n=26) | Açık (n=49, mark) | Toplam (n=75) |
|---|---:|---:|---:|
| Tam kopya (aynı yöntem) | -30,05 | +16,76 | -13,28 |
| İlk açılış + tam kapanış | -66,61 | +38,21 | -28,40 |
| Gerçek kayıt (tam kopya, ücret dahil) | -29,99 | +20,63 | -9,36 |

Pozisyon başına (kapalı, n=26):

| Trader | Coin | Dolum | Tam kopya $ | İlk+son $ |
|---|---|---:|---:|---:|
| 0x2d29c0… | BTC | 4 | -1,39 | -0,20 |
| 0x2d29c0… | MEGA | 2 | -0,05 | -0,05 |
| 0x2d29c0… | PAXG | 2 | -0,31 | -0,31 |
| 0x2d29c0… | PURR | 3 | +10,70 | +1,79 |
| 0x2d29c0… | VVV | 2 | -15,07 | -5,73 |
| 0x2d29c0… | io:NVDA | 7 | -0,41 | -0,39 |
| 0x6a8686… | HYPE | 2 | +0,15 | +0,15 |
| 0x6a8686… | HYPE | 11 | -0,56 | +0,02 |
| 0x6d2667… | HYPE | 9 | +65,68 | +0,94 |
| 0x6d2667… | HYPE | 14 | +30,24 | +0,69 |
| 0x76c2cd… | CAKE | 10 | +2,81 | +0,60 |
| 0x76c2cd… | LIT | 2 | -0,66 | -0,66 |
| 0xc30c7e… | ETH | 4 | +0,97 | +0,15 |
| 0xc30c7e… | ETH | 2 | -0,01 | -0,01 |
| 0xc30c7e… | ZEC | 6 | -0,65 | -0,74 |
| 0xc30c7e… | ZEC | 9 | -0,07 | +0,36 |
| 0xdebd49… | BTC | 14 | -12,65 | -13,93 |
| 0xdebd49… | BTC | 8 | -15,62 | -2,54 |
| 0xdebd49… | BTC | 6 | -9,10 | -3,13 |
| 0xdebd49… | BTC | 2 | -2,72 | -2,72 |
| 0xdebd49… | ETH | 14 | -50,72 | -31,20 |
| 0xdebd49… | SOL | 5 | -12,93 | -13,27 |
| 0xdebd49… | SOL | 5 | +3,54 | +9,34 |
| 0xdebd49… | SOL | 2 | -1,41 | -1,41 |
| 0xdebd49… | SOL | 13 | -20,07 | -4,61 |
| 0xf83e8b… | XRP | 2 | +0,26 | +0,26 |

Trader başına (tüm pozisyonlar):

| Trader | Pozisyon (n) | Tam kopya $ | İlk+son $ | Fark $ |
|---|---:|---:|---:|---:|
| 0x2d29c0… | 11 | -50,54 | -6,75 | +43,79 |
| 0x3d380a… | 2 | -8,36 | -8,36 | +0,00 |
| 0x6a8686… | 16 | -20,07 | -18,24 | +1,83 |
| 0x6d2667… | 2 | +95,93 | +1,63 | -94,30 |
| 0x76c2cd… | 20 | -0,53 | -2,77 | -2,24 |
| 0x9eb42f… | 1 | -20,43 | -20,43 | +0,00 |
| 0xc30c7e… | 5 | +33,32 | +32,84 | -0,48 |
| 0xc3602c… | 6 | +72,59 | +55,88 | -16,71 |
| 0xdebd49… | 11 | -115,46 | -62,47 | +52,99 |
| 0xf83e8b… | 1 | +0,26 | +0,26 | +0,00 |

Etiket: düzeltme öncesi; O1'den etkilenir.

### 3) İlk dolum boyutu / en büyük boyut oranı ile sonuç

Oran = ilk dolum boyutu / pozisyonun ulaştığı en büyük açık boyut.

| Oran kovası | n | Ort. net K/Z $ | Toplam $ | Kapalı n | Kapalı kazanma |
|---|---:|---:|---:|---:|---:|
| <0,25 | 17 | +1,92 | +32,71 | 10 | 50% |
| 0,25–0,5 | 4 | -5,16 | -20,66 | 4 | 25% |
| 0,5–0,75 | 9 | -2,81 | -25,25 | 1 | 0% |
| >=0,75 | 45 | +0,09 | +3,84 | 11 | 18% |

Trader başına ortalama oran (artan sıra; oran < 0,25 = 'deneme ile açan'):

| Trader | Pozisyon (n) | Ort. oran | Toplam net $ | İşaret |
|---|---:|---:|---:|---|
| 0x6d2667… | 2 | 0,019 | +95,93 | deneme ile açan (oran<0,25) |
| 0x2d29c0… | 11 | 0,447 | -49,87 |  |
| 0xc30c7e… | 5 | 0,529 | +33,91 |  |
| 0xdebd49… | 11 | 0,614 | -115,31 |  |
| 0xc3602c… | 6 | 0,695 | +73,18 |  |
| 0x6a8686… | 16 | 0,834 | -19,64 |  |
| 0x76c2cd… | 20 | 0,865 | +0,05 |  |
| 0x3d380a… | 2 | 1,0 | -8,06 |  |
| 0x9eb42f… | 1 | 1,0 | -19,82 |  |
| 0xf83e8b… | 1 | 1,0 | +0,26 |  |

Etiket: düzeltme öncesi; O1'den etkilenir.

### 4) Yalnız ilk 1 ve ilk 2 ara dolum kopyalansa

İlk açılış her zaman kopyalanır; ara dolumların ilk K tanesi sırayla alınır, sonrakiler yok sayılır; son kapanış tam kopyalanır.

| Senaryo | Kapalı $ | Açık $ (mark) | Toplam $ | n |
|---|---:|---:|---:|---:|
| Tam kopya | -30,05 | +16,76 | -13,28 | 75 |
| İlk 1 ara dolum | -16,85 | +45,83 | +28,98 | 75 |
| İlk 2 ara dolum | -6,88 | +44,70 | +37,82 | 75 |
| Hiç ara dolum (ilk+son) | -66,61 | +38,21 | -28,40 | 75 |

Açık pozisyonlar mark'a bağlıdır (gerçekleşmemiş); kapalı sütun gerçekleşmiştir. Etiket: düzeltme öncesi; O1'den etkilenir.

### 5) Çok dolumlu pozisyonlar

| Grup | n | Kapalı n | Net K/Z $ (gerçek) | Kapalı kazanma |
|---|---:|---:|---:|---:|
| >5 dolum | 13 | 12 | -40,65 | 25% |
| >10 dolum | 6 | 5 | -83,29 | 20% |

Etiket: düzeltme öncesi; O1'den etkilenir.

### Komisyon payı (toplam 13,35 $)

| Dolum türü | Komisyon $ | Pay |
|---|---:|---:|
| Pozisyonun ilk açılış dolumu (75) | 4,61 | %34,5 |
| Ara artırma/azaltma dolumları (161) | 7,28 | %54,5 |
| Son kapanış dolumu (kapalı, 25) | 1,46 | %10,9 |

Etiket: düzeltme öncesi; O1'den etkilenir (ara dolumların sayısı ve boyutu azaltma çarpanına bağlı).

### Sınırlar

- Açık pozisyon sonuçları mark'a bağlıdır; kapalı sonuçlar gerçekleşmiştir.
- Karşı-olgu fiyatları kayıttaki dolum fiyatlarıdır; kayma, gecikme ve kısmi dolum modellenmedi.
- VVV tasfiyesi `tasfiye_px` ve `tasfiye` pnl'i ile; ZEC son dolumla tam kapanış sayıldı (kapanis_duzeltme kaydıyla).
- Örneklem küçük (kapalı 26); yalnız bilgi.

