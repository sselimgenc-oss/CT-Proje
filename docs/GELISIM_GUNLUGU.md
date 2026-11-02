
Kronolojik, en yeni üstte. İkinci doğru kaynak değil: kararların ayrıntısı `DURUM.md`, `docs/KARARLAR_D.md` ve
görev belgelerinde durur; burada yalnız hangi değişikliğin hangi ölçümü/veriyi etkilediği kısaca kayıtlıdır.

## 2026-10-31 01:30 TR — degisim_rapor v3'e çevrildi (kullanıcı: "v3 olmalı, yeni çalışmamız o")
`copytrade/degisim_rapor.py` (oda rotasyon "değişim alfası") `sanal_kopya.toplam` (v1) yerine `sanal_kopya_v3.toplam`
okuyor. Rapora `kaynak` + `taban_sifirlandi` eklendi; `kaynak`sız (v1 dönemi) önceki rapordaki
`cikarilan_taban_net` değerleri v3 ile karıştırılmaz, taban yeniden alınır. v3 `hesaplanamadi` ise v1'e düşülmez,
değişim "bekleniyor" kalır. Gerçekte henüz hiç rotasyon kaydı yok (`copytrade/degisim.jsonl` yok; ilk Perşembe
koşusu bekleniyor), yani sıfırlanacak canlı taban da yok — koruma ileriye dönük. Gerçek veri denemesi (O01 çıkarılan,
B17 alınan, bugünkü HL durumu): çıkarılan −%0,36, alınan −%32,73, alfa −%32,73 (taban ilk raporda = çıkarılanın
değeri). 2 yeni altın örnek + mevcut test v3'e uyarlandı. Ön kayıt eşikleri/gerekçeler değişmedi.

`sanalKohort()`, `izleme_motoru.py::kasa_egrisi()`). v1/v2 silinmedi (kural 6), yalnız gösterilen sürüm değişti.
- Gerçek bir hata bulundu ve düzeltildi: Telegram'daki `.filter(Boolean)` ve ofisteki `kol()` fonksiyonu
  `{"durum":"hesaplanamadi"}` yer tutucusunu ELEMİYORDU (truthy nesne) — ortalama getiriye payda olarak giriyor,
  pay olarak girmiyordu (sessizce düşük gösterim). Artık yalnız gerçek `getiri` sayısı olan girdiler sayılır.
- Örnek veri (`izleme/ornek_durum.json`, iki repo) her trader'a `sanal_kopya_v3` kazandı (v1 ile aynı sayılar).
- **Kural 6 kıyası (gerçek veri, O01/O02/B17):** O01 v1 +%5,87 ↔ v3 −%0,36; O02 ikisi de hesaplanamadı; B17 v1
  +%0,16 ↔ v3 **−%32,73** (büyük/kaldıraçlı trader'da sabit-$ eğrisi çok daha büyük pay oynatıyor — tasarımın
  kendisi, `sanal_kopya_v3` belgesinde zaten yazılı). Panodaki/Telegram'daki sayılar bu PR'dan sonra belirgin
  değişecek; hata değil.
- `copytrade/degisim_rapor.py` bu PR'da bilerek v1'de bırakıldı; ardından kullanıcı kararıyla v3'e çevrildi (üstteki girdi).

## 2026-10-30 23:15 TR — E2 devamı 2: v3'e tasfiye + aşamalı çıkış (kullanıcı: "dokümanda ne yazıyorsa onu yap")
  çalışmasını istiyor (önceki E2 devamı bunu kasıtlı ayırmıştı, kapsam notunda açıkça yazılıydı).
- `golge.py`'nin risk katmanı (`_denetle_ve_kapat`/`kirp_pozisyon`/`v2_cikislari`) sentetik dolum enjekte edip
  trader-hesabına-oranlı `scale`'den geçiriyor; sabit tutarda sizin böyle bir `scale` yok (yol bağımlı). Çözüm:
  `defter.copy_ledger` içine AYRI bir risk katmanı (`_risk_denetle`/`_zorla_kapat`) — gerçek `held`/`entry` üzerinde,
  sentetik dolum olmadan, AYNI dondurulmuş eşiklerle (`golge_likidasyon_esigi`, `golge_v2`). `v2_sinir` `golge.py`
  → `defter.py`'ye taşındı (kural 7: tek yer; `golge.py` re-export eder, mevcut testler değişmedi).
