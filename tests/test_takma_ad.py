from copytrade.canli import telegram as tg
from copytrade.canli.takma_ad import KELIMELER, kisa_adres, takma_ad

A1 = "0x78aabbccddeeff00112233445566778899aabbcc"
A2 = "0x1234ab5678cdef901234567890abcdef12345678"
A3 = "0xAbCdEf0123456789abcdef0123456789abcdef01"


def test_takma_ad_sabit_liste_ve_bilinen_adresler():
    # Liste sırası/içeriği değişirse tüm takma adlar kayar: bu test onu yakalar.
    assert len(KELIMELER) == 110 and len(set(KELIMELER)) == 110
    assert (KELIMELER[0], KELIMELER[1], KELIMELER[-1]) == ("Kartal", "Şahin", "Fenrir")
    assert takma_ad(A1) == "Lemur-78"
    assert takma_ad(A2) == "Kuzgun-12"
    assert takma_ad(A3) == "Kanguru-AB"


def test_takma_ad_kararli_ve_buyuk_kucuk_harf_duyarsiz():
    assert takma_ad(A3) == takma_ad(A3.lower()) == takma_ad(A3.upper().replace("0X", "0x"))
    assert takma_ad(A1) == takma_ad(A1)


def test_takma_ad_gecersizde_kisa_bicim():
    assert takma_ad("") == ""
    assert takma_ad("abcdefghijkl") == "abcdefgh…"
    assert takma_ad("xyz") == "xyz"
    assert kisa_adres(A1) == "0x78aabb…"


def test_telegram_acildi_kapandi_takma_ad_gosterir_adres_yok():
    m1 = tg.msg_acildi(A1, "BTC", "B", 100.0, 50.0, 95.0, "sanal")
    m2 = tg.msg_kapandi(A1, "BTC", 1.5, 0.03, "", "sanal")
    for m in (m1, m2):
        assert "trader Lemur-78" in m and A1[:8] not in m and A1 not in m
