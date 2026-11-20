> **İPTAL — kullanıcı kararı 20.11:** CT ile ML arasında hiçbir etkileşim olmayacak (ML CT'den veri okumaz; konsensüs, ortak ders deposu ve ortak koruyucunun ML bağlantısı iptal). Bu taslak uygulanmaz; yalnız arşiv. CT'nin yerel koruyucusu (K-82) aynen sürer.

# Ortak koruyucu arayüzü (CT <-> ML) — TASLAK — ML onayı olmadan kesinleşmez

Kapsam: CT ve ML'nin toplam riskini tek yerden izleyecek ortak koruyucunun dosya arayüzü (docs/binance-plan.md §5). Limit rakamları burada SEÇİLMEZ.
Kullanıcı kararı A1: ML ana Binance hesabında, CT ayrı alt hesapta; iki hesabın teminatı AYRI, toplam risk koruyucudan izlenir.

## 1. Dosyalar (tek yazar kuralı)
Dizin: `ortak/` (ortak sunucuda; yolu birimlerde `ORTAK_DIZIN` ile verilir). Biçim JSON (UTF-8). Yazma atomik: `.tmp` + fsync + `os.replace` + dizin fsync. Her dosyanın TEK yazarı var; ortak yazma yok, bu yüzden kilit gerekmez.

| Dosya | Yazar | Okur |
|---|---|---|
| `ortak/ct.json` | CT tarafı (şimdilik CT yerel koruyucusu, motor dosyalarından türetir) | ortak koruyucu |
| `ortak/ml.json` | ML | ortak koruyucu |
| `ortak/dur.json` | yalnız ortak koruyucu | CT motoru, ML |
| `ortak/koruyucu.json` | ortak koruyucu (nabız) | CT, ML |

## 2. Hesap bölümü şeması (`ct.json`, `ml.json`; aynı alanlar)
`sema` str `ortak.hesap.v1` · `surum` int (şema sürümü; uyumsuzsa okuyan alarm verir, tahmin etmez) · `taraf` str `ct`|`ml` · `kip` str `sanal`|`gercek` · `yazildi_ms` int (nabız) ·
`ozsermaye_usd` float · `gun_basi_usd` float (UTC gün sınırında önceki günün son değeri) · `zirve_usd` float · `gunluk_kayip_oran` float · `zirveden_dusus_oran` float ·
`acik_nosyonel_usd` float · `kaldirac` float|null (en yüksek pozisyon kaldıracı) · `acik_pozisyon` int · `dur` bool (taraf kendi DUR'unda mı).
Bilinmeyen değer `null`; uydurma 0 yazılmaz.

## 3. Toplam ve dur bayrağı (`dur.json`, yalnız koruyucu yazar)
`sema` `ortak.dur.v1` · `surum` · `yazildi_ms` · `toplam`: {`ozsermaye_usd`, `gun_basi_usd`, `zirve_usd`, `gunluk_kayip_oran`, `zirveden_dusus_oran`, `acik_nosyonel_usd`} (ct+ml toplamı; bir taraf bayatsa `null` ve `eksik_taraf`) ·
`ct` ve `ml`: {`yeni_acilis_dur` bool, `kapat_dur` bool, `nedenler` [str], `ms`}.
Semantik: `yeni_acilis_dur` = yeni açılış/artırma yok, kapanış/azaltma ASLA engellenmez, koşul bitince (UTC gün dönümü ya da nabız düzelince) koruyucu kaldırır. `kapat_dur` = tüm pozisyonlar kapatılır + taraf durur; mandal: yalnız insan (bayrağı/DUR'u silerek) kaldırır, taraf kendi bayrağını silemez.
Hesap başı öncelik (Fable F2): bir tarafın bayrağı diğerini kapatmaz; toplam eşiği dolarsa ikisine de yazılır.

## 4. Nabız ve bayat veri
Her yazar `yazildi_ms`'i her döngüde yeniler (öneri 30 sn). Bayat eşiği KULLANICI KARARI BEKLİYOR (CT yerelde `kurallar.yaml` `koruyucu_nabiz_bayat_sn` = 180 sn, plan §5 önerisi). Taraf bayatsa: koruyucu alarm + o tarafa `yeni_acilis_dur`; toplam o taraf için `null`. Koruyucu nabzı bayatsa taraflar yeni açılış yapmaz; ilk kurulumda koruyucu hiç görülmemişse yalnız uyarı (geçiş kuralı, CT: bir kez görüldükten sonra mandal).

## 5. Limitler
| Limit | Değer |
|---|---|
| CT günlük kayıp (yeni açılış dur) | %5 (`canli_gunluk_kayip_oran`, mevcut) |
| CT zirveden düşüş (kapat + dur) | %20 (`canli_zirve_dusus_oran`, mevcut) |
| CT günlük sert fren (bilgi; motor uygular) | %10 (`canli_gunluk_kapat_oran`, mevcut) |
| ML hesap limitleri | KULLANICI KARARI BEKLİYOR |
| Toplam (ct+ml) günlük kayıp / zirveden düşüş / açık nosyonel / kaldıraç | KULLANICI KARARI BEKLİYOR |
| Nabız bayat eşiği (ML ve toplam) | KULLANICI KARARI BEKLİYOR |

## 6. Çakışma ve kilit
Ortak yazılan dosya yok; her taraf yalnız kendi dosyasını yazar, `dur.json`'u yalnız koruyucu. Okuyan yarım dosya görmez (atomik yer değiştirme). Okuma hatası/bozuk JSON = bayat sayılır (açılış durur, kapanış serbest). Tek hesapta sembol kilidi (plan §6) bu taslakta YOK; alt hesap yolu esas.

## 7. Doğrulanmadı (Binance'e özgü varsayımlar)
- Ana hesap API anahtarının alt hesap özsermayesi/pozisyonunu okuyabilmesi (koruyucunun toplamı buna dayanır; yoksa her taraf kendi değerini yazar, koruyucu yalnız dosyaya güvenir).
- Ana hesabın alt hesap adına emir verememesi/verebilmesi (koruyucunun doğrudan kapatma yetkisi buna bağlı; yoksa kapatma tarafın kendi motoruna `dur.json` ile istenir).
- Alt hesap anahtarının çekme-kapalı/IP-kısıtlı oluşturulabilmesi. Hiçbiri gerçek hesapta denenmedi; bu taslak gerçek para/anahtar/ağ izni içermez.
