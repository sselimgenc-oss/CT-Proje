# GÖREV T4 — Canlı motor (Sonnet)

Dayanak: `docs/RADAR_V1.md` §5–§6, K‑22/K‑23/K‑26/K‑28. Dal: `claude/t4-canli-motor` (main'den, T3 birleştikten sonra). Gerekirse 2 PR (a: motor + testler, b: Telegram + kurulum).
**İki kip, tek kod yolu (K‑29):** `kip: sanal` (cüzdan yok, 1.000 $ yatırılmış gibi) ve `kip: gercek` (API cüzdanı). Motor, kadro, boyut, risk, Telegram,
kayıt **aynı**; yalnız yürütücünün arka ucu değişir. Varsayılan `sanal`; `gercek` yalnız anahtar varsa ve `kurallar.yaml` `canli_kip: gercek` ise.
Kip geçişi = anahtar + bu ayar, motor yeniden başlatılır; sanal dönemin kasası/pozisyonları gerçek hesaba **taşınmaz** (gerçek hesap HL'den okunur).

## 0. T3 gerçek çıktısından gelen kurallar (K‑33, lider)
- **Kadro N'den küçük olabilir** (ilk günlük koşu: 10 kişi geçti, Yedek boş). Saha = min(N, kadrodaki kişi). Boş slot **nakit kalır**; slot tutarı
  yine `kasa / N`, boş slotun parası başka trader'a dağıtılmaz (risk büyümesin). Kadro büyüdükçe boş slot §5 giriş kuralıyla dolar (günde ≤ 2 değişiklik sayılır).
- `kadro.json` kaynağı: veri dalı `radar`, `radar/son/kadro.json` (`radar_yayimla.sh`). Dosya yoksa ya da `kosu_ms` 36 saatten eskiyse: saha olduğu gibi
  kalır, **yeni giriş yok**, düşme kuralları çalışır, Telegram alarmı (günde 1 kez).
- Korelasyon (`kadro.json` `korelasyon`): ilk günlerde az günlük veriyle (8 gün) hesaplı; kural yine uygulanır (≥ 0,7 → en fazla 2), kayıtta `kor_kirpildi`.
- `min_islem` eşiği bilgi koşusu sonrası lider kararıyla değişebilir; motor eşik okumaz, yalnız `kadro.json`'u okur (T4'ü etkilemez).

## 0b. Lider denetimi düzeltmeleri (K‑35, PR #504 birleşmeden önce)
1. **Slot toplam tavanı (kritik):** `boyut` tavanı bugün coin başına (3 × slot) — bir trader 5 coinde açarsa 5 × 3 × slot olur. RADAR §6 "slot başına 3,0x".
   Kural: bir trader'ın **tüm coinlerdeki** kopya nosyoneli toplamı ≤ `radar_slot_tavan_carpan` × slot; açılış/artırma bu kalana kırpılır (< 11 $ → atla, `slot_tavani`).
   `boyut.hedef_emir`'e `biz_slot_toplam_usd` girdisi; aynı kural `kopya_v5`'te (R1/6 aynı sayıyı görsün, K‑28). Altın örnek: slot 90,91, mevcut 2 coin 200 $ → yeni açılış en çok 72,73 $.
2. **Toplam marj tavanı (kritik):** açık pozisyonların başlangıç marjı toplamı (nosyonel / 3) + yeni emrin marjı ≤ serbest kasa (özsermaye). Aşan kısım kırpılır (`marj_yok`).
   Gerçek kipte HL zaten reddeder; sanal kipte bu olmadan getiri şişer.
3. **Trader hesap paydası (yüksek):** motor `clearinghouseState` yalnız ana dex okuyor; radar lider tablosu `accountValue` kullanıyor. Payda = tüm perp dex'lerin
   `accountValue` toplamı + spot USDC (`hl_ortak.spot_usdc`). Böylece birleşik/spot hesaplı trader'da oran şişip her emir tavana vurmaz.
4. **Gerçek kipte kasa (orta):** kullanılan kasa = min(`canli_kasa_usd`, HL hesap değeri); `--kontrol` bunu raporlar.
5. Her biri testle; sanal vardiya kaydında `slot_tavani` / `marj_yok` sayıları PR özetine.

## 1. Yapı (`copytrade/canli/`)
- `motor.py` — tek süreç: `dinleyici.py` WebSocket (userFills, İlk 11'in sahadaki adresleri) → `boyut.hedef_emir` → risk (`risk.py`) → `yurutucu.py`.
  Mevcut `dinleyici.py` / `live_koruma.py` yeniden kullanılır (kural 7); `risk_defter.py`'nin sabit tutar boyutu **kullanılmaz** (yerini `boyut.py` aldı).
- `kadro.py` — her 5 dk `radar/son/kadro.json` (veri dalı, salt okunur HTTPS) okunur; §5 saha kuralları: ilk gün sıra 1–11 sahaya; giriş/histerezis
  (aday sıra ≤ 11, üye sıra > 11, form farkı ≥ 10); günde ≤ 2 değişiklik; düşme: anında (slot −%10, kaldıraç > 20x), günlük (sıra 2 gün > 22 / 1 gün > 30,
  72 sa işlem yok, R1 elemesi); sonuçla düşene 14 gün bekleme, sonuç dışına yok; korelasyon ≥ 0,7 en fazla 2. Durum `durum/saha.json`.
- `yurutucu.py` — ortak arayüz `emir(coin, yon, usd, reduce_only) -> dolum`; iki arka uç:
  - **Sanal:** emir anında HL `l2Book` alınır, bizim tutarımızla defter yürünür (IOC: ± %0,5 bandı dışında kalan kısım dolmaz), dolum fiyatı = yürünen
    ortalama, ücret = taker; izole 3x marj ve tasfiye fiyatı yerelde hesaplanır (mark fiyatı her dakika). Kasa `canli_kasa_usd` (kullanıcı ayarı: 100/250/500/750/1000…, üst sınır 1.000; K‑30) — sanal ve gerçek kipte aynı ayar;
    gerçek kipte motor bu tutarın üstünü kullanmaz (hesapta daha fazla olsa bile).
  - **Gerçek:** HL resmi Python SDK (`hyperliquid-python-sdk`, sürüm sabit, ≥ 2 haftalık). Coin başına **izole 3x** (`update_leverage`), **IOC limit**,
  fiyat = en iyi karşı fiyat ± %0,5; azaltma/kapama **reduce-only**. Dolmayan kısım yeniden denenmez. Anahtar yalnız ortam değişkeninden
  (`HL_API_CUZDAN_ANAHTARI` = para çekme yetkisiz API cüzdanı; `HL_HESAP_ADRESI` = ana hesap, açık). Anahtar yoksa motor başlamaz.
- `risk.py` — §6: coin başına tüm slotlar ≤ kasanın %30'u (aşan kırpılır); patlama freni (10 dk ≥ 8 yeni coin → 30 dk ara); günlük kayıp ≥ %5 → o gün
  yeni açılış yok; zirveden −%20 → tüm pozisyonları reduce-only kapat, motor durur, `durum/DUR` yazılır (elle silinmeden yeniden açılmaz); `/kapat` aynı (2026-11-05: eski `/dur` → `/kapat`; yeni `/dur` yalnız yeni girişi durdurur, `/devam` açar).
- `mutabakat.py` — gerçek kipte her 60 sn HL `clearinghouseState` ile bizim defter (sanal kipte defter ↔ mark fiyatı tutarlılığı); fark > %1 → alarm, motor yeni açılışı durdurur (yetim/pozisyon kaçağı).
- `telegram.py` — Bot API doğrudan (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` ortamdan): saha giriş/çıkış, her emir (kısa), alarm, 09:00 TR günlük özet
  (kasa, gün/toplam getiri, saha 11, açık pozisyonlar); komut `/dur`, `/durum`.
- Kayıt: her olay JSONL (`kayit/<tarih>.jsonl`): trader dolum zamanı, görme zamanı, emir/dolum fiyatı, kayma, ücret, neden. Yeniden başlatmada HL'den
  açık pozisyonlar + `durum/` okunur, kaldığı yerden devam (çift emir yok: işlenen dolum kimlikleri saklanır).

## 2. Testler (sahte borsa; altın örnekler)
- Sanal yürütücü altın örneği: elle yazılmış `l2Book` (3 seviye) ve 50 $ alış → yürünen ortalama fiyat + ücret elle; band dışı kısım dolmaz.
- Uçtan uca: sahte WS dolumu → doğru emir (tutar, yön, reduce-only, IOC fiyatı ± %0,5) → defter. Boyut örnekleri T3 ile aynı.
- Risk: coin %30 kırpması; patlama freni zamanlaması; −%5 günlük; −%20 kapanış + DUR; `/dur`.
- Saha: histerezis, günde 2, bekleme ayrımı (sonuç / sonuç dışı), korelasyon kuralı, ilk gün.
- Dayanıklılık: WS kopması + yeniden bağlanma ve kaçan dolumun REST ile tamamlanması; yeniden başlatmada çift emir yok; anahtar yoksa başlamaz;
  SDK hata/ret yanıtı kaydedilir, motor çökmez.
- Kod taraması: anahtar/tokens repo'da yok (test), `AGENTS.md` sınırı: kasa > 1.000 $ görülürse yeni açılış yok + alarm.

## 3. Nerede çalışır
- Sürekli açık makine (sunucu) hedeftir. Sunucu açılana kadar **sanal kip** GitHub Actions'ta vardiyalı koşar: `canli_vardiya.yml`, 4 saatte bir başlar,
  4 sa 15 dk sürer; durum veri dalı `canli-durum`'da; yeni vardiya başlayınca eskisi devreder (kilit dosyası, çift emir yok); açılışta kaçan dolumlar REST
  ile tamamlanır ve `gec_goruldu` işaretlenir (o anki fiyatla). **Gerçek kip asla Actions'ta koşmaz.**

## 4. Kurulum (T5'e hazır)
- `deploy/sg-canli.service` (systemd, yeniden başlatma), `deploy/kurulum.md` (Ubuntu 24.04: python, repo, `.env` izinleri 600, servis aç/kapat).
- `python -m copytrade.canli.motor --kontrol`: anahtar, bakiye, HL bağlantısı, kadro okuma, Telegram — **emir göndermez**, rapor yazar (T5 açılış kontrolü).
- Kabul: `pytest -q` yeşil; sanal kip Actions vardiyasında 1 vardiya (≥ 4 sa) gerçek WS verisiyle koşmuş, kayıt özeti PR'da (emir sayısı, ortalama kayma,
  kasa, saha 11); GitHub runner'da `--kontrol` benzeri salt okunur koşu (anahtarsız: bağlantı + kadro okuma) yeşil; `DURUM.md` güncel.
