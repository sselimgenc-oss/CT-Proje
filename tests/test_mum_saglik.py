"""`copytrade/mum_saglik.py` testleri (Argon A15 altın örnekleri + oranla sıçrama/çöküş, geçerli mum medyanı) ve defter/kapı bağlantıları."""
from __future__ import annotations

import unittest

from copytrade.kurallar import load_rules
from copytrade.mum_saglik import BIR_SAAT_MS, isaret_yasi as _isaret_yasi, mum_kontrol as _mum_kontrol, ozet

KURALLAR = load_rules()


def mum_kontrol(mumlar, sicrama_kat=None, pencere=None):
    return _mum_kontrol(mumlar, KURALLAR["mum_sicrama_kat"] if sicrama_kat is None else sicrama_kat, KURALLAR["mum_medyan_pencere"] if pencere is None else pencere)


def isaret_yasi(mumlar, an_ms):
    return _isaret_yasi(mum_kontrol(mumlar), an_ms)


class TestMumSaglik(unittest.TestCase):
    def _ornek_mum(
        self,
        t: int = 1_000_000,
        o: str = "100.0",
        c: str = "100.0",
        h: str = "105.0",
        l: str = "95.0",
        v: str = "10.0",
        n: int = 5,
        s: str = "BTC",
        i: str = "1h",
    ) -> dict:
        return {
            "t": t,
            "T": t + BIR_SAAT_MS - 1,
            "s": s,
            "i": i,
            "o": o,
            "c": c,
            "h": h,
            "l": l,
            "v": v,
            "n": n,
        }

    # 1. Altın Örnekler
    def test_altin_ornek_bozuk_h_kucuk_l(self):
        mum = self._ornek_mum(h="90.0", l="100.0")
        sonuclar = mum_kontrol([mum])
        self.assertEqual(len(sonuclar), 1)
        self.assertIn("bozuk", sonuclar[0]["sorunlar"])
        self.assertFalse(sonuclar[0]["gecerli"])

    def test_altin_ornek_bozuk_acilis_aralik_disi(self):
        mum1 = self._ornek_mum(o="110.0", h="105.0", l="95.0", c="100.0")
        sonuc1 = mum_kontrol([mum1])[0]
        self.assertIn("bozuk", sonuc1["sorunlar"])
        self.assertFalse(sonuc1["gecerli"])

        mum2 = self._ornek_mum(o="90.0", h="105.0", l="95.0", c="100.0")
        sonuc2 = mum_kontrol([mum2])[0]
        self.assertIn("bozuk", sonuc2["sorunlar"])
        self.assertFalse(sonuc2["gecerli"])

    def test_altin_ornek_bozuk_kapanis_aralik_disi(self):
        mum1 = self._ornek_mum(c="110.0", h="105.0", l="95.0", o="100.0")
        sonuc1 = mum_kontrol([mum1])[0]
        self.assertIn("bozuk", sonuc1["sorunlar"])
        self.assertFalse(sonuc1["gecerli"])

        mum2 = self._ornek_mum(c="90.0", h="105.0", l="95.0", o="100.0")
        sonuc2 = mum_kontrol([mum2])[0]
        self.assertIn("bozuk", sonuc2["sorunlar"])
        self.assertFalse(sonuc2["gecerli"])

    def test_altin_ornek_bozuk_sayi_degil(self):
        for val in ["abc", "", "nan", "inf", "-inf", None]:
            mum = self._ornek_mum(o=val)
            sonuc = mum_kontrol([mum])[0]
            self.assertIn("bozuk", sonuc["sorunlar"])
            self.assertFalse(sonuc["gecerli"])

    def test_altin_ornek_sicrama(self):
        t0 = 1_000_000
        mumlar = [
            self._ornek_mum(t=t0, o="100.0", c="100.0", h="105.0", l="95.0"),
            self._ornek_mum(t=t0 + BIR_SAAT_MS, o="100.0", c="100.0", h="105.0", l="95.0"),
            self._ornek_mum(t=t0 + 2 * BIR_SAAT_MS, o="100.0", c="100.0", h="105.0", l="95.0"),
            self._ornek_mum(t=t0 + 3 * BIR_SAAT_MS, o="500.0", c="500.0", h="505.0", l="495.0"),
        ]
        sonuclar = mum_kontrol(mumlar, sicrama_kat=2.0, pencere=3)
        self.assertEqual(len(sonuclar), 4)
        for s in sonuclar[:3]:
            self.assertEqual(s["sorunlar"], [])
            self.assertTrue(s["gecerli"])
        self.assertIn("sicrama", sonuclar[3]["sorunlar"])
        self.assertFalse(sonuclar[3]["gecerli"])

    def test_altin_ornek_bosluk(self):
        t0 = 1_000_000
        mumlar = [
            self._ornek_mum(t=t0),
            self._ornek_mum(t=t0 + 2 * BIR_SAAT_MS),
        ]
        sonuclar = mum_kontrol(mumlar)
        self.assertEqual(len(sonuclar), 2)
        self.assertTrue(sonuclar[0]["gecerli"])
        self.assertIn("bosluk", sonuclar[1]["sorunlar"])
        self.assertFalse(sonuclar[1]["gecerli"])

    def test_altin_ornek_bosluk_yok_tam_bir_saat(self):
        t0 = 1_000_000
        mumlar = [
            self._ornek_mum(t=t0),
            self._ornek_mum(t=t0 + BIR_SAAT_MS),
        ]
        sonuclar = mum_kontrol(mumlar)
        self.assertEqual(sonuclar[0]["sorunlar"], [])
        self.assertEqual(sonuclar[1]["sorunlar"], [])

    def test_altin_ornek_hacimsiz(self):
        mum1 = self._ornek_mum(v="0.0", n=0)
        self.assertIn("hacimsiz", mum_kontrol([mum1])[0]["sorunlar"])

        mum2 = self._ornek_mum(v="0", n=0)
        self.assertIn("hacimsiz", mum_kontrol([mum2])[0]["sorunlar"])

        mum3 = self._ornek_mum(v="10.0", n=0)
        self.assertNotIn("hacimsiz", mum_kontrol([mum3])[0]["sorunlar"])

        mum4 = self._ornek_mum(v="0.0", n=3)
        self.assertNotIn("hacimsiz", mum_kontrol([mum4])[0]["sorunlar"])

    # 2. Sıralanmamış Girdi
    def test_siralanmamis_girdi(self):
        t0 = 10_000_000
        m0 = self._ornek_mum(t=t0)
        m1 = self._ornek_mum(t=t0 + BIR_SAAT_MS)
        m2 = self._ornek_mum(t=t0 + 3 * BIR_SAAT_MS)

        karisik = [m2, m0, m1]
        sonuclar = mum_kontrol(karisik)
        self.assertEqual([s["t"] for s in sonuclar], [m0["t"], m1["t"], m2["t"]])
        self.assertTrue(sonuclar[0]["gecerli"])
        self.assertTrue(sonuclar[1]["gecerli"])
        self.assertIn("bosluk", sonuclar[2]["sorunlar"])

    # 3. Boş Liste
    def test_bos_liste(self):
        self.assertEqual(mum_kontrol([]), [])
        self.assertIsNone(isaret_yasi([], 1_000_000))
        o = ozet([])
        self.assertEqual(o["bozuk"], 0)
        self.assertEqual(o["gecerli_orani"], 0.0)

    # 4. Tek Mum
    def test_tek_mum_gecerli(self):
        mum = self._ornek_mum(t=5_000_000)
        sonuclar = mum_kontrol([mum])
        self.assertEqual(len(sonuclar), 1)
        self.assertTrue(sonuclar[0]["gecerli"])
        self.assertEqual(isaret_yasi([mum], 6_500_000), 1_500_000)
        self.assertIsNone(isaret_yasi([mum], 4_000_000))

    def test_tek_mum_bozuk(self):
        mum = self._ornek_mum(h="50.0", l="100.0")
        sonuclar = mum_kontrol([mum])
        self.assertEqual(sonuclar[0]["sorunlar"], ["bozuk"])
        self.assertFalse(sonuclar[0]["gecerli"])
        self.assertIsNone(isaret_yasi([mum], 2_000_000))

    def test_tek_mum_hacimsiz(self):
        mum = self._ornek_mum(v="0", n=0)
        sonuclar = mum_kontrol([mum])
        self.assertEqual(sonuclar[0]["sorunlar"], ["hacimsiz"])
        self.assertFalse(sonuclar[0]["gecerli"])

    # 5. Ek Senaryolar
    def test_ayni_mumda_birden_fazla_sorun(self):
        t0 = 1_000_000
        m1 = self._ornek_mum(t=t0)
        m2 = self._ornek_mum(t=t0 + 3 * BIR_SAAT_MS, v="0.0", n=0)
        sonuclar = mum_kontrol([m1, m2])
        self.assertIn("bosluk", sonuclar[1]["sorunlar"])
        self.assertIn("hacimsiz", sonuclar[1]["sorunlar"])

    def test_isaret_yasi_son_gecerli_mumu_bulma(self):
        t0 = 1_000_000
        m0 = self._ornek_mum(t=t0)
        m1 = self._ornek_mum(t=t0 + BIR_SAAT_MS, h="10.0", l="100.0")
        an = t0 + 2 * BIR_SAAT_MS
        self.assertEqual(isaret_yasi([m0, m1], an), 2 * BIR_SAAT_MS)

    def test_isaret_yasi_gecerli_mum_yoksa(self):
        m0 = self._ornek_mum(h="10.0", l="100.0")
        self.assertIsNone(isaret_yasi([m0], 5_000_000))

    def test_ozet_hesaplama_ve_anahtar_erisimleri(self):
        t0 = 1_000_000
        mumlar = [
            self._ornek_mum(t=t0),
            self._ornek_mum(t=t0 + BIR_SAAT_MS, v="0", n=0),
            self._ornek_mum(t=t0 + 2 * BIR_SAAT_MS, h="10.0", l="100.0"),
            self._ornek_mum(t=t0 + 5 * BIR_SAAT_MS),
        ]
        sonuclar = mum_kontrol(mumlar)
        o = ozet(sonuclar)

        self.assertEqual(o["bozuk"], 1)
        self.assertEqual(o["sicrama"], 0)
        self.assertEqual(o["bosluk"], 1)
        self.assertEqual(o["hacimsiz"], 1)
        self.assertEqual(o["gecerli_orani"], 0.25)




