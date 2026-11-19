"""Üretim `kurallar.yaml` boyut/risk değerleri (K-56'dan, K-66 Form Radarı ile: N 11, slot 200 $, tavan 1,5×, yuvarlama alt sınırı 5,5 $, slot stop %20; D-01: radar kasası 10.000 $) v1'den farklıdır.
Eski altın örnekler (elle hesaplanmış sayılar) v1 değerleriyle yazıldı; mantığı aynen sınamaya devam etsinler diye testlerde `load_rules()` bu anahtarları v1 değerleriyle (toplu emir bandı 15.11: kapalı) döndürür.
Üretim değerlerinin kendisi `tests/test_k66_uretim.py`'de `load_rules_asil()` (dosyadaki gerçek değerler) ile ayrıca sınanır. Başka hiçbir anahtar değişmez."""
import copytrade.kurallar as _k

V1_BOYUT_RISK = {"radar_saha_max": 11, "radar_canli_slot_min_usd": 25, "radar_slot_tavan_carpan": 3.0, "radar_min_emir_yuvarla_alt": 0.0,
                 "canli_slot_dusus_oran": 0.10, "canli_bekleme_gun": 14, "canli_islem_yok_saat": 72,
                 "radar_kasa_usd": 1000,       # D-01 (14.11): v1 radar oynatma kasası = canli_kasa_usd (1.000 $); üretim 10.000 $ test_k66_uretim / test_d01_radar_kasa'da
                 "canli_bant_usd": 0, "canli_bant_oran": 0.0, "canli_bant_azalt_usd": 0, "canli_bant_azalt_oran": 0.0,
                 "canli_haftalik_kadro": False, "canli_inen_saat": 24,
                 "canli_min_azami_kaldirac": 0}   # K-67 (17.11) kaldıraç süzgeci eski altın testlerde kapalı (sahte HL `meta` maxLeverage içermez); üretim değeri 5 test_denetim_1117_kaldirac_mutabakat'ta load_rules_asil ile   # haftalık kadro (16.11) v1'de yok; üretim davranışı test_haftalik_kadro'da load_rules_asil ile   # toplu emir bandı (15.11) v1'de yok; üretim değerleri test_boyut_bant'ta load_rules_asil ile

if not hasattr(_k, "load_rules_asil"):
    _k.load_rules_asil = _k.load_rules

    def _test_kurallari(path=_k.RULES):
        r = _k.load_rules_asil(path)
        if path == _k.RULES:
            r.update(V1_BOYUT_RISK)
        return r

    _k.load_rules = _test_kurallari


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _rejim_agsiz(monkeypatch):
    """Testlerde ML rejim yayınına ağ çağrısı yapılmaz (üretim `rejim_kaynak_url` dolu; okuma testleri sahte getiriciyle)."""
    import copytrade.canli.rejim as _rejim

    def _yok(url):
        raise OSError("testte ağ yok")

    monkeypatch.setattr(_rejim, "_getir_varsayilan", _yok)
