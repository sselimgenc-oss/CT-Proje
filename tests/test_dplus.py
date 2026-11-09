"""K-56 D+ (kullanıcı onayı 09.11): üretim kurallar.yaml boyut/risk değerleri (testlerde conftest v1 değerlerini yükler; burada dosyadaki gerçek değerler) + açılış eşiği."""
import pytest

from copytrade import boyut
from copytrade.canli import motor as mt
from copytrade.kurallar import load_rules, load_rules_asil


def test_dplus_kurallar_dosyada():
    r = load_rules_asil()
    assert (r["radar_saha_max"], r["radar_canli_slot_min_usd"], r["radar_slot_tavan_carpan"], r["radar_min_emir_yuvarla_alt"]) == (5, 200, 1.5, 5.5)
    assert (r["canli_slot_dusus_oran"], r["canli_bekleme_gun"], r["canli_islem_yok_saat"]) == (0.20, 31, 336)
    assert (r["secim_aktif_coin_max"], r["secim_cikis_giris_dusus"], r["radar_min_kopya_islem"], r["radar_kisa_islem_payi_max"]) == (8, 0.20, 10, 0.25)
    assert boyut.saha_sayisi(1000.0, r) == 5 and boyut.slot_usd(1000.0, r) == pytest.approx(200.0)
    assert mt.radar_surum_oku() == "v2"


def test_dplus_acilis_esigi_5_5_alti_acilmaz_ustu_11e_yuvarlanir():
    r = {**load_rules_asil()}
    # slot 200 $, trader hesap 100.000 $: hedef = 200 × nosyonel / 100.000
    assert boyut.hedef_emir("ac", 0, 2.0, 100_000, 0, 200, 1_000.0, r) == (0.0, "min_emir_atlandi")
    assert boyut.hedef_emir("ac", 0, 3.0, 100_000, 0, 200, 1_000.0, r) == (11.0, "min_emir_yuvarlandi")       # hedef 6 $ ≥ 5,5 → 11 $
    assert boyut.hedef_emir("ac", 0, 2.75, 100_000, 0, 200, 1_000.0, r) == (11.0, "min_emir_yuvarlandi")      # tam 5,5 sınır dahil
    assert boyut.hedef_emir("ac", 0, 200.0, 100_000, 0, 200, 1_000.0, r) == (300.0, "tavan_kirpildi")        # 400 $ → tavan 1,5 × 200
    v1 = load_rules()                                                                                         # testlerde v1 (alt sınır 0): her küçük hedef yuvarlanır
    assert boyut.hedef_emir("ac", 0, 2.0, 100_000, 0, 200, 1_000.0, v1) == (11.0, "min_emir_yuvarlandi")
