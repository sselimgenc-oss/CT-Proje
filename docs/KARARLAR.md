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
