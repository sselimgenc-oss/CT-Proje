# Form Radarı v1 — tasarım (şimdi + gelecek)

Durum: **tasarım, lider (Claude) yazdı, kullanıcı onayladı (K‑19, 2026-11-04).** Kod yok; uygulama `docs/GOREV_T*.md` ile Sonnet'te.
Eski sistem (Kapı v3, İlk 11 puanı, oda/kontrol, ön kayıt) **kaldırıldı**; bu belge onun yerine geçen tek strateji kaynağıdır.

## 0. Temel fikir (neden böyle)
- "Gelecek" ölçülemez; 7 günlük performans da geçmiştir, yalnız kısa. 7 günde öne çıkanların çoğu **şanstır** ve çoğu zirvede yakalanır
  (ortalamaya dönüş). Bu yüzden 7 günlük form **aday bulur, kanıt saymaz**.
- **Kanıt = seçimden SONRAKİ gerçek (ileri) performans.** Adaya girenin sanal kopyası seçim anında (t0) başlar; takıma çıkışı ve
  takımda kalışı t0 sonrası sonuca bağlıdır. Sızıntı yok: t0 sonrası veri seçimi kuran kurala hiç dokunmaz.
- Sistemin kendisi de sınanır: radarın seçtikleri, aynı filtreden geçmiş **rastgele kontrol grubunu** ileri dönemde yenmiyorsa
  canlıya geçilmez (§6).

Akış: **R0 evren → R1 kopyalanabilirlik (şimdi) → R2 form puanı (son 7 gün) → R3 ileri deneme + kadro (gelecek) → R4 risk → R5 canlı kapısı.**

## 1. Birimler (kalite kuralı 2; `VERI_SOZLESMESI.md`'ye aynen yazılır)
- Getiri **oran** (0,012 = %1,2). Tutar **$**; ölçek her alanda yazılır: `trader_$` (trader hesabı) ya da `kopya_$` (sanal kopya kasası).
- Kaldıraç **x** (nosyonel / hesap değeri). Süre: tutma **saat**, gecikme **dakika**. Zaman **UTC ms**; `t0` = adayın radara giriş anı.
- Sıra/yüzdelik puanlar **0–100**. Pencere: `son7g` = [koşu zamanı − 7×24 sa, koşu zamanı).

## 2. R0 — Evren (günlük, 00:37 UTC)
- Kaynak: Hyperliquid lider tablosu (`stats-data` leaderboard; hafta penceresi `pnl`, `vlm`, `accountValue`). Leaderboard ROI **kullanılmaz**
  (yatırma/çekme bozuyor); getiri kendi kopya hesabımızdan gelir.
- Ön filtre: `accountValue ≥ 10.000 trader_$`, hafta `pnl > 0`, hafta `vlm > 0`, vault/alt hesap değil.
- Ön filtreden geçenler hafta `pnl`'e göre sıralanır, en çok **300** aday için son 7 gün dolumları (`userFillsByTime`) ve açık pozisyonlar çekilir
  (API bütçesi). 300 sınırı ve kaç kişinin dışarıda kaldığı raporlanır.

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

## 5. R3 — Kadro ve ileri kanıt (gelecek) — K‑22: denemesiz, doğrudan canlı
Katmanlar: **PAF (28) → Yedek 11 → İlk 11.** İlk 11'in ilk **N**'i **sahada** (gerçek para), geri kalanı **gölgede**.
- **Saha sayısı:** `N = min(11, taban(kasa / radar_canli_slot_min_usd))`, `radar_canli_slot_min_usd = 25` → 100 $ kasada **N = 4**.
  Slot kasası = kasa / N (gerçek USDC).
- **Gölge:** sahada olmayan herkes (İlk 11'in kalanı, Yedek, PAF) **aynı motorda emirsiz** izlenir: dolum o anki L2 defterinden, bizim tutarımızla.
  Bu bir "deneme aşaması" değildir, canlıyı geciktirmez; yalnız terfi kararı için ileri kanıt üretir. PAF/Yedek gölge slotu 25 $.
- **Başlangıç (bir kez):** ilk günlük koşuda R1'den geçen form sırasının ilk 11'i doğrudan İlk 11 olur, ilk N'i sahaya çıkar (teyit beklenmez).
  Sonra aşağıdaki kurallar.
- **Radar → PAF:** günlük koşuda form sırası en iyi 28 içinde olan (kadroda olmayan) PAF'a girer; `t0` atanır, gölge kopya t0'da başlar.
  t0'da açık olan pozisyonlar kopyalanmaz; yalnız t0 sonrası açılışlar (sahada da aynı).
- **PAF → Yedek 11:** ileri süre ≥ 24 sa ve ileri getiri ≥ 0; boş yer form sırasıyla dolar.
- **Yedek → İlk 11 (teyit):** ileri süre ≥ 48 sa, ileri kapanmış kopya işlemi ≥ 3, ileri getiri > 0 (maliyet dahil),
  güncel form sırası ≤ 22. Boş yer form sırasıyla dolar. Saha boşalınca İlk 11'in sıradaki üyesi sahaya çıkar.
- **Değiştirme (histerezis):** dolu İlk 11'de bir üyenin yerini aday ancak aday form sırası ≤ 11 **ve** üye form sırası > 22 ise alır.
  Günde en fazla **3** İlk 11 değişikliği (devir maliyeti).
- **İlk 11'den düşme:**
  - Anında: İlk 11'e girişten beri düşüş ≥ %10 (slot kasasında) → Yedek'e; R1/4 (kaldıraç > 20x) ihlali → PAF dışı.
  - Günlük: form sırası 2 gün üst üste > 33 → Yedek; 72 sa yeni işlem yok → Yedek.
- **PAF/Yedek'ten çıkış:** form sırası 3 gün üst üste > 50, ya da ileri getiri ≤ −%10, ya da R1 ihlali → radardan çıkar (14 gün bekleme).
- **Sahadan inen üyenin açık pozisyonları:** yeni açılış durur, trader'ın kapanışları izlenir, 24 sa sonra açık kalan kapatılır.

## 5b. Canlı yürütme ve boyutlandırma (sahada)
- **Açılış:** hedef nosyonel = slot kasası × (trader'ın pozisyon nosyoneli / trader hesap değeri), tavan **3,0 × slot kasası**.
  Hedef < `radar_min_emir_usd` (**11 $**; HL alt sınırı 10 $ + pay): 3,0 × slot ≥ 11 $ ise 11 $'a yuvarlanır, değilse atlanır (`min_emir_atlandi`).
- **Artırma / azaltma:** trader'ın pozisyon değişim oranıyla aynı oran. Emir < 11 $ çıkarsa: azaltmada kalan < 11 $ olacaksa pozisyonun tamamı
  kapatılır, değilse atlanır; artırmada atlanır. Trader tamamen kapatınca biz de tamamen kapatırız (reduce‑only).
- **Marj:** coin başına **izole, 3x** (bir pozisyonun tasfiyesi kasanın geri kalanını yakmaz).
- **Emir:** IOC limit, fiyat = en iyi karşı fiyat ± **%0,5** kayma tavanı; dolmayan kısım yeniden denenmez (`dolmadi` kaydı).
- Her emir için kayıt: trader dolum zamanı, bizim görme zamanımız, emir/dolum fiyatı, kayma, ücret, neden. Gölge aynı kaydı üretir (emir hariç).
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
3. **Kontrol grubunu yener:** her gün R1 havuzundan rastgele 11 kişi gölgede aynı kurallarla izlenir; 1.000 rastgele kadroya karşı
   İlk 11 ileri getirisinin tek yönlü p ≤ 0,10 (form gerçekten işe yarıyor mu).
4. Yürütme sağlığı: kaçan dolum ≈ 0, medyan kayma ve gecikme raporlu; motor çalışma süresi ≥ %98.
Bilgi ölçüsü: **form → ileri getiri bağı** (Spearman IC, günlük form puanı ↔ sonraki 7 gün). 4 hafta sonra IC ≤ 0 ise tasarım gözden geçirilir.

## 8. Kilit ve değişiklik
- Tüm eşik ve ağırlıklar **v1'de donar**, `kurallar.yaml` `radar_*` anahtarlarında tek yerde (kodda sayı sabiti yok).
- 28 günlük canlı değerlendirme bitmeden ayar değişmez (aşırı uydurma koruması). Değişiklik yeni sürüm olur (v1.1), eski seri silinmez.
- Veri/kod hatası düzeltmesi serbesttir; sonuç sayılarını değiştiriyorsa PR'da eski ↔ yeni yan yana.

## 9. İş sırası
T1 eski sistemi sil · T1b Cloudflare kalıntıları · T2 R0+R1 tarama · T3 R2 form puanı · **T4 canlı motor** (kadro, saha/gölge, yürütücü, §5b
boyutlandırma, §6 risk, Telegram) · **T5 sunucu + canlıya alma** (kullanıcı: sunucu, API cüzdanı, 100 $ USDC) · T6 kontrol grubu raporu + pano.