# ---------------------------------------------------------------- A15 düzeltmeleri


def _mum(t, o, h=None, l=None, c=None):
    return {"t": t, "T": t + BIR_SAAT_MS - 1, "s": "BTC", "i": "1h", "o": str(o), "c": str(c if c is not None else o),
            "h": str(h if h is not None else o + 1), "l": str(l if l is not None else o - 1), "v": "10", "n": 5}


def test_sicrama_oranla_olculur_cokusler_de_yakalanir():
    """Medyan 100, kat 2: 200 (×2,00) ve 50 (÷2,00) sıçrama; 199 (×1,99) ve 51 (÷1,96) değil. Eski mutlak kural |o−medyan| ≥ 2·medyan çöküşü hiç yakalamazdı."""
    base = [_mum(i * BIR_SAAT_MS, 100) for i in range(3)]
    for price, flagged in ((200, True), (50, True), (199, False), (51, False), (500, True), (10, True)):
        res = mum_kontrol(base + [_mum(3 * BIR_SAAT_MS, price, h=price + 1, l=price - 1)], sicrama_kat=2.0, pencere=3)
        assert ("sicrama" in res[-1]["sorunlar"]) is flagged, price


def test_medyana_yalniz_gecerli_mumlarin_kapanisi_girer():
    """Bozuk bir mumun (h<l) kapanışı 1000 medyanı bozmamalı; sıçrama mumunun kapanışı (500) da girmemeli: sonraki 100 normal kalır."""
    mumlar = [_mum(0, 100), _mum(BIR_SAAT_MS, 100), _mum(2 * BIR_SAAT_MS, 100, h=90, l=110, c=1000),      # bozuk, kapanış 1000
              _mum(3 * BIR_SAAT_MS, 100), _mum(4 * BIR_SAAT_MS, 500), _mum(5 * BIR_SAAT_MS, 100)]
    res = mum_kontrol(mumlar, sicrama_kat=2.0, pencere=24)
    assert [r["sorunlar"] for r in res] == [[], [], ["bozuk"], [], ["sicrama"], []]


def test_pozitif_olmayan_fiyat_bozuktur_ve_sifira_bolmez():
    res = mum_kontrol([_mum(0, 100), _mum(BIR_SAAT_MS, 0, h=1, l=0)], sicrama_kat=2.0, pencere=24)
    assert res[1]["sorunlar"] == ["bozuk"]


def test_yaml_esikleri():
    assert KURALLAR["mum_sicrama_kat"] == 2.0 and KURALLAR["mum_medyan_pencere"] == 24


def test_ozet_duz_sozluk_ve_tek_anahtar():
    res = mum_kontrol([_mum(0, 100), _mum(BIR_SAAT_MS, 100, h=90, l=110)])
    assert ozet(res) == {"bozuk": 1, "sicrama": 0, "bosluk": 0, "hacimsiz": 0, "gecerli_orani": 0.5} and type(ozet(res)) is dict
