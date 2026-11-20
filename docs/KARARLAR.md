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

## K-48 — Proje denetimi (Fable, 08.11) sonrası gerçek para ön koşulları
- `docs/DENETIM_PROJE_2026-11-08.md`: yeni zorunlu maddeler **G-12…G-24** (kritik: G-12 sessiz donma/zaman aşımsız emir, G-13 tasfiye sonrası ters reduce-only, G-14 bayat trader pozisyonu ezmesi; G-1'in kurtarma yolu hiç çalışmıyor). Açılış kontrol listesi ve Telegram metin önerileri belgede.
- **Hüküm:** sanal ölçüm motoru olarak sağlam; gerçek para yürütücüsü olarak henüz hazır değil. Gerçek para öncesi: G-1…G-6, G-9, G-12…G-23 main'de ve testli; G-8/G-23 + dış nabız (G-10); 300 $ seri (G-24) sonucu kullanıcıya sunulmuş; 7 temiz sanal gün.
- **12.11'den önce:** S-4 (pano maliyet/kapanan işlemler yalnız 2 günü okuyor).
- **Not (kullanıcı kararı #577):** Actions'ta Telegram kapalıyken sanal motor ölürse alarm yok; tek iz pano "VERİ BAYAT". Lider günlük gözetimle izler.

## K-49 — Yeni dönem: 09.11 00:01 TSİ (2026-11-08T21:01Z) sıfırdan başlangıç (kullanıcı kararı 08.11)
- Tüm denetim düzeltmeleriyle temiz ölçüm. `copytrade/canli/DONEM` = başlangıç; `.github/scripts/donem_geri.sh`: bu andan önce başlayan vardiya bekler (≤ 230 dk; motor süresi kalan bütçeye iner); veri dalındaki dönem farklıysa durum/kayıt/pano YÜKLENMEZ (saha, pozisyonlar, bekleme cezaları, K-39 gün sayaçları sıfır). `canli_yayimla.sh` yeni dönemin ilk yayımında eski dosyaları dal ucundan siler; **git geçmişinde arşivli kalır** (geri dönülebilir).
- Yalnız `canli-durum` (1.000 $). **300 $ paralel seri iptal** (kullanıcı 08.11: "bir tane olsun, 1.000 $"; `canli_vardiya_300.yml` silindi, `--sanal-kasa-usd` bayrağı kodda kalır). 7 temiz gün sayacı ve isabet/canlı karşılaştırması bu dönemden başlar.

## K-50 — Gerçek para da 1.000 $ ile başlar; G-24 kapandı (kullanıcı kararı 08.11)
- Kullanıcı: "gerçek paraya da 1.000 USD ile geçeriz". Gerçek kasa = sanal kasa = 1.000 $ (K-22/K-26 üst sınırı). Sanal seri ile aynı boyut rejimi → 300 $ paralel ölçüm (G-24) gereksiz; K-47 "300 $ sanal ≥ 7 gün" şartı yerine **1.000 $ sanal ≥ 7 temiz gün** (K-49 döneminden).
- Diğer gerçek para ön koşulları (K-48) aynen: G-1…G-6, G-9, G-12…G-23 main'de ve testli; G-8 + dış nabız (G-10) kullanıcıyla; açılış listesi `deploy/ACILIS_KONTROL.md`. Geçiş kararı yine kullanıcının.

## K-51 — Fable denetimleri kapanışı (lider, 08.11)
- **Main'de ve testli (#573–#587):** G-1…G-6, G-9, G-11…G-23 (G-24 K-50 ile düştü); S-1…S-22 (S-6 bilinçli tasarım: para yalnız köprüyle, açılış listesinde); M-1…M-3; R-1, R-2, R-6, R-7; seçim B4, B6/B9 (isabet ek grupları), B8, B11, B12/B3 (bilgi), B14 (bilgi), B15; A-2.
- **Kullanıcıyla kapandı:** G-7 (Telegram açık, 08.11), G-8 (`main-koruma` ruleset, 08.11), G-10 (dış nabız `sg-nabiz`).
- **Açık:** S-23 (gerçek HL yanıt kaydı → ilk gerçek deneme), S-24 dışı test hijyeni yok; A-1 (Cloudflare token kapsamı, kullanıcı); B1/B7/B10/B13/B16/B17 ve G t ≥ 2 v1.1 adayları → 28. gün, tek tek, kayıtlı havuzlarla çevrimdışı sınanarak (K-47).
- **Doğrulama kanıtı:** B8 300 aday gerçek koşu (gecti 15 → 16, 3 açıklanabilir fark); G-23/S-20 dal vardiyası (dönem beklemesi → 74 dk, yayımlar sorunsuz); yeni dönem 21:01Z temiz başladı (donem.txt, eski dosyalar dal ucundan silindi, 347 coin maxLeverage).

## K-52 — Dış denetim (3 tur, 09.11) ve temizlik (kullanıcı onayı 09.11)
- **Tur 1 (#591):** radar.yml G-23 (yazma yalnız radar işinde, persist-credentials false, YAYIM_TOKEN yalnız yayım adımında; dal denemesi başarılı); kullanılmayan 5 paket çıkarıldı (websockets açıkça eklendi); ölü deneme kodu silindi; CI'da ruff (F + E9); README.
- **Tur 2 (#591):** gerçek kipte HL değer tavanı kasa sınırından ayrı (`canli_hl_deger_ust_usd` 1.500 $; kasa ≤ 1.000 $ aynen); Telegram grup chat yetkisi; açıklanamayan HL sıçraması → mutabakat + alarm (DUR bir okuma ertelenir); bekçi nabzı kapanış döngüsünde; mutabakat yeniden okuma; `calis()` entegrasyon testi; `canli_kadro_repo` CT-Proje.
- **Tur 3 (#592):** yarım DUR yeniden başlatmada kapanır + alarm (Y-1); belirsiz emirde bant merdiveni durur (Y-2); `sg-nabiz` kaynağı ayarlanabilir, gerçek kipte gerçek yayım hedefine bağlanması açılış ön koşulu (Y-3); hesap adresine bağlı kilit + yabancı açık emir denetimi (Y-5); yüksek fiyatlı coinlerde limit yuvarlama (Y-7); iki mutasyon boşluğu testlendi.
- **Temizlik (#590, #593):** 40 eski `claude/*` dalı ve 5 eski deneme iş akışı silindi; FAZ3 kalıntı modülleri silindi; ana dal koruması (`main-koruma`); Pages kapalı; Cloudflare token yalnız Workers Scripts Edit + Account Settings Read; issue #1 kapatıldı. 300 $ arşiv dalları tek seferlik iş akışıyla silinecek.
- **Ertelenen:** motor.py bölme (28. gün sonrası), v1.1 adayları (02–03.12), S-23 (ilk gerçek deneme).

## K-53 — Seçim kuralları v1.1: tek seferde, kalıcı (kullanıcı kararı 09.11; Fable 5.1 yüksek görüşü)
- Kullanıcı: "bu trader seçimi ve değiştirilmesini düşünelim ve bir kez yapalım, 14/28 günle uğraşamayız". RADAR §8 28 gün kilidi kullanıcı kararıyla bu sürüm için kaldırıldı; v1.1 kurulduktan sonra yeniden kilitli (yalnız hata düzeltmesi serbest).
- **Teşhis (Fable, 49 kişi-gün):** geçmiş getiri/form ileri getiriyi tahmin etmiyor (Spearman −0,10…−0,17; seçilenler önce +2,26 $/gün → sonra −0,07 $/gün). İlke: sıralama ağırlıklarıyla uğraşma; kuralları geç/kal kapısı yap; boş koltuk nakitte kalabilir.
- **Kurulan (`radar_surum: v1.1`, kadro.json'a yazılır):** S1 `radar_ay_pnl_pozitif` (lider tablosu 30 g pnl > 0; pencere yoksa geçer) · S2 `radar_min_kopya_islem: 10` (`kopya_islem_az`, `sans_riski`'den önce; ≥10 +0,1 $ / <10 −1,6 $) · S4 `radar_agirlik_h: 0` (diğer dördü /0,80) · D1 `radar_tutma_onceki_kadro` (önceki kadro üyesi R0 dışına düşse de R1'den geçer; geçen kalır — R0 dışı çıkanlar +1,7 $, R1'den kalanlar −2,5 $). radar.yml tarama adımına `--onceki-kadro`.
- **Reddedilen:** t ≥ 2 önceliği (taslak; kişi başı −1,2 $, avantaj boş koltuktan), 14–28 g sıralama, ≥3 kârlı gün, net yön tavanı, N=6/2×, Yedek form tabanı. Yuvarlama (B3) ayrı karar: kalıcılık testinden sonra.
- **Aynen:** K-39 kadro dışı 2 gün, histerezis, K-45 boş slot → nakit, benzerlik, slot stop, 72 sa, inen 24 sa.
- **Yeni dönem yok:** saha K-39 ile 1–2 günde v1.1 kadrosuna uyar; 7 temiz gün sayacı (yürütme sağlamlığı) sıfırlanmaz. Doğrulama: geriye dönük 8 haftalık kalıcılık testi (ayrı iş, salt okur) + K-46 isabet serisi.
- Kanıt: `copytrade/v11_sinama.py` koşusu 42626202353 (4 kadro günü); testler `tests/test_v11_kurallar.py`.

## K-56 — Sadık boyutlama (bulgu düzeltmesi; denetim B3, 09.11)
- Açılışların %79–86'sı 11 $'a yuvarlanıyordu → slot 200 $ (`radar_canli_slot_min_usd`); açılış hedefi < 5,5 $ ise açılmaz, [5,5; 11) → 11 $ (`radar_min_emir_yuvarla_alt`, `boyut.hedef_emir`); slot tavanı 1,5×. Motor risk: slot stop %20. Günlük −%5 ve zirveden −%20 kasa kilidi.

## K-58 — Codex denetimi (F01–F16), Fable doğrulaması: öncelikli düzeltmeler (kullanıcı: "Fable'ın dediklerini yap", 10.11)
- Fable: 16 bulgunun 14'ü gerçek, 2'si şüphe, yanlış yok; Codex'in "yüksek" derecelerinin 10'u orta/düşüğe indi.
- **F10 (yapıldı):** açılış/artırmada trader hesap önbelleği `canli_hesap_azami_yas_sn` (1.800 sn = 3 × okuma aralığı) eskiyse yeniden okunur; okunamazsa açılmaz (bayat paydayla büyük emir yok). Azaltma eski değerle sürer.
- **F01 (yapıldı):** kalıcılık testinin hükmü "devam" yerine "pozitif/negatif fark (teşhis, kanıt değil)"; özete ileri bakış yanlılığı uyarısı (aday evreni bugünden geriye kurulu).
- **F11 (yapıldı, B4):** iki adres de benzerlik matrisinde ama r ölçülemedi (None) → benzer sayılır (temkinli).
- **F14 (yapıldı):** seçim taramasında ön filtre / ölçülen / portfolio hatası (türüne göre) / bütçe dışı sayaçları `havuz.json` `tarama`'ya yazılır.
- **Fable ek gözlemi (yapıldı):** motorun üretim D+ boyutuyla (5 × 200 $, 5,5 $ eşiği, tavan 1,5×) uçtan uca altın örnek testi (`tests/test_dplus.py`).
- **Küçük beşli (yapıldı, kullanıcı: "sonraya bırakmak için geçerli mazeretin var mı" → başla):** F09 yeni UTC gününün tabanı önceki günün son gözlenen özsermayesi (`son_oz`, kalıcı); F02 payda serisi ilk noktadan önce 0 = ölçülemez (açılış atlanır, gelecek değer yok); F07 sanal funding'de oran okunamayan saat, sınırdaki pozisyon görüntüsüyle hesaplanır; F12 v1.1 sınamasında eksik trader'lı gün kıyas dışı ve özette görünür; F15 bootstrap altın örnek.
- **Büyük üçlü (Codex'e verilecek, lider denetler):** F08 (D+ kadrosunu tek portföy olarak oynatma; coin/marj/slot tavanı), F04 + F06 (oynatmada haftalık likidite ve fundingHistory), F05 (oynatma ↔ sanal kip mutabakat raporu). Canlı motor ve eşikler dokunulmaz.
- Gerekmeyen: F03 (bilerek kötümser), F13/F16 (şüphe; somut etki yok). Codex'in 10 geliştirme önerisi doğrulanmadı; bilgi olarak.

## K-62 — Dengeli risk eki: günlük sert fren, felaket stopu, sığ coin tavanı (kullanıcı: "dengeli olsun, çok temkinli değil", 11.11)
- Kullanıcı kararı (11.11): canlıya geçiş istatistiksel kanıt beklemez, 2027'den önce küçük kasayla canlı; riskler biliniyor. Risk tarafı "dengeli": yalnız felaket senaryoları kapatılır, getiriyi kısan ek temkin yok.
- Fable (iki tur; ikinci turda yön tavanı, −%3/−%6 kademesi ve yarım boyut "fazla temkin" diye geri çekildi). Uygulanan:
  1. **Günlük sert fren** (`canli_gunluk_kapat_oran` 0,10): gün başından −%10 → tüm pozisyonlar kapanır, o gün açılış yok; DUR değil, ertesi UTC günü normal. −%5 açılış durdurma (`canli_gunluk_kayip_oran`) aynen.
  2. **Felaket stopu** (`canli_felaket_stop_oran` 0,20): pozisyon ortalama girişten %20 aleyhe → o pozisyon kapanır, trader sahada kalır. Şimdilik motor içi (yazılım); **borsada duran tetik emri gerçek para ön koşulu** (`deploy/ACILIS_KONTROL.md`), HL testnet'te denenecek.
  3. **Sığ coin tavanı** (`canli_sig_hacim_usd` 20 M $ 24 sa hacim; `canli_sig_coin_tavan_usd` 150 $): sığ coinde trader başına kopya pozisyonu ≤ 150 $; majörde 1,5 × slot (300 $). Hacim `metaAndAssetCtxs` `dayNtlVlm`, saatte bir; hiç okunamazsa sınır uygulanmaz, listede olmayan coin sığ sayılır.
- Değişmeyen: zirveden −%20 DUR, slot −%20 düşme, coin %30 tavanı, brüt 1.500 $, kasa ≤ 1.000 $. Yarım boyutla başlama kullanıcı kararına bırakıldı (Fable: isteğe bağlı, 1 hafta yeter).
- Test: `tests/test_k62_risk.py`.

## K-64 — Borsada duran felaket stopu (gerçek kip; K-62'nin borsa tarafı, 11.11)
- Hyperliquid hesabında coin başına tek net pozisyon olduğundan stop coin'in NET pozisyonuna konur: baskın yöndeki yerel pozisyonların ağırlıklı girişinden `canli_borsa_stop_oran` (0,22) aleyhe, reduce-only, piyasa tetikli (`tpsl: sl`), cloid öneki `0x5354`.
- Motor ayaktayken K-62 yazılım stopu (%20) önce keser; borsa stopu süreç/bağlantı/sunucu çökmesine karşı yedek. Eşitleme dakikalık (`canli_borsa_stop_sn` 60): miktar > %2 / tetik > %0,5 / yön değişince ÖNCE yeni stop, SONRA eski iptal; pozisyon yoksa iptal; net < 10 $ ise stop yok; iptali başarısız stop kalıcı listede yeniden denenir; süreç başında önekli ama bilinmeyen (yetim) stop iptal edilir.
- Açık emirlerde kaybolan stop (tetiklendi) + yerel pozisyon varsa: alarm + `_kapat_coin` (borsa 0 → G-13 harici kapanış ile defter düzeltmesi). Y-5 yabancı emir denetimi önekli stopları bizim sayar. DUR sonrası stoplar iptal edilir.
- `copytrade/canli/stop_deneme.py`: yalnız `HL_AG=testnet` ile çalışan 7 adımlı deneme (aç → stop → görüldü → yenile → iptal → kapat → borsa 0). Gerçek motor `HL_AG` ayarlıysa başlamaz.
- Testler: `tests/test_k64_borsa_stop.py`, `tests/test_canli_g6.py::test_k64_main_hl_ag_ayarliysa_gercek_motor_baslamaz`; test borsası (`BorsaSim`) tetik emri/iptal/openOrders destekler.
- Gerçek paradan önce kalan: testnet denemesinin "HEPSİ GEÇTİ" çıktısı (kullanıcının testnet cüzdanı ile).

## K-65 — Veri ve ölçüm düzeltmeleri, acil kapatma (11–14.11)
- **Veri (hata düzeltmesi, `veri_surum: 2`):** pnl yalnız PERP (`perpAllTime` + `perpMonth` + `perpWeek` birleşik; ince dönem ortak en yeni noktada allTime seviyesine oturtulur); hesap değeri toplam seriden (allTime + month + week). En yeni pnl noktası `secim_veri_azami_yas_saat` (24) saatten eski aday `veri_bayat`. Kopya kapısına gelen aday ve üyede hesap değeri motor tanımıyla da okunur (`canli/motor.py` `hesap_degeri_oku`: tüm perp dex accountValue + spot USDC); |seri/motor − 1| > `secim_payda_azami_fark` (0,02) ise motor değeri kullanılır (`payda_duzeltildi`, oynatma paydası ölçeklenir; aday reddedilmez). `veri_surum` 1 kadrosundaki üyenin giriş/zirve pnl'i perp seriden yeniden kurulur (`veri_gocu`).
- **Acil durumda otomatik kapatma (uygulama, gerçek kip):** borsa stopu beklenen coin `canli_borsa_stop_korumasiz_sn` (7.200 sn = 2 sa) borsada stopsuz kalırsa (koyma reddi/hata) motor o coindeki pozisyonları kendisi kapatır (`borsa_stop_korumasiz`), Telegram alarmı verir ve `canli_borsa_stop_ceza_sn` (6 sa) yeni açılış/artırma yapmaz (`stop_korumasiz` bayrağı; kapanış serbest). Süre ve ceza `borsa_stop.json`'da saklanır (yeniden başlatmada sürer). Test: `tests/test_k64_borsa_stop.py::test_k65_*`.
- **Fable denetimi düzeltmeleri (13.11 kullanıcı kararı "hataları düzeltelim, pano verilerini de"):** (1) **Payda çift sayımı** (K-65 hatası): HL birleşik hesapta (`userAbstraction` = `unifiedAccount`) perp marjı spot USDC `hold` içinde; `hesap_degeri_oku` artık perp + USDC `total` − `hold` (0x8abc 13.11: 43.351 $; eski formül 86.662 $), portföy marjında (`portfolioMargin`, USDC borçlu olabilir) HL `portfolio` gün serisinin son değeri, klasikte K-35 tanımı aynen. Motor boyutları ve radar `payda_duzeltildi` (kapıların gevşemesi) düzelir; walk-forward testi `portfolio` serisini kullandığı için etkilenmez. (2) **Benzerlik serisi**: üyenin `kopya_gunluk` serisi ucuz kapıya takılsa da hesaplanır (`seri_zorla`), okuma hatasında önceki seri korunur (0xfc76 HIP-3 yüzünden `coin_fazla` → `None` → "benzer" sayılıp 0x424d dışarıda kalıyordu). (3) **Coin tavanı** = max(kasa × `canli_coin_tavan_oran`, `radar_slot_tavan_carpan` × slot): 1.000 $'da 300 $ (değişmez), 600 $'da 180 → 300 $. (4) Ölçümler bozuk olduğu için **yeni sanal dönem** `DONEM` = 2026-11-13T15:30Z (ilk vardiya ~17:00Z = 20:00 TSİ); 28 gün ≈ 11.12. Açık konu (kural tartışması, uygulanmadı): `ters_netlesme` ile atlanan açılışın engel kalkınca telafisi (0x8abc HYPE).
- **Birleşik hesap paydası düzeltmesi (14.11):** 13.11 formülü (perp + USDC `total` − `hold`) yanlış: `hold` bekleyen emirlerin teminatını da içeriyor; 14.11 radarında 0xfc76… (pozisyonsuz, emirli) 213.155 $ yerine 0,09 $ okundu (`payda_oran` 2,4 milyon). Birleşik hesapta payda artık yalnız USDC `total` (HL `portfolio` değeriyle aynı; 0x8abc ve 0xfc76'da doğrulandı). Yeni dönemde henüz emir yoktu; bozuk paydalı emir riskine karşı `DONEM` = 2026-11-14T09:00Z (ilk vardiya ~10:05Z = 13:05 TSİ).

## K-66 — Kullanıcının modeline dönüş: Form Radarı, İlk 11 + Yedek 19 (kullanıcı kararı 14.11)
- Kullanıcı: "benim fikrime dön, güncelle her şeyi": son 1 haftanın formuna göre takıma girip çıkma; "geçmişi geç, şu an + gelecek".
- Dış araştırma (`arastirma/dis_inceleme/`): geçmiş performansa göre seçimin kazandırdığı ne dünyada ne HL'de kanıtlı; D+ ve walk-forward kolları rastgeleden iyi değil. Bu yüzden kalıcı seçim (D+) bırakılır; karar ileriye dönük sanal ölçümle verilir.
- **Seçim:** Form Radarı v1 (`docs/RADAR_V1.md`) + v1.1 kuralları (K-53): günlük, kayan son 7 gün; kadro 30 = İlk 11 + Yedek 19; giriş/çıkış RADAR_V1 §5 (bekleme 14 g, işlem yok 72 sa). Kadro sürümü `v3`.
- **Boyut:** saha 11 × 200 $ → sanal kasa 2.200 $ (futbol sınaması: küçük slotta açılışların %22–33'ü yuvarlanıyor). Gerçek para kuralı (K-22/K-26, ≤ 1.000 $) değişmez; kasa artırımı yalnız kullanıcı kararı.
- **Risk:** zirveden −%20 ve günlük −%5 kasa kilidi aynen.
- **Değerlendirme 31.12.2026:** başarı = ayda ≥ %4 ve aynı dönemde BTC al-tut'tan iyi. Değilse bu yapıyla gerçek para yok.
- **Silinenler (kullanıcı: "planımdan sonraki kararları sil"):** D/D+ seçimi ve kararları (eski K-54, K-55, K-57, K-59, K-60, K-61, K-63), K-65 seçim vetoları, elle çıkarma listesi, erken canlı yol haritası, walk-forward seçim doğrulaması ve Revizyon 1; kodları, testleri ve belgeleri repodan kaldırıldı (git geçmişinde). Kalanlar: K-56 sadık boyutlama, K-58 düzeltmeleri, K-62 risk eki, K-64 borsa stopu, K-65 veri/ölçüm düzeltmeleri ve acil kapatma.
- **Uygulama:** radar iş akışı tarama → kadro → isabet; `RADAR_SURUM` v3; saha 11 × 200 $; sanal kasa üst sınırı `canli_sanal_kasa_ust_usd` 10.000 $ (kullanıcı 14.11: "önemli olan seçim işe yarıyor mu"; slot ≈ 909 $, boyut/yuvarlama ölçümü etkilemesin) (yalnız sanal kip; gerçek kip 1.000 $ değişmez); yeni sanal dönem `DONEM` = 2026-11-14T19:30Z (v4 kurallarıyla; önceki 15:15Z ve 16:30Z dönemleri sayılmaz — hatalı radar ölçeği / boş saha).
- **Saha hep dolu (kullanıcı 14.11):** boş yer aynı koşuda form sırasıyla İlk 11, sonra Yedek'ten dolar (K-45/K-44 yürürlükte); RADAR_V1 §5 metni buna göre güncellendi.
- **Radar hunisi (kullanıcı 14.11, "Önerinle onaylıyorum"; Fable bağımsız denetimi):** 14.11 radarı 300 adaydan 0 geçen verdi (evren 2.457). (1) `radar_aday_tavan` 300 → 900; `radar_zaman_butcesi_dk` 120 → 150, radar.yml iş zaman aşımı 180 → 210 dk (aşımda koşu eksik, `son/` güncellenmez). (2) `radar_min_kopya_islem` 10 → 0 (v1.1 S2; RADAR_V1 §3 tablosunda yoktu); şans süzgeci (kural 8) ve diğer kapılar aynen. Düzeltmeler (kural değil): vault sorgusu ve para hareketi yalnız dolum kurallarını geçende (hız); `dolum_fazla` yalnız perp dolumla sayılır; R1 çıkışında veri nedenleri (`veri_hatasi`, `payda_yok`, `zaman_yok`) sonuçla düşme + 14 gün bekleme vermez (`veri:<neden>`).
- **Mantık denetimi (Fable) M-06 + M-07 (kullanıcı kararı 14.11 "evet"):** (a) soğuyan üye (son 72 sa kopya getirisi < −%2) AYNI gün sonuçla düşer + 14 gün bekleme; kadro dışı (> 30, iki farklı UTC günü) en az sıra kuralı kadar cezalı = sonuçla + bekleme (yalnız veri nedeniyle başlayan seri sonuç dışı). (b) Sonuçla her düşmede (slot −%20 stopu dahil) açık pozisyonlar HEMEN kapanır; 24 sa açık bırakma yalnız sonuç dışı düşmede. RADAR_V1 §5 güncellendi.
- **M-09 (kullanıcı kararı 14.11 "evet"):** `radar_surum` v3 → v4 ve `copytrade/canli/RADAR_SURUM` v4: eski kurallarla seçilmiş v3 kadrosu motor tarafından uygulanmaz; ilk v4 radar koşusuna kadar bekleme vardiyası (saha boş, kasa nakitte). `DONEM` lider birleştirmede.
- **Korelasyon sahayı boş bırakmaz (kullanıcı kararı 15.11; Fable A+):** 15.11 radarında 3 üye R1'den düştü; kalan 18 adayın hepsi `kor_kirpildi` oldu, saha 8/11 kaldı (7 günlük seriyle r ≥ 0,7 sık çıkıyor; M-08). Doldurmada birinci tur aynen; yer kalırsa sahadakilere DOĞRUDAN en az benzeyen aday girer (`kor_gevsetildi`, eşitlikte form sırası). Değiştirmede (histerezis) kural aynen.
- **Toplu emir bandı (kullanıcı kararı 15.11; Fable önerisi):** ilk 14 saatte 456 emir (çoğu trader'ın parça parça dolumu). Artırma farkı max(50 $, %10 × hedef), azaltma farkı max(25 $, %5 × hedef) altındaysa emir verilmez (`bant_ici`), fark birikir ve eşik aşılınca tek emirle hedefe eşitlenir. Açılış, tam kapanış, küçük kalan kapatma muaf. Yalnız canlı motor; radar kopya simülasyonu değişmez. Fable sınaması (14 sa kayıt): 456 → ~190 emir, sonuç pratikte aynı (kazanç operasyonel). 5–7 gün izlenecek; aynı dönemde "sabit tutar, yalnız ilk emir" senaryosu kâğıt üzerinde yan yana hesaplanacak.
- **Ölçüm bilgileri (kullanıcı onayı 15.11; Fable önerisi; kural DEĞİL):** pano özetine dönem komisyonu ve brüt K/Z'ye oranı (komisyon hacme bağlıdır, emir sayısına değil); kadro satırlarına ve pano kartlarına medyan pozisyon tutma süresi + sınıfı (scalp < 0,5 sa · kısa day 0,5–4 · day 4–24 · swing > 24) ve haftalık devir. Fable sınaması (72 hesap, 14 gün): kısa tutan / yüksek devirli trader'lar hacmin çoğunu, kârın azını üretiyor; ama sınıf haftadan haftaya kalıcı değil, fark küçük örnekte. 1–2 hafta ölçülecek; fark sürerse sert kapı yerine form puanında yüksek devire ceza değerlendirilecek. Net giriş oranı (ilk 5 dk / en büyük boyut) kural olarak önerilmedi (trader'a değil pozisyona ait; kâr farkı kanıtlanmadı).
- **Haftalık kadro (kullanıcı kararı 16.11; Fable önerisi + mantık denetimi):** ilk 38 saatte sahaya 20 trader girdi, 9'u bir günde çıktı (8'i günlük R1 elemesi). Kullanıcı: "geçmiş 1 hafta performansına göre iyi diyorsam bir hafta kalmalı; pazardan pazara değiştiririz; çıkanın pozisyonu arka planda kalsın". Kurallar (`canli_haftalik_kadro`):
  (1) haftanın kadrosu = pazar haftasının (UTC) ilk taze radar koşusu, `saha.json` `hafta` alanında kalıcı; (2) günlük kadro yalnız tazelik, kaldıraç, korelasyon ve uyarı için okunur;
  (3) hafta içi R1 / soğuma / kadro dışı / sıra / histerezis çıkışı yok → Telegram uyarısı; sayaçlar pazar sıfırlanır; (4) hafta içi güvenlik çıkışları: slot −%20, kaldıraç (radar kaldıraçtan elediyse dahil), 72 sa işlem yok, felaket stopu, günlük frenler, kasa kilidi; stopla çıkan hemen kapanır + 14 gün bekleme;
  (5) hafta içi boş yer: haftanın sırasıyla, o günün kadrosunda da duran aday; (6) pazar: yeni İlk 11'de olmayan iner — yedekte duruyorsa pozisyonları trader kapatana kadar izlenir (`canli_inen_saat` 24 → 72 sa), kadroda hiç yoksa hemen kapanır (R1/soğuma ise sonuçla + bekleme);
  (7) inenlere slot −%20 stopu; inenlerin toplam nosyoneli kasa × %15'i (`canli_inen_tavan_oran`) aşarsa en zarardaki inen kapanır; sahadaki trader ters yönde açarsa inenin o coini kapanır (K-41 engellemesin); (8) inen, iniş bitene kadar yeniden giremez; (9) yeni dönem `DONEM` 2026-11-16T11:30Z (31.12 ölçümü kural setlerini karıştırmasın).
  Fable ölçümü (bu dönem): çıkışlarda hemen kapatma, trader'a bırakmaya göre ~90 $ daha iyiydi (ZEC/HYPE) — 2–3 hafta sonra (6) yeniden ölçülecek. M-07'nin hafta içi R1/soğuma kısmı bu kuralla askıya alındı.

## K-67 — Canlı denetim (17.11, Fable onaylı): gerçek kipte kaldıraç süzgeci
- 2026-11-17 canlı denetim (Fable onaylı): `canli_min_azami_kaldirac` 5. Gerçek kipte HL azami kaldıracı 5'ten küçük coinde AÇILIŞ/artırma yok (atla nedeni `kaldirac_dusuk`; tablo okunamazsa `kaldirac_bilinmiyor`, kapanış serbest). Gerekçe: izole 3x'te azami kaldıracı 3 olan coin −%20'de tasfiye olur; stoplar %20/%22. Sanal kip etkilenmez.

## K-68 — Canlı denetim (17.11, kullanıcı onaylı): defter dışı borsa fazlası otomatik kapanır ve stopla korunur (yalnız gerçek kip)
- `canli_yetim_kapat_sn: 600`. Borsada defterin karşılamadığı pay (yetim coin ya da aynı coinde fazla) 600 sn KESİNTİSİZ sürerse reduce-only, borsa teyitli kapatılır (`_borsa_yetim_kapat`, yalnız o coinler); eşikten sonra her dakika yeniden denenir. O coinde belirsiz emir / sonuçsuz niyet varken kapatılmaz. Tespitte ve kapatmada Telegram alarmı + kayıt. İlk görülme zamanı ve mark `motor.json`'da kalıcı (`yetim_ilk`).
- Bekleme süresince koruma: fazla miktar için ek borsa stopu, tetik referansı yetimin İLK görüldüğü andaki mark (sabit; fiyatı kovalamaz), `canli_borsa_stop_oran` uzakta. Defter temelli borsa stopu (`hedefler`) değişmedi. Sanal kip etkilenmez.

## K-69 — Canlı denetim (17.11, kullanıcı kararı): stopsuz pozisyon toleransı 2 saat → 30 dakika (K-65 güncellemesi)
- `canli_borsa_stop_korumasiz_sn` 7200 → **1800**. Borsa stopu beklenen coinde 30 dk kurulamazsa pozisyon otomatik kapatılır (K-65'in geri kalanı aynı: ceza süresi `canli_borsa_stop_ceza_sn`, kapanış serbest). Gerekçe: stopsuz pozisyonun 2 saat çıplak kalması; yalnız gerçek kip etkilenir, sanal kip borsa stopu kullanmaz.

## K-70 — 2. canlı denetim kararları (18.11, kullanıcı: "hepsini yapalım"; Fable önerileri)
- **O-1 (N = 3):** gerçek kipte ardışık 3 HL okuma hatasında `hl_okunamiyor` açılış bayrağı + alarm (saatte bir); başarılı okumada kalkar. Risk/DUR ertelenmez.
- **O-2 (600 sn → kapat):** defterde pozisyonu olup ne `saha.uyeler` ne `saha.inen`de olan adres ilk görülmede alarm; `canli_yetim_kapat_sn` (600 sn, K-68) KESİNTİSİZ sürerse reduce-only kapatılır (kapanış kuyruğundaki / belirsiz emirli coinler hariç). Sanal kipte de aynı bekleme. Gerçek kipte `saha.json` sıkı okunur (bozuksa `DurumBozuk`); kozmetik pano çağrıları yalıtılır.
- **K-1 (ofset bayrağı / yerel risk):** açılışta ledger okunur, ofset mutabakattan ÖNCE yenilenir (transfer türleri dahil). Ofset doğrulanana kadar risk YEREL defter özsermayesiyle sürer (çekimden etkilenmez, ertelenmez), yalnız `ofset` açılış bayrağı kapalı; 3. başarısız ledger okumasında alarm (saatte bir). Açıklanamayan sıçrama (`hl_sicrama`) hafızası `motor.json`'da; açılışta son kayıtlı özsermayeyle kıyas.
- **D-11 (yalnız kapanış modu):** gerçek kipte HL > `canli_hl_deger_ust_usd` (1.500 $) iken yeniden başlatmada borsada açık pozisyon varsa motor başlar ama YENİ AÇILIŞ YOK (`kapanis_modu` bayrağı + alarm; kapanış, borsa stopu, trader kapanış takibi çalışır). Pozisyon yoksa bugünkü ret (çıkış 3).
- **D-2 yapılmadı:** `set_expires_after` borsa stoplarını bozar (Fable); `belirsiz_coz` bunun yerine yalnız açık `unknownOid` yanıtını ve iki ardışık okumada "emir yok" sayar.

## K-71 — Süre, tarih ve işlem sayısı şartları kaldırıldı (kullanıcı kesin kararı 19.11, orkestratör üzerinden)
- Sanal dönemin bitiş tarihi yok, canlı tarihi yok; kullanıcı bildirene kadar sanal test sürer.
- Kaldırılan otomatik karar noktaları: K-46 kontrol noktası (02–03.12 dur/devam ve 19.11 "üst sınır < 0 ise dur"), K-66'daki 31.12 değerlendirmesi ("ayda ≥ %4 ve BTC'den iyi değilse gerçek para yok"), K-62/K-66 tarih şartları (K-62 ↔ K-66 çelişkisi böylece kalktı). Proje zarar etse de devam eder; kullanıcı geliştirir.
- Kaldırılan işlem sayısı şartları: RADAR §7 madde 1 (≥ 28 gün canlı, ≥ 100 kapanmış işlem).
- Kalan: ölçüm ve raporlama (isabet, %4/ay ve BTC karşılaştırması bilgi olarak), risk kilitleri (zirveden %20, günlük frenler) ve tüm güvenlik kuralları. Gerçek paraya geçişin zamanı ve şekli yalnız kullanıcının kararı.
- Kod: bu şartlara bağlı otomatik durdurma kodda yok (K-46 ve 31.12 yalnız belge kuralıydı); kod değişikliği gerekmedi.
- 28 günlük strateji kilidi (AGENTS.md kural 5) de kaldırıldı (kullanıcı kararı 19.11, seçenek b): strateji ayarları kullanıcı kararı ve onaylı süreçle istendiği zaman değişebilir; değişiklik yeni sürüm olur, eski seri silinmez.

## K-72 — Gerçek para sert sınırları koda gömüldü (kullanıcı kararı 19.11; Fable önerisi: CT 3x kalır)
- Sınırlar `copytrade/canli/sert_sinirlar.py` içinde sabit; yanlış `kurallar.yaml` aşamaz. Yalnız GERÇEK kip; sanal kip (10.000 $ sanal sınır) değişmez.
- Kasa üst sınırı 1.000 → **1.500 $** (`canli_kasa_ust_usd: 1500`; etkin sınır = min(yaml, 1.500)). Seçili kasa `canli_kasa_usd` 1.000 $ olarak kalır (kasa seçimi kullanıcının sonraki kararı). `canli_hl_deger_ust_usd` 1.500 kalır (kasa sınırı değil, yeniden başlatma tavanı; ayrı sert sınır yok).
- Günlük kayıp ≤ %5: `canli_gunluk_kayip_oran` > 0,05 ise gerçek kip başlamaz (KipHatasi, çıkış 3; `--kontrol` da hata verir).
- Kaldıraç ∈ [1, 5]x: `canli_marj_kaldirac` dışındaysa gerçek kip başlamaz. CT 3x kalır: 5x izole tasfiye (≈ −%17-19) bizim %20/%22 stoplarımızdan önce gelir. K-67 `canli_min_azami_kaldirac` (coin filtresi) ayrı, değişmedi.

## K-73 — Sanalda tüm özellikler açık (kullanıcı kararı 19.11 gece)
- Karar: SANAL kipte hiçbir özellik kapalı / gölge / yalnız-kayıt kalmaz; işlem sonucunu etkiler. Kapılar ve kalite eşikleri YALNIZ gerçek kipte. DEĞİŞMEYEN: sert sınırlar (`sert_sinirlar.py`: günlük kayıp %5, kaldıraç 1–5x, 1.500 $), holdout mührü, gerçek kipin tüm davranışı. Her yeni etki yalnız `kip == "sanal"`, yalnız yeni açılış/artırmayı atlar ya da küçültür (kapanış/azaltma asla engellenmez), `kurallar.yaml` bayrağıyla (varsayılan açık) ve `_atla` yoluyla kaydedilir (alinmayan_neden, kural maliyeti, karşı-olgu; Telegram etiketi `ATLA_TR`).
- 1) Rejim: 1d VE 4h etiketi giriş yönüne ters (long/trend_down, short/trend_up) → `rejim_ters` ("piyasa yönüne ters"); bilinmeyen etiket = atlama yok. Bayrak `sanal_rejim_filtre`.
- 2) Haber: ton ters (negatif/long, pozitif/short) ve 24 sa başlık >= `sanal_haber_min_baslik` (2) → `haber_ters` ("haber akışı ters"). Bayrak `sanal_haber_filtre`.
- 2b) Duygu (ek, 19.11): Fear & Greed >= `duygu_ust` (75) → yeni long yok, <= `duygu_alt` (25) → yeni short yok → `duygu_ters` ("piyasa duygusu ters"); değer yok/bayat = atlama yok. Bayrak `sanal_duygu_filtre`. Filtre hatası 1 saatte 3+ kez olursa Telegram ⚠️ uyarısı (6 saatte bir).
- 3) HIP-3: `sanal_hip3_kopya: true` (gerçekte `canli_hip3_kopya: false` kalır); radar `radar_hip3_kopya: true` (radar çıktısı bugün yalnız sanal motorda; gerçeğe geçmeden önce yeniden değerlendirilir). Testler bilerek güncellendi.
- 4) Gölge kurallar: A (hesap < `golge_hesap_alt_usd`) → `hesap_kucuk`; B20 (kaldıraç > `golge_kaldirac_cikar`) → `kaldirac_cok_yuksek`; B5 (> `golge_kaldirac_uyari`) → boyut x0,5 (`emir.golge_carpan`). Bayrak `sanal_golge_kurallar_etkin`; `golge_kural` olayları sürer.
- 5) Öğrenme drift: sanalda CUSUM alarmı → `egit_zorla` (filtre sonraki saatlik adımda yeniden eğitilir) + kurulum çarpanı min(mevcut, 0,5) (haftalık kadro değişiminde biter); olay `drift_eylem`. Bayrak `sanal_ogrenme_drift_eylem`; `ogrenme_drift_telegram` kapalı kalır.
- 6) `kurallar.yaml` yorumları, VERI_SOZLESMESI ve DURUM güncellendi.
- 8) İz süren koruma (yalnız sanal): kâr zirvesi (girişe göre, yön + mark) %15'e ulaşınca stop girişe; %30'a ulaşınca stop +%15 kâra; kâr stopa inerse pozisyon kapanır (`iz_suren_koruma`, trader sahada kalır). Zirve `Poz.zirve_kar` (hesap.json; yeniden başlatmada kalır; artırmada ortalama giriş değişince sıfırlanır). Sabit kâr al YOK; %20 felaket stopu aynen sürer. Ayarlar: `sanal_iz_suren`, `iz_basabas_oran` 0,15, `iz_kilit_oran` 0,30, `iz_kilit_seviye` 0,15.
- **Ek (denetim O1, 20.11): azaltma çarpanı.** Açılış/artırmada slotu küçülten çarpan (ders ×[0,5–1] · sanal gölge B5 ×0,5) `Poz.boyut_carpan` olarak pozisyona yazılır (`hesap.json` ile kalıcı; eski kayıtlarda 1,0). AZALTMA hedefi aynı çarpanlı slotla hesaplanır (hedef = slot × çarpan × trader_sonra / hesap); böylece trader yarıya inince biz de yarıya iner (eskiden çarpansız slot hedefi büyük çıkıp azaltma atlanıyordu). Tavanlar/min emir/bant aynen. Ders çarpanı gerçek kipte de geçerli olduğundan düzeltme iki kipte de etkilidir. Artırmada çarpan güncel değerle yeniden yazılır.
- **Ek (denetim O3, 20.11): haber tonu kelime sınırında.** `haber.ton` artık alt-dize değil kelime-sınırı (Unicode-güvenli regex) eşleşir: 'bank'≠'ban', 'issue'≠'sue', 'against'≠'gain'. Çekim ekleri (s/es/ed/d/ing) ve 'approv'/'liquidat' kökleri korunur.

## K-74 (kullanıcı onayı 20.11) — Tasfiyeden önce duran dinamik stop
- Karar: `dinamik_stop: true` (sanal + gerçek). Daraltılmış stopla kapanış nedeni `tasfiye_koruma_stop` (Telegram: "Neden: tasfiye koruması stopu").
- Sorun: izole 3x'te HL azami kaldıracı 3 olan coin (örnek VVV, bakım marjı %16,7) girişten ~%14,3 aleyhe gidince tasfiye olur; %20 felaket stopu (gerçekte %22 borsa stopu) tasfiyeden SONRA kalır.
- Öneri (bayrak `dinamik_stop`, varsayılan false = bugünkü davranış): yazılım stopu = min(`canli_felaket_stop_oran` 0,20; tasfiye mesafesi − 0,03); gerçekte borsa stopu = min(`canli_borsa_stop_oran` 0,22; tasfiye mesafesi − 0,01). Tasfiye mesafesi `hesap.tasfiye_fiyati` formülüyle: ortalama giriş, kaldıraç, coin azami kaldıracı. Mark fiyatıyla tetiklenir; artırmada ortalama giriş değişince yeniden hesaplanır (borsada mevcut stop eşitlemesi yeni stopu koyup eskisini iptal eder).
- Örnekler (giriş 100, 3x): azami 3 short → tasfiye 114,2857, stop %11,2857 (111,2857); azami 5 short → 121,2121, stop %18,2121; azami 20 → stop %20 (değişmez); azami 3 long → tasfiye 80, stop %17.
- Not: gerçekte borsanın bildirdiği tasfiye fiyatı kodda okunmuyor; formül kullanılır. Defter dışı (yetim) stoplar değişmez.
- Ayrıca (onaylı, bayraktan bağımsız): sanal tasfiye artık `emir` kaydı (neden tasfiye) + standart "kapandı" Telegram mesajı + 💥 alarm üretir; pano KAPANAN nedeni "Tasfiye".

## K-75 kaçan açılış telafisi (sanal) — kullanıcı kararı 20.11 (orkestratör üzerinden)
- Sorun: trader açılışı `canli_olay_stale_sn` (120 sn) sonra görülürse `gec_acilis` ile atlanır; yeniden başlatmada `kacanlari_tamamla` yalnız son `canli_kacan_pencere_dk` (60 dk) dolumlarını oynatır. Daha eski açılışlar bizde hiç açılmazdı (kapanışlar sorun değil: senkron trader pozisyonu 0 görünce kapatır).
- Karar (YALNIZ sanal kip; bayrak `sanal_kacan_acilis_telafi: true`, gerçek kip değişmez): senkron adımında (`dakika`; başlatmada ilk dakika senkronu hemen yapar, `_son` bellekte) her saha traderı için, trader pozisyonunu (aynı coin) biz tutmuyorsak ve aşağıdaki koşullar sağlanıyorsa pozisyon NORMAL açılış yolundan (`_emir_isle`: tüm K-73 filtreleri, slot/coin/marj tavanları, ders/ML çarpanları, min emir; boyut hedef tabanlı) açılır.
- Koşullar: (1) fiyat: güncel mark, trader giriş fiyatına (`clearinghouseState.entryPx`) göre bizim aleyhimize en çok `kacan_telafi_kayma` = %1 (long: mark/giriş − 1; short: 1 − mark/giriş; lehimize sınırsız); (2) yaş: trader pozisyonunun son sıfırdan açılış dolumu son `kacan_telafi_max_saat` = 24 sa içinde (dolumlardan; pencerede açılış yoksa "pozisyon_eski", okuma hatasında o tur atlanır, `startPosition` yoksa bilinmiyor = serbest); (3) filtre saygısı: o `adres|coin` için son açılış atlama nedeni (`motor.son_atla`, `motor.json`'da kalıcı) `gec_acilis` / `trader_hesap_yok` / `hesap_yok` DEĞİLSE (rejim, haber, duygu, hesap_kucuk, kaldirac, ML, slot_tavani, hip3/spot, ters_netlesme, engel...) telafi yok; pozisyon açılışından ÖNCE yazılmış eski atlama yok sayılır. Telafi denemesi kendi atlamasını da yazar → aynı pozisyon her senkronda yeniden denenmez.
- Kayıt: `emir` `boyut_neden: "kacan_telafi"` (+ `telafi_boyut_neden` = normal yolun nedeni, `telafi_trader_giris`, `telafi_kayma`, `telafi_yas_sa`); `kacan_telafi` (karar/neden) ve `kacan_telafi_atlandi` (neden değişince bir kez) olayları; normal "açıldı" Telegram mesajı.
- Bilinen sınır: HIP-3 (`hip3_atlandi`) sanal bayrak açılmadan ÖNCE atlanmış açılışlar "filtre atlaması" sayılır, telafi edilmez (kasıtlı; istenirse ayrı karar).
- Mutabakat notu (aynı gün): 8 açma/artırma sapmasının TAMAMI K-35 slot toplam tavanı (`slot_tavani`; K-56'dan beri 1,5 × slot) kaynaklı, hata değil.
- Ek (denetim R4, kullanıcı onaylı istisna): (a) Kendi korumamızla kapanan pozisyon (`felaket_stop`, `tasfiye_koruma_stop`, `iz_suren_koruma`, `tasfiye`, `borsa_stop`/`borsa_stop_korumasiz`, `gunluk_kapat`, `dur:*` [zirve düşüşü dahil]) telafiyle YENİDEN AÇILMAZ: `motor.stop_muaf["adres|coin"] = [trader yön işareti, kapanış ms]`. Muafiyet kimliği: trader pozisyonunun yönü + zamanı. Biter: trader pozisyonu sıfırlanınca/ters dönünce (senkronda görülür), ya da trader'ın o coinde kapanış anımızdan DAHA YENİ bir açılış dolumu görülünce (telafi yaş okuması), ya da yeni canlı açılış normal yoldan kopyalanınca. Canlı yeni açılış (`_olay_isle`) engellenmez; yalnız telafi etkilenir. `motor.json`'da kalıcı. (b) Fiyat sınırı İKİ YÖNLÜ: |mark/trader_giriş − 1| ≤ `kacan_telafi_kayma` (%1); lehimize %1'den fazlası da açılmaz (kovalama yok; eski "lehimize sınırsız" kaldırıldı). Olay `kacan_telafi_atlandi` neden: `stop_muafiyeti` | `kayma_lehte_fazla`.

## K-76 kopyalama kapsamı: ilk açılış + ilk 2 ara dolum + tam kapanış (kullanıcı onayı 20.11, beyin fırtınası)
- Karar: Kopyalama ilk açılış + ilk 2 ara dolum + tam kapanış (kullanıcı onayı 20.11, beyin fırtınası); karşı-olgu ölçülmez.
- Kural: `kopya_ara_dolum_max: 2` (sanal + gerçek). Ara dolum = açılıştan sonra, tam kapanıştan önce trader'ın aynı pozisyonda artırması YA DA azaltması; sayaç pozisyon başına (`motor.json` `ara_dolum`, kalıcı), tam kapanışta ve yön dönüşünde sıfırlanır. 3. ve sonrası: emir yok (`emir_yok` / `ara_dolum_siniri`). Parçalı dolum: aynı yön + önceki dolumdan en çok `kopya_ara_dolum_kume_ms` (1000) sonrası = aynı ara dolum (açılış emrinin parçaları ara dolum sayılmaz).
- Senkron / telafi / drift atlananı geri getirmez: `_senkron_azalt` kaçan azaltmayı da ara dolum sayar (sınır aşıldıysa emir yok); K-75 telafi sınırı aşılmış pozisyonu açmaz; drift "ideal"i bu pozisyonu dışlar. Tam kapanış (canlı ya da senkronda trader 0) her zaman alınır, boyut farkı olsa da reduce-only tam kapanış. Stoplar ve risk kapıları aynen.


## K-77 zarar ettiren trader: önce küçült, sonra ele (kullanıcı kararı 20.11, beyin fırtınası)
- Karar: Bir trader'dan kopyaladığımız tam kapanmış pozisyonlar (pozisyon bazında net = giriş+çıkış ücreti dahil; pano `kapanan_ozeti` / `hesap.dolum_net` ile aynı tanım) en az 5 ve toplam net < 0 → o trader'ın yeni açılış/artırma boyutu ×0,5; en az 10 kapanışta net hâlâ < 0 → en küçük boyut; toplam net ≥ 0 olunca çarpan 1. Mevcut `kopya_zarar` (radar R1) elemesi AYNEN sürer; küçültme önce devreye girer.
- Kural (kurallar.yaml, sanal + gerçek; sanalda kapalı değil): `trader_zarar_kucult_n1: 5`, `trader_zarar_kucult_carpan1: 0.5`, `trader_zarar_kucult_n2: 10`.
- Pencere: `kopya_zarar` ölçümüyle AYNI = `radar_pencere_saat` (168 sa, kayan). Kapanış kayıtları `hesap.json` `kapanan` (trader başına en çok 200) ile kalıcı: yeniden başlatmada kaybolmaz; pozisyon başına net `poz_net`te birikir (açıkken yeniden başlatma da korunur; bu sürümden ÖNCE açık pozisyonun eski dolumları sayılmaz).
- "En küçük" = asgari emir `radar_min_emir_usd` (11 $; HL alt emir sınırı + pay; boyut kuralının zaten yuvarladığı en küçük emir). Açılış 11 $ olur (neden `trader_en_kucuk`), ARTIRMA yok (`trader_en_kucuk` atlandı; hedef zaten asgari), azaltma/kapanış aynen. Kapanışlar `kopya_getiri` kapısını (`radar_min_emir_yuvarla_alt`) etkilemez.
- Çarpan etkileşimi: ders × gölge-B5 × K-77 hepsi ÇARPIMSAL (çift sayım yok: her biri bir kez, slota uygulanır); sonuç `Poz.boyut_carpan`a yazılır, azaltma o çarpanı kullanmaya devam eder (O1 bozulmadı). En küçük boyutta çarpan = 11 $ / (küçültmesiz-ders-gölgeli hedef). K-76 ara dolum mantığına dokunulmadı; K-77 yalnız açılış/artırma boyutuna etki eder.
- Kayıt: seviye değişince TEK `trader_kucult` olayı {adres, eski, yeni, n, net} (seviye 0 = ×1, 1 = ×0,5, 2 = en küçük); Telegram'da ayrı mesaj YOK, saatlik özete (pencerede değişen) ve günlük rapora (aktif olanlar) tek satır; pano trader satırında "½" / "en küçük" rozeti.

## K-78 günlük radar sunucuda (kullanıcı kararı 20.11, beyin fırtınası)
- Karar: Radar GitHub Actions yerine sunucu zamanlayıcısında koşar. Neden: Actions cron'u ~7 sa geç tetikleniyordu (kadro 03:37 TSİ yerine ~10:42'de çıkıyordu; yedek cron da aynı sorunu taşıyordu).
- Uygulama: `deploy/sg-sanal-radar.timer` (00:37 UTC = 03:37 TSİ, `Persistent=true`, ±2 dk) → `sg-sanal-radar.service` → `deploy/sanal_radar.sh`. Adımlar `radar.yml` ile birebir (tarama, kadro, isabet, PBO, rastgele, holdout mührü, `radar` dalına yayım: `.github/scripts/radar_yayimla.sh` ortak). Radar FORMÜLÜ / seçim / puanlama kodu DEĞİŞMEDİ.
- Düzen: ayrı geçici worktree (motorun çalışma dizinine dokunmaz), `flock` tek koşu, adım zaman aşımları, `MemoryHigh/Max` 550M/700M + `Nice=15` + `IOSchedulingClass=idle` + `CPUQuota=60%`. Ayrı venv (`requirements-radar.lock`, sha256 kilitli; pandas/numpy canlı motor venv'inde yok). Sır YOK (halka açık veri); push kimliği mevcut SSH deploy anahtarı. Otomatik güncelleme (`sanal_guncelle.sh`) birimleri kurar ve `enable --now` eder.
- Alarm: başarısızlıkta tek `[CT] ⚠️ Radar sunucuda çalışmadı: <adım>`; başarıda mesaj yok.
- Actions: `radar.yml`'de cron kaldırıldı, `workflow_dispatch` (elle yedek) kaldı. Sağlık/pano radar gecikme eşikleri (30 sa uyarı / 54 sa kritik) yeni saatle de doğru (normal yaş ≤ ~27 sa).

## K-79 Telegram işlem mesajları saatlik TEK özet; uyarılar anında (kullanıcı kararı 20.11, beyin fırtınası)
- Karar: Telegram günlük mesaj sayısı ciddi azaltılır. İşlem mesajları (açıldı / kapandı / artırma / azaltma / stop kapanışı) AYRI gitmez; saatlik TEK özet mesajında satır olur. Uyarılar anında kalır. Günlük (21:00 TSİ) ve haftalık özet aynen.
- Önceki durum: sanalda emirler 60 dk özetleniyor (`canli_telegram_sanal_ozet_dk`) ama özet türü (`emir_ozeti`) bastırılıyordu; kullanıcıya her "açıldı" ve her "kapandı" ayrı sessiz mesajla gidiyordu (saatte en çok 10, fazlası "+N işlem daha"). Gerçek kipte açıldı/kapandı anında gidiyordu (dolu artırma/azaltma bastırılır; dolmayan emir 🚨 anında, G-18 tampon).
- Yeni: tek özet `🧾 Son 1 saat: N emir (açılış/kapanış/artırma/azaltma) · net ±X $` + 🟢 Açılan · ✅/🔻 Kapanan · 🛑 Stopla kapanan (felaket/borsa/tasfiye-koruma stopu, iz süren koruma, tasfiye; nedeni yanında vurgulu) · ↕️ artırılan/azaltılan · 💰 Kasa (+ K-77 küçültme satırı). Gövde en çok 5 satır; sığmazsa artırma/azaltma kalemleri ve küçültme satırı düşer (sayılar başlıkta, kayıt/pano/günlük raporda var). Pencere 60 dk (motor saati); işlem yoksa mesaj yok ("sistem çalışıyor" satırı da yok).
- Net K/Z tanımı: penceredeki TAM kapanan pozisyonların net toplamı; pozisyon neti = gerçekleşen − her dolumun ücreti (giriş/artırma ücreti dahil, `hesap.dolum_net`) = pano KAPANAN `net` = K-77 `kapanan` kaydı; kısmi azaltmalar pozisyon sonunda zaten içindedir (çift sayılmaz). Test: `tests/test_telegram_saatlik_tek_ozet.py`.
- GERÇEK kip (kullanıcı kararı genel: "işlem mesajları saatlik tek özet"): gerçek kipte de aynı saatlik tek özet (`canli_telegram_gercek_ozet_dk: 60`, `🧾 … · GERÇEK PARA`). ANINDA kalanlar: tasfiye 💥, felaket/borsa stopu ve "stopsuz pozisyon kapatıldı" ALARM'ları, risk/kayıp sınırı/sert fren, motor/sağlık/mutabakat/kasa sınırı uyarıları, "Bot durdu"/"Düzeldi", komut yanıtları, dolmayan/reddedilen emir 🚨 (G-18 tampon, gece sesli). Yani gerçek parada yalnız başarıyla dolan açılış/kapanış/artırma/azaltma bildirimi saate yayılır; bir şey ters giderse eskisi gibi hemen haber gelir.
- Kayıt: `tg_mesaj` olayları sürer: tek tek metin + yapısal alan `tur: islem_satiri` (bastırıldı), saatlik özet `tur: islem_ozeti` (gönderildi). Kaldırılanlar: `canli_telegram_islem_saat_max` üst sınırı, `msg_islem_toplu` ("+N işlem daha"). Eski 15 dk'lık özet (`canli_telegram_*_ozet_dk: 0`) hâlâ bastırılan tür.
- Tahmini mesaj sayısı (kayıt verisinden değil, mutabakat 16–20.11 oranlarından kaba): önce ≈ 35–45/gün işlem mesajı (126 dolu açılış/artış + 21 kapanış ≈ 4 günde; açıldı+kapandı ayrı) + uyarı/günlük; sonra ≤ 24/gün (işlem olan saat başına 1; tipik 10–15) + aynı uyarı/günlük.

## K-80 kararlılık paketi (kullanıcı kararı 20.11, beyin fırtınası madde 4)
Son günlerdeki hataların çoğu "güncelleme sonrası yeni özellik", "dış servis hız sınırı" ve "altyapı varsayımı" kaynaklıydı. Risk limitleri, radar formülü ve K-74…K-79 mantığı DEĞİŞMEDİ; sanalda hiçbir özellik kapatılmadı.
1. **Günde 2 güncelleme penceresi:** `sg-sanal-guncelle.timer` 10:30 ve 22:30 TSİ (07:30/19:30 UTC, ±3 dk, Persistent). Pencere dışında CI-yeşil commit bekler. Acil: `sudo systemctl start --no-block sg-sanal-guncelle` (betik pencereye bakmaz). Saatlik dayanıklılık alarmı ayrı `sg-sanal-denetim.timer`'a (aynı betik, yalnız alarm) taşındı; birim dosyası değişince oto-güncelleme yeni birimi zaten kopyalayıp `daemon-reload` ediyordu (`birimleri_kur`), yeni zamanlayıcılar için `enable --now` eklendi.
2. **Kurulum sonrası 15 dk yalnız ölümcül:** güncelleme betiği `durum/guncelleme_zamani` (epoch) yazar; `Telegram.gonder` her WARN/CRIT'te okur (tasarım gerekçesi: tüm uyarılar tek geçitten geçer, motor yeniden başlasa da dosya kalıcı, ek servis/IPC yok; `saglik.py --guncelleme-isareti`). Ölümcül = bot durdu, tasfiye, kayıp sınırı/sert fren, kapanış eksik, DUR, felaket stopu, vardiya başlamadı. Ertelenen: pencere sonunda durum alarmı `dogrula` ile hâlâ geçerliyse, olay alarmı gecikmeli gider; INFO/işlem özeti etkilenmez.
3. **60 dk bekçi + otomatik geri dönüş:** `sg-sanal-bekci.timer` (5 dk) + `sanal_bekci.sh`. Eşikler (betik değişkeni): yeniden başlama ≥3, `bekci_tetik` ≥1, Telegram hata+429 ≥5, `kacan_telafi_hata` ≥3, hata olayı ≥8, motor pasif 2 tur. Aşılırsa `SANAL_HEDEF_SHA` geri alma yolu + tek ⚠️ + sha `kotu_sha`.
4. **Çift doğrulama + bağlam:** durum alarmları ≥45 sn sonra yeniden sınanır, +1 bağlam satırı; olay alarmları girmez. Sunucu betikleri (bot durdu, ikinci alarm) ve `saglik.py` aynı kural.
5. **Uçtan uca duman testi:** `tests/test_uctan_uca_duman.py` (`-m uctan_uca`, normal suite'te; ~2 sn): sahte HL REST + sahte Telegram + gerçek motor + gerçek yayım betiği + pano + güncelleme kapısı + bekçi.
6. **Kurulum sonrası öz-denetim:** servisler/zamanlayıcılar/`ozet.json` yazımı/yayım tazeliği; başarısızsa geri alma (3 ile aynı yol).
Test: `tests/test_k80_telegram_kararlilik.py`, `tests/test_deploy_sanal.py` (K-80 bölümü), `tests/test_uctan_uca_duman.py`. Ayrıntı: `deploy/kurulum_sanal.md` §6b/§6d.

## K-81 Binance KÂĞIT katmanı, Aşama A (kullanıcı onayı 20.11; orkestratör)
Dayanak: `docs/binance-plan.md` §2-4/§7, `docs/binance-arastirma.md` §1b, Fable F3/F4. Kapsam: CT sinyalleri Binance USDⓈ-M public fiyatlarıyla KÂĞITTA yürür; gerçek emir YOK, anahtar YOK. Risk limitleri, K-73…K-80 mantığı ve HL sanal/gerçek davranışı DEĞİŞMEDİ.
- **Mimari (paralel):** HL sanal motoru (`sg-sanal`) aynen sürer. Binance kâğıt = AYNI motor kodu, ayrı süreç/birim (`sg-sanal-binance-kagit`, `motor --kip sanal --borsa binance_kagit`), ayrı durum/kayıt dizini (`durum/binance_kagit`, `kayit/binance_kagit`) ve ayrı 10.000 $ sanal kasa. Neden ayrı süreç: (1) Binance 451 / çökme HL motorunu ASLA etkilemez, (2) motor.py'de tek satırlık karar yolu değişikliği yok, (3) iki defter aynı HL sinyalini görür (aynı trader seti, aynı olay kimliği → aynı `cloid`; kıyas cloid ile eşlenir). Bedel: ikinci HL WebSocket/REST yükü (HL fiyat okumaları Binance'e yönlendiği için REST yükü az; 429 izlenir).
- **Piyasa verisi arayüzü (en dar hali):** motor zaten `post(...)` arayüzüne bağlı; `copytrade/canli/binance_piyasa.py:piyasa_post` yalnız `allMids` (eşlemeli coinlerde Binance mark) ve `metaAndAssetCtxs` (eşlemeli coinlerde Binance fonlaması) çağrılarını Binance'e yönlendirir; trader/kadro/HL durumu okumaları HL'de kalır. HL sürecinde bu modül kullanılmaz (HL yolu bayt bayt aynı; mevcut testler değişmeden yeşil).
- **Yürütücü:** `BinanceKagitYurutucu` (`binance_yurutucu.py`): dolum = Binance derinliği (alışta ask, satışta bid yürünür; boyuta göre kayma), `binance_kagit_gecikme_ms` sonra okunan defter, IOC bandı (majör 10 bp / altcoin-TradFi 25 bp, F3; kapanış/azaltma bant dışında reduceOnly MARKET gibi bantsız), miktar `stepSize`'a (açılış aşağı), limit `tickSize`'a içe, `minNotional` altı açılış atlanır (`binance_min_nosyonel`), reduceOnly muaf, ücret `binance_taker` (0,05 %), fonlama = Binance son oranı / aralık saati (saatlik tahakkuk; Binance okunamazsa HL oranı + kayıtta `funding_kaynak: hl_yedek`), `binance_kagit_fark_bp` (null = düzeltme yok).
- **Eşleme:** `copytrade/binance_eslesme.yaml` (`dogrulandi` alanlı; kPEPE→1000PEPEUSDT çarpanlı; HIP-3→TradFi, ölçüm modülündeki tabloyla tutarlı). Eşlemesiz / doğrulanmamış / Binance'te işlem görmeyen coinde AÇILIŞ atlanır: `emir_yok` nedenleri `binance_eslesme_yok`, `binance_eslesme_dogrulanmadi`, `binance_islem_yok` (karşı-olgu ölçülür); kapanış/azaltma serbest.
- **K-74 Binance uyarlaması:** `hesap.tasfiye_fiyati(..., mmr, cum_oran)`; Binance'te mmr = `binance_mmr_varsayilan` (%0,5) ya da `binance_mmr_kademe` (alt, üst, mmr, cum); HL sürecinde `mmr_varsayilan = None` → eski formül aynen. Stop = min(üst, tasfiye mesafesi − pay) aynı kural. Tasfiye fiyatı kâğıtta bu formülle hesaplanır; Binance'in gerçek `liquidationPrice`ı imzalı uç olduğundan Aşama C'de karşılaştırılır.
- **Kâğıtta açık ve işleme etkili:** Binance defteri GERÇEKTEN açar/kapar/azaltır; kendi yazılım stopları, iz süren koruma, sanal tasfiye, risk kapıları (günlük kayıp, marj, slot/coin tavanı), K-75/K-76/K-77, rejim/haber/gölge filtreleri, ortak öğrenme HL sanalıyla AYNI kodda ve açık; gölge/yalnız-kayıt/onay-bekler özellik YOK. Kalite kapıları yalnız canlı içindir.
- **Erişim yoksa:** açılışta 403/451 → TEK ⚠️ Telegram + süreç başlamaz (çıkış 4); çalışırken `binance_kagit_erisim_kesinti_sn` (180) kesintisiz hata → TEK ⚠️ + temiz durma (çıkış 4, birim `SuccessExitStatus=4`: yeniden başlatma döngüsü yok). Binance mark okunamazsa önceki mark'lar kalır, Binance defteri okunamazsa emir YOK (uydurma fiyat yok). HL sanal motoru etkilenmez (ayrı süreç).
- **Kayıt / pano / Telegram:** Binance `emir` kayıtlarında `yurutucu: binance_kagit` ve `binance_sembol`, `binance_bid/ask`, `binance_dolum_px`, `carpan`, `bant`, `limit_px`, `gecikme_ms`, `fark_bp_uygulanan`, `market_yedek`; HL kayıtları DEĞİŞMEDİ. Pano TEKNİK sekmesi "Binance kâğıt kıyası" kartı (HL sanal ↔ Binance: açık, kapanan, net K/Z, kayma). Telegram: ayrı işlem mesajı YOK; HL saatlik özetine tek satır "🅱️ Binance kâğıt: N açık · M kapanan · net ±X $ · kayma Y bp" (veri 30 dk bayatsa "⚠️ durdu").
- **DOĞRULANMADI varsayımlar (resmi dokümandan teyit bekler):** taker %0,05 · bakım marjı %0,5 (leverageBracket imzalı, anahtarsız okunamaz) ve `cum` formülü · reduceOnly'nin minNotional'dan muaf olması · fonlama aralığı (`fundingInfo`, varsayılan 8 sa) ve `lastFundingRate`'in tahakkuk oranı olarak kullanımı (gerçek ödeme 8 saatte bir, kâğıt saatlik tahakkuk eder: toplam aynı, zamanlama farklı) · emir gecikmesi 250 ms · IOC bantları · BTCUSDT 100 $ minNotional iddiası · `dogrulandi: false` satırların dayanak eşleşmesi · public `exchangeInfo/premiumIndex/depth` uçlarının sunucu IP'sinden erişilebilirliği (451 riski).
- Test: `tests/test_binance_kagit.py` (eşleme, yuvarlama/minNotional, dolum yönü, ücret, fonlama, K-74, erişim yokken HL etkilenmez, paralel defter bağımsızlığı, fark parametresi). Ayrıntı: `deploy/kurulum_sanal.md` §9. Aşama A geçiş kriteri (plan §7): 5 gün paralel kıyas; 96 saatlik fark ölçümü (`copytrade/olcum/`) bitince `binance_kagit_fark_bp` doldurulur.
