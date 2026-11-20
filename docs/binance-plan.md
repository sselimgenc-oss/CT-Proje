# CT -> Binance USDⓈ-M Futures: uygulama planı

Tarih: 2026-11-20. YALNIZ PLAN; kod yok. Dayanak: `docs/binance-arastirma.md` (kapsama, gecikme, ücret, erişim), `docs/KARARLAR.md` (K-72..K-77), kod: `copytrade/canli/`.

Okuma notu: "(doğrulanmadı)" = Binance dokümanının kendisini bu ortamdan okuyamadım ya da arama özeti tutarsız; kodlamadan ÖNCE resmi sayfadan teyit edilecek. Rakam uydurulmadı; eşikler "öneri" diye işaretli.

## 0. Karar özeti (kullanıcı, 20.11 beyin fırtınası)

| Konu | Karar |
|---|---|
| Motor | CT ayrı motor kalır; ML botuyla ortak katman (ortak koruyucu) üzerinden bağlanır |
| Borsa | CT, Binance USDⓈ-M Futures'a geçer. Sinyal kaynağı HL WebSocket'te KALIR |
| Hesap düzeni | Aynı Binance hesabı, ALT HESAP: ML = ana hesap, CT = alt hesap (Sub Accounts açık, şu an 0 alt hesap) |
| Fable şartları | Koruyucu AYRI SÜREÇ + canlılık sinyali; borsada zarar-kes emri; alt hesap yoksa sembol kilidi |
| İlk adım | Binance KÂĞIT yürütme: sinyal HL'den, dolum fiyatı Binance defterinden simüle |
| Sert limitler (değişmez) | Günlük kayıp %5 (yalnız yeni açılış durur), %10 hepsi kapanır; kaldıraç 1–5x; gerçek nakit tavanı 1.500 $; anahtarda para çekme kapalı + IP beyaz liste; anahtar yalnız sunucu/GitHub Secrets |
| Not | Fable araştırmada "şimdilik HAYIR" demişti (`binance-arastirma.md` sonu); bu plan kullanıcının sonradan verdiği karardır. Fable'ın önkoşulu (iki borsa fiyat ölçümü + erişim testi) bu planın Aşama 0'ıdır |

## 1. Mimari

```
 Hyperliquid WebSocket (trader dolumları)         [DEĞİŞMEZ: copytrade/dinleyici.py -> motor olay kuyruğu]
            |
            v
 +-------------------------------+
 |  CT MOTOR (motor.py)          |  filtreler (K-73), K-76 ara dolum sayacı, K-75 telafi, K-77, slot/tavanlar
 |  hesap.py (defter)            |  risk.py (günlük kayıp), borsa_stop.py (stop eşitleme), mutabakat
 +---------------+---------------+
                 |  Yurutucu arayüzü:  emir(...) / hazirla(...) / stop_koy / stop_durum / stop_iptal
     +-----------+---------------+----------------------+
     |                           |                      |
 SanalYurutucu (HL l2Book)  BinanceKagitYurutucu    BinanceGercekYurutucu (alt hesap anahtarı)
 [bugünkü sanal]            (Binance bookTicker/    (fapi emir, ALGO stop)
 [GercekYurutucu = HL gerçek, derinlik, simüle;     
  hazır ama kapalı]          emir göndermez)                    |
                                                                v
                                              Binance USDⓈ-M: CT ALT HESABI

 ML BOT (ayrı) ---- emir ----> Binance USDⓈ-M: ANA HESAP

 +----------------------------------------------------------------------------+
 | ORTAK KORUYUCU (AYRI SÜREÇ, ayrı systemd birimi, kendi heartbeat'i)        |
 |  okur: ana hesap (kendi) + alt hesap (ana hesap API'siyle: sub-account uçları)|
 |  izler: toplam marj/özsermaye, hesap başı + toplam günlük kayıp, stop varlığı|
 |  yapar: alarm; eşik aşılırsa "yeni açılış dur" bayrağı; %10'da hepsini kapat |
 +----------------------------------------------------------------------------+
   CT motor + ML bot -> koruyucuya heartbeat (dosya/uç); koruyucu -> ikisine "dur" bayrağı
```

### 1.1 Koruyucunun hesap okuması: Binance sub-account uçları

