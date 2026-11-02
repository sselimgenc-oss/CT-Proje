# Görev: Trader seçimi — CT-Kapı v1.1 + Keşif verisi (3. adım, 2026-10-27, lider; kullanıcı onaylı)

Yapan: **Sonnet** (kullanıcı kararı 2026-10-27). Dal: `claude/kapi-v1-1`. Tek PR, `main`'e; lider birleştirir.
Ağ: bulut oturumundan Hyperliquid'e erişim yok (proxy 403) → canlı koşular GitHub Actions'ta. İş akışı geliştirme dalından
da tetiklenebilsin (`copytrade/kapi/CALISTIR` yoluna push); sonuçları veri dalından okuyup kontrol et.
Kaynak: `docs/GOREV_COPYTRADE_KAPI.md`, `copytrade/kapi.py`, son sonuç `copytrade/kapi/2026-10-27/`.
Eşikler aşağıdaki **kullanıcı kararlarıdır**; başka eşik değişmez. Eşikler koda gömülmez, `copytrade/kurallar.yaml`'a yazılır.

## Kullanıcı kararları (2026-10-27; Sol 6.1 görüşüyle)
Kullanım: bildirimle **elle** kopya. Kapı iki **tarz** tanır; her trader medyan elde tutma süresine göre birine girer:

| | Intraday | Swing |
|---|---|---|
| Medyan elde tutma | 1–24 saat | ≥ 24 saat |
| Scalp ayıklama: kısa işlem payı ≤ %25 | < 15 dk süren işlemler | < 2 saat süren işlemler |
| Adım 3 gecikme testi (zorunlu, net > 0) | 30 dk | 2 saat |
| Raporlanan stres gecikmesi (zorunlu değil) | 2 saat | 8 saat (negatifse `not: gece riskli`) |

- Gecikme giriş **ve** çıkış dolumlarına uygulanır; taker + kayma + funding dahil (`delayed_copy` bugün böyle; 480 dk eklenir).
- Medyan < 1 saat: tarz `scalp` → adım 3 Kaldı.
- Kaldıraç kuralları aynı (medyan ≤ 3x, en fazla ≤ 10x).
- Geçmiş ≥ 180 gün aynı; ≥ 365 gün olanlar sıralamada öne, 180–365 gün olanlar `genc_aday` etiketi.
- **Adım 6 alfa kıyası:** işlem hacminin ≥ %50'si kripto ise BTC (bugünkü gibi); değilse trader'ın işlem yaptığı
  varlıkların eşit ağırlıklı, maruziyet eşleşmiş al-tut sepeti (HIP-3 coinlerin 1 saatlik mumlarından).
- **Katman** (her satıra `katman`):
  - `kopyalanabilir` = adım 1–7'nin hepsi Geçti.
  - `izleme_adayi` = adım 1, 2, 3 Geçti (tarz + kaldıraç + gecikmeli kopya kârlı); 4–7 ne olursa olsun.
  - `yok` = diğer.

## Lider teşhisi (2026-10-27 sonucundan)
- **Plasebo hiç hesaplanamadı.** Adım 3+4'ü geçen 9 adresin hepsinde
  `plasebo_hata = non-overlapping placebo placement unavailable`. Nedeni `randomize_trades`: bir trader'ın **tüm** coinlerdeki
  işlemlerini birbirine hiç değmeyecek şekilde yerleştirmeye çalışıyor; aynı anda birçok coinde pozisyon tutan trader'da
  bu imkânsız.
- **Kapsam eksik:** 12.461 adresin 8.196'sı işlendi; 66 adres HTTP 500 ile düştü.
- Yeni eşiklerle kaba tahmin (eldeki %66 veriyle): swing adım 3 ≈ 22, adım 4 ≈ 4. Intraday ayrıca gelecek.

## İşler
1. **Plasebo düzeltmesi.** Çakışma yasağı **coin başına** olsun: aynı coinde aynı anda tek pozisyon, farklı coinler
   çakışabilir. Coin, yön, büyüklük, süre ve maliyet aynı kalır; 1000 tekrar; p ≤ 0,05. Bir coin coin başına da
   yerleşemiyorsa o coinin işlem dizisi bütün olarak rastgele **dairesel kaydırılır** ve `plasebo_not`'a yazılır. Gecikme
   tarza göredir: intraday 30 dk, swing 2 saat.
