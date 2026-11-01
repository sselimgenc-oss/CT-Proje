# DURUM (lider günceller; tek doğru kaynak budur)

Son güncelleme: 2026-10-30 gece, Sonnet (E2 sabit tutar/v3). Lider: Sonnet (K‑11, birleştirme yetkili).

**Kullanıcı kararı (2026-10-30 gece):** Sol (Codex) denetimi artık **manuel** — zorunlu birleştirme koşulu değil,
yalnız kullanıcı isterse ayrıca devreye girer. Birleştirme koşulu: **CI yeşil** (lider kendi birleştirir, denetim
beklemez).

## Hedef (K‑11)
Hyperliquid kaldıraç trader'larını sanal kasada, küçük sabit tutarla, Etre'nin çıkış kurallarıyla kopyalayan; tek panelde ve
Telegram'da canlı izlenen; her kuralı ileri testle ölçen sistem. Gerçek para/emir yok. Görev: `docs/GOREV_ETRE_GECIS.md` (E1–E6).

## Durum
- `izleme.yml`, `izleme_deneme.yml`, `arsiv.yml`, `arsiv_alarm.yml`, `golge_saglama.yml`, `copytrade_kapi.yml`, `copytrade_secim.yml` ve `copytrade_haftalik.yml` iş akışları emekliye ayrıldı ve GitHub'dan kaldırıldı. Worker artık workflow tetiklemez. Tarihsel izleme çıktısı `copytrade-izleme` veri dalında (`izleme/durum.json`), motor durumu ise R2'de tutulur.
- Worker: günlük özet 09:00 TR + alarm (işlem bildirimleri kapalı). Pano/ofis: `sg-pano/` (artık bu repo içinde,
  ayrı bir repo değil — `sg-pano` reposu geçmişiyle birlikte `git subtree` ile buraya taşındı).

## Belgeler
`AGENTS.md` (kurallar) · `docs/KARARLAR_D.md` (kullanıcı kararları) · `docs/ONKAYIT_D.md` (ön kayıt) · `docs/VERI_SOZLESMESI.md` ·
`docs/GOREV_ETRE_GECIS.md` (tek görev listesi) · seçim yöntemi: `docs/GOREV_TRADER_SECIMI.md`, `docs/KAPI_V3.md`, `docs/GOREV_SECIM_V1.md`, `docs/GOREV_SECIM_V13.md` ·
`docs/WORKER_TETIKLEME.md` · `docs/etre_envanter.md` · `docs/DENETIM_TRADER_2026-10-30.md` · `docs/LIDER_DEVIR.md` · `docs/PROTOKOL.md`.

## Temizlik (kullanıcı kararı 2026-10-30: "yeni stratejide işe yaramayan her şey silinsin")
Silindi (git geçmişinde duruyor): Faz 3, kalıcılık, inceleme, maliyet/makas, mutabakat, rejim, kapı satır teşhisi modülleri ve iş akışları;
eski aday taraması; biten/askıdaki görev ve durum belgeleri (`GOREV_*`, `codex_*`, eski denetimler, fikirler); `arastirma/` (yalnız kapının okuduğu
`arastirma/copytrade/bagimsiz_secim` kaldı); eski kapı anlık görüntüsü. Eski dallar ve çalıştırmalar da temizlendi.

## E1 (2026-10-30 akşam, lider Sonnet)
Lisans (`#439`, sg-pano `#46`), Sol'un denetim raporu (`#442`) ve veri hattı sağlığı (`#441`) birleşti. `#441`
Sol'un iki YÜKSEK bulgusuna göre düzeltilmişti (alan adı pozisyon yaşı oldu, yanlış tazelik kontrolü çıkarıldı).
Pano temizliği Opus'ta; bu dal (sg-arge) E1-E6'ya devam ediyor.

