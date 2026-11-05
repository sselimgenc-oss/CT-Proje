# Veri sözleşmesi — copy trade izleme (v1.24 §12 Radar havuzu; v1.23, 2026-11-04; T1: eski sistem — kapı, İlk 11 puan alanları, oda/kol — sözleşmeden çıkarıldı; yeni radar alanları T2+ ile eklenecek)

sözleşmeye göre çalışır; alan eklemek/değiştirmek lider onayıyla `surum` artırılarak yapılır.

## 1. Dosyalar ve yer
| Dosya | Nerede | Kim yazar | Sıklık |
|---|---|---|---|
| `izleme/durum.json` | sg-arge, `copytrade-izleme` dalı (main büyümesin) | izleme işi (Actions) | 2 saatte bir |
| `izleme/motor.json.gz` (ham dolum önbelleği, sıkıştırılmış; K‑20) | sg-arge, `copytrade-izleme` dalı | izleme işi (`gzip -n`; sıkıştırılmamış `motor.json` dala girmez) | 2 saatte bir |
| `izleme/ornek_durum.json` | sg-arge `main` (sabit örnek, 4 trader) | lider (hazır) | sabit; Sonnet bununla başlar |

Repolar herkese açık (kullanıcı kararı 2026-10-27). Bu yüzden yayımlanan dosyalarda **tutar, bakiye, hesap, isim yoktur**
(trader adresleri zaten herkese açık zincir verisidir).

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
      "saglik": {"isik": "yesil | sari | kirmizi | bilinmiyor", "nedenler": ["konide", "kaldıraç normal"]},
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
- `olaylar`: en çok 200 olay, yeniden eskiye; v1.17'den beri trader başına ADİL PAY (aşağıda). `id` kalıcı ve tekildir (bildirim tekrarını ve kararı buna bağlarız).
- **`olay_ozeti` ve olay arşivi (v1.17, A4-2):** `olaylar` toplam üst sınırı 200 (adet) KALDI, şema aynı (tüketiciler kırılmaz); ama artık global "son 200" değil **trader başına adil pay**: kotadan az olayı olan
  trader'ın tüm olayları yayımlanır, artan kota çok olay üretenlere eşit bölünür (artık 1'ler trader kimliği sırasıyla); her trader'ın EN YENİ olayları yayımlanır. Örnek: A 500, B 10, C 5 olay -> A 185, B 10, C 5 yayında.
  `olay_ozeti` = `{toplam, yayimlanan, tasan, trader_basina}` (adet; `trader_basina` TÜM olaylar, taşanlar dahil, trader kimliği -> adet; yayımlanan trader başı adet `olaylar`tan sayılır).
  Taşan olaylar atılmaz: motor `olay_tasan.jsonl` yazar (JSONL, bir satır bir olay, `olaylar` ile aynı şema), yayın betiği (`izleme_yayimla.sh`) bunu `copytrade-izleme:izleme/olay_arsivi.jsonl` dosyasına EKLER
  (eklemeli, `id` başına tekil, (zaman, id) artan; mevcut kayıt asla değişmez/silinmez). `olay_tasan.jsonl` dala girmez. Bir trader'ın tüm olayı = `durum.json.olaylar` (yayın payı) + `olay_arsivi.jsonl` (daha eski/taşan). Zaman UTC.
- **Olay kimliği (v1.2):** `{trader}-{oid}-{tur}` (ör. `T1-123456789-acilis`); ışık olayı `{trader}-{ms}-isik`.
  Olaylar **emir (`oid`) düzeyinde** üretilir: aynı emrin dolumları birleştirilir (tek açılış sahte büyütmeler doğurmaz).
- `traderlar[].kol` (v1.5, ek alan; `surum` 1 kalır): `oda` | `kontrol` | `taban` | `elle` | `referans_oda` | `referans_kontrol` | `cikarilan` | `havuz` (K-8, sessiz ileri ölçüm); `kollar` adresin bulunduğu tüm kollar. İzleme listesinden
  aynen taşınır.
- `traderlar[].secim` (v1.8, isteğe bağlı): izleme listesindeki değişmez etiket; eski seçim sistemi silindi (T1), alan yalnız listeden aynen taşınır.
  deseninden esinlenilmiş — `copytrade/saglik_hatti.py`, saf fonksiyon, **yalnız rapor**; hiçbir pozisyon/kopya
  bundan etkilenmez; oda için **performans ışığından (`traderlar[].saglik.isik`) ayrı**, veri hattının kendisinin
  sağlığıdır): `{kol: "oda", n, yetim_golge_orani, isaret_eksik_toplam, veri_hata_orani, kirmizi_sayisi,
  sari_sayisi, acik_pozisyon_yasi_dk_medyan, isik: "yesil|sari|kirmizi", nedenler: []}`. `yetim_golge_orani` =
  oda'daki `veri_kalitesi.mutabakat.yetim` toplamı / `toplam` toplamı (mutabakat verisi yoksa `null`, sıfıra
  bölünmez); `veri_hata_orani` = `gecerli: false` olan oda üyesi oranı; `acik_pozisyon_yasi_dk_medyan` = son 180 dk
  içinde açılmış oda pozisyonlarının (`pozisyonlar[].acilis`) `uretildi`'ye göre medyan **yaşı** (dk) — bu **pozisyon
  yaşıdır, gerçek sinyal/algılama gecikmesi değildir** (Sol denetimi 2026-10-30); kopya ekonomisini değiştirmez.
  Eşikler `saglik_hatti.ESIKLER`. **Veri tazeliği burada değerlendirilmez** — yayım anında hesaplanırsa her zaman
  ~0 döner ve durmuş akışı yakalayamaz; tazelik, tüketicinin okuma anındaki gerçek saatiyle `uretildi` karşılaştırmasıyla yapılır (pano: 2 saat; `bayat_isle`).
