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
