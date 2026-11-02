# Ön kayıt — D yolu (2026-10-28; kullanıcı onaylı, K1–K11)

Bu belge gölge verisi görülmeden yazıldı. Değişiklik yalnız kullanıcı kararıyla, yeni sürüm olarak (eski sürüm silinmez).
Sayılar uygulamada yalnız `copytrade/kurallar.yaml`'dan okunur; bu belge ↔ yaml uygunluk testi zorunlu.
**Dondurma:** Faz 3 başlamadan önce lider bu dosyanın commit hash'ini `DURUM.md`'ye yazar.

## Katlar
- Havuz: ön elemeyi (veri yeterliliği, tarz, kaldıraç, hesap değeri tabanı) geçen adreslerin tamamı; hepsi gölgede.
- Aday: gölge puanına göre havuzun en iyi %15'i.
- Oda: aday katından en iyi 10–20 adres.
- Terfi: gölgede en az 3 hafta ve 10 kapanmış işlem. Odadan çıkış: puan aday katının alt yarısına düşerse.
- Etiketlenen adres hiçbir kayıttan silinmez; pasifleşirse sıfır getirili gün olarak paydada kalır.

## Kollar
- Kohort: oda (ikincil: aday katı).
- Kontrol: havuzdan puana bakmadan rastgele, oda ile aynı sayıda; tohum her etiketleme için `tarih` + sabit tohum, kayda geçer.
- Taban: leaderboard 30 günlük PnL ilk N (N = oda sayısı).
- Elle liste: `copytrade/izleme_listesi.yaml`.
- Elle kopya: Telegram [Açtım]/[Atladım].

## Kopya kuralı varyantları (aynı sinyaller, paralel gölge)
- V0 birebir (tarz gecikmesi: intraday 30 dk, swing 120 dk).
- V1 fiyat bandı: giriş, trader girişinden intraday ≤ %1, swing ≤ %2 uzaksa; atlananlar ayrıca izlenir.
- V2 zarar/süre çıkışı (sayılar kullanıcı onayı 2026-10-28, **dondu**). Teminat = gölgenin o işleme ayırdığı para.
  - Intraday: teminatın −%50'si zararda çık.
  - Swing: 0–7. gün zarar −%50, kâr sınırı yok; 7. günden sonra −%30 / +%60; 14. günden sonra −%20 / +%40.
- Gölge pozisyon üst sınırı (tüm varyantlar, **dondu**): tek pozisyonun büyüklüğü o trader'a ayrılan gölge parasının en çok 3 katı;
  aşan ekleme kırpılır, olay `kirpildi` diye kaydedilir.

## Ölçüm
- Birincil: eşit ağırlıklı, sabit sermayeli kohort ve kontrol portföylerinin günlük net getiri farkı (V0).
- Belirsizlik: haftalık blok bootstrap, %95; ikincil: trader kümesi bootstrap, BTC betası düzeltilmiş fark.
- Başarı: fark alt sınırı > 0 **ve** kohortun maliyet sonrası mutlak getirisi > 0.
- Canlı gölge: en az 12 hafta; performansa yalnız analiz tarihinde bakılır, arada yalnız veri kalitesi. Belirsizse bir kez
  12 hafta uzatılır.

## Durdurma
1. Faz 3 (geçmiş prova) pencerelerinin yarısından fazlasında kohort kontrolü geçemiyorsa canlı gölge başlamaz.
2. Hiçbir kol gecikme ve maliyet sonrası > 0 değilse "bu yöntemle işe yaramıyor" sonucu sunulur.

## Sürüm 1.1 (2026-10-28, kullanıcı onayı)
- Sıra değişti: canlı izleme, düzeltilmiş kapının tam koşusundan çıkan **Seçim v1** ile hemen başlar (`docs/GOREV_SECIM_V1.md`);
  Faz 3 geçmiş prova paralel yürür. Durdurma 1 aynen geçerli: prova geçemezse canlı izleme durdurulur.