| Amaç | Uç (ana hesap anahtarıyla) | Durum |
|---|---|---|
| Alt hesap listesi / oluşturma | `GET /sapi/v1/sub-account/list`, `POST /sapi/v1/sub-account/virtualSubAccount` | uç adları doküman başlığından; parametre/izin doğrulanmadı |
| Alt hesapta Futures açma | `POST /sapi/v1/sub-account/futures/enable` | doğrulanmadı (Futures'ın alt hesapta açılması gerekir) |
| Alt hesap Futures pozisyon riski | `GET /sapi/v1/sub-account/futures/positionRisk` (V1) ve **V2** (`/sapi/v2/sub-account/futures/positionRisk`; e-posta + futuresType 1 = USDT-M) | ana hesap ucu olduğu arama sonuçlarında doğrulandı; hangi API izni gerektiği **doğrulanmadı** |
| Alt hesap Futures özet (marj/bakiye) | `GET /sapi/v1/sub-account/futures/account` / `/sapi/v2/...` | doğrulanmadı |
| Alt hesaplar arası/ana hesaba transfer | `POST /sapi/v1/sub-account/futures/internalTransfer`, universal transfer | koruyucu bunu KULLANMAZ (para hareketi yok) |
| Alt hesap API anahtarı IP kısıtı | `.../sub-account/subAccountApi/ipRestriction` ailesi | doğrulanmadı |

Önemli açık nokta (doğrulanmadı, Aşama 0 işi): ana hesap anahtarı alt hesap adına EMİR VEREMEZ/İPTAL EDEMEZ olabilir; sub-account uçları genelde yalnız okuma + transfer + ayar. O zaman %10 "hepsini kapat" için koruyucunun alt hesabın KENDİ anahtarını da tutması gerekir (trade izinli, para çekme yok). Alternatif: koruyucu yalnız "dur bayrağı" yazar, kapatmayı CT motoru yapar; ama motor ölüyse kapatan olmaz. Bu yüzden alt hesap anahtarı (yalnız işlem izni) ikinci anahtar olarak koruyucuda da durmalı, VEYA zarar-kes emirleri (bölüm 2.3) son sigorta olarak borsada kalmalı. Karar gerekli (bölüm 8).

Anahtar listesi (hepsinde para çekme KAPALI, IP beyaz liste):

| Anahtar | Hesap | İzin | Kim kullanır |
|---|---|---|---|
| ML anahtarı | ana | okuma + Futures işlem | ML bot (mevcut/planlanan) |
| CT-işlem anahtarı | alt | okuma + Futures işlem | CT motor (yürütücü) |
| Koruyucu-okuma anahtarı | ana (sub-account okuma uçları için) | okuma | koruyucu |
| Koruyucu-kapatma anahtarı (karar bekliyor) | alt | Futures işlem | koruyucu, yalnız acil kapatma |

## 2. Yürütücü soyutlaması

### 2.1 Bugün neyin borsaya özgü olduğu

Ortak arayüz zaten var: `yurutucu.py:Yurutucu` (Protocol; `emir`, `hazirla`) ve `Dolum` dataclass'ı. Motor yalnız bu arayüze ve `post({...})` HL info çağrılarına bağlı. Borsaya özgü parçalar:

| Dosya:fonksiyon | HL'ye özgü olan | Binance karşılığı |
|---|---|---|
| `yurutucu.py:GercekYurutucu.emir` | SDK `exchange.order(..., TIF_IOC, reduce_only, cloid)`, `l2Book`, limit = en iyi fiyat ± `canli_ioc_bant`, yanıt `statuses[0]["filled"]` | `POST /fapi/v1/order` (LIMIT + IOC ya da MARKET), `reduceOnly`, `newClientOrderId`; yanıt `status`, `executedQty`, `avgPrice` |
| `yurutucu.py:_izgara`, `limit_yuvarla` | HL fiyat ızgarası (5 anlamlı basamak, szDecimals) | `exchangeInfo` PRICE_FILTER `tickSize` |
| `yurutucu.py:GercekYurutucu._sz_decimals`, `_meta_oku`, `lot_adim` | HL `meta` / `szDecimals` | `exchangeInfo` LOT_SIZE `stepSize`/`minQty` (MARKET emri için MARKET_LOT_SIZE ayrı; doğrulanmadı) |
| `yurutucu.py:min_nosyonel_ok`, `canli_min_nosyonel_usd` (10 $) | HL minimum emir değeri; reduce-only küçük kapanış serbest | `exchangeInfo` MIN_NOTIONAL (genelde 5 $, BTCUSDT 100 $ iddiası doğrulanmadı); reduceOnly muafiyeti doğrulanmadı |
| `yurutucu.py:GercekYurutucu.hazirla` | `update_leverage(x, coin, is_cross=False)` | `POST /fapi/v1/marginType` (ISOLATED) + `POST /fapi/v1/leverage` |
| `yurutucu.py:cloid_nesne` | HL `Cloid` (0x + 32 hex) | `newClientOrderId` (`^[\.A-Z\:/a-z0-9_-]{1,36}$`, doğrulanmadı) |
| `yurutucu.py:_gercek_ucret`, `ucret_eslestir` | `userFillsByTime` ile gerçek ücret | `GET /fapi/v1/userTrades` (`commission`, `commissionAsset`) veya emir yanıtı; BNB ile ödenirse ücret BNB cinsinden gelir |
| `yurutucu.py:GercekYurutucu.stop_koy` | `order(..., {"trigger": {...,"tpsl":"sl"}}, reduce_only)` | Binance **Algo Order** ucu (bölüm 2.3) |
| `yurutucu.py:stop_durum`, `stop_iptal` | `orderStatus`, `exchange.cancel` | Algo sorgu / Algo iptal uçları (doğrulanmadı) |
| `yurutucu.py:gercek_yurutucu_olustur` | `HL_API_CUZDAN_ANAHTARI`, `HL_HESAP_ADRESI`, `HL_AG` (testnet) | `BINANCE_CT_API_KEY/SECRET` (+ testnet: `testnet.binancefuture.com`, doğrulanmadı) |
| `borsa_stop.py:ONEK` (`0x5354`), `stop_cloid`, `bizim_mi` | HL cloid öneki | Binance clientOrderId öneki (örn. `ctst_`); sınır 36 karakter |
| `borsa_stop.py:hedefler`, `degisti_mi`, `BorsaStop.esitle` (koy-sonra-iptal, `bekleyen`, yetim tarama) | Mantık borsadan bağımsız (SAF); yalnız `yurutucu.stop_koy/stop_durum/stop_iptal` ve `acik` (açık emir listesi) biçimi | Aynen kalır; `acik` = Binance açık algo emirleri + açık emirler, `oid` = algoId |
| `motor.py:mids_al` (`allMids`) | HL mark/mid | `GET /fapi/v1/premiumIndex` (markPrice, tüm semboller) veya WS `!markPrice@arr` |
| `motor.py:funding_oku`, `funding_uygula`, `funding_gercek_oku/uygula` (`metaAndAssetCtxs`, `userFunding`; saatlik) | HL saatlik funding | `premiumIndex.lastFundingRate` + `nextFundingTime`; gerçek: `GET /fapi/v1/income?incomeType=FUNDING_FEE` |
| `motor.py:hl_oku`, `hl_uygula`, `_hl_izle`, `_hl_sicrama_denetle`, `hesap_oku` | `clearinghouseState` (özsermaye, pozisyon) | `GET /fapi/v3/account` ve `positionRisk` (CT alt hesabı kendi anahtarıyla) |
| `motor.py:senkron_oku/senkron_uygula` | TRADER pozisyonu: HL `clearinghouseState` (trader kimliği HL'de) | DEĞİŞMEZ (trader HL'de) |
| `motor.py:_mutabakat`, `_mutabakat_tutan_sorunlar`, `_yetim_izle`, `_borsa_yetim_kapat`, `hl_acik_say`, `acilis_hl_denetle` | HL pozisyon/açık emir okuması, `canli_hl_deger_ust_usd` | Binance `positionRisk` + açık emirler; yetim stop taraması |
| `motor.py:borsa_stop_esitle`, `_stop_kayip_teyit`, `_stopsuz_denetle`, `_felaket_stop` (`openOrders`) | HL açık emir okuması | Binance açık algo emirleri |
| `motor.py:_gercek_dolum`, belirsiz emir çözümü (`orderStatus` cloid) | HL orderStatus | `GET /fapi/v1/order?origClientOrderId=` |
| `motor.py:~316-356` (`extraAgents`, `userRole`, G-19 ajan süresi) | HL API cüzdanı bitiş denetimi | Binance anahtarında süre yok; yerine "anahtar yaşıyor mu / izinler doğru mu (çekme kapalı)" denetimi: `GET /sapi/v1/account/apiRestrictions` (doğrulanmadı) |
| `hesap.py:tasfiye_fiyati`, `tasfiye_mesafe`, `dinamik_stop_orani` | HL formülü mmr = 1/(2×azami kaldıraç) | Binance kademeli MMR (bölüm 4.4) |
| `kurallar.yaml` `maliyet_taker`, `canli_ioc_bant`, `canli_min_nosyonel_usd`, `canli_marj_kaldirac` | HL değerleri | Binance için ayrı değerler (bölüm 2.4) |

Borsadan BAĞIMSIZ kalanlar (dokunulmaz): `risk.py` (tamamı), `sert_sinirlar.py`, `hesap.py` defter mantığı (`uygula`, `slot_*`), `borsa_stop.py` karar katmanı, motor filtreleri/K-75/K-76/K-77, `dinleyici.py`.

### 2.2 Önerilen soyutlama (yalnız tasarım)

1. `Yurutucu` arayüzünü genişlet: `emir`, `hazirla`, `stop_koy`, `stop_durum`, `stop_iptal`, `lot_adim`, `min_nosyonel(sembol)`, `kural(sembol)` (tick/step/minNotional).
2. Yeni bir "piyasa verisi" arayüzü: `marklar()`, `funding()`, `defter(sembol)`, `hesap_durumu()`, `acik_emirler()`. Bugün motor `self.post({...HL...})` ile doğrudan konuşuyor (motor.py'de ~20 yer); bu çağrılar arayüze taşınır. En büyük refaktör budur ve HL davranışı BİREBİR korunmalıdır (mevcut testler regresyon ağı).
3. Seçim: `canli_borsa: hl | binance` + `canli_kip: sanal | gercek`. Üç yürütücü: HL (bugünkü iki sınıf), `BinanceKagitYurutucu`, `BinanceGercekYurutucu`.

### 2.3 Binance emir ayrıntıları

| Konu | Binance | Durum |
|---|---|---|
| Piyasa/IOC açılış-kapanış | `/fapi/v1/order` LIMIT+`timeInForce=IOC` (HL'deki gibi bant) ya da MARKET | tip adları bilinen; bant hesabı bizde kalır |
| Kapatma | `reduceOnly=true` (tek yön modda) | doğrulandı (tek yön); hedge modda reduceOnly GÖNDERİLEMEZ (ikincil kaynak) |
| Pozisyon modu | `POST /fapi/v1/positionSide/dual` -> **tek yön (One-way)**; CT alt hesabında ve ML hesabında ayrı ayrı ayarlanır (hesap başına ayar; doğrulanmadı) | bizim "coin başına net pozisyon" mantığı tek yönle uyumlu |
| Marj tipi + kaldıraç | coin başına ISOLATED + `canli_marj_kaldirac` (3x), `marginType` + `leverage`; kaldıraç sembolün kademe sınırını aşamaz (`leverageBracket`) | doğrulandı (uç adları); kaldıraç tavanı sembole göre |
| Zarar-kes | **STOP_MARKET**, `closePosition=true` (miktar/reduceOnly ile birlikte kullanılamaz) ya da miktarlı reduceOnly; `workingType=MARK_PRICE` (HL mark mantığıyla aynı) | Binance Aralık 2025'te koşullu emirleri ayrı **Algo Order** servisine taşıdı (`POST /fapi/v1/algoOrder`; eski `/fapi/v1/order`'a STOP_MARKET göndermek -4120 verebilir). Tarih iki kaynakta 02.12 / 09.12.2025; parametreler **doğrulanmadı**, resmi "New Algo Order" sayfasından teyit şart |
| closePosition vs miktarlı | `closePosition=true` pozisyonu bütünüyle kapatır: artırma/azaltmada stopu yeniden kurmak gerekmez ama kısmi azaltmada da tamamını kapatır; bizim `BorsaStop` "net miktar" mantığı miktarlı reduceOnly'ye daha yakın | seçim: miktarlı reduceOnly (mevcut `degisti_mi` %2 miktar eşiğiyle aynı); `closePosition` yalnız koruyucunun son-sigorta stopunda |
| Dolum yanıtı | MARKET/IOC yanıtı hemen dolum içerir (`avgPrice`, `executedQty`) ya da `status=NEW` ile gelip sonra dolar; belirsizlikte `origClientOrderId` ile sorgu (bugünkü `belirsiz` -> `orderStatus(cloid)` akışının karşılığı) | yanıt alanları doküman özeti; doğrulanmadı |
| Hız sınırı | IP 2400 ağırlık/dk; hesap 1200 emir/dk, 300/10 sn (arastirma: ~75 emir/gün için fazlasıyla yeter) | orta güven |
| Yetim/yabancı emir denetimi | clientOrderId önekiyle (`bizim_mi` karşılığı) | CT ve ML aynı öneki kullanmamalı; alt hesap ayrı olduğundan zaten ayrışır |

### 2.4 Ayar (kurallar.yaml) için Binance değerleri

`maliyet_taker`: Binance VIP0 taker %0,05 (BNB indirimiyle %0,045; doğrulanmadı, tarife değişir) - kâğıt kipte VARSAYILAN %0,05, gerçek ücret `userTrades`'ten. `canli_min_nosyonel_usd` sembole göre `exchangeInfo`'dan (tek sabit yetmez). `canli_ioc_bant` Binance için ayrı ölçülüp belirlenir (5a sonucu). Yeni anahtarlar: `canli_borsa`, `binance_alt_hesap`, `binance_sembol_eslesme_dosyasi`.

## 3. Sembol eşleme (HL coin <-> Binance sembolü)

Kural tablosu (kapsama sayıları `binance-arastirma.md` 1/1b; 4.1 günlük veri):

| HL coin | Binance | Not |
|---|---|---|
| `BTC`, `ETH`, `SOL` ... | `BTCUSDT`, ... | coin + `USDT` |
| `kPEPE`, `kSHIB`, `kBONK`, `kFLOKI` (HL "k" = 1000'lik) | `1000PEPEUSDT`, `1000SHIBUSDT`, `1000BONKUSDT`, `1000FLOKIUSDT` | çarpan 1000 ama HL ve Binance çarpanı HER coinde aynı olmayabilir: eşleme tablosuna `carpan` alanı yazılır; miktar `sz_binance = sz_hl_esdeger / carpan_farki`, fiyat karşılaştırması çarpanla normalize (doğrulanmadı: her coin için exchangeInfo'dan kontrol) |
| Binance'te yalnız farklı adla olanlar (örn. `MATIC`/`POL`, `RNDR`/`RENDER` türü yeniden adlandırmalar) | tablo | elle onaylı tablo; otomatik tahmin YOK |
| HIP-3 `xyz:NVDA`, `io:NVDA` | `NVDAUSDT` (TradFi perp) | `io:` ve `xyz:` aynı sembole gider (çift sayım: tek net pozisyon); dayanak eşleşmesi SPCX, DRAM, BE, SOXL, `io:*` için DOĞRULANMADI -> bunlar "güvenli listeye" alınana dek atlanır |
| `xyz:ANT` (Anthropic pre-IPO) | `ANTHROPICUSDT` olabilir | doğrulanmadı |
| `xyz:XYZ100`, `PURR` | yok | atla |

Bulunmayan / güvenilmeyen coinde davranış:

| Durum | Davranış | Kayıt |
|---|---|---|
| Eşleme tablosunda yok | AÇILIŞ atlanır (`atla`, neden `binance_sembol_yok`); kapanış/azaltma konusu yok (pozisyon hiç açılmadı) | `emir` kaydı + Telegram `ATLA_TR` etiketi; kural maliyeti/karşı-olgu (K-73 `_atla` yolu) |
| Tabloda var, Binance'te `status != TRADING` (delist, kapalı seans) | açılış atlanır (`binance_islem_yok`); AÇIK pozisyon varsa kapanış denenir, olmazsa alarm | alarm |
| Dayanak doğrulanmamış (`dogrulandi: false`) | açılış atlanır (`binance_eslesme_dogrulanmadi`) | kayıt |
| TradFi perp ama kullanıcı TradFi-Perps sözleşmesini imzalamadı | atla (`binance_tradfi_sozlesme`) | doğrulanmadı; Aşama 0'da test edilir |
| Min notional/step nedeniyle boyut sıfır | atla (`binance_min_nosyonel`) | BTC/ETH <100 $ riski (arastirma bölüm 4) |
| Seans: Binance hisse perp'i seansı izliyorsa kapalıyken | atla (`binance_seans_kapali`) | kaynaklar çelişiyor; Aşama 0'da hafta sonu `exchangeInfo.status` ile ölçülür |

Eşleme tablosu: `copytrade/canli/binance_eslesme.yaml` (öneri); her satır `hl`, `binance`, `carpan`, `dogrulandi`, `tur` (kripto/tradfi/preipo). Başlangıçta `exchangeInfo`'dan üretilen ADAY liste + elle onay; delist/yeni sembol için günlük yenileme ve fark alarmı. Ayrı bir cuma/hafta sonu testi (HIP-3 örneği tek gün, bir Cuma) planlanır.

Çift sembol/çift trader notu: HL'de coin başına tek net pozisyon zaten vardı (`borsa_stop.py` açıklaması); Binance'te de alt hesapta sembol başına tek net pozisyon, yani aynı kural geçerli.

## 4. Kâğıt (sanal) Binance yürütme

Kural K-73: kâğıtta hiçbir özellik kapalı/gölge/yalnız-kayıt kalmaz; Binance kâğıt kipi de TÜM mevcut sanal özellikleri (filtreler, K-74 dinamik stop, K-75 telafi, K-76, K-77, iz süren koruma, sanal tasfiye) açık çalıştırır. Kalite kapıları yalnız gerçek içindir.

### 4.1 Dolum modeli

- Veri: Binance public WebSocket `<sembol>@bookTicker` (en iyi alış/satış + miktar) ve `@depth5@100ms` / `@depth10` (derinlik). Public uçlar anahtar istemez (kâğıt kipte anahtar YOK, bugünkü `SanalYurutucu` gibi). Erişim: sunucunun Binance'e erişebilmesi gerekir (bölüm 8, 451 riski). Public market data uçları futures bölge kısıtından muaf olabilir (doğrulanmadı); testte ölçülür.
- Dolum: bugünkü `SanalYurutucu.emir` + `defter_yuru` mantığı korunur: emir anında Binance defteri alınır, bizim tutar defter seviyelerinde yürütülür (kayma ayrıca eklenmez, yürüyüş kaymayı taşır), `canli_ioc_bant` dışı dolmaz, `_derinlik_dus` (aynı coin/yönde ardışık emirler öncekilerin seviyelerini düşer) aynen. Fark yalnız veri kaynağı: HL `l2Book` yerine Binance derinlik anlık görüntüsü.
- Gecikme simülasyonu: emir anından DOLUM anına, ölçülen/varsayılan Binance emir yolu gecikmesi (arastirma tahmini ~230–280 ms, ölçülmedi) kadar sonraki defter kullanılır; yani sinyal geldiği an değil "sinyal + gecikme" anındaki defter. Gecikme parametresi `binance_kagit_gecikme_ms` (varsayılan: 5a ölçümünden; ölçüm yoksa 250 öneri, işaretli varsayım).
- Kayıt (karşılaştırma için ŞART): her emirde HL referans fiyatı, trader HL dolum fiyatı, Binance bookTicker, Binance dolum fiyatı. Bu alanlar 5a "iki borsa fiyat farkı" ölçümünün canlı karşılığı olur.
- Boyut kuralları: tick/step/minNotional `exchangeInfo`'dan; küçük emir reddedilirse "binance_min_nosyonel" atlama kaydı (HL'den sapma ölçülsün diye ayrı sayaç).

### 4.2 Ücret

| Kalem | Kâğıt modeli | Not |
|---|---|---|
| Taker | `maliyet_taker` yerine `binance_taker` = 0,0005 (VIP0; BNB indirimi için 0,00045) | tarife doğrulanmadı |
| Maker | kullanılmaz (hep IOC/market) | |
| BNB ile ödeme | kâğıtta yok sayılır; gerçekte BNB bakiyesi gerekir | gerçek aşama notu |

### 4.3 Fonlama

Binance fonlaması 8 saatlik (00:00/08:00/16:00 UTC) varsayımıyla; bazı kontratlarda 4 saatlik/farklı aralık olabilir (kaynaklar tutarsız; doğrulanmadı): `premiumIndex.nextFundingTime` ve `fundingInfo` (aralık, tavan/taban; uç doğrulanmadı) okunarak sembol başına belirlenir. Bugünkü `funding_uygula` (tam saat başı, saatlik oran, 24 saat geriye tamamlama) genelleştirilir: sembolün funding zamanında, o anki pozisyon ve mark fiyatıyla `-sz × mark × oran` (long pozitif oranda öder). Oran: `lastFundingRate` (anlık) yerine uygulama anındaki kesinleşen oran; kesinleşen değer `GET /fapi/v1/fundingRate` geçmişinden (doğrulanmadı). Pozisyon yalnız saatlerce tutulduğundan etki küçük; yine de açık (K-73).

### 4.4 K-74 dinamik stop: Binance tasfiye formülü

Bugün `hesap.py:tasfiye_fiyati`: `mmr = 1/(2×azami_kaldirac)`; stop = min(üst, tasfiye mesafesi − pay). Binance'te bakım marjı KADEMELİ: `MM = notional × MMR(kademe) − bakım_tutarı(cum)`; izole tasfiye fiyatı yaklaşık (tek pozisyon, izole, ücret hariç; formülün resmi hali Binance SSS'sinde, doğrulanmadı ve sürüm farkı olabilir):

