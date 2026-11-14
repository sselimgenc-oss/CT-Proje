"""Üretim `kurallar.yaml` boyut/risk değerleri (K-56'dan, K-66 Form Radarı ile: N 11, slot 200 $, tavan 1,5×, yuvarlama alt sınırı 5,5 $, slot stop %20) v1'den farklıdır.
Eski altın örnekler (elle hesaplanmış sayılar) v1 değerleriyle yazıldı; mantığı aynen sınamaya devam etsinler diye testlerde `load_rules()` bu yedi anahtarı v1 değerleriyle döndürür.
Üretim değerlerinin kendisi `tests/test_k66_uretim.py`'de `load_rules_asil()` (dosyadaki gerçek değerler) ile ayrıca sınanır. Başka hiçbir anahtar değişmez."""
import copytrade.kurallar as _k

V1_BOYUT_RISK = {"radar_saha_max": 11, "radar_canli_slot_min_usd": 25, "radar_slot_tavan_carpan": 3.0, "radar_min_emir_yuvarla_alt": 0.0,
                 "canli_slot_dusus_oran": 0.10, "canli_bekleme_gun": 14, "canli_islem_yok_saat": 72}

if not hasattr(_k, "load_rules_asil"):
    _k.load_rules_asil = _k.load_rules

    def _test_kurallari(path=_k.RULES):
        r = _k.load_rules_asil(path)
        if path == _k.RULES:
            r.update(V1_BOYUT_RISK)
        return r

    _k.load_rules = _test_kurallari
