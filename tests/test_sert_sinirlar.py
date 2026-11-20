"""K-72: gerçek para sert sınırları (koda gömülü). Gerçek kipte yaml sınırı aşarsa başlamaz; sanal kip etkilenmez."""
import pytest

from copytrade.canli import motor as mt
from copytrade.canli import sert_sinirlar as sert
from copytrade.canli.risk import Risk
from copytrade.kurallar import load_rules

RULES = load_rules()
ORTAM = {"CANLI_KASA_USD": "1000"}


def test_sabitler():
    assert (sert.GERCEK_KASA_UST_USD, sert.GUNLUK_KAYIP_UST_ORAN, sert.KALDIRAC_ALT, sert.KALDIRAC_UST) == (1500.0, 0.05, 1, 5)


def test_yaml_su_anki_degerler_sinir_icinde():
    assert RULES["canli_kasa_ust_usd"] == 1500 and RULES["canli_kasa_usd"] == 1000
    assert RULES["canli_gunluk_kayip_oran"] == 0.05 and RULES["canli_marj_kaldirac"] == 3
    sert.gercek_kip_dogrula(RULES)
    assert mt.kasa_belirle(RULES, "gercek", ORTAM) == (1000.0, "ortam")
    assert mt.kasa_belirle(RULES, "gercek", {"CANLI_KASA_USD": "1500"}) == (1500.0, "ortam")


def test_kasa_1500_ustu_reddedilir():
    with pytest.raises(mt.KipHatasi):
        mt.kasa_belirle(RULES, "gercek", {"CANLI_KASA_USD": "1500.01"})


def test_yaml_kasa_siniri_sert_sabiti_asamaz():
    r = {**RULES, "canli_kasa_ust_usd": 5000}
    assert mt.kasa_ust(r, "gercek") == 1500.0                                   # min(yaml, sert)
    with pytest.raises(mt.KipHatasi, match="sert sınır"):
        mt.kasa_belirle(r, "gercek", ORTAM)                                       # başlangıçta açık ret
    assert Risk(r, 1000.0).kasa_siniri_asildi(1500.01) is True                    # Risk varsayılanı da min


@pytest.mark.parametrize("oran", [0.0501, 0.1, 1.0])
def test_gunluk_kayip_oran_sert_ustu_gercekte_reddedilir(oran):
    with pytest.raises(mt.KipHatasi, match="canli_gunluk_kayip_oran"):
        mt.kasa_belirle({**RULES, "canli_gunluk_kayip_oran": oran}, "gercek", ORTAM)


@pytest.mark.parametrize("k", [5.01, 10, 0.5, 0])
def test_kaldirac_aralik_disi_gercekte_reddedilir(k):
    with pytest.raises(mt.KipHatasi, match="canli_marj_kaldirac"):
        mt.kasa_belirle({**RULES, "canli_marj_kaldirac": k}, "gercek", ORTAM)


@pytest.mark.parametrize("k", [1, 3, 5])
def test_kaldirac_aralik_ici_kabul(k):
    assert mt.kasa_belirle({**RULES, "canli_marj_kaldirac": k}, "gercek", ORTAM)[0] == 1000.0


def test_sanal_kip_etkilenmez():
    r = {**RULES, "canli_gunluk_kayip_oran": 0.2, "canli_marj_kaldirac": 10, "canli_kasa_ust_usd": 5000}
    assert mt.kasa_belirle(r, "sanal", {}) == (float(r["canli_kasa_usd"]), "yaml")
    assert mt.kasa_ust(RULES, "sanal") == 10000.0
    assert mt.sanal_kasa_dogrula(RULES, "sanal", 10000) == 10000.0


@pytest.mark.parametrize("k", [4.5, 1.5, 2.0001])
def test_d8_kesirli_kaldirac_gercekte_reddedilir(k):
    with pytest.raises(mt.KipHatasi, match="canli_marj_kaldirac"):
        mt.kasa_belirle({**RULES, "canli_marj_kaldirac": k}, "gercek", ORTAM)


def test_d8_tam_sayi_gibi_float_kabul():
    assert mt.kasa_belirle({**RULES, "canli_marj_kaldirac": 4.0}, "gercek", ORTAM)[0] == 1000.0
