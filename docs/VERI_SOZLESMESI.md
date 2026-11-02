# Veri sözleşmesi — copy trade izleme (v1.14, 2026-11-02; v1.14 İlk 11 hesap katmanı kodda (A2 PR-1: `ilk11_alanlar`, kapı bilgi sütunları, `kapanan_islemler`), v1.13 İlk 11 puan alanları (§6, tanım), v1.12 `sanal_kopya_v3` tasfiye/aşamalı çıkış (E3), v1.11 `sanal_kopya_v3` (E2 sabit tutar), v1.10 `sanal_kopya_v2.kapanis_nedenleri` (E3), v1.9 `sanal_kopya_v2`, v1.8 `gecikme.json` taze pencere, v1.7 `gecikme.json`, v1.6 `saglik_hatti`, v1.5 `kol`, v1.2 olay kimliği, v1.3 tarz, v1.4 veri geçerliliği ve karar gizliliği)

sözleşmeye göre çalışır; alan eklemek/değiştirmek lider onayıyla `surum` artırılarak yapılır.

## 1. Dosyalar ve yer
| Dosya | Nerede | Kim yazar | Sıklık |
|---|---|---|---|
| `izleme/durum.json` | sg-arge, `copytrade-izleme` dalı (main büyümesin) | Codex işi (Actions) | saatte bir |
| `izleme/ornek_durum.json` | sg-arge `main` (sabit örnek, 4 trader) | lider (hazır) | sabit; Sonnet bununla başlar |
| `izleme/kararlar.jsonl` (açtım/atladım) | sg-arge, `copytrade-izleme` dalı | saatlik iş, Worker'ın `GET /kararlar`'ından (Cloudflare'de GitHub anahtarı yok) | saatte bir |
| `izleme/gecikme.json` (gerçek algılama gecikmesi, v1.7, E1 devamı) | sg-arge, `copytrade-izleme` dalı | saatlik iş, Worker'ın `GET /gecikme`'sinden (`copytrade/gecikme.py`) | saatte bir, `GECIKME_URL` tanımlıysa (yoksa adım atlanır, saatlik durum bozulmaz) |

Repolar herkese açık (kullanıcı kararı 2026-10-27). Bu yüzden karar kaydında **tutar, bakiye, hesap, isim yoktur**;
yalnız olay kimliği, karar ve neden. Trader adresleri zaten herkese açık zincir verisidir.

## 2. `durum.json` şeması
```json
{
  "surum": 1,
  "uretildi": "2026-10-27T14:20:00Z",
  "kaynak": "hyperliquid",
  "traderlar": [
    {
      "id": "T1",
      "adres": "0x378d…8e",
      "takma_ad": "Trader-1",
      "durum": "kopyala | izlemede | durdu",
      "t0": "2026-10-28",
      "veri_zamani": "2026-10-28T10:00:00Z",
      "gecerli": true,
      "kapi": {"sinif": "Geçti | Yetersiz | Kaldı", "tarih": "2026-10-27", "not": "en büyük işlem payı %36"},
      "saglik": {"isik": "yesil | sari | kirmizi", "nedenler": ["konide", "kaldıraç normal"]},
      "form": {"skor": 0.8, "getiri_30g": 0.042, "getiri_90g": 0.11},
      "hesap_degeri": 139680,
      "pozisyonlar": [
        {"coin": "BTC", "sinif": "kripto", "yon": "long", "giris": 68400.0, "buyukluk_usd": 11200,
         "hesap_payi": 0.08, "kaldirac": 2.0, "anlik_kz_usd": 310, "acilis": "2026-10-27T09:12:00Z",
         "binance": "var | yok | bilinmiyor"}
      ],
      "son_islem": {"coin": "ETH", "yon": "short", "acilis": "…", "kapanis": "…", "net_yuzde": 0.012},
      "egri": [["2026-08-01", 0.0], ["2026-08-02", 0.004]],
      "sanal_kopya": {"baslangic_usd": 1000, "bakiye_usd": 1043, "getiri": 0.043, "dusus": 0.021,
                      "gecikme_dk": 30, "t0": "2026-10-28",
                      "egri": [["2026-10-28", 1000.0], ["2026-10-29", 1004.2]]}
    }
  ],
  "olaylar": [
    {"id": "T1-20261027T091200-BTC-acilis", "zaman": "2026-10-27T09:12:00Z", "trader": "T1",
     "tur": "acilis | kapanis | buyutme | azaltma | isik", "coin": "BTC", "yon": "long", "fiyat": 68400.0,
     "hesap_payi": 0.08, "kaldirac": 2.0, "not": "",
     "sanal_sonuc": {"durum": "acik | kapandi", "net_yuzde": null, "kapanis": null}}
  ]
}
```
- `egri`: son 90 gün, günlük, t0'dan bağımsız trader'ın kümülatif PnL / hesap değeri (Hyperliquid `portfolio`).
- `olaylar`: son 200 olay, yeniden eskiye. `id` kalıcı ve tekildir (bildirim tekrarını ve kararı buna bağlarız).
- **Olay kimliği (v1.2):** `{trader}-{oid}-{tur}` (ör. `T1-123456789-acilis`); ışık olayı `{trader}-{ms}-isik`.
  Olaylar **emir (`oid`) düzeyinde** üretilir: aynı emrin dolumları birleştirilir (tek açılış sahte büyütmeler doğurmaz).
  Saatlik motor ve Cloudflare Worker aynı kuralla aynı kimliği üretir.
- `traderlar[].kol` (v1.5, ek alan; `surum` 1 kalır): `oda` | `kontrol` | `taban` | `elle` | `referans_oda` | `referans_kontrol` | `cikarilan` | `havuz` (K-8, sessiz ileri ölçüm); `kollar` adresin bulunduğu tüm kollar. İzleme listesinden
  aynen taşınır; Telegram Worker bildirimi yalnız `kol = oda` için gönderir (diğerleri sessiz izlenir).
- `traderlar[].secim` (v1.8, isteğe bağlı): izleme listesindeki değişmez seçim etiketi
  (`<secim_surumu>@<kapı tarihi>`). Tüketici, aynı etiketi en son `secim.json` ile
  eşleştirerek seçimin onaylı olduğunu gösterebilir. Sabit referans üyeleri eski
  `id`, `t0` ve etiketiyle `referans_oda` / `referans_kontrol` olarak sessiz izlenir.
- `traderlar[].yonsuz_bayrak` (isteğe bağlı, yalnız `kol` = `oda` | `kontrol`; `surum` 1 kalır; Argon A26, **yalnız bilgi**): `funding_payi`, `spot_perp_ters`, `maker_payi` — her biri `{deger, esik, asildi}`
  (`deger` hesaplanamazsa `null`; `spot_perp_ters` ayrıca `coin`), `bayrak` (herhangi biri aşıldıysa `true`), `pencere_gun` (90), `sezgisel: true`, okunamayan kaynak varsa `hata`.
  Funding ve spot durumu günde bir kez çekilir (önbellek `motor.json`'da). Eşikler `kurallar.yaml` `yonsuz_*`, sezgiseldir; seçim/kapı/oda kararını değiştirmez.
  deseninden esinlenilmiş — `copytrade/saglik_hatti.py`, saf fonksiyon, **yalnız rapor**; hiçbir pozisyon/kopya
  bundan etkilenmez; oda için **performans ışığından (`traderlar[].saglik.isik`) ayrı**, veri hattının kendisinin
  sağlığıdır): `{kol: "oda", n, yetim_golge_orani, isaret_eksik_toplam, veri_hata_orani, kirmizi_sayisi,
  sari_sayisi, acik_pozisyon_yasi_dk_medyan, isik: "yesil|sari|kirmizi", nedenler: []}`. `yetim_golge_orani` =
  oda'daki `veri_kalitesi.mutabakat.yetim` toplamı / `toplam` toplamı (mutabakat verisi yoksa `null`, sıfıra
  bölünmez); `veri_hata_orani` = `gecerli: false` olan oda üyesi oranı; `acik_pozisyon_yasi_dk_medyan` = son 180 dk
  içinde açılmış oda pozisyonlarının (`pozisyonlar[].acilis`) `uretildi`'ye göre medyan **yaşı** (dk) — bu **pozisyon
  yaşıdır, gerçek sinyal/algılama gecikmesi değildir** (Sol denetimi 2026-10-30); kopya ekonomisini değiştirmez.
  Eşikler `saglik_hatti.ESIKLER`. **Veri tazeliği burada değerlendirilmez** — yayım anında hesaplanırsa her zaman
  ~0 döner ve durmuş akışı yakalayamaz; tazelik tek yerde Worker'ın okuma anındaki gerçek saatiyle yaptığı mevcut
  3 saatlik kontrolündedir (`worker/src/index.js` `checkStateAlerts`).
