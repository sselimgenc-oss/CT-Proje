# D yolu — kullanıcı kararı bekleyen konular (2026-10-28, lider)

**Karar (kullanıcı, 2026-10-28): K1–K11'de lider önerilerinin hepsi onaylandı.** Sayısal değerler `docs/ONKAYIT_D.md`'de dondurulur.

Her madde: ne, neden önemli, seçenekler, lider önerisi.
Görev: `docs/GOREV_D_YOLU.md`.

## Hemen gerekenler (iş bunlarsız başlamaz)

### K1. Faz 0: Sonnet'in kapı dalı `main`'e alınsın mı?
- **Ne:** `claude/kapi-v1-1` dalında düzeltilmiş kapı, kopya defteri (`defter.py`), altın örnek testleri, akıl sağlığı kapısı var. PR'ı yok.
- **Neden:** gölge motoru bu defterin üstüne kurulacak; trader seçimini yeniden yapmak için düzeltilmiş kapıyla tam koşu gerekiyor.
- **Seçenekler:** (a) lider denetler, PR açar, birleştirir, tam koşuyu başlatır; (b) dal bırakılır, gölge motoru sıfırdan yazılır.
- **Öneri:** (a). Sıfırdan yazmak, aynı hataları yeniden yapmak demek.
- **Verilmezse:** hiçbir faz başlamaz.

### K2. Arşiv şimdi, paralel başlasın mı?
- **Ne:** leaderboard fotoğrafı, dolumlar, funding, 1 dk mumlar, olaylar bugünden kaydedilir.
- **Neden:** Hyperliquid geçmişi sınırlı veriyor (dolumda son ~10.000, 1 saatlik mumda ~200 gün). Kaydedilmeyen gün geri gelmez.
- **Seçenekler:** (a) Faz 0 ile paralel; (b) sırası gelince (Faz 2 civarı, birkaç hafta sonra).
- **Öneri:** (a). Arşiv yalnız veri toplar, başka işi etkilemez; "bir iş bitmeden diğeri yok" kuralına tek istisna.
- **Verilmezse:** her gün veri kaybı; 3 ay sonraki analiz o kadar eksik olur.

### K3. Arşiv nerede dursun?
- **Seçenekler:**
  - (a) **Cloudflare R2:** ücretsiz katman yaklaşık 10 GB (doğrulanacak), okuması kolay. Kullanıcı R2 alanı açar, anahtarı GitHub Secrets'a koyar.
  - (b) **GitHub Release dosyaları:** yeni hesap yok; analiz için indirmek zahmetli, dosya başı boyut sınırı var.
  - (c) Git veri dalı: önerilmez, repo şişer.
- **Öneri:** (a).

## Ön kayıttan önce gerekenler (Faz 1)

### K4. Durdurma kriterleri
- **Ne:** hangi sonuçta "olmadı" deyip duracağımız; sonuç görülmeden yazılır.
- **Öneri:**
  1. Geçmiş provada pencerelerin yarısından fazlasında seçilen grup rastgele grubu geçemezse canlı gölgeye başlanmaz.
  2. Hiçbir grup gecikme ve maliyet sonrası kâr etmezse "bu yöntemle Hyperliquid copy trade işe yaramıyor" sonucu sunulur;
     araştırmayı kapatmak geçerli sonuçtur.
- **Neden:** önceden yazılmazsa sonuç kötü çıkınca "biraz daha bekleyelim" denir; eski kapının yaşadığı sorun.

### K5. Canlı gölge süresi ve analiz tarihi
- **Öneri:** en az 12 hafta; performansa yalnız o tarihte bakılır, arada yalnız veri kalitesi.
- **Bilinmesi gereken:** 12 haftada yalnız büyük farklar görünür; "belirsiz" sonucu olası. Uzatma gerekirse kuralı şimdiden yazılır
  (ör. belirsizse 12 hafta daha, bir kez).

### K6. Kat büyüklükleri ve terfi kuralları
- **Ne:** havuz (hepsi gölgede) → aday → oda.
- **Öneri:** aday = havuzun %15'i; oda = 10–20; terfi için en az 3 hafta ve 10 kapanmış işlem gölgede; odadan çıkış için puanın
  aday katının alt yarısına düşmesi (gidip gelmeyi önler).

### K7. Kopya kuralı varyantlarının sayıları
  teminatın −%50'si zarar kesme, süreye bağlı daralma swing için 7 / 14 gün.
- **Not:** hepsi aynı sinyallerde paralel gölge; kazananı veri seçer.

