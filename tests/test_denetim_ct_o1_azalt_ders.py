"""R3-1: yarım slotlu pozisyon trader %30 azaltınca (300->210) azaltılmaz: hedef çarpansız slot ile 190,9 $ > biz 136,4 $."""
import pytest
from copytrade.canli import motor as mt
from copytrade.canli.ogrenme_adaptor import takma_ad
from tests.test_canli_motor import adr, kur, olay


@pytest.fixture(autouse=True)
def _m():
    yield
    mt.MASKE.clear()


def test_kismi_azaltma_carpanli_pozisyonda_orantili_olmali(tmp_path):
    m, hl, saat, _ = kur(tmp_path, kasa=10000.0, kurallar={"canli_telegram_sanal_ozet_dk": 0})
    m.baslat()
    m.ogrenme.uyg["carpan"][takma_ad(adr(1))] = {"deger": 0.5, "etki": 1.0, "kimlikler": [], "ms": 0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    ilk = m.hesap.sz(adr(1), "BTC")
    assert ilk == pytest.approx(1.36364, abs=1e-4)
    m.piyasa_oku(saat())
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "A", 150, 100.0, 300.0, saat))   # trader %50 azaltır
    # beklenen: bizim pozisyon da ~%50 küçülür (0.68 BTC); gerçek: 1.36 aynen kalır (azalt "min_emir_atlandi")
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(ilk / 2, rel=0.05), [(x.eylem, x.karar, x.neden) for x in s]


def test_azaltma_carpani_kalici_yeniden_baslatmada(tmp_path):
    from copytrade.canli.hesap import Hesap
    m, hl, saat, _ = kur(tmp_path, kasa=10000.0, kurallar={"canli_telegram_sanal_ozet_dk": 0})
    m.baslat()
    m.ogrenme.uyg["carpan"][takma_ad(adr(1))] = {"deger": 0.5, "etki": 1.0, "kimlikler": [], "ms": 0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.hesap.poz[adr(1)]["BTC"].boyut_carpan == pytest.approx(0.5)
    assert Hesap.from_json(m.hesap.to_json()).poz[adr(1)]["BTC"].boyut_carpan == pytest.approx(0.5)