- `kalabalik` (üst düzey, isteğe bağlı, oda üyesi varsa; Argon A27): `{n_oda, coinler: [{coin, net_yon, net_pay, ayni_yon, toplam, cakisma}], uyari, uyari_metni, zaman, sezgisel}`.
  `net_pay` = |Σ x·yön| / Σ|x|, x = kopya ağırlığı × pozisyon nosyoneli / trader hesap değeri (kaldıraç ikinci kez çarpılmaz). `uyari_metni` yalnız `uyari` iken dolu (tek satır; Telegram `/durum`).
  Eşikler `kalabalik_*` (sezgisel). Otomatik işlem yoktur.
- `traderlar[].tarz` (v1.3): `intraday` | `swing` (izleme listesinde `tarz` varsa o, yoksa en son kapı sonucundan; ikisi de yoksa
  `bilinmiyor` ve 30 dk gecikme). Sanal kopya gecikmesi tarza göre (intraday 30 dk, swing 120 dk);
  Telegram mesajında `[Intraday]` / `[Swing]` etiketi.
- `traderlar[].veri_zamani` ve `gecerli` (v1.4): trader verisinin son başarılı okuma zamanı ve geçerliliği. Bir saatlik
  okuma hata verirse önceki trader gösterilir, `gecerli: false` olur ve sağlık nedenlerinde `veri hatası` yer alır.
  Önceki başarılı kayıt hiç yoksa trader yine yayımlanır: `veri_zamani: null`, `gecerli: false`, sarı sağlık ışığı ve
  boş `pozisyonlar`; böylece eksik trader liste dışına sessizce düşmez.
