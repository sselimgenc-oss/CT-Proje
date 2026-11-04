# Form Radarı v1 — tasarım (şimdi + gelecek)

Durum: **tasarım, lider (Claude) yazdı, kullanıcı onayladı (K‑19, 2026-11-04).** Kod yok; uygulama `docs/GOREV_T*.md` ile Sonnet'te.
Eski sistem (Kapı v3, İlk 11 puanı, oda/kontrol, ön kayıt) **kaldırıldı**; bu belge onun yerine geçen tek strateji kaynağıdır.

## 0. Temel fikir (neden böyle)
- 7 günlük form tek başına şanstan ayrılamaz; çoğu öne çıkan zirvede yakalanır (ortalamaya dönüş). Bu yüzden form puanı şans korumalıdır
  (bootstrap alt sınırı, yayılma, istikrar) ve kopyalanabilirlik **bugün** gecikme + maliyetle sınanır (R1/6).
- **Kanıt = sahadaki gerçek para sonucu.** Tek motor canlıdır; deneme, kâğıt ya da gölge yoktur (K‑23). Sahadaki kişi kendi canlı sonucu
  ve günlük formuyla kalır ya da düşer.
- Kayıp kasa ile sınırlıdır (100 $, −%20'de durur); kasa büyütmek ayrı kapıdır (§7).

Akış: **R0 evren → R1 kopyalanabilirlik (şimdi) → R2 form puanı (son 7 gün) → R3 kadro + canlı saha (gelecek) → R4 risk → R5 büyütme kapısı.**

## 1. Birimler (kalite kuralı 2; `VERI_SOZLESMESI.md`'ye aynen yazılır)
- Getiri **oran** (0,012 = %1,2). Tutar **$**; ölçek her alanda yazılır: `trader_$` (trader hesabı) ya da `kopya_$` (sanal kopya kasası).
- Kaldıraç **x** (nosyonel / hesap değeri). Süre: tutma **saat**, gecikme **dakika**. Zaman **UTC ms**; `t0` = adayın radara giriş anı.
- Sıra/yüzdelik puanlar **0–100**. Pencere: `son7g` = [koşu zamanı − 7×24 sa, koşu zamanı).

## 2. R0 — Evren ve tarama ritmi (K‑25: her gün + her saat)
- Kaynak: Hyperliquid lider tablosu (`stats-data` leaderboard; `day` ve `week` pencereleri: `pnl`, `vlm`, `accountValue`). Leaderboard ROI
  **kullanılmaz** (yatırma/çekme bozuyor); getiri kendi kopya hesabımızdan gelir.
- Ön filtre (iki taramada aynı): `accountValue ≥ 10.000 trader_$`, hafta `pnl > 0`, hafta `vlm > 0`, vault/alt hesap değil.
- **Tam tarama (günde 1, 00:37 UTC):** ön filtreden geçenler hafta `pnl`'e göre sıralanır, ilk **300** için son 7 gün dolumları çekilir →
  R1 → R2 → **kadro yeniden sıralanır** (giriş ve çıkış). Kesilen kişi sayısı raporlanır.
- **Sıcak tarama (her saat, :07 UTC):** "şu an başarılı işlem yapanları hemen yakala".
  - Adaylar: ön filtreyi geçen ve **gün `pnl`'ine göre ilk 50**'de olup kadroda olmayanlar; son 6 saatte değerlendirilmiş olan atlanır.
  - Bunlar için aynı R1 + R2 (son 7 gün, aynı eşikler, puan **son tam taramanın havuzuna göre** yüzdelik — ölçek aynı kalsın).
  - Ayrıca kadronun 30 üyesinin puanı da aynı yolla güncellenir (sıra canlı kalsın).
  - **Hızlı giriş, sakin çıkış:** sıcak tarama yalnız **ekler/yükseltir** (Yedek'e giriş, İlk 11'e yükselme, §5 histerezisiyle sahaya çıkış);
    **düşürme** kararları (sıra > 22 / > 30) yalnız tam taramada verilir. Anında düşme kuralları (slot −%10, kaldıraç) her an geçerli.
  - Kadro 30'u aşarsa en düşük puanlı Yedek çıkar.
- Her iki tarama GitHub Actions'ta (salt okunur); çıktı `kadro.json` veri dalına yazılır; canlı motor sunucuda bunu **5 dakikada bir** okur.

## 3. R1 — Kopyalanabilirlik (şimdi; sert filtreler, hepsi gerekli)
| # | Kural | Eşik | Gerekçe |
|---|---|---|---|
| 1 | Kapanmış işlem (round trip) `son7g` | ≥ 10 | Az işlemde puan anlamsız |
| 2 | Medyan tutma süresi | ≥ 1,0 saat | Gecikme (~0,3 dk ölçüldü) scalper'da kârı yer |
| 3 | 5 dk'dan kısa işlemlerin payı | ≤ %25 | Aynı gerekçe |
| 4 | En yüksek kaldıraç `son7g` | ≤ 20x | Tasfiye riski |
| 5 | Likit coin payı (nosyonel; coin 24 sa hacmi ≥ 1 milyon $) | ≥ %80 | Kayma |
| 6 | **Gecikmeli kopya testi:** `son7g` dolumları 1 dk gecikme + maliyet (taker %0,045 + kayma %0,05, mevcut `kurallar.yaml` değerleri) ile mevcut kopya motorunda (`defter.copy_ledger`, sabit tutar v4) yeniden oynatılır | kopya getirisi > 0 **ve** ≥ trader'ın kendi `son7g` getirisinin %50'si | Trader kazanıp biz kazanamıyorsak işe yaramaz |
| 7 | Akıl sağlığı | kopya getirisi ≤ +%300, hesap > 0 | Uç değer = veri hatası şüphesi → elenir, raporlanır |

R1'den geçenlere **"radar havuzu"** denir. Her eleme nedeniyle (`neden` kodu) raporlanır.

## 4. R2 — Form puanı (son 7 gün, havuz içinde göreli)
Her bileşen havuz içinde **yüzdelik sıraya** (0–100) çevrilir (uç değerlere dayanıklı; ROI 1800 gibi sapmalar sıralamayı bozamaz).
`form = Σ ağırlık × yüzdelik`.

| Bileşen | Tanım | Ağırlık |
|---|---|---|
| G — güven ayarlı getiri | Kopya işlem getirilerinden 1.000 tekrar bootstrap; `son7g` toplam kopya getirisinin **%20 alt yüzdeliği** (şans koruması) | 0,35 |
| K — kopya getirisi | R1/6'daki gecikmeli+maliyetli `son7g` kopya getirisi (oran) | 0,15 |
| İ1 — kârlı gün oranı | Aktif günlerde kopya günlük getirisi > 0 olan gün oranı | 0,10 |
| İ2 — düşüş | `son7g` kopya özsermayesinin en büyük düşüşü (az olan yüksek puan) | 0,10 |
| Y — yayılma | 1 − (en iyi tek işlemin toplam kârdaki payı) | 0,10 |
| H — hype yakalama | Aşağıda | 0,20 |

**H (hype yakalama):** "trend coin" = `son7g`'de |coin getirisi| HL perp coinleri içinde en üst %25'te **ya da** listelenme ≤ 30 gün.
"Erken giriş" = pozisyon, coinin 7 günlük hareketinin (saatlik mumlarla, yön trader'ın yönü) **%50'si gerçekleşmeden** açılmış.
H = trader'ın `son7g` brüt kârının erken-trend girişlerden gelen payı (0–1). Kârı yoksa 0.

**Form sürüyor mu (sert kural):** son 72 saatte kopya getirisi ≥ −%2. Altındaysa puanlanmaz (soğuyan hype).

## 5. R3 — Kadro (K‑22/K‑23: tek motor, canlı; deneme/gölge yok)
Kadro günlük radar koşusunun **form sırasıdır**, toplam **30**: 1–11 **İlk 11**, 12–30 **Yedek 19** (K‑24; PAF yok). Yalnız İlk 11'in ilk **N**'i
gerçek parayla kopyalanır (**saha**); Yedek yalnız sıra listesidir, izlenmez, emir yok. Havuzda 30'dan az kişi varsa kadro o kadardır.
- **Saha sayısı:** `N = min(11, taban(kasa / radar_canli_slot_min_usd))`, `radar_canli_slot_min_usd = 25` → 100 $ kasada **N = 4**.
  Slot kasası = kasa / N (gerçek USDC).
- **İlk gün:** form sırasının ilk N'i sahaya çıkar.
- **Sahaya giriş (sonraki günler):** saha slotu boşalınca İlk 11'in sahada olmayan en iyi sıralısı girer.
- **Değiştirme (histerezis):** dolu sahada bir üyenin yerini aday ancak aday form sırası ≤ N **ve** üye form sırası > 11 ise alır.
  Günde en fazla **2** saha değişikliği (devir maliyeti; sıcak + tam tarama toplamı).
- **Sahadan düşme:**
  - Anında: sahaya girişten beri slot düşüşü ≥ %10; R1/4 (kaldıraç > 20x) ihlali.
  - Günlük: form sırası 2 gün üst üste > 22, ya da 1 gün kadro dışı (> 30); 72 sa yeni işlem yok; R1'den elendi.
  - Düşen 14 gün sahaya dönemez.
- **Sahadan inen üyenin açık pozisyonları:** yeni açılış durur, trader'ın kapanışları izlenir, 24 sa sonra açık kalan kapatılır.

## 5b. Canlı yürütme ve boyutlandırma (sahada)
- **Açılış:** hedef nosyonel = slot kasası × (trader'ın pozisyon nosyoneli / trader hesap değeri), tavan **3,0 × slot kasası**.
  Hedef < `radar_min_emir_usd` (**11 $**; HL alt sınırı 10 $ + pay): 3,0 × slot ≥ 11 $ ise 11 $'a yuvarlanır, değilse atlanır (`min_emir_atlandi`).
- **Artırma / azaltma:** trader'ın pozisyon değişim oranıyla aynı oran. Emir < 11 $ çıkarsa: azaltmada kalan < 11 $ olacaksa pozisyonun tamamı
  kapatılır, değilse atlanır; artırmada atlanır. Trader tamamen kapatınca biz de tamamen kapatırız (reduce‑only).
- **Marj:** coin başına **izole, 3x** (bir pozisyonun tasfiyesi kasanın geri kalanını yakmaz).
- **Emir:** IOC limit, fiyat = en iyi karşı fiyat ± **%0,5** kayma tavanı; dolmayan kısım yeniden denenmez (`dolmadi` kaydı).
- Her emir için kayıt: trader dolum zamanı, bizim görme zamanımız, emir/dolum fiyatı, kayma, ücret, neden.
- **Güvenlik:** HL **API cüzdanı** (işlem yetkili, para çekme yetkisiz); ana cüzdan anahtarı hiçbir yere konmaz. API anahtarı yalnız sunucuda.

## 6. R4 — Portföy riski
- Slot başına pozisyon tavanı 3,0x (yukarıda), mevcut tasfiye ve aşamalı çıkış (v4) aynen.
- **Coin yoğunlaşması:** aynı coinde tüm saha slotlarının toplam brüt nosyoneli ≤ kasanın %30'u; aşan açılış kırpılır.
- **Benzer trader:** sahada `son7g` günlük kopya getirisi korelasyonu ≥ 0,7 olan en fazla 2 kişi; fazlası sıradaki üyeye yer verir.
- Günlük kasa kaybı ≥ %5 → o gün yeni açılış yok. Kasa zirveden düşüş ≥ **%20** → tüm pozisyonlar kapatılır, motor durur, Telegram (K‑19).
- **/dur şalteri:** Telegram komutu ya da sunucuda dosya → aynı kapanış.

## 7. R5 — Büyütme kapısı (kasaya para eklemek; son karar kullanıcının)
Kasa 100 $'da kalır; artırım ancak hepsi sağlanırsa **önerilir**:
1. ≥ 28 gün canlı, ≥ 100 kapanmış saha işlemi.
2. Net getiri > 0 (ücret + kayma + funding dahil), en büyük düşüş ≤ %15.
3. Yürütme sağlığı: kaçan dolum ≈ 0, medyan kayma ve gecikme raporlu; motor çalışma süresi ≥ %98.
Bilgi ölçüsü (yalnız rapor, ek motor yok): günlük radar dosyalarından form puanı ↔ sonraki 7 gün form getirisi Spearman IC.

## 8. Kilit ve değişiklik
- Tüm eşik ve ağırlıklar **v1'de donar**, `kurallar.yaml` `radar_*` anahtarlarında tek yerde (kodda sayı sabiti yok).
- 28 günlük canlı değerlendirme bitmeden ayar değişmez (aşırı uydurma koruması). Değişiklik yeni sürüm olur (v1.1), eski seri silinmez.
- Veri/kod hatası düzeltmesi serbesttir; sonuç sayılarını değiştiriyorsa PR'da eski ↔ yeni yan yana.

## 9. İş sırası
T1 eski sistemi sil · T1b Cloudflare kalıntıları · T2 R0+R1 tarama · T3 R2 form puanı · **T4 canlı motor** (kadro, saha, yürütücü, §5b
boyutlandırma, §6 risk, Telegram) · **T5 sunucu + canlıya alma** (kullanıcı: sunucu, API cüzdanı, 100 $ USDC) · T6 rapor + pano.
