# GÖREV T3 — Tek boyutlandırma + R2 form puanı + günlük kadro (Sonnet)

Dayanak: `docs/RADAR_V1.md` §3–§5b, K‑26…K‑28. Dal: `claude/t3-form-kadro` (main'den, T2 birleştikten sonra). Tek PR.

## 1. Tek boyutlandırma (K‑28, önce bu)
- Yeni `copytrade/boyut.py`: `RADAR_V1.md` §5b'nin **tek** uygulaması. Saf fonksiyon (ağ yok):
  `hedef_emir(eylem, trader_poz_once, trader_poz_sonra, trader_hesap_usd, biz_poz_usd, slot_usd, fiyat, rules) -> (emir_usd | 0, neden)`.
  Kurallar: açılış = slot × (trader nosyonel / trader hesap), tavan 3,0 × slot; < 11 $ → 3,0 × slot ≥ 11 ise 11 $, değilse 0 (`min_emir_atlandi`);
  artırma/azaltma trader'ın değişim oranıyla; < 11 $ azaltmada kalan < 11 $ ise tamamı kapat, değilse 0; artırmada 0; trader tam kapanış → tam kapanış.
- Yeni `copytrade/kopya_v5.py` = `kopya_v4` risk katmanı + `boyut.hedef_emir` (sabit tutar eğrisi yerine). Slot = `canli_kasa_usd / N`, `N = min(11, taban(canli_kasa_usd / radar_canli_slot_min_usd))`
  (`canli_kasa_usd` kullanıcı ayarı, varsayılan 1000; K‑30). R1/6 kopya testi de bu slotla oynatır. Kural 6: v4 **silinmez**; R1/6 kopya testi v5'e geçer; PR'da aynı havuzda v4 ↔ v5 kopya getirisi yan yana (20 aday).
- Altın örnekler (elle): kasa 100 → N 4, slot 25; kasa 250 → N 10, slot 25; kasa 500 → N 11, slot 45,45; kasa 1000 → slot 90,91; trader hesap 100.000, 30.000 $ açılış → 27,27 $; 5.000 $ açılış → 4,55 → 11 $; trader %50 azaltır, biz 27,27 →
  13,64 $ satış; biz 15 $ iken trader %40 azaltır → 6 $ < 11 ve kalan 9 < 11 → 15 $ tam kapanış; tavan: 400.000 $ açılış → 272,73 $.

## 1b. R1/6 kopya koruma (K‑32) ve tarama dayanıklılığı
- `radar_tarama` kopya testi v5'e geçer ve **iki oynatma** yapar: kopya (1 dk gecikme + maliyet) ve ayna (`kopya_v5`, gecikme 0, maliyet 0); ikisi pencere başında boş,
  aynı slot. `kopya_koruma = kopya_getiri_7g / ayna_getiri_7g`; ayna ≤ 0 → `kopya_koruma_dusuk`. Yeni alan `ayna_getiri_7g` (oran, kasa ölçeğinde) sözleşmeye.
  Altın örnek (elle): tek long 100→110, slot 90,91, trader nosyonel/hesap 0,5 → ayna ve kopya sayıları testte yazılı; oran elle.
- HL 5xx yanıtı (300 koşusunda 1 kez `500 Internal Server Error`): `PublicClient` 5xx'i 429 gibi en çok 3 kez artan beklemeyle yeniden dener; sonra `veri_hatasi`. Test ile.
- **Bilgi (karar değil):** 300 koşusunda `islem_az` 184/300 (medyan 3 işlem). `radar_deneme.yml`'e yalnız deneme için `kural_ust` girdisi (`anahtar=deger`)
  eklenir (günlük `radar.yml`'de YOK); `radar_min_islem=5` ile ikinci koşu, iki koşunun `gecti` sayısı ve neden dağılımı PR'da yan yana. Eşik kararını lider verir.

## 2. R2 form puanı (`copytrade/radar_form.py`)
- Girdi: T2 `havuz.json` (yalnız `gecti`). `RADAR_V1.md` §4 aynen: G (0,35), K (0,15), İ1 kârlı gün oranı (0,10), İ2 düşüş (0,10, az = iyi),
  Y yayılma (0,10), H hype (0,20); her biri havuz içi yüzdelik (0–100, eşitlikte ortalama sıra); `form` = ağırlıklı toplam.
- H: trend coin = HL perp coinleri içinde |7 g getiri| üst %25 **ya da** listelenme ≤ 30 gün (`meta` + ilk mum zamanı); erken giriş = pozisyon,
  coinin 7 g hareketinin (saatlik mum, trader yönünde) %50'si gerçekleşmeden açılmış; H = erken-trend girişlerin brüt kârdaki payı (kâr yoksa 0).
- "Form sürüyor": son 72 sa kopya getirisi ≥ −%2, değilse puanlanmaz (`neden: soguyor`).
- İ1/İ2/K/G için gereken günlük kopya özsermayesi T2 oynatmasından gelir; T2 satırına gerekiyorsa alan ekle (sözleşmeye yaz).
- Benzer trader: `son7g` günlük kopya getirisi korelasyon matrisi (İlk 11 adayları için) `kadro.json`'a yazılır (canlı motor §6 kuralını uygular).

## 3. Günlük kadro (`copytrade/radar_kadro.py`)
- Sıra = form azalan; 1–11 `ilk11`, 12–30 `yedek`. `kadro.json`: `{"sema": "radar-kadro-v1", "kosu_ms", "kasa_usd", "slot_usd", "satirlar": [
  {adres, sira, katman, form, bilesenler{G,K,I1,I2,Y,H}, kopya_getiri_7g, max_kaldirac}], "korelasyon": {...}}`.
- **Saha kararları burada değil** (canlı sonuca bağlı: slot −%10, bekleme, günde 2 değişiklik) → T4 motoru `kadro.json`'u okuyup §5 kurallarını uygular.
- İş akışı `radar.yml`: her gün **00:37 UTC** T2 taraması → R2 → kadro; çıktılar veri dalı `radar`'a (orphan değil, tarihli klasör; 90 gün tutulur):
  `radar/<tarih>/{havuz,kadro}.json` + `radar/son/kadro.json`. Hata `|| true` ile örtülmez; eksik koşuda `son/` güncellenmez.

## 4. Testler ve kabul
- Altın örnekler: §1 boyut örnekleri; yüzdelik (3 kişi [1,2,3] → 0/50/100), ağırlıklı form elle; H için 1 trend + 1 trend dışı coinle elle pay;
  `soguyor` sınırı (tam −%2 geçer). Sözleşme: `VERI_SOZLESMESI.md` "Radar kadro" bölümü (birimler).
- Gerçek veri (önce): `radar_deneme.yml` aday 300, v5 + K‑32 ile → `gecti`, neden dağılımı, `kopya_koruma`/`ayna_getiri_7g` min/medyan/max; ardından `radar_min_islem=5` bilgi koşusu (§1b).
- Gerçek veri: `radar.yml` elle 1 kez (aday 300) → `kadro.json` PR'da: İlk 11 + Yedek listesi, her bileşenin min/medyan/max'ı, v4 ↔ v5 tablosu.
- `python -m pytest -q` yeşil; `DURUM.md` güncel.