## E1 devamı (2026-10-30 akşam): gerçek algılama gecikmesi
`#445`: Worker'ın zaten çektiği dolumlardan **gerçek** algılama gecikmesi (Hyperliquid dolum zamanı → Worker'ın
görmesi) ölçülüyor (`son_gecikme` D1 tablosu, `GET /gecikme`, `copytrade/gecikme.py` → `izleme/gecikme.json`).
`#441`'deki pozisyon yaşından (tahmini) tamamen ayrı, gerçek ölçüm.
- **D1 şeması**: `worker.yml` her dağıtımda otomatik uyguluyor — önceki not ("bir kez elle uygulanmalı") yanlıştı,
  düzeltildi. Canlı kontrol: `https://sg-arge-telegram.sselimgenc-c18.workers.dev/gecikme` çalışıyor, gerçek veri
  dönüyor (2026-10-30 ~16:40 TR: medyan ≈ 0,31 dk, maks ≈ 0,52 dk — 2 örnek).
- **Kullanıcıdan gereken tek adım:** GitHub reponun Settings → Secrets and variables → Actions → Variables'a
  `GECIKME_URL` = `https://sg-arge-telegram.sselimgenc-c18.workers.dev/gecikme` eklemek (büyük olasılıkla
  `KARAR_URL`'in yanına, aynı yöntemle). Eklenmezse saatlik iş adımı sessizce atlanır, hiçbir şey bozulmaz.
- Sol'un 2. denetimindeki (`docs/DENETIM_ETRE_GECIS_TEKRAR_2026-10-30.md`) YÜKSEK bulgusu — eski/eylemsiz
  trader'ın tek D1 örneğinin oda medyanını bozması — `copytrade/gecikme.py`'de pencere filtresiyle (120 dk)
  düzeltildi (`#447`, birleşti).

## E2 (2026-10-30 gece): kopya hesabı v2 — tek motor, tasfiye, pozisyon tavanı
Canlı `sanal_kopya` (v1) `defter.copy_ledger`'ı çıplak çağırıyordu; araştırma gölgesindeki (`golge.py`) tasfiye ve
pozisyon tavanı mantığı canlıya bağlı değildi (K3/K5/K6, `DENETIM_TRADER_2026-10-30.md`). `copytrade/kopya_v2.py`
(eski taslak #434'ten güncel main'e uyarlanarak) bunu düzeltiyor; `sanal_kopya_v2` v1 yanında yayımlanıyor, v1
değişmedi. **Gerçek veri (canlı HL, O01):** v1 getiri +%7,18 ↔ v2 +%0,95 — fark açıklanabilir: O01'in gerçek açık
pozisyonu hesabın %163'ü notional (HL'den doğrulandı), v1 kapsız kopyalıyor, v2'nin pozisyon tavanı (3,0x) kırpıyor.
8 altın örnek testi; `python -m pytest -q` 535 geçti. Kapsam dışı (E3): sabit $ tutar, aşamalı zarar_kes/kar_al.

## E2 devamı (2026-10-30 gece): sabit $ işlem tutarı (v3)
Kullanıcı kararı: "Etre eğrisini enterpolasyonla port et" (Etre'nin kendi `kasa.py`/`ayar.py` sayıları, DEĞİŞTİRİLMEDİ:
200$→5,2$, 1.000$→~20,75$, 10.000$→~150,35$, sonrası sabit). `copytrade/kopya_v3.py` (`sanal_kopya_v3`, v1/v2
yanında, kural 6): açılış kopyanın KENDİ 1.000 $ değerine göre bu eğriden sabit tutarla (trader'ın işlem büyüklüğü
etkilemez); ekleme mevcut pozisyona oranla (Etre `masa.py _ekle`). Aynı motor (`defter.copy_ledger`, kural 7),
yalnız yeni `tutar_egrisi` parametresiyle. 14 altın örnek testi (`test_defter_sabit_tutar.py`, `test_kopya_v3.py`).
**Kapsam dışı (bu sürümde HENÜZ yok):** tasfiye/pozisyon tavanı/aşamalı çıkış — `golge.py`'nin bu katmanı trader
hesabına ORANLI ölçeklemeye kodlanmış; sabit tutar tabanına taşınması ayrı tasarım kararı (sentetik zorunlu-çıkış
dolumlarının ölçeği belirsiz). Kaldıraç kademesi/marj modeli/"ikna" çarpanı da kapsam dışı (ayrı GOREV alt maddesi).
**Küçük gerçek veri denemesi** (O01, O02, B17; canlı HL): O01 v1 +%7,68, v2 +%0,91, v3 −%0,34 (makul, küçük fark).
B17 (taban, hesap 70,2 milyon $) v1 +%0,81, v2 +%0,76, v3 **+%18,8** — beklenen ayrışma: v1/v2 B17'nin devasa
hesabına ORANLI kopyaladığından pozisyon kırıntı kalıyor, v3 sabit $ açtığından aynı fiyat hareketi kopya
sermayesinin çok daha büyük bir payını oynatıyor (tasarımın amacı tam bu). **Yan bulgu:** B17'de v2 `fiyatsiz_eylem`
0, v3 322 — v3 hatası değil: `golge.v2_cikislari` yürütülemeyen dolumu deftere vermeden sessizce atıyor, v2'nin
sayısına hiç girmiyor (maskeli alt sınır); v3 `copy_ledger`'ı doğrudan çağırdığından gerçek sayıyı yayımlıyor
(`VERI_SOZLESMESI.md`'ye not düşüldü). O02 hesap=0 hata zaten v1/v2'yi de etkiliyor (benim değişikliğimden önce).
`python -m pytest -q`: 544 geçti.

## E2 devamı 2 (2026-10-30 gece): v3'e tasfiye + aşamalı çıkış de bağlandı
Kullanıcı kararı: "dokümanda ne yazıyorsa onu yap" — GOREV_ETRE_GECIS.md'nin "bitti tanımı" kopya motorunun
**sabit tutar + çıkış kuralları + tasfiye** üçünün BİRLİKTE çalışmasını istiyor; az önceki E2 devamı bunu kasıtlı
ayırmıştı. `golge.py`'nin tasfiye/aşamalı-çıkış katmanı (`_denetle_ve_kapat`) sentetik dolum enjekte edip trader
hesabına ORANLI `scale`'den geçirerek çalışıyor — sabit tutarda böyle bir `scale` yok (boyutlandırma yol bağımlı),
o yüzden bu numara kullanılamadı. Çözüm: `defter.copy_ledger` içine, gerçek (yol bağımlı) `held`/`entry` durumu
üzerinde çalışan AYRI bir risk katmanı (`_risk_denetle`/`_zorla_kapat`) — AYNI dondurulmuş eşikler
(`golge_likidasyon_esigi`, `golge_v2`, DEĞİŞTİRİLMEDİ). `v2_sinir` tek yere (kural 7) taşındı: `golge.py` →
`defter.py` (golge re-export eder, `test_golge.py`'nin importu değişmedi).
- Gerçek bir hata bulundu ve düzeltildi: `held[coin]` tam kapanışta hiç silinmiyordu (yalnız `entry` siliniyordu) —
  risk katmanının "açık mı" kontrolü buna dayandığından sahte-açık kayıt kalıyordu; artık ikisi de silinir (v1/v2
  davranışını etkilemez, zaten her yerde `.get(coin,0.0)` kullanılıyor).
- `tests/test_kurallar_uygunluk.py` (sayı sabiti yasağı, kural 23): `v2_sinir`'in 7/14 gün eşikleri artık
  `kurallar.yaml`'daki `golge_v2.swing` anahtarlarından (`gun_7`/`gun_14`) okunuyor, kodda sabit değil.
- 8 yeni altın örnek (`test_defter_sabit_tutar.py`: tasfiye, aşamalı zarar_kes, zorunlu-çıkıştan-sonra-bastırma;
  `test_kopya_v3.py`: ikisi uçtan uca). **Gözlem (hata değil):** sabit tutar küçük olduğundan (~%2-15 hesap payı),
  tek pozisyon gerçek fiyat hareketiyle bu eşiklere pratikte ulaşamıyor — testlerde eşik yalnız mekanizmayı
  göstermek için gevşetildi (test_a19.py'deki yerel `rules` kopyalama deseniyle, `kurallar.yaml` değişmedi).
- **Gerçek veri denemesi bir performans hatası buldu (kalite kuralı 1'in tam kanıtladığı an):** `_risk_denetle`,
  bir coin'in o saat için piyasa işareti (`market.mark`) YOKSA `son_kontrol[c]`'yi ilerletmiyordu; bu, o coin'e
  ait her sonraki dolumda (herhangi bir coin için çağrıldığında, tüm `held` coin'leri üzerinden minimum alındığı
  için) aynı, büyüyen boşluğun baştan taranmasına yol açıyordu — O(dolum × boş-saat) patlaması. Gerçek veride
  (B17, çok sayıda kısa ömürlü/düşük likiditeli coin) 30 dakikalık arka plan bütçesinde çıktısız durdu; sentetik
  testler hiçbiri bunu yakalamamıştı. Düzeltme: işaret bulunamasa da `son_kontrol[c]=saat` her zaman ilerletilir
  (yalnız zorla kapatılan coin takipten tamamen çıkar). Kalıcı regresyon testi eklendi
  (`test_mark_eksik_olan_pozisyon_her_dolumda_bastan_taranmaz`, 2s sınır). Düzeltme sonrası küçük denemede
  (O01/O02/B17) 3 trader ~6 dk 48s'de bitti (kullanıcı CPU'su 29s — süre ağ gecikmesinden, donma yok): O01 ve B17
  için `sanal_kopya_v3` sağlıklı (`bakiye_usd`/`getiri` mantıklı, `tasfiye: false`, `kapanis_nedenleri: []` —
  gözlemle uyumlu, eşiklere tek pozisyonla ulaşılmadı), O02 beklendiği gibi `hesaplanamadi`.
- `python -m pytest -q`: 550 geçti.

## E3 (2026-10-30 gece): aşamalı zarar_kes/kar_al canlıya bağlandı
Kullanıcı: "sırayla yap, sormana gerek yok." `golge.py`'deki ön kayıtlı aşamalı çıkış kuralı (intraday −%50; swing
gün 0/7/14 kademeli) `kopya_v2`'ye `variant='V2'` ile bağlandı; eşikler değişmedi (zaten dondurulmuştu). Her
zorunlu çıkışın nedeni `kapanis_nedenleri`de. 9 altın örnek, `pytest -q` 536 geçti. Gerçek veride (O01) henüz
tetiklenmedi (pozisyon eşiğe değmiyor) — doğru, yanlış tetiklenme yok. **Sabit $ işlem tutarı sorulmadan
atlandı** (eşik/strateji kararı, AGENTS.md): Etre'nin eğrisi (200$→5,2$, 1.000$→20,7$, 10.000$→150$, sonrası
sabit) kesin sayı gerektiriyor, kullanıcı onayı bekliyor.

## E4 (2026-10-30 gece): zaten büyük ölçüde mevcut — yeni kod yazılmadı
İncelemede: Etre'nin "gerekçeli giriş/çıkış, bekleme süreli, değişmez olay günlüğü, odadan düşme kuralı" istekleri
K-11'den ÖNCE kurulmuş, kullanıcı onaylı (ön kayıt 1.6) `copytrade/gecis.py` + `copytrade_haftalik.yml` (her
Perşembe) tarafından zaten sağlanıyor: alt dilim + ardışık hafta çıkış kuralı, 28 günde ≤2 çıkış tavanı, değişmez
`rotasyon/kayit.jsonl` olay günlüğü. Yeni kod yazmadım (kural 7: mevcut fonksiyonu kopyalama). Gerçek veri kontrolü:
`rotasyon/kayit.jsonl` henüz yok — pilot 29.10'da başladı, ilk Perşembe koşusu henüz gerçekleşmedi (zamanlama,
hata değil). "Aday sırası" kavramı `havuz` kolu ile zaten karşılanıyor.