### K8. Tarama altyapısı ve havuz büyüklüğü
- **Ne:** havuzun tamamını gölgede izlemek 250–300 adresi sürekli taramak demek.
- **Seçenekler:** (a) Worker ücretsiz, adresler sırayla (her adres birkaç dakikada bir; 30 dk / 2 sa gecikme modeline yeter);
  (b) Worker ücretli plan (aylık ücret); (c) havuzu ~50 adresle sınırlamak.
- **Öneri:** (a) ile başla; Faz 2'de Hyperliquid istek sınırları doğrulanınca yetmezse (b).

### K9. İş dağılımı
- **Öneri:** Faz 0 ve denetim lider; arşiv tek ajan; Faz 2–3 (gölge motoru + geçmiş prova) tek ajan, tek dal. Sonnet kapıyı
  bildiği için Faz 2–3'e uygun; Codex izleme/Worker'ı bildiği için arşiv ve tarama altyapısına uygun.

## Sonraki kararlar

- **Öneri:** ilk canlı gölge verisi gelince (Faz 4). O zamana kadar panoda sade durum tablosu. Her karakter gerçek bir modüle bağlı.

### K11. Otomatik emir (uzun vade)
- **Durum:** `AGENTS.md` gereği emir ve gerçek para yok. Bu ancak D yolu olumlu sonuç verirse ve kullanıcı açıkça isterse konuşulur.

