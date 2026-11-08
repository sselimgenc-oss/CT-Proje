# Kullanıcı kararları (yeni dönem; eskisi `KARARLAR_D.md` T1 ile silinir)

### K‑19. Form Radarı: şimdi + gelecek; eski sistem silinir (kullanıcı, 2026-11-04)
- Strateji geçmiş performans kapısından çıkıp **son 7 günlük form + seçim sonrası ileri deneme** üzerine kurulur: `docs/RADAR_V1.md`.
- Onaylanan lider önerileri: hype = trader'ın sıcak dönemi + trend coini erken yakalama (ikisi); evren ön filtresi hesap ≥ 10.000 $,
  7 günde ≥ 10 işlem, kaldıraç ≤ 20x; günlük kayan 7 günlük pencere, tek kötü günde atma yok (art arda gün kuralı); tutma medyanı ≥ 1 saat;
  kasa zirveden −%20'de her şey durur.
- **Eski sistem** (Kapı v3, İlk 11 puanı, oda/kontrol, ön kayıt, seçim, araştırma) **tamamen silinir**; yan yana tutulmaz. Görev: `GOREV_T1`.
- Roller: **Claude (Opus) = lider/beyin**: tasarım, görev belgesi, denetim (gerçek çıktıya bakarak), birleştirme. **Sonnet = yazıcı**:
  kod, test, PR. Codex devre dışı.
- Kullanıcıda kalan: canlıya geçiş (son karar), sermaye miktarı, para/hesap/anahtar/cüzdan, sunucu. Gerçek para yasağı canlı kapısı
  (`RADAR_V1.md` §7) geçilip kullanıcı açıkça karar verene kadar sürer.

### K‑20. Cloudflare ve DigitalOcean yok; her şey GitHub Actions'ta (lider kararı, 2026-11-04)
- Kullanıcı iki hesabı da kapattı. Worker (Telegram, D1, R2) ve VPS (anlık dinleyici) **artık yok**.
- Gerekçe: ileri sanal kopya hesabı dolum zamanlarından **sonradan** yapılır (1 dk gecikme modeli), yoklama sıklığı sonucu değiştirmez →
  paper için anlık sunucu gerekmez. Günlük tarama ve 2 saatlik ileri deneme GitHub Actions'ta; durum veri dalında; Telegram (varsa) doğrudan
  Actions'tan Bot API ile.
- Anlık dinleyici kodu (`dinleyici.py`, `risk_defter.py`, `live_koruma.py`) **kalır**: canlıya geçişte gerekir. Sunucu seçimi canlı kararıyla birlikte
  kullanıcıya gelir.
- Görev: `docs/GOREV_T1B_SUNUCUSUZ.md`.

### K‑21. Deneme = canlıyla aynı motor; tek anahtarla canlıya geçiş (kullanıcı, 2026-11-04; K‑20'yi düzeltir)
- Kullanıcı: "Deneme dediğimiz şey hemen bir anda canlıya geçebileceğimiz yapı olacak."
- İleri deneme **sonradan hesap değildir**: anlık motor (`dinleyici.py` WebSocket → `risk_defter.py` sınırları → yürütücü) gerçek zamanlı çalışır.
  Yürütücü iki kipli, kod yolu aynı: `kip: kagit` → emir gönderilmez, dolum **o anki emir defterinden** (L2, bizim tutarımızla yürünen fiyat + taker)
  yazılır; `kip: canli` → aynı emir HL'ye gider. Geçiş = `kurallar.yaml` kip + anahtar (GitHub Secrets / sunucu), başka değişiklik yok.
- Kâğıt kipinde de canlıdaki her şey çalışır: kadro (İlk 11), slot kasası, risk sınırları, /dur şalteri, Telegram bildirimi, mutabakat.
- **Sunucu:** sürekli açık bir makine gerekir (canlıda zorunlu). Kullanıcı açana kadar kâğıt kipi GitHub Actions'ta **vardiyalı** koşar
  (4 saatte bir başlayan, 4 sa 15 dk süren iş; durum veri dalında; açılışta kaçan dolumlar REST'ten tamamlanır ve `gec_goruldu` işaretlenir,
  o anki fiyatla yazılır — yani dürüst). Canlı **asla** Actions'ta koşmaz; canlı = sunucu.
- K‑20'den geçerli kalan: Cloudflare Worker/D1/R2 yok; Telegram doğrudan motordan Bot API ile.
- Ön kayıtlı canlı kapısı (`RADAR_V1.md` §7) yalnız bu anlık kâğıt kipinin sonuçlarıyla değerlendirilir.