## E6 (2026-10-30 gece): mühendislik — mevcut durum zaten iyi
`except Exception` taraması: `copytrade/`+`worker/`'da 11 yer, hepsi `# noqa: BLE001` ile gerekçeli ve hata
sayılıp/loglanıyor (Etre'nin "128 yerde sessiz yutma" sorunu yok). Ayarlar tek dosyada (`kurallar.yaml`).

**İş akışı arşivi (kullanıcı onayı "onaylıyorum devam et" ile, 2026-10-30 gece):** 12 iş akışı incelendi (GOREV'in
andığı 17 değil; #443 temizliği zaten indirmiş). İkisi tamamlanmış tek seferlik işti, Actions geçmişinden
doğrulanıp kaldırıldı (git geçmişinde duruyor):
- `hf_dogrulama.yml` — HF geçmiş veri doğrulaması (`docs/GOREV_HF_DOGRULAMA.md`), son koşu (28.10) başarılı, görev bitti.
- `pilot_bosluk.yml` — dosyasında "TEK SEFER, elle" yazıyordu; son koşu (29.10 16:03) başarılı, boşluk dolduruldu.

Dokunulmayanlar (hâlâ kullanılan, yeniden kullanılabilir araçlar): `golge_saglama.yml` (manuel `golge.py` sağlık
kontrolü), `izleme_deneme.yml` (kural 1'in gerektirdiği "küçük gerçek veri denemesi" aracı — zorunlu, silinmez).
İş akışı sayısı 12 → 10.

## E5 devamı (2026-10-30 gece): pano/ofis/Telegram artık v1 değil **v3** gösteriyor (kullanıcı kararı)
Kontrol sırasında bulundu: `sg-pano` (E5, Opus'ta ayrı yürütülmüş) hâlâ yalnız `sanal_kopya` (v1 — eski, trader
hesabına ORANLI, risksiz kopya) okuyordu; `sanal_kopya_v2`'ye de hiç bağlı değildi. `sanal_kopya_v3` (bugünkü
#453, sabit tutar + çıkış kuralları + tasfiye — "bitti tanımı"nın istediği motor) panoya/ofise/Telegram'a HİÇ
ulaşmıyordu; görünen rakamlar güncel motoru yansıtmıyordu. Kullanıcı: "güncel motorumuz ona bağlansın ... eski
olur mu hiç" — üç tüketici de v3'e geçirildi. **Kural 6 (yan yana):** v1/v2 silinmedi/değişmedi, `durum.json`'da
hâlâ yayımlanıyor; yalnız HANGİ sürümü gösterdikleri değişti.
- `sg-pano/index.html` (6 yer) ve `sg-pano/ofis/gercek.js` (3 yer): `t.sanal_kopya` → `t.sanal_kopya_v3`.
- `worker/src/index.js` `sanalKohort()` (Telegram günlük özet): aynı değişiklik; ayrıca gerçek bir hata bulundu
  ve düzeltildi — `.filter(Boolean)` bir `{"durum":"hesaplanamadi"}` yer tutucusunu ELEMİYORDU (nesne truthy),
  bu da ortalama getiriyi (payda büyür, pay büyümez) ve ofisteki kohort `n` sayısını sessizce çekiyordu; artık
  yalnız gerçek `getiri` sayısı olan girdiler sayılır (`copytrade/kopya_v3.py`'nin "hiç okunmadı" yer tutucusu
  ilk kez gerçek bir tüketiciye ulaştığı için açığa çıktı). Aynı düzeltme `sg-pano/ofis/gercek.js`'in `kol()`
  fonksiyonuna da uygulandı (ofisin Kohort↔Kontrol kartı aynı hatayı taşıyordu).
- `copytrade/izleme_motoru.py::kasa_egrisi()`: pano'nun "Kasa eğrisi" grafiğinin sunucu tarafı toplamı da v3'e
  geçti (v3 hesaplanamayan trader o günden dışarıda bırakılır, sıfır sayılmaz — yeni altın örnek test).
- Örnek/demo veri (`izleme/ornek_durum.json`, iki repoda da): her trader'a `sanal_kopya_v3` eklendi (v1'in aynı
  sayılarıyla — örnek veri zaten "ÖRNEK VERİ" etiketli, gerçek değil); pano'nun demo modu boş kalmasın diye.
- **Gerçek veri kıyası (kural 6, bugünkü küçük deneme — O01/O02/B17, aynı koşu):**
  | Trader | v1 (eski, artık gösterilmiyor) | v3 (yeni, artık gösterilen) |
  |---|---|---|
  | O01 | +%5,87 ($1.058,70) | −%0,36 ($996,45) |
  | O02 | hesaplanamadı (hesap verisi yok) | hesaplanamadı (aynı neden) |
  | B17 | +%0,16 ($1.001,62) | **−%32,73 ($672,72)** |

  Fark açıklanabilir ve zaten `VERI_SOZLESMESI.md`'de belgeli: v1 trader hesabına ORANLI kopyalıyor (B17'nin
  70,2 milyon $ hesabında kopya payı kırıntı kalıyor), v3 Etre'nin sabit-$ eğrisiyle KOPYANIN KENDİ (küçük)
  değerine göre açıyor — aynı fiyat hareketi artık kopya sermayesinin çok daha büyük bir payını oynatıyor
  (tasarımın amacı tam bu). **Önemli:** pano ve Telegram'da görünen sayılar bu PR'dan sonra BELİRGİN şekilde
  değişecek (ör. B17 gibi büyük/kaldıraçlı trader'larda); bu bir hata değil, artık doğru motoru göstermenin
  sonucu.
- **`copytrade/degisim_rapor.py` (oda rotasyon "değişim alfası") — #454'te bilerek v1'de bırakılmıştı, sonra
  kullanıcı kararıyla ("v3 olmalı, yeni çalışmamız o") v3'e çevrildi** (bkz. aşağıdaki "degisim_rapor v3" bölümü).
- `python -m pytest -q`: 551 geçti (yeni `test_kasa_egrisi_v1i_degil_v3u_okur...`). `worker`: `node --test` 40
  geçti (yeni "v3 hesaplanamamış trader ortalamaya 0 olarak girmez"). `sg-pano`: `node test/pano.test.js`,
  `node ofis/test/gercek.test.js`, `node ofis/test/replik.test.js`, `node ofis/test/ui.test.js` hepsi geçti.

## degisim_rapor v3 (2026-10-31 gece): oda rotasyon raporu da güncel motoru okuyor
Kullanıcı: "V3 olmalı sonuçta, yeni çalışmamız o." `copytrade/degisim_rapor.py` artık `sanal_kopya_v3.toplam`
okuyor (v1 değil). Önceki rapor `kaynak`sız ise (v1 dönemi) kayıtlı `cikarilan_taban_net` değerleri v3 sayılarıyla
karıştırılmaz: taban v3'ten yeniden alınır, raporda `taban_sifirlandi: true`. v3 hesaplanamamışsa değişim "izleme
verisi bekleniyor" kalır (v1'e düşmez). Henüz hiç rotasyon kaydı olmadığından (`copytrade/degisim.jsonl` yok)
sıfırlanan canlı bir taban yok. Gerçek veri denemesi: O01→B17 örneği, alfa = alınanın v3 getirisi (−%32,73) −
(çıkarılanın birikimi − taban = 0). Ön kayıt eşikleri/gerekçeler/tavanlar değişmedi.