- Sade yazım (yaklaşık, ücret hariç): tasfiye mesafesi ≈ `1/kaldıraç − MMR_etkin`, burada `MMR_etkin = MMR(kademe) − cum/notional`. Tam formül Binance SSS'sinde; koda konmadan önce resmi sayfadan teyit edilecek.
- Girdi: sembol başına `GET /fapi/v1/leverageBracket` (kademe tablosu: `notionalFloor/Cap`, `maintMarginRatio`, `cum`, `initialLeverage`). Tablo günlük çekilip yerelde saklanır (Binance kademeleri periyodik günceller; duyuru: 2025 örneği).
- Bizim durumumuz: slot/pozisyon küçük (yüzlerce $), yani HER ZAMAN ilk kademe: `MMR_etkin = MMR(ilk kademe)` (cum = 0 ilk kademede). Büyük kademe formülü yalnız kasa çok büyürse gerekir; yine de koda genel formül konur.
- Uyarlama: `tasfiye_mesafe(long, giris, kaldirac, azami)` imzasındaki `azami_kaldirac` -> `mmr` parametresiyle değiştirilir (`mmr_ilk_kademe`); HL'de eski formül aynen kalır (HL için sarmalayıcı). Stop = min(`canli_borsa_stop_oran` 0,22; mesafe − 0,01), yazılım stopu min(0,20; mesafe − 0,03) AYNI kurallar; mark fiyatı tetikli (`workingType=MARK_PRICE`).
- Örnek (yalnız formülü göstermek için; MMR %0,5 bir VARSAYIMDIR, gerçek değer doğrulanmadı): 3x ve MMR %0,5 ise tasfiye mesafesi ≈ 1/3 − 0,005 ≈ %32,8; stop %20/%22 zaten tasfiyeden önce; yani Binance'in majör kademelerinde HL'nin düşük-azami-kaldıraçlı coinlerinde yaşanan "tasfiye stoptan önce" sorunu (K-74'ün VVV örneği) daha az görülür. Düşük kaldıraç tavanlı (kademe başına 3–5x) altcoinlerde tablo sembol başına okunmalı.
- Tasfiye fiyatı doğrulaması: `GET /fapi/v3/positionRisk`'in `liquidationPrice` alanı gerçek tasfiye fiyatını verir (gerçek aşamada koruyucu bunu formülle karşılaştırır; sapma alarmı). Bugün HL'de "borsanın bildirdiği tasfiye fiyatı kodda okunmuyor" (K-74 notu): Binance'te okumak kolay.
- Kâğıt kipte sanal tasfiye (`tasfiye_kontrol`) bu formülle çalışır; mark fiyatı Binance mark (`@markPrice`).
- Ek Binance farkı: Binance, tasfiye öncesi kısmi tasfiye ve sigorta fonu ücreti uygular (doğrulanmadı); kâğıtta tam tasfiye + tasfiye ücreti yaklaşık modellenir, gerçek kayıp kâğıttan farklı olabilir.

## 5. Ortak koruyucu

Ayrı süreç (`copytrade/koruyucu/...` önerisi; CT ve ML'nin İKİSİNİN de kodundan bağımsız, aynı sunucuda ayrı systemd birimi `sg-koruyucu.service`, kendi `Restart=always`, kendi kullanıcısı; anahtarları yalnız bu birimin ortam dosyasında).

| Sorumluluk | Ayrıntı | Eşik (kullanıcı kararı değişmez / öneri) |
|---|---|---|
| Toplam özsermaye/marj | Ana hesap (kendi anahtarı) + alt hesap (sub-account uçları) her 15–30 sn okunur; toplam, hesap başına kullanılan marj, açık pozisyon sayısı | okuma sıklığı öneri |
| Hesap başı günlük kayıp | CT alt hesabı ve ML ana hesabı için ayrı ayrı: %5 -> o hesabın YENİ AÇILIŞI durur ("dur bayrağı"); %10 -> o hesabın tüm pozisyonları kapanır | %5 / %10 (kullanıcı kararı) |
| Toplam kayıp | İkisinin toplamı için de %5 / %10 (tek hesap gibi) | aynı oranlar; toplamın tabanı = gün başı iki özsermayenin toplamı (UTC gün sınırı, `risk.py:gun` ile aynı) |
| Nakit tavanı | CT alt hesabı özsermayesi 1.500 $'ı aşarsa yeni açılış durur (`sert_sinirlar.py:GERCEK_KASA_UST_USD`); aşım için ML'nin payı konusu açık soru | 1.500 $ (karar); ML payı bölüm 8 |
| Kaldıraç denetimi | `positionRisk.leverage` 1–5x dışı ise alarm + dur | karar (1–5x) |
| Borsa tarafı stop varlık denetimi | Her açık pozisyon için borsada açık STOP_MARKET algo emri VAR mı, yönü/miktarı doğru mu, tetik mark'tan makul uzaklıkta mı (CT: `BorsaStop` durumu ile karşılaştırma). Eksikse: önce CT'ye "stop kur" uyarısı, `canli_borsa_stop_korumasiz_sn` (1.800 sn) dolunca koruyucu kendisi son-sigorta `closePosition` stopu koyar ya da pozisyonu kapatır (K-65 mantığının koruyucuya taşınması) | süre 1.800 sn mevcut |
| Anahtar sağlığı | Anahtar izinleri (çekme KAPALI) ve IP kısıtı periyodik denetlenir; çekme izni açık görünürse alarm + dur | günlük |
| Heartbeat | CT motoru ve ML bot koruyucuya `nabiz` yazar (dosya mtime ya da küçük yerel uç); koruyucu da kendi heartbeat'ini DIŞ nabza yazar (mevcut `sg-nabiz` altyapısı, `deploy/ACILIS_KONTROL.md` Y-3) | aralık öneri 30 sn |

Canlılık sinyali kesilirse:

| Kesilen | Süre (öneri, doğrulama gerekir) | Eylem |
|---|---|---|
| CT motoru nabzı | 3 dk | koruyucu alarm verir; borsa stopları zaten duruyor; yeni açılış yapılamaz çünkü motor yok; 30 dk sonra (K-65 `korumasiz_sn` benzeri) açık pozisyonlar için stop varlığı teyit, yoksa kapat |
| ML bot nabzı | 3 dk | alarm; ana hesap stopları (ML'nin işi) varlık denetimi |
| KORUYUCUNUN kendisi (dış nabız) | 3 dk | dış `sg-nabiz` Telegram alarmı (insan müdahalesi); CT motoru koruyucunun nabzını da izler: koruyucu 3 dk yoksa CT YENİ AÇILIŞI durdurur (açılış yapmadan önce koruyucu nabzı şart: "koruyucu yoksa açma") |
| Binance API erişimi | 60 sn art arda hata | alarm; yeni açılış durur; borsa stopları yerinde kalır |

Alarm: bugünkü Telegram (`telegram.py`) + `deploy/alarm.sh` kanalı; koruyucu ayrı bot/kanal anahtarı gerekmez, ama KENDİ gönderim yolu olmalı (motor çökmüşse motorun Telegram'ı yok).

Tek hata noktası notu: koruyucu ve motorun aynı sunucuda olması sunucu çökerse ikisinin de gitmesi demek; ancak o durumda bile borsadaki STOP_MARKET algo emirleri çalışmaya devam eder (Fable şartı; bu yüzden zorunlu). Dış nabız sunucu çöküşünü bildirir.

Bayrak mekanizması: koruyucu `dur-ct.json`/`dur-ml.json` (ya da kilitli tek dosya) yazar; CT motoru her dakikalık bakımda okur (`risk.py:dur_ver` / `acilis_durdu` yolu: yeni açılış durur, kapanış asla engellenmez). Motor bu bayrağı sildirmez; yalnız insan (ya da UTC gün dönümü, %5 durumu için) temizler. %10 kapatma: koruyucu `closePosition`/reduceOnly MARKET ile (alt hesap işlem anahtarı gerekirse bölüm 1.1 sorusu).

## 6. Yedek yol: alt hesap yok -> tek hesap + sembol kilidi

Yalnız alt hesap kurulamazsa (örn. Sub Accounts Futures'ı açılamazsa). Aynı hesapta tek net pozisyon/sembol kuralı CT ile ML'yi birbirine karıştırır (Binance tek yön modunda sembol başına TEK pozisyon), bu yüzden:

| Konu | Tasarım |
|---|---|
| Kural | ML ile CT aynı sembolde aynı anda pozisyon tutamaz. CT bir sembolde açmadan önce kilit alır; kilit sahibi o sembolün pozisyonu kapanana dek tutar |
| Kilidin yeri | Motorların kendi dosya kilidi yetmez (ayrı süreçler). Öneri: ortak koruyucunun sahip olduğu küçük kayıt (SQLite/dosya + `flock`, ya da koruyucunun yerel uç noktası): `sembol -> {sahip: ct|ml, ms, pozisyon_var}`. Kilidi KORUYUCU verir; ML ve CT sormadan açmaz |
| Yarış durumu | İki taraf aynı anda ister: kilit alma atomik (`flock` ya da SQLite `BEGIN IMMEDIATE`); kazanan alır, kaybeden bekler ya da atlar. Tutarlılık için ikinci kontrol: açmadan hemen önce borsada `positionRisk` ile sembolde başka sahibin pozisyonu var mı (kilit kaydı yanlış/bayat olabilir) |
| Çökme | Kilit sahibi çökerse kilit ölmez: koruyucu `positionRisk`'i esas alır (gerçek pozisyon var = kilit var; pozisyon yok + nabız yok = kilit bırakılır) |
| clientOrderId | Önek ile pozisyonun hangi bota ait olduğu ayrışır (`ctst_`, ML öneki), ama borsada NET pozisyon tek: sahibi ayırmak için kilit kaydı gerekir |
| Marj | Tek hesapta izole marj sembol başına ayrı; yine de ortak cüzdan bakiyesi paylaşılır: koruyucu "CT payı" ve "ML payı" için SOFT bütçe izler (özsermaye payı) ve tek hesap günlük kayıp %5/%10'u hesap toplamına uygular |
| Maliyet | CT trader kopyası ML'nin kullandığı semboller yüzünden sık atlanır; kopya sapması artar. Bu yüzden alt hesap öncelikli, bu yol son çare. Atlanan sinyaller `binance_sembol_kilidi` nedeniyle kayda geçer |
| Hesap tek, anahtar tek mi | Tek hesapta ML ve CT AYRI API anahtarı alır (hesap başına çok anahtar mümkün; doğrulanmadı) ve ayrı IP beyaz listesi |

## 7. Aşamalar ve süre

Öneri süre (gün; `binance-arastirma.md` 10–14 gün tahmini + koruyucu + alt hesap kurulumu dahil, tahmin). Hiçbir aşama kullanıcı onayı olmadan sonrakine geçmez.

| Aşama | İş | Süre (gün) | Geçiş kriteri (ÖLÇÜLEBİLİR) |
|---|---|---|---|
| 0 Ön ölçüm / ön koşul | (a) 5a: HL trader dolum fiyatı ile ~0,6 sn sonraki Binance fiyatı farkı (WebSocket, 1–2 gün, kod yok); (b) sunucunun Binance Futures API'sine erişimi (451 testi, public ve imzasız uç); (c) Sub Accounts'ta alt hesap + Futures açılabiliyor mu; (d) Algo Order/STOP_MARKET resmi doküman teyidi; (e) sub-account uçlarının gereken izinler; (f) TradFi-Perps sözleşmesi gerekiyor mu | 2–3 | (b) sunucudan fapi `exchangeInfo` HTTP 200; (a) fark ölçümü tamamlandı ve medyan/p90 raporlandı (kriter bölüm 8'de kullanıcı/Fable kararı); (c) alt hesap ve Futures AÇIK; (d)(e) sayfalar okunup bu belgedeki "doğrulanmadı" satırları kapatıldı |
| A Kâğıt Binance (sanal) | Piyasa verisi arayüzü refaktörü (HL davranışı değişmeden), `BinanceKagitYurutucu`, eşleme tablosu, kâğıt dolum/ücret/fonlama, K-74 Binance formülü, kayıt alanları, pano/Telegram uyumu | 5–6 | (1) HL sanal ile Binance kâğıt AYNI sinyalde en az 5 gün paralel (kıyas); (2) tüm mevcut testler geçiyor + Binance yürütücü/eşleme birim testleri; (3) eşleme: kayıtlı emirlerin en az %95'i (emir sayısı) Binance sembolüne eşlendi, atlananların hepsi nedenli; (4) Binance kâğıt dolum fiyatı ile HL trader fiyatı farkı kayıt altında, medyan ve p90 bp raporlandı; (5) en az bir kez açık pozisyonda sembol delist/status değişimi ve hafta sonu davranışı gözlendi; (6) sıfır işlenmemiş hata/çökme bu pencerede |
| B Koruyucu | Ayrı süreç + systemd, sub-account okuma, hesap başı + toplam eşikler, stop varlık denetimi, heartbeat (CT <-> koruyucu <-> dış nabız), alarm, "dur bayrağı" akışı; Binance TESTNET'te (uygunsa; doğrulanmadı) ya da küçük kâğıt hesapla deneme betiği (bugünkü `stop_deneme.py` karşılığı) | 4–5 | (1) koruyucunun heartbeat'i kesilince CT açılışı durdurması testle kanıtlı; (2) CT nabzı kesilince alarm süresi ölçüldü (hedef <= 3 dk); (3) sahte eşik testi: %5 -> yalnız açılış durdu, %10 -> tüm pozisyonlar kapandı (testnet/sahte); (4) stop varlık denetimi: bilerek silinen stop 1.800 sn içinde yeniden kuruldu ya da pozisyon kapandı; (5) çekme izninin kapalı olduğu otomatik denetimle doğrulandı; (6) Fable kod incelemesi (K-72 sert sınırlar korunuyor) |
| C Gerçek (küçük tavan) | `BinanceGercekYurutucu` + ALGO stop; alt hesap CT anahtarı (yalnız işlem izni, IP beyaz liste, çekme kapalı) GitHub Secrets/sunucu; İLK tavan çok küçük (öneri: 100–150 $ özsermaye; tavanı kullanıcı belirler), 5x'in altında 3x; her emirde Telegram | 3 + en az 7 gün gözlem | (1) ilk 7 günde: yetim pozisyon 0, kayıp stop 0, mutabakat farkı kasa×%1 altı; (2) gerçek dolum fiyatı ile kâğıt tahmini farkı raporlandı; (3) borsa stopları her açık pozisyonda mevcut (koruyucu denetim kaydı); (4) günlük kayıp bayrağı sahte denemede çalıştı; (5) kullanıcı onayıyla tavan kademeli artış (100 -> ... -> 1.500 $, her kademe ayrı karar) |

Toplam: ~14–17 gün çalışma + gözlem pencereleri (A paralel 5 gün, C gözlem 7 gün). `binance-arastirma.md`'deki 10–14 gün yalnız istemci+eşleme+emir işiydi; koruyucu (B) onun üstüne eklenmiştir.

Aşama sırası: 0 -> A -> B -> C. Not: B'nin bir kısmı (koruyucu iskeleti, ML tarafı için de gereken) A ile paralel yazılabilir; ancak C için B bitmeden gerçek anahtar sunucuya konmaz.

## 8. Riskler ve açık sorular

### 8.1 Riskler

| # | Risk | Etki | Önlem |
|---|---|---|---|
| R1 | Erişim: Amsterdam IP'sinden Binance Futures 451 ihtimali (`binance-arastirma.md` bölüm 5); bölge atlatma Binance şartlarını ihlal edebilir | İş başlamaz | Aşama 0(b); sunucu konumu kullanıcı kararı |
| R2 | İki borsa fiyat farkı: sinyal HL, dolum Binance; ~0,6 sn gecikme + fiyat farkı | Kopya sapması; arastirma tahmini 3–5 bp ≈ 70–115 $/ay (ölçülmedi) | 5a ölçümü; Aşama A kayıtları; `canli_ioc_bant` Binance için ayrı |
| R3 | Algo Order göçü: koşullu emir uçları değişti, dokümana göre güncel parametreler doğrulanmadı | Stop kurulamaz = en büyük güvenlik riski | Aşama 0(d); testnet/küçük gerçek stop denemesi (C öncesi) |
| R4 | Sub-account yetki belirsizliği (ana anahtar alt hesabı okuyabilir mi / kapatabilir mi) | Koruyucu görevini yapamaz | Aşama 0(e); ikinci anahtar kararı |
| R5 | HIP-3/TradFi eşleme: dayanak eşleşmesi (SPCX, DRAM, BE, SOXL, `io:*`) doğrulanmadı; seans davranışı çelişkili | Yanlış varlığa işlem | `dogrulandi:false` atlanır; hafta sonu testi |
| R6 | Min notional/step: BTC/ETH küçük emirler reddedilebilir | Kopya sapması | atlama kaydı + sayaç |
| R7 | Çift sistem karmaşıklığı: 3 yürütücü, 2 borsa, koruyucu, ML | Hata yüzeyi | HL gerçek/sanal davranışı birebir korunur (testler); HL yolu silinmez |
| R8 | Tasfiye formülü: Binance kademeli MMR + kısmi tasfiye + sigorta fonu; kâğıt model yaklaşık | Kâğıt-gerçek sapma | `positionRisk.liquidationPrice` ile karşılaştırma (C) |
| R9 | Anahtar güvenliği | Para kaybı | çekme izni kapalı, IP kısıtı, yalnız sunucu/Secrets, anahtar günlüğe yazılmaz (mevcut kural), koruyucuda ayrı anahtar |
| R10 | Koruyucu ve motor aynı sunucuda: sunucu çöküşü | İkisi de gider | Borsa stopları zorunlu (Fable şartı) + dış nabız |
| R11 | ML ile CT aynı hesap/alt hesap ortak kayıp eşiği: bir bot diğerini durdurur mu? | Beklenmedik duruş | hesap başı + toplam eşik ayrımı net yazılacak (8.2-K3) |
| R12 | Hesap yapısı gereği ücret kademesi: alt hesaplar ana hesabın VIP/hacim kademesini paylaşır mı | Ücret farkı | doğrulanmadı; küçük etki (arastirma: ücret farkı ~0–12 $/ay) |
| R13 | Veri: kapsama/gecikme sayıları ~4,1 günlük sanal kayıt ve 40 günlük üçüncü taraf `exchangeInfo` dökümüne dayanıyor | Tahminler değişebilir | Aşama 0 ve A güncel veriyle yeniler |

### 8.2 Açık sorular (karar kimde)

Kullanıcı kararı:

| # | Soru |
|---|---|
| K1 | Sunucu nereden çalışacak (Amsterdam Binance Futures için kapalı olabilir)? Hangi konum/yasal çerçeve? (hukuki karar kullanıcıya ait) |
| K2 | Binance hesabının ülke kaydı, KYC ve TradFi-Perps sözleşmesi imzası (hisse/endeks perp'leri için) |
| K3 | Gerçek nakit tavanı 1.500 $ CT alt hesabına mı, ML+CT toplamına mı uygulanır? ML'nin payı nedir? (Planda: CT alt hesabı 1.500 $'ı aşamaz; toplam için ayrı sınır yok) |
| K4 | Aşama C başlangıç tavanı (öneri 100–150 $) ve kademe planı |
| K5 | 5a ölçümünün sonuç eşiği: "bu fark/gecikme kabul edilebilir" ölçütü (Fable'ın önerisi: Binance farkı HL'deki bugünkü kaymadan belirgin küçük çıkmazsa konu kapanır; "belirgin" sayısal tanım yok, kullanıcı/Fable koymalı) |
| K6 | BNB ile ücret indirimi kullanılsın mı (BNB bakiyesi tutmak gerekir)? |

Fable kararı/görüşü:

| # | Soru |
|---|---|
| F1 | Koruyucu alt hesap işlem anahtarını (yalnız acil kapatma için) tutsun mu, yoksa yalnız dur bayrağı + borsadaki stoplar yeter mi? |
| F2 | Hesap başı mı toplam mı kayıp eşiği öncelikli; bir hesabın %10 kapatması diğerini de kapatır mı? (K3/R11 ile birlikte) |
| F3 | Binance için dolum modeli: IOC limit + bant mı, MARKET mi? (kayma/işlem garantisi dengesi) |
| F4 | Stop türü: miktarlı reduceOnly stop mu (mevcut `BorsaStop` mantığı), `closePosition` mı? Algo uçlarının güncel kuralları teyitten sonra |
| F5 | CT yürütücüsü "Binance gerçek"e geçtiğinde HL gerçek kipi (hazır, kapalı) kalıcı yedek mi, kaldırılacak mı? |

Teknik doğrulama bekleyen (Aşama 0 işi): sub-account uçlarının izinleri; Algo Order parametreleri; `exchangeInfo` MIN_NOTIONAL/MARKET_LOT_SIZE kuralı ve BTCUSDT 100 $ iddiası; reduceOnly küçük kapanış muafiyeti; kademeli MMR ve resmi tasfiye formülü; fonlama aralığı/tavan; clientOrderId biçimi; testnet var mı; alt hesapta hesap başına pozisyon modu; ücret kademesi paylaşımı; public market data'nın bölge kısıtından muaf olup olmadığı; TradFi seans davranışı.

### 8.3 5a bağlantısı

5a (iki borsa fiyat farkı ölçümü) Aşama 0(a)'dır. Sonucu üç yere bağlanır: (1) "devam / dur" kararı (K5); (2) `canli_ioc_bant` ve `binance_kagit_gecikme_ms` değerleri; (3) hangi coinler/HIP-3 için Binance'in güvenli bulunduğu (eşleme `dogrulandi`). Ölçüm sonucu planın bu bölümüne tarihli not olarak işlenecek.

## Kaynaklar (WebSearch, 20.11; sayfaların kendisi tam okunmadı)

- Binance geliştirici dokümanı: New Algo Order (USDⓈ-M) ve Change Log (Algo servisi göçü, `-4120`).
- Binance geliştirici dokümanı: Sub Account, "Get Futures Position-Risk of Sub-account (V1/V2)" (ana hesap ucu; izin bilgisi bulunamadı).
- Binance SSS 360033162192 "Leverage and Margin of USDⓈ-M Futures" (bakım marjı = notional × MMR − bakım tutarı; izole tasfiye formülü).
- Diğer her Binance bilgisi `docs/binance-arastirma.md` kaynaklarından (arama özetleri) ve bu belgede "doğrulanmadı" diye işaretlidir.

## Fable görüşü (20.11, öneri; ölçülmedi)

| Soru | Görüş | Gerekçe |
|---|---|---|
| F1 koruyucu işlem anahtarı | **Tutsun** (alt hesabın yalnız işlem izinli, çekme kapalı, IP kısıtlı anahtarı); yalnız %10 kapatma ve stopsuz pozisyon için | Borsa stopları pozisyon başına ~%22'de durur, günlük %10'u uygulamaz; motor ölürse kapatan kalmaz |
| F2 %10 kapsamı | **Hesap başı öncelikli**; bir hesabın %10'u diğerini kapatmaz (diğerinde yalnız alarm); toplam %10 dolarsa ikisi de kapanır | ML öncelikli; CT'nin kötü günü ML'yi kapatmamalı |
| F3 dolum | Açılış **IOC limit + bant** (majör 10 bp, altcoin/TradFi 25 bp; 5a p95 ile kesinleşir); kapanış/azaltma IOC dolmazsa hemen reduceOnly MARKET | Gecikmede kötü fiyata açmaktansa atlamak ucuz; kapanış dolmadan kalamaz |
| F4 borsa stopu | CT stopları **miktarlı reduceOnly**; `closePosition` yalnız koruyucunun son-sigorta stopunda | BorsaStop net miktar mantığı aynen taşınır; kısmi azaltmada yanlış tam kapanış olmaz |
| F5 HL gerçek kipi | **Kalsın (kapalı yedek)**, kod silinmesin, testler yeşil; yeni özellik yok; Aşama C'de 30 gün sorunsuzsa yeniden bakılır | 451 ve Algo stop belirsizliğinde tek geri dönüş yolu |

**K5 kabul eşiği (5a ölçümü; kullanıcı onayına gelecek).** Yön düzeltilmiş fark (aleyhimize +):
- **GEÇ:** medyan ≤ 1,0 bp **ve** p90 ≤ 10 bp **ve** ortalama ≤ 1,5 bp (bugünkü HL kayması: medyan 0,4, p90 6,6 bp; ~75 emir/gün × ~150 $ ile 1 bp ≈ 30–35 $/ay).
- **GRİ:** medyan 1–2 bp ya da p90 10–15 bp → karar Aşama A'daki 5 günlük paralel kâğıt kıyasına kalır.
- **DUR:** medyan > 2 bp ya da p90 > 15 bp ya da ortalama > 3 bp.
- **Asgari örnek:** ≥ 300 eşleşmiş dolum, ≥ 3 gün (biri hafta sonu), ≥ 15 coin; majör / altcoin / TradFi ayrı raporlanır, 30 dolumdan az grup için karar verilmez (`dogrulandi:false` kalır).

K1–K4, K6 (konum/yasal, KYC, tavan, başlangıç tutarı, BNB): Aşama C öncesi toplu sorulacak (orkestratör, 20.11). Aşama 0 ve A bunlara takılmadan sürer.
