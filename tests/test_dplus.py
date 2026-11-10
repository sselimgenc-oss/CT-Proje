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


def test_dplus_motor_uctan_uca_uretim_boyutuyla(tmp_path):
    """Fable ek gözlemi (denetim 10.11): motor uçtan uca ÜRETİM D+ boyutuyla (conftest'in v1 yaması olmadan; dosyadaki 7 anahtar).
    Kasa 1.000 $, N 5 → slot 200 $. Trader hesap 100.000 $:
    - 300 BTC × 100 $ = 30.000 $ (oran 0,30) → açılış 200 × 0,30 = 60 $.
    - +10 BTC (310 → hedef 62 $, fark 2 $) ve +40 BTC (350 → hedef 70 $, fark 10 $ < en küçük emir) → artırma atlanır (min_emir_atlandi).
    - +1.000 BTC (1.350 → hedef 270 $ ≤ tavan 1,5 × 200 = 300 $) → artırma 270 − 60 = 210 $.
    - 20 ETH × 100 $ = 2.000 $ → hedef 4 $ < 5,5 $ → açılmaz; 40 SOL × 100 $ = 4.000 $ → hedef 8 $ ≥ 5,5 $ → en küçük emre (11 $) yuvarlanır."""
    from tests.conftest import V1_BOYUT_RISK
    from tests.test_canli_motor import adr, kayitlar, kur, olay
    asil = load_rules_asil()
    m, _, saat, _ = kur(tmp_path, kurallar={k: asil[k] for k in V1_BOYUT_RISK})
    m.baslat()
    assert m.saha.slot == pytest.approx(200.0)
    adim = [("a:1", 300, 0.0, ("ac", "emir")), ("a:2", 10, 300.0, ("artir", "atlandi")), ("a:3", 40, 310.0, ("artir", "atlandi")), ("a:4", 1000, 350.0, ("artir", "emir"))]
    for kimlik, sz, once, beklenen in adim:
        assert [(x.eylem, x.karar) for x in m.olay_isle(olay(kimlik, adr(1), "BTC", "B", sz, 100.0, once, saat))] == [beklenen]
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(2.7)
    assert [(x.karar, x.neden) for x in m.olay_isle(olay("b:1", adr(1), "ETH", "B", 20, 100.0, 0.0, saat))] == [("atlandi", "min_emir_atlandi")]
    assert [(x.karar, x.neden) for x in m.olay_isle(olay("b:2", adr(1), "SOL", "B", 40, 100.0, 0.0, saat))] == [("emir", "min_emir_yuvarlandi")]
    assert [(e["coin"], e["usd_istenen"]) for e in kayitlar(tmp_path, "emir")] == [("BTC", pytest.approx(60.0)), ("BTC", pytest.approx(210.0)), ("SOL", pytest.approx(11.0))]
