<!-- Kaynak: sselimgenc-oss/SG-Github-AB-proje trader/paket/ortak_ogrenme/README.md @ af68a02 (kopya; değiştirme, güncelleme kaynaktan) -->
# ortak_ogrenme (SURUM 1.0.0)

Ortak öğrenme paketi: aday kaydı (`Aday`), kodla yazılan işlem notu (`notlar.not_yaz`) ve aday ders yaşam döngüsü
(`ders`). Yalnız Python 3.11+ standart kütüphane. `trader_core` / `trader_engine` / `trader_ml` içe aktarılmaz.
Paket yalnız puan, rapor ve etiket üretir; hiçbir işlemi engellemez. Spec: `docs/standart/ortak-ogrenme-paketi-spec.md`.

## Kopyalama

1. Bu klasörü (`trader/paket/ortak_ogrenme/`) alan projenin paket dizinine olduğu gibi kopyalayın.
2. Kaynak yolu ve commit'i not edin, örnek: `Kaynak: trader/paket/ortak_ogrenme @ <commit>, SURUM 1.0.0`.
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