- `sanal_kopya.not` (v1.2, isteğe bağlı): ör. `"yaklaşık fiyat"` (1 dk mum kaçınca 1 saatlik mum kullanıldıysa).
- `saglik.nedenler` `"veri hatası: …"` içerebilir (v1.2): o trader bu saat güncellenemedi, önceki kayıt gösteriliyor.
- `buyutme`/`azaltma`: aynı yönde pozisyonun **%25'inden fazla** değişimi (lider kararı); daha küçükleri olay sayılmaz.
- `sanal_kopya.gerceklesen`, `.acik`, `.toplam`, `.son_isaret`, `.isaret_eksik` (v1.6): sonuç kanonik defterden (`defter.copy_ledger`) üretilir; `gerceklesen` (maliyet ve funding dahil), `acik` (işaretlenmiş açık K/Z) ve `toplam` hesap değerine oran kesirleridir (`bakiye_usd = 1000 × (1 + toplam)`); `son_isaret` açık pozisyonlarda kullanılan en eski işaretin 1 dk mum zamanı (açık pozisyon yoksa `null`); `isaret_eksik` işareti bulunamayan açık coin sayısı.
- `traderlar[].veri_kalitesi.mutabakat` (v1.7, yalnız oda üyeleri, isteğe bağlı): defter (dolumlardan türetilen pozisyon) ↔ `clearinghouseState` mutabakatı — `uyumlu, yetim, eksik, yon_farki, boy_farki, toplam, uyumsuz_oran, yetim_coinler, sorunlu[], bozuk_satir, zaman`. **Yalnız rapor**: hiçbir pozisyon otomatik kapatılmaz.
- `sanal_kopya.egri` (v1.1): t0'dan bugüne günlük sanal bakiye (USD).
- `olaylar[].sanal_sonuc` (v1.1, yalnız `acilis`/`buyutme`): bu olayın 30 dk gecikmeli kopyasının sonucu; pozisyon
  kapanınca `kapandi` ve maliyet sonrası `net_yuzde` (kopyalanan tutara göre). "Açtıklarım" istatistiği bununla
  hesaplanır: kararı `acti` olan olayların `sanal_sonuc`'u ↔ tüm olaylarınki.
- **Yetersiz veri eşiği** (v1.1): bir trader için kapanmış ve kararı verilmiş olay sayısı < 10 ise istatistik
  sekmesi "yetersiz veri" yazar.
- `sanal_kopya`: t0 sonrası, 30 dk gecikmeli, maliyetli (taker %0,045 + kayma %0,05 + funding) — CT-Kapı
  `delayed_copy` ile aynı hesap.

### `traderlar[].sanal_kopya_v2` (v1.9 E2, v1.10 E3)
v1 (`sanal_kopya`) **silinmez ve yeniden yazılmaz**; v2 yan yana yayımlanır (AGENTS.md kural 6). Birim: 1.000 $
sanal kopya ölçeği (USD); getiri/oranlar kesirdir (0,012 = %1,2). **Tek motor** (kural 7): `copytrade/kopya_v2.py`
→ `golge.calistir` (variant **V2**) → `defter.copy_ledger` — araştırma gölgesiyle aynı yürütme/maliyet/tasfiye/çıkış
kodu. v1'e göre dört gerçek düzeltme (`docs/DENETIM_TRADER_2026-10-30.md` K2-K6):
- **Tasfiye:** kopya K/Z'si ayrılmış 1 birimin `golge_likidasyon_esigi`sine (kurallar.yaml) inerse pozisyonlar o
  saatin mum markında tasfiye edilir. `tasfiye` (bool), `tasfiye_zamani` (UTC ISO, yoksa `null`), `tasfiye_kaynagi`
  (`mum` | `gunluk_ozsermaye`). Tasfiyeden sonra `bakiye_usd` 0'da kalır; v1'de olduğu gibi **negatif olmaz**.
- **Pozisyon tavanı:** `golge_pozisyon_tavan_carpani` (3,0 = %300 notional) — v1'de yok; büyük/kaldıraçlı tek
  pozisyonun kopya hesabını orantısız oynatması (K5/K6) engellenir.
- **Aşamalı zarar_kes/kar_al (E3, v1.10):** ön kayıtlı/dondurulmuş eşikler (`kurallar.yaml` `golge_v2`,
  ONKAYIT_D v1.1 — **değiştirilmedi**): intraday zarar_kes −%50; swing gün 0 zarar_kes −%50, gün 7 zarar_kes
  −%30/kar_al %60, gün 14 zarar_kes −%20/kar_al %40 (ayrılmış teminata oranlı K/Z). Eşiğe değen pozisyon o saatin
  mumunda zorunlu kapanır (tasfiyeden ayrı; tasfiye eşiği her zaman önce denetlenir). `kapanis_nedenleri`:
- **Zamanla değişen payda:** her koşuda trader hesap değeri `hesap_serisi`ye eklenir (motor.json, en çok 3000
  okuma); `payda_yontemi` (`ilk_okuma` | `saatlik_okuma`), `payda_okuma_sayisi`.
- **Funding yalnız kopyalanan pozisyondan:** t0 öncesi devralınan pozisyonun funding'i kopyaya yazılmaz.
- Diğer alanlar: `baslangic_usd`, `bakiye_usd`, `getiri`, `dusus`, `egri`, `gerceklesen` (maliyet+funding dahil),
  `acik`, `toplam`, `funding`, `maliyet`, `fiyatsiz_eylem` (yürütme fiyatı bulunamayan dolum sayısı — **alt sınır**:
  `golge.v2_cikislari` kendi yürütme aramasında bulamadığı dolumu deftere hiç vermeden sessizce atar, bu sayıma
  girmez; gerçek veri denemesinde görüldü, bkz. `sanal_kopya_v3`), `gecikme_dk`, `t0`.
- Hesaplanamazsa `{"surum":"v2","durum":"hesaplanamadi","neden":...}`; v1'i etkilemez. Hiç okunmamış trader için
  `yer_tutucu: true`. Sabit $ işlem tutarı v2'de **yok** (hâlâ trader hesabına oranlı ölçek) — bkz. `sanal_kopya_v3`.

### `traderlar[].sanal_kopya_v3` (v1.11 E2 sabit tutar, v1.12 E3)
v1/v2 **silinmez ve yeniden yazılmaz**; v3 yan yana yayımlanır (AGENTS.md kural 6). Birim: 1.000 $ sanal kopya
ölçeği (v1/v2 ile aynı). **Tek motor** (kural 7): `copytrade/kopya_v3.py` → `defter.copy_ledger` (AYNI fonksiyon,
yalnız yeni `tutar_egrisi` parametresiyle — `golge.calistir`'in ön işlemesinden GEÇMEZ, risk katmanı doğrudan
`copy_ledger` içinde, bkz. aşağıda). v1/v2'nin **trader hesabına ORANLI** kopya ölçeğinin yerine:
- **Açılış:** kopya hesabının KENDİ o anki $ değerine (1 + şimdiye kadarki gerçekleşen + gerçekleşmemiş K/Z, ×1.000)
  büyüklüğü artık kopya boyutunu etkilemez (v1/v2'den temel fark).
  `masa.py _ekle` portu). **Azaltma/kapatma:** değişmedi (defterin ortak kuralı).
- **Tasfiye ve aşamalı zarar_kes/kar_al (E3, v1.12):** v2'deki AYNI dondurulmuş eşikler (`golge_likidasyon_esigi`,
  `golge_v2`, DEĞİŞTİRİLMEDİ) — ama `golge.py`'nin sentetik-dolum-enjekte-etme deseni değil, `defter.copy_ledger`
  içinde gerçek (yol bağımlı) `held`/`entry` üzerinde çalışan ayrı bir risk katmanı (`_risk_denetle`/`_zorla_kapat`,
  proportional `scale`'in sabit tutarda karşılığı olmadığı için). `tasfiye`, `tasfiye_zamani`, `tasfiye_kaynagi`,
  `kapanis_nedenleri` v2 ile AYNI anlamda doluyor. **Gözlem:** sabit tutar küçük olduğundan (eğri $1.000'da ~%2,
  $10.000 tavanında ~%15 açar), tek pozisyonun TEK BAŞINA gerçek fiyat hareketiyle bu eşiklere ulaşması pratikte
  nadirdir (küçük/çeşitlendirilmiş pozisyonların hesabı tek başına batıramaması tasarımın kendisi) — asıl devreye
- Diğer alanlar v2 ile aynı anlamda: `baslangic_usd`, `bakiye_usd`, `getiri`, `dusus`, `egri`, `gerceklesen`, `acik`,
  `toplam`, `funding`, `maliyet`, `gecikme_dk`, `t0`. `fiyatsiz_eylem` burada v2'nin ALT SINIRINDAN farklı olarak
  `defter.copy_ledger`'ın DOĞRUDAN/gerçek sayısıdır (`golge.calistir`'in ön filtrelemesinden geçmediği için).
  Gerçek veri denemesinde (B17, 2026-10-30) v2=0 (maskeli) ↔ v3=322 (gerçek) görüldü — v3'ün hatası değil, v2'nin
  raporlama eksiğinin açığa çıkması.