- Seçim v1 başlangıç etiketidir (gölge motoru yokken puan = kapının tarz gecikmeli kopya getirisi). Gölge motoru gelince katlar
  ön kayıttaki terfi/çıkış kurallarıyla haftalık güncellenir; v1 etiketleri silinmez.

## Sürüm 1.2 (2026-10-28, kullanıcı onayı)
- V2'deki "teminat" = gölgenin o trader için ayırdığı sermayenin tamamı (1 birim). Her açık pozisyonun K/Z'si bu birime
  oranlanır ve her saatlik mumda denetlenir. Neden: işlem başı teminat (trader'ın pozisyon kaldıracı) dolum kayıtlarında yok;
  geçmiş prova ile canlı gölge aynı kuralla ölçülsün. Eşik sayıları değişmedi.
- Faz 3 evreni: geçmiş leaderboard kaynağı yok (Dune ücretli); bugünkü leaderboard kullanılır, sonuç "iyimser üst sınır".

## Sürüm 1.3 (2026-10-29, kullanıcı yetki devri: "sen karar ver")
Gölge verisi henüz yok; değişiklikler veri görülmeden yapıldı. Gerekçe: beş bağımsız denetim (`docs/DENETIM_GENEL_2026-10-29.md` ve
Argon raporları) — seçim kapının risk adımlarını atlıyor, kontrol odayla örtüşüyor, 12 hafta oda↔kontrol farkı için güçsüz.
Yeni sayılar `kurallar.yaml`'a girer; aşağıdaki sayılar ilk değerlerdir.

**Rol:** Canlı gölge bir rotasyon sistemidir; ilk seçimin doğru olması beklenmez. İlk 12 hafta *pilot*tur: amaç seçim kuralının
havuz genelinde ileri getiriyi taşıyıp taşımadığını öğrenmek ve yapıyı sınamaktır. Gerçek paraya geçiş ayrı karar ve ayrı fazdır.

1. **Havuz:** adım 1 ve 2 Geçti, tarz intraday/swing **ve** adım 3'ün statik koşulları: kısa işlem payı ≤ `kisa_islem_payi_max`,
   medyan kaldıraç ≤ `kapi_max_medyan_kaldirac`, en yüksek kaldıraç ≤ `kapi_max_kaldirac`. (Ön kayıttaki "kaldıraç ön elemesi" artık uygulanır.)
2. **Kontrol:** odayla ayrık (havuz − oda). Dilim = tarz × en yüksek kaldıraç (havuz medyanının altı/üstü). Her oda üyesi için aynı
   dilimden bir kontrol, puana bakmadan, `sha256(secim-<sürüm>-<kapı tarihi>-<adres>)` sırasıyla. Dilim boşsa aynı tarzın diğer dilimi.
   Havuzun oda dışı tamamı **ikincil kontrol**dür. Tohum kapı koşusunun tarihine bağlıdır (seçim yeniden koşsa da aynı kontrol).
3. **Seçim kimliği ve rotasyon:** Her seçim bir sürümdür (`secim_surumu`, kapı tarihi, kod ve kurallar hash'i). Yayımlanan sürümün
   üzerine yazılmaz. Oda giriş/çıkışları tarih, sürüm ve nedenle geçiş kaydına yazılır, silinmez. Kohort ölçümü **ITT**: her sürümün
   odası, etiket gününden itibaren tüm günleriyle izlenir (sonradan çıkan dahil). Odadan çıkış için en az 2 ardışık haftalık değerlendirme.
4. **Ölçüm hiyerarşisi:**
   - **Birincil:** havuzun tamamında seçim puanı ↔ sonraki 12 haftanın maliyet sonrası net getirisi, Spearman ρ (tek yönlü).
   - **İkincil:** oda ↔ eşleştirilmiş kontrol günlük farkı, **BTC betası düzeltilmiş**; haftalık (7 gün) blok bootstrap %95.
     Not: küçük örneklemde MBB aralığı iyimserdir (kapama ~%83); tablolarda belirtilir.
   - **Tanımlayıcı (karar dışı):** ham fark, V1/V2, taban, elle, aday katı, rejim kırılımı, kırpılmış (her trader'ın dönem getirisi
     %5–%95 winsorize) fark, intraday için 2× maliyet duyarlılığı.
5. **Üç sonuç** (12. hafta; belirsizse bir kez 24. hafta):
   - **İşe yarıyor:** birincil ρ > 0 ve p < 0,05, ikincil fark nokta tahmini > 0, oda maliyet sonrası mutlak getirisi > 0.
   - **İşe yaramıyor:** birincil ρ'nun iki yönlü %90 güven aralığı üst sınırı < 0,10 (pratik eşik δρ = 0,10).
   - **Sınanamadı:** diğer her durum. 24. haftada da sınanamadıysa "bu ölçekte sınanamadı" yazılır; rotasyon sürer, sonuç gerçek
     paraya geçiş kanıtı sayılmaz.
   Her analiz raporu saptanabilir en küçük farkı (MDE) ve varsayımlarını yazar.
6. **Ara bakış:** Performansa yalnız 12. ve 24. haftada bakılır. 4. haftada yalnız σ ve trader arası ρ ölçülüp MDE güncellenir
   (performans değil). Haftalık geri bildirim raporu (puan ↔ ileri getiri) **rotasyon içindir**, karar analizi değildir; kol
   bazında getiri farkı haftalık raporda yer almaz (körlük).
7. **Kenar durumlar:** oda < 10 ("kisa") ise seçim yine başlar; ikincil fark tanımlayıcıya düşer, birincil etkilenmez. Bir haftada
   oda veya kontrol dolum/işaret eksikliği > %5 ise o hafta "veri eksik" işaretlenir ve raporda ayrıca gösterilir.
8. **Faz 3** (geçmiş prova, bugünkü leaderboard → iyimser üst sınır) yalnız **durdurabilir**; başlatma kanıtı sayılmaz.
9. **Dondurma:** Bu sürümün commit hash'i ve ilk v1.3 seçiminin kimliği `DURUM.md`'ye yazılır. Birincil ve ikincil analiz kodu
   altın örnekleriyle gölge verisi görülmeden yazılır ve aynı dondurmaya girer.

## Sürüm 1.4 (2026-10-29, kullanıcı onayı: "sıkıntı yaşamazsak okeyim")
Gölge verisi henüz yok. Gerekçe: Argon A18 (odadan çıkarma kuralları; Goyal & Wahal 2008 — kısa dönem performansa göre
çıkarma ortalamaya dönüş yüzünden zarar ettirir; risk disiplini bozulması ise beklemeden ele alınmalı). Birincil/ikincil analiz
(ITT) değişmez: odadan çıkan da etiket gününden itibaren analizde kalır. Değişen yalnız kimin kopyalandığıdır.

1. **Performansa dayalı çıkış (v1.3 madde 3'ün yerine):** Odadaki bir trader ancak şu üçü birlikte sağlanırsa çıkar:
   - etiket gününden bu yana en az `secim_cikis_min_hafta` (4) haftalık değerlendirme ve en az `secim_cikis_min_kapanmis_islem`
     (60) kapanmış işlem;
   - **histerezis:** havuz puan sırasında alt `secim_cikis_havuz_alt_dilim` (0,50) dilimine düşmüş olması (giriş: tarz başına
     pozitif puanlıların ilk %15'i — çıkış eşiği girişten belirgin biçimde düşük);
   - bu durumun `secim_cikis_ardisik_hafta` (2) ardışık haftalık değerlendirmede sürmesi.
2. **Risk işaretleri (yalnız bilgi, otomatik çıkış yok):** Haftalık raporda oda üyesi için işaretlenir:
   - kaldıraç sıçraması: son haftanın en yüksek kaldıracı, etiket anındaki medyan kaldıracın `risk_kaldirac_sicrama_kat` (2,5) katını aşarsa;
   - martingale başlangıcı: `bayrak_katlama_orani` etiket anındakinden yüksek ve son haftada ≥ 1 zararda katlama;
   - zarardaki pozisyonu uzun tutma: zarardaki açık pozisyonun yaşı, trader'ın medyan tutma süresinin `risk_tutma_anomali_kat` (3) katını aşarsa.
   Bu işaretler performans içermez (körlükle uyumlu). Bir işaretin çıkışa dönüşmesi ayrı kullanıcı kararıdır.
3. Karantina/sermaye kesintisi, tarz kayması tespiti ve günlük kayıp soğuması gerçek işlem fazına bırakıldı (`docs/FIKIRLER.md`).

## Sürüm 1.5 (2026-10-29, kullanıcı kararı: "Evet diyorum başlayalım")
Pilotun ilk günü; gölge sonucu henüz görülmedi. Gerekçe (kullanıcı): proje haftalarca yolda gelişecek; trader kararları kullanıcıda
olmalı, 12 hafta beklemek kabul görmüyor.

   performans konisini yeniden kullanır (`saglik_performans_konisi: true`). Madde 6'daki "performansa yalnız 12./24. haftada bakılır"
   ve K‑6 (c) kuralı kaldırıldı.
2. **Oda kullanıcı kararıyla her an değişebilir.** Her değişiklik yeni seçim sürümü ya da tarih + gerekçeli geçiş kaydıyla yapılır
   (`gecis.py` kaydı; silme yok). v1.4 çıkış kuralı otomatik öneri olarak kalır; son karar kullanıcıda.
3. **Sabit referans kolu.** Seçim v1.3 odası (18) ve eşleştirilmiş kontrolü (18), oda sonradan değişse de 2026-10-29'dan itibaren
   değiştirilmeden izlenir (`referans_oda`, `referans_kontrol`). "Kararlarım değer kattı mı?" = yönetilen oda ↔ sabit referans oda.
4. **Analiz.** 12. hafta (2027-01-21) birincil/ikincil hesabı yine yapılır ama artık "kör test" değildir; raporda bu yazılır.
   Ara bakışlar serbesttir.

## Sürüm 1.6 (2026-10-29, kullanıcı kararı: "evet"; dayanak `arastirma/fikir_gorusleri/OZET.md`)
Altı dış görüşün ortak uyarısı: gerekçesiz, kâra bakarak trader değiştirmek veri gözetlemedir. 1.5'teki değiştirme hakkı
korunur; ölçülebilir olması için kayıt kuralı eklenir.

1. **Gerekçe kodu zorunlu.** Her oda değişikliği (çıkış/giriş) `gecis.py` kaydına şu kodlardan biriyle yazılır:
   `kaldirac_ihlali`, `tarz_kaymasi`, `hareketsizlik`, `veri_sorunu`, `anti_martingale`, `otomatik_kural` (v1.4 çıkış önerisi),
   `kullanici_takdiri`. Kâr/zarar ayrı bir kod değildir; kullanıcı sezgisiyle yapılan değişiklik `kullanici_takdiri` olarak işaretlenir
   ve ayrıca raporlanır ("takdirle yapılan değişiklikler değer kattı mı?").
2. **Değişiklik tavanı.** Kayan `degisim_tavan_gun` (28) gün içinde en çok `degisim_tavan_adet` (2) çıkış. `kaldirac_ihlali` ve
   `veri_sorunu` tavana sayılmaz.
3. **Çıkarılan izlenir.** Odadan çıkan trader `cikarilan_izleme_gun` (56) gün `cikarilan` kolunda sessizce izlenir (bildirim yok).
   "Değişim alfası" = giren − çıkan (aynı tarihlerden itibaren, sanal kopya getirisi); trader ve gerekçe kodu bazında raporlanır.
4. Sabit referans kolu (1.5 madde 3), analiz tarihi ve Faz 3 değişmez.
