<!-- Kaynak: sselimgenc-oss/SG-Github-AB-proje trader/paket/ortak_ogrenme/README.md @ 84f6cad (kopya; değiştirme, güncelleme kaynaktan) -->
# ortak_ogrenme (SURUM 1.1.0)

Ortak öğrenme paketi: aday kaydı (`Aday`), kodla yazılan işlem notu (`notlar.not_yaz`) ve aday ders yaşam döngüsü
(`ders`). Parça 1 yalnız Python 3.11+ standart kütüphane kullanır; parça 2'de yalnız `filtre.py` numpy ister. `trader_core` / `trader_engine` / `trader_ml` içe aktarılmaz.
Paket yalnız puan, rapor ve etiket üretir; hiçbir işlemi engellemez. Spec: `docs/standart/ortak-ogrenme-paketi-spec.md`.

## Kopyalama

1. Bu klasörü (`trader/paket/ortak_ogrenme/`) alan projenin paket dizinine olduğu gibi kopyalayın.
2. Kaynak yolu ve commit'i not edin, örnek: `Kaynak: trader/paket/ortak_ogrenme @ <commit>, SURUM 1.1.0`.
3. Paketi değiştirmeyin. Projeye özgü çeviri yalnız adaptörde yapılır.
4. Adaptörünüzü yazın (aşağıdaki örnek) ve kendi testinizde ML/başka bir referansla eşdeğerliği doğrulayın.
   Referans testi: `tests/paket/test_ortak_ogrenme_parity.py`.

## Adaptör örneği

Kendi işlem kaydınızı `Aday`'a çevirin. Kapanmış işlemler için `cikis` ve `ozellikler` alanlarını doldurun.

```python
from datetime import timezone
from ortak_ogrenme.kayit import Aday
from ortak_ogrenme import notlar, ders

def adaya_cevir(islem, karar):
    """islem: kapanmış işlem kaydınız; karar: karar anı kaydınız (yoksa None)."""
    ozellikler = dict(karar.features) if karar else {}
    if karar and karar.atr_ratio is not None:
        ozellikler["atr_ratio"] = karar.atr_ratio   # yuksek_vol bu anahtarı okur
    return Aday(
        id=str(islem.trade_id), proje="ML", kurulum=islem.setup, enstruman=islem.pair,
        varlik_sinifi="kripto", yon=islem.side,
        ts=(karar.bar_close_ts if karar else islem.entry_ts).astimezone(timezone.utc),
        alindi=True, r=islem.r_multiple,
        seans=karar.session_tag if karar else None, rejim=islem.regime,
        ozellikler=ozellikler,
        cikis={"entry_price": islem.entry_price, "planned_entry": islem.planned_entry,
               "planned_stop": islem.planned_stop, "exit_reason": islem.exit_reason,
               "bars_held": islem.bars_held, "mfe_r": islem.mfe_r, "mae_r": islem.mae_r},
    )

# Kullanım:
# etiketler, metin = notlar.not_yaz(adaya_cevir(islem, karar))
# etki, n = ders.ders_etkisi(adaylar, "seans_kapali:T1", "2026-05-01", as_of, shrink_n=10)
```

## Önemli notlar

- `kurulum` değeri ders kimliğinde doğrudan kullanılır (`ders:<kod>:<kurulum>`). Etiket sözlüğü yalnız
  harf, rakam ve `_` kabul eder. `@` içeren bir kurulum (örn. `T1@1h`) kayıpta ders etiketi üretirken `ValueError`
  verir. Adaptörde kurulumu `@` öncesi kısımla verin.
- `ders_etkisi` varsayılan `shrink_n = 0` (spec). ML kâğıt kararı da 0'dır; ML `trade_notes` modülü ise 10 kullanır.
  Eşdeğerlik testlerinde iki taraf da açıkça aynı değerle çağrılır.
- Durum dosyası (`gece_adimi`) atomik yazılır; bozuk veya eksik dosya boş durum sayılır.

## Parça 2: karne, sanal kasa, drift, ortak filtre

Girdi her yerde `Aday` listesidir. Paket yine yalnız puan ve rapor üretir; bir işlemi engelleyip engellemediği
adaptörün kararıdır.

### `karne.py` (standart kütüphane)

- `karne(adaylar, kurulumlar=())`: kurulum başına `aday`, `alinan`, `cozulen`, `ort_r_alinan`, `ort_r_tum`,
  varlık sınıfına göre `sinif` ve `kasa`. `kurulumlar` içindeki adaysız kurulumlar sıfır satırla yer alır.
- `sanal_kasa(adaylar, *, baslangic=1000.0, risk=0.01, kurulumlar=())`: ML'deki `arm_virtual_bankroll` ile aynı
  kural. Seri `{n, kasa, getiri_pct, en_derin_pct}`; `en_derin_pct` tepe noktasından pozitif yüzde olarak verilir.
  `alinan` yalnız alınan işlemleri, `tum` alınmayan ("alınsaydı") işlemleri de içerir.

### `drift.py` (standart kütüphane)

- `cusum(rs)`: ML `cusum_replay` ile aynı sabitler ve kurallar. `alarms` 1-tabanlı indekslerdir.
- `kurulum_drift(adaylar)`: alınmış ve R'si bilinen adaylar üzerinden kurulum başına CUSUM. `durum` alanı son
  alarmdan beri 30 işlemden az geçtiyse `uyari`, değilse `normal` olur.

### `filtre.py` (numpy: yalnız bu modül)

- `egit(kurulum, adaylar, *, olusturma, kilit, azami)`: ridge lojistik regresyon (Newton/IRLS; ML
  `fit_logistic` ile sayısal olarak aynı). Yalnız alınmış ve R'si bilinen adaylar kullanılır, etiket `r > 0`,
  eşik `0.9 x taban oran`. Veri yoksa ya da tek sınıf varsa `None` döner.
- Kilit aralıkları (holdout): `kilit=[(baslangic, bitis), ...]` içindeki `ts` değerine sahip satırlar eğitimden
  yapısal olarak düşer ve `meta.kilit_dusen` ile sayılır. Bu bir karar değil, eğitim veri kümesinin kuralıdır.
- `kaydet(paket, klasor)`: `<kurulum>.json` dosyasını atomik yazar, öncekini `<kurulum>.prev.json` yapar. Yazmadan
  önce gidiş-dönüş doğrulaması yapar. Son kullanma denetlenmez, çünkü kayıt bir kullanım değildir.
- `yukle(yol_ya_da_sozluk, *, simdi, sure_kontrol)`: model hash'i, özellik hash'i, paket sürümü ve son kullanma
  (olusturma + 21 gün) denetlenir. Hata durumunda `PaketHatasi` (ValueError alt sınıfı) fırlatılır.
- `puan(paket, ozellikler)`: standardizasyon, sigmoid (z, [-35, 35] aralığında kırpılır). Eksik ya da sayı olmayan
  özellik modeldeki `fill` değeriyle doldurulur. Sonuç her zaman `[0, 1]` aralığındadır.

### Parça 2 eşdeğerlik testleri

`tests/paket/test_ortak_ogrenme_parca2_parity.py`: `karne` / `sanal_kasa` ↔ `arm_scorecard` / `arm_virtual_bankroll`
(alan adı eşlemesiyle), `fit_logistic` ↔ `setup_filter.train.fit_logistic` (NaN dahil), `cusum` ↔ `cusum_replay`,
`puan` ↔ `TreeModel` lojistik tahmini. Filtre paketi için gidiş-dönüş, hash ve süre denetimleri ile kilit düşürme
testleri de burada.