2. **Tarz ve eşikler** (yukarıdaki tablo); yeni sütunlar `tarz`, `kisa_islem_payi`, `gecikme_480dk_net`, `katman`,
   `genc_aday`, `alfa_kiyas` (`BTC` | `sepet`).
3. **Kapsam:** shard 16 → 32; `--eksikleri-tamamla` (aynı günün `sonuc.csv`'sinde olmayan veya `neden` alanı
   "veri hatası" olan adresler); HTTP 5xx için 3 deneme (artan bekleme); RAPOR'a "işlenen / evren" yazılır, hedef ≥ %98.
4. **İlişkili hesap kontrolü** (katmanı `yok` olmayanlara; puanı değiştirmez, işaret koyar). Kaynak:
   `arastirma/copytrade/argon_hazir_servis_iliskili_hesap.md`. İstekler: `subAccounts`, `userVaultEquities` +
   `vaultDetails.leader`, `extraAgents`, `userNonFundingLedgerUpdates` (iç transfer karşı adresleri). Sütunlar
   `iliskili_adresler` (`;` ile ayrılmış) ve `iliskili_not`.
   (yoksa yetim dal). Kapı sonuçları da bu dala yazılır, `main`'e yazılmaz.
6. **İş akışı:** `main`'den tetiklenir (`copytrade/kapi/CALISTIR` yolu ve elle); **haftalık zamanlama** (pazar, TSİ
   gece). `--yalniz-adim5` modu korunur: önce 9 adres için hızlı koşu, sonra tam koşu.
7. **Telegram Worker:** cron `*/5` → `* * * * *` (her dakika; ücretsiz plan yeter). Mesaja tarz etiketi
   `[Intraday]` / `[Swing]` eklenir; `durum.json`'daki `tarz` alanından okunur.
8. **İzleme motoru:** `durum.json`'da trader başına `tarz` (izleme listesinde yeni alan `tarz`; yoksa kapı sonucundan).
   Sanal kopya gecikmesi tarza göre: intraday 30 dk, swing 120 dk; `sanal_kopya.gecikme_dk` buna göre. Sözleşme v1.3:
   `traderlar[].tarz`.