### K‑22. Denemesiz, doğrudan canlı; 100 $ kasa (kullanıcı, 2026-11-04; K‑21'in kâğıt aşamasını kaldırır)
- Kullanıcı: "Deneme yapmayacağız, direkt canlı kuracağız, 100 dolar ile deneyeceğiz."
- Kâğıt aşaması ve canlı kapısı yok. 100 $ kasa ile canlı başlanır; sahada N = 4 slot (HL 10 $ alt emir sınırı yüzünden 11'e bölünemez),
  Ayrıntı `RADAR_V1.md` §5–§7.
- Eski canlı kapısı → **büyütme kapısı** (kasaya para eklemek için; son karar kullanıcı).
- Güvenlik: HL API cüzdanı (para çekemez), anahtar yalnız sunucuda; kasa 100 $'ı aşmaz (kullanıcı kararı olmadan para eklenmez); −%20'de durur.
- Sunucu zorunlu (canlı GitHub Actions'ta koşmaz). K‑21'deki Actions vardiyası iptal; günlük radar taraması Actions'ta kalır.
- Lider görüşü (K‑17 gereği): kayıp üst sınırı 100 $ ile kabul edilebilir; gerçek dolum verisi kâğıttan değerlidir. Tek uyarı: ilk haftalar
  "sistem çalışıyor mu" sınavıdır, kâr beklentisi değil.

### K‑23. Deneme yok: gölge ve kontrol grubu da yok (kullanıcı, 2026-11-04)
- Kullanıcı: "Deneme diye bir şey yok, direkt canlı motor." Tek motor canlıdır; emirsiz izleme (gölge), kâğıt kipi, rastgele kontrol grubu kaldırıldı.
- Kadro = günlük form sırası (İlk 11 / Yedek; sıra listesi); sahadaki 4 kişi canlı sonuç + form ile kalır/düşer (`RADAR_V1.md` §5).
- Kod güvenliği için birim/altın örnek testleri ve salt okunur veri denemeleri (emir göndermeyen) sürer; bunlar işlem denemesi değildir.

### K‑24. PAF kaldırıldı: kadro = İlk 11 + Yedek 19 = 30 (kullanıcı, 2026-11-04)
- Günlük form sırası 1–11 İlk 11, 12–30 Yedek 19. PAF yok. Saha (canlı) İlk 11'in ilk N'i (100 $ → 4). `RADAR_V1.md` §5.

### K‑25. ~~Tarama her gün tam + her saat sıcak~~ (K‑26 ile kaldırıldı)
- Kullanıcı: "Her gün Hyperliquid performansı ölçelim, başarılı işlemlileri hemen değerlendirelim."
- Günde 1 tam tarama (300 aday, kadro yeniden sıralanır) + saatte 1 sıcak tarama (gün kârında ilk 50 yeni aday + kadro 30 puan güncellemesi).
  Sıcak tarama yalnız ekler/yükseltir; düşürme tam taramada (gürültüyle sahadan atılmasın). `RADAR_V1.md` §2.

### K‑26. Kasa 1.000 $; saatlik tarama kalktı (kullanıcı, 2026-11-04)
- Kasa **1.000 $** → sahada İlk 11'in **tamamı** (N = 11, slot ≈ 90,9 $; HL 10 $ alt emir sınırı sorun olmaktan çıkar). −%20 durdurma = 200 $.
- Tarama **günde bir**, her gün önceki 7 günü ölçer (kayan pencere). Saatlik sıcak tarama (K‑25) kaldırıldı.
- "Geçmiş veri yok" = uzun geçmiş (yıllık) bakılmaz; yalnız trader'ın son 7 günlük sıcak/form dönemi (kullanıcı açıklaması).

### K‑27. "trading-office" incelemesinden eklemeler (kullanıcı, 2026-11-04: "ekle hepsini")
- Dayanak: başka bir kopya sisteminin ölçümü — puan sonraki sonucu öngörmedi (rho ≈ 0), geçmiş kopya sonucu ters öngördü (−0,26); motor
  sağlamdı, sorun **trader bulmak**. Bu, 7 günlük form seçiminin ana riskidir.
- Eklenenler (`RADAR_V1.md`): R1/7 devir ≤ 100 kat; R1/8 şans süzgeci (bootstrap alt sınır > 0); §5 yer değiştirmede +10 puan farkı ve sonuç dışı
  düşüşe bekleme cezası yok; §6 patlama freni (10 dk'da ≥ 8 yeni coin → 30 dk ara); §7b seçim isabet ölçümü (rapor, emir/gölge yok) ve
  14. gün önceden kayıtlı kuralı; §8 v1.1 ağırlık öğrenme (28 gün sonra, ileri sınama kapılı, ≤ %50 harman).

### K‑28. Tek boyutlandırma: kapıdaki kopya testi canlıyla aynı boyutla (lider kararı, 2026-11-04)
- Bulgu: R1/6 kopya testi `kopya_v4` sabit tutar eğrisiyle (1.000 $ → ~20 $/işlem) oynatıyordu; canlı ise §5b (slot ≈ 90,9 $ × trader oranı) açacak.
  Test canlıdan farklı şeyi ölçerse kapı yanlış kişiyi geçirir.
- Karar: §5b tek yerde (`copytrade/boyut.py`); `kopya_v5` = v4 risk + bu boyut; R1/6 ve canlı motor aynısını kullanır. v4 silinmez (kural 6). Görev T3.

### K‑29. Canlı program önce cüzdansız (sanal kip), kullanıcı hazır olunca cüzdan (kullanıcı, 2026-11-04)
- Kullanıcı: "Motoru canlı olarak hazırlayın, ilk etapta 1.000 $ yatırmış gibi izleyeceğim; hazır hissedince cüzdanı bağlayacağım. Bu deneme/test değil,
  canlı programın demo hâli."
- Motor tek kod yolu, iki kip: `sanal` (varsayılan; dolum o anki L2 defterinden, ücret dahil) / `gercek` (API cüzdanı). Geçiş = anahtar + ayar.
- Sanal kip sunucu yokken GitHub Actions'ta vardiyalı koşabilir; gerçek kip yalnız sunucuda. Görev T4 (`GOREV_T4_CANLI_MOTOR.md` §1, §3).
- Büyütme kapısı (§7) gerçek kipe geçişten sonra sayılır; sanal dönem bilgi olarak raporlanır.

### K‑30. Kasa kullanıcı ayarı (kullanıcı, 2026-11-04)
- "İster 100, ister 250, 500, 750 kafama göre ayarlarım." Kasa sabit değil: `canli_kasa_usd` (üst sınır 1.000 $). Saha sayısı ve slot buna göre hesaplanır
  (`N = min(11, taban(kasa / 25))`). Gerçek kipte motor hesapta daha fazla para olsa da bu tutarın üstünü kullanmaz. `RADAR_V1.md` §5.

### K‑31. R0 sıralaması: hafta pnl $ yerine 7 günlük getiri (lider, 2026-11-04)
- **Neden:** ilk 300 adayın (pnl $ sırası) hesap değeri medyanı 4,7 M $ — balina / piyasa yapıcı; 300'den 198 `islem_az`, 73 `dolum_fazla`, kopya aşamasına varan yok.
  Form radarı yüzde getiriyi ölçmeli, dolar kârı değil.
- **Kural (`RADAR_V1.md` §2):** evren `accountValue − hafta pnl ≥ radar_min_hesap_usd` (hafta başı sermaye ≥ 10.000 $; yatırma şişirmesini önler), hafta `pnl > 0`,
  hafta `vlm > 0`, vault değil; sıra `trader_getiri_7g` azalan; ilk `radar_aday_tavan` (300). Diğer R1 eşikleri DEĞİŞMEZ.

### K‑32. Kopya koruma oranı: kopya / ayna (lider, 2026-11-04)
- **Neden:** T2 300 koşusunda (run 41873761070) kopya testine varan 25 adayın 19'u `kopya_koruma_dusuk`; medyan oran 0,0099. Sebep ölçü hatası:
  (1) kopya sabit küçük tutarla (v4) oynuyor, trader getirisi hesap yüzdesi — elma/armut; (2) `trader_getiri_7g` pencereden önce açılmış pozisyonların
  kârını içerir, kopya pencere başında boş başlar.
- **Kural (`RADAR_V1.md` §3/6):** aynı `son7g` dolumları `kopya_v5` ile iki kez: kopya (1 dk + maliyet) ve ayna (0 gecikme, 0 maliyet); ikisi de boş başlar,
  aynı slot. `kopya_koruma = kopya_getiri / ayna_getiri`; ayna ≤ 0 → `kopya_koruma_dusuk`. Eşik 0,50 ve `kopya_zarar` (kopya > 0) değişmez.
  `trader_getiri_7g` yalnız R0 sırası ve bilgi. Görev T3.

### K‑33. Kadro N'den küçükse boş slot nakit (lider, 2026-11-04)
- **Neden:** T3 ilk günlük koşu (#498, run 41885556829): 300 adaydan 10 geçti → kadro 10 (İlk 11'de 1 boş, Yedek boş).
- **Kural:** saha = min(N, kadro); slot `kasa / N` sabit, boş slot nakit; kadro 36 sa'ten eskiyse yeni giriş yok + alarm. `GOREV_T4` §0.

### K‑34. `radar_min_islem` 10 kalır (lider, 2026-11-04)
- **Veri (aynı gün, 300 aday, K‑32):** eşik 10 → kopya aşamasına 25, `gecti` 10 (%40). Eşik 5 (bilgi koşusu, run 41896859450) → kopya aşamasına 64,
  `gecti` 16. Ek 39 kişiden (5–9 işlem) yalnız 6'sı geçti (%15); `sans_riski` 8 → 26, `kopya_zarar` 6 → 17.
- **Karar:** eşik 10 kalır. 5–9 işlemlik grup çoğunlukla şans/zarar; az işlemde bootstrap (şans süzgeci) zayıf. Kadroyu doldurmak için kapı gevşetilmez;
  boş slot nakit (K‑33). Yeniden değerlendirme: 28 günlük canlı dönemden sonra §7b isabet ölçümüyle.

### K‑35. Slot toplam tavanı + toplam marj tavanı + tek payda (lider denetimi, 2026-11-04)
- **Bulgu:** `boyut` 3 × slot tavanını coin başına uyguluyor; trader çok coinde açarsa slotun katları kadar risk. Toplam marj kasayla sınırlı değil (sanal kip
  imkânsız pozisyon tutabilir). Motorun trader hesap paydası (ana dex) radarınkinden (lider tablosu) farklı.
- **Karar:** trader başına tüm coinler toplamı ≤ 3 × slot; toplam başlangıç marjı ≤ özsermaye; payda = tüm perp dex + spot USDC; gerçek kipte kasa = min(ayar, hesap).
  `kopya_v5` aynı kuralı uygular (R1/6 ile motor aynı). `GOREV_T4` §0b.

### K‑36. Artırma hedef tabanlı (lider, 2026-11-04; Sonnet bulgusu, `sonnet_durum_t4.md` #17)
- **Bulgu:** ilk sanal vardiya (run 41904629030), `xyz:GEV`: açılış hedefi < 11 $ → 11 $'a yuvarlandı; aynı emrin sonraki kısmi dolumu "önceki pozisyona göre
  büyük artış" göründü → 11 $ × oran = 261,73 $ (tavana dayandı). Oransal artırma, yuvarlanmış küçük açılışı ve kısmi dolum zincirini büyütüyor.
- **Karar (`RADAR_V1.md` §5b):** artırma = max(0, hedef − mevcut), hedef = slot × trader nosyonel sonra / trader hesap (3 × slot ve K‑35 tavanlı); < 11 $ atlanır.
  Azaltma ve kapanış oransal kalır. `boyut.hedef_emir` tek yer → `kopya_v5` (R1/6) ve motor aynı anda değişir (K‑28). Eski/yeni R1 sayıları yan yana (kural 6).

### K‑37. Bağımsız denetim sonrası sağlamlaştırma; gerçek kip kapısı (lider, 2026-11-05)
- **Denetim (dış ajan, 2026-11-05) doğrulanan bulgular:**
  - kapanış teyidi yok (IOC kalanı yeniden denenmiyor, DUR teyitsiz);
  - gerçek kipte risk yerel özsermayeye dayanıyor;
  - sanal kip funding'i dışlıyor (R1 dahil ediyor);
  - emir öncesi kalıcı niyet / `cloid` yok;
  - yuvarlama sonrası 10 $ kontrolü yok;
  - gecikmiş açılış 60 dk'ya kadar kopyalanıyor;
  - Telegram `from.id` ve offset denetimi yok;
  - vardiyalar tek eşzamanlılık grubunda.
  Artırma bulgusu K‑36 ile zaten çözüldü.
- **Karar:** `GOREV_T4B_SAGLAMLASTIRMA.md`. Gecikmiş açılış: yaş > 120 sn → açılış/artırma yok; kapanış her zaman.
- **Strateji kanıtı:** geçmiş lider tablosu olmadığı için geriye dönük walk‑forward kurulamaz. Örneklem dışı isabet, günlük `kadro.json` anlık kayıtlarından
  ileri dönük ölçülür (T6 ilk madde, RADAR §7b).
- **Gerçek kipe geçiş kullanıcı kararıdır** (demo → cüzdan bağla). Tek teknik şart: T4b madde 1–5 ve 7 bitmiş olmalı (para güvenliği).
  Lider önerisi ≈ 14 gün sanal; bağlayıcı değildir.
- **Denetçi önerilerinden alınanlar:**
  - T6 raporu kötü senaryoyu da verir: kayma 2×, gecikme 3 dk.
  - T6'da trader'ın pencere içi para yatırma/çekme hareketleri ölçülür (getiriyi şişiren yatırma).
  - Gerçek kip yalnız kalıcı sunucuda koşar (T5; zaten kural).
- **Alınmayanlar:**
  - 6–12 aylık geriye dönük test: geçmiş lider tablosu yok.
  - PBO / Deflated Sharpe: bu ölçekte gereksiz.
  - Varyant kayıt tablosu: K‑kararları ve `radar_deneme` koşuları zaten kayıt.
  - 30–60 gün zorunlu paper süresi: geçiş kullanıcı kararı.
  - T4b 6 (kuyruk önceliği) ve 9 (sanal defter derinliği) çıkarıldı: 11–90 $'lık emirlerde etkisi önemsiz.

### K‑38. Azaltma hedef tabanlı (lider, 2026-11-05)
- durum: **main'e girdi (PR #554, 06.11 ≈ 01:59Z)**; üretimde bir sonraki vardiyadan itibaren (≈ 05:22Z) geçerli. Temiz deneme vardiyası (run 42113249911): azaltmada toz emri 0 (eski kural 9), `min_emir_atlandi` azaltma 350 → 79, `hesap_yok` 0, `kapanis_eksik` 0. 7 günlük sayaç 01:07Z'de başladı; K-38 ilk üretim vardiyasından önceki kısa dilim eski azaltma kuralıyla koştu (sayaç açısından kayıt notu).
- **Bulgu:** küçük parçalı azaltmalar < 11 $ olduğu için atlanıyor ve kayboluyor. Bizim pozisyon trader'a göre büyük kalıyor (vardiya 42003105254: 1.535 `min_emir_atlandi`).
- **Kural:** `docs/DENETIM_PANO_2026-11-05.md` §A. `boyut.hedef_emir` `azalt`; `kopya_v5` ve motor aynı fonksiyonu kullanır; eski/yeni R1 sayıları yan yana verilir.

### K‑39. Kadro dışı düşme iki farklı UTC günü ister, bekleme yok (lider, 2026-11-05)
- **Bulgu:** aynı gün ikinci radar koşusu 3 üyeyi girişlerinden 3 saat sonra düşürdü ve 14 gün yasakladı.
- **Kural:** `docs/DENETIM_PANO_2026-11-05.md` §A. Motor gün başına ilk kadroyu uygular. Sonuçla düşme ve bekleme kuralları değişmez.

### K‑40. Pano Cloudflare Workers `sg-pano` ile gösterilir — K‑20 istisnası (lider onayı, 2026-11-05)
- Kullanıcı kendi Cloudflare hesabında `sg-pano` Workers statik sayfasını kurdu; GitHub reposuna bağlı, üretim dalı `canli-durum`, çıktı klasörü `pano`.
- **Yalnız herkese açık veri dalını okuyan salt okunur görüntü:** secret/anahtar yok, hesap/emir yok, sunucu yok. K‑20 ("Cloudflare ve DigitalOcean yok") bu istisna dışında geçerlidir; gerçek para sunucusu (T5) ayrı karardır.
- **Ek (kullanıcı onayı 2026-11-05):** Cloudflare'in kendi build sistemi bu repoda 10'dan fazla denemede takıldığı için pano yayını `canli_yayimla.sh` içinden `wrangler deploy` ile yapılır (yalnız ana dal `canli-durum`, yalnız `pano/index.html`). `CLOUDFLARE_API_TOKEN` yalnız "Workers düzenle" yetkilidir (para/emir/hesap yetkisi yok) ve yalnız GitHub Secrets'ta durur; `CLOUDFLARE_ACCOUNT_ID` aynı yerde. Test istisnası yalnız `canli_vardiya.yml` içindir; R2/AWS/wrangler iş akışı yasakları sürer. Hata yayımı durdurmaz, uyarı olarak görünür. Lider denetiminde.

### K‑41. Aynı coinde ters yönlü kopya pozisyonu açılmaz (lider, 2026-11-05 akşam)
- **Bulgu:** başka trader'dan ters pozisyon varken açılış gelirse net pozisyon küçülür; reduce‑only kapanış net pozisyonu büyütebilir (`sonnet_durum_t4b.md` #4).
- **Kural:** aynı coinde zıt yönde kopya pozisyonumuz varken gelen **açılış** atlanır (sayaç `ters_netlesme`); sanal ve gerçek kipte aynıdır (demo gerçeği yansıtsın). Pano atlanan sinyallerde gösterir.

### Lider kararları — 2026-11-05 akşam (kullanıcının "ikinci beyni")
- **Madde 0 (a–e):** hepsi ONAY (K‑40 işlendi).
- **Gerçek kip öncesi (T5'ten ÖNCE; sanalda da aynı kod, testle):** t4b #2 (kısmi/iptal dolum miktarı deftere), #3 (her dolumdan sonra `hesap.json` + `motor.json` atomik yazım: geçici dosya + fsync + rename; son uygulanan niyet kimliği `hesap.json`'da; yeniden başlatmada sonrası oynatılır; çökme testi),
  #4 (K‑41), #5 (kendi yatırma/çekme kaydı görülünce `hl_ofset` yeniden hesaplanır; HL hesabında kasa ayarı kadar para tutulursa ofset 0), #6 (kuyruk taşınca düşen olay da `poz_tr`'yi günceller), #7 (`funding_oran_yok` sayacı).
- **Telegram:** `/kapat`, `/dur` (yalnız yeni giriş durur), `/devam` ONAY. `baslat`'ta `DUR` dosyası yoksa `risk.json dur` sıfırlanır ve kayda yazılır (`DUR` dosyası tek yetkili). Vardiya başında, başlangıçtan önceki son 15 dk'da gelip düşürülen komutlara "komut vardiya arasında geldi, işlenmedi, tekrar gönder" yanıtı (komut çalıştırılmaz). `/durum` gerçek risk bayraklarını gösterir (günlük kayıp, mutabakat, `elle_dur`, fren).
- **Diğer:** HL < 10 $ reduce‑only: T5'te kullanıcı onayıyla küçük gerçek deneme; kısmi azaltma kalanı < 10 $ ise atlanır (t4b #2) ONAY. `yatirma_payi` −8,27 önemli olabilir: yöntem DEĞİŞMEZ, 7 gün ölç (her radar özetinde |yatirma_payi| > 0,2 olan aday sayısı ve kadroda olanlar), Pazartesi birlikte karar.
  `kopya_koruma` −21,7: bilgi (kapı zaten eler), kapatıldı. `non_funding_ledger` sayfalama: DÜZELT. Pano bayat `ozet.json`: 15 dk döngüde vardiya kimliği kontrolü varsa yeter, kapat. `sonnet_isci.yml` kullanılmıyorsa KALDIR.
  `copytrade-izleme` ve birleşmiş `claude/*` dallarının silinmesi ONAY ("eski sistemden hiçbir şey kalmasın"); önce liste PR'a yazılır. KORUNAN: `main`, `radar`, `radar-deneme`, `canli-durum`, `canli-durum-deneme`, `claude/stoic-carson-w3xagz`.
- **Canlıya geçiş:** 7 gün sanal ONAY; "temiz" tanımı ONAY (vardiya boşluğu yok, `kapanis_eksik` 0, KRİTİK yok; KRİTİK olursa sayaç 0'dan). Ek şart: yukarıdaki gerçek kip öncesi ve Telegram maddeleri main'de ve testli olmalı; **sayaç bunlar birleştikten sonraki ilk vardiyadan başlar**.
- **İlk gerçek kasa: 300 $** (kullanıcı kararı; lider önerisi: 11 trader sahada kalacak kadar. 275 $ alt sınır, 250 $ → N = 10). Önceki "100 $" kararı geçersiz: 100 $'da N = 4, slot 25 $, en küçük emir 11 $ → sinyallerin çoğu atlanır.
- **Paralel deneme:** 300 $'lık sanal vardiya `canli-durum-deneme` dalında koşar; üretim 1.000 $ serisi değişmez. Özet/pano: atlanan sinyal oranı (`min_emir_atlandi` / toplam sinyal) 300 $ ve 1.000 $ yan yana gösterilir.


### K‑42. Spot ve HIP‑3 dolumları kopyalanmaz; patlama freni farklı coin sayar (lider, 2026-11-05 gece)
- **Bulgu:** `docs/DENETIM_UCTAN_UCA_2026-11-05.md` Y1/B3/O1. Spot (`@N`, `A/B`) perp gibi kopyalanıyordu (05.11 kaydı: 14 emir, 276 $); HIP‑3 (`dex:COIN`) gerçek kipte emir verilemez (SDK `perp_dexs`) ama sanalda açılıyordu (37 emir, 626 $) → demo ≠ gerçek.
- **Kural:** spot ve HIP‑3 **açılış/artırma** iki kipte de atlanır (`spot_atlandi`, `hip3_atlandi`; `emir_yok`, `neden_say`, pano "Atlanan sinyaller"). Kapanış/azaltma ASLA engellenmez. HIP‑3 için tek anahtar: `kurallar.yaml canli_hip3_kopya: false` (true yalnız gerçek kipte `perp_dexs` desteği + test sonrası). `radar_*` DEĞİŞMEDİ.
- **O1:** RADAR §6 "≥ 8 yeni coin" → patlama freni FARKLI coin sayar ve yalnız gerçekten dolan açılışları (emir sonrası `Risk.yeni_coin_kaydet`); aynı coinin parçaları ve emir verilmeyen açılışlar sayılmaz. Eşik/pencere/ara değişmedi.
- **K‑42 canlıya girişi:** PR #546 birleşme zamanı = 2026-11-05T22:04:55Z (UTC ms `1793916295000`; `git log` commit 3decb05). Bu zamandan sonra üretim vardiyası yeni kodla koşar.
- **Sayaç:** 7 günlük sanal sayaç K‑42'den SONRA başlar (önceki seri HIP‑3/spot içeriyordu). Açık 3 HIP‑3 pozisyon kapanana dek seride kalır (kapanışları engellenmez).
- **Bilgi:** `ozet.json trader_atlanan` (trader başına `spot_atlandi`/`hip3_atlandi`): sahada olup yalnız HIP‑3 yapan trader görünür; alarm yok.

### K‑43. Radar R1'de HIP‑3 hariç (Opus onayı, kullanıcı adına; 06.11 gece)
- **Karar:** `radar_hip3_kopya: false` varsayılan: R1 kopya oynatmasında HIP‑3 (`dex:COIN`) dolumları oynatmadan çıkar. K‑28 TUTARLILIK DÜZELTMESİ: motor K‑42 ile zaten HIP‑3 açmıyor; eşik/ağırlık/yöntem değişmez.
- **Gerekçe (A↔B yan yana; A: HIP‑3 dahil, B: hariç):** `gecti` A 20, B 15. İlk 11'de ortak 6 / yeni 5 / düşen 5. HIP‑3 payı ≥ 0,7 olan 7 kişiden A'nın İlk 11'indeki 5'i B'de `kopya_zarar` ile düştü; A'da tam HIP‑3 olanların 0,024–0,045 getirisi motorun açamadığı pozisyonlardandı.
- **Geri alma:** tek satır `radar_hip3_kopya: true` (eski v1 davranışı). Kullanıcı onayı BEKLİYOR (sabah sunulacak; reddederse true'ya dönülür).
- **Sayaç / ilk false kadro (06.11):** radar.yml (main, elle tetik #565) kadroyu **06:34:44Z (= 1793946884000 ms UTC)** yayımladı: `gecti_sayisi` **15** (≥ 11 ✔; İlk 11 + 4 yedek); İlk 11'in `hip3_nosyonel_pay` değerleri 0–0,73 (çoğu < 0,5). K-43 kadrosu motora bu andan sonraki ilk 5 dk okumasında geçti; 7 günlük sanal doğrulama ölçümü bu kadroyu da içerir (üretim vardiyası 05:22Z'de yeni kodla başlamıştı).
- **Uyarı:** `gecti` < 11 ise radar özeti ve sağlık kontrolü UYARI verir (`kadro_11den_az`); otomatik true'ya dönülmez, lider karar verir.

## Kullanıcı onayları 06.11 (öğle)
Kullanıcı "Hepsi tamam" dedi (K-43 + K1–K8, lider önerileri olduğu gibi):
- **K-43** onaylandı (radar HIP-3 hariç; geri alma: `radar_hip3_kopya: true`).
- **K1** Actions vardiyası `TELEGRAM_KOMUT=kapali` (sunucu motoru devreye girince). **K2** gerçek durum maskeli `canli-gercek` dalına. **K3** bağımsız nabız servisi yapılacak. **K4** MetaMask + agent cüzdan (çekme yetkisiz), ilk kasa 300 $. **K5** sunucu + `/etc/sg-canli.env` (T5'te). **K6** <10 $ reduce-only küçük gerçek deneme yapılacak. **K7** hesap değeri >1.000 $ ise yeniden başlatmada ret: kasıtlı. **K8** strateji ilk 28 gün kilitli.
- **Gerçek mod yine başlamadı:** 7 temiz sanal gün (en erken 13.11), cüzdan/anahtar/sunucu adımları kullanıcıyla ve ayrı onayla.
- **Dal silme:** `copytrade-izleme` (tip 83f276cf) ve `claude/gecici-dal-sil` silinmesi onaylandı; otomatik izin denetimi silme komutunu engelledi, kullanıcı izin kuralı verene dek bekliyor.

## K-44 — Boş slot doldurma günlük değişiklik sınırına sayılmaz (lider, 06.11)
- **Karar:** `canli_gunde_degisiklik` (günde 2) YALNIZ sahadaki üyeyi değiştirmek (histerezis, `daha_iyisi_geldi`) için geçerli. Boş slot doldurma (`bos_slot`) sınıra sayılmaz ve ona takılmaz. Kor. sınırı (`canli_kor_max`), 14 gün bekleme, K-39 (iki UTC günü kadro dışı) AYNEN.
- **Gerekçe:** Lider denetimi (canli-durum, vardiya 42229578322): sahadaki 8 üyenin 7'si bugünkü kadroda yok; bugünkü İlk 11'den 10'u BEKLİYOR, 3 slot boş. Sınır doluyken boş slotlar dolmuyor, 12.11 isabet ölçümü anlamsızlaşırdı.
- **Doğrulama (birleşmeden, gerçek veriyle yerel):** bugünkü `radar/son/kadro.json` + canli-durum `saha.json` → `Saha.degerlendir`: saha 8 → **11/11**; 3 giriş, üçü `bos_slot` (sıra 2, 3, 4); sayaç `adet` değişmez. Sahadaki sıra dağılımı sonra: 1, 2, 3, 4 + 7 üye bugünkü kadroda YOK (K-39: kadro dışı, ikinci UTC günü kadroda yoksa sonuç dışı düşer; sonra İlk 11 adayları boş yerleri doldurur). Yani 11/11 olur; "İlk 11 ağırlıklı" olması K-39 gereği 1–2 gün sürer (şu an İlk 11'den 4/11).
- **Testler:** `test_gunde_en_fazla_2_degisiklik…` (3 boş slot aynı gün dolar, sayaç 0), `test_k44_gunluk_sinir_yalniz_uye_degistirmek_icin…` (değiştirme hâlâ günde ≤ 2).
- **Aynı PR (lider denetimi 06.11 maddeleri 2–4):** emir kaydına boyut girdileri (VERI_SOZLESMESI), `kor_kirpildi` yalnız durum değişince, pano: özsermaye/düşüş grafiği 15 dk `tur` noktalarıyla, kapanan işlemler kâr faktörü alt satırda, "ortanca fark (bp)" + ortalama mutlak fark.
- **Yöntem DEĞİŞMEZ:** zarar seçimden geliyor (brüt −39,07 $, maliyet −2,83 $; 38 kapanan işlem, %34 kazanma); 12.11 isabet ölçümü beklenir.

## K-45 — Boş slot sıradaki adayla dolar (Yedek dahil); eski kadro yok sayılır (lider, 06.11)
- **Karar:** Boş slot doldurma (`Saha._doldur`) kadroda sıradaki uygun adayı alır: önce İlk 11, korelasyon (r ≥ 0,7 en çok 2) ya da bekleme yüzünden alınamayan olursa **Yedek**. RADAR §6 "fazlası sıradaki üyeye yer verir" bu şekilde okunur. Histerezis değiştirme (`_degistir`) değişmez: yalnız İlk 11 adayı.
- **Ek:** Uygulanan kadrodan daha eski `kosu_ms` taşıyan kadro (CDN önbelleği) yok sayılır; günlük kurallar aynı gün iki kez çalışmaz.
- **Gerekçe:** Devir denetimi (06.11 gece): bugünkü kadroyla yarın 7 eski üye K-39'la düşer; İlk 11'den 4 aday birbirine r 0,85–0,94 bağlı olduğundan alınamaz → eski kodla saha **7/11** kalırdı (4 slot nakit).
- **Doğrulama (gerçek veri, yerel):** canli-durum `saha.json` + `radar/2026-11-06/kadro.json` (kosu +1 gün) → yeni kodla saha **11/11** (8 giriş `bos_slot`, 4 aday `kor_kirpildi`). Testler: `test_k45_bos_slot_kor_kirpilinca_yedekten_sirayla_dolar`, `test_k45_uygulanandan_eski_kadro_yok_sayilir…` (ikisi eski kodda kırılır). Tam paket 880 geçti.
- **Yöntem eşikleri DEĞİŞMEZ** (R1/R2/korelasyon eşiği aynı).

## K-45 eki — Benzerlik matrisi tüm kadroyu kapsar (lider, 08.11)
- **Hata:** `radar_kadro` korelasyon matrisini yalnız İlk 11 için yazıyordu; K-45 ile Yedek boş slota girebildiği halde matris dışında kaldığı için "ilişkisiz" sayıldı. 08.11 sahasında 3 Yedek girişi (sıra 12–14) ile **5 kişilik bağlı küme** (r 0,74–0,96; sınır 2) oluştu. Bulgu: seçim denetimi iş akışı (kadro-dinamigi, kod-sadakati mercekleri), lider gerçek veriyle doğruladı.
- **Düzeltme:** matris tüm kadro satırları için (`radar_kadro.py`). Eşik/yöntem aynı. Yarınki radar koşusundan itibaren geçerli.
- **Doğrulama:** `radar/2026-11-08/havuz.json` ile yeniden kadro → matris 14×14; bugünkü saha üyeleri arasında 7 kenar r ≥ 0,7, en büyük küme 5. Testler: `test_ilk11_yedek_19_ve_30_siniri` (matris 30), `test_k45_eki_yedekten_giris_de_korelasyon_denetimine_tabi`. Tam paket 882.
- **Açık soru (kullanıcı/lider):** mevcut fazla benzer üyeler sahadan çıkarılsın mı? Kod yalnız GİRİŞİ denetler; RADAR §6 "fazlası sıradaki üyeye yer verir" çıkarmayı da ima eder. Şimdilik doğal çıkışlarla (K-39) azalması beklenir.

## K-46 — İsabet karar kuralı yeniden kaydedildi (lider + kullanıcı onayı, 08.11; 12.11 verisi görülmeden)
- RADAR §7b'ye eklendi: ana ölçü havuz `sonraki_7g` ortalaması (maliyet sonrası) + havuz − elenen; gün bloklu bootstrap %80 güven aralığı; ≥ 21 ölçülmüş gün (≈ 02–03.12). Alt > 0 devam; üst < 0 dur; arada kasa artmaz. 19.11'de yalnız üst < 0 ise dur. IC ve (b) bilgi.
- Gerekçe: Fable seçim denetimi B6 (`docs/DENETIM_SECIM_2026-11-08.md`): n = 11–15'te 7 günlük IC ortalaması gerçek IC 0,03 iken %38 olasılıkla ≤ 0 çıkar; (b) İlk 11 havuzun %73–100'ü olduğundan ≈ 0.

## K-47 — Seçim denetimi (Fable, 08.11) sonrası plan (kullanıcı onayı 08.11)
- **Lider v1.1 önerisi geri çekildi** (7 gün tutma, kadro dışı 3 gün, haftalık değiştirme, 72 sa inen, slot %15): veri teşhisi çürüttü — çıkan 15 kişiden 0'ı geri döndü; çıkanlar −18,44 $, kalanlar −0,74 $; zorla kapanış zararının −11,8 $'ı K-42 öncesi HIP-3 kalıntısı.
- **Hemen (yöntem değişmez):** K-45 eki (birleşti, #576); R-1 isabet günün ilk kadrosu; `islem_yok` sayacı son dolumdan; `kor_kirpildi` tekilleştirme; bilgi alanları (H'siz form, çıkış nedeni); **300 $ paralel sanal motor** (`canli-durum-300`).
- **İkinci adım (Actions'ta gerçek veriyle):** R1 hesap paydası zaman bağımlı (B8, eski ↔ yeni yan yana); R1/kadro 300 $ ile yan yana; `kopya_islem_sayisi`, `yuvarlanan_pay`.
- **Gerçek para şartı (güncel):** 300 $ sanal ≥ 7 gün; G-1…G-10 kapalı; isabet havuz ortalaması belirgin negatif değil. v1.1 adayları (evren ölçüsü, nedene bağlı çıkış, yuvarlama kuralı, kopya işlem kapısı, H çıkarma, net yön tavanı) 28. günden sonra, tek tek ve çevrimdışı sınanarak.
