> Kaynak: Fable seçim denetimi iş akışı (6 mercek, 48 bulgu, 34 hakemden geçti). Lider değerlendirmesi ve uygulama planı: KARARLAR K-46, K-47.

# Seçim ve kadro denetimi: sentez (08.11.2026)

Kaynaklar: 6 mercek ve 3 hakem. Veri: origin/radar 05–08.11 (kadro + havuz) ve origin/canli-durum (saha, kayıt 05–08.11). 06.11 denetiminin maddeleri (R‑1…R‑7, G‑1…G‑11, A‑2) burada tekrarlanmıyor, üstüne konuyor. Ben de birkaç noktayı repoda kontrol ettim:
- K‑45 eki (d85c5e39) yalnız `claude/stoic-carson-w3xagz` dalında, origin/main'de yok.
- R‑1 hâlâ düzeltilmedi: `radar_isabet.py` `gun_kadro` okumuyor.
- `radar_tarama.py:378` sabit `hesap_usd` geçiriyor.

## 0. Beş cümlede

1. −42 $'ın kaynağı seçim ve 05.11'deki tek piyasa hareketi (o gün −39 $; saha 10/10 long, BTC −%3,7). Çıkış ve değişim mekaniği değil: 4 günde ücret 3,67 $, HIP‑3 dışındaki zorla kapanışlar −0,31 $.
2. v1.1 önerisi yanlış bir teşhise dayanıyor. Çıkışların nedeni form düşüşü değil: trader'ların yaklaşık yarısı haftalık ilk 300'den, yarısı da gerçek bir R1 kapısından düştü. Çıkan 15 kişiden hiçbiri İlk 11'e dönmedi.
3. v1.1'in üç maddesi pratikte etkisiz. "sıra>22" hiç tetiklenmedi (kadro en çok 15 satır). Değiştirme 4 günde 0 kez çalıştı. "Kadro dışı 3 gün" 12 çıkışın en az 9'unu değiştirmezdi.
4. En büyük açık 300 $. Ne R1 testi ne de "300 $ paralel deneme" 300 $ ile koştu; ikisi de 1.000 $'da. 1.000 $'da bile açılışların 46/58'i 11 $ tabanına yuvarlanıyor; hedefin medyanı 0,41 $, yani 27 katı şişiyor.
5. Edge için kanıt yok; aleyhine kanıt da zayıf. 12.11'deki ilk isabet ölçümü karar verisi sayılmamalı. Karar kuralı 12.11'den önce, veriyi görmeden, güven aralığıyla yeniden yazılmalı.

---

## 1. Bulgular (tekilleştirildi, önem sırasıyla)

### KRİTİK

**B1. Seçilenler "geçen haftanın en şanslıları" olabilir; ileriye bakan tek filtre kopyalanabilirlik.** Güven orta: bu bir tasarım eleştirisi, etkisi henüz ölçülmedi.
- **Sorun:**
  - R0, 3.500–6.000 hesabı 7 günlük getiriye göre sıralayıp ilk 300'ü alıyor.
  - R2 aynı 7 günü yeniden sıralıyor: form ile G arasında ρ 0,77–0,93.
  - Performansın devam edip etmediği hiçbir aşamada ölçülmüyor.
- **Kanıt:**
  - Kesim: 300. trader'ın 7g getirisi 0,372 / 0,333 / 0,307 / 0,317, yani haftada +%31–37.
  - Şans modeli: kaldıraçlı hesapta haftalık σ %25–40 alınırsa, bu eşiği 3.500 hesaptan 360–750'si yalnız şansla geçer.
  - Önceki hafta: geçenlerin kopya getirisi medyanı ~%16–20 slot/hafta. Bu tekrar etseydi kasa günde ~+%2 kazanırdı.
  - Gerçekleşen: 4 günde −%4; 05.11'den sonra yaklaşık 0 (961,06 → 961,31 $).
- **Aleyhine kanıt:** 07.11 kadrosunun 11 kişisinden 10'u 08.11'de yine geçti. İlk iki günün devri K‑43 ve K‑39 hatasıyla karışık.
- **Etki:** Kalıcılık yoksa beklenen getiri ≈ 0 eksi maliyet. Ücret yükü yaklaşık %2,8 kasa/ay (3,67 $ / 4 gün). v1.1'in tutma ve çıkış maddeleri bu kök nedene dokunmuyor.
- **Düzeltme:**
  - v1 kilitli kalsın.
  - İsabet ölçümüne kontrol grubu eklensin (B6).
  - v1.1 adayı: daha pürüzsüz bir evren ölçüsü (14–28 günlük getiri ya da "7 günün en az 3'ünde kârlı"). Kayıtlı havuzlarla çevrimdışı sınanmadan kullanılmasın.

