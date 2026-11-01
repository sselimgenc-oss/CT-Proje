# Ofis veri şeması (v1, 2026-10-28; sürüm 2 alanları eklendi, `surum` hâlâ 1: yalnız ekleme, geriye dönük uyumlu)

Tek giriş dosyası: `ofis/ornek_durum.json`. Biçim `sg-arge/docs/VERI_SOZLESMESI.md` tarzındadır (`surum`, `uretildi`, `kaynak`).
Varsayılan kaynak **gerçek veridir** (§9: `ofis/gercek.js`); örnek veri yalnız `?durum=ornek` ile açılır.
Sayfa `surum` ≠ 1 ise veriyi reddeder ve "Sahte veri gösterilmiyor" der (sessizce örnek göstermez).

## 1. Kurallar
- **Her sayının yanında zaman damgası ya da n vardır** (`zaman`, `gun_n`, `n`). Ekranda hep birlikte gösterilir.
- **Veri yoksa "bilinmiyor"** yazılır, sıfır değil: alan `null` ya da hiç yok → panel "bilinmiyor" der. Örnekte
  `veri_kalitesi[gecikme].deger = null` bunu gösterir.
- **Örnek veri işareti:** `kaynak` değeri `ornek` ile başlıyorsa ofiste köşede "örnek veri · adresler uydurma" şeridi, her kartta `örnek`
  rozeti ve trader ipuçlarında `örnek` görünür. Gerçek veride `kaynak` `hyperliquid` vb. olur ve etiketler kalkar.
- Örnekteki adresler uydurmadır (`0xAAAA…0031` biçimi); gerçek adres yoktur.
- Para birimi USD; oranlar yüzde olarak (`kz_yuzde: 2.1` = %2,1), kasa payları 0–1 arası.
- Zamanlar ISO-8601 UTC (`2026-10-28T14:20:00Z`); ekranda yerel saat (SS:DD).

## 2. Üst düzey alanlar
```json
{
  "surum": 1,
  "uretildi": "2026-10-28T14:20:00Z",
  "kaynak": "ornek (sahte veri; adresler gerçek değil)",
  "vardiya": {"gunduz_baslangic": "07:00", "aksam_baslangic": "19:00"},
  "cipler": {"golge": "GÖLGE · SİM", "telegram": "AÇIK"},
  "kasa": {...}, "ozet": {...}, "katlar": {...}, "traderlar": [...],
  "acik_islemler": [...], "kapananlar": [...], "kohort_kontrol": {...},
  "veri_kalitesi": [...], "risk": {...}, "telegram": {...}, "tarama": {...},
  "olaylar": [...], "akis_suresi_sn": 156
}
```
Gün ışığı **gerçek saate** göre sayfada hesaplanır (arayüzde yalnız "ışık saati" görünür; `vardiya` alanı artık gösterilmez, şemada geriye dönük uyum için durur); `?saat=SS:DD` ile denenebilir.
`cipler.golge` ve `cipler.telegram` değerleri sol menü altındaki durum plakalarında ("kayıt kipi", "haber hattı") küçük harfle gösterilir; yoksa "bilinmiyor".

## 3. Alanlar
**`kasa`** (gölge kasası, sanal): `deger_usd`, `baslangic_usd`, `zaman`, `gun_n` (kaç günlük veri), `egri: [["2026-10-20", 1000.0], …]` günlük değer.
**Ön kayıt (performans körlüğü):** `deger_usd` ve `egri` veri olarak durur ama **ofiste gösterilmez**: kasa kartı ve Finans ekranı "kilitli (hafta x/12)" der; yalnız `baslangic_usd`
ve açık işlem teminatı görünür. Aynı kural `ozet.bugun_kz_usd` (günlük toplam K/Z) ve kol toplam getirileri için de geçerlidir. Kapatma: `Off.KILIT` (`office.js`), yalnız lider kararıyla.

**`ozet`**: `islem_basi_usd` (kural), `bugun_kz_usd`, `bugun_acilan_n`, `bugun_kapanan_n`, `zaman`.

**`katlar`** (huni): her biri `{n, masa, zaman}`; `oda` ayrıca `kapasite`. `n` gerçek sayıdır; `masa` ofiste çizilen koltuk sayısıdır
(en yüksek puanlı `masa` adres figür olur, kalanı yalnız sayıdır — ofis ölçeklenmez). `havuz` → Lab, `aday` → Aday, `oda` → Oda, `kontrol` → Kontrol grubu.