- `traderlar[].tarz` (v1.3): `intraday` | `swing` (izleme listesindeki `tarz`; yoksa `bilinmiyor` ve 30 dk gecikme; kapı sonucundan okuma T1'de kaldırıldı). Sanal kopya gecikmesi tarza göre (intraday 30 dk, swing 120 dk);

- **`traderlar[].veri_durumu` + `veri_durumu_neden` (v1.15, K-14):** tek bir eksik yüzünden trader takipten düşmez; durumu kodlanır. (`durum`
  izleme listesinin kendi alanıdır — `kopyala | izlemede | durdu` — ve değişmez; bu yüzden yeni alan `veri_durumu`.) Değerler, öncelik sırasıyla:
  - `okuma_hatasi`: bu saatin okuması başarısız (ağ / API). Önceki başarılı yük korunur (`gecerli: false`, `veri_zamani` eski); hiç okunmamışsa yer tutucu.
  - `perp_bos`: perp hesap değeri (ana + HIP-3 `marginSummary`) ≤ 0 ($). v3 ve olaylar yine hesaplanır (v3 trader hesabına bakmaz; `hesap_payi` 0);
    v1 (`sanal_kopya`, hesaba oranlı) ve v2 hesaplanamaz.
  - `fiyatsiz`: en az bir dolum için gecikmeli yürütme mumu yok (1 dk, ya da 1 sa yedek). Hedef atlanır ve sayılır (önbelleğe girmez, sonraki saat yeniden
    denenir); asla "sonraki fiyat" kullanılmaz. v1'de `sanal_kopya.fiyatsiz_eylem` (adet; atlanan dolum) ve `not`; v3'te `fiyatsiz_eylem` (`copy_ledger` sayısı).
    Açık kopya coini için son 15 dakikada işaret (1 dk) mumu yoksa da `fiyatsiz`: neden "işaret fiyatı eksik: <coin listesi>" (işaret eksiği bir FİYAT eksiğidir).
  - `bayat`: trader'ın `veri_zamani` değeri yayın anındaki `uretildi`'den `veri_tazelik_dk` (270 dk = 2 × 120 dk koşu aralığı + 30 dk tampon) dakikadan DAHA eski (sınır dahil değil) ve başka bir kod yok
    (öncelik: okuma_hatasi > perp_bos > fiyatsiz > bayat > tamam). `veri_durumu_neden`: "veri N dk eski (> 270 dk)".
  - `tamam`: yukarıdakilerin hiçbiri. `veri_durumu_neden`: kısa Türkçe metin (`tamam`da boş).
- **`traderlar[].mum_eksik` ve negatif önbellek (v1.16, K-18):** `{hedef, onbellekten}` (adet). `hedef` = bu koşuda fiyatı olmayan yürütme hedefi sayısı; `onbellekten` = bunların kaç tanesi
  API'ye YENİDEN SORULMADAN negatif önbellekten geldi. Eksik çıkan (coin, hedef dakika) `motor.json`'da `traderlar[ID].mum_eksik = {coin: {hedef_ms: son_deneme_ms}}` olarak
  saklanır (UTC ms, koşu `now`'u); 6 saat (`NEGATIF_MUM_YENIDEN_MS`) dolmadan sorulmaz, dolunca BİR kez yeniden denenir: mum gelmişse kayıt silinir ve dolum hesaba girer,
  gelmemişse kayıt tazelenir (kalıcı atlama yok; her 6 saatte bir yeniden). Önbellekten gelen hedef de `fiyatsiz` sayılır (`veri_durumu_neden` bunu söyler).
- **v1 yer tutucusu:** `sanal_kopya.yer_tutucu: true` (bakiye 1.000 $, getiri 0, `egri: []`; `perp_bos` ise `neden` da yazılır) — gerçek hesap DEĞİL.
  Tüketici `yer_tutucu` olanı ortalamaya / toplama katmamalı (v3 `durum: hesaplanamadi` ile aynı kural).
- **Sağlık ışığı `bilinmiyor` (K-14):** t0 için pozitif hesap değeri (sağlık paydası) yoksa ya da portfolio PnL eğrisi kurulamıyorsa `saglik.isik = "bilinmiyor"`,
  `nedenler[0] = "sağlık paydası yok: <neden>"` (kaldıraç / martingale nedenleri yine eklenir); takip, dolumlar ve v3 sürer; `egri` boş, `form.skor` 0. Payda sabitlenmez,
  sonraki saat yeniden denenir (`motor.json` `saglik_paydasi: null`). Perp hesap 0 iken kopya paydası (`kopya_paydasi`) 0'a SABİTLENMEZ.
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
- `sanal_kopya`: t0 sonrası, 30 dk gecikmeli, maliyetli (taker %0,045 + kayma %0,05 + funding) —
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
  dondurulmuş eşikler — **değiştirilmedi**): intraday zarar_kes −%50; swing gün 0 zarar_kes −%50, gün 7 zarar_kes
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
kopyalama kararını değiştirmez.

## 4b. `gecikme_kar.json` — H1 gecikme–kâr ölçümü (v1.19, 2026-11-03; K‑17)
YALNIZ ölçüm (bilgi amaçlı; eşik ve `durum.json` değişmez). Üretim: `python -m copytrade.gecikme_kar`.
Hesap tek motorda: `kopya_v3.hesapla` → `defter.copy_ledger` (kural 7). `kopya_v3.hesapla(delay=0)` = **anlık**: yürütme fiyatı trader'ın dolum fiyatı `px`,
yürütme zamanı dolum zamanı, maliyet ledger'daki taker + kayma (`kurallar.yaml` `maliyet_taker` + `maliyet_kayma`); `delay > 0` davranışı değişmedi.
Anlıkta `px` yok/≤ 0 ise dolum `fiyatsiz_eylem`e girer (mum aranmaz, sahte fiyat yok).

| Alan | Birim / anlam |
|---|---|
| `surum` | `"h1-v1"` |
| `uretildi` | UTC ISO; koşu başlangıcı (okuma zamanı değil) |
| `pencere` | `dakika` (t0 yerine `max(t0, şimdi − 4800 dk)`; bütün gecikmeler gerçek 1 dk açılışı) \| `tam` (t0'dan; 1 dk mum erişimi ~4999 dk dışındaki dolumlar saatlik açılışla YAKLAŞIK → kısa gecikmeler birbirinden ayrışmaz) |
| `gecikmeler_dk` | `[0, 1, 5, 30, 120]` (dk; 0 = anlık) |
| `maliyet.taker`, `maliyet.kayma` | ORAN, tek yön, notional'a oranla (varsayılan 0,00045 ve 0,0005; `--taker`/`--kayma` ile geçersiz kılınır; tüm gecikmelerde aynı) |
| `traderlar[].id` | izleme kimliği (örn. `O01`) |
| `traderlar[].adres` | küçük harf halka açık adres (bu dosya adres İÇERİR; `ozet.json`/`durum.json` gibi yayımlanmaz, yalnız CI artefaktı) |
| `traderlar[].tarz` | `intraday` \| `swing` \| `bilinmiyor` (bilinmiyorsa izleme varsayılan gecikmesi 30 dk) |
| `traderlar[].t0` | UTC ISO; ölçüm penceresinin etkin başlangıcı (`dakika` penceresinde kırpılmış olabilir) |
| `traderlar[].ilk_dolum` | UTC ISO; API'nin gerçekten döndürdüğü, pencere içindeki ilk perp dolumunun zamanı (`null` = dolum yok). Yalnız okunurluk — ölçümü DEĞİŞTİRMEZ. `t0`'dan belirgin sonraysa API'nin ~10.000 dolum sınırı pencereyi kısaltmıştır (aşağıdaki veri sınırı) |
| `traderlar[].dolum` | pencere içi perp dolum sayısı (adet) |
| `traderlar[].mevcut_gecikme_dk` | izlemenin bu trader için kullandığı gecikme (dk; intraday 30, swing 120) |
| `traderlar[].mevcut_net` | `gecikmeler[mevcut_gecikme_dk].net` (ORAN) — izleme `sanal_kopya_v3.getiri` ile `tam` pencerede karşılaştırılır |
| `traderlar[].gecikmeler.<dk>.net` | net getiri, ORAN (0,012 = %1,2); 1.000 $ sanal kopya ölçeği; gerçekleşen − taker/kayma + funding + açık K/Z (işaretle); hesaplanamazsa `null` (sıfır SAYILMAZ) |
| `…<dk>.islem` | kapanan kopya işlemi sayısı (adet; açık işlem sayılmaz) |
| `…<dk>.fiyatsiz` | yürütme fiyatı BULUNAMAYAN dolum (adet; eksik mum / anlıkta `px` yok). Yürütme zamanı gelmemiş dolum burada DEĞİL |
| `…<dk>.bekleyen` | yürütme zamanı (dolum + gecikme) henüz gelmemiş dolum (adet; anlıkta 0) — fiyatsız sayılmaz (B17 dersi) |
| `…<dk>.yaklasik` | yürütme fiyatı saatlik açılışla yaklaşık bulunan hedef (adet; yalnız `tam` pencere) |
| `…<dk>.tasfiye` | bool; kopya tasfiye oldu mu (v3 çapraz teminat) |
| `…<dk>.neden` | `null`; v3 `hesaplanamadi` döndürürse nedeni (metin). **Sınır:** sabit tutar yolunda motor `net` için `None` döndürmez — hiç fiyatı bulunamayan trader `net = 0,0`, `islem = 0`, `fiyatsiz > 0` görünür; `fiyatsiz` sütunu okunmadan `net = 0` yorumlanmaz |
| `traderlar[].fark_anlik_30dk` | `net(0) − net(30)`, ORAN puanı (0,01 = 1 puan); biri `null` ise `null` |
| `hatalar[]` | `{id, hata}`: okunamayan trader (ölçümü düşürmez) |
| `ozet` | `trader`, `anlik_hesaplanan`, `anlik_hesaplanamayan`, `anlik_kazanan` (net > 0), `anlik_kaybeden` (net < 0), `anlik_sifir`, `fark_anlik_30dk {min, medyan, maks}`, `fark_anlik_30dk_ortalama`, `anlik_30dk_karsilastirilan` |

**Veri sınırı (küçük gerçek veri denemesi bulgusu, 2026-11-03):** Hyperliquid `userFillsByTime` yalnız hesabın EN YENİ ~10.000 dolumunu döndürür (sayfa sınırı değil, API'nin geçmiş sınırı). Çok işlem yapan hesapta (B17: ~220 dolum/saat) pencere gerçekte `t0`'dan çok daha kısadır
(yerel kontrol: `t0` 29 Ekim iken ilk dönen dolum 3 Kasım 08:58) ve `dolum` sayısı pencere uzatıldıkça artmaz. Bu hesaplarda `traderlar[].t0` etkin başlangıcı DEĞİL istenen başlangıcı gösterir; `net` yalnız dönen dolumları kapsar ve ilk dolumlar miras pozisyona ekleme olduğundan `islem = 0` çıkabilir.
Büyük `bekleyen` (B17: 120 dk gecikmede ~4.500) hata değildir: son 120 dk'daki dolum sayısıdır (yerel kontrol: son 120 dk 4.511, son 30 dk 1.958 dolum).

Varsayım/sınır: anlık = bizim emrimizin trader dolumuyla AYNI fiyattan, kayma+taker ile dolması (algılama + emir gecikmesi 0 sayılır; gerçek gecikme H2 ile ölçülür).
Geçmişte dakikalık fiyat ~4999 dk ile sınırlıdır; `tam` pencerede 1/5/30 dk yaklaşık olur — karar için `dakika` penceresi esas alınır.

## 7. Dinleyici risk kapısı — DRY-RUN (v1.18, H5; `copytrade/risk_defter.py`, `copytrade/live_koruma.py`)
**Emir, anahtar, cüzdan, imza YOK; yalnız karar kaydı.** Her satır/blokta `emir_gonderildi` = `false`. Sınırlar `kurallar.yaml` `risk_dry_run:` bloğundan (tek kaynak).
Tüm tutarlar **notional $, 1.000 $ sanal kopya ölçeğinde** (trader hesabı DEĞİL); zaman UTC; fiyat $/coin; maliyet (taker/kayma) hesaba katılmaz.

| Anahtar (`risk_dry_run`) | Değer | Birim / anlam |
|---|---|---|
| `referans_kasa_usd` | 1000 | $ sanal kopya kasası (v3 boyut eğrisi bu kasanın o anki değeriyle çalışır) |
| `emir_tavan_usd` | 100 | $ tek emir notional tavanı |
| `trader_tavan_usd` | 200 | $ trader başına açık brüt notional tavanı (yeni sınır; ret nedeni `trader_tavani`) |
| `toplam_brut_tavan_usd` | 1500 | $ toplam açık brüt notional (1,5x referans) |
| `gunluk_zarar_usd` | 30 | $ UTC gün başından beri toplam K/Z düşüşü; eşit ya da aşınca şalter |
| `sinyal_tazelik_sn` | 10 | sn, dolum zamanı → karar anı (aşarsa `gec_sinyal`; tam 10 sn kabul) |
| `dur_dosyasi` | `$STATE_DIRECTORY/DUR` | dosya varsa yeni giriş/ekleme reddedilir (`yeni_ekleme_durduruldu`), çıkış serbest |

**Niyet kuralları (v3 ile aynı boyut):** yalnız `takim == ilk11` trader'lar için niyet üretilir (diğerleri `ilk11_disi` sayılır, yalnız ölçülür). Açılış tutarı `kurallar.sabit_tutar_egrisi` (defterle AYNI fonksiyon, `defter` yeniden dışa verir) × kopya hesabı değeri = `referans_kasa_usd` + gerçekleşen + gerçekleşmemiş (son görülen işlem fiyatı).
Ekleme = kopya notional × (trader'ın eklediği / trader'ın önceki pozisyonu). Azaltma/kapatma = kopya pozisyonunun trader'ın kapattığı oranı; ters dönüşte `exit` + `open` (iki niyet). Çıkış sınırlardan muaftır; kopyada açık pozisyon yoksa `acik_pozisyon_yok`.
**Miras pozisyon:** trader'ın zaten açık (kopyalanmamış) pozisyonuna eklemesi `miras_pozisyon` ile reddedilir; kapanışı `acik_pozisyon_yok`. Trader'ın dolum öncesi pozisyonu `startPosition`'dan (userFills / REST) alınır; `trades` kanalında YOK. **H5b (v1.20):** dinleyici her (yeniden) bağlanmada `ilk11` adreslerinin açık pozisyonlarını REST `clearinghouseState` ile (ana perp dex + her HIP-3 dex, `dex` parametresiyle; `szi` = işaretli coin miktarı, + long / − short) okur ve risk defterine başlangıç/tazeleme olarak verir; okunan listede olmayan coin **düzdür** (varsayım değil). Yeniden bağlanmada sıra: REST dolgusu → pozisyon tazeleme (REST gerçektir; o adresin önceki izlemesi silinir). Okuma anı `okuma_ms` ve öncesindeki dolum okumaya dahil sayılır, tekrar eklenmez (okuma anı = çağrıdan hemen ÖNCE; sınırdaki bir dolum için en fazla ~1 sn belirsizlik). Okuma **arka planda** yapılır (WS akışı ve gecikme/kaçan ölçümü hiçbir koşulda beklemez); istekler arası en az 0,5 sn. Bir adresin okuması (herhangi bir dex dahil; 429, ağ ya da geçersiz yanıt) başarısızsa kısmi sonuç uygulanmaz ve en çok 3 kez yeniden denenir (denemeden önce 2 / 5 / 15 sn bekleme). 3 yeniden deneme de başarısızsa `genel.baslangic_poz_hata` +1 olur ve o adres başarılı olana dek her 300 sn'de arka planda yeniden denenir; bu sürede YALNIZ o adres için eski varsayım geçerlidir: o coin için ilk gözlemde trader **düz varsayılır** (`lider_pozisyon_varsayimi` sayar). Başarılı okuma izlemeyi gerçeğe çevirir. Dex'ler ardışık okunduğundan okuma anı dex başına tutulur (çift sayım koruması dex'in kendi okuma anına göre). Yeniden bağlanmada tüm görevler iptal edilip yeniden başlar. Snapshot / abonelik öncesi dolumlar yalnız bu izlemeyi besler (niyet yok, `snapshot_gozlem`).
Günlük zarar şalteri **kilitlidir**: eşiğe değince UTC gün sonuna kadar (zarar geri dönse de) girişler `gunluk_zarar_limiti` ile reddedilir; UTC gün dönümünde baz sıfırlanır ve şalter açılır. Fiyatı olmayan dolum `fiyat_yok` ile reddedilir (tahmin yok). Aynı dolum iki kaynaktan gelirse (`{adres}:{tid}`) tek niyet. REST dolgusu geç gelir: girişleri `gec_sinyal` ile reddedilir, çıkışlar işlenir.

### `ozet.json` → `risk` (saatlik özetle birlikte; sayaçlar çalışma başından beri KÜMÜLATİF, defter bellekte — yeniden başlatmada sıfırlanır)
`niyet` (int), `kabul` (int), `ret` ({neden: adet}; bir karar birden çok neden taşıyabilir → toplam `niyet − kabul`'ten büyük olabilir), `acik_brut_usd` ($, açık kopya pozisyonlarının |miktar| × son fiyat toplamı), `gunluk_zarar_usd` ($, ≥ 0), `salter_tetiklendi` (bool), `dur_aktif` (bool), `ilk11_disi`, `gecersiz_dolum` (sıfır/negatif/eksik miktar ya da yön: niyet yok), `lider_pozisyon_varsayimi` (adet; YALNIZ REST başlangıç pozisyonu okunamayan trader'ın ilk gözlemlenen coin'i için), `baslangic_bilinen_trader` (adet; REST pozisyonu okunmuş ilk11 trader sayısı), `snapshot_gozlem`, `acik_pozisyon` (adet), `emir_gonderildi` (`false`). `genel.risk_hata`: risk katmanında yakalanan hata (dinleme sürer). `genel.baslangic_poz_okundu` (adet; başarılı trader okuması, yeniden bağlanmada tekrar sayılır), `genel.baslangic_poz_hata` (adet; 3 yeniden deneme de tükenen okuma turu — ağ/429/geçersiz yanıt; dinleme ve gecikme/kaçan ölçümü etkilenmez), `genel.baslangic_poz_yeniden_deneme` (adet; hızlı yeniden denemeler, 2/5/15 sn), `genel.baslangic_poz_arka_plan` (adet; 5 dk'lık arka plan denemeleri) ve `genel.baslangic_poz_bekleyen` (adet, anlık gösterge; arka planda hâlâ okunamayan adres sayısı). Hepsi yalnız risk açıkken yazılır; `bekleyen` dışındakiler çalışma başından beri kümülatiftir.

### `$STATE_DIRECTORY/risk_kararlari.jsonl` (adres YOK, takma ad)
Günlük döner (UTC gün sınırında `risk_kararlari.<YYYY-MM-DD>.jsonl`), son 7 gün tutulur. Satır: `zaman` (karar anı, UTC ISO ms), `gun` (UTC `YYYY-MM-DD`), `trader` (takma ad), `coin`, `aksiyon` (`open|add|exit`), `kabul` (bool), `nedenler` ([str]), `notional_usd` ($; fiyat yokken niyet tutarı), `fiyat` ($/coin | null), `dolum_zamani` (UTC ISO ms), `gecikme_sn` (sn), `kaynak` (`trades|userFills|dolgu`), `dur_aktif` (bool), `emir_gonderildi` (`false`).

### Liste alanı
Dinleyici listesinde İlk 11 üyeliği `takim: ilk11` alanıyla gelir (`copytrade/izleme_listesi.yaml`; `izleme_liste.load_list` şeması). Pilot liste `copytrade/izleme_listesi.yaml`'da `takim` yoktur → risk kapısı niyet üretmez. Yalnız DENEME için `--risk-tum-liste` listedeki herkesi "ilk11 sayar".

## 8. Dinleyici REST koruması — dolgu / hakem / başlangıç pozisyonu (v1.20; `copytrade/dinleyici.py`)
Sunucuda yeniden bağlanmada ~92 adresin `userFillsByTime` dolgusu art arda yapılıp 429 aldığı için (4 saatte `genel.dolgu_hata: 78`) **tüm REST işleri** (dolgu, hakem, başlangıç pozisyonu) tek desene bağlandı:
- **Arka plan:** hiçbiri WS akışını / gecikme-kaçan ölçümünü beklemez (REST çağrısı `asyncio.to_thread` içinde). Hakem turu sürerken yeni tur gelirse atlanır (`genel.rest_tur_atlanan`, adet). Hakem, bekleyen dolguyu önce bitirir (aynı aralıktaki dolumlar "kopma aralığı kaçanı" diye görülmüş işaretlenmesin).
- **İstek aralığı (iki ayrı ayar, lider kararı):** `userFillsByTime` (dolgu ve hakem; sayfa istekleri dahil, ortak sayaç) ardışık istekleri arası en az **1,5 sn** (`Ayar.rest_dolum_ara_sn`; ağırlık ≥ 20 → ≈ 13–15 ağırlık/sn ≈ 800–880/dk, HL IP sınırı 1.200/dk'nın altında, dinleyicinin diğer isteklerine pay kalır); `clearinghouseState` (başlangıç pozisyonu, ağırlık 2) arası **0,5 sn** (`Ayar.rest_poz_ara_sn`). Sunucudaki `dolgu_hata_tur` verisine bakılıp gerekirse değiştirilir.
- **Yeniden deneme:** dolgu ve hakemde bir adres için 429 / ağ / geçersiz yanıt hatasında en çok 3 yeniden deneme, öncesinde 2 / 5 / 15 sn bekleme (`Ayar.rest_bekleme_sn`). Dolgu: 3'ü de başarısızsa `genel.dolgu_hata` +1; adres **doldurulamayan en eski kopma aralığı başlangıcıyla** bekleyende kalır ve sonraki REST turunda (varsayılan 600 sn) yeniden denenir; yeni bir kopma bekleyen başlangıcı geriye çekmez (en eski korunur). Hakem: `genel.hakem_hata` +1; pencere (2 tur) sonraki turda yeniden kapsandığı için o adres sonraki turda yeniden denenmiş olur. Hakem hatası artık oturumu **koparmaz** (eski davranış: istisna → `kopma` → yeniden bağlanma → yeni dolgu fırtınası).
- **Kapanış turu** (servis durdurulurken son hakem; durdurma süresi 90 sn'yi aşmasın diye): bekleme / yeniden deneme yok ve **en fazla 60 sn** (`Ayar.kapanis_sinir_sn`). Yetişmeyen adresler (o an süren adres dahil) `genel.kapanis_atlanan` (adet) ile sayılır; son özet (`ozet.json`) her durumda yazılır. 91 adres × 1,5 sn ≈ 136 sn sürerdi → ≈ 40 adres taranır. Not: sınırda iptal edilen son istek bir iş parçacığında bitene kadar sürebilir (en çok istek zaman aşımı, 20 sn).

`ozet.json` → `genel` (hepsi adet, çalışma başından beri kümülatif; `*_bekleyen` anlık gösterge):
| Alan | Anlam |
|---|---|
| `dolgu` | dolguyla kurtarılan dolum (mevcut) |
| `dolgu_hata` | 3 yeniden deneme de tükenen dolgu adresi sayısı (mevcut; artık yalnız tükenmede) |
| `dolgu_yeniden_deneme` | dolgudaki yeniden deneme sayısı (2 / 5 / 15 sn beklemeli denemeler) |
| `dolgu_bekleyen` | hâlâ doldurulamayan adres sayısı (anlık) |
| `dolgu_hata_tur` | `{hata türü: adet}`; `dolgu_hata` ile aynı olaylar, tükenen turun SON hatasının sınıfı (toplam = `dolgu_hata`). Örn. `{"HTTP 429": 70, "Timeout": 8}` |
| `hakem_yeniden_deneme`, `hakem_hata`, `hakem_hata_tur` | aynı anlamlar, REST hakem için |
| `baslangic_poz_hata_tur` | `{hata türü: adet}`, başlangıç pozisyonu okuması için (toplam = `baslangic_poz_hata`); yalnız risk açıkken |
| `rest_tur_atlanan` | önceki hakem turu sürdüğü için atlanan tur |
| `kapanis_atlanan` | kapanıştaki son hakem turunda 60 sn sınırına yetişmeyen adres sayısı (adet) |

**Hata türü** = hatanın SINIFI (`hata_turu`): `HTTP <kod>` (örn. `HTTP 429`), `Timeout`, `Ağ (URLError)`, `Geçersiz yanıt`, ya da istisna sınıf adı. **Adres, URL ve sağlayıcı metni hiçbir yerde yazılmaz** (`ozet.json` adres içeremez, testli).
**Journal:** her REST hatası (yeniden denemeler dahil) stderr'e TEK satır: `UYARI REST hatası kaynak=<dolgu|hakem|baslangic_poz> trader=<takma ad> tur=<hata türü>` (`journalctl -u sg-dinleyici | grep "UYARI REST"`).

## 10. `pano.json` (Faz 2 pano; GitHub Pages `pano.json`, üretici `copytrade/pano_veri.py`, iş akışı `.github/workflows/pano.yml`) — v1.22
Girdiler (yalnız okunur): `copytrade-izleme:izleme/durum.json`, `copytrade/izleme_listesi.yaml` (alan `takim`: `ilk11` | `yedek11` | `paf`). (Eski İlk 11 snapshot girdisi T1'de kaldırıldı.)
Biçim `pano/ornek_veri.json` ile aynıdır; **panonun JS'i hiçbir şey hesaplamaz** (AGENTS kural 7). Motorda olmayan alan **`null`** (pano "—" gösterir); eksik alan sıfır sayılmaz, uydurulmaz: bir toplamın bir bileşeni `null` ise toplam `null`.
Oranlar kesirdir (0,012 = %1,2); zaman UTC; üyelik yalnız `takim` alanından (`kol` / `kollar` kullanılmaz). Takımlar sabit sırayla: `İlk 11`, `Yedek 11`, `PAF`.

**Ölçek (ekranda ve `olcek` bloğunda yazılıdır):** tüm tutarlar **1.000 $ sanal kopya, `sanal_kopya_v4`** (v3 + H5 risk sınırları, §11), trader başına. **Takım değeri üyelerin TOPLAMIDIR** (her üye 1.000 $ ile başlar): `kasa.baslangic_usd` = 1.000 × toplama giren üye sayısı. `kasa.olcek_notu` = `"<N> × 1.000 $ sanal (trader başına)"` (pano kasa kartında gösterir). Açık işlemler artık gerçek AÇIK KOPYA pozisyonlarıdır (`sanal_kopya_v4.acik_pozisyonlar`); kasa ile aynı ölçektedir. Pano kasası v3'ten v4'e geçti: v4 yoksa / hesaplanamadıysa üye veri vermemiş sayılır (v3'e düşülmez).

| Alan | Birim / anlam |
|---|---|
| `uretildi` | kaynak `durum.json`'un üretim zamanı (UTC ISO); pano bunu 2 saatten eskiyse sarı uyarıyla gösterir |
| `tazelik` | `{kaynak_uretildi, pano_uretildi (UTC), yas_dk (dk, pano_uretildi − kaynak_uretildi), esik_dk (120), bayat (bool: yas_dk > esik_dk; kaynak zamanı yoksa true)}` |
| `dinleyici` | `null` (sunucunun veri yazma yolu yok) |
| `takimlar[].kasa.baslangic_usd / bakiye_usd / degisim_usd` | $, v3 ölçeği, üye toplamı (`sanal_kopya_v3.baslangic_usd`, `bakiye_usd`); `degisim_usd` = bakiye − başlangıç |
| `kasa.degisim_oran` | oran = `degisim_usd` / `baslangic_usd` |
| `kasa.egri` | `[[UTC ISO gün başı, $]]`, son 30 gün: üyelerin `sanal_kopya_v3.egri` günlük değerlerinin toplamı, yalnız TÜM üyelerde değeri olan günler (eksik gün için değer uydurulmaz) |
| `ozet.nakit_usd` | $ = `kasa.bakiye_usd` − `acik_teminat_usd` (serbest teminat); teminat eksikse `null` |
| `ozet.islem_basi_usd` | `null` (motorda yok: sabit tutar eğrisi tek bir sayı değildir) |
| `ozet.acik_islem` | adet = açık kopya pozisyonu sayısı (`acik` satırı) |
| `ozet.acik_teminat_usd` / `acik_kz_usd` | $: `acik[].teminat_usd` / `kz_usd` toplamı (TOPLAM satırı ile aynı; bir satırda eksikse `null`) |
| `ozet.bugun_acilan` / `bugun_kapanan` | adet; "bugün" = `uretildi` (kaynak) tarihinin UTC günü. Açılan = bugün açılan `acik` (trader pozisyonu) + bugün açılıp bugün/sonra kapanan işlemler (kırpılmış `kapanan_islemler`); kapanan = `kapanis` bugün olanlar |
| `ozet.son24_islem` / `son24_kazanma_orani` | adet / oran: `kapanis` ∈ (`uretildi` − 24 sa, `uretildi`] olan kapanmış işlemler; kazanma = `sonuc_usd` > 0 (işlem yoksa oran `null`) |
| `ozet.kadro_dolu` / `kadro_toplam` | adet: `durum.json`'da geçerli v3 verisi olan üye (kopyası henüz başlamamış olanlar dahil) / her zaman `null` (kadro büyüklüğü kaynağı T1'de kaldırıldı; radar kadrosu T4'te) |
| `metrik.bugun_oran` / `hafta_oran` / `ay_oran` | oran: `kasa.egri` son gün / (1, 7, 30 gün önceki gün) − 1; o gün seride yoksa `null` (komşu günle yaklaşıklama yok) |
| `metrik.toplam_oran` | oran = `kasa.degisim_oran` |
| `metrik.maruziyet_oran` | oran = `acik_teminat_usd` / `kasa.bakiye_usd` |
| `metrik.kazanma_orani`, `kar_faktoru`, `ort_kazanc_oran`, `ort_kayip_oran`, `beklenti_oran`, `islem_sayisi` | `durum.json`'daki (KIRPILMIŞ, §`kapanan_islemler`) geçerli kapanmış işlemlerden: kazanma = `sonuc_usd` > 0 payı; kâr faktörü = Σ kazanç $ / Σ zarar $ (zarar yoksa `null`); ort. kazanç/kayıp = kazanan/kaybeden işlemlerin `getiri` ortalaması; beklenti = tüm `getiri` ortalaması; `islem_sayisi` = işlem adedi (tam geçmiş değil) |
| `seriler.bakiye` | `[[gün, $]]` = `kasa.egri`; `kumulatif_kz` = bakiye − başlangıç ($); `dusus` = bakiye / zirve − 1 (oran, ≤ 0); `gunluk_kz` = bakiye / önceki gün bakiye − 1 (oran) |
| `traderlar[]` | `ad` (`takma_ad`), `islem` (adet), `kazanma_orani` (oran), `net_oran` (oran = `sanal_kopya_v3.getiri` = bakiye / başlangıç − 1; tasfiyede `toplam`'dan farklı olabilir, bakiye ile tutarlı olan `getiri` alınır), `son_islem` (UTC ISO, son `kapanis`) |
| `acik[]` | açık kopya pozisyonu (v4, 1.000 $ ölçeği): `coin`, `yon`, `trader` (`takma_ad`), `acilis` (UTC ISO; kopya pozisyonunun açıldığı yürütme anı), `buyukluk_usd` ($, son işaret fiyatıyla), `teminat_usd` ($ = büyüklük / HL azami kaldıracı = başlangıç teminatı; azami kaldıraç bilinmiyorsa `null`), `kaldirac` (x = büyüklük / teminat = HL azami kaldıracı), `giris` ($/coin, ortalama), `son` ($/coin, işaret), `kz_usd` ($, gerçekleşmemiş, funding hariç), `kz_oran` (oran = `kz_usd` / `teminat_usd`); `likidasyona_uzaklik_oran` motorda yok → `null`. En yeni açılış önce |
| `kapanan[]` | son 20 geçerli işlem (kapanış sırasıyla, en yeni önce), v3 ölçeği: `coin`, `acilis`/`kapanis` (UTC ISO), `kz_usd` = `sonuc_usd` ($, maliyet + funding dahil), `kz_oran` = `getiri`, `ana_para_usd` = `sonuc_usd` / `getiri` ($, açılan toplam tutar), `neden`: `trader` → `trader_kapatti`, `zarar_kes` → `stop`, `likidasyon` → `tasfiye`, `kar_al` → `null` (panoda karşılığı yok); `yon` ve `kaldirac` motorda yok → `null` |

**Başlamamış üye:** kopya `t0`'da başlar. `t0` > `uretildi` tarihi olan üyenin pozisyonları kopya işlemi değildir; o üye `kasa`, `acik`, `kapanan`, `ozet`, `metrik`, `seriler` ve `traderlar` toplamlarına GİRMEZ (yalnız `kadro_dolu`'ya sayılır). Takımda toplama giren üye yoksa tüm bu alanlar `null` / boş liste.

Gizlilik: dosyada API anahtarı, token, URL ya da sunucu IP'si yoktur (testle denetlenir); trader adresleri yayımlanmaz, yalnız 4 haneli `takma_ad`.

## 11. `traderlar[].sanal_kopya_v4` (izleme `durum.json`, v1.22) — v3 + H5 risk sınırları
**v3 silinmez / değişmez** (kural 6): v4 `sanal_kopya_v4` olarak v3'ün YANINDA yayımlanır. Birim: 1.000 $ sanal kopya ölçeği (v3 ile aynı). **Tek motor** (kural 7): `copytrade/kopya_v4.py` → `kopya_v3.hesapla(risk_limitleri=…, surum='v4')` → `defter.copy_ledger(risk_limitleri=…)`; `risk_limitleri` verilmezse hesap v3 ile BİREBİR aynıdır (testle gösterilir).
- **Model:** v3 ile aynı (kopya hesabının kendi değerine göre sabit tutarla açılış; ekleme = kopyanın mevcut pozisyonu × trader'ın eklediği / trader'ın önceki pozisyonu; aynı maliyet / funding / tasfiye / aşamalı çıkış).
- **Ek sınırlar** (`kurallar.yaml` `risk_dry_run`, H5 dinleyici defteriyle AYNI sayılar, kodda yeniden yazılmaz; $ referans kasa ölçeğinde): (1) **emir başına** artış ≤ `emir_tavan_usd`; (2) kopyanın **trader başına brüt pozisyonu** (Σ |pozisyon| × işaret) ≤ `trader_tavan_usd`; (3) **kaldıraç:** başlangıç teminatı Σ notional / HL azami kaldıracı ≤ kopya özsermayesi (`azami_kaldirac` = `meta` ve HIP-3 dex `meta`larının `maxLeverage` değerleri; okunamazsa / coin'de yoksa bu sınır uygulanmaz, `limitler.azami_kaldirac_uygulandi: false`). Sınırlar yalnız **artış** kısmına uygulanır (açılış, ekleme, ters dönüşte yeni açılan kısım); azaltma/kapama serbesttir. `toplam_brut_tavan_usd` v4'e girmedi (trader başına kopya defteri tek trader'dır).
- **Kırpma:** artış sınırı aşarsa kırpılır (sıfıra kadar), neden kaydedilir: `risk_kirpma` = son 50 kayıt `[{coin, zaman (UTC ISO yürütme anı), istenen_usd ($), uygulanan_usd ($), neden: emir_tavani | trader_tavani | kaldirac_siniri}]` (neden = en kısıtlayıcı sınır), `risk_kirpma_toplam` (adet), `risk_kirpma_nedenler` ({neden: adet}).
- v3 alanları aynı anlamda: `baslangic_usd`, `bakiye_usd`, `getiri`, `dusus`, `egri`, `gerceklesen`, `acik` (oran), `toplam`, `funding`, `maliyet`, `fiyatsiz_eylem`, `tasfiye*`, `kapanis_nedenleri`, `kapanan_islemler` (§6; `durum.json`'da v3 ile aynı kırpma).
- **Yeni alanlar:** `limitler` (`emir_tavan_usd`, `trader_tavan_usd`, `referans_kasa_usd`, `azami_kaldirac_uygulandi`), `tepe_pozisyon_usd` ($, pencere boyunca en büyük tek coin notional'ı, yürütme fiyatında), `tepe_brut_usd` ($, en büyük brüt notional), `acik_pozisyonlar[]` (pencere sonu açık kopya pozisyonları): `coin`, `yon` (`long`|`short`), `buyukluk_usd` ($, son işaretle; işaret yoksa `null`), `giris` ($/coin), `son` ($/coin), `kz_usd` ($, funding hariç), `acilis` (UTC ISO) / `acilis_ms`, `azami_kaldirac` (x | `null`), `teminat_usd` ($ = büyüklük / azami kaldıraç | `null`), `kz_oran` (oran = `kz_usd` / `teminat_usd` | `null`).
- Hesaplanamazsa `{"surum":"v4","durum":"hesaplanamadi","neden":…}`; v3'ü etkilemez. Hiç okunmamış trader için `yer_tutucu: true`.

## 12. Radar havuzu (R0/R1) — `radar/<YYYY-MM-DD>/havuz.json` (v1.24, T2; `copytrade/radar_tarama.py`, strateji: `docs/RADAR_V1.md` §2–3)
Üretici: `python -m copytrade.radar_tarama` (iş akışı `radar_deneme.yml`; günlük zamanlama T4'te). Salt okunur, herkese açık Hyperliquid verisi. **Birim kuralları:** oranlar kesirdir (0,10 = %10); `*_usd` alanlarında ölçek
adıyla yazılır: `trader_$` = trader'ın kendi hesabı, `kopya_$` = sanal kopya kasası (`canli_kasa_usd`, varsayılan 1.000 $; K‑28); zaman UTC milisaniye; tutma süresi saat; kaldıraç "x" (pozisyon değeri / hesap değeri).
**Pencere** `son7g` = `[kosu_ms − radar_pencere_saat × 3.600.000, kosu_ms)` (koşu BAŞLANGICI; okuma zamanı değil). **Kopya oynatma** pencere başında BOŞ başlar (pencere başında açık pozisyon kopyalanmaz); gecikme `radar_kopya_gecikme_dk` (1 dk),
maliyet taker + kayma (`kurallar.yaml`), **`kopya_v5.hesapla`** (K‑28: §5b oransal boyut `boyut.hedef_emir` + v4 HL azami kaldıraç/teminat sınırı, tarz `intraday`; **K‑35:** v4'ün eski emir başına 100 $ / trader toplamı 200 $ sınırı v5'te KALKTI, yerini trader'ın TÜM coinlerdeki toplamı ≤ 3 × slot tavanı aldı; slot = `canli_kasa_usd` / N; trader hesap payda = `hesap_usd`, koşu anı `accountValue`); R1/6 **iki oynatma** yapar (K‑32): **kopya** (gecikme + maliyet) ve **ayna** (gecikme 0 = trader'ın dolum fiyatı, maliyet 0; aynı slot, ikisi de pencere başında boş); funding oynatmaya **girmez** (v1 kararı). Yürütme fiyatı: son ≈ 3,5 gün için hedef dakikanın 1 dk mumunun açılışı;
daha eskisi için (Hyperliquid `candleSnapshot` yalnız son 5.000 dakikalık mumu verir) hedefi içeren **5 dk mumun açılış ve kapanışından bizim yönümüze kötü olanı** (alışta büyük, satışta küçük; aynı hedefte karışık yön varsa açılış) — temkinli yaklaşık fiyat,
`yaklasik_fiyat_eylem` ile sayılır; eksik mum fiyatı uydurulmaz (eylem atlanır, `fiyatsiz_eylem` ile sayılır). **Ölçüm sırası ucuzdan pahalıya** (lider kararı 2026-11-04): lider tablosundan elemeler (`payda_yok`, `devir_yuksek`) → `vault` → dolum
(en çok `radar_dolum_tavan`; tavana ulaşırsa `dolum_fazla`) → dolum tabanlı kurallar (işlem, tutma, kısa işlem, kaldıraç, likidite) → yalnız hepsi geçtiyse kopya oynatma ve kalan kurallar. **Ölçülmeyen alan `null`**'dır. Radar istemcisi hız sınırı `radar_api_agirlik_dk`
(ağırlık/dk); koşu süresi `radar_zaman_butcesi_dk`'yı aşarsa kalan adaylar `zaman_yok` olur (ölçüsüz).

Üst düzey: `sema` (`"radar-havuz-v1"`), `kural_ust` (YALNIZ deneme koşusunda, varsa: üstüne yazılan `radar_*` anahtarları; günlük koşuda yok), `kosu_ms` (UTC ms, koşu başlangıcı), `pencere_bas_ms` (UTC ms), `evren_toplam` (ön filtreyi geçen kişi sayısı), `evren_kesilen` (aday tavanı nedeniyle dışarıda kalan kişi sayısı),
`satirlar` (aday başına bir satır, `trader_getiri_7g`'ye göre azalan sırada (K‑31)).

| Alan | Birim / ölçek | Anlam |
|---|---|---|
| `adres` | metin | trader adresi (herkese açık) |
| `hesap_usd` | trader_$ | lider tablosundaki `accountValue`, koşu anı |
| `hafta_pnl_usd` | trader_$ | lider tablosu `week` penceresi `pnl` (yatırma/çekme içermez) |
| `trader_getiri_7g` | oran | `hafta_pnl / (hesap − hafta_pnl)`; payda ≤ 0 ise `null` (`neden: payda_yok`) |
| `islem_sayisi` | adet | pencerede KAPANAN round trip (pencere başında açık pozisyonun kapanışı dahil) |
| `medyan_tutma_saat` | saat | kapanan işlemlerin medyan tutma süresi (başlangıcı pencere öncesi olanlar hariç); yoksa `null` |
| `kisa_islem_payi` | oran | tutma süresi `radar_kisa_islem_dk`'dan KISA işlemlerin (süresi bilinenler içinde) payı |
| `max_kaldirac` | x | pencere boyunca en yüksek (toplam pozisyon değeri / `hesap_usd`); payda **koşu anındaki** hesap değeridir (dolum anındaki değil; v1 kararı) |
| `likit_pay` | oran | nosyonelin (px × sz, tüm perp dolumları) 24 sa hacmi ≥ `radar_likit_coin_hacim_usd` ($, `metaAndAssetCtxs.dayNtlVlm`) coinlerdeki payı |
| `kopya_getiri_7g` | oran, kopya_$ ölçeği | sanal kopyanın (v5, kasa = `canli_kasa_usd`) pencere getirisi (gecikme + maliyet dahil); hesaplanamazsa `null` |
| `ayna_getiri_7g` | oran, kopya_$ ölçeği | AYNI slot ve dolumlarla gecikmesiz + maliyetsiz oynatmanın getirisi (K‑32); kopya yoksa `null` |
| `kopya_koruma` | oran | **K‑32:** `kopya_getiri_7g / ayna_getiri_7g`; ayna ≤ 0 ya da yok → `null` (`kopya_koruma_dusuk`) |
| `v4_kopya_getiri_7g` | oran, kopya_$ ölçeği | YALNIZ bilgi (deneme koşuları `--v4-yan-yana`): aynı dolumlar `kopya_v4` (sabit tutar) ile; karar girdisi DEĞİL; yoksa `null` |
| `v5_onceki_kopya_getiri_7g` | oran, kopya_$ ölçeği | YALNIZ bilgi (`--v4-yan-yana`): aynı dolumlar K‑35 ÖNCESİ v5 kuralıyla (v4 emir başına 100 $ / trader toplamı 200 $ sınırı açık, slot tavanı coin başına); `kopya_getiri_7g` ile "önce/sonra"; karar girdisi DEĞİL |
| `devir_hafta` | kat | hafta `vlm` / `hesap_usd` (`vlm` trader_$ nosyonel) |
| `kopya_alt20` | oran, kopya_$ ölçeği | kopya işlem sonuçlarından (`sonuc_usd / 1.000`, geçersiz işlem hariç) `radar_bootstrap_tekrar` yeniden örneklemenin TOPLAMININ `radar_bootstrap_alt_yuzdelik` alt yüzdeliği; tohum adresten türetilir |
| `fiyatsiz_eylem` | adet | yürütme fiyatı bulunamadığı için kopyalanamayan eylem sayısı (`null`: kopya hesaplanmadı) |
| `yaklasik_fiyat_eylem` | adet | yürütme fiyatı 5 dk mumdan (yönümüze kötü olan fiyat) alınan kopya eylemi sayısı (`null`: kopya hesaplanmadı) |
| `kopya_gunluk` | liste (kasa oranı) | **R2 girdisi, yalnız `gecti` satırlarında** (aksi `null`): günlük kopya getirisi = (özsermaye_gün − önceki) / kasa, pencere gün sayısı kadar (UTC günleri, ilk gün önceki = kasa) |
| `kopya_kazanc_gun_orani` | oran | R2 İ1 (yalnız `gecti`): aktif günlerde (getiri ≠ 0) getirisi > 0 olan gün oranı; aktif gün yoksa 0 |
| `kopya_dusus` | oran | R2 İ2 (yalnız `gecti`): kopya özsermaye eğrisinin pencere içi en büyük zirveden düşüşü (kesir) |
| `yayilma` | oran | R2 Y (yalnız `gecti`): 1 − (en iyi tek kopya işleminin kârlı işlemler toplamındaki payı); kâr yoksa 0 |
| `kopya_getiri_72s` | oran, kopya_$ ölçeği | "form sürüyor" (yalnız `gecti`): aynı dolumlarla kopya, penceresi son `radar_soguyor_saat` saat ve o pencerenin başında BOŞ; hesaplanamazsa 0 |
| `hype_payi` | oran | R2 H (yalnız `gecti`): trader'ın kârlı round trip `net_pnl` toplamının erken-trend girişlerden gelen payı (trader_$ ölçeğinden bağımsız oran); kâr yoksa 0 |
| `gecti` | bool | R1'in tüm kuralları geçildi mi (radar havuzu) |
| `neden` | kod \| `null` | ilk başarısız kuralın kodu; sıra: `veri_hatasi` (istek hatası), `payda_yok`, `devir_yuksek`, `vault`, `dolum_fazla`, `islem_az`, `tutma_kisa`, `kisa_islem_fazla`, `kaldirac_yuksek`, `likidite_dusuk`, `kopya_zarar`, `kopya_koruma_dusuk`, `sans_riski`, `akil_sagligi`, `zaman_yok` |
| `hata` | metin \| `null` | `veri_hatasi` ise ilk satır hata iletisi (uydurma yok) |

Eşikler `kurallar.yaml` `radar_*` anahtarlarındadır; sınırlar DAHİLDİR (tam 10 işlem, 1,0 sa, %25, 20x, %80, %50, 100 kat geçer; `kopya_alt20` için tam 0 ELENİR, `kopya_getiri_7g` tam +%300 geçer, tam 0 elenir).
Ölçülmeyen alan `null`'dır: `payda_yok`, `devir_yuksek`, `vault`, `dolum_fazla`, `zaman_yok` satırlarında dolum alanları; dolum tabanlı bir kuralla elenenlerde kopya alanları; her zaman ölçülenler (ör. `devir_hafta`) yazılır. Evrene yalnız `accountValue ≥ radar_min_hesap_usd`, hafta `pnl > 0`, hafta `vlm > 0` girer.

## 13. Radar kadro — `radar/<YYYY-MM-DD>/kadro.json` ve `radar/son/kadro.json` (v1.25, T3; `copytrade/radar_form.py`, `copytrade/radar_kadro.py`, strateji: `docs/RADAR_V1.md` §4–5)
Üretici: `python -m copytrade.radar_kadro` (günlük iş akışı `radar.yml`, 00:37 UTC; yayın veri dalı `radar`, 90 gün tutulur; `son/kadro.json` yalnız tam koşuda güncellenir: `zaman_yok` yok ve satır sayısı = min(`radar_aday_tavan`, `evren_toplam`)).
**Birimler:** oranlar kesirdir; `form` ve `bilesenler` 0–100 yüzdelik puandır; `kasa_usd`/`slot_usd` kopya kasası ölçeğinde $ (kopya_$); zaman UTC ms.
**Form puanı (`radar_form.py`):** `gecti` satırlarından; "form sürüyor" (`kopya_getiri_72s` ≥ `radar_soguyor_min_getiri`, tam sınır geçer; ölçü yok = geçmez) değilse puanlanmaz (`soguyan[]`, neden `soguyor`) ve yüzdelik havuzundan çıkarılır.
Her bileşen kalan havuzda 0–100 yüzdelik sıra (eşitlikte ortalama sıra; 1 kişi 50; İ2 ters): G=`kopya_alt20`, K=`kopya_getiri_7g`, İ1=`kopya_kazanc_gun_orani`, İ2=`kopya_dusus`, Y=`yayilma`, H=`hype_payi`; `form = Σ radar_agirlik_* × yüzdelik`
(0,35 / 0,15 / 0,10 / 0,10 / 0,10 / 0,20). **H:** trend coin = HL perp coinleri içinde |7 g getiri| (saatlik açılış mumları, pencere başı → son) üst `radar_hype_trend_oran` (nicelik ≥) **ya da** listelenme ≤ `radar_hype_yeni_gun` gün (ilk saatlik mum zamanı);
erken giriş = açılışı bilinen kârlı işlem, trend coin, coinin hareketi işlem yönünde ve açılış anında bu hareketin `radar_hype_erken_pay`'ından azı gerçekleşmiş.

Üst düzey: `sema` (`"radar-kadro-v1"`), `kosu_ms`, `kasa_usd`, `slot_usd` (= kasa / `saha_n`), `saha_n` (N = min(`radar_saha_max`, taban(kasa / `radar_canli_slot_min_usd`))), `gecti_sayisi`, `soguyan` ([{adres, neden, kopya_getiri_72s}]),
`satirlar` (form azalan, en çok `radar_kadro_toplam`), `korelasyon` ({`adresler` (İlk 11), `gun_sayisi`, `matris` (Pearson, günlük `kopya_gunluk`; sabit seri `null`)}).
`satirlar[]`: `adres`, `sira` (1…30), `katman` (`ilk11` ≤ `radar_kadro_ilk` < `yedek`), `form`, `bilesenler` {G,K,I1,I2,Y,H}, `kopya_getiri_7g` (oran, kopya_$), `max_kaldirac` (x).
**Saha kararları (slot −%10, bekleme, günde 2 değişiklik, benzer trader ≥ 0,7) kadroda DEĞİL:** T4 motoru okuyup §5/§6 kurallarını uygular.


## 14. Canlı motor — durum ve kayıt (v1.26, T4; `copytrade/canli/`, strateji: `docs/RADAR_V1.md` §5–§6, K‑29/K‑30/K‑33)
Motor kipi `sanal` (varsayılan; cüzdan yok) | `gercek` (yalnız sunucuda; Actions'ta ASLA). **Birimler:** `$` kasa ölçeğinde (`canli_kasa_usd`, kullanıcı ayarı, ≤ 1.000; kopya_$), oranlar kesir, fiyat $/coin, `sz` coin miktarı (işaretli: + long / − short),
zaman UTC ms. Yürütme: IOC, fiyat = en iyi karşı fiyat ± `canli_ioc_bant` (%0,5); sanal kipte `l2Book` yürüyüşü + taker ücreti (`maliyet_taker`), kayma ayrıca eklenmez; coin başına izole 3x marj, tasfiye fiyatı yerelde. **Funding hesaba girmez** (v1, T2 ile aynı).
Veri dalı `canli-durum` (dal doğrulamasında `canli-durum-deneme`): `durum/*.json`, `durum/DUR` (varsa), `kayit/<YYYY-MM-DD>.jsonl` (14 gün).

**`durum/hesap.json`** — `kasa_usd`, `kaldirac`, `poz` {adres → coin → {`sz` (coin, işaretli), `giris` ($/coin ağırlıklı), `acilis_ms`, `kaldirac`}}, `realize` {adres → girişten beri gerçekleşen K/Z, ücret hariç}, `ucret` {adres → ücret},
`slot_bas` {adres → giriş anı slot $}, `kapanmis_net` (sahadan silinen üyelerin net K/Z'si), `tasfiyeler`. Özsermaye = kasa + Σ gerçekleşen − Σ ücret + gerçekleşmemiş (mark) + `kapanmis_net`.
**`durum/saha.json`** — `uyeler` {adres → {`giris_ms`, `giris_sira`, `sira_ust` (art arda sıra > 22 gün), `son_islem_ms`}}, `inen` {adres → {`inis_ms`, `neden`}}, `bekleme` {adres → bitiş ms (sonuçla düşen, 14 gün)},
`degisiklik` {gun, adet}, `son_kosu_ms`, `kurulu`, `alarm_gunu`. **`durum/risk.json`** — `zirve`, `gun`, `gun_basi`, `dur`, `dur_neden`, `fren_bitis`, `yeni_coin`, `acilis_durdu` {neden → aktif}.
**Trader hesap paydası (K‑35):** `hesap_tr[adres].deger` = tüm perp dex'lerin `marginSummary.accountValue` toplamı + spot USDC (radar lider tablosu `accountValue` ile aynı tanım); okuma `canli_hesap_okuma_sn`'de bir, kilit dışında. **Etkin kasa:** sanal kip `canli_kasa_usd`; gerçek kip min(`canli_kasa_usd`, HL hesap değeri) (`--kontrol` `hl_hesap_degeri` / `etkin_kasa_usd`).
**`durum/motor.json`** — `islenen` (son `canli_islenen_sakla` dolum kimliği `{adres}:{tid}`: yeniden başlatmada çift emir yok), `poz_tr` (izlenen trader pozisyonları, coin işaretli), `hesap_tr` {adres → {`deger` trader_$, `ms`}}, `son_olay_ms`, `kip`, `kasa_usd`, `vardiya`.
**`durum/kilit.json`** — `vardiya`, `nabiz_ms`, `birakildi` (başka vardiya `canli_kilit_dk` içinde nabız attıysa motor başlamaz). **`durum/ozet.json`** — vardiya özeti: `kip`, `sure_dk`, `kasa_usd`, `ozsermaye_usd`, `getiri`, `saha`, `saha_n`, `slot_usd`,
`emir` {emir, dolu, kismi, dolmadi, red, atlandi, engel, gec_goruldu}, `neden_say` {boyut/risk nedeni → adet}, `slot_tavani`, `marj_yok` (K‑35 sayaçları), `ortalama_kayma_trader`, `ortalama_kayma_ref`, `kayma_n`, `brut_usd`, `tasfiye`, `dur`, `uyeler`, `dinleyici` (kopma / yeniden bağlanma / mesaj sayaçları).
**`kayit/<tarih>.jsonl`** — satır başına bir olay, ortak alan `zaman_ms`, `olay`:
- `emir`: `kip`, `adres`, `coin`, `eylem` (ac | artir | azalt | kapat), `yon` (B/A), `usd_istenen` ($), `usd_dolan` ($), `sz`, `reduce_only`, `durum` (dolu | kismi | dolmadi | red), `red_neden`, `boyut_neden`, `trader_px`, **`trader_dolum_ms`** (trader dolum zamanı),
  **`gorme_ms`** (bizim gördüğümüz an), `emir_ms`, `dolum_ms`, `referans_px` (en iyi karşı fiyat), `dolum_px` (yürünen ortalama), **`kayma_ref`** (dolum ↔ en iyi karşı fiyat) ve **`kayma_trader`** (dolum ↔ trader'ın dolum fiyatı) — ikisi de oran, **pozitif = aleyhimize**, `ucret` ($), `gec_goruldu` (REST/dolgu ile geç tamamlandı), `kaynak`. `boyut_neden` (K‑35): `tamam` | `tavan_kirpildi` | `slot_tavani` (trader'ın tüm coinlerdeki toplamı 3 × slot'u aştığı için kırpıldı/atlandı) | `marj_yok` (toplam başlangıç marjı + yeni marj > özsermaye) | `coin_tavani_kirpildi` | `min_emir_yuvarlandi` | …
- `emir_yok` (`karar`: atlandi | engel, `neden`), `saha_giris` / `saha_dus` (`sonuc`: sonuçla mı), `kor_kirpildi`, `tasfiye`, `risk`, `dur`, `mutabakat_alarm` / `mutabakat_duzeldi`, `poz_senkron`, `kacan_tamamlandi`, `eski_dolum_atlandi`, `kadro_yok` / `kadro_bayat`, `telegram` (metin ≤ 300; token ASLA), `kapanis` (vardiya özeti).
Adresler trader'ların halka açık adresleridir; API anahtarı, hesap adresimiz ve Telegram token'ı hiçbir dosyaya yazılmaz.