### K‑5. Maliyet (kullanıcı kararı 2026-10-29: "tamam")
- Ana karar maliyeti tek oran kalır (taker %0,045 + kayma %0,05); pilot süresince değişmez (ön kayıt bütünlüğü).
- Coin sınıfı (büyük / küçük / HIP‑3 büyüme / HIP‑3 standart) ve seans ayrımlı maliyet yalnız duyarlılık raporunda, bilgi amaçlı.
  Dayanak: Argon A20 (doğrulanmamış derleme; HIP‑3'te yön coin ve saate bağlı).

### K‑7. Canlıya geçiş tarihi (kullanıcı kararı 2026-10-30: "tamam yaz")
- **En geç 31.12.2026** gerçek parayla canlı işlem başlar; tutar küçük (100–1.000 $, kullanıcı belirler), kazansa da kaybetse de.
  **Kanıt şartı yok** (sonuç beklenmez; "öğrenme bedeli"). K11'in "D yolu olumlu sonuç verirse" şartı bu kararla kalkar.
- Hedef **otomatik işlem** (kullanıcı: manuel takip pratik değil). **Güvenlik şartları pazarlık dışı:** para çekme yetkisi olmayan
  Hyperliquid API (agent) anahtarı, ayrı alt hesap; işlem başına / günlük / toplam zarar limiti ve en yüksek kaldıraç; Telegram'dan
  tek tuşla durdurma (/dur); saatlik mutabakat, uyumsuzlukta otomatik duruş; her emir kayıtlı; en az 2 hafta "canlı fiyatla gölge"
  (emir göndermeden) aşaması.
- Takvim: Kasım 1–2. hf veri doğruluğu ve düzenli birikim; Kasım 3–4. hf bot (emir modülü önce yalnız kayıt, limitler, /dur,
  mutabakat); Aralık 1–2. hf canlı fiyatla gölge; Aralık 3. hf hesap kurulumu ve kullanıcı son onayı; en geç 31.12 canlı.
- `AGENTS.md`'deki "emir ve gerçek para yok" kuralı bot görevi başlayana dek geçerli; bot görevi ayrı görev belgesiyle ve kullanıcı
  onayıyla açılır. Anahtarlar yalnız GitHub/Cloudflare secret'ında; repo herkese açık.

### K‑7a. Canlı tarih öne alındı (kullanıcı kararı 2026-10-30: "yeni plan 1 Aralık canlı")
- K‑7'deki tarih **1.12.2026** olur; diğer her şey (küçük tutar, kanıt şartı yok, güvenlik şartları) aynen geçerli.
- Takvim (sıkıştırılmış; veri ve bot paralel yürür):
  - **Hf 1 (30.10–6.11):** veri düzeltmeleri `GOREV_VERI_DUZELTME.md` (1–11, 13, 14) + kalıcılık yeniden koşu. Bot aşama 1 başlar (`GOREV_BOT.md`).
  - **Hf 2 (7.11–14.11):** bot aşama 1 biter (emir göndermeyen karar+kayıt, limitler, /dur, mutabakat). Sol veri denetimi tekrar.
    Canlı oda seçimi (kullanıcı kararı; kalıcılık sonucu + pilot verisi).
  - **Hf 3–4 (15.11–28.11):** canlı fiyatla gölge, en az 14 gün (güvenlik şartı; kısaltılmaz).
  - **29–30.11:** alt hesap, para çekme yetkisi olmayan API anahtarı (secret), tutar; kullanıcının son onayı.
  - **1.12:** canlı.
- Faz 3 (madde 12) artık zorunlu değil; zaman kalırsa önbellek + ön eleme ile, önce küçük deneme. Kalıcılık testi öncelikli.
- `AGENTS.md` "emir yok" kuralı aşama 1–2 boyunca geçerli (bot emir göndermez); gerçek emir yalnız kullanıcının 30.11 onayıyla açılır.

### K‑8. İleriye dönük ölçümle seçim (kullanıcı kararı 2026-10-30: "tamam yapalım")
- Seçim havuzunun (v1.3, 185) liste dışı üyeleri `havuz` kolunda **sessiz** izlenir (Telegram yok); t0 = ekleme günü. Sıra sha256(adres)
  (sonuca bakmayan, sabit). İlk adım 30 trader (koşu süresi denemesi), sonra tamamı.
- 1.12 canlı odası için ileri sanal kopya verisi **eleme** ölçütüdür, sıralama değil (kısa dönem kazananı kovalama tuzağı): kopyada maliyet
  sonrası zarar etmemiş, kırmızı/kaldıraç ihlali yok, yeterli işlem; eşikler canlı oda seçiminden ÖNCE `kurallar.yaml`'a yazılır.
  Elemeyi geçenler arasında sıralama kapı puanıyla (kalıcılık testi hangi puanın daha iyi olduğunu gösterirse o).
- Oda, kontrol, referans kolları ve ön kayıt analizi değişmez.

### K‑7b. Canlı tarihi iptal (kullanıcı kararı 2026-10-30: "Kasımda bitecek planı iptal et, süresi yok, eski yönteme devam")
- K‑7 ve K‑7a'daki **tarih** (31.12 / 1.12) ve sıkıştırılmış takvim kalkar; canlıya geçiş için sabit süre yok.
- Eski yöntem sürer: canlı gölge pilotu ve veri biriktirme, önce veri doğruluğu (`GOREV_VERI_DUZELTME.md`), kalıcılık; canlı kararı
  ileride kullanıcı verir. K‑7'deki güvenlik şartları (para çekme yetkisi olmayan anahtar, limitler, /dur, ≥14 gün canlı fiyatla gölge)
  canlıya ne zaman geçilirse geçilsin geçerli kalır. `GOREV_BOT.md` askıda (öncelik veri). K‑8 (havuz kolu, ileri ölçüm) sürer.

### K‑9. Birleşik derin denetim düzeltmeleri (kullanıcı kararı 2026-10-30: "iletelim onayım var")
- Kaynak: `docs/DENETIM_TRADER_2026-10-30.md` (lider) + Codex `DERIN_COPYTRADE_DENETIM_2026-10-30` (Sol). Görev: `GOREV_VERI_DUZELTME.md` 15–25.
- Kopya hesap düzeltmeleri (tek motor, tasfiye, zamanla değişen payda, funding) **v2 hesap sürümü** olarak eklenir; v1 seri silinmez,
  yeniden yazılmaz, yan yana yayımlanır. Ön kayıt analizi v1 üzerinde de raporlanır (sapma şeffaf).
- Yeni kol `gecikme5` (5 dk gecikmeli sanal kopya, oda üyeleriyle aynı adresler, paralel; Telegram yok) ve oda brüt kaldıraç tavanı
  yalnız **tanısal**: ön kayıtlı birincil analiz değişmez; eşikler kod değişmeden önce `kurallar.yaml`'a yazılır.

### K‑10. Sadeleştirme ve dondurma (kullanıcı kararı 2026-10-30: "yap")
- `AGENTS.md` kural 4–8: yeni özellik dondurması, strateji kilidi, hesap değişikliği yan yana (v2), her iş tek yerde, tek yazar/tek denetçi.
- Plan: `GOREV_VERI_DUZELTME.md` "Sadeleştirme" (S1–S5). Ayrı büyük yeniden yazım yok; mevcut maddelerin içinde yapılır.
- K‑8 havuz genişletmesi (30 → +30, motor ≈ 60 dk) dondurma bitene kadar bekler; 91 trader'da motor adımı 45 dk.

- Yürütme: Sonnet tek lider ve birleştirme yetkili; Codex (Sol) denetçi.

### K‑12. İlk 11 seçimi ve veri hattı önceliği (kullanıcı kararı 2026-11-02: lider önerileri onaylandı)
- **Pano yok (şimdilik).** Öncelik: motor + İlk 11 / Yedek 11 / PAF seçiminin sorunsuz oturması + canlı veri akışı. Pano sonra.
- **Uygunluk:** CT-Kapı `katman` = `izleme_adayi` veya `kopyalanabilir` olanlar (~91) kadroya aday olabilir.
- **İlk sıralama İlk 11 puanıyla** (`copytrade/ilk11.py`, 10 alan), yalnız 10 alanın hepsi gerçek veriyle dolduktan sonra.
  `ILK11_KADRO_V1.md`'deki "kapı sıralamasına göre" ifadesi bu kararla geçersiz (belge düzeltildi).
- 2026-11-01 acil leaderboard-only kadro **geçici**dir; gerçek Pazar kadrosu gelince tamamen kaldırılır.
- **Haftalık form puanı** = aynı 10 alanlı puan, son 30 günün verisiyle her Pazar yeniden hesaplanır.
- Strateji kilidi (kural 5) sürer: ağırlıklar, 60/40, 11/11/28, terfi kapısı değişmez. Tanımlar ve açık sorular (K‑12.1–K‑12.11):
  `docs/ILK11_SECIM_SARTNAME.md` §7.
- **K‑12.1–K‑12.11: önerilen seçeneklerin tümü onaylandı (kullanıcı 2026-11-02). Kullanıcının vurgusu: önce verinin doğru gelmesi ve
  kalıcı kaydı.**
  - K‑12.1 `golge` (ilk seçim): kapının tarz gecikmeli kopya neti (`secim.puan`); formda v3 `kapanan_islemler`.
  - K‑12.2 `tutarli`: pozitif gün oranı, 30 gün, payda PnL'i değişen günler.
  - K‑12.3 `kaldirac`: efektif kaldıraç, dönüşüm aynen. Not: kaldıraç dönüşümü ilk kadroda aynen kalır; adaylar 0,03–2,87x olduğundan
    dönüşüm bu aralıkta yüksek kaldıraca daha yüksek puan veriyor — ilk gerçek kadrodan sonra etkisi raporlanır, değişiklik ayrı kullanıcı kararıdır.
  - K‑12.4 İlk seçim penceresi (kazanma/sıklık/tutma/kaldıraç): kapı penceresi 365 gün.
  - K‑12.5 Form yüzdelik evreni: kadronun 50 kişisi.
  - K‑12.6 Kadro boşluğu: her Pazar uygun adaylardan İlk 11 puanıyla en iyisi boş PAF yerine girer.
  - K‑12.7 Pazar planı: otomatik uygulanır (PAPER); geri alma `gecis.py` kaydıyla.
  - K‑12.8 İzleme kapsamı: kadro 50 + `referans_oda`/`referans_kontrol`; eski pilot kolları (taban, elle, havuz vb.) saatlik izlemeden çıkar;
    geçmiş veri dalda kalır, silinmez.
  - K‑12.9 Az aday: uygun < 11 → yayın yok; 11–49 → uyarılı yayın.
  - K‑12.10 Veri kalitesi parametreleri (`ilk11_*`: tazelik 7 gün / 120 dk, form ≥ 8/10 alan, doluluk ≥ %90, akıl sağlığı aralıkları, ihlal > %5 → kırmızı): olduğu gibi.
  - K‑12.11 Kapıya 5 bilgi sütunu (adım/eşik değişmez; veri bir kez çekilir): onaylandı.

### K‑13. Telegram / Cloudflare Worker ertelendi (kullanıcı kararı 2026-11-02: lider önerisi kabul)
- Telegram/Cloudflare Worker ertelendi. Trader seçimi ve veri akışı Worker'a bağlı değildir; Worker canlı veri akışı oturduktan sonra
  yeniden bağlanır.
- Şu an GitHub'da `CLOUDFLARE_API_TOKEN` (ve muhtemelen diğer Worker secret'ları) yok; `worker.yml` dağıtımı "Gerekli secret'ları doğrula"
  adımında kırmızı biter — bu beklenen durumdur. Canlıdaki eski Worker sürümü dokunulmadan kalır.

### K‑15. Faz 2 işlem panosu ve otonom yürütme (kullanıcı kararı 2026-11-02)
- Faz 2'de kullanıcı dostu işlem panosu yapılır: telefonda ve PC'de çalışan statik HTML; içerik ve düzen `docs/FAZ2_PANO.md`
  (örnek ekran `docs/img/pano_ornek_2026-11-02.webp`). Sıra değişmez: önce Faz 1 (veri, trader seçimi, motor) tamamlanır.
- Lider, kullanıcının önemli kararları (para/cüzdan/anahtar, canlıya geçiş, eşik/strateji kilidi, silme) dışında Faz 2 ve Faz 3 işlerini
  kullanıcıdan tetik beklemeden sürdürür; model kullanım sınırına takılınca sınır açıldığında kaldığı yerden devam eder.