**`traderlar[]`**: `id`, `adres` (kısa), `kat` (`lab|aday|oda|kontrol|disari`), `kol` (`havuz|kohort|kontrol`), `tarz` (`intraday|swing`),
`etiket` (etiketlenme tarihi), `gun` (n), `islem_n` (n), `puan` (bilgi sütunu; karar vermez), `ornek: true`,
`kat_olay` (sürüm 2): `{id, kural, zaman}` = trader'ı bu kata koyan geçmiş olay (bilgi kutusunda "Neden burada?").
Yalnız figür çizilecek adresler listelenir (`masa` sınırı kadar).

**`acik_islemler[]`**: `id`, `trader`, `coin`, `yon` (`long|short`), `kaldirac`, `yas_dk` (veri üretildiğinde yaşı), `kz_usd`, `kz_yuzde`,
`lik_uzaklik` (likidasyona uzaklık, %), `teminat_usd`. Süre sütunu `yas_dk` + sayfada geçen süreyle akar.

**`kapananlar[]`**: `coin`, `yon`, `neden` (`trader_kapatti|zarar_kesme|sure`), `sure_dk`, `kz_usd`, `kz_yuzde`, `trader`. En yeni üstte.

**`kohort_kontrol`**: `hafta`, `hafta_toplam`, `performans_kilitli` (true ise **hiçbir performans sayısı gösterilmez**), `kollar: [{ad, n}]`
(kohort / kontrol / taban / elle liste), `onkayit` (metin), `zaman`.

**`veri_kalitesi[]`**: `anahtar` (`tarama|lab|arsiv|denetim|gecikme|mum`; ilk dördü ofiste ilgili odaya bağlanır), `ad`, `durum`
(`tamam|bayat|uyari|bilinmiyor`), `deger` (metin ya da `null`), `zaman` (ya da `null`).

**`risk`**: `zaman`, `tavanlar: [{anahtar, ad, kullanim, tavan, birim}]`; doluluk = `kullanim / tavan`; ≥ 1 → "TAVAN DOLU" ve Risk odasında alarm.
Eşikler yalnız `kurallar.yaml`'dadır; bu dosya yalnız okur.

**`arsiv`** (sürüm 2, isteğe bağlı): `turler: [{tur, satir, son_kayit}]`, `zaman` (Arşiv rafı bilgi kutusu). **`kapi`**: `bugun_gecen_n`, `bugun_elenen_n`, `zaman` (turnike bilgi kutusu).
**`telegram`**: `bugun_n`, `son: [metin]`, `zaman`.  **`tarama`**: `puanlar` (Tarama duvar ekranındaki sıralama çubukları), `zaman`.

## 4. Olay akışı (`olaylar[]`)
Her olay: `id` (**`olay_id`**, kalıcı ve tekil), `t` (örnek akışta saniye; gerçek veride `zaman` ISO), `tur`, `oda` (vurgulanacak oda), `kural` (olayı doğuran kural, kısa metin) ve türe özgü alanlar.
Yeni türler: `kirmizi_bayrak` / `bayrak_kalkti` (`trader`, `neden`). Türler, animasyon eşlemesi ve
panel etkisi **`OLAYLAR.md`**'dedir. Örnek akış `akis_suresi_sn` sonunda başa sarar (sayılar ilk veriye döner; kişiler başlangıç koltuklarına döndüğü
için akış döngü içinde tutarlıdır). Gerçek veride akış yeniden oynatılmaz: yeni olay geldikçe aynı işleyiciler çalışır.

## 5. Gerçek veriye bağlama (Faz 5 taslağı)
| Ofis alanı | Kaynak |
|---|---|
| `traderlar`, `acik_islemler`, `kapananlar`, `olaylar` | `izleme/durum.json` (v1.4) ve gölge defteri (`copytrade/golge.py`); olay `id`'leri kalıcıdır |
| `kasa`, `ozet` | Finans: gölge defterinin sanal kasası (`kurallar.yaml` işlem başı kural) |
| `katlar`, `kohort_kontrol` | `copytrade/kollar.py` etiketleri; kat geçiş kuralları ön kayıttan |
| `veri_kalitesi`, `risk` | Denetçi (akıl sağlığı kapısı, sağlama, gecikme zinciri) ve Risk modülü |
| `telegram` | Worker `/durum` ve bildirim günlüğü |
Eksik kaynak → alan `null` → ekranda "bilinmiyor"; sayfa hiçbir zaman eksiği sıfırla doldurmaz.

