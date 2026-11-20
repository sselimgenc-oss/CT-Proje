"""K-77 (kullanıcı kararı 20.11, beyin fırtınası): zarar ettiren trader önce KÜÇÜLTÜLÜR. Kopyaladığımız tam kapanmış pozisyonlar (pozisyon bazında net) >= 5 ve toplam net < 0 → yeni açılış ×0,5;
>= 10 ve net hâlâ < 0 → en küçük boyut (asgari emir 11 $); net >= 0 → ×1. `kopya_zarar` radar elemesi değişmez. Ağsız. Kasa 1.000 → slot 90,909 $; trader hesap 100.000 $, BTC 100 $ (ask 100 / bid 99,9)."""
from __future__ import annotations

import pytest

from copytrade import radar_tarama
from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from copytrade.canli.hesap import Hesap
from copytrade.kurallar import load_rules
from tests.test_canli_motor import adr, kayitlar, kur, olay

A = adr(1)
ACILIS_USD = 27.2727            # 300 BTC × 100 $ / 100.000 $ × slot 90,909 $


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _hazir(tmp_path, **k):
    m, hl, saat, tgp = kur(tmp_path, kurallar={"canli_telegram_sanal_ozet_dk": 0}, **k)
    m.baslat()
    return m, hl, saat, tgp


class _Tur:
    """Bir tam round trip (aç → trader kapatır). `bid` kapanış fiyatı: 99,9 (varsayılan) = zarar, yüksek = kâr."""
    def __init__(self, m, hl, saat, bas=0):
        self.m, self.hl, self.saat, self.i = m, hl, saat, bas

    def __call__(self, bid="99.9"):
        self.i += 1
        m, saat = self.m, self.saat
        saat.ms += 10_000
        m.piyasa_oku(saat())
        s0 = m.olay_isle(olay(f"o:{self.i}", A, "BTC", "B", 300, 100.0, 0.0, saat))
        self.hl.kitaplar["BTC"]["levels"] = [[{"px": bid, "sz": "1000"}], [{"px": str(float(bid) + 0.1), "sz": "1000"}]]     # kapanış fiyatı (kâr turunda mark da buna gider)
        self.hl.mids["BTC"] = bid
        saat.ms += 10_000
        m.piyasa_oku(saat())
        s1 = m.olay_isle(olay(f"c:{self.i}", A, "BTC", "A", 300, float(bid), 300.0, saat))
        self.hl.kitaplar["BTC"]["levels"] = [[{"px": "99.9", "sz": "1000"}], [{"px": "100", "sz": "1000"}]]
        self.hl.mids["BTC"] = "100"
        return s0, s1


def _acilis_usd(tmp_path):
    return [e for e in kayitlar(tmp_path, "emir") if not e["reduce_only"]][-1]["usd_istenen"]


def test_yaml_varsayilanlari():
    r = load_rules()
    assert (r["trader_zarar_kucult_n1"], r["trader_zarar_kucult_carpan1"], r["trader_zarar_kucult_n2"]) == (5, 0.5, 10)


def test_dort_zararda_degismez_besinci_zararli_kapanista_yari(tmp_path):
    m, hl, saat, tgp = _hazir(tmp_path)
    tur = _Tur(m, hl, saat)
    for _ in range(4):
        tur()
        assert m.hesap.kucult_seviye(A, saat(), 7 * 86_400_000, 5, 10)[0] == 0
    assert _acilis_usd(tmp_path) == pytest.approx(ACILIS_USD, abs=1e-3)
    assert not kayitlar(tmp_path, "trader_kucult")
    tur()                                                                           # 5. zararlı kapanış
    olaylar = kayitlar(tmp_path, "trader_kucult")
    assert len(olaylar) == 1 and (olaylar[0]["adres"], olaylar[0]["eski"], olaylar[0]["yeni"], olaylar[0]["n"]) == (A, 0, 1, 5) and olaylar[0]["net"] < 0
    tur()                                                                           # 6. tur: açılış ½
    emir = [e for e in kayitlar(tmp_path, "emir") if not e["reduce_only"]][-1]
    assert emir["usd_istenen"] == pytest.approx(ACILIS_USD / 2, abs=1e-3) and emir["kucult_seviye"] == 1
    assert len(kayitlar(tmp_path, "trader_kucult")) == 1                            # değişmedi: olay tekrarlanmaz
    assert not any("küçült" in x.lower() for x in tgp.ham)                          # ayrı Telegram mesajı YOK


def test_onda_en_kucuk_boyut(tmp_path):
    m, hl, saat, _ = _hazir(tmp_path)
    tur = _Tur(m, hl, saat)
    for _ in range(10):
        tur()
    assert m.hesap.kucult[A] == 2
    assert [(e["eski"], e["yeni"]) for e in kayitlar(tmp_path, "trader_kucult")] == [(0, 1), (1, 2)]
    tur()
    emir = [e for e in kayitlar(tmp_path, "emir") if not e["reduce_only"]][-1]
    assert emir["usd_istenen"] == pytest.approx(float(load_rules()["radar_min_emir_usd"])) and emir["boyut_neden"] == "trader_en_kucuk"
    assert m.saha.uyeler.get(A) is not None                                         # eleme yok: `kopya_zarar` kendi (radar) yolunda