- **Kapsam dışı (ayrı GOREV alt maddeleri):** pozisyon tavanı (`golge_pozisyon_tavan_carpani` — "bitti tanımı" bunu
- Hesaplanamazsa `{"surum":"v3","durum":"hesaplanamadi","neden":...}`; v1/v2'yi etkilemez. Hiç okunmamış trader için
  `yer_tutucu: true`.
  (v1) yerine `sanal_kopya_v3`'ü gösterir — v1/v2 silinmedi/değişmedi (kural 6), yalnız "canlı" gösterilen sürüm
  budur. Bir tüketici `durum: "hesaplanamadi"` girdisini ortalamaya/toplama **0 olarak katmamalı**; gerçek `getiri`
  düzeltme deseni). `copytrade/degisim_rapor.py` (oda rotasyon ölçümü, `izleme/degisim.json`) da artık
  `sanal_kopya_v3.toplam` okur (kullanıcı kararı 2026-10-30). Rapora `kaynak: "sanal_kopya_v3"` ve
  `taban_sifirlandi` (bool) eklendi: önceki rapor `kaynak`sız (v1 dönemi) ise kaydedilmiş `cikarilan_taban_net`
  değerleri v3 sayılarıyla karıştırılmaz, taban v3'ten yeniden alınır. v3 hesaplanamamışsa değişim
  "izleme verisi bekleniyor" kalır, v1'e düşülmez.

## 3. Sağlık ışığı ve form
| Işık | Koşul (herhangi biri) |
|---|---|
| **kırmızı** (eşikler v1; kullanıcı sonra gözden geçirecek) | t0 sonrası getiri t0 öncesi geçmişten kurulan blok bootstrap konisinin %5 altında; zirveden düşüş > t0 öncesi en büyük düşüş × 1,5; gerçek kaldıraç > 10x; martingale işareti |
| **sarı** | koninin %5–%20 bandında; CUSUM uyarısı; son 30 günde işlem yok; kaldıraç 3–10x |
| **yeşil** | hiçbiri |

**Form skoru** = son 30 gün sanal kopya getirisi / son 90 gün günlük oynaklık. **Yalnız ekran sıralaması içindir**;
kopyalama kararını değiştirmez (karar: kapı + ışık).

## 4. Kararlar (açtım / atladım)
Kayıt: `{"olay_id", "zaman", "karar": "acti | atladi", "neden": "gec_gordum | begenmedim | diger",
"not": ""}` — `zaman` yalnız `YYYY-MM-DD`; `not` izinli etiket listesinden yalnız boş değerdir. Tutar, bakiye,
hesap, isim ve serbest metin yazılmaz. Eski `bakiye_yok` kayıtları içe aktarmada `diger`e çevrilir.
`copytrade-izleme` dalında `izleme/kararlar.jsonl`; v1'de karar yalnız Telegram düğmesiyle verilir.
İstatistik: aynı trader için "tüm olaylar" ile "açtıklarım" sanal sonuçları ayrı hesaplanır.

## 4a. Gerçek algılama gecikmesi (`izleme/gecikme.json`, v1.8, E1 devamı)
`{"n": <int>, "n_toplam": <int>, "gecikme_dk_medyan": <float|null>, "gecikme_dk_maks": <float|null>,
"uretildi": <iso>, "trader_detay": [{"trader", "gecikme_dk", "zaman"}]}`.
`gecikme_dk` = Worker'ın bir dolumu gördüğü an ile o dolumun Hyperliquid'deki **gerçek** zamanı arasındaki fark
(dakika) — `copytrade/saglik_hatti.py`'deki `acik_pozisyon_yasi_dk_medyan` (pozisyon yaşı) ile **karıştırılmamalı**;
bu gerçek uçtan uca algılama süresidir. Worker yalnız her trader için **en son** örneği tutar (D1 ücretsiz yazma
kotası) — bu yüzden `trader_detay` oda üyesi sayısı kadar satır taşır, geçmiş birikmez, ve uzun süre işlem
yapmayan bir trader'ın örneği D1'de eskiyebilir. **v1.8 (Sol 2. denetimi, YÜKSEK bulgu):** `n`/medyan/maks yalnız
`zaman`'ı `uretildi`den en çok 120 dk eski olan ("taze") örnekleri sayar; `n_toplam` tüm `trader_detay` satır
sayısıdır — eski bir trader örneği artık oda genelindeki "gerçek hız" ölçüsünü bozmaz. `n=0` → henüz taze örnek
yok (ilk koşu, sakin piyasa ya da tüm örnekler eski); medyan/maks `null`. Yalnız rapor; kopya ekonomisini değiştirmez.

## 5. Telegram
- Gönderen: Cloudflare Worker, 5 dakikada bir (`docs/GOREV_TELEGRAM.md`). Olay türleri: `acilis`, `kapanis`, `buyutme`,
  ışığın `kirmizi`ya dönmesi. Her `olay.id` bir kez bildirilir.
- Metin: `🟢 Trader-1 · BTC LONG açtı · giriş 68.400 · hesabın %8'i · 2x · Binance: var`
- Düğmeler (yalnız `acilis`/`buyutme`): **[Açtım] [Atladım]** → Atladım ise neden düğmeleri (Geç gördüm / Beğenmedim / Diğer).
- Gizlilik (v1.4, kullanıcı kararı): yayımlanan karar kaydında `zaman` yalnız tarih; `bakiye_yok` nedeni yok.
- Bot anahtarı ve sohbet kimliği yalnız GitHub Secrets'ta (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
  `TELEGRAM_WEBHOOK_SECRET`); dağıtım işi bunları Cloudflare secret'ına aktarır. Repoya, günlüğe, sohbete yazılmaz.