9. **Binance karşılığı (HIP-3):** `binance_symbol` bugün tüm `xyz:` coinlerine "yok" diyor. Önek atılır; takma ad tablosu
   `kurallar.yaml`'da (GOLD→XAU, SILVER→XAG, BRENTOIL→BZ; diğerleri aynı ad) + `USDT`; Binance USDⓈ-M sembol listesinde
   (TradFi perp'ler dahil) varsa "var". Kaynak: `arastirma/copytrade/argon_uygulama_yeri.md`. Test: `xyz:GOLD`,
   `xyz:NVDA`, listede olmayan bir hisse.

10. **Plasebo 10.000 tekrar** (kullanıcı + Sol 6.1, 2026-10-27). Test ailesi = adım 1–4'ü geçen tüm adresler; `m`
    RAPOR'a yazılır. Tekrar sayısı sonuçlara göre değiştirilmez.
11. **Aktiflik (adım 2'ye ek, kullanıcı kararı):** son 90 günde kapanmış düz-düz döngü (dolum değil) intraday ≥ 20,
    swing ≥ 5; son işlem ≤ 30 gün önce. Kâr şartı yok. Sütunlar `son90_dongu`, `son_islem_gun`; eşikler `kurallar.yaml`.
12. **Yalnız rapor:** gece (TSİ 01–09) açılan işlem payı `gece_payi` (kapı ölçütü değil); gecikme testinin kapsadığı
    gün sayısı `gecikme_gun` (≈200, mum sınırı).
13. **Mutabakat:** `0x1404109f8cd4a79a0447365edbb7a13acd0b2f27` için gecikmeli kopya sonucunu ayrıntılı ver (aralık,
    işlem sayısı, coinler, HIP-3 dahil mi, payda, maliyet); bir model aynı adres için 190 günde −%22,6 buldu, bizde +%22.
14. **Kârlı ay eşiği (kullanıcı kararı 2026-10-27):** 1. aşama ≥ %44, adım 4 ≥ %49 (önce %60/%60). Gerekçe: swing
    trader'da kâr az sayıda büyük işlemden gelir; şans kontrolünü "en büyük işlem payı" ve "en iyisiz PF" yapar.
15. **Düşüş ölçümü hatası (hata düzeltmesi):** 2026-10-27 sonucunda 1.308 adreste `max_drawdown` > 1 (imkânsız).
    PnL / medyan hesap değeri paydası yatırma-çekme ve büyüyen hesapta bozuluyor. Düşüşü sermaye eğrisinden hesapla
    (zaman ağırlıklı getiri zinciri; yatırma/çekme getiri sayılmaz); 0–1 aralığında olsun; test ekle. Eşik (≤ %30) aynı.
16. **Dış adaylar:** `arastirma/copytrade/bagimsiz_secim/` dosyalarındaki tüm adresler leaderboard filtresinden
    bağımsız olarak kapıdan geçirilir; satıra `kaynak = dis_aday`.
17. **Kurallar donar:** 14–16 ile bu tur kapanır. Tam koşudan sonra eşik değişikliği yok; sonraki karar 3 aylık
    ileriye dönük sanal izlemenin sonucuyla.
18. **Lider denetimi (`docs/DENETIM_2026-10-27.md`) ekleri:** (a) mum eksik dolum varsa kopya getirisi o dolumları
    atlamasın — eksik oran > %0 ise satır `kopya_eksik` işaretli ve adım 3 `Yetersiz`; (b) ölü sütunlar
    (`liquid_coin_share`, `setting_leverage`) ya düzeltilsin ya kaldırılsın; (c) `userFillsByTime` geçmiş sınırına
    dayanan hesap `dolum_siniri` işaretli; (d) **akıl sağlığı kapısı**: birleştirmede oran/düşüş 0–1, kaldıraç 0–200, sabit
    ya da tamamen boş sütun yok, adım 1–4'ü geçende `plasebo_p` dolu; biri tutmazsa yayın yok ve iş kırmızı; testle sınansın.

### Sol 6.1 bağımsız denetimi (2026-10-27, `main` 82a8a74) — tam koşudan önce zorunlu
19. **Kopya defteri** (`kapi.py` `delayed_copy` ve çevresi): (a) mum araması en fazla 1 mum aralığı uzaklıkta; daha
    uzaksa o dolum "eksik" (iş 18a); (b) pencere başında açık olan pozisyon ayrı yönetilir — onu azaltan/kapatan dolum yeni
    ters pozisyon açmaz (dalda 05154c5 ile başlandı; teste bağla); (c) açık pozisyonlar her gün fiyatlanır (gerçekleşmemiş
    K/Z eğriye ve düşüşe girer); (d) funding trader'dan aktarılmaz, kopyanın kendi pozisyonu × funding oranıyla hesaplanır.
20. **Plasebo aynı motorla:** rastgele yerleştirilen işlemler gerçek kopyayla **aynı** hesaptan geçer — aynı
    ekleme/kısmi kapanış dizisi (yalnız ilk açılış miktarı değil), aynı tarz gecikmesi, funding dahil. Gerçek skor ile
    plasebo skoru aynı fonksiyondan çıkar.
21. **Alfa maruziyeti:** "o gün K/Z var mı" değil, gerçek pozisyon zaman çizelgesi (gün içinde açık pozisyon = maruz);
    kıyas belgeye göre BTC/sepet (iş 2) — kodda gerçekten uygulanmış olsun.
22. **Ölçüler** (`olcut.py`): kaldıraç = o andaki pozisyon değeri / o anki hesap değeri (zaman eşleşmiş), medyan zamana
    ağırlıklı; tersine dönen emrin ücreti kapanan ve açılan kısma miktarla bölünür; "en iyisiz PF" yalnız **bir** en iyi
    işlemi çıkarır; martingale emirleri gerçek sırayla işler.
23. **Tek kural kaynağı + uygunluk testi:** tüm eşikler yalnız `kurallar.yaml`'da (kodda sayı yok); bir test, görev
    belgesindeki kullanıcı kararlarını (`%44/%49`, 10.000, aktiflik, tarz eşikleri) yaml ile karşılaştırır. Dondurma:
    RAPOR'a `kurallar.yaml` + `kapi.py` + `olcut.py` SHA-256 özetleri ve aday listesinin özeti yazılır.
24. **Koşu dürüstlüğü:** iş akışında hatayı örten `|| true` kalkar; zaman aşımı/eksik parça varsa sonuç
    `durum: eksik` olarak yayımlanır, RAPOR'da kapsam yazılır, `kesif.json` eksik koşudan üretilmez.
25. **Altın örnekler (kabul):** elle hesaplanmış en az 6 küçük senaryo testi, her biri beklenen sayıyla:
    miras pozisyonun kapanışı; parçalı açılış/kısmi kapanış; tersine dönüş; gecikmede mum boşluğu; açık pozisyonun
    fiyatlanması; funding. Her senaryo hem kopya defteri hem plasebo motoru için aynı sonucu vermeli.
26. **Kapsam ayrımı:** bu daldaki `worker/` ve `izleme_motoru.py` değişikliklerini (cron, tarz etiketi, tarza göre
    gecikme) **ayrı küçük bir PR** yap; lider birleştirir. Bu dal yalnız kapı/ölçü dosyalarında kalır; izleme ve Worker
    düzeltmeleri Codex'te (`docs/GOREV_IZLEME_DUZELTME.md`).
27. **Hesap değeri tabanı (kullanıcı kararı 2026-10-27):** 1. aşamada bugünkü hesap değeri (`clearinghouseState`
    ana piyasa + tüm HIP-3 dex toplamı) **≥ 5.000 $** değilse Kaldı, `neden = hesap değeri tabanı`. Eşik yalnız
    `kurallar.yaml`'da (`hesap_degeri_min_usd: 5000`; kullanıcı kararı 2026-10-29: 10.000 → 5.000). Gerekçe: 69b0 eski kapıda "kopyalanabilir" çıktı ama hesap değeri
    0 $ (para çekilmiş). Altın örnek: 0 $ ve 4.999 $ Kaldı, 5.000 $ geçer. Kurallar donmadan önce eklenir.

## `kesif.json` şeması (v1)
```json
{"surum": 1, "uretildi": "…Z", "evren": 12461, "islenen": 12300,
 "adaylar": [{
   "adres": "0x…", "tarz": "intraday|swing|scalp", "katman": "kopyalanabilir|izleme_adayi",
   "genc_aday": false, "gecmis_gun": 365, "kapanan_islem": 120, "aktif_ay": 12, "hesap_degeri": 250000,
   "piyasa_payi": {"kripto": 0.7, "hisse": 0.2, "emtia": 0.1}, "binance_payi": 0.65,
   "medyan_tutma_sa": 30.5, "kisa_islem_payi": 0.08, "medyan_kaldirac": 1.8, "max_kaldirac": 6.0,
   "kopya": {"g30": 0.12, "g120": 0.09, "g480": 0.03},
   "karli_ay_orani": 0.67, "en_buyuk_islem_payi": 0.18, "pf_en_iyisiz": 1.6, "max_dusus": 0.22, "getiri_12a": 0.45,
   "plasebo_p": 0.03, "alfa_t": 2.4, "alfa_kiyas": "BTC", "bhy_q": 0.08,
   "adimlar": {"1": {"durum": "Geçti", "neden": ""}, "2": {"…": "…"}, "…": {}, "8": {}},
   "iliskili_not": "", "egri": [["2025-10-27", 0.0], ["2025-11-03", 0.012]]
 }]}
```
- Yalnız katmanı `yok` olmayanlar girer.
- `egri`: son 365 gün, haftalık, PnL / hesap.
- Sıralama: katman, sonra `genc_aday` olmayanlar, sonra `alfa_t`.
- Sayılar ham (oran 0–1); biçimlendirme panoda yapılır.

## Testler (ağsız)
- Plasebo: aynı anda iki coinde pozisyonu olan trader için yerleşir; tek coinde sığmayan dizi dairesel kayar ve not
  düşülür; 1000 skor üretilir.
- Tarz sınıflaması ve sınırlar (1 saat, 24 saat, kısa işlem payı).
- Katman kuralları.
- Alfa kıyası seçimi (kripto payı %50 sınırı).
- 5xx yeniden deneme; eksikleri tamamla birleştirmesi (tekrar satır yok).
- İlişkili hesap işaretleri (sabit yanıtlarla).
- `kesif.json` şeması.
- Worker'da tarz etiketi.

## Kabul
- `python -m pytest -q` ve Worker testleri yeşil.
- `--yalniz-adim5` koşusunda 9 adresin hepsinde `plasebo_p` bir sayı (ya da nedeni açık `plasebo_hata`).
- Tam koşuda işlenen ≥ %98; RAPOR'da huni tarz ve katmana göre ayrı.
- `kesif.json` veri dalında.
- `docs/codex_durum_trader_secimi.md`: yapılanlar, seçimler, sınırlar.

## Sonra
**kullanıcı onayıyla** güncellenir; t0 = giriş günü; 3 ay sanal izleme. Gerçek para yok.