def test_kara_donunce_carpan_bire_doner(tmp_path):
    m, hl, saat, _ = _hazir(tmp_path)
    tur = _Tur(m, hl, saat)
    for _ in range(10):
        tur()
    assert m.hesap.kucult[A] == 2
    tur(bid="130")                                                                  # en küçük boyutta büyük kâr: toplam net >= 0
    assert m.hesap.kapanan_ozet(A, saat(), 7 * 86_400_000)[1] >= 0
    assert A not in m.hesap.kucult
    assert kayitlar(tmp_path, "trader_kucult")[-1]["yeni"] == 0
    tur()
    assert _acilis_usd(tmp_path) == pytest.approx(ACILIS_USD, abs=1e-3)


def test_yeniden_baslatmada_durum_korunur(tmp_path):
    m, hl, saat, _ = _hazir(tmp_path)
    tur = _Tur(m, hl, saat)
    for _ in range(5):
        tur()
    assert m.hesap.kucult[A] == 1
    h2 = Hesap.from_json(m.hesap.to_json())
    assert h2.kucult == {A: 1} and len(h2.kapanan[A]) == 5
    assert h2.kapanan_ozet(A, saat(), 7 * 86_400_000) == pytest.approx(m.hesap.kapanan_ozet(A, saat(), 7 * 86_400_000))
    m2, _, _, _ = kur(tmp_path, hl=hl, saat=saat, kurallar={"canli_telegram_sanal_ozet_dk": 0})
    m2.baslat()
    assert m2.hesap.kucult == {A: 1} and len(m2.hesap.kapanan[A]) == 5
    n_olay = len(kayitlar(tmp_path, "trader_kucult"))
    _Tur(m2, hl, saat, 100)()
    assert len(kayitlar(tmp_path, "trader_kucult")) == n_olay                       # yeniden başlatma sahte olay üretmez
    emir = [e for e in kayitlar(tmp_path, "emir") if not e["reduce_only"]][-1]
    assert emir["usd_istenen"] == pytest.approx(ACILIS_USD / 2, abs=1e-3)


def test_pencere_disi_kapanislar_sayilmaz(tmp_path):
    h = Hesap(1000.0)
    gun = 86_400_000
    h.kapanan[A] = [[i * 1000, -1.0] for i in range(10)]                            # çok eski 10 zarar
    assert h.kucult_seviye(A, 30 * gun, 7 * gun, 5, 10) == (0, 0, 0.0)
    h.kapanan[A] += [[29 * gun + i, -1.0] for i in range(5)]
    assert h.kucult_seviye(A, 30 * gun, 7 * gun, 5, 10)[0] == 1


def test_azaltma_acilis_carpanini_kullanir(tmp_path):
    m, hl, saat, _ = _hazir(tmp_path, kasa=10000.0)         # slot 909 $: yarı boyutta %50 azaltma asgari emrin (11 $) altına düşmesin
    tur = _Tur(m, hl, saat)
    for _ in range(5):
        tur()
    saat.ms += 10_000
    m.piyasa_oku(saat())
    m.olay_isle(olay("x:1", A, "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.hesap.poz[A]["BTC"].boyut_carpan == pytest.approx(0.5)
    ilk = m.hesap.sz(A, "BTC")
    saat.ms += 10_000
    m.piyasa_oku(saat())
    m.olay_isle(olay("x:2", A, "BTC", "A", 150, 100.0, 300.0, saat))               # trader %50 azaltır → biz de ~%50
    assert m.hesap.sz(A, "BTC") == pytest.approx(ilk / 2, rel=0.05)


def test_kopya_zarar_elemesi_degismedi():
    assert "kopya_zarar" in radar_tarama.R1_SIRA if hasattr(radar_tarama, "R1_SIRA") else True
    kaynak = open(radar_tarama.__file__, encoding="utf-8").read()
    assert '("kopya_zarar", basarisiz(satir.get("kopya_getiri_7g"), lambda v: v > 0))' in kaynak


def test_ozet_satiri():
    assert tg.kucult_satiri([]) == ""
    s = tg.kucult_satiri([{"adres": A, "eski": 0, "yeni": 1, "n": 5, "net": -3.2}])
    assert "½" in s and "5 kapanış" in s and "\n" not in s
    assert "en küçük" in tg.kucult_satiri([{"adres": A, "eski": 1, "yeni": 2, "n": 10, "net": -4.0}])
    assert "geri ×1" in tg.kucult_satiri([{"adres": A, "eski": 2, "yeni": 0, "n": 11, "net": 1.0}])
    assert "Zarar küçültme" in tg.msg_sanal_saatlik(0, 1, 60, [{"eylem": "ac", "durum": "dolu"}], {}, kucult_satir=s)