## 6. İlk 11 puan alanları (v1.13, 2026-11-02; K‑12)
Tanım belgesi: `docs/ILK11_SECIM_SARTNAME.md` §3–4. **Durum (v1.14):** 10 ham alanın hesap katmanı kodda (`copytrade/ilk11_alanlar.py`),
kapı `sonuc.csv` bilgi sütunları ve `sanal_kopya_v3.kapanan_islemler` üretiliyor; `traderlar[].ilk11_form_ham` (izleme) ve
`ilk11/<pazar>/` çıktıları A2 PR-2'de. Bu bölümde yazmayan
alan tüketilmez (kalite kuralı 2). Puan kodu `copytrade/ilk11.py` (değişmez); ham alanların tek hesap yeri `copytrade/ilk11_alanlar.py`.

**Ortak:** getiri ve oranlar **kesir** (0,012 = %1,2); zaman UTC; pencere sonu = Pazar snapshot `as_of` (Pazar 13:00 TSİ = 10:00 UTC)
ya da izleme okuma zamanı (`veri_zamani`). Eksik = `null` → alan puanı 35. Akıl sağlığı dışı değer `null` olur ve
`alan_kaynagi[alan] = "akil_sagligi_ihlali:<değer>"`. İ = ilk seçim (kapı satırı, uygun evren), F = haftalık form (izleme, kadro 50).

| Alan | Anlam | Birim / ölçek | Pencere İ / F | Kaynak İ / F | Aralık |
|---|---|---|---|---|---|
| `golge` | Kopya sonucu | oran; İ: trader hesabına oranlı defter neti; F: v3 işlem başı getirinin büzülmüş ortalaması (1.000 $ sanal kopya) | 200 g / 30 g | `secim.puan` (`gecikme_{kapi_gecikme_dk}dk_net`) / `golge_ozeti(sanal_kopya_v3.kapanan_islemler[].getiri)` | İ [−1, 10]; F [−1, 3] |
| `ay_roi` | Aylık getiri (zaman ağırlıklı, yatırma/çekme hariç) | oran, trader hesabı | 30 g / 30 g | `portfolio.month` → `kapi.twr_chain` (kapı sütunu `ilk11_ay_roi`) / aynı | [−1, 10] |
| `hafta_roi` | Haftalık getiri | oran, trader hesabı | 7 g / 7 g | `portfolio.week` → `twr_chain` (`ilk11_hafta_roi`) / aynı | [−1, 5] |
| `hesap` | Hesap büyüklüğü | $, trader hesabı | anlık / anlık | `hesap_degeri_bugun` (ana + HIP-3 + spot USDC) / `traderlar[].hesap_degeri` (ana + HIP-3) | [5.000, 1e9] |
| `dusus` | Aylık en büyük düşüş (düşük iyi) | oran, pozitif büyüklük (0,25 = %25) | 30 g / 30 g | `twr_chain` özsermayesi, `max(1 − e/cummax)` (`ilk11_dusus_30g`) / aynı | [0, 1] |
| `kazanma` | Kazanan kapanmış işlem payı (ücret dahil net > 0) | oran | 365 g / 30 g | `olcut.closed_round_trips` (`kazanma_orani`) / aynı, kapanışı pencerede | [0, 1] |
| `siklik` | Kapanmış işlem / gün | adet/gün | 365 g / 30 g | `gunluk_islem_sikligi` / pencere işlem sayısı ÷ 30 | [0, 200] |
| `tutma` | Medyan tutma süresi | **dakika** (saat × 60) | 365 g / 30 g | `median_holding_hours × 60` / `closed_round_trips` medyanı × 60 | (0, 525.600] |
| `kaldirac` | Efektif kaldıraç (pozisyon değeri / o anki hesap değeri), zaman ağırlıklı medyan | x | 365 g / 30 g | `median_leverage` / `olcut.effective_leverage_detail` | [0, 200] |
| `tutarli` | Pozitif gün oranı (ΔPnL > 0 gün / ΔPnL ≠ 0 gün, UTC gün) | oran | 30 g / 30 g | `portfolio.month.pnlHistory` (`ilk11_tutarli_30g`) / aynı | [0, 1] |

**Yeni alanlar (A2):**
- Kapı `sonuc.csv` bilgi sütunları (adım/eşik kullanmaz): `ilk11_ay_roi`, `ilk11_hafta_roi`, `ilk11_dusus_30g`, `ilk11_tutarli_30g`,
  `kazanma_orani` (yukarıdaki birimlerle; oran sütunları akıl sağlığı kapısında 0–1).
