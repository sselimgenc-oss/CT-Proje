"""R2-1: canli_marj_kaldirac yaml'da degisince defter (hesap.json'dan yuklenen) eski kaldiraci korur."""
from tests.test_canli_motor import kur


def test_yaml_kaldirac_degisince_defter_kaldiraci_guncellenir(tmp_path):
    m, hl, saat, tgp = kur(tmp_path, kurallar={"canli_marj_kaldirac": 3})
    m.baslat()
    m.durum_yaz()
    assert m.hesap.kaldirac == 3.0
    m2, *_ = kur(tmp_path, kurallar={"canli_marj_kaldirac": 5})      # ayni durum dizini, yaml 3 -> 5
    assert m2.rules["canli_marj_kaldirac"] == 5
    assert m2.hesap.kaldirac == 5.0, f"defter kaldiraci {m2.hesap.kaldirac} (yaml 5)"