## 6. Adres parametreleri (denemek için)
`?durum=ornek` örnek veri (örnek şeridiyle) · `?durum=URL` başka veri dosyası · `?saat=SS:DD` gün ışığı · `?hiz=2` örnek akış hızı · `?etiket=0` trader etiketlerini gizler ·
`?hareket=0` hareketi kapatır (`prefers-reduced-motion` açıkken zaten kapalıdır) · `?oda=lab` açılışta odaya yaklaşır · `?perf=1` kare süresi · `#oda/<id>` adresi odanın iç görünümünü açar (`?oda=lab` aynısına çevrilir).

## 7. Kadro ve replikler (sürüm 2)
- **`kadro.json`**: varsayılan oda adları (`odalar[id]: {ad, yapar, yapmaz}`), çalışan adları (`calisanlar[id]: {ad, oda, yapar}`) ve nesne açıklamaları (`nesneler["oda.nesne"]: {ad, ne, suz}`).
  Kullanıcı adları **tarayıcıda** (`localStorage`, anahtar `sgofis.adlar.v1`) saklanır; **Adlar** düğmesinden JSON olarak dışa/içe aktarılır
  (`{"surum":1,"odalar":{…},"calisanlar":{…},"traderlar":{"T033":"takma ad"}}`; bilinmeyen kimlikler atlanır, ad ≤ 24 karakter). Ad yalnız etiketi değiştirir: veri ve trader'ın gerçek adresi (kısaltılmış) sabit kalır.
- **`replikler.json`**: `veri: [{olay_turu, rol, sablon}]` (olaydan doğar; `{yer_tutucu}` alanları olay/veriden dolar, yoksa "bilinmiyor") ve `suz: [{rol, metin}]` (ofis esprisi;
  **rakam, adres, oran, para içermez**; arayüzde ayrı, "ofis esprisi" etiketli kutuda). Test: `node ofis/test/replik.test.js`.

## 8. Sürüm 2b alanları (yalnız ekleme)
- `esik_dk` (dakika): her veri kaynağında (`kasa, ozet, risk, telegram, kohort_kontrol, arsiv, kapi, tarama, onkayit_kasasi`, `veri_kalitesi[]`, `katlar.*`). Bu yaştan eski veri "VERİ ESKİ" sayılır.
- `oda_kaynak: {oda: ["veri_kalitesi:lab", "katlar:havuz", …]}` ve `ekran_kaynak`: hangi oda/ekran hangi kaynaklardan beslenir (bayatlık buradan hesaplanır).
- `onkayit_kasasi: {surum, commit, dondurma_tarihi, zaman, esik_dk}`.
- `gecmis_olaylar[]`: `{id, zaman, tur, oda, trader?, metin, kural?}`; olay çekmecesi ve günlük özet bunu kullanır.
- Olaylarda `kural` zorunludur ve metin olaydan okunur; trader `kat_olay` kaydı terfi/kat düşürme olayında olaydan güncellenir.
- `kadro.json`: `olay_turleri[tur] = {ad, ton}`, `ozet_gruplari`, yeni nesneler (`risk.alarm`, `haberlesme.zarf_rafi`, `sekreterlik.onkayit_kasasi`, `oda.masa`).

## 9. Gerçek veri uyarlayıcı (`ofis/gercek.js`)
Kaynak (varsayılan; `?durum` yoksa): `sg-arge` veri dalı `copytrade-kapi`.
- Ağaç: `https://api.github.com/repos/sselimgenc-oss/sg-arge/git/trees/copytrade-kapi?recursive=1` (tek kimliksiz çağrı; `truncated` ise açık hata).
- En son seçim: `secim/<klasör>/secim.json` yolları klasör adına göre sıralanır (`<tarih>-v1.3`, aynı günkü `<tarih>`'ten sonra gelir).
- Kapı durumu: `secim.json`'da `kapi_tarihi` varsa o gün (v1.3), yoksa seçim tarihinden önceki/aynı en son `copytrade/kapi/<tarih>/durum.json`.
- Ham dosyalar `https://raw.githubusercontent.com/sselimgenc-oss/sg-arge/copytrade-kapi/<yol>`.
- Öneri (yayıncı): veri dalı köküne `son.json` `{"secim": "<klasör>", "kapi": "<tarih>"}` yazılırsa ağaç çağrısı gerekmez.

| Ofis alanı | Kaynak |
|---|---|
| `traderlar` (kat `oda`, `aday`) | `secim.json` `adresler`: `oda` kolundakiler → Oda (`O01…`); `aday` kolunda olup odada olmayanlar → Aday (`A01…`). Sıra: aday sırası, tarz, adres. Alanlar: `takma_ad` (adresin ilk 4 hanesi), `tarz`, `sira`, `medyan_kaldirac`, `en_yuksek_kaldirac`, `gun`, `genc_aday`. **`puan` taşınmaz.** |
| `katlar.*.n` | `secim.json` `sayilar` (havuz, aday, oda, kontrol); `masa` = çizilen figür sayısı (Lab 0, Kontrol 0) |
| `oda_sayilar.tarama` | `durum.json`: evren, işlenen, kapsam, hesap sürümü |
| `oda_sayilar.kapi` | `secim.json` `sayilar`: havuz, aday, oda |
| `kohort_kontrol.kollar` | oda, kontrol, taban, elle sayıları (kontrol kolu ofiste **yalnız burada** sayı olarak görünür) |
| `secim` | `{surum, tarih, kapi_tarihi, onaylandi:false}`; üst şerit: "Seçim <sürüm> — ön izleme, onaylanmadı (<tarih>)" |

Yeni alanlar (yalnız ekleme, `surum` hâlâ 1): `oda_durum: {oda: {gri, metin} | {gizli}}` — `gri` oda gri çizilir, köşede metin ("sanal izleme başlamadı") yazar, bilgi kutusu aynı metni söyler, sol panel kartı sayı yerine bu metni gösterir; `gizli` oda (kontrol) ofiste çizilmez, tıklanamaz, sol menüde yoktur. `oda_sayilar: {oda: [[ad, değer], …]}` oda bilgisi satırı. `secim`.
Gerçek veride: **kasa, özet, risk, telegram, kapanan işlem, olaylar boştur**; Lab, Finans, Risk gri; "örnek" rozetleri yoktur. Körlük: kâr/zarar, kol karşılaştırması, puan hiçbir yerde yer almaz.
**Açık işlemler** istisnadır: seçim etiketi onaylıysa (`secim.onaylandi`), yalnız Oda üyelerinin (`kollar` içinde `oda`) `copytrade-izleme/izleme/durum.json`'daki `pozisyonlar[]` listesinden gelir (`coin`, `yon`, `kaldirac`, `kz_usd`, `yas_dk`: açılıştan veri üretim anına kadar). Kaynakta olmayan `kz_yuzde`, `lik_uzaklik`, `teminat_usd` uydurulmaz, `null` kalır (panelde "bilinmiyor").

## 10. Acil leaderboard-only İlk11 snapshotı
Varsayılan yayın yolu, ofis sayfasına göre `../veri/ilk11/son.json` (`sg-pano/veri/ilk11/son.json`). Yayın ortamı `window.OFIS_ILK11_SNAPSHOT_URL` ile aynı sözleşmeye uygun, yayımlanmış JSON adresi verebilir. Kaynak `ilk11/acil_baslangic_leaderboard_only.json`; kaynak türü `acil_baslangic_leaderboard_only` ve `snapshot_id` alanı görünür biçimde korunur.

Bu snapshot yalnız Hyperliquid public leaderboard verisinden türetilmiş acil başlangıç rosterıdır. Normal Pazar 13:00 sonucu değildir, Kapı-qualified değildir ve Kapı geçişi iddiası taşımaz. Eksik K1/K5-K10 alanları ile Phase1 varsayılan puanı uyarıları `veri_kaynagi.uyari` içinde korunur. Puan ofise taşınmaz; `takim` alanı yalnız roster yerleşimini belirler (İlk11→oda, Yedekler→kontrol, PAF→aday), uygunluk veya Kapı kararı değildir.

Yalnız endpoint HTTP 404 döndürürse eski seçim uyarlayıcısı çalışır ve üstte `LEGACY` etiketi görünür. Diğer HTTP hataları ve bozuk JSON/şema/takım/uyarı verileri ofis hata bandında açıkça gösterilir; eski veriyle gizli devam edilmez. Test: `node ofis/test/gercek.test.js`.
