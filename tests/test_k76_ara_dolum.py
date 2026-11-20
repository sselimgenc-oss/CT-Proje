"""K-76 (kullanıcı kararı 20.11, beyin fırtınası): kopyalama = trader pozisyonunun İLK AÇILIŞI + İLK 2 ARA DOLUMU + TAM KAPANIŞI. 3. ve sonraki ara dolumlar (artır ya da azalt) alınmaz
(`emir_yok` / `ara_dolum_siniri`); kapanış her zaman alınır; senkron atlananı geri getirmez. Ağsız. Kasa 1.000 → slot 90,909 $; trader hesap 100.000 $, BTC 100 $."""
from __future__ import annotations

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from copytrade.kurallar import load_rules
from tests.test_canli_motor import adr, kayitlar, kur, olay

A = adr(1)


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _hazir(tmp_path, **k):
    m, hl, saat, tgp = kur(tmp_path, **k)
    m.baslat()
    return m, hl, saat


def _dolum(m, saat, kimlik, yon, sz, bas, ileri_ms=10_000):
    """Trader dolumu: saat ileri alınır (her dolum ayrı ms kümesi; aynı küme için ileri_ms=0), mark güncellenir."""
    saat.ms += ileri_ms
    m.piyasa_oku(saat())
    return m.olay_isle(olay(kimlik, A, "BTC", yon, sz, 100.0, bas, saat, yas_ms=0 if ileri_ms == 0 else 1000))


def _uc_ara(m, saat):
    """Açılış 300; ara dolumlar: +200 (1.), +200 (2.), +200 (3., alınmaz). Trader 900 BTC."""
    s0 = _dolum(m, saat, "a:1", "B", 300, 0.0)
    s1 = _dolum(m, saat, "a:2", "B", 200, 300.0)
    s2 = _dolum(m, saat, "a:3", "B", 200, 500.0)
    s3 = _dolum(m, saat, "a:4", "B", 200, 700.0)
    return s0, s1, s2, s3


def test_yaml_varsayilani():
    assert load_rules()["kopya_ara_dolum_max"] == 2


def test_ilk_iki_ara_dolum_kopyalanir_ucuncu_artir_alinmaz(tmp_path):
    m, _, saat = _hazir(tmp_path)
    s0, s1, s2, s3 = _uc_ara(m, saat)
    assert [(x.eylem, x.karar) for x in s0] == [("ac", "emir")]
    assert [(x.eylem, x.karar) for x in s1] == [("artir", "emir")]                 # 1. ara dolum
    assert [(x.eylem, x.karar) for x in s2] == [("artir", "emir")]                 # 2. ara dolum
    biz = m.hesap.sz(A, "BTC")
    assert [(x.eylem, x.karar, x.neden) for x in s3] == [("artir", "atlandi", "ara_dolum_siniri")]
    assert m.hesap.sz(A, "BTC") == biz                                              # 3. artır: emir yok
    y = [e for e in kayitlar(tmp_path, "emir_yok") if e["neden"] == "ara_dolum_siniri"]
    assert len(y) == 1 and y[0]["eylem"] == "artir" and y[0]["karar"] == "atlandi"
    assert m.neden_say["ara_dolum_siniri"] == 1
    assert not m.karsi_olgu and not kayitlar(tmp_path, "karsi_olgu_hata")           # karşı-olgu ölçülmez


def test_ucuncu_azalt_alinmaz(tmp_path):
    m, _, saat = _hazir(tmp_path)
    _dolum(m, saat, "a:1", "B", 300, 0.0)
    _dolum(m, saat, "a:2", "B", 200, 300.0)
    s2 = _dolum(m, saat, "a:3", "B", 200, 500.0)
    assert s2[0].karar == "emir"
    biz = m.hesap.sz(A, "BTC")
    s3 = _dolum(m, saat, "a:4", "A", 400, 700.0)                                    # 3. ara dolum = azaltma
    assert [(x.eylem, x.karar, x.neden) for x in s3] == [("azalt", "atlandi", "ara_dolum_siniri")]
    assert m.hesap.sz(A, "BTC") == biz


def test_azaltma_da_ilk_iki_icinde_kopyalanir(tmp_path):
    m, _, saat = _hazir(tmp_path)
    _dolum(m, saat, "a:1", "B", 300, 0.0)
    s = _dolum(m, saat, "a:2", "A", 150, 300.0)                                     # 1. ara dolum (azalt)
    assert [(x.eylem, x.karar) for x in s] == [("azalt", "emir")]


def test_tam_kapanis_atlananlara_ragmen_tamamen_kapatir(tmp_path):
    m, _, saat = _hazir(tmp_path)
    _uc_ara(m, saat)
    _dolum(m, saat, "a:5", "B", 200, 900.0)                                         # 4. ara dolum: alınmaz
    assert m.hesap.sz(A, "BTC") > 0
    s = _dolum(m, saat, "a:6", "A", 1100, 1100.0)                                   # trader tam kapatır
    assert [(x.eylem, x.karar) for x in s] == [("kapat", "emir")]
    assert abs(m.hesap.sz(A, "BTC")) < mt.EPS
    e = kayitlar(tmp_path, "emir")[-1]
    assert e["eylem"] == "kapat" and e["reduce_only"] is True
    assert f"{A}|BTC" not in m.ara_dolum                                            # sayaç sıfırlandı


