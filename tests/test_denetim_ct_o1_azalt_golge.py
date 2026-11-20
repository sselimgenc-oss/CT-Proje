"""R1-1: artirma/acilis slot'u golge_carpan (x0.5) ile olceklenir, AZALTMA olceklenmez -> trader yariya indirse de biz azaltmayiz."""
from tests.test_canli_motor import kur, olay, adr


def test_azalt_golge_carpan_ile_ayni_slotu_kullanmali(tmp_path):
    m, hl, saat, _ = kur(tmp_path, kasa=2200.0)             # N=11 -> slot 200 $
    m.baslat()
    m._golge_acik[adr(1)] = ["B_kaldirac_5x"]                      # sanal: trader kaldiraci > 5x -> acilis boyutu x0.5
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 900, 100.0, 0.0, saat))     # 90.000 $/100.000 -> hedef 0.9*200*0.5 = 90 $
    ilk = m.hesap.sz(adr(1), "BTC") * 100.0
    assert 89 < ilk < 91                                   # slot 200 x0.5 x 0.9 = 90
    m.piyasa_oku(saat())
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "A", 450, 100.0, 900.0, saat))   # trader yariya indirir: beklenen hedef 45 -> 45 $ azaltma (gercek: hedef 90 = biz -> fark 0 -> min_emir_atlandi)
    assert [(x.eylem, x.karar) for x in s] == [("azalt", "emir")], [(x.eylem, x.karar, x.neden) for x in s]
