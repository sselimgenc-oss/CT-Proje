# Araştırma: Trader sinyali HL'den, emir BINANCE USDⓈ-M Futures'ta

Tarih: 2026-11-20. Yalnız araştırma; bot koduna dokunulmadı. Cüzdan adresi yazılmadı.

**Sonuç (kısa): KISMEN yapılabilir.** Coin kapsaması iyi (47/50 coin; emirlerin %98,0'i, hacmin %98,9'u) ama "gecikmesiz" olamaz, Hollanda'dan erişim büyük olasılıkla yasak, ve fiyat sapması riski HL'ye göre artar. Ayrıntı en altta.

## Veri ve yöntem (neye ne kadar güvenilir)

| Konu | Kaynak | Güven |
|---|---|---|
| Bizim işlemler | `origin/canli-durum` kayıtları 16.11 11:32 – 20.11 14:58 (UTC). 14 ve 15.11 dosyaları dalda **yok**; yani ~4,1 gün, 7 gün değil. 302 dolu (sanal) emir, 31.719 $ hacim. | Ölçüm |
| HL fonlama / hacim / defter | HL API (`metaAndAssetCtxs`, `l2Book`) 20.11'de canlı çekildi | Ölçüm |
| Binance perp listesi | Bu ortamdan Binance API ve binance.com engelli. Üçüncü taraf GitHub'daki exchangeInfo dökümü (`MoeAZack/ZackBot2`, `binance-um-exchangeinfo-v2-20261011.json`, Binance'ten 11.10.2026'da alınmış, 924 sembol, 525 USDT-TRADING). **40 günlük**; yeni listeler/delistler eksik olabilir. | Orta |
| Binance kuralları/ücret/limit | WebSearch arama özetleri (WebFetch bu ortamda engelli, sayfaların kendisini okuyamadım) | Orta-düşük, aşağıda her satırda işaretli |
| Binance fiyat/derinlik | Ölçülemedi. Tahmin. | Düşük |

Yardımcı betik: `araclar/binance_kapsama.py` (kayıtları ve exchangeInfo dökümünü okuyup kapsama + gecikme basar).

## 1. Kapsama

Eşleme: coin adı + `USDT`; HIP-3 öneki (`xyz:`, `io:`) atılır (ör. `xyz:NVDA` -> `NVDAUSDT`); `kSHIB` -> `1000SHIBUSDT`.

| | Emir sayısı | Hacim ($) | Gerçekleşen K/Z ($) | Coin sayısı |
|---|---|---|---|---|
| Binance'te **var** | 296 (%98,0) | 31.364 (%98,9) | -31,87 | 47 |
| Binance'te **yok** | 6 (%2,0) | 355 (%1,1) | +10,80 | 3 |
| Toplam | 302 | 31.719 | -21,08 | 50 |

- Yok: `PURR` (3 emir, K/Z +10,76 $), `xyz:ANT` (2 emir, +0,04), `xyz:XYZ100` (1 emir, 0). Bu üçü dökümde hiç geçmiyor.
- HIP-3 (hisse vb.): 18 coin, 74 emir, 5.718 $ hacim, K/Z +5,17 $. Bunların 15'i Binance'te **"TradFi perp"** olarak var (NVDA, SNDK, GOOGL, META, MSFT, AMZN, AMD, INTC, MU, PLTR, BE, DRAM, SOXL, SPCX; `io:NVDA`/`io:SNDK` aynı hisseye eşleşir). Dökümde 179 hisse + 8 emtia TradFi perp'i var.
- **Emin değilim:** `xyz:SPCX`, `xyz:DRAM`, `xyz:BE`, `xyz:SOXL` aynı sembol adıyla var ama aynı dayanak varlık mı, doğrulanmadı. `io:` markalı kontratların dayanağı da HL'de aynı hisse fiyatını mı izliyor, Binance'inkiyle bire bir mi, kontrol gerekir.
- Binance TradFi perp açmak için kullanıcının ayrıca "TradFi-Perps sözleşmesi" imzalaması gerekiyor olabilir (Aralık 2025'te API'ye bu uç noktanın eklendiği haberi; şartları bulamadım).
- K/Z payı: toplam K/Z negatif (-21 $), yani "yok" grubu kâr tarafında. Ama 6 emir/3 coin = küçük örnek; sonuç çıkarılamaz.