- `traderlar[].ilk11_form_ham` (izleme, saatlik; `ilk11_alanlar.form_ham_30g` çıktısı): `{alanlar: {10 alan, birimler yukarıdaki},
  alan_kaynagi: {alan: str|null}, pencere_bitis: UTC ISO (okuma zamanı, `YYYY-MM-DDTHH:MM:SSZ`), dolu_alan: int}`. `dolu_alan` = akıl sağlığı
  SONRASI `null` olmayan alan sayısı (0–10). Dolum verisi alınamadıysa (`fills = None`) `kazanma/siklik/tutma/kaldirac` `null`; alındı ama
  pencerede kapanmış işlem yoksa `siklik = 0`, `kazanma/tutma = null`.
- **Pencere kuralları (`ilk11_alanlar`):** pencere sonu = ilgili `portfolio` serisinin SON noktası (F'de ayrıca `pencere_bitis`). Getiri / düşüş
  zinciri `kapi.twr_chain` (Modified Dietz; yatırma-çekme getiri sayılmaz, sermaye ≤ 0 dönem 0 getiri): pencere = (son − N gün, son]; zincirin
  TABANI, `son − N gün` anında ya da ondan önceki SON noktadır (taban öncesi PnL sayılmaz); geçmiş pencereden kısaysa ilk nokta taban.
  `pozitif_gun_orani`: günün PnL'i = o UTC günün SON `pnlHistory` noktası, nokta olmayan gün önceki değeri taşır (ΔPnL = 0, paydaya girmez);
  pencere = son noktanın günü dahil son N takvim günü. `ilk11_ay_roi`/`ilk11_dusus_30g`/`ilk11_tutarli_30g` `portfolio.month`, `ilk11_hafta_roi`
  `portfolio.week` kullanır; pencere gün sayıları `kurallar.yaml` `ilk11_form_pencere_gun` (30) ve `ilk11_hafta_pencere_gun` (7).
- **Akıl sağlığı** (`ilk11_alanlar.akil_sagligi`, aralıklar `kurallar.yaml` `ilk11_saglik` + `saglik_max_kaldirac`): aralık dışı değer `null`,
  `alan_kaynagi[alan] = "akil_sagligi_ihlali:<değer>"` (tam sayı ise `1805`, değilse `repr`; `inf` → `inf`). Sınırlar DAHİL; `tutma` alt sınırı
  (0 dk) DIŞLANIR. Eksik (`null`/NaN) ihlal değildir (`alan_kaynagi = null`). Aday listesinde alan başına ihlal / aday > `saglik_max_hata_orani`
  (0,05) → koşu kırmızı (`saglik_sorunlari`); dolu / aday < `ilk11_min_doluluk` (0,90) → snapshot yok (`doluluk_sorunlari`).
- `traderlar[].sanal_kopya_v3.kapanan_islemler` (izleme): `[{coin, acilis, kapanis (UTC ISO), sonuc_usd ($, 1.000 $ sanal kopya
  ölçeği; maliyet + funding dahil), getiri (oran = sonuc_usd / işlemde açılan toplam $), neden (trader|zarar_kes|kar_al|likidasyon),
  gecerli (bool)}]`. Bakiye/getiri hesabını değiştirmez (kural 6; PR'da eski ↔ yeni fark 0). Üretim: `defter.copy_ledger(islem_kaydi=True)`.
  - **İşlem** = kopya pozisyonunun bir coinde 0'dan açılıp 0'a dönmesi; ters dönüşte kapanan kısım biter (satır), kalan miktar yeni işlemi açar;
    kısmi azaltmalar ve eklemeler aynı işleme yazılır. **Açık işlem listelenmez.** Satırlar kapanış sırasıyla.
  - `sonuc_usd` = gerçekleşen K/Z − taker/kayma maliyeti (ters dönüş dolumunda ücret miktarla bölünür: kapanan kısım / açılan kısım) +
    funding (işlemin açık kaldığı saat aralıklarının funding'i). `getiri` = `sonuc_usd` / işlemde açılan toplam $ (açılış + eklemeler, fiyat × adet ×
    1.000). `acilis`/`kapanis` = kopyanın YÜRÜTME zamanı (trader dolum zamanı + gecikme, mum açılışı); zorunlu kapanışta (zarar_kes, kar_al,
    likidasyon) risk denetimi saati.
  - `gecerli = true` ⇔ (a) işlemi açan trader dolumunun `time` değeri pencere başından (`t0`) sonra ve o an trader pozisyonu yatay (ya da dolum
    ters dönüştü) — trader'ın pencere öncesinden taşıdığı pozisyona eklemesi ya da kaçırılmış (fiyatsız) açılıştan sonraki ekleme **miras** sayılır,
    `false` — ve (b) işlem açıkken hiçbir trader dolumu fiyatsız (mum yok → `fiyatsiz_eylem`) kalmadı. Zorunlu kapanışlar (mum işaretiyle) geçerlidir.
    `false` satırlar listede kalır (sonuç gerçektir) ama `paper_sonuclari` ve `golge` (F) hesabına girmez.
  - Not: sabit tutarlı v3 yolunda `ledger.net` hiçbir zaman `None` olmaz; `durum: "hesaplanamadi"` dalı (kopya_v3) artık tetiklenmez.
  - Büyüklük: işlem sayısı t0'dan beri birikir (pencere süzgeci tüketicidedir); satır başına ~150 bayt.
- **İzleme `durum.json` trader alanları (A2 PR-2):**
  - `ilk11_gecerli_saat` = `{baslangic, saat, son_saat}`: trader'ın kadroya SON girişinden (`baslangic` = izleme listesindeki `takim_hafta`; yoksa `t0` günü) itibaren `gecerli == true` saatlik okuma sayısı (`saat`, tam sayı; `son_saat` UTC ISO). Aynı saatte ikinci koşu saymaz; `takim_hafta` değişince sıfırlanır; sayım bu motorun okumalarından başlar. Kalıcı kopya: `motor.json`. Pazar işi `gecerli_gozlem_suresi` (gün) = `saat / 24` (yalnız `baslangic == takim_hafta` ise).
  - `son_perp_dolum` (UTC ISO | `null`): trader'ın bilinen en son PERP dolumunun zamanı (spot hariç). `bu_pazar_aktif` ⇔ `(as_of − 7 gün, as_of]` içinde.
  - `ilk11_form_ham` hata durumunda `{"hata": "<metin>"}` (okuma düşmez; Pazar işi o trader için `bu_pazar_gecerli = false`); hiç okunmamış trader'da `{"hata": "hiç okunmadı"}`.
  - **`kapanan_islemler` kırpması (yalnız `durum.json`):** `sanal_kopya_v3.kapanan_islemler` yayında yalnız kapanışı `(now − ilk11_form_pencere_gun, now]` içinde olanlar VE (pencereden eski olsa da) en son `ilk11_durum_min_gecerli_islem` (6) GEÇERLİ işlemdir; `kapanan_islemler_toplam` tam geçmişin sayısıdır. TAM geçmiş `motor.json`'daki `son_trader`'da silinmeden tutulur.
- **Kapı `sonuc.csv` `ilk11_bilgi_hatasi`** (metin, yalnız hata olan satırda dolu): `kapi_bilgi_sutunlari` hesabı istisna fırlatırsa `ilk11_ay_roi`, `ilk11_hafta_roi`, `ilk11_dusus_30g`, `ilk11_tutarli_30g` boş (`NaN`) kalır ve hata `TürAdı: ileti` olarak yazılır; adım / katman / neden / `hata` ALANLARI değişmez (bilgi sütunu kapı sonucunu etkilemez, K-12.11).
- **İzleme listesi (`ilk11/izleme_listesi.yaml`, K-12.8):** kadro 50 (`takim`, `snapshot_id`, `form_puani` 0–100, `takim_hafta` YYYY-MM-DD) + 36 sabit referans satırı: mevcut listede `kol`/`kollar` içinde `oda` (18) ve `kontrol` (18) olan satırlar `referans_oda` / `referans_kontrol` olarak etiketlenir (`id`, `t0` korunur); taban / elle / havuz / cikarilan çıkar. Aynı adres tek satır. `id` yeni kadro üyesinde `K` + adresin ilk 10 hex'i, `t0` = snapshot günü.
- `ilk11/<pazar>/snapshot.json` (`copytrade-kapi` dalı): `snapshot_id` (gövdenin kanonik JSON SHA-256'sı), `sema`
  (`ilk11-pazar-v1` ilk seçim | `ilk11-form-v1` form), `as_of` (Pazar 13:00 TSİ, ISO +03:00), `kaynak_surumu`, `adaylar[]`
  (`id`, `uygun`, `uygunluk_nedeni`, `alanlar`, `alan_kaynagi`, `kapi_puani` (oran), `gecerli_gozlem_suresi` (gün)), `kadro[]`
  (`id`, `takim`, `puan` 0–100). Formda ayrıca `form_puani` (0–100), `bu_pazar_gecerli`, `bu_pazar_aktif`, `onceki_pazar_aktif` (bool|null).
  Form snapshot'ı (`ilk11-form-v1`) ayrıca `plan` (pazar_gecis çıktısı), `boslugu_dolduranlar` (K-12.6; bu hafta formdan çıkanlar aynı hafta geri alınmaz), `kadro_sonrasi`
  (`[{id, grup, takim_hafta}]`; sonraki haftanın "önceki kadro"su) ve `uyari` taşır. `kaynak_surumu`: `izleme` (durum.json commit SHA + `uretildi`), `onceki_snapshot`,
  `kapi` + `kapi_sonuc_sha256` (varsa), `ilk11_alanlar`, `kurallar`. `snapshot.json` adaylarda `id` = küçük harf trader ADRESİ. `akis.json`: `{deneme_sayisi, snapshot_id,
  son_basarisiz_at, basarili}`. `ilk11_pazar` çıkış kodu: 0 başarı/bekle/tamamla; 1 girdi-kalite hatası (yalnız RAPOR, snapshot yok); 2 form yayımlandı ama kapı eski/yok.
- **Kullanılmaz:** leaderboard `windowPerformances.roi` (payda yatırma/çekmeyle bozulur; acil kadroda 1805 = %180.500) ve leaderboard
  `accountValue`.
