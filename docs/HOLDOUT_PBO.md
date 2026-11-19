# Aşırı uydurma koruması: holdout mührü, PBO, sürüm karşılaştırma

Kapsam: **yalnız raporlama** (Faz 2). Strateji, `radar_*` eşikleri ve emir kararları değişmez. Kod: `copytrade/holdout_muhur.py`, `copytrade/pbo.py`, `copytrade/pbo_rapor.py`, `copytrade/surum_karsilastirma.py`.

## 1. Holdout mührü (sınav kâğıdını mühürlemek)

**Sorun:** Aynı veriye bakıp stratejiyi tekrar tekrar ayarlarsak, sonunda "geçmişte çok iyi" ama gelecekte işe yaramayan bir ayar buluruz (aşırı uydurma). Çözüm: bir kısım veriyi ayırıp mühürlemek ve ona **tek seferlik** bakmak.

- **Başlangıç:** `copytrade/kurallar.yaml` → `holdout_bas: "2026-11-20"`. Bu tarihten itibaren her gün radar dalına yazılan şu dosyalar mühürlenir: `havuz_ilk.json`, `kadro_ilk.json` (günün ilk taraması/kadrosu) ve `isabet.json` (7 gün sonra ölçülen sonuç). (`kadro.json`/`havuz.json` gün içinde yeniden yazıldığı için mühürlenmez.)
- **Nasıl:** `radar.yml` içinde "Holdout mührü" adımı, her dosyanın SHA-256 parmak izini `radar/holdout/manifest.json`'a yazar (`radar` dalı; yayım `radar_yayimla.sh`).
- **Yalnız eklenir (append-only):** manifest'teki kayıtlar bir zincirle bağlıdır; eski bir kaydı değiştirmek/silmek zinciri bozar ve yakalanır. Mühürlü bir dosya sonradan değişirse mühür **ezilmez**, `ihlaller` listesine yazılır ve iş günlüğünde `::error::HOLDOUT İHLALİ` görünür (radar yayımı yine de durmaz; bu bir bilgi/koruma katmanıdır).
- **Kontrol:** `python -m copytrade.holdout_muhur dogrula --veri-dali radar` (sorun varsa çıkış kodu 1).
- **Saklama:** radar dalı tarihli klasörleri 90 gün tutar, ancak manifest'in andığı mühürlü dosyalar bu silmeden MUAFTIR (`radar_yayimla.sh`; klasörde yalnız onlar kalır). Yine de 90 günden eski eksik dosya ihlal sayılmaz (`saklama_disi`; eski veri dalı koşuları için).

### Tek kullanım kuralı

> Yeni bir strateji ya da ML değişikliği holdout verisi üzerinde **yalnız bir kez** değerlendirilir. Sonuç kötü çıkarsa aynı değişiklik ayarlanıp holdout'a ikinci kez sokulmaz; yeni bir fikir yeni bir kullanım sayılır.

- Her holdout kullanımı `manifest.json` → `kullanim` listesine **tarih + amaç** ile yazılır (`kullanim_sayisi` sayaç). Kayıt, `copytrade/radar/HOLDOUT_KULLANIM.txt` dosyasına PR ile eklenen satırdan gelir (`YYYY-MM-DD | amaç | not | tekrar`); radar koşusu yeni satırları manifest'e işler (aynı tarih+amaç bir kez). Elle: `python -m copytrade.holdout_muhur muhurla --kullanim-amac ... --kullanim-not ...`.
- Aynı `amac` ikinci kez girilirse kayıt reddedilir; gerçekten ikinci bakış gerekiyorsa satırın sonuna `| tekrar` yazılır ve kayıt `tekrar: true` olarak görünür (kaç kez baktığımız saklanmaz, açıkça görünür).
- Holdout'a bakma kararı kullanıcıyla birlikte verilir; kayıt tutmak yetkiyi vermez.

## 2. PBO: "seçtiğim yöntem şans eseri mi iyi görünüyor?"

PBO = *backtest aşırı uydurma olasılığı* (Bailey ve ark. 2015, CSCV yöntemi). Fikir: elimizde birkaç aday yöntem ve günlük getiri serileri var. Günleri 8 bloğa böleriz; blokların yarısında "en iyi" olanı seçip kalan yarıda nasıl çıktığına bakarız; bunu tüm bölünmeler için tekrarlarız. Seçtiğimiz yöntem sınama yarısında **ortanın altında kalıyorsa** o bölünme "uydurma" sayılır. PBO bu bölünmelerin oranıdır.

- **PBO ≈ 0,5:** seçim gürültüden ayırt edilemiyor (yazı-tura gibi). **0'a yakın:** eğitimde iyi olan sınamada da iyi (gerçek üstünlük). **1'e yakın:** eğitimde iyi görünen sınamada hep kötü.
- **Deflated Sharpe (DSR):** çok sayıda aday denendiğinde en iyisinin şansla bu kadar yüksek çıkma payı düşülür; 0–1 arası "gerçek beceri olasılığı". 
- **Adaylar (sütunlar):** `ilk11` (forma göre İlk 11), `havuz` (R1 havuz ortalaması), `elenen` ve `evren_ornek30` (rastgele kontrol grupları), `ilk11_fiili` (her günde veri varsa). Dönem = isabet günü, değer = o günün seçiminin `sonraki_7g` getirisi. ML filtresi (açık/kapalı) gelince `--ek-aday` JSON'u ile sütun olarak eklenir.
- **Yetersiz veri:** gün sayısı `2 × S` altındaysa (S = `pbo_s` = 8 → en az 16 gün) rapor "yetersiz veri" yazar, hesap yapmaz. İlk tam isabet ölçümleri 7 gün sonra başladığı için bu rapor ilk haftalarda "yetersiz veri" gösterir; bu normaldir.
- **Dikkat:** günlük 7 günlük pencereler birbiriyle örtüşür (ardışık günler bağımlı) ve aday sayısı az (4–5). Bu yüzden PBO kaba bir göstergedir; tek başına karar vermez.
- **Çıktı:** `radar/<tarih>/pbo.json` (radar dalı) + `ISABET_OZET.md` sonuna tek satır; canlı pano `OZET.md` "Seçim isabeti" bölümünde aynı satır görünür.

## 3. Sürüm karşılaştırma (eski ↔ yeni yan yana)

Kural 6 gereği eski ve yeni sürüm yan yana gösterilir; yalnız rapordur (pano `OZET.md` "Sürüm karşılaştırma" bölümü ve pano sayfasındaki küçük tablo).

- **v4+ML (fiili):** motorun gerçekten yaptığı kapanış işlemleri, net K/Z = gerçekleşen − ücret (pano "Kapanan işlemler" ile aynı tanım), UTC günlük.
- **v4 taban (ML/ders yokmuş gibi):** fiili + ML veya ders yüzünden **atlanan** sinyallerin hayali K/Z'si (motorun `karsi_olgu_kapandi` kaydı; nedenler `ml_filtre_atla`, `ders_emekli`). Hayali K/Z ücret ve kayma içermez, yani taban biraz iyimserdir.
- **Sürüm:** olayın gününde uygulanan kadronun `radar_surum`'u (veri dalında `kadro_ilk.json`).
- **ML/ders:** motor `ml_filtre_atla` (ML filtresi) ve `ders_emekli` (emekli trader) nedenleriyle atladığı sinyalleri kaydeder; taban serisi bunların hayali K/Z'sini ekler. Hiç atlama yoksa iki seri aynıdır ve rapor bunu yazar.