## 2. Gecikme

Kayıt alanları: `trader_dolum_ms` (trader'ın HL dolumu), `gorme_ms` (bizim görmemiz), `emir_ms`, `dolum_ms`. Trader sinyaliyle tetiklenen 262 emir (kaynak `userFills`+`trades`):

| Bölüm | Medyan | p90 |
|---|---|---|
| Trader dolumu -> bizim görmemiz (HL'den izleme) | **0,36 sn** | 0,48 sn |
| Görme -> emir gönder -> dolum (şimdi sanal, HL fiyatı) | 0,17 sn | 0,29 sn |
| **Toplam trader -> bizim dolum** | **0,57 sn** (tüm 302 emirde 0,56) | 0,99–1,09 sn |

Senin "~0,7 sn" bilgin doğrulandı: gerçek medyan 0,56–0,57 sn, p90 ~1 sn. (Telafi emirlerinde ~96 sn, "kapat" kaynaklı emirlerde 0,22 sn; bunlar sinyal gecikmesi değil.) Not: "emir->dolum" 0,17 sn **sanal** kipte; gerçek HL emrinin ağ süresi değildir.

**Binance'e geçince:** İzleme hâlâ HL'den, yani 0,36 sn sabit kalır. Değişen kısım emir yolu.

| Parça | Tahmin | Dayanak |
|---|---|---|
| Amsterdam -> Tokyo RTT | **~210–260 ms** (tahmin) | AWS Dublin–Tokyo ölçümü ~211 ms (AWS çalışması, 2021); Amsterdam biraz daha uzak. Ölçülmedi. |
| Binance eşleştirme motoru yeri | Tokyo (AWS ap-northeast-1) olarak yaygın aktarılıyor (Glassnode: WS/FIX doğrudan AWS Tokyo'ya gidiyor). Tek bir blog ise USDT-M motoru için us-east-1 diyor; doğrulanmadı. | Orta-düşük |
| Kalıcı WebSocket emir (1 RTT) + motor işleme | ~230–280 ms | Tahmin |
| **Toplam (HL'den görme + Binance emri)** | **~0,6–0,65 sn medyan** | 0,36 + ~0,25–0,3 |

Yani Binance bugünkü 0,57 sn'ye göre kabaca **+0,05–0,1 sn** ekler; bu, HL'nin emir yolunun gerçekte ne kadar sürdüğüne bağlı (HL ucu Amsterdam'dan kaç ms, ölçmedim). **"Gecikmesiz" mümkün değil:** sinyali HL'de görmek en az ~0,36 sn, Binance'e ulaşmak ~0,25 sn daha. Fiyat, trader HL'de dolduktan en az ~0,6 sn sonrasına göre alınır.

## 3. Fiyat farkı, fonlama, likidite

**HL tarafı (canlı, 20.11; 24s hacim, spread, kayma ölçüldü):**

| Coin | 24s hacim | HL spread | HL kayma 50 $ / 300 $ (al yönü) | Fonlama (8 sa eşdeğer) |
|---|---|---|---|---|
| BTC | 5,48 Mr $ | 0,2 bp | 0,1 / 0,1 bp | +0,0031% |
| ETH | 1,05 Mr | 1,7 bp | 0,9 / 0,9 | -0,0055% |
| SOL | 201 Mn | 0,7 bp | 0,4 / 0,4 | +0,0050% |
| HYPE | 800 Mn | 0,2 bp | 0,1 / 0,6 | +0,0100% |
| ZEC | 283 Mn | 0,6 bp | 0,3 / 0,3 | +0,0100% |
| TRX | 1,5 Mn | 0,3 bp | 0,2 / 0,2 | -0,0254% |
| CAKE | 0,2 Mn | 3,9 bp | 1,9 / 1,9 | -0,0314% |
| VVV | 12 Mn | 8,7 bp | 4,4 / 7,0 | +0,0100% |
| WLFI | 0,9 Mn | 3,4 bp | 1,7 / 2,2 | +0,0021% |
| xyz:NVDA | 444 Mn | 0,7 bp | 0,4 / 1,3 | +0,0278% |
| xyz:SNDK | 147 Mn | 0,1 bp | 0,1 / 1,8 | +0,0106% |
| xyz:SPCX | 151 Mn | 0,8 bp | 0,4 / 0,4 | +0,0050% |
| xyz:META | 57 Mn | 6,3 bp | 3,2 / 3,2 | +0,0050% |
| io:NVDA | 27 Mn | 2,1 bp | 1,1 / 1,5 | +0,0257% |
| PURR (Binance'te yok) | 0,8 Mn | 34,9 bp | 17,4 / 17,5 | +0,0100% |

(bp = baz puan = %0,01.) HL'de bizim 50–300 $ emirlerimiz için kayma çoğu coinde 1 bp altı; bu emir boyutunda likidite HL'de sorun değil.

**Binance tarafı (ölçemedim, tahmin):** Majörlerde (BTC/ETH/SOL/XRP) Binance derinliği HL'den belirgin büyük (bir kaynak: günlük perp hacmi Binance ~51,7 Mr $ vs HL ~3,8 Mr $, tek örnek). 50–300 $ için kayma ~0–1 bp beklenir (tahmin). Küçük altlarda (CAKE, WLFI, TRX, VVV) Binance büyük olasılıkla HL'den daha derin. TradFi hisse perp'lerinde Binance derinliği bilinmiyor; gün içi hacimleri "çoğu >1 Mn $" diye aktarılmış (haber, Haziran 2026), 50–300 $ için sorun beklenmez ama spread geniş olabilir (tahmin).

**İki borsa arası fiyat farkı:** Ölçemedim (Binance engelli). Tek bir kişisel araştırma sayfası HL ETH-PERP ile Binance ETH spot arasında ortalama -3,8 bp, azami 17 bp, std ~2 bp farkı raporlamış (tek örnek, saat kayması karışmış olabilir). Tahminim: majörlerde 1–5 bp, orta altlarda 5–20 bp, HL'ye özgü ince coinlerde ve hisselerde (özellikle ABD piyasası kapalıyken, oracle/EWMA fiyatları farklı) daha fazla. Önemli olan: HL'deki trader fiyatı ile bizim Binance doldurma fiyatımız arasında **hem fark hem ~0,6 sn hareket** birikir. Bugün HL'de iken `kayma_trader` medyanı 0,4 bp, p90 6,6 bp, p99 33 bp; Binance'te buna fark da eklenir. Bu, ölçülmeden çıkarılamaz: öneri, kısa bir **iki borsa fiyat kaydı** (WebSocket, 1–2 gün) toplayıp gerçek farkı çıkarmak.

**Fonlama:** HL saatlik (tabloda 8 sa'e çevrildi), Binance 8 saatlik (TradFi'de çoğunlukla 8 sa, bazı kontratlarda 4 sa; kaynaklar tutarsız). Ana faiz bileşeni ikisinde de benzer (~%0,01/8 sa). Fark çoğunlukla coin/hisse talebine bağlı: HL'de bazı coinlerde (TRX -0,025%, CAKE -0,031%, xyz:NVDA +0,028%) 8 sa'lik eşdeğer büyük; Binance karşılığı ölçülemedi. Pozisyon süresi kısa (saat) olduğundan aylık etki küçük; ama uzun tutulan pozisyonda iki borsa fonlaması ayrışabilir.

## 4. Kurallar (Binance USDⓈ-M)

| Konu | Bilgi | Kaynak / güven |
|---|---|---|
| Min emir değeri (notional) | Genelde **5 USDT**; BTCUSDT için **100 USDT** olduğu bir Binance SSS'sinde yazıyor (başka kaynakla doğrulanmadı). Sembol bazlı, Binance haber vermeden değiştirebilir; asıl değer `exchangeInfo` MIN_NOTIONAL filtresinde. | Binance SSS özetleri; orta-düşük |
| Bizim emirler | Min dolum 10,7 $, hiçbiri 5 $ altı yok. Ama BTC'de 35 dolumun 9'u, ETH'de 42'nin 22'si 100 $ altı. 100 $ eşiği doğruysa bunlar (yeni açma/artırma ~18'i) reddedilir; azaltma/kapatma "reduceOnly" ile muaf olabilir (doğrulanmadı). | Hesap; eşik doğruysa |
| Adet adımı (LOT_SIZE stepSize) | Her sembolün adım/min adedi var; adet buna yuvarlanmalı. HL'nin `szDecimals`'ı ile Binance adımı farklı. Kısmi artır/azalt oranı yuvarlamayla kayar; çok küçük (<min adet) azaltmalar uygulanamaz, kapatmada kalıntı "toz" kalabilir. | Resmi doküman özeti; orta |
| Kaldıraç | Sembole ve notional kademesine göre (kademe tablosu API'de `leverageBracket`). Hisse perp'lerinde 20x'e kadar, TSLAUSDT'de 5x gibi, kontrata göre değişiyor. Bizim kaldıraç ihtiyacımız küçük. | Haber özetleri; orta |
| API hız sınırı | IP başına **2400 ağırlık/dk**; hesap başına **1200 emir/dk** ve **300 emir/10 sn**. Aşınca 429, ısrar edince IP banı (418; 2 dk–3 gün). Bizim ~75 emir/gün için fazlasıyla yeterli. | Binance SSS (Aralık 2024 güncel); orta |
| Pozisyon modu | `POST /fapi/v1/positionSide/dual`: tek yön (One-way) veya hedge. Tüm semboller için geçerli. Bizim kopya mantığı (coin başına net pozisyon, azalt/artır) **tek yön** modla uyumlu. Hedge modda `reduceOnly` gönderilemez, `positionSide` gerekir. | Resmi doküman özeti; orta |
| Stop emirleri | Koşullu (stop) emirler Binance'te son dönemde ayrı "Algo Order" uçlarına taşınmış görünüyor (dokümanda "Algo Order" başlıkları); ayrıntı doğrulanmalı. | Arama özeti; düşük |

## 5. Erişim / yasal (yalnız bilgi, karar kullanıcının)

- **Hollanda (sunucu Amsterdam):** Binance, 30 Temmuz 2021'de Almanya, İtalya ve Hollanda'da futures/türev ürünlerini kapattığını duyurdu (The Block, 2021-07-30; Binance resmi duyurusu "Unavailability of Futures and Derivatives Products in Germany, Italy, and the Netherlands"). İkincil bir kaynak Hollanda'nın Binance "yasaklı ülkeler" listesinde olduğunu söylüyor (resmi liste sayfasından 27.02.2024 tarihli, ama içeriği göremedim). Futures API'si IP'ye göre bölge denetler: kısıtlı IP'den **HTTP 451 "restricted location"**; Hollanda'daki bulut sunucularda görülmüş. Yani Amsterdam'daki DigitalOcean sunucusundan Binance Futures API'si büyük olasılıkla **451 verir**. (Sonradan AB'de yeniden açıldığına dair tek bir Rusça kaynak var; doğrulanmadı.) Bölgeyi atlatma (VPN/başka ülke sunucusu) Binance şartlarını ihlal edebilir; öneri değil.
- **Türkiye (kullanıcının kendisi):** Binance.com Türkiye'den erişilebilir kalacağını söyledi (2024); Türkçe destek ve reklam durduruldu, TRY çiftleri için Binance TR doğrulaması 27.11.2025'e kadar istendi. Binance TR (yerel kuruluş) vadeli işlemi sunmuyor görünüyor (üçüncü taraf, tarihsiz). Türk IP'sinin `fapi`'de 451 alıp almadığını **bulamadım**. Binance global'de kimlik doğrulaması (KYC) zorunlu, API anahtarı için IP beyaz listesi öneriliyor (anahtar güvenliği).
- Kısacası: sunucu konumunu Binance'in izin verdiği bir bölgeye taşımak gerekebilir ve bu kullanıcının hukuki/şart kararıdır. Hesabın hangi ülke kaydıyla açılacağı, vergi/mevzuat da kullanıcıya ait.

## 6. Maliyet (HL vs Binance)

| | Maker | Taker |
|---|---|---|
| HL (bizde ölçülen) | ~0,015% (tahmin, tarife) | **0,045%** (14,27 $ ücret / 31.719 $ hacim = %0,045) |
| Binance USDⓈ-M, normal kullanıcı (VIP0) | 0,020% | 0,050% |
| Binance + BNB indirimi (%10, futures hesabında BNB gerekir) | 0,018% | **0,045%** |

Kaynak: Binance SSS (360033544231) özetleri; sayfanın kendisini okuyamadım, "tarife değişebilir" uyarısı var. Taker-program indirimi (Ağustos 2025 duyurusu) ayrıca olabilir.

Bizim hacim: 31.719 $ / 4,14 gün = ~7.660 $/gün -> **~230.000 $/ay** (tahmin; kasa/slot büyürse artar). Emirlerimiz taker olduğu için:

| | Aylık ücret (tahmin) |
|---|---|
| HL taker %0,045 | ~103 $ |
| Binance taker %0,05 | ~115 $ (+12 $) |
| Binance taker + BNB %0,045 | ~103 $ (fark ~0) |

Yani **ücret farkı önemsiz** (en fazla ~12 $/ay). Asıl maliyet fiyat sapması: 1 bp = 23 $/ay (230.000 $ hacimde); iki borsa farkı + 0,6 sn hareket ortalama ~3–5 bp ek etki yaratsa bile ~70–115 $/ay eder, ücret farkından büyük (tahmin; ölçülmeli).

## 7. İş büyüklüğü ve riskler

**İş (tahmin, gün):**

| Parça | Gün |
|---|---|
| Binance istemci (imzalı REST + WebSocket, kütüphane: ccxt/resmi), hata/yeniden dene | 2–3 |
| Sembol/adım/min-notional eşleme (HL coin -> Binance sembol, `1000x`, HIP-3 eşleme) | 1–2 |
| Emir mantığı: yuvarlama, kısmi artır/azalt, kapat, stop eşleme, tek yön mod | 2–3 |
| Pozisyon/bakiye senkronu, fonlama, hesap okuma, kayıt/şema (`poz_senkron`, `kopya_drift`) | 2 |
| Sanal kipte Binance fiyatıyla gölge ölçüm + iki borsa fiyat kaydı | 1–2 |
| Test, canlıya geçiş hazırlığı (küçük tutar) | 2 |
| **Toplam** | **~10–14 gün** (erişim/KYC sorunu çözülmüş varsayımıyla) |

**Riskler:**
1. **Erişim**: Amsterdam IP'sinden 451 riski (bölüm 5); çözülmeden bu iş başlamaz.
2. **İki borsa fiyat sapması**: sinyal HL'de, emir Binance'te; ölçülmedi, tahminen bp'lerce kayma ve nadir uçlarda büyük sapma (HL'ye özgü ince coinler, piyasa kapalı hisse saatleri).
3. **Stop eşleme**: bizim Stop'lar HL fiyatına göre; Binance'te farklı fiyat/mark mantığı (mark fiyat farkı), algo emir uçları; stop tetiklenme farkı.
4. **HIP-3 kaybı**: HL'ye özgü `xyz:`/`io:` kontratların bir kısmı Binance'te yok (ANT, XYZ100) ya da dayanağı doğrulanmadı; TradFi perp sözleşmesi gerekebilir. Kaybedilen pay şimdilik hacmin ~%1'i, ama HIP-3 payı artarsa risk büyür.
5. **Anahtar güvenliği**: Binance API anahtarı gerçek para; yalnız işlem izni, **çekme izni yok**, IP beyaz listesi; anahtar repoya girmez. HL tarafında anahtar zaten ayrı.
6. **Min notional / adım**: küçük slotta (BTC/ETH <100 $) reddedilen emirler = kopya sapması.
7. **Çift sistem karmaşıklığı**: iki borsada bakiye/marj, hesap okuma; HL'de kalan açık pozisyonlarla Binance'in birlikte yönetimi.

## Sonuç: KISMEN yapılabilir

- **Teknik olarak** mümkün: coin kapsaması 47/50 coin (emir %98,0, hacim %98,9), ücret farkı ~0, API sınırları yeterli, ~10–14 günlük iş.
- **"Gecikmesiz" olmaz:** izleme HL'de kaldığı için en az ~0,6 sn; bugünkü 0,57 sn'ye göre ~0,05–0,1 sn daha yavaş (tahmin).
- **Engel/belirsizlik:** Hollanda IP'sinden erişim büyük olasılıkla kapalı (resmi 2021 duyurusu + 451 raporları); Türkiye için kesin kaynak bulunamadı; Binance fiyat/derinlik ölçülemedi.
- Binance'i seçmenin tek net artısı derin likidite (özellikle küçük altlarda) olur; HL'de 50–300 $ emir için kayma zaten ~1 bp altında, yani HL'de bir likidite sorunu görünmüyor.
- Karar vermeden önce yapılacak ucuz adım (kod değiştirmeden): 1–2 gün iki borsa fiyat kaydı + sunucu IP'sinin Binance'e erişimini test etme.

## Fable görüşü

**HAYIR (şimdilik değmez).** (20.11)
1. Çözülecek sorun yok: HL'de 50–300 $ emirde kayma çoğu coinde 1 bp altı; Binance'in derinlik artısı bu boyutta işe yaramaz.
2. Ücret kazancı yok: aylık fark 0 ile +12 $.
3. Yeni maliyet: iki borsa fiyat farkı + ~0,6 sn gecikme; tahmini 3–5 bp ek sapma ≈ 70–115 $/ay (ölçülmedi). Gecikme iyileşmez, ~0,05–0,1 sn kötüleşir.
4. Erişim: Amsterdam'dan Binance Futures büyük olasılıkla kapalı (451); bölge atlatma Binance şartlarını ihlal edebilir — kullanıcının hukuki kararı.
5. Bedel: 10–14 gün iş, çift borsa karmaşıklığı, stop eşleme riski; 1.500 $ tavanlı gerçek kip HL'de bile henüz başlamadı.

Önce yapılacak tek ölçüm (kod değişmeden, 1–2 gün): trader'ın HL dolum fiyatı ile ~0,6 sn sonraki Binance fiyatı arasındaki fark, bizim coinlerde. Bu fark HL'deki bugünkü kaymadan (medyan 0,4 bp, p90 6,6 bp) belirgin küçük çıkmazsa konu kapanır. Aynı ölçüm erişim sorusunu da cevaplar.

Uyarı: veri ~4,1 gün (302 sanal emir); Binance tarafı ölçüm değil tahmin/arama özeti; sembol listesi 40 günlük üçüncü taraf dökümü.