def test_yon_donusu_sayaci_sifirlar(tmp_path):
    m, _, saat = _hazir(tmp_path)
    _uc_ara(m, saat)
    assert m.ara_dolum[f"{A}|BTC"]["n"] == 3
    s = _dolum(m, saat, "a:5", "A", 1200, 900.0)                                    # 900 → −300: kapat + yeni açılış (short)
    assert [x.eylem for x in s] == ["kapat", "ac"] and s[0].karar == "emir"
    assert m.ara_dolum[f"{A}|BTC"]["n"] == 0
    assert m.hesap.sz(A, "BTC") < 0
    s2 = _dolum(m, saat, "a:6", "A", 200, -300.0)                                   # yeni pozisyonun 1. ara dolumu: alınır
    assert [(x.eylem, x.karar) for x in s2] == [("artir", "emir")]
    assert m.ara_dolum[f"{A}|BTC"]["n"] == 1


def test_yeniden_baslatmada_sayac_korunur(tmp_path):
    m, hl, saat = _hazir(tmp_path)
    _dolum(m, saat, "a:1", "B", 300, 0.0)
    _dolum(m, saat, "a:2", "B", 200, 300.0)
    _dolum(m, saat, "a:3", "B", 200, 500.0)
    m.durum_yaz()
    hl.pozlar = {A: {"BTC": 700.0}}
    m2, _, _, _ = kur(tmp_path, hl=hl, saat=saat)
    m2.baslat()
    assert m2.ara_dolum[f"{A}|BTC"]["n"] == 2
    saat.ms += 10_000
    m2.piyasa_oku(saat())
    s = m2.olay_isle(olay("a:4", A, "BTC", "B", 200, 100.0, 700.0, saat))
    assert [(x.eylem, x.karar, x.neden) for x in s] == [("artir", "atlandi", "ara_dolum_siniri")]


def test_parcali_dolum_tek_ara_dolum_sayilir(tmp_path):
    """Aynı yön + aynı ms kümesindeki dolumlar (bir emrin parçaları) tek ara dolumdur; açılış emrinin ardışık parçaları ara dolum sayılmaz."""
    m, _, saat = _hazir(tmp_path)
    _dolum(m, saat, "a:1", "B", 200, 0.0)                                           # açılışın 1. parçası
    _dolum(m, saat, "a:2", "B", 100, 200.0, ileri_ms=0)                             # aynı ms: açılışın 2. parçası (ara dolum DEĞİL)
    assert m.ara_dolum[f"{A}|BTC"]["n"] == 0
    _dolum(m, saat, "a:3", "B", 100, 300.0)                                         # 1. ara dolum, 1. parça
    s = _dolum(m, saat, "a:4", "B", 100, 400.0, ileri_ms=0)                         # aynı ms: aynı ara dolum
    assert m.ara_dolum[f"{A}|BTC"]["n"] == 1 and all(x.neden != "ara_dolum_siniri" for x in s)
    _dolum(m, saat, "a:5", "B", 100, 500.0)                                         # 2.
    assert m.ara_dolum[f"{A}|BTC"]["n"] == 2
    s3 = _dolum(m, saat, "a:6", "B", 100, 600.0)                                    # 3.: alınmaz
    s3b = _dolum(m, saat, "a:7", "B", 100, 700.0, ileri_ms=0)                       # 3.'nün 2. parçası: o da alınmaz
    assert [x.neden for x in s3] == ["ara_dolum_siniri"] and [x.neden for x in s3b] == ["ara_dolum_siniri"]
    assert m.ara_dolum[f"{A}|BTC"]["n"] == 3


def test_senkron_atlananı_geri_getirmez_ve_kapanis_alir(tmp_path):
    m, hl, saat = _hazir(tmp_path)
    _uc_ara(m, saat)
    biz = m.hesap.sz(A, "BTC")
    n_emir = len(kayitlar(tmp_path, "emir"))
    hl.pozlar = {A: {"BTC": 900.0}}                                                 # REST: trader 900 (izlenenle aynı)
    m.senkron_uygula(m.senkron_oku())
    assert m.hesap.sz(A, "BTC") == biz and len(kayitlar(tmp_path, "emir")) == n_emir
    hl.pozlar = {A: {"BTC": 800.0}}                                                 # kaçan kısmi azaltma (3.+ ara dolum): senkron da AZALTMAZ
    m.senkron_uygula(m.senkron_oku())
    assert m.hesap.sz(A, "BTC") == biz and len(kayitlar(tmp_path, "emir")) == n_emir
    assert kayitlar(tmp_path, "senkron_azalt")[-1]["neden"] == "ara_dolum_siniri"
    hl.pozlar = {A: {}}                                                             # trader kapattı (kapanış kaçtı): senkron tam kapatır
    m.senkron_uygula(m.senkron_oku())
    assert abs(m.hesap.sz(A, "BTC")) < mt.EPS and f"{A}|BTC" not in m.ara_dolum


def test_senkron_kaçan_ilk_azaltmayi_yine_yapar_ve_say(tmp_path):
    """Sınır dolmadıysa senkron azaltması eskisi gibi çalışır (ara dolum olarak sayılır)."""
    m, hl, saat = _hazir(tmp_path)
    _dolum(m, saat, "a:1", "B", 300, 0.0)
    biz = m.hesap.sz(A, "BTC")
    hl.pozlar = {A: {"BTC": 150.0}}
    m.senkron_uygula(m.senkron_oku())
    assert m.hesap.sz(A, "BTC") < biz and m.ara_dolum[f"{A}|BTC"]["n"] == 1


def test_etiket_ve_veri_sozlesmesi():
    assert tg.ATLA_TR["ara_dolum_siniri"] == "ara dolum sınırı (ilk 2 sonrası)"
    assert tg.atla_etiket("ara_dolum_siniri") == "ara dolum sınırı (ilk 2 sonrası)"