- Gerçek bug: `held[coin]` tam kapanışta hiç silinmiyordu (`entry` siliniyordu ama `held` sıfır değerle kalıyordu);
  risk katmanının "pozisyon açık mı" kontrolü bu yüzden KeyError/sahte-açık veriyordu. İkisi de artık siliniyor.
- `tests/test_kurallar_uygunluk.py` (kural 23, sayı sabiti yasağı): `v2_sinir`'in 7/14 gün eşikleri artık
  `kurallar.yaml`'ın `golge_v2.swing` anahtarlarından (`gun_7`/`gun_14`) parse ediliyor — sabit değil (bu, `v2_sinir`
  taşınınca denetlenen dosya listesine girdiği için açığa çıkan, ÖNCEDEN DE var olan bir eksiklikti).
- 8 yeni altın örnek: `test_defter_sabit_tutar.py` (tasfiye, aşamalı zarar_kes, zorunlu-çıkıştan-sonra-bastırma —
- Gözlem (davranış doğru, hata değil): sabit tutar küçük olduğundan ($1.000'da ~%2, $10.000 tavanında ~%15), tek
  pozisyon gerçek fiyat hareketiyle −1,0/−0,50 eşiklerine pratikte ulaşamıyor — testlerde eşik yalnız mekanizmayı
  göstermek için (test_a19.py'deki yerel `rules` kopyalama deseniyle) gevşetildi, `kurallar.yaml` değişmedi.
- Gerçek veri denemesi bir performans hatası buldu: `_risk_denetle` işaret (`market.mark`) yoksa `son_kontrol[c]`'yi
  ilerletmiyordu → her sonraki dolumda aynı, büyüyen boşluk baştan taranıyordu (O(dolum × boş-saat)); B17'de
  (çok sayıda kısa ömürlü coin) 30 dk'da çıktısız durdu, sentetik testler yakalamamıştı. Düzeltme: işaret yoksa da
  `son_kontrol[c]=saat` her zaman ilerler (yalnız zorla kapatılan coin tamamen takipten çıkar); kalıcı regresyon
  testi eklendi (2s sınır). Düzeltme sonrası küçük denemede (O01/O02/B17, prod listesinin TAMAMI değil) 3 trader
  ~6dk48s'de bitti (CPU 29s — ağ gecikmesi, donma yok): O01/B17 `sanal_kopya_v3` sağlıklı (`tasfiye:false`,
  `kapanis_nedenleri:[]`, gözlemle uyumlu), O02 beklenen `hesaplanamadi`.
- `python -m pytest -q`: 550 geçti.

  Kasa.islem_usd`'nin birebir portu (varsayılanlar `ayar.py`'den, DEĞİŞTİRİLMEDİ): tutar_usd = 5,2 ×
  (clamp(hesap,1,10.000)/200)^0,86. `copytrade/kopya_v3.py` (`sanal_kopya_v3`, v1/v2 yanında): açılış kopyanın
- `defter.copy_ledger`'a yeni `tutar_egrisi`/`base_usd` parametresi (varsayılan `None` → v1/v2 davranışı AYNEN
  korunur, regresyon yok); verildiğinde `account`/trader hesabı hiç okunmaz. Yardımcı `_fresh_open`/
  `_sabit_tutar_signed`: açılış/flip'in yeni tarafı eğriyle (kopyanın o anki gerçekleşen+gerçekleşmemiş K/Z'sinden
  tahmini $ değeri), ekleme/azaltma/kapatma mevcut mantıkla.
- **Kapsam dışı (ayrı tasarım kararı gerektirir):** tasfiye, pozisyon tavanı, aşamalı zarar_kes/kar_al —
  `golge.py`'nin bu katmanı (`_denetle_ve_kapat`/`kirp_pozisyon`/`v2_cikislari`) trader hesabına ORANLI
  ölçeklemeye kodlanmış; v3 bu yüzden `golge.calistir`'i değil `defter.copy_ledger`'ı DOĞRUDAN çağırıyor.
  Kaldıraç kademesi/marj modeli/"ikna" çarpanı da kapsam dışı.
- Test: `tests/test_defter_sabit_tutar.py` (5, `copy_ledger` seviyesinde — eğri/trader-büyüklüğünden bağımsızlık/
  ekleme/flip) + `tests/test_kopya_v3.py` (5, `kopya_v3.hesapla` seviyesinde). `python -m pytest -q`: 544 geçti.
- Küçük gerçek veri denemesi (canlı HL, O01/O02/B17): O01 v3 −%0,34 (v1 +%7,68, v2 +%0,91 — makul). B17 (taban,
  hesap 70,2M $) v3 **+%18,8** (v1/v2 ~+%0,8) — beklenen: v1/v2 devasa hesaba oranlı kırıntı kopyalıyor, v3 sabit
  $ açıyor (tasarımın amacı). Yan bulgu: B17'de `fiyatsiz_eylem` v2=0 ↔ v3=322 — v2'nin `golge.v2_cikislari`'ı
  yürütülemeyen dolumu sessizce atıp hiç saymıyor (maskeli alt sınır); v3 `copy_ledger`'ı doğrudan çağırdığından
  gerçek sayıyı yayımlıyor (v3 hatası değil, v2 raporlama eksiği — `VERI_SOZLESMESI.md`'ye not düşüldü).

## 2026-10-30 21:30 TR — E6: kullanılmayan iş akışı arşivi
- Kullanıcı onayı ("onaylıyorum devam et"): iki tek seferlik, tamamlanmış iş akışı Actions geçmişi doğrulanarak
  kaldırıldı (git geçmişinde duruyor, kural: hiçbir şey kalıcı silinmez).
  - `hf_dogrulama.yml` — son koşusu (28.10, run #3) başarılı; `docs/GOREV_HF_DOGRULAMA.md` görevi bitti.
  - `pilot_bosluk.yml` — dosyasının kendi başlığı "TEK SEFER, elle"; son koşusu (29.10 16:03, run #6) başarılı,
    boşluk dolduruldu, tekrar koşulacak bir durum yok.
- Dokunulmadı: `golge_saglama.yml` (yeniden kullanılabilir manuel sağlık kontrolü), `izleme_deneme.yml` (kural 1'in
  zorunlu kıldığı "küçük gerçek veri denemesi" aracı — görev sürüyor, silinmez). İş akışı sayısı 12 → 10.
- Kod/davranış değişikliği yok, test etkisi yok.

## 2026-10-30 21:00 TR — E4/E6 incelemesi: yeni kod yok (kural 7 — mevcut fonksiyonu kopyalama)
- **Yönetim kararı:** Sol (Codex) denetimi manuel oldu (kullanıcı); birleştirme koşulu artık yalnız CI yeşil.
  odadan düşme kuralı K-11'den önce kurulmuş: `copytrade/gecis.py` (alt dilim + ardışık hafta çıkış, 28 günde
  ≤2 çıkış tavanı) + `copytrade_haftalik.yml` (her Perşembe, ön kayıt 1.6 onaylı). Yeni kod yazmadım. Gerçek veri
  kontrolü: `rotasyon/kayit.jsonl` henüz yok (pilot 29.10 başladı, ilk Perşembe koşusu gelmedi — zamanlama).
  İş akışı sayısı 12 (#443 zaten indirmiş). Ayarlar tek dosyada. Kullanılmayan iş akışı arşivi kullanıcı onayı
  gerektiriyor, ayrı soru.

## 2026-10-30 20:45 TR — E3: aşamalı zarar_kes/kar_al canlıya bağlandı
- Kullanıcı kararı: "Opus sana ne değişiklik verdiyse sırayla yap, sormana gerek yok" — E2'nin kalan parçası
  (sabit $ işlem tutarı) eşik/strateji kararı gerektirdiği için (AGENTS.md: eşik kararı kullanıcının) atlanıp
  E3'e geçildi: `golge.py`'de zaten yazılı, ön kayıtlı aşamalı çıkış kuralı (`v2_sinir`) canlıya hiç bağlı değildi.
  kurallar.py'sindeki zamana bağlı stop/kâr mantığına denk hâle getiriyor (eşikler DEĞİŞMEDİ, zaten dondurulmuştu).
- Test: `tests/test_kopya_v2.py`'deki "tasfiye olmayan derin zarar" testi V2 altında artık erken zarar_kes'e
  giriyor (eşik -%50) — elle yeniden hesaplanıp güncellendi (bakiye 196,96 $, kapanış nedeni kaydı doğrulandı);
  eşiğe değmeyen bir senaryo için yeni ayrı test eklendi. 9 altın örnek, `pytest -q` 536 geçti.
- Küçük gerçek veri denemesi (canlı HL, O01, 7,5 sn): `kapanis_nedenleri: []` — mevcut pozisyon eşiğe değmiyor,
  yanlışlıkla tetiklenmedi (gerçek veriyle doğrulandı).
  10.000$→150$, sonrası sabit) belgelerden yaklaşık çıkarılabilir ama kesin sayılar strateji/eşik kararı.

## 2026-10-30 20:15 TR — E2: kopya hesabı v2 (tek motor, tasfiye, pozisyon tavanı, doğru payda/funding)
- `copytrade/kopya_v2.py` (yeni): canlı `sanal_kopya` (v1, `izleme_motoru.copy_results`) `defter.copy_ledger`'ı
  çıplak çağırıyordu — araştırma gölgesinde (`golge.py`) zaten var olan tasfiye/pozisyon tavanı mantığı canlıya
  hiç bağlı değildi (DENETIM_TRADER_2026-10-30.md K3/K5/K6). v2 aynı motoru (`golge.calistir`, V0) kullanır: eski
  taslak PR #434'ten (birleştirilmeyecek) `sanal_kopya_v2` bölümü güncel main'e yeniden uyarlanıp getirildi.
- İki küçük destek düzeltmesi (tek motor çalışabilsin diye): `defter.Market.funding_cum` artık yalnız tam saatlik
  mumları funding ızgarasına alıyor (1 dk işaret mumu karışınca fazladan/eksik funding sayma riski); `golge.v2_cikislari`
  dolum üzerindeki hazır `_execution_*` alanını (v1'in zaten çektiği gecikmeli dakika mumu) kullanıyor.
- `izleme_motoru.update_trader()`: `sanal_kopya_v2` v1 yanında yazılıyor; hata olursa yalnız v2 `{"durum":"hesaplanamadi"}`
  döner, v1 düşmez (try/except, kural 6).
- **Küçük gerçek veri denemesi** (canlı Hyperliquid, tek gerçek oda trader'ı O01, 8 sn): v1 getiri **+%7,18**, v2
  getiri **+%0,95**. **Açıklanan fark:** O01'in gerçek açık pozisyonu (NEAR, 10x, hesabın %163'ü notional — HL'den
  doğrulandı) v1'de kapsız kopyalanıyor, v2'nin pozisyon tavanı (`golge_pozisyon_tavan_carpani`=3,0) bunu kırpıyor;
  tasfiye tetiklenmedi (`tasfiye=false`). Bu v2'nin **doğru çalıştığının** kanıtı, hata değil.
- Test: `tests/test_kopya_v2.py` 8 altın örnek (tek motor=v1 eşitliği, tasfiye, tasfiye olmayan derin zarar, zamanla
  değişen payda, yalnız kopyalanan pozisyonun funding'i, dakika mumu funding ızgarasına girmez, eksik hesap serisi,
  boş hesap). `tests/test_izleme.py` 2 küçük güncelleme (v2'nin koşuyla ilerleyen alanları karşılaştırma dışı;
  v2'nin kendi saatlik mum önbelleği ayrı sayaçla +1/koşu — regresyon değil, yeni, beklenen davranış).
- `python -m pytest -q`: 535 geçti. `docs/VERI_SOZLESMESI.md` v1.9: `sanal_kopya_v2` şeması belgelendi.
  zarar_kes/kar_al çıkışları — `golge.calistir` bunları bilerek `variant='V0'` ile uygulamıyor.

## 2026-10-30 19:45 TR — Sol'un 2. denetimi (%33): #445'teki gerçek bulgu düzeltildi, canlı kanıt eklendi
  başlamadı, sıradaki iş zaten bu. Rapordaki iki gerçek hata:
  1. **Önceki düzeltme:** "dakikalık Worker yoklaması yok" bulgusu rapor yazarının kendi hatasıydı — Worker
     zaten her dakika çalışıyor (`wrangler.toml` `crons`); "hız" alanı KISMİ'ye düzeltildi.
  2. **YÜKSEK, gerçek:** `son_gecikme` D1'de trader başına tek satır kalıcı olduğundan, uzun süre işlem yapmayan
     bir trader'ın eski örneği oda medyanına filtresiz giriyordu. `copytrade/gecikme.py::ozet()` artık `zaman`'ı
     120 dk'dan eski örnekleri medyandan/maks'tan dışlıyor (`n` taze, `n_toplam` hepsi) — `claude/e1-gecikme-pencere`.
- **Canlı kanıt (denetimin istediği, önceden eksikti):** Worker'ın gerçek adresi bulundu (deploy log'undan):
  `https://sg-arge-telegram.sselimgenc-c18.workers.dev`. `/gecikme` canlıda çalışıyor, gerçek veri dönüyor
  (2026-10-30 ~16:40 TR): 2 örnek, medyan ≈ 0,31 dk, maks ≈ 0,52 dk — **E1'in hedeflediği ≤5 dk'nın çok altında**.
  `/kararlar` da canlı. D1 şeması manuel adım değil, `worker.yml` her dağıtımda otomatik uyguluyor (önceki
  günlük/DURUM notu yanlıştı, düzeltildi). Tek gerçek eksik: `GECIKME_URL` GitHub Actions değişkeni henüz
  tanımlı değil (kullanıcı eklemeli); tanımlanınca saatlik iş bu canlı veriyi `izleme/gecikme.json`'a yazacak.
- Test: `tests/test_gecikme.py` 8 altın örnek (pencere filtresi dahil, eski örnek senaryosu elle hesaplandı).

## 2026-10-30 19:00 TR — E1 devamı: gerçek algılama gecikmesi
  parçası: Worker zaten her dakika oda trader'larının dolumlarını çekiyordu (`fills()`), yalnız bunu kullanıp
  **gerçek** algılama gecikmesini (Hyperliquid dolum zamanı → Worker'ın onu görmesi) ölçmeye başladık.
- Worker: yeni dolum görülünce (`newest` imleç ilerleyince) D1 `son_gecikme` tablosuna trader başına **en son**
  örnek yazılıyor (kota için geçmiş birikmiyor); `GET /gecikme` bu tabloyu listeler.
- `copytrade/gecikme.py` (yeni): saf `ozet()` fonksiyonu medyan/maks üretir; `izleme.yml`'e yeni adım
  (`GECIKME_URL` tanımlıysa, düşerse `continue-on-error`) → `izleme/gecikme.json`.
- **Bu, `copytrade/saglik_hatti.py`'deki `acik_pozisyon_yasi_dk_medyan`'dan (pozisyon yaşı) tamamen ayrı** — Sol'un
  önceki denetiminin ayırdığı iki kavram artık ikisi de gerçek veriyle ölçülüyor, karıştırılmıyor.
- `docs/VERI_SOZLESMESI.md` v1.6: `izleme/gecikme.json` şeması belgelendi.
- Test: `worker/test/gecikme.test.js` 4 altın örnek (saf fonksiyon + D1 yazma + yeni dolum yoksa yazmama + uç nokta);
  `tests/test_gecikme.py` 4 altın örnek (medyan, boş liste, eksik değer, çift eleman medyanı); `node --test` 37/37,
  `pytest -q` regresyonsuz.
- **Kullanıcı/dağıtım adımı (kod dışı):** Cloudflare D1'e `worker/schema.sql`'deki `son_gecikme` tablosu bir kez
  uygulanmalı; `GECIKME_URL` GitHub Actions değişkeni (Worker'ın `.../gecikme` adresi) tanımlanmalı — yoksa adım
  sessizce atlanır, saatlik akış bozulmaz.

## 2026-10-30 18:50 TR — Sol denetimi: #441'de iki YÜKSEK bulgu, düzeltildi
  pozisyon yaşı ölçülüyor, algılama gecikmesi değil); sağlık ışığının tazelik kontrolü yayım anındaki `now` ile
  hesaplandığından her zaman ~0 dönüyor, durmuş akışı yakalayamıyor.
- Düzeltme: alan `acik_pozisyon_yasi_dk_medyan` olarak yeniden adlandırıldı, docstring/sözleşme bunun pozisyon
  yaşı olduğunu açıkça söylüyor. `veri_tazeligi_dk` ve eşikleri `saglik_hatti`'den tamamen çıkarıldı — tazelik tek
  yerde kalıyor: Worker'ın `checkStateAlerts`'teki mevcut gerçek-zamanlı 3 saatlik kontrolü (AGENTS.md kural 7).
  `olc()` artık `simdi` parametresi almıyor (gereksizleşti). Kaynak/atıf notu modül docstring'ine eklendi.
- Test: `tests/test_saglik_hatti.py` güncellendi (yeniden adlandırma + 2 yeni uç durum: bozuk `uretildi`, acilis
  `uretildi`'den sonra görünen saat kayması). `python -m pytest -q` ve worker testleri yeniden koşuldu.

- `copytrade/saglik_hatti.py` eklendi: oda kolu için tek sağlık kaydı (yetim gölge payı, işaret eksikliği, veri
  hata oranı, açık pozisyon yaşı) → ışık + neden listesi. Saf fonksiyonlar (`olc`/`kontrol`). **Performans
  ışığından (`traderlar[].saglik.isik`) ayrı** — bu, veri hattının kendi sağlığı.
- `izleme_motoru.run()` her koşuda `durum.json["saglik_hatti"]` yazıyor (izleme listesi boşken eklenmiyor).
- Worker `checkStateAlerts` kırmızıya geçişte Telegram uyarısı gönderiyor (yeşil/sarıdan kırmızıya; aynı kırmızıda tekrarlamaz).
- `docs/VERI_SOZLESMESI.md` v1.6: yeni alan belgelendi.
- Küçük gerçek veri denemesi: canlı `durum.json` (91 trader, `uretildi` 2026-10-30T14:20Z) üzerinde dört kol için
  çalıştırıldı. Oda: n=18, yetim_golge_orani %0,37, pozisyon yaşı medyan ≈ 41 dk, **ışık yeşil**. Kontrol:
  veri_hata_orani %11 → sarı. Havuz (t0 30.10, 1 gün yeni): veri_hata_orani %20 → **kırmızı** (gerçek bulgu: yeni
  eklenen havuz trader'larında veri hata oranı oda'dan yüksek; izlenecek).
- Test: `tests/test_saglik_hatti.py` 6 altın örnek (elle hesap) + `tests/test_izleme.py` (70, regresyon yok) +
  `worker/test/bildirim.test.js` 2 yeni (toplam 9) — hepsi yeşil.

  Kod/davranış değişikliği yok. E1'in kod devşirme ön koşulu.

  mühendislik) devşirilir; güvenlik (gerçek para/emir/cüzdan yok), ölçüm yöntemi ve seçim mantığı korunur.