**B2. 300 $ hiç ölçülmedi.** Güven yüksek.
- **Kanıt (kod):**
  - `kopya_v5.py:72`: kasa verilmezse `canli_kasa_usd` = 1.000 kullanılıyor; `radar_kadro.py:34` de aynı.
  - Motor gerçek kipte kasayı ortamdan alıyor (`motor.py:89–104`).
  - `deploy/kurulum.md:27` ve `VERI_SOZLESMESI.md:403` bunu açıkça yazıyor.
- **Kanıt (deneme dalı):** origin/canli-durum-deneme'de `kasa_usd` 1000, slot 90,909 $, son veri 06.11 22:21Z. K‑41'deki "300 $ paralel deneme" hiç 300 $ ile koşmadı.
- **300 $'da bugünkü kurallar:**
  - N = min(11, ⌊300/25⌋) = 11; slot 27,27 $.
  - 11 $ asgari emir slotun %40'ı.
  - 3× tavan 81,8 $: yaklaşık 7 asgari emir (1.000 $'da 24).
  - Slot −%10 = 2,73 $.
- **Etki:** "7 temiz sanal gün" kabul kanıtı 300 $ gerçek para için geçerli değil. R1'in "kopyalanabilir" dediği portföy 300 $'da başka bir portföy.
- **Düzeltme (gerçek paradan önce şart):**
  - Deneme dalı gerçekten `CANLI_KASA_USD=300` ile koşsun.
  - R1 ve kadro 300 $ ile de üretilsin, 1.000 $ ile yan yana yayımlansın.
  - `kadro.json` `kasa_usd` etkin kasadan farklıysa motor alarm versin.

**B3. Tanecik bozulması: kopya trader'ın oranında değil, "dokunduğu her coine ≈11 $".** Güven yüksek.
- **Kanıt:**
  - Boyut alanı taşıyan 15 açılışın 13'ü 11 $'a yuvarlandı. Hedefler 0,05–10,56 $; şişme medyan 27×, en çok 202×.
  - 58 açılışın 46'sı tam 11,00 $.
  - Trader hesabının %0,06–1,1'i olan bir pozisyon bizde slotun %12'si.
  - Ayna da aynı boyutlandırmayı kullandığı için `kopya_koruma` bunu göremez.
- **Tutulan nosyonel** (196 "tamam" emir ölçeklenerek; alt sınır): slot 27 $ → %29, 50 $ → %46, 68 $ → %63.
- **Not:** Atlanan artırma ve azaltmalar (`min_emir_atlandi` 5.870) kaybolmuyor; hedef tabanlı boyutlandırma bunları sonraki dolumda yakalıyor. Asıl sorun açılışların şişmesi.
- **Etki:** Trader'ın kanaat ağırlıklaması kopyada yok. R2 bileşenleri de bu bozulmuş seriden hesaplanıyor.
- **Düzeltme:**
  - Hemen, bilgi olarak (eşik değişmez): havuza `yuvarlanan_pay`, `kopya_islem_sayisi`, saf oransal bir `oransal_ayna` oynatması ve `koruma_boyut = ayna / oransal_ayna`.
  - v1.1 adayı [DOĞRULA]: "hedef ≥ 5,5 $ ise 11 $'a yuvarla, değilse açma" (şişme en çok 2×). R1 oynatmasında eski ↔ yeni yan yana sınansın.

**B4. Yedek'ten girenlerde benzerlik denetimi çalışmıyordu; düzeltme dalda, main'de değil.** Güven yüksek.
- **Kanıt:**
  - origin/main `radar_kadro.py:50` matrisi yalnız İlk 11 için yazıyor.
  - `canli/kadro.py:63` matriste olmayan çifti ilişkisiz sayıyor.
  - 08.11 07:24–25'te sıra 12–13 (form 36,5 / 29,6) girdi; aynı turda sıra 4–5 (64,6 / 52,3) `kor_kirpildi` ile engellendi.
  - Sahada 5 kişilik bağlı küme oluştu: r 0,74–0,96, sınır 2.
- **Durum:** K‑45 eki (d85c5e39) bunu düzeltiyor ama origin/main'de değil.
- **Açık kalan:** `kadro.py:63`, kadrodan düşmüş saha üyesini de (0x4b9b60) ilişkisiz sayıyor. Mevcut 5'li küme için karar verilmedi.
- **Düzeltme:**
  - K‑45 eki birleşsin.
  - Kadroda olmayan üye için korelasyon havuzdaki `kopya_gunluk`'tan hesaplansın; hesaplanamıyorsa "bilinmiyor" olarak kayda düşsün.

**B5. Devrin nedeni yanlış teşhis edildi.** Güven yüksek; R0 / R1 payı orta.
- **Çıkışların dağılımı:**
  - 15 çıkış = 12 `kadro_disi` + 3 `slot_dusus`. 12'nin 3'ü 05.11'deki K‑39 hatası.
  - Gerçek 9 `kadro_disi` çıkışın ilk "kadro dışı" gününde 5'i R1'de gerçek bir düşüşle elendi:
    - 3 `sans_riski`: alt20 +0,003…+0,010'dan −0,002…−0,0045'e indi.
    - 1 `kopya_zarar`, 1 `islem_az`.
  - Kalan 4'ü iki gün de ilk 300'ün dışındaydı.
- **Sonrası:**
  - 0/15 İlk 11'e döndü; yalnız 0x62edf4 bir gün sıra 14'te göründü.
  - Realize K/Z: çıkanlar −18,44 $, kalanlar −0,74 $.
  - Sahada kalma süresinin medyanı 37 saat.
- **Devrin çoğu açılış dönemine ait:**
  - Kadro örtüşmesi 05→06: 1/14 (K‑43 ile karışık); 06→07: 6/15; 07→08: 10/11.
  - Aynı gün 6 saat arayla yapılan iki koşu kadroyu %47 değiştirdi (Jaccard 0,53). Yani sıralamanın kendisi gürültülü.
- **Etki:** Tutma süresini uzatmak devir maliyetini "geç çıkış maliyetine" çevirir. v1.1'in 4 maddesi (7 gün, 3 gün, haftalık, 72 sa) bu teşhise dayanıyor.
- **Düzeltme:**
  - `kadro.json`'a dünkü üyelerin düşme nedeni (`eski_uye_neden`) yazılsın.
  - R1'de elenenler `katman: elendi` + neden ile eklensin.
  - Saha üyeleri her gün, R0'dan bağımsız olarak, R1'den geçirilsin (bilgi amaçlı).
  - Çıkışı nedene bağlamak v1.1 adayı [DOĞRULA].

### ÖNEMLİ

**B6. 12.11 isabet testinin (§7b) karar verecek gücü yok; (b) ölçüsü yapısal olarak ≈0.** Güven yüksek.
- **IC'nin gücü:**
  - n = 11–15 iken günlük IC'nin standart hatası 0,27–0,32.
  - 7 günün ortalamasında bu ~0,10–0,12'ye iner; ama günler çakışıyor (evren Jaccard 0,20 / 0,52 / 0,72), yani gerçek hata daha büyük.
  - Gerçek IC 0,03 olsa bile 7 günlük ortalama %38 olasılıkla ≤ 0, %24 olasılıkla ≥ 0,10 çıkar.
- **(b) ölçüsü:** İlk 11 havuzun %73–100'ü. 07.11'de `havuz_geri` boş olduğu için (b) tanım gereği 0.
- **12.11'in verisi kirli:** 05.11 havuzunu kullanıyor. O havuz K‑43 öncesi (HIP‑3 dahil). Sahaya 01:58 kadrosu uygulandı, dosyada 08:06 kadrosu var (R‑1). Üstüne K‑39 hatası.
- **Düzeltme:** Karar kuralı 12.11'den önce yeniden kaydedilsin (bkz. §5). R‑1 de 12.11'den önce düzeltilsin (06.11 planında zaten var).

**B7. Form puanı seçim yapmıyor; kadro 30 değil 11–15; dört kural ölü.** Güven yüksek.
- **Kanıt:**
  - `gecti` 14 / 15 / 11 / 14; görülen en yüksek sıra 15.
  - `canli_sira_dus` 22 ve `canli_kadro_disi_sira` 30 (`kadro.py:187,196`) tetiklenemez.
  - 26 giriş: 10 `ilk_gun`, 16 `bos_slot`, 0 değiştirme.
  - 300 kişiden elemeler: `islem_az` 176–185, `devir_yuksek` 49–63, `dolum_fazla` 15–26.
- **Etki:** Ağırlık, hype ve histerezis tartışmaları bugün sonucu değiştiremez.
- **Düzeltme:**
  - RADAR §5'e gerçek durumu anlatan not.
  - Ölü kurallar kaldırılsın ya da göreli tanımlansın ("> gecti_sayisi").
  - Havuz boyutu ↔ kapı duyarlılık tablosu hazırlansın.

**B8. R1 testinde trader hesap paydası sabit.** Mekanizma kesin; sıralamaya etkisinin yönü orta güvenle.
- **Kanıt:**
  - `radar_tarama.py:378` koşu anındaki `hesap_usd`'yi kullanıyor; canlı motor hesabı 10 dakikada bir güncelliyor.
  - Hafta başı sermayesine oran 1,33–2,91 (0x57da5c'de 2,86).
  - `radar_isabet` de aynı paydayı kullanıyor.
  - 06.11'deki R‑3 yalnız kaldıracı kapsıyordu; bu bulgu boyut ve getiri tarafı.
- **Etki:**
  - `kopya_getiri_7g`, `alt20`, `dusus` ve `kopya_gunluk` (korelasyon dahil) canlının göreceğinden farklı.
  - Hafta başındaki pozisyonlar 1,3–2,9× küçük oynatılıyor.
  - Kârını hafta sonunda yapan trader'ı öne çıkarma eğilimi olabilir (çıkarım).
- **Düzeltme:** Zaman bağımlı payda. Sonuç sayılarını değiştirdiği için PR'da eski ↔ yeni yan yana, artı altın örnek testi.

**B9. Saha ≠ kadro.** Güven orta.
- **Kanıt:**
  - Bugün İlk 11'in yalnız 7'si sahada; 4'ü r > 0,9 kümelerinde takıldı.
  - Yedek 12–14 (form 36,5 / 29,6 / 10,8) sahada.
  - 07.11 11:19'dan 08.11 04:24'e kadar saha 8/11 kaldı: ~21 saat, ~270 $ nakit.
  - Risk katmanının ürettiği `emir_yok`: 06.11'de 293, 07.11'de 200 (o gün yalnız 58 emir).
- **Korelasyon kuralı gürültü değil:** engelleyen kenarların hepsi r ≥ 0,82 (n = 8'de p < 0,01). Ama sahanın asıl ortak riskini (hep long kripto betası) yakalamıyor.
- **Düzeltme:**
  - Kadro raporuna günlük "saha simülasyonu".
  - `ozet.json`'a `risk_engel_pay`.
  - İsabete `ilk11_fiili` ve `kor_kirpildi` grupları.
  - v1.1 adayı [DOĞRULA]: portföy net yön tavanı.

**B10. H (hype) bileşeni bir piyango.** Güven yüksek.
- **Kanıt:**
  - `hype_payi` gecti'lerin %71–86'sında 0.
  - Sıfırdan farklı herhangi bir değer (0,0004 bile) form puanına +7,9…+10 ekliyor; bu histerezis eşiğine eşit.
  - H, aynı pencerenin coin hareketiyle tanımlı (`radar_form.py:91–126`).
- **Düzeltme:** Bilgi olarak "H'siz form" sütunu. v1.1 adayı: H çıkarılsın ya da sıfırlara 0 verilsin.

**B11. Histerezis 4 günde 0 kez çalıştı; `kor_kirpildi` tekilleştirmesi bozuk.** Güven yüksek.
- **Kanıt:**
  - `degisiklik.adet` hep 0.
  - `kor_kirpildi` satırı günde 36 / 216 / 22 / 753.
  - `motor.py:803–806` imzası `kalan` listesinden kuruluyor; liste her üyeye göre değiştiği için her döngüde yeniden yazılıyor. K‑44'ün kayıt tekilleştirmesi bu yolda gerilemiş.
- **Düzeltme:** İmza (aday, engelleyen küme) olsun; altın örnek testi.

**B12. Kopya işlem sayısı için kapı yok.** Güven orta.
- **Kanıt:** 0x6ba51c'nin `yayilma` değeri 0,0: tek bir kârlı kopya işlemiyle `sans_riski`'yi geçti.
- **Düzeltme:** `kopya_islem_sayisi` bilgi alanı olarak eklensin. v1.1 adayı [DOĞRULA]: "kopya kapanan işlem ≥ 5".

**B13. Zorla kapanış ve slot stop'un "maliyeti" yanlış okunuyor.** Güven orta–yüksek.
- **Zorla kapanış (`inen_24sa`):**
  - Toplam −12,10 $.
  - Bunun −11,79 $'ı iki eski HIP‑3 pozisyondan; K‑42'den sonra tekrar edemez.
  - Diğer 8 kapanış toplam −0,31 $.
  - Bekleseydik ne olurdu, ölçülmedi.
  - Bu sürede inen trader'ın 2.142 artırması ve 568 açılışı kopyalanmıyor.
  - `marj_yok` tüm vardiyalarda 0.
- **Slot stop:**
  - 3 stop toplam −32,9 $, yani zararın %78'i.
  - Ancak zararı stop değil, trader'ların kendi kapanışları gerçekleştirdi. Örnek: 0x241c'nin slotu, stop tetiklenmeden 25 sn önce zaten boşalmıştı.
  - 14 günlük ceza hiçbir adayı engellemedi; üçü de sonradan R1'i geçemedi.

### KÜÇÜK

- **B14. G>0 "şans süzgeci" zayıf.**
  - Kanıt: bootstrap alt %20 > 0 ⇔ t > 0,84. Günde 300 karşılaştırma için çok gevşek; 300'den yalnız 6–10 kişi eleniyor.
  - Düzeltme: t-istatistiği bilgi olarak yazılsın. v1.1 adayı: t ≥ 2.
- **B15. "72 sa işlem yok" sayacı girişten başlıyor** (`kadro.py:203`).
  - Etki: 0xe7795f ~1 gün geç iner.
  - Düzeltme: `giris_ms` max'tan çıkarılsın (son dolum zaten kaydediliyor); altın örnek testi.
- **B16. "Alt hesap değil" filtresi kodda yok.**
  - Kanıt: RADAR §2'de var, kod yalnız vault kontrol ediyor. Veride ana + alt hesap çifti bulunmadı. Güven düşük.
- **B17. v1.1 paketi 7 parametreyi aynı anda değiştiriyor.**
  - Kanıt: 4 günlük veri ve 3 stop olayı var; −42 $'ın −39 $'ı tek günde. Etkiler birbirinden ayrılamaz.
  - Düzeltme: mekanik düzeltmeler (v1.0.x) ile strateji değişiklikleri (v1.1) ayrılsın.

---

## 2. Liderin v1.1 önerisi: madde madde hüküm

1. **Asgari tutma 7 gün → RET.**
   - Çıkanların hiçbiri dönmedi (0/15).
   - Çıkanlar −18,44 $, kalanlar −0,74 $.
   - 9 gerçek çıkışın 5'i gerçek bir R1 düşüşüydü. Örnek: 0xd2cfee `kopya_zarar` (kendi oynatması −%0,33) iken 7 gün tutulurdu.
   - Devrin maliyeti küçük, uzun tutmanın riski büyük.
2. **Kadro dışı 2 → 3 gün → RET.**
   - 12 çıkışın 9'unu değiştirmez; 1 değişir, 2 bilinmiyor.
   - Kapıdan düşmüş yaklaşık 10 kişiyi bir gün daha taşır. Örnek: bugün 0x4b9b60 `devir_yuksek`, kasanın %26'sı onda.
   - Yerine (v1.1 adayı, DOĞRULA): çıkışı nedene bağla (bkz. §6).
3. **"sıra>22" kaldır → KABUL, ama düzeltme sayılmaz.** Hiç tetiklenmedi, etkisi 0. "kadro dışı > 30" ile birlikte temizlik olarak yapılsın.
4. **Değiştirme haftada bir → RET.**
   - Histerezis 4 günde 0 kez çalıştı.
   - Havuz günde %9–93 değişiyor; sahayı haftalık dondurmak, 7 günlük tutmayla aynı sorunu taşır.
5. **Çıkanın pozisyonu trader kapatana kadar (en geç 72 sa) → RET, şimdilik ölçülsün.**
   - −12 $'ın −11,8 $'ı HIP‑3 artığı; geri kalan kapanışlar −0,31 $.
   - 72 saat boyunca trader'ın artırma ve yön değiştirmeleri kopyalanmaz.
   - Ölçülecek: 24 → 72 sa arasındaki mark K/Z ve trader'ın kapanış fiyatı. 28. günde karar.
6. **Slot zarar %10 → %15 → RET.**
   - 3 olayda zararı trader'ın kapanışı gerçekleştirdi.
   - Sınırı yükseltmek olay başına azami kaybı 9,1 $'dan 13,6 $'a çıkarır; ölçülmüş bir faydası yok.
   - Gevşetilecekse slot tavanı 2×'e indirilsin.
7. **N = kasa/50 (300 $ → 6) → DEĞİŞTİR.**
   - Yön doğru: tutulan nosyonel %29'dan %46'ya çıkar.
   - Ama hiç sınanmadı, ve 3 × 50 $ = 150 $ ile tek trader kasanın %50'sine çıkabiliyor.
   - Nasıl: 300 $ deneme N=11 ve N=6 (slot tavanı 2×, kişi başı ≤ %33) yan yana en az 7 gün koşsun. Karar sadakat ölçüleriyle verilsin, K/Z ile değil.

---

## 3. Önerilmeyen ama kanıtın gösterdiği değişiklikler

**Hemen, hata düzeltmesi (yöntem değişmez):**
- K‑45 eki birleşsin; kadro dışı saha üyesi için de benzerlik denetimi (B4).
- R‑1 düzeltilsin (12.11'den önce).
- `kor_kirpildi` tekilleştirmesi düzeltilsin (B11).
- `islem_yok` sayacı düzeltilsin (B15).
- 300 $ deneme gerçekten 300 $ ile koşsun; R1/kadro 300 $ ile yan yana; kasa uyuşmazlık alarmı (B2).
- Zaman bağımlı payda, PR'da eski ↔ yeni yan yana (B8).

**Hemen, bilgi alanı (eşik değişmez):**
- `eski_uye_neden`, `katman: elendi`.
- `kopya_islem_sayisi`, `yuvarlanan_pay`, `oransal_ayna`, `koruma_boyut`.
- G t-istatistiği, "H'siz form".
- Saha simülasyonu, `risk_engel_pay`.
- İsabete ek gruplar: `ilk11_fiili`, `kor_kirpildi`, çıkanlar, sabit tohumlu 30 kişilik evren örneği.

**v1.1 adayları (28 günden sonra, her biri tek tek ve çevrimdışı sınanarak):**
- Pürüzsüz evren ölçüsü.
- Nedene bağlı çıkış + saha üyesinin her gün yeniden ölçülmesi.
- Yuvarlama kuralı.
- Kopya işlem sayısı kapısı.
- H'nin çıkarılması.
- Net yön tavanı.
- Havuzu büyütme: önce ilk 600–900'e ucuz kapılar, sonra oynatma.
- Ölü kuralların temizliği.

---

## 4. Yöntemin edge'i var mı?

**Kısa cevap: bilmiyoruz.** Edge için kanıt yok; aleyhine güçlü bir kanıt da yok. Tasarım şüpheci olmayı haklı çıkarıyor.

**Kanıt (aleyhine):**
- Seçim, 7 günlük getirinin en uç kuyruğundan yapılıyor; ilk 300 şanslı bir örnekten istatistiksel olarak ayrılamıyor.
- İleriye bakan tek filtre "kopyalanabilir mi" sorusu; "devam eder mi" diye soran bir filtre yok.
- Geçenlerin önceki haftası ~%16–20 slot/hafta idi, canlıda tekrarlanmadı. Ortalamaya dönüş bu tasarımda beklenen bir sonuç.

**Kanıt (lehine ya da nötr):**
- 06–08.11 arası yatay.
- −39 $'ın tamamı tek gün ve K‑42/K‑43 öncesi kodla.
- 07→08 arasında geçenlerin 10/11'i kaldı.

**Neden şimdi karar verilemez:**
- 4 gün, 38 kapanmış işlem, %34 kazanma oranı: istatistiksel olarak hiçbir yöne karar verdirmez.
- Ücret engeli ayda ~%3 kasa: brüt getiri bunu aşmalı.

**Ne zaman bilinir:** En az 21 ölçülmüş gün (yaklaşık 3 bağımsız hafta). Koşullar:
- Havuzun `sonraki_7g` ortalaması, maliyet sonrası, sıfırın üstünde.
- Havuz, elenen gruptan iyi.
- Blok-bootstrap güven aralığı ile.
- En erken 02–03.12; bu, 28 günlük kilidin bitişiyle aynı zamana denk geliyor.

**Önsel bilgi (bu veriyle kanıtlanmadı):** Lider tablosunun kuyruğundan seçen yöntemlerde kalıcı edge genellikle küçük ya da hiç yok.

---

## 5. 12.11'den önce ve sonra

**Önce (08–11.11), sırayla:**
1. Karar kuralını şimdi, veriyi görmeden yeniden kaydet:
   - En az 21 ölçülmüş gün.
   - Ana ölçüler: havuzun `sonraki_7g` ortalaması (maliyet sonrası) ve havuz − elenen farkı.
   - Blok-bootstrap (blok = gün), %80 güven aralığı.
   - Alt sınır > 0 → devam; büyütmeye aday.
   - Üst sınır < 0 → dur, tasarımı gözden geçir.
   - Arada kalırsa → kasa artmaz.
   - IC ve (b) yalnız bilgi olarak raporlansın.
2. R‑1 düzeltilsin; K‑45 eki birleşsin; `kor_kirpildi` tekilleştirmesi düzeltilsin.
3. İsabet ek grupları ve kadro bilgi alanları eklensin.
4. 300 $ deneme gerçekten 300 $ ile başlasın (N=11 ve N=6/2× yan yana). R1/kadro 300 $ ile yan yana üretilsin.
5. v1.1 kuralı uygulanmasın, gerçek para başlamasın. 0x4b9b60 K‑39 ile yarın kendiliğinden iner; ayrıca bir şey yapmaya gerek yok.

**12.11'de:**
- Bu ölçüm boru hattının çalıştığını gösteren bir kontrol; karar verisi değil.
- Sayılar akıl sağlığı açısından gözle kontrol edilsin: `sonraki_7g` aralığı, n, gruplar.

**Sonra:**
- **19.11 (7 ölçülmüş gün):** §7b kuralı nokta tahminle uygulanmasın. Yalnız "üst sınır < 0" durumunda durulsun.
- **02–03.12 (28 gün, 21 ölçülmüş gün):** v1.1 kararı verilsin. Adaylar kayıtlı havuzlarla önceden sınanmış olsun; tek tek ve yan yana sanal seriyle.

---

## 6. Önerim: olması gereken seçim ve kadro sistemi

Etiketler:
- [Hemen-hata]: hata düzeltmesi, yöntem değişmez.
- [Hemen-bilgi]: yalnız bilgi alanı, eşik değişmez.
- [v1.1-DOĞRULA]: veriyle doğrulanmadan yapılmamalı.

| Kural | Şimdi | Önerilen | Kanıt / gerekçe | Beklenen etki |
|---|---|---|---|---|
| Evren (R0) | 7g getiri, ilk 300 (+%31–37/hf) | Değişmez. Aday: 7g + "≥3 kârlı gün" ya da 14–28g [v1.1-DOĞRULA] | Şans eşiği; 6 saatte kadro %47 değişti | Daha az devir; getiriye etkisi bilinmiyor |
| Saha üyesinin yeniden ölçümü | İlk 300 dışına düşen ölçülmeden çıkar | Saha + bekleyen (≤11) her gün R1'den geçsin [Hemen-bilgi]; çıkışa bağlamak [v1.1-DOĞRULA] | 9 çıkışın 4'ü yalnız R0 kesimi | "Yok" ile "kötü" ayrılır |
| R1 eşikleri | islem ≥10, koruma ≥0,5, G>0, kopya>0 | Değişmez. Bilgi alanları [Hemen-bilgi]; kopya işlem ≥5 [v1.1-DOĞRULA] | 0x6ba51c tek kopya işlemiyle geçti; G>0 ⇔ t>0,84 | Gürültülü aday azalır |
| R1 oynatma kasası | Hep 1.000 $ | Gerçek kasa ile de, yan yana; uyuşmazlık alarmı [Hemen-hata] | `kopya_v5.py:72`; deneme 1.000 $ ile koştu | 300 $ davranışı ilk kez görülür |
| R1 hesap paydası | Koşu anı, sabit | Zaman bağımlı; eski ↔ yeni + altın örnek [Hemen-hata] | Oran 1,33–2,91 | Test = canlı |
| R2 form | 6 bileşen, H %20 | Kilitli. "H'siz form" bilgi [Hemen-bilgi]; H çıkar [v1.1-DOĞRULA] | H %71–86 sıfır; +8–10 puan | Bugün ~0 |
| Kadro boyu, sıra kuralları | "30"; sıra>22, >30 | Gerçek durum notu; ölü kurallar kaldırılsın ya da göreli olsun; `katman: elendi` | Kadro 11–15; tetik 0 | 0 (temizlik) |
| Kadro dışı çıkış | 2 UTC günü (K‑39) | Aynı. Aday: R1 sonuç kapısı → 2 gün; yalnız R0 dışı ama R1 geçiyor → kalır [v1.1-DOĞRULA] | 5/9 gerçek R1 düşüşü; 0/15 dönüş | Gereksiz çıkış azalır, kötüleşen tutulmaz |
| Asgari tutma | Yok | Yok | −18,44 $ / −0,74 $; 0 dönüş | Zarar büyümez |
| Değiştirme (histerezis) | Günde 2, +10 puan | Dokunma; v1.1'de sadeleştir | 0 başarılı değiştirme | 0 |
| Boş slot (K‑45) | İlk 11, sonra Yedek | Aynı + K‑45 eki [Hemen-hata]; Yedek yalnız form ≥ havuz medyanı [v1.1-DOĞRULA] | Form 10,8 girdi, 64,6 dışarıda | Bilinmiyor (form değeri kanıtsız) |
| Benzerlik | r ≥0,7, 8 gün, en çok 2 | Kural kalsın; kadro dışı üye için de; engellenen ↔ giren ölçülsün. Net long tavanı [v1.1-DOĞRULA] | 5'li küme; engelleyen kenarlar r ≥0,82; 05.11 10/10 long −39 $ | Yoğunlaşma riski düşer |
| Slot stop | −%10, 14 gün ceza | Aynı; stop sonrası 24/72 sa toparlanma ölçülsün | Zararı trader'ın kapanışı gerçekleştirdi | 0 |
| İnen pozisyon | 24 sa | Aynı; 24→72 sa mark K/Z ölçülsün | HIP‑3 dışı −0,31 $ | 0 |
| İşlem yok 72 sa | Girişten başlar | Trader'ın son dolumundan [Hemen-hata] | `kadro.py:203` | ~1 gün daha az boş koltuk |
| Asgari emir | Hedef <11 $ → 11 $ | Aynı; `oransal_ayna` bilgi; hedef ≥5,5 → 11, değilse açma [v1.1-DOĞRULA] | 46/58 açılış 11 $; 27× şişme | Kopya trader'a benzer |
| Kayıt | `kor_kirpildi` 753 satır/gün | Tekilleştirme [Hemen-hata] | `motor.py:803–806` | Denetim okunur |
| İsabet kuralı | 7 gün, nokta tahmin | ≥21 gün, %80 güven aralığı, kontrol grupları; 12.11'den önce kaydedilsin | Günlük SE 0,27–0,32; (b) ≈0 | Yazı-tura kararı önlenir |
| N ve slot tavanı (300 $) | N=11, slot 27,3 $, 3× | N=11 ile N=6/2× deneme yan yana ≥7 gün [v1.1-DOĞRULA] | Tutulan nosyonel %29 / %46 | Sadakat ↑, çeşitlilik ↓ |

**300 $ için not:**
- **Bugünkü kurallarla 300 $:**
  - Slot 27,27 $; 11 $ = slotun %40'ı.
  - Tavan 81,8 $; slot stop 2,73 $.
  - Günlük −%5 = 15 $; zirveden −%20 = 60 $. Tasarlanan en büyük kayıp ~60 $.
- Bu boyutlandırma ancak ~550 $'dan itibaren makul çalışıyor (N=11, slot 50 $).
- Edge kanıtı olmadan 300 $ gerçek para, aslında bir yürütme denemesi.
- **Başlamadan önce gerekenler:**
  - 300 $ deneme en az 7 gün gerçekten 300 $ ile koşmuş olsun.
  - R1/kadro 300 $ ile yan yana üretilmiş olsun.
  - 06.11'deki G‑1…G‑10 kapanmış olsun.
  - İsabette havuz ortalaması belirgin şekilde negatif olmasın.

**Veriyle doğrulanmadan yapılmaması gerekenler:**
- Evren ölçüsünün değişmesi.
- Nedene bağlı çıkış.
- Yuvarlama kuralı.
- Kopya işlem kapısı.
- H'nin çıkarılması.
- Net yön tavanı.
- Yedek form tabanı.
- 300 $ için N/tavan seçimi.
- Stop ve inen pozisyon süresinde herhangi bir değişiklik.

---

## 7. Çürütülenler (neden düştü)

1. **"72 sa soğuyor kuralı kasa ölçeğinde 24× gevşek"**: oran 24× değil 2,2×. Kural kimseyi işaretlemedi; önerilen düzeltme de işaretlemezdi. Ölü kural olarak B7'ye katıldı.
2. **"N=kasa/50 emirlerin %82'sini 11 $ altına iter"**: hedef tabanlı boyutlandırma atlanan artırmayı sonra yakalıyor; açılışlar atlanmıyor, yuvarlanıyor.
3. **"Slot −%10 ile R1 düşüşü 11× ölçek uyumsuz"**: `kopya_dusus` yalnız sıralama bileşeni; ölçek farkı sıralamayı değiştirmez. Tahmin veride tutmadı: 0xfbd234 %16,8 test düşüşüne rağmen kesilmedi.
4. **"−42 $'ın bir kısmı altyapı (157 dk boşluk)"**: HYPE zararı canlıda ve piyasa kaynaklı; geç kapanışın maliyeti 1 $'ın altında.
5. **"Zorla kapanış maliyeti seçimde görünmez"**: HIP‑3 dışındaki 8 kapanış toplam −0,31 $; K‑42'den sonra tekrar edemez.
6. **"`kopya_koruma` iki küçük sayının oranı, devri sürüklüyor"**: sayılar şişirilmişti; gerçek eleme 9 kişi, günde ~2. Devirle bağı gösterilemedi. Ücret %0,045, varsayımla aynı.
7. **"Slot %15 ve N kasa/50" (kadro-dinamiği merceği)**: karşılaştırma tabanı yanlıştı; 300 $'da N zaten 11, slot 27 $ (90,9 $ değil).
8. **"K‑45 korelasyonu atlıyor" (kod-sadakati merceği)**: dalda zaten düzeltilmiş (d85c5e39); tekrar.
9. **"72 sa oynatması 0,0 yazınca kural geçiyor"**: sözleşmede belgeli; boş kopyanın getirisi 0 doğru.
10. **"−42 $'ın %70'i slot stop'tan"**: zararı trader'ların kendi kapanışları gerçekleştirdi; stop yalnız etiket ve boş slot ekledi.
11. **"14 gün ceza 7 günlük pencereden uzun"**: ceza hiçbir adayı engellemedi; asimetri iddiası R‑5'in tekrarı.
12. **"Eşit slot volatiliteyi yok sayıyor"**: durdurulanlar orta volatiliteliydi; en oynak ikisi durdurulmadı.
13. **"8 noktalık korelasyon gürültü" (şeytanın avukatı)**: engelleyen kenarlar r ≥ 0,82 (p < 0,01); 15/91 çift ≥ 0,7, şansla beklenen ~4,5. Önerilen "≥20 gün" kuralı hiç bağlamazdı.
14. **"Üyelerin üçte biri hiç emir üretmiyor"**: sıfır emirli üyeler gerçekten işlem yapmamıştı; `min_emir_atlandi` kayıtları yok.

Dosyalar:
- /home/user/sg-arge/docs/RADAR_V1.md
- /home/user/sg-arge/docs/KARARLAR.md
- /home/user/sg-arge/docs/DENETIM_DEVIR_2026-11-06.md
- /home/user/sg-arge/copytrade/radar_tarama.py
- /home/user/sg-arge/copytrade/radar_kadro.py
- /home/user/sg-arge/copytrade/radar_isabet.py
- /home/user/sg-arge/copytrade/kopya_v5.py
- /home/user/sg-arge/copytrade/canli/kadro.py
- /home/user/sg-arge/copytrade/canli/motor.py
- /home/user/sg-arge/copytrade/boyut.py