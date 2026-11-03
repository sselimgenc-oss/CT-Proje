# İlk 11 seçim şartnamesi (A1, 2026-11-02)

Durum: **şartname** (karar + tanım belgesi). Kod yok; uygulama A2'de Sonnet'e verilir, kabul A3'te.
Dayanak: kullanıcı kararları **K‑12** ve **K‑13** (Worker ertelendi) (`docs/KARARLAR_D.md`), `docs/ILK11_KADRO_V1.md`, `copytrade/ilk11.py`, `copytrade/ilk11_veri.py`,
`copytrade/pazar_akis.py`. Birimler `docs/VERI_SOZLESMESI.md` "İlk 11 puan alanları" bölümündedir.

**Strateji kilidi (AGENTS kural 5):** ağırlıklar (`KALDIRAC_AGIRLIKLARI`), alan dönüşümleri, eksik alan = 35, 60/40 eşikleri,
11/11/28, terfi kapısı (son 6 / toplam > 0 / kazanma ≥ 0,40 / en iyi hariç > 0) **değişmez**. Bu belge yalnız tanımsız olanı
(veri kaynağı, pencere, birim, eksik/hata davranışı, iş akışı) tanımlar. Yeni sayısal parametreler (tazelik, doluluk, akıl sağlığı
aralığı) veri kalitesi içindir, `kurallar.yaml`'a `ilk11_*` anahtarlarıyla yazılır ve §7 K‑12.10 ile kullanıcı tarafından onaylandı (2026-11-02).

---

## 1. Kararlar (K‑12 özeti) ve kapsam

**K‑12 (kullanıcı, 2026-11-02; lider önerileri onaylandı):**
1. Şimdilik **pano yok**. Öncelik: motor + İlk 11 / Yedek 11 / PAF seçiminin sorunsuz oturması + canlı veri akışı. Pano sonra.
2. **Uygunluk:** CT-Kapı'da `katman` ∈ {`izleme_adayi`, `kopyalanabilir`} olanlar (2026-10-28 koşusunda 91 kişi) kadroya aday olabilir.
3. **İlk sıralama İlk 11 puanıyla** (`copytrade/ilk11.py`, 10 alan) yapılır — **yalnız 10 alanın hepsi gerçek veriyle doldurulduktan
   sonra** (kabul: §6, her alan doluluk ≥ %90). `ILK11_KADRO_V1.md`'deki "kapı sıralamasına göre" ifadesi bu kararla geçersizdir;
   kapı yalnız **uygunluğu** belirler, sırayı İlk 11 puanı belirler.
4. 1 Kasım'daki acil leaderboard-only kadro (`snapshot_id 1d92dd25…`, `sema: ilk11-acil-baslangic-leaderboard-only-v1`) **"geçici"**
   etiketiyle kalır; ilk gerçek Pazar kadrosu yayımlanınca tamamen kaldırılır (§5.7).
5. **Haftalık form puanı** = aynı 10 alanlı puan (`ilk11.agirlikli_puan`), **son 30 günün verisiyle**, her Pazar yeniden hesaplanır.

**Kapsam (bu şartname):** uygunluk (§2), 10 alanın kaynağı/birimi/penceresi (§3), form ve `paper_sonuclari` (§4), A2 veri hattı (§5),
A3 kabul kanıtı (§6), kararlar (§7; hepsi 2026-11-02'de verildi).
**Kapsam dışı:** pano/ofis, gerçek emir/cüzdan (Faz 3), Faz 2 oda iç kararları, kapı adım mantığı ve eşikleri.

**Lider tespitleri ve bu belgedeki çözümü:**

| Sorun | Çözüm |
|---|---|
| 7 alan (`golge, kazanma, tutarli, dusus, siklik, tutma, kaldirac`) hiçbir kaynaktan dolmuyor → herkese 35 | §3: her alana tek kaynak; A2 doldurur; A3 doluluk ≥ %90 |
| Acil kadroda `ay_roi` = 1805 (leaderboard `roi`, oran → %180.500) | Leaderboard ROI **kullanılmaz**; ROI, kapının zaman ağırlıklı zinciriyle (`kapi.twr_chain`, yatırma/çekme getiri sayılmaz) hesaplanır; akıl sağlığı aralığı (§3.3) |
| Kapı/seçim/izleme iş akışları silindi; kapı verisi 28 Ekim'den | §5: kapı (haftalık), izleme (2 saatte bir, K‑18), İlk 11 Pazar işi geri gelir; tazelik kuralı §2 |
| `form_puani`, `paper_sonuclari` kaynağı tanımsız | §4 |
| Bu ortamdan HL erişimi yok (proxy 403) | Tüm canlı koşular GitHub Actions'ta (§5) |
| `form_esle` `medyan_tutma_saat`'i ×60 yapmadan taşıyordu (26e3f97 `value *= 60.0` satırını silmişti; test kırmızıydı) | **#461 ile düzeldi** (satır geri kondu; `main` 594 test yeşil). `tutma` ham birimi **dakika**: kaynak saat ise ×60 |
| **Yeni bulgu:** `form_esle._DOGRUDAN` kapı sütun adlarıyla eşleşmiyor (`median_holding_hours`, `median_leverage` yok; `account_value` = leaderboard değeri, bugünkü hesap değil) | A2: Pazar işi 10 alanı **açıkça `form_ham`** olarak verir (§5.4); doğrudan eşleme yalnız geri uyumluluk |

---

## 2. Uygunluk (ilk seçim ve kadro boşluğu adayları)

Bir adres `uygun: true` olur, ancak ve ancak aşağıdakilerin **hepsi** sağlanırsa:

1. **Kapı koşusu:** `copytrade-kapi` veri dalında `copytrade/kapi/<YYYY-MM-DD>/` klasörü; `durum.json` → `durum == "tamam"`,
   `kapsam ≥ kapsam_hedefi` (`kurallar.yaml`, bugün 0,98), `hesap` = güncel `HESAP_SURUMU`.
   **Veri bütünlüğü (2026-11-03; kapı kuralı değil):** `durum.json` → `hatali_oran_aday ≤ veri_butunlugu_hatali_oran_max` (`kurallar.yaml`, bugün 0,01 = %1; `hatali_satir` = `hata` dolu satır, `hatali_oran_aday` = hatalı / analize giren = `asama1` Geçti; `hatali_oran_evren` yalnız bilgi). Aşılırsa kapı `durum: eksik`
   (`neden`: `hatali_satir …`) yayımlar ve bu klasör seçimde kullanılmaz (`kapsam` hatalı satırları da kapsanmış saydığı için ayrı ölçü). Hatalı satırlar
   `copytrade_kapi.yml` `yeniden_dene_gun` girdisiyle yeniden koşulur (`VERI_SOZLESMESI.md` §9); yeniden koşulan satır `satir_kaynagi == "bu_kosu"` kalır (3. madde). Birden fazla uygun klasör varsa
   **as_of'tan önceki en yeni** tarih alınır (as_of = Pazar 13:00 TSİ = 10:00 UTC).
2. **Tazelik (koşu):** `as_of tarihi − kapı klasör tarihi ≤ ilk11_kapi_tazelik_gun` (**7 gün**, K‑12.10). Daha eskiyse kapı verisi
   **geçersiz**: ilk seçim ve kadro boşluğu doldurma yapılmaz; iş kırmızı biter, RAPOR/iş özetine neden yazılır (Telegram K‑13 ile ertelendi). (Haftalık form
   kapıya bağlı değildir, §4; yalnız `kapi_puani` eşitlik bozucusu boş kalır.)
3. **Tazelik (satır):** satır o koşuda hesaplanmış olmalı: `satir_kaynagi == "bu_kosu"` (sütun yoksa `now_ms` ≥ as_of − 7 gün).
   Önceki dosyadan taşınan satır (`onceki_dosya_ayni_hesap`) uygun **değildir**. Not: 28 Ekim koşusunda 91 adayın 87'si taşınmış
   satırdı → bu veri ilk seçim için kullanılamaz; ilk gerçek Pazar **yeni tam kapı koşusu** gerektirir (§5.1, mod `tam`).
4. **Sütun:** `katman ∈ {"izleme_adayi", "kopyalanabilir"}` (`kapi.katman`; adım 1–3 Geçti ya da 1–7 Geçti).
5. **Evren:** `evren_disi != True` (güncel lider tablosu evreninde ya da `kaynak == dis_aday`). (`secim.havuz` ile aynı kural, kural 7.)
6. **Akıl sağlığı:** satır kapının akıl sağlığı kapısını geçmiş koşudan gelir (koşu `durum: tamam` zaten bunu içerir) ve
   `hata` boştur.

Diğer satırlar `uygun: false` ve `uygunluk_nedeni` (`katman_yok` | `eski_satir` | `evren_disi` | `hata`) ile snapshot'a girer
(`ilk11_veri.snapshot_olustur` zaten `uygun` false olanı sıralamaz).

**Aday sayısı < 50 iken davranış** (`ilk11.ilk_kadro` mevcut davranışı + yayın kuralı):
- 50 ≤ uygun: normal; ilk 50 → 11/11/28.
- 11 ≤ uygun < 50: snapshot **yayımlanır**; sıra İlk 11 → Yedek 11 → PAF doldurulur, boş kalan yer `kapasite_bos`, `uyari`
  dolu; RAPOR ve iş özetinde uyarı. Kapasite yapay doldurulmaz (uygun olmayan aday alınmaz).
- uygun < 11: snapshot **yayımlanmaz**, iş kırmızı; önceki kadro (ilk haftada geçici kadro) sürer. (Eşik 11 = İlk 11'in dolması;
  karar §7 K‑12.9.)

---

## 3. 10 puan alanı

### 3.1 Genel kurallar
- Alanlar `ilk11.KALDIRAC_ALANLARI` sırasıyla; ham değer → `ilk11.hazirla_kaldirac_alanlari` (yalnız `hesap, siklik, tutma, kaldirac`
  dönüştürülür) → `ilk11.yuzdelik` (aday evreninde sıra ortası yüzdelik; `dusus` düşük iyi) → `ilk11.agirlikli_puan`. **Değişmez.**
- **Tek yerde hesap (kural 7):** 10 alanın hamı yalnız yeni `copytrade/ilk11_alanlar.py` saf fonksiyonlarında üretilir; bu
  fonksiyonlar mevcut hesapları çağırır (`kapi.twr_chain`, `olcut.closed_round_trips`, `olcut.effective_leverage_detail`,
  `secim.puan`, `ilk11.golge_ozeti`), kopyalamaz. Kapı (ilk seçim) ve izleme motoru (form) aynı fonksiyonları çağırır.
- **İki koşu:** *İlk seçim* (kapı satırından, uygun evrenin tamamı) ve *Haftalık form* (izleme motorundan, kadronun 50'si, son 30 gün).
- **Eksik:** değer `None` → alan puanı 35 (`EKSİK_ALAN_PUANI`, değişmez); `alan_kaynagi[alan] = None` ve RAPOR'da sayılır.
- **Akıl sağlığı ihlali:** aralık dışı değer **kullanılmaz** → `None` (35) + `alan_kaynagi[alan] = "akil_sagligi_ihlali:<değer>"`.
  Bir alanda ihlal oranı > `saglik_max_hata_orani` (bugün 0,05) ise koşu **kırmızı**, snapshot yayımlanmaz.

### 3.2 Alan tablosu

Pencere sütunu: **İ** = ilk seçim, **F** = haftalık form. "30g" = as_of'tan geriye 30 × 24 saat.

| Alan (ağırlık) | Anlamı (Etre K1–K10) | Kaynak — İ (kapı satırı) | Kaynak — F (izleme, kadro 50) | Ham birim | Pencere İ / F | Dönüşüm (`ilk11.py`) | Eksikse | Akıl sağlığı aralığı |
|---|---|---|---|---|---|---|---|---|
| `golge` (1,0) | Kopyalanınca ne kazandırır (gölge/sanal kopya sonucu) | `secim.puan(row)` = `gecikme_{kapi_gecikme_dk}dk_net` (tarz gecikmeli, maliyet+funding dahil, `defter.copy_ledger`, trader hesabına oranlı) — **seçim v1.3 puanıyla aynı**, yeni hesap yok | `ilk11.golge_ozeti(getiriler).buzulmus_ortalama`; `getiriler` = `sanal_kopya_v3.kapanan_islemler[].getiri`, kapanışı son 30g içinde, `gecerli == true` (§4.2) | oran (0,10 = %10) | İ: 200 g (`mum_pencere_gun`) / F: 30g | yok (yüzdelik); F'de [−1, 3] kırpma + k=8 büzülme `golge_ozeti` içinde | İ: adım 3 Geçti satırında hep dolu; F: kapanan işlem yok → `None` | İ: [−1, 10] (kapı `saglik_net_*` [−1, 100] zaten); F: [−1, 3] (yapı gereği) |
| `ay_roi` (0,8) | Aylık getiri | Yeni kapı bilgi sütunu `ilk11_ay_roi` = `ilk11_alanlar.pencere_getiri(portfolio, "month", 30)` → `kapi.twr_chain` zinciri son değer − 1 | Aynı fonksiyon, izleme motorunun her saat zaten çektiği `portfolio` ile | oran (zaman ağırlıklı; yatırma/çekme getiri değil) | 30g / 30g | yok | `month` penceresinde < 2 nokta → `None` | [−1, 10] |
| `hafta_roi` (0,6) | Haftalık getiri | `ilk11_hafta_roi` = `pencere_getiri(portfolio, "week", 7)` | Aynı | oran | 7g / 7g | yok | aynı | [−1, 5] |
| `hesap` (0,6) | Hesap büyüklüğü | `hesap_degeri_bugun` (ana + HIP-3 + spot USDC, `kapi.total_account_value`) | `traderlar[].hesap_degeri` (izleme; ana + HIP-3 `marginSummary`) | $ (trader hesabı ölçeği) | anlık / anlık (son saatlik okuma) | `hesap_puani`: `sqrt(clamp((usd−5000)/500000, 0, 1))` | ≤ 0 / yok → `None` | [5.000, 1e9] (alt sınır = kapı tabanı) |
| `dusus` (2,0; **düşük iyi**) | Aylık en büyük düşüş | Yeni `ilk11_dusus_30g` = `pencere_dusus(portfolio, "month", 30)` = `max(1 − equity/cummax)`, aynı `twr_chain` zinciri | Aynı | oran, pozitif büyüklük (0,25 = %25) | 30g / 30g | yok (yüzdelik ters) | `None` | [0, 1] |
| `kazanma` (1,0) | Kazanma oranı | Yeni olcut bilgi sütunu `kazanma_orani` = `net_pnl > 0` işlem sayısı / kapanmış işlem sayısı (`olcut.closed_round_trips`, ücret dahil, tersine dönüş ücret bölüşümü mevcut) | Aynı fonksiyon, kapanışı son 30g içinde olan işlemler | oran [0, 1] | 365 g (`fills_lookback_days`) / 30g | yok | kapanmış işlem 0 → `None` | [0, 1] |
| `siklik` (0,7) | Günlük işlem sıklığı | `gunluk_islem_sikligi` (olcut; kapanmış işlem / gözlenen gün) | kapanışı son 30g içinde işlem sayısı / 30 | adet/gün | 365 g / 30g | `siklik_puani(x, bot=150)` (≥ 20/gün → 0) | işlem verisi yok → `None`; 0 işlem → 0 (puan 0) | [0, 200] |
| `tutma` (0,8) | Medyan tutma süresi | `median_holding_hours × 60` | `closed_round_trips` (son 30g kapanan, açılışı bilinen) medyan saat × 60 | **dakika** | 365 g / 30g | `tutma_puani(dk)` | açılışı bilinen işlem yok → `None` | (0, 525.600] |
| `kaldirac` (0,9) | Kaldıraç kullanımı | `median_leverage` (efektif = o anki pozisyon değeri / o anki hesap değeri, zaman ağırlıklı medyan; `olcut.effective_leverage_detail`) | Aynı fonksiyon, son 30g dolumları + `portfolio` hesap serisi | x | 365 g / 30g | `kaldirac_puani`: `max(0, 1 − |x−4|/20)` | `None` | [0, 200] (`saglik_max_kaldirac`); not: kapı adayları ≤ 3x medyan |
| `tutarli` (1,8) | Pozitif gün tutarlılığı | Yeni `ilk11_tutarli_30g` = `pozitif_gun_orani(portfolio, "month", 30)` = günlük ΔPnL > 0 gün / ΔPnL ≠ 0 gün (`pnlHistory`, UTC gün sonu) | Aynı | oran [0, 1] | 30g / 30g | yok | aktif gün 0 → `None` | [0, 1] |

### 3.3 Seçim gerekçeleri (belirsizler)
- **`golge` (İ):** iki aday vardı: (a) kapının tarz gecikmeli kopya neti (`gecikme_30dk_net` intraday / `gecikme_120dk_net` swing),
  (b) `sanal_kopya_v3`. v3 yalnız izlenen trader'da ve t0'dan sonra var; 91 adayın çoğunda **hiç yok**. (a) tüm uygun evrende aynı
  motorla (`defter.copy_ledger`, gecikme + maliyet + funding) hesaplı ve seçim v1.3'ün puanıyla birebir aynı (`secim.puan`) → tek yerde.
  Eksi: v1 tipi (trader hesabına oranlı) ölçek, v3 değil. Yüzdelik sıralamada ölçek farkı sırayı az etkiler. **Seçildi (karar §7 K‑12.1).**
- **`golge` (F):** kadronun hepsi saatlik v3 izlemede → güncel motor (v3, sabit tutar + çıkış + tasfiye). İşlem başı sonuç
  `golge_ozeti`'nin tasarlandığı girdi (kırpma + büzülme az işlemli trader'ı ortalamaya çeker). Bunun için v3'e yalnız **çıktı alanı**
  `kapanan_islemler` eklenir (§4.2; hesap değişmez).
- **`kazanma`:** kapıda kazanma oranı sütunu yok; `olcut.calculate_metrics` zaten `wins`/`rounds` hesaplıyor ama yayımlamıyor →
  tek satırlık bilgi sütunu. `yonlu_dolum_iyi_orani` (gecikmeli yürütme fiyatı kalitesi) **kazanma oranı değildir** (`ilk11_veri`
  testindeki karar korunur). v3 kopya işlemleri yerine trader'ın kendi işlemleri seçildi: ilk seçimde v3 yok; form ile aynı tanım kalsın.
- **`tutarli`:** Etre tanımı "pozitif gün tutarlılığı". Kapının `profitable_month_ratio` (kârlı ay, 12 ay) aylık; 30 günlük formda
  anlamsız (≤ 1 ay). Pozitif gün oranı her iki koşuda aynı tanımla çalışır. Payda yalnız aktif günler (kapının "aktif ay" tanımıyla
  tutarlı; swing trader'ın işlemsiz günleri cezalandırılmaz). Karar §7 K‑12.2.
- **`ay_roi` / `hafta_roi`:** leaderboard `roi` paydası yatırma/çekmeyle bozuluyor (1805 örneği). Kapının yatırma/çekmeyi ayıklayan
  Modified Dietz zinciri (`twr_chain`, görev 15) tek yerde kullanılır. HL `portfolio` yanıtının `month`/`week` pencereleri bu iş için var;
  örnekleme sıklığı kural 1 denemesinde (§5.6) gözle doğrulanır.
- **`dusus`:** Etre tanımı "aylık azami düşüş". Kapının `max_drawdown`'ı 365 günlük (adım 1 eşiği için); alan 30 günlük düşüşle doldurulur
  (aynı zincir, kural 7). `max_drawdown` kapıda adım olarak kalır, bu alana girmez.
- **`hesap`:** İ'de kapının bugünkü toplamı (spot USDC dahil), F'de izlemenin `hesap_degeri` (spot hariç). Fark küçük; her koşu kendi
  içinde yüzdeliklendiği için tutarlıdır. `account_value` (leaderboard) **kullanılmaz**.
- **`kaldirac`:** "kaldıraç kullanımı" = efektif kaldıraç (kapının ölçüsü). Bilgi: uygun 91 adayın medyan kaldıracı 0,03–2,87x;
  dönüşümün tepe noktası 4x olduğundan bu aralıkta puan **kaldıraçla artar**. Dönüşüm kilitli; karar §7 K‑12.3.

---

## 4. Form puanı ve `paper_sonuclari`

### 4.1 Form puanı
- **Tanım:** `form_puani = ilk11.agirlikli_puan(kadro_alanlari)[id]` (0–100); `kadro_alanlari` = §3.2 F sütunları,
  `hazirla_kaldirac_alanlari` ile dönüştürülmüş. Ağırlıklar, 35 kuralı değişmez.
- **Yüzdelik evreni:** o Pazar kadroda olan 50 kişi (İlk 11 + Yedek 11 + PAF). Gerekçe: F alanlarının kaynağı (v3, saatlik izleme)
  yalnız kadroda var; kadro dışı biri `golge` için hep 35 alırdı. Karar §7 K‑12.5.
- **Hesap yeri (kural 7):** izleme motoru her saat `traderlar[].ilk11_form_ham` (10 ham alan + `alan_kaynagi` + `pencere_bitis`)
  yayımlar (`ilk11_alanlar.form_ham_30g`). Pazar işi yalnız okur, yüzdeliklendirir.
- **Girdi dondurma:** Pazar işi, `copytrade-izleme` dalında `uretildi ≤ as_of` olan **en son** `izleme/durum.json` sürümünü
  (git geçmişinden) alır; `as_of − uretildi ≤ ilk11_form_tazelik_dk` (270 dk = 2 × izleme aralığı 120 dk + 30 dk tampon; K‑12.10 değeri K‑18 ile izleme 2 saatte bire inince güncellendi) değilse o hafta form **geçersiz** (hareket yok).
  Bu seçim yalnız as_of'a bağlı olduğundan tekrar denemede aynı girdi, aynı `snapshot_id` çıkar (`pazar_akis` şartı).
- **`bu_pazar_gecerli`** (`pazar_gecis` girdisi) `true` ⇔ trader'ın `gecerli == true`, `veri_zamani ≥ as_of − 120 dk`, ve 10 alandan
  en az `ilk11_form_min_dolu_alan` (**8**, K‑12.10) gerçek değerle dolu. Değilse form hareketi yok (`pazar_gecis` açıklama yazar).
- **`bu_pazar_aktif`** `true` ⇔ (as_of − 7 gün, as_of] aralığında trader'ın en az bir **perp** dolumu var (HL `userFillsByTime`,
  izleme motorunun dolum önbelleği). `onceki_pazar_aktif` = bir önceki Pazar form snapshot'ındaki değer; yoksa `None`
  (iki Pazar hareketsizlik kararı verilmez).
- **`kapi_puani`** (eşitlik 2.) = son geçerli kapı satırında `secim.puan(row)`; yoksa `None` (→ 0, `_tie_key` mevcut davranışı).
- **`gecerli_gozlem_suresi`** (eşitlik 3.) = trader'ın kadroya **son girişinden** (`takim_hafta`) as_of'a kadar `gecerli == true`
  saatlik okuma sayısı / 24 (gün). **K‑18 notu:** sayaç anlamı (saat) korunur: her yeni `izleme_aralik_dk` kovası (UTC'ye hizalı 2 saat) `izleme_aralik_dk/60` saat ekler; aynı kovada ikinci koşu saymaz (24 saatte 12 koşu = 24 saat). Kaynak: izleme `motor.json` saatlik geçerlilik sayacı (A2: `ilk11_gecerli_saat` alanı).
- Form ilk gerçek kadronun **ertesi** Pazarından itibaren hesaplanır (ilk Pazar yalnız ilk seçimdir; 60/40 hareketi yok).

### 4.2 `paper_sonuclari` (Yedek → İlk 11 kapısı girdisi)
- **Kaynak:** `sanal_kopya_v3` (güncel motor, `defter.copy_ledger` + `tutar_egrisi`). v3'e **yeni çıktı alanı** `kapanan_islemler`
  eklenir — defterin zaten yürüttüğü kopya pozisyonlarının kapanış kaydı; bakiye/getiri **değişmez** (kural 6: yeni hesap yok,
  yalnız raporlanan alan; yine de altın örnek zorunlu, §6.5).
- **Bir "işlem"** = kopyanın kendi pozisyonunun bir coinde 0'dan açılıp 0'a dönmesi (ters dönüşte kapanan kısım biter, kalan yeni işlem
  açar; `olcut.closed_round_trips` ile aynı kural). Kısmi azaltmalar aynı işleme yazılır.
- **Satır:** `{coin, acilis, kapanis (UTC ISO), sonuc_usd, getiri, neden, gecerli}`:
  - `sonuc_usd` = gerçekleşen K/Z − maliyet (taker + kayma) ± funding, **1.000 $ sanal kopya ölçeğinde** ($).
  - `getiri` = `sonuc_usd` / işlemde açılan toplam tutar ($) → oran.
  - `neden` = `trader` | `zarar_kes` | `kar_al` | `likidasyon` (`kapanis_nedenleri` ile aynı sözlük).
  - `gecerli = true` ⇔ işlem t0'dan sonra açıldı (miras değil), tüm yürütmeleri fiyatlı (`fiyatsiz_eylem` yok), kapanış fiyatı mumdan.
    Zorunlu kapanış (zarar_kes, kar_al, likidasyon) **geçerlidir** (gerçek sonuç).
- **Kapıya giren liste:** kadroya son girişten (`takim_hafta`) sonra **açılmış**, `gecerli == true`, kapanış ≤ as_of işlemler,
  kapanış sırasıyla; `ilk11.yedekten_terfi_kapisi` son 6'yı alır. Kapıya `sonuc = sonuc_usd` verilir (toplam ve "en iyi hariç toplam"
  $ ile anlamlı; oranların toplamı işaret değiştirebilir).
- Son 6'ya ulaşmayan aday geçemez (mevcut kural). Açık pozisyon sayılmaz.

---

## 5. A2 veri hattı tasarımı (Sonnet uygular)

### 5.1 İş akışları ve zamanlama

| İş akışı | Ne yapar | Zaman (UTC) | Süre bütçesi | Çıktı (veri dalı yolu) |
|---|---|---|---|---|
| `copytrade_kapi.yml` (870974e^'dan geri getir) | CT-Kapı **tam** koşu, 48 parça + birleştirme + akıl sağlığı | Cumartesi 18:43 (`43 18 * * 6`; TSİ 21:43) + elle | plan 10 dk; parça ≤ 120 dk; birleştirme ≤ 90 dk; **toplam ≤ 4 sa** (Pazar 10:00'a ≥ 11 sa pay) | `copytrade-kapi:copytrade/kapi/<tarih>/{sonuc.csv, durum.json, RAPOR.md, evren.json}` |
| `izleme.yml` (870974e^'dan geri getir) | Saatlik `izleme_motoru` (kadro 50 + §7 K‑12.8 kapsamı); `sanal_kopya_v3.kapanan_islemler` ve `ilk11_form_ham` dahil | her saat :23 | ≤ 55 dk (K‑10: 91 trader ≈ 45 dk); `concurrency` ile çakışma yok | `copytrade-izleme:izleme/durum.json`; `motor.json` R2'de (`izleme/motor.json.gz`, eski düzen) |
| `ilk11_pazar.yml` (yeni) | `pazar_akis` planına göre ilk seçim ya da form + `pazar_gecis` + uygulama | Pazar 10:07, 12:07, 14:07, 16:07, 18:07 (`7 10-18/2 * * 0`) + elle | ≤ 15 dk (HL çağrısı yok) | `copytrade-kapi:ilk11/<pazar-tarihi>/…` (§5.3) |
| `ilk11_deneme.yml` (yeni, elle) | Kural 1 küçük gerçek veri denemesi (§5.6) | elle | ≤ 30 dk | Actions artifact (veri dalına yazmaz) |

- **Telegram / Cloudflare Worker A2 kapsamı dışındadır (K‑13).** Seçim ve veri akışı Worker'a bağlı değildir; Worker'a kod/secret
  değişikliği yapılmaz, `worker.yml`'in secret adımında kırmızı bitmesi beklenen durumdur. Telegram'a özet/uyarı maddeleri Worker yeniden
  bağlanana kadar yalnız RAPOR + Actions iş özeti (`$GITHUB_STEP_SUMMARY`) olarak yazılır.
- Worker iş akışı tetiklemez (DURUM); hepsi cron + `workflow_dispatch`.
- Cron gecikmesi (Actions) tolere edilir: Pazar işi as_of'u **saatten değil takvimden** (o haftanın Pazar 13:00 TSİ) alır.

### 5.2 Modüller (var olanı yeniden kullan)

| Modül | Durum | Sorumluluk |
|---|---|---|
| `copytrade/ilk11_alanlar.py` | **yeni**, saf (ağ/dosya yok) | `pencere_getiri`, `pencere_dusus`, `pozitif_gun_orani` (hepsi `kapi.twr_chain` üstünde), `kazanma_orani` (`closed_round_trips`), `ilk_alanlar(kapi_satiri) → (form_ham, alan_kaynagi)`, `form_ham_30g(fills, portfolio, hesap, v3, now)`, `akil_sagligi(alanlar, rules)`. 10 alanın tek hesap yeri. |
| `copytrade/ilk11_pazar.py` | **yeni**, CLI | Girdi seçimi (kapı klasörü, as_of'a göre `durum.json` sürümü), uygunluk (§2), ilk seçim (`ilk11_veri.snapshot_olustur`) ya da form snapshot + `ilk11.pazar_gecis`, planı izleme listesine uygulama, `pazar_akis.pazar_akis_plani` durumu (`akis.json`), RAPOR. Yalnız dosya üretir; commit iş akışında. |
| `copytrade/olcut.py` | değişir (bilgi) | `calculate_metrics` → `kazanma_orani` (yalnız bilgi sütunu; kapı adımı kullanmaz). |
| `copytrade/kapi.py` | değişir (bilgi) | `evaluate_address`: zaten çekilen `portfolio`'dan `ilk11_ay_roi`, `ilk11_hafta_roi`, `ilk11_dusus_30g`, `ilk11_tutarli_30g` (`ilk11_alanlar` çağrısı). Adım mantığı, eşikler, `HESAP_SURUMU` **değişmez**; `RATIO_COLUMNS`'a `ilk11_dusus_30g`, `ilk11_tutarli_30g`, `kazanma_orani` eklenir (akıl sağlığı). Karar §7 K‑12.11. |
| `copytrade/defter.py` + `kopya_v3.py` | değişir (çıktı) | `copy_ledger` kapanan kopya işlemlerini listeler; v3 `kapanan_islemler` yayımlar. Bakiye/getiri aynı (eski ↔ yeni sayılar PR'da yan yana; fark 0 olmalı). |
| `copytrade/izleme_motoru.py` | değişir | trader başına `ilk11_form_ham`; `motor.json`'da `ilk11_gecerli_saat`; izleme listesini veri dalından okuyabilme (`--liste` parametresi). |
| `copytrade/ilk11_veri.py` | değişmez | `form_esle` saat→dakika (×60) #461 ile doğru; A2'de `form_ham` yolu esas (10 alan açıkça verilir). |
| `copytrade/ilk11.py`, `pazar_akis.py` | **değişmez** | Puan, dağıtım, 60/40, terfi kapısı, yeniden deneme. |
| `copytrade/kurallar.yaml` | ekleme | `ilk11_kapi_tazelik_gun: 7`, `ilk11_form_tazelik_dk: 120`, `ilk11_form_min_dolu_alan: 8`, `ilk11_min_doluluk: 0.90`, `ilk11_min_uygun: 11`, `ilk11_saglik` (§3.2 aralıkları), `ilk11_form_pencere_gun: 30`. Kodda sayı yok (görev 23 testi). |

### 5.3 Pazar işi girdi/çıktı
- **Girdi:** `copytrade-kapi:copytrade/kapi/<tarih>/sonuc.csv` + `durum.json`; `copytrade-izleme:izleme/durum.json` (git sürümü
  as_of'a göre); önceki `ilk11/<önceki pazar>/snapshot.json` (kadro, `onceki_pazar_aktif`); `kurallar.yaml`.
- **Çıktı (`copytrade-kapi:ilk11/<YYYY-MM-DD>/`):**
  - `snapshot.json` — `snapshot_id` + gövde; ilk seçimde `sema: ilk11-pazar-v1` (mevcut), formda `sema: ilk11-form-v1`
    (aynı kanonik JSON + SHA-256 kuralı, `snapshot_json` ile doğrulanır). `kaynak_surumu` en az: `kapi` (tarih + kurallar SHA),
    `izleme` (durum.json commit SHA + `uretildi`), `ilk11_alanlar` (dosya SHA), `kurallar` (SHA).
  - `alanlar.csv` — aday başına 10 ham alan, 10 yüzdelik, puan, `alan_kaynagi`, `uygun`, `uygunluk_nedeni`.
  - `plan.json` — `pazar_gecis` çıktısı (formda) ya da ilk dağıtım.
  - `akis.json` — `{deneme_sayisi, snapshot_id, son_basarisiz_at, basarili}` (`pazar_akis` girdisi).
  - `RAPOR.md` — §6 tablosu (doluluk, min/medyan/max, ihlaller, 11/11/28, uyarılar).
- **Kadro listesi:** `copytrade-kapi:ilk11/izleme_listesi.yaml` (izleme motoru şeması: `takim`, `snapshot_id`, `form_puani`,
  `takim_hafta` alanları **zaten** destekleniyor). Saatlik izleme bu dosyayı `copytrade/izleme_listesi.yaml` yerine okur; `main`'e
  otomatik yazım yok (AGENTS: main'e doğrudan push yok). Yeni kadro üyesine yeni `id` + `t0` = snapshot günü (motor t0 değişmezliği).
  Pilot listesinde zaten olan adres tek satırda kalır (adres tekilliği), `takim` eklenir; `paper_sonuclari` `takim_hafta`'dan sonrasını sayar.
- `copytrade-kapi:son.json` işaretçisine `ilk11` anahtarı eklenir (son başarılı Pazar).

### 5.4 Akış (Pazar işi)
1. `pazar_akis_plani(now, deneme_sayisi, snapshot_id, …)` → `bekle` ise çık (yeşil).
2. `snapshot_hazirla`: girdileri as_of'a göre seç → uygunluk → alanlar (`ilk_alanlar` / `ilk11_form_ham`) → akıl sağlığı → doluluk kontrolü
   (§6.2) → snapshot. Hazırlık hatası **deneme sayılmaz**, iş kırmızı; bir sonraki cron (2 sa) baştan dener (girdi seçimi as_of'a
   bağlı → aynı sonuç).
3. `calistir` / `yeniden_dene`: plan + izleme listesi + `son.json` yazımı; veri dalına commit + push (yarışta `pull --rebase`, en çok
   5 deneme, eski iş akışı deseni). Push başarısızsa `basarili=false`, `son_basarisiz_at` kaydedilir; 2 sa sonra **aynı
   `snapshot_id`** ile.
4. `tamamla`: sonraki cron'lar hiçbir şey yazmaz.
- İlk seçim ve form kararı: veri dalında daha önce başarılı ilk seçim snapshot'ı yoksa → ilk seçim; varsa → form.

### 5.5 Hata davranışı
- `set -euo pipefail`; **`|| true` yok**. Kapı `durum: eksik` → kapı işi kırmızı (mevcut adım). Pazar işi eksik kapıyı reddeder (§2).
- Tüm izleme trader'ları hatalıysa izleme yayımlamaz (mevcut `RuntimeError`).
- Akıl sağlığı / doluluk tutmazsa snapshot yayımlanmaz, iş kırmızı, önceki kadro sürer; RAPOR artifact olarak yüklenir (gözle bakılabilsin).
- Ağ engeli (proxy 403) bu ortamda: sonuç uydurulmaz; doğrulama yalnız Actions çıktısıyla.

### 5.5a Silinen iş akışı testlerinin kuralları yeniden kurulur
870974e iş akışlarını sildiğinde onları koruyan testler de (`test_esik_5000`, `test_izleme_is_akisi`, `test_eksik_koşu_dis_aday`,
`test_secim`, `test_son_json` vb. iş akışı testleri) kalktı/uyarlandı. A2'nin geri getirdiği ve yeni yazdığı her iş akışı için **yeni
testler** aynı kuralları sınar (YAML metni ve çalışma davranışı üstünden):
- Hata **`|| true` ile örtülmez**; `set -euo pipefail` (her `run:` bloğunda).
- **Eksik koşu kırmızı biter ama kısmi sonuç yine yazılır** (kapı: `durum: eksik` + RAPOR veri dalına yazılır, sonra iş kırmızı;
  `kesif.json`/İlk 11 snapshot eksik koşudan üretilmez).
- **Plan günü ile parça günü aynı:** plan işinin seçtiği `--tarih` tüm parçalara ve birleştirmeye aynen geçer (gece yarısını aşan koşu
  iki klasöre bölünmez); Pazar işinde as_of tarihi takvimden.
- Veri dalına yazım yarışında `pull --rebase` + sınırlı yeniden deneme; `main`'e yazım yok.
- İzleme: R2'den `motor.json` geri yükleme, kısmi sonuç yazımı ve "tüm trader hatalı → yayın yok" davranışı.

**A2'de temizlenecek artıklar** (silinen iş akışlarından kalan, artık hiçbir şeyin tetiklemediği dosyalar): `copytrade/kapi/CALISTIR`,
`copytrade/secim/CALISTIR`, `.github/scripts/kapi_yayimla.sh`, `.github/scripts/izleme_yayimla.sh` — geri getirilen iş akışı
bunlardan birini gerçekten kullanmıyorsa silinir (kullanıyorsa yeni testle bağlanır); `.github/scripts/son_yaz.py` ve
`.github/scripts/__pycache__` de aynı denetimden geçer.

### 5.6 Kural 1 — küçük gerçek veri denemesi (A2 PR'ından önce zorunlu)
- **Kapı tarafı:** 28 Ekim adaylarından 5 adres (2 intraday, 2 swing, 1 `kopyalanabilir`; biri büyük ≥ 1 M$, biri küçük < 50 k$ hesap):
  `ilk11_deneme.yml` → `evaluate_address` + `ilk_alanlar` (kapıya `--yalniz-adres` benzeri dar mod). Gözle: 10 alan dolu mu, `ay_roi`
  ve `hafta_roi` [−1, 10] içinde mi, `month`/`week` `pnlHistory` nokta sayısı, `tutma` dakika mı (saat değil), `kaldirac` kapıyla aynı mı.
- **İzleme tarafı:** aynı 5 adres, 1 saatlik izleme (`izleme_motoru` deneme listesiyle): `kapanan_islemler` satırları, `getiri`
  aralığı, `ilk11_form_ham` doluluğu, koşu süresi (trader başı sn → 50 trader bütçe tahmini).
- **Pazar işi:** bu iki çıktıyla `ilk11_pazar --deneme` (as_of = son Pazar 13:00): 5 kişilik evrende puan, snapshot_id iki koşuda aynı.
- PR açıklamasına: komutlar, satır sayısı, her sütunun min/medyan/max'ı, gözle bulunan sorunlar.
- Uç durum testleri (sentetik, gerçek veriden esinli): sıfıra yakın payda (hesap ~0 dönem), boş hesap, kapanmış işlemi olmayan trader,
  `pnlHistory` < 2 nokta, eksik mum (fiyatsız yürütme), 10.000 dolum sınırı, büyük `motor.json`.

### 5.7 Geçici kadro
- Acil kadro (`2669673:sg-pano/veri/ilk11/son.json`) `main`'den pano ile birlikte zaten silindi (26e3f97); hiçbir iş akışı onu okumaz.
- İlk gerçek Pazar snapshot'ı yayımlanınca: geçici kadroya ait kalan her kopya (veri dalı, Worker sabitleri, belge örnekleri) kaldırılır;
  belgelerde yalnız "geçici, 2026-11-01, kaldırıldı <tarih>" notu kalır. `ilk11_pazar` geçici kadroyu `onceki` kadro **saymaz**
  (ilk gerçek koşu ilk seçimdir).

---

## 6. Kabul kanıtı (A3) — ilk gerçek Pazar koşusu

Lider/denetçi `RAPOR.md` + `alanlar.csv` + `snapshot.json`'a **gerçek çıktıda** bakar (kalite kuralı 3). Hepsi tutmadan "bitti" denmez.

1. **Kadro:** `secim_adedi == 50` (ya da §2'ye göre uyarılı daha az), `ilk11 = 11`, `yedek11 = 11`, `paf = 28`; adresler benzersiz;
   hepsi `uygun == true`; uygun evren sayısı ve kapı tarihi raporda.
2. **Doluluk:** uygun evrende her alan için `dolu / uygun ≥ ilk11_min_doluluk` (%90). Tablo: alan | dolu | eksik | ihlal | kaynak.
   Herhangi biri < %90 ise snapshot yayımlanmamış olmalı (iş kırmızı).
3. **Dağılım:** her ham alan ve her yüzdelik + `puan` için min / medyan / max; sabit sütun yok (tüm değerler aynı = hata);
   puan aralığı makul (0 < min, max < 100; herkes 35 civarı = alanlar dolmamış demektir).
4. **Akıl sağlığı:** §3.2 aralıkları; `ay_roi` ≤ 10 (1805 türü yok), oranlar 0–1, `tutma` dakika (saat değil: 28 Ekim adaylarında tutma 1,0–281 sa
   ≈ 61–16.800 dk, medyan 20,5 sa ≈ 1.230 dk; değerler bu mertebede olmalı), `kaldirac` kapıyla aynı, `hesap ≥ 5.000 $`.
5. **snapshot_id doğrulaması:** (a) `snapshot_json(snapshot)` hata vermez; (b) aynı girdi dosyalarıyla yeniden üretim aynı `snapshot_id`;
   (c) `as_of` = Pazar 13:00 TSİ; (d) `kaynak_surumu` SHA'ları dosyalarla eşleşir; (e) yeniden deneme olduysa `akis.json`'daki kimlik aynı.
6. **Altın örnek testleri (elle hesaplı, girdi + beklenen sayı; A2 PR'ında):**
   1. `pencere_getiri`: hesap 1.000 $, PnL 0 → +100, akış yok → **0,10**; dönem ortasında +1.000 $ yatırma (ΔPnL 0) → getiri değişmez.
   2. `pencere_getiri` 7 gün kesimi: 8. günden önceki PnL sayılmaz.
   3. `pencere_dusus`: özsermaye 1,0 → 1,2 → 0,9 → 1,0 → **0,25**.
   4. `pozitif_gun_orani`: günlük ΔPnL [+5, −3, 0, +2] → **2/3**.
   5. `kazanma_orani`: net [+10, −5, +3, −1] → **0,5**; ücret yüzünden −0,2'ye dönen işlem kaybeden sayılır; tersine dönüşte iki işlem.
   6. `siklik`: 30 günde 12 işlem → **0,4/gün**; `siklik_puani(0,4)` = **0,4**.
   7. `tutma`: tutma saatleri [1, 2, 30] → medyan 2 sa → **120 dk**; `tutma_puani(120)` = 1 − 0,6·log10(4)/log10(8) = **0,6**.
   8. `kaldirac`: efektif 2x → `kaldirac_puani` = **0,9**.
   9. `hesap`: 255.000 $ → sqrt(0,5) = **0,7071**.
   10. `golge` İ: intraday satır, `gecikme_30dk_net = 0,12`, `gecikme_120dk_net = 0,30` → **0,12** (tarz gecikmesi).
   11. `golge` F: getiriler [0,10, −0,05, 0,20] → ort 0,0833, büzülmüş 0,0833·3/11 = **0,02273**.
   12. v3 `kapanan_islemler`: tek coinde aç-kapa (maliyet + funding) → `sonuc_usd` elle; ters dönüşte 2 satır; t0 öncesi açılmış → `gecerli: false`;
       `kapanan_islemler` eklendikten sonra `bakiye_usd`/`getiri` eski sürümle **aynı** (fark 0).
   13. Terfi kapısı: `sonuc_usd` [+3, −1, +2, −1, +1, −1] → toplam 3, kazanma 0,5, en iyi hariç **0 → geçmez**;
       [+3, −1, +2, −1, +2, −1] → en iyi hariç **1 → geçer**.
   14. Akıl sağlığı: `ay_roi = 1805` → `None` + `akil_sagligi_ihlali:1805`; 20 adaydan 2'sinde ihlal (%10 > %5) → koşu kırmızı.
   15. Uygunluk: kapı klasörü 8 gün eski → reddet; `satir_kaynagi = onceki_dosya_ayni_hesap` → `uygun: false, eski_satir`;
       `katman = yok` → `katman_yok`.
   16. Az aday: 49 uygun → `kapasite_bos = 1`, `uyari` dolu, PAF 27; 10 uygun → yayın yok.
   17. `form_esle`: `medyan_tutma_saat = 3,5` → `tutma = 210` dk (#461'de var; korunur) ve kapı satırından `median_holding_hours = 3,5` → `form_ham.tutma = 210`.
   18. Form: `bu_pazar_gecerli` — 7 alan dolu → `false` (hareket yok); veri 3 sa eski → `false`; `bu_pazar_aktif` — 7 gün içinde tek perp dolumu → `true`, yalnız spot → `false`.
   19. Snapshot deterministik: aynı girdi iki kez → aynı `snapshot_id`; tek alan değişimi → farklı kimlik ve `snapshot_json` reddi.
7. Tam test paketi `python -m pytest -q` yeşil; sonuç PR açıklamasında.

---

## 7. Kararlar (K‑12.1–K‑12.11)

**Karar verildi (kullanıcı, 2026-11-02):** "Önerilerini kabul ediyorum; amacım verilerin doğru gelmesi ve kaydedilmesi." Önerilen seçeneklerin
tümü onaylandı. Vurgu: önce verinin doğru gelmesi ve kalıcı kaydı. Açık karar yoktur; kilitli değerlerin (ağırlık, dönüşüm, 60/40,
11/11/28, terfi kapısı) hiçbiri değişmedi.

- **K‑12.1 `golge` (ilk seçim) kaynağı — Karar verildi (2026-11-02):** kapının tarz gecikmeli kopya neti (`secim.puan`, 200 gün).
  Form tarafı v3 `kapanan_islemler`.
- **K‑12.2 `tutarli` tanımı — Karar verildi (2026-11-02):** pozitif gün oranı, 30 gün, payda = PnL'i değişen günler.
- **K‑12.3 `kaldirac` anlamı — Karar verildi (2026-11-02):** efektif kaldıraç (kapının ölçüsü), dönüşüm aynen. Not: adaylar 0,03–2,87x
  olduğundan dönüşüm bu aralıkta yüksek kaldıraca daha yüksek puan veriyor; ilk gerçek kadrodan sonra etkisi raporlanır (A3 RAPOR),
  değişiklik ayrı kullanıcı kararıdır.
- **K‑12.4 İlk seçim penceresi (`kazanma/siklik/tutma/kaldirac`) — Karar verildi (2026-11-02):** kapı penceresi (365 gün); form 30 gün.
- **K‑12.5 Form yüzdelik evreni — Karar verildi (2026-11-02):** kadronun 50 kişisi.
- **K‑12.6 Kadro boşluğu — Karar verildi (2026-11-02):** her Pazar, kadroda olmayan uygun adaylar İlk 11 puanıyla sıralanır; boş PAF
  yerine en iyisi girer (yalnız PAF'a giriş).
- **K‑12.7 Pazar planı — Karar verildi (2026-11-02):** otomatik uygulanır (PAPER); RAPOR/iş özetinde özet (Worker dönünce Telegram);
  kullanıcı istediğinde `gecis.py` kaydıyla geri alınır.
- **K‑12.8 İzleme kapsamı — Karar verildi (2026-11-02):** kadro 50 + sabit referans kolları (`referans_oda` + `referans_kontrol`, 36).
  Eski pilot kolları (oda, kontrol, taban, elle, havuz, cikarilan) saatlik izlemeden çıkar; geçmiş veri dalda kalır, silinmez.
  Not (lider, 2026-11-02): 36 referans = mevcut `izleme_listesi.yaml`'da `kol`/`kollar`'ında `oda` (18) ve `kontrol` (18) olan satırlar; `id`/`t0` korunur, `referans_oda`/`referans_kontrol` olarak etiketlenir.
- **K‑12.9 Az aday eşiği — Karar verildi (2026-11-02):** uygun < 11 → yayın yok; 11–49 → uyarılı yayın.
- **K‑12.10 Veri kalitesi parametreleri — Karar verildi (2026-11-02):** kapı tazeliği 7 gün, form tazeliği 120 dk, form geçerliliği
  ≥ 8/10 alan, alan doluluğu ≥ %90, §3.2 akıl sağlığı aralıkları, ihlal > %5 → kırmızı (`kurallar.yaml` `ilk11_*`).
- **K‑12.11 Kapıya bilgi sütunu — Karar verildi (2026-11-02):** `kapi.py`/`olcut.py`'ye 5 bilgi sütunu (`ilk11_ay_roi`, `ilk11_hafta_roi`,
  `ilk11_dusus_30g`, `ilk11_tutarli_30g`, `kazanma_orani`); veri bir kez çekilir. Adım mantığı/eşik değişmez; dondurma SHA'sı değişir.
