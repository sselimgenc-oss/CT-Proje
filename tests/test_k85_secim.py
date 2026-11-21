"""K-85 (21.11) CT yeni sade seçim: 30 günlük kurallar (radar_tarama), kadro durum makinesi (radar_kadro), motorun sade kadro okuması (canli/kadro.Saha).
Ağsız: sahte HL istemcisi; kopya oynatma sahte (hesabı kopya_v5 testlerinde)."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from copytrade import radar_kadro as rk
from copytrade import radar_tarama as r
from copytrade.canli import kadro as kd
from copytrade.defter import HOUR
from copytrade.kurallar import load_rules

RULES = load_rules()
GUN = 24 * HOUR
KOSU = int(datetime(2026, 11, 23, 0, 37, tzinfo=UTC).timestamp() * 1000)          # Pazartesi (kontrol günü)
SALI = KOSU + GUN
DONEM = "2026-11-21T07:30:00Z"


def adr(i: int) -> str:
    return "0x" + f"{i:040x}"


def lider(a: str, hesap=50_000, hafta=500, ay=3_000) -> dict:
    return {"ethAddress": a, "accountValue": str(hesap), "windowPerformances": [["day", {"pnl": "0", "vlm": "1"}], ["week", {"pnl": str(hafta), "vlm": "1000"}], ["month", {"pnl": str(ay), "vlm": "5000"}]]}


def portfoy(pnl_gunluk: list[float], allt: list[tuple[int, float]] | None = None) -> list:
    """pnl_gunluk: KOSU'dan geriye 30 gün için günlük kümülatif pnl (31 nokta)."""
    n = len(pnl_gunluk)
    nokta = [[KOSU - (n - 1 - i) * GUN, str(v)] for i, v in enumerate(pnl_gunluk)]
    return [["month", {"pnlHistory": nokta, "accountValueHistory": [[t, str(50_000 + float(v))] for t, v in nokta]}],
            ["allTime", {"pnlHistory": [[t, str(v)] for t, v in (allt or [(KOSU - 200 * GUN, 0.0), (KOSU - 90 * GUN, 1_000.0), (KOSU, 5_000.0)])]}]]


KARLI = [i * 100.0 for i in range(31)]            # her hafta kârlı, düşüş yok, 30 g pnl 3.000


# ------------------------------------------------------------------------------------------------ yapılandırma
def test_k85_kural_anahtarlari_ve_silinenler():
    assert RULES["radar_coinler"] == ["BTC", "ETH", "BNB", "XRP", "SOL", "TRX"]
    assert (RULES["radar_min_hesap_usd"], RULES["radar_pencere_gun"], RULES["radar_max_dusus_30g"], RULES["radar_min_getiri_7g"]) == (25000, 30, 0.25, -0.05)
    assert (RULES["radar_coin_hacim_pay_min"], RULES["radar_coin_kar_pay_min"], RULES["radar_min_islem"], RULES["radar_max_acilis_hafta"]) == (0.80, 0.70, 8, 15)
    assert (RULES["radar_min_medyan_tutma_saat"], RULES["radar_max_kaldirac"], RULES["radar_kopya_koruma_min"], RULES["radar_siralama_dusus_taban"]) == (4.0, 10.0, 0.50, 0.05)
    assert (RULES["radar_kadro_n"], RULES["radar_kontrol_gunleri"], RULES["radar_degisim_azami"], RULES["radar_cikis_kopya_esigi"], RULES["radar_yasak_gun"], RULES["radar_cikanlar_saat"]) == (5, [0, 3], 2, -0.10, 14, 72)
    for silinen in ("radar_aday_tavan", "radar_agirlik_g", "radar_bootstrap_tekrar", "radar_max_devir_hafta", "radar_kisa_islem_payi_max", "radar_akil_sagligi_getiri_max", "radar_soguyor_saat",
                    "radar_kadro_toplam", "radar_tutma_onceki_kadro", "radar_likit_pay_min"):
        assert silinen not in RULES
    assert RULES["radar_surum"] == "v5" and rk.donem_oku() == DONEM


# ------------------------------------------------------------------------------------------------ evren / portfolio
def test_evren_tam_evren_hesap_ay_pnl_ve_7g_veto():
    tablo = [lider(adr(1)), lider(adr(2), hesap=24_999), lider(adr(3), ay=-1), lider(adr(4), hafta=-3_000, hesap=50_000), lider(adr(5), hafta=-2_380, hesap=50_000), lider(adr(6), ay=0)]
    adaylar, say = r.evren(tablo, RULES)
    # adr4: -3000/(53000) = -5,66% veto; adr5: -2380/52380 = -4,54% geçer
    assert [a["adres"] for a in adaylar] == [adr(1), adr(5)] and say == {"ay_pnl": 2, "getiri_7g_dusuk": 1, "hesap_dusuk": 1}
    assert len(r.evren([lider(adr(i)) for i in range(1, 1500)], RULES)[0]) == 1499                       # aday tavanı YOK


def test_portfoy_olculeri_kari_dusus_hafta_ve_90g():
    o = r.portfoy_olculeri(portfoy(KARLI), 53_000, KOSU, RULES)
    assert o["pnl_30g"] == 3000 and o["getiri_30g"] == pytest.approx(3000 / 50_000) and o["dusus_30g"] == 0 and o["hafta_karli"] == 4 and o["pnl_90g"] == 4_000
    # zirve 1.500 sonra 0'a düşüş (özsermaye 51.500 → 50.000): %2,91; son günlerde yeniden yükselir
    seri = [i * 100.0 for i in range(16)] + [1_500 - (i + 1) * 300 for i in range(5)] + [i * 150.0 for i in range(10)]
    o2 = r.portfoy_olculeri(portfoy(seri), 50_000 + seri[-1], KOSU, RULES)
    assert o2["dusus_30g"] == pytest.approx(1500 / 51_500)
    kayip_hafta = [0.0] * 31
    for i in range(31):
        kayip_hafta[i] = 100.0 * min(i, 14)         # son 16 gün sabit: son iki hafta kârsız (≤ 0)
    assert r.portfoy_olculeri(portfoy(kayip_hafta), 51_400, KOSU, RULES)["hafta_karli"] == 2
    # 90 g: hesap 90 günden gençse ölçülemez (None); 90 g pnl negatif yakalanır
    genc = r.portfoy_olculeri(portfoy(KARLI, [(KOSU - 40 * GUN, 0.0), (KOSU, 3_000.0)]), 53_000, KOSU, RULES)
    assert genc["pnl_90g"] is None
    assert r.portfoy_olculeri(portfoy(KARLI, [(KOSU - 200 * GUN, 0.0), (KOSU - 90 * GUN, 4_000.0), (KOSU, 3_000.0)]), 53_000, KOSU, RULES)["pnl_90g"] == -1_000
    assert r.portfoy_olculeri([], 50_000, KOSU, RULES)["pnl_30g"] is None


def test_skor_getiri_bolu_max_dusus_taban():
    assert r.skor_hesapla(0.10, 0.02, RULES) == pytest.approx(2.0)          # taban %5
    assert r.skor_hesapla(0.10, 0.20, RULES) == pytest.approx(0.5)
    assert r.skor_hesapla(None, 0.1, RULES) is None


# ------------------------------------------------------------------------------------------------ dolum ölçüleri
def dolumlar(coin: str, n: int, bas_ms: int, pnl: float = 50.0, tutma_saat: float = 6.0, aralik_saat: float = 24.0, sira0: int = 0) -> list[dict]:
    """n kapanan işlem: her biri al (aç) + sat (kapat), `tutma_saat` sonra."""
    cikti = []
    for i in range(n):
        t = bas_ms + int(i * aralik_saat * HOUR)
        cikti.append({"coin": coin, "px": "100", "sz": "10", "side": "B", "time": t, "startPosition": "0", "closedPnl": "0", "fee": "0.1", "tid": sira0 + 2 * i})
        cikti.append({"coin": coin, "px": "105", "sz": "10", "side": "A", "time": t + int(tutma_saat * HOUR), "startPosition": "10", "closedPnl": str(pnl), "fee": "0.1", "tid": sira0 + 2 * i + 1})
    return cikti


def test_acilis_sayisi_ve_ters_donus():
    f = dolumlar("BTC", 3, KOSU - 20 * GUN)
    assert r.acilis_sayisi(f) == 3
    donus = [{"coin": "BTC", "px": "1", "sz": "15", "side": "A", "time": 1, "startPosition": "10"}]       # +10 → −5: kapanış + yeni açılış; pencere başında açık olan pozisyon açılış sayılmaz
    assert r.acilis_sayisi(donus) == 1
    assert r.acilis_sayisi([{"coin": "BTC", "px": "1", "sz": "4", "side": "A", "time": 1, "startPosition": "10"}]) == 0


def test_dolum_olculeri_liste_paylari_tek_islem_tutma_ve_acilis():
    bas = KOSU - 29 * GUN
    f = dolumlar("BTC", 9, bas, pnl=50.0, tutma_saat=6) + dolumlar("DOGE", 1, bas + 12 * GUN, pnl=100.0, sira0=500)
    o = r.dolum_olculeri(f, 50_000, 550.0, RULES)
    assert o["islem_sayisi"] == 9 and o["medyan_tutma_saat"] == pytest.approx(6.0)
    # kâr payı: liste (9 × ~49,8) / toplam (9 × 49,8 + ~99,8)
    liste_kar, toplam_kar = 9 * 49.8, 9 * 49.8 + 99.8
    assert o["coin_kar_pay"] == pytest.approx(liste_kar / toplam_kar, rel=1e-6)
    notional = lambda n, px: n * 10 * px                              # noqa: E731
    assert o["coin_hacim_pay"] == pytest.approx(9 * (1000 + 1050) / (9 * 2050 + 2050))
    assert o["tek_islem_haric_pnl"] == pytest.approx(550.0 - 99.8)    # en büyük kazanan (DOGE) çıkarılır
    assert o["acilis_hafta"] == pytest.approx(9 / (30 / 7))
    assert notional(1, 100) == 1000


def test_pencere_basinda_acik_pozisyon_kapaninca_sayilir_tutma_bilinmez():
    f = [{"coin": "ETH", "px": "100", "sz": "10", "side": "A", "time": KOSU - 20 * GUN, "startPosition": "10", "closedPnl": "40", "fee": "0"}] + dolumlar("ETH", 2, KOSU - 10 * GUN, sira0=10)
    o = r.dolum_olculeri(f, 50_000, 100.0, RULES)
    assert o["islem_sayisi"] == 3 and o["medyan_tutma_saat"] == pytest.approx(6.0)          # 3 kapanan; bilinmeyen tutma medyana girmez


# ------------------------------------------------------------------------------------------------ kural sırası
def tam_satir(**ek) -> dict:
    s = {"adres": adr(1), "getiri_30g": 0.06, "pnl_30g": 3000.0, "pnl_90g": 4000.0, "hafta_karli": 3, "dusus_30g": 0.25, "getiri_7g": -0.05, "coin_hacim_pay": 0.80, "coin_kar_pay": 0.70, "tek_islem_haric_pnl": 1.0,
         "islem_sayisi": 8, "acilis_hafta": 15.0, "medyan_tutma_saat": 4.0, "max_kaldirac": 10.0, "kopya_getiri_30g": 0.01, "kopya_koruma": 0.50}
    s.update(ek)
    return s


def test_degerlendir_sinirlar_dahil_ve_her_kural_kendi_nedeniyle_eler():
    assert r.degerlendir(tam_satir(), RULES) == (True, None)
    elenecek = {"pnl_30g": ("ay_pnl", 0.0), "pnl_90g": ("pnl_90g", 0.0), "hafta_karli": ("hafta_karli", 2), "dusus_30g": ("dusus_yuksek", 0.2501), "getiri_7g": ("getiri_7g_dusuk", -0.0501),
                "coin_hacim_pay": ("coin_hacim", 0.79), "coin_kar_pay": ("coin_kar", 0.69), "tek_islem_haric_pnl": ("kar_tek_islem", 0.0), "islem_sayisi": ("islem_az", 7),
                "acilis_hafta": ("acilis_fazla", 15.01), "medyan_tutma_saat": ("tutma_kisa", 3.99), "max_kaldirac": ("kaldirac_yuksek", 10.01),
                "kopya_getiri_30g": ("kopya_zarar", 0.0), "kopya_koruma": ("kopya_koruma_dusuk", 0.49)}
    for alan, (neden, deger) in elenecek.items():
        assert r.degerlendir(tam_satir(**{alan: deger}), RULES) == (False, neden), alan
    assert r.degerlendir(tam_satir(pnl_90g=None), RULES) == (True, None)                      # 90 g ölçülemezse kural uygulanmaz
    assert r.degerlendir(tam_satir(medyan_tutma_saat=None), RULES) == (False, "tutma_kisa")   # ölçü yok = başarısız
    assert r.degerlendir(tam_satir(kopya_koruma=0.1), RULES, asama=r.ASAMA_DOLUM) == (True, None)
    assert r.degerlendir(tam_satir(hata="x"), RULES) == (False, "veri_hatasi")
    assert "kisa_islem_fazla" not in r.NEDENLER and "sans_riski" not in r.NEDENLER and "devir_yuksek" not in r.NEDENLER        # silinen kurallar


class Baglamsiz:
    """kopyalanabilirlik için sahte bağlam (kopya oynatma sabit sonuç)."""
    def __init__(self, getiri=0.02, ayna=0.03, giris=-0.004):
        self.rules, self.kosu_ms, self.pencere_bas_ms = RULES, KOSU, KOSU - 30 * GUN
        self.cagri: list = []
        self._g = (getiri, ayna, giris)

    def kopya_oynat(self, dolumlar, payda, bas_ms=None):
        self.cagri.append((len(dolumlar), bas_ms))
        g = self._g[0] if bas_ms is None else self._g[2]
        return {"getiri": g, "ayna": {"getiri": self._g[1]}, "baslangic_usd": 1000.0, "slot_usd": 200.0}


def aday(i=1) -> dict:
    return {"adres": adr(i), "hesap_usd": 53_000.0, "hafta_pnl_usd": 500.0, "ay_pnl_usd": 3000.0, "getiri_7g": 0.01}


def iyi_dolum() -> list[dict]:
    bas = KOSU - 29 * GUN
    return dolumlar("BTC", 9, bas, pnl=50.0, tutma_saat=6, aralik_saat=24 * 3) + dolumlar("ETH", 1, bas + 25 * GUN, pnl=10.0, sira0=500)


def test_kopyalanabilirlik_uctan_uca_kopya_yalniz_liste_coinleri_ve_giris_getirisi():
    b = Baglamsiz()
    s = r.kopyalanabilirlik(aday(), b, portfoy(KARLI), lambda: iyi_dolum() + dolumlar("DOGE", 1, KOSU - 5 * GUN, sira0=900), vault_mi=lambda: False, giris_ms=KOSU - 3 * GUN)
    assert s["gecti"] and s["neden"] is None, s
    assert s["kopya_getiri_30g"] == 0.02 and s["kopya_koruma"] == pytest.approx(0.02 / 0.03) and s["skor"] == pytest.approx(0.06 / 0.05)
    assert b.cagri[0] == (20, None) and b.cagri[1] == (20, KOSU - 3 * GUN)           # DOGE (listede değil) kopya oynatmasına girmez; 10×2 liste dolumu
    assert s["giris_getiri"] == pytest.approx(-0.004 * 5)                           # slot ölçeği = kasa getirisi × (kasa / slot)


def test_kopyalanabilirlik_erken_elemede_dolum_cekilmez_vault_ve_tavan():
    b, cekim = Baglamsiz(), []
    s = r.kopyalanabilirlik(aday(), b, portfoy([0.0] * 31), lambda: cekim.append(1) or [], vault_mi=None)
    assert s["neden"] == "ay_pnl" and not cekim and not b.cagri                      # portfolio kuralı başarısız: dolum çekilmez
    assert r.kopyalanabilirlik(aday(), b, portfoy(KARLI), lambda: iyi_dolum(), vault_mi=lambda: True)["neden"] == "vault"
    assert not b.cagri
    ham = [{"coin": "BTC", "px": "1", "sz": "1", "side": "B", "time": KOSU - GUN, "startPosition": "0", "closedPnl": "0", "fee": "0", "tid": i} for i in range(int(RULES["radar_dolum_tavan"]))]
    assert r.kopyalanabilirlik(aday(), b, portfoy(KARLI), lambda: ham)["neden"] == "dolum_fazla"
    def hata():
        raise ValueError("boom")
    assert r.kopyalanabilirlik(aday(), b, portfoy(KARLI), hata)["neden"] == "veri_hatasi"
    assert r.kopyalanabilirlik(aday(), Baglamsiz(getiri=-0.01), portfoy(KARLI), lambda: iyi_dolum())["neden"] == "kopya_zarar"
    assert r.kopyalanabilirlik(aday(), Baglamsiz(getiri=0.01, ayna=0.03), portfoy(KARLI), lambda: iyi_dolum())["neden"] == "kopya_koruma_dusuk"


# ------------------------------------------------------------------------------------------------ koşu: tam evren, kontrol günü, ilerleme
class SahteIstemci:
    stats: dict = {}

    def __init__(self, n: int = 3):
        self.n, self.portfoy_say, self.dolum_say = n, 0, 0

    def leaderboard(self):
        return [lider(adr(i)) for i in range(1, self.n + 1)]

    def info(self, payload, weight=20):
        raise AssertionError(f"beklenmeyen istek {payload}")

    def portfolio(self, a):
        self.portfoy_say += 1
        return portfoy(KARLI)

    def fills(self, a, bas, max_rows=None, end_ms=None):
        self.dolum_say += 1
        return iyi_dolum()

    def vault_details(self, a):
        return {}


@pytest.fixture
def sahte_baglam(monkeypatch):
    monkeypatch.setattr(r.Baglam, "piyasa_oku", lambda self: None)
    monkeypatch.setattr(r.Baglam, "kopya_oynat", lambda self, d, p, bas_ms=None: {"getiri": 0.02, "ayna": {"getiri": 0.03}, "baslangic_usd": 1000.0, "slot_usd": 200.0})


def test_kos_tam_evren_ilk_kurulumda_taranir_havuz_yazilir(tmp_path, sahte_baglam):
    c = SahteIstemci(4)
    h = r.kos(c, KOSU, tmp_path, RULES, log=lambda *_: None, onceki=None, donem=DONEM)
    assert h["tarama"] and h["tarama_sebep"] == "ilk_kurulum" and len(h["satirlar"]) == 4 and all(s["gecti"] for s in h["satirlar"]) and h["sema"] == rk.HAVUZ_SEMA
    assert (tmp_path / "2026-11-23/havuz.json").exists() and c.portfoy_say == 4


def test_kos_kontrol_gunu_degilse_taramaz_kadro_surer(tmp_path, sahte_baglam):
    onceki = rk.kadro_olustur(r.kos(SahteIstemci(6), KOSU, tmp_path / "a", RULES, log=lambda *_: None, donem=DONEM), RULES, None, DONEM)
    c = SahteIstemci(6)
    h = r.kos(c, SALI, tmp_path / "b", RULES, log=lambda *_: None, onceki=onceki, donem=DONEM)
    assert h["tarama"] is False and h["satirlar"] == [] and c.portfoy_say == 0 and "bugun_kontrol_yapildi" not in h["tarama_sebep"] and h["tarama_sebep"] == "kontrol_gunu_degil"
    sali_kadro = rk.kadro_olustur(h, RULES, onceki, DONEM)
    assert [s["adres"] for s in sali_kadro["satirlar"]] == [s["adres"] for s in onceki["satirlar"]] and sali_kadro["kosu_ms"] == SALI      # yalnız kosu_ms tazelenir
    assert r.kos(SahteIstemci(6), KOSU + 3 * GUN, tmp_path / "c", RULES, log=lambda *_: None, onceki=onceki, donem=DONEM)["tarama"] is True      # Perşembe: kontrol günü


def test_kos_ayni_gun_ikinci_kosu_kontrol_yapmaz(tmp_path, sahte_baglam):
    onceki = rk.kadro_olustur(r.kos(SahteIstemci(6), KOSU, tmp_path / "a", RULES, log=lambda *_: None, donem=DONEM), RULES, None, DONEM)
    assert rk.tarama_gerekli(onceki, DONEM, KOSU + HOUR, RULES) == (False, "bugun_kontrol_yapildi")
    assert rk.tarama_gerekli(onceki, "2026-12-01T00:00:00Z", SALI, RULES) == (True, "ilk_kurulum")        # yeni dönem: hemen
    assert rk.tarama_gerekli({**onceki, "satirlar": []}, DONEM, SALI, RULES) == (True, "kadro_bos")


def test_kos_uyeler_suzgec_disi_olsa_da_olculur_ve_liste_disi_isaretlenir(tmp_path, sahte_baglam):
    onceki = rk.kadro_olustur(r.kos(SahteIstemci(2), KOSU, tmp_path / "a", RULES, log=lambda *_: None, donem=DONEM), RULES, None, DONEM)
    onceki["satirlar"].append({"adres": adr(99), "giris_ms": KOSU, "sira": 3})
    h = r.kos(SahteIstemci(2), KOSU + 3 * GUN, tmp_path / "b", RULES, log=lambda *_: None, onceki=onceki, donem=DONEM)
    liste_disi = next(s for s in h["satirlar"] if s["adres"] == adr(99))
    assert liste_disi["neden"] == "liste_disi" and not liste_disi["gecti"]
    uye = next(s for s in h["satirlar"] if s["adres"] == adr(1))
    assert uye["giris_getiri"] is not None                                                        # üyeler için girişten beri kopya sonucu hesaplanır


def test_kos_ilerleme_dosyasindan_kaldigi_yerden_surer(tmp_path, sahte_baglam):
    ilerleme = tmp_path / "ilerleme"
    c1 = SahteIstemci(4)
    orijinal = c1.fills
    cekim = {"n": 0}

    def kesilen(a, bas, max_rows=None, end_ms=None):
        cekim["n"] += 1
        if cekim["n"] == 3:
            raise KeyboardInterrupt                                                               # üçüncü adayda süreç kesilir
        return orijinal(a, bas, max_rows, end_ms)
    c1.fills = kesilen
    with pytest.raises(KeyboardInterrupt):
        r.kos(c1, KOSU, tmp_path / "o", RULES, log=lambda *_: None, donem=DONEM, ilerleme_dizin=ilerleme)
    c2 = SahteIstemci(4)
    h = r.kos(c2, KOSU + 5 * HOUR, tmp_path / "o", RULES, log=lambda *_: None, donem=DONEM, ilerleme_dizin=ilerleme)      # yeniden başlatma: kosu_ms korunur, biten 2 aday yeniden çekilmez
    assert h["kosu_ms"] == KOSU and c2.portfoy_say == 2 and len(h["satirlar"]) == 4 and all(s["gecti"] for s in h["satirlar"])


def test_kos_zaman_butcesi_asilirsa_zaman_yok_ve_eksik_kosu(tmp_path, sahte_baglam):
    t = iter(range(0, 10_000_000, 5000))
    h = r.kos(SahteIstemci(3), KOSU, tmp_path, {**RULES, "radar_zaman_butcesi_dk": 1}, log=lambda *_: None, saat=lambda: next(t), donem=DONEM)
    assert any(s["neden"] == "zaman_yok" for s in h["satirlar"]) and rk.kosu_tam_mi(h, RULES)[0] is False


# ------------------------------------------------------------------------------------------------ kadro durum makinesi
def hs(i: int, gecti=True, skor=1.0, neden=None, giris=None, **ek) -> dict:
    return {"adres": adr(i), "gecti": gecti, "neden": neden if not gecti else None, "skor": skor, "giris_getiri": giris, "kopya_getiri_30g": 0.01, "getiri_30g": 0.05, "dusus_30g": 0.05,
            "max_kaldirac": 3.0, "medyan_tutma_saat": 6.0, **ek}


def havuz(satirlar, kosu=KOSU, tarama=True) -> dict:
    return {"sema": rk.HAVUZ_SEMA, "kosu_ms": kosu, "kasa_usd": 1000.0, "tarama": tarama, "evren_toplam": 100, "satirlar": satirlar, "donem": DONEM}


def test_ilk_kurulum_en_iyi_bes_azsa_bos_kalir_gecmeyen_doldurulmaz():
    k = rk.kadro_olustur(havuz([hs(i, skor=float(i)) for i in range(1, 8)] + [hs(20, gecti=False, neden="islem_az")]), RULES, None, DONEM)
    assert [s["adres"] for s in k["satirlar"]] == [adr(7), adr(6), adr(5), adr(4), adr(3)] and [s["sira"] for s in k["satirlar"]] == [1, 2, 3, 4, 5]
    assert k["sade"] and k["radar_surum"] == "v5" and k["donem"] == DONEM and k["kontrol_gun"] == "2026-11-23" and k["cikanlar"] == [] and k["yasak"] == {}
    assert k["saha_n"] == 5 and k["kasa_usd"] == 1000.0 and all(s["katman"] == "ilk11" for s in k["satirlar"])
    az = rk.kadro_olustur(havuz([hs(1), hs(2), hs(3, gecti=False, neden="coin_kar")]), RULES, None, DONEM)
    assert [s["adres"] for s in az["satirlar"]] == [adr(1), adr(2)]                           # 3 slot BOŞ
    assert [d["neden"] for d in az["degisim"]] == ["ilk_kurulum", "ilk_kurulum"]


def kadro_5() -> dict:
    return rk.kadro_olustur(havuz([hs(i, skor=10.0 - i) for i in range(1, 11)]), RULES, None, DONEM)          # üyeler 1..5; 6..10 yedekte DEĞİL (yedek yok)


def test_kontrol_gunu_suzgecten_dusen_ve_kopya_kaybi_cikar_en_cok_2_yasak_14_gun_cikanlar():
    onceki = kadro_5()
    kosu2 = KOSU + 3 * GUN                                                                      # Perşembe
    sat = [hs(1, gecti=False, neden="coin_kar"), hs(2, giris=-0.10), hs(3, giris=-0.12), hs(4, giris=-0.01), hs(5, giris=0.02)] + [hs(i, skor=10.0 - i) for i in range(6, 11)]
    k = rk.kadro_olustur(havuz(sat, kosu2), RULES, onceki, DONEM)
    cik = [d["adres"] for d in k["degisim"] if d["tur"] == "cikis"]
    assert cik == [adr(1), adr(3)]                                                              # önce süzgeçten düşen, sonra en kötü sonuç; ≤2 (adr2 −%10 de uygun ama 3. değişiklik)
    assert {s["adres"] for s in k["satirlar"]} >= {adr(2), adr(4), adr(5)} and adr(1) not in {s["adres"] for s in k["satirlar"]}
    gir = [d["adres"] for d in k["degisim"] if d["tur"] == "giris"]
    assert gir == [adr(6), adr(7)] and len(k["satirlar"]) == 5                                  # boş slotlar sıradaki en iyiyle
    assert k["yasak"][adr(1)] == kosu2 + 14 * GUN and k["yasak"][adr(3)] == kosu2 + 14 * GUN
    assert k["cikanlar"] == [{"adres": adr(1), "cikis_ms": kosu2}, {"adres": adr(3), "cikis_ms": kosu2}]
    assert next(s for s in k["satirlar"] if s["adres"] == adr(2))["giris_ms"] == KOSU            # kalanların giriş zamanı korunur


def test_cikan_14_gun_geri_giremez_72_saat_sonra_cikanlardan_silinir_yasak_biter():
    onceki = kadro_5()
    k = rk.kadro_olustur(havuz([hs(1, gecti=False, neden="islem_az")] + [hs(i, skor=10.0 - i) for i in range(2, 11)], KOSU + 3 * GUN), RULES, onceki, DONEM)
    assert adr(1) in k["yasak"]
    # 4 gün sonra (Pazartesi) adr1 yeniden şartları geçiyor ve en iyi skor: yasak sürerken (14 gün) girmez; boş slot yok zaten
    k2 = rk.kadro_olustur(havuz([hs(1, skor=99.0)] + [hs(i, skor=10.0 - i) for i in range(2, 11)], KOSU + 7 * GUN), RULES, k, DONEM)
    assert adr(1) not in {s["adres"] for s in k2["satirlar"]} and k2["cikanlar"] == []              # 72 sa geçti: cikanlar boş
    k3 = rk.kadro_olustur(havuz([hs(i, gecti=False, neden="islem_az") for i in (2, 3)] + [hs(1, skor=99.0)] + [hs(i, skor=10.0 - i) for i in range(4, 11)], KOSU + 17 * GUN), RULES, k2, DONEM)
    assert adr(1) in {s["adres"] for s in k3["satirlar"]} and adr(1) not in k3["yasak"]             # 14 gün (KOSU+3g + 14g = +17g) bitti: geri girebilir


def test_veri_hatasi_cikis_nedeni_degil_ve_sonuc_ya_da_kayip_yoksa_uye_kalir():
    onceki = kadro_5()
    sat = [hs(1, gecti=False, neden="veri_hatasi"), hs(2, gecti=False, neden="zaman_yok"), hs(3, giris=None)] + [hs(i) for i in range(4, 11)]
    k = rk.kadro_olustur(havuz(sat, KOSU + 3 * GUN), RULES, onceki, DONEM)
    assert k["degisim"] == [] and {s["adres"] for s in k["satirlar"]} == {adr(i) for i in range(1, 6)}


def test_kontrol_gunu_disinda_degisiklik_yok_cikanlar_ve_yasak_tasinir():
    onceki = kadro_5()
    k = rk.kadro_olustur(havuz([hs(1, gecti=False, neden="coin_kar")] + [hs(i) for i in range(2, 11)], KOSU + 3 * GUN), RULES, onceki, DONEM)
    carry = rk.kadro_olustur(havuz([], KOSU + 4 * GUN, tarama=False), RULES, k, DONEM)
    assert carry["satirlar"] == k["satirlar"] and carry["cikanlar"] == k["cikanlar"] and carry["yasak"] == k["yasak"] and carry["degisim"] == [] and carry["kosu_ms"] == KOSU + 4 * GUN
    uzun = rk.kadro_olustur(havuz([], KOSU + 3 * GUN + 80 * HOUR, tarama=False), RULES, k, DONEM)
    assert uzun["cikanlar"] == []                                                                  # 72 sa'ten eski çıkanlar düşer


def test_yeni_donem_ya_da_eski_surum_kadrosu_devralinmaz_ve_eski_dosyada_cikanlar_yoksa_bos():
    onceki = kadro_5()
    yeni = rk.kadro_olustur(havuz([hs(i, skor=float(i)) for i in range(1, 4)]), RULES, onceki, "2026-12-01T00:00:00Z")
    assert [s["adres"] for s in yeni["satirlar"]] == [adr(3), adr(2), adr(1)] and yeni["yasak"] == {} and yeni["donem"] == "2026-12-01T00:00:00Z"
    eski = {"sema": rk.SEMA, "radar_surum": "v4", "kosu_ms": 1, "satirlar": [{"adres": adr(50), "sira": 1}]}                  # v4 dosyasında cikanlar/sade/donem yok
    assert rk.aktif_onceki(eski, DONEM, RULES) is None and rk.tarama_gerekli(eski, DONEM, SALI, RULES) == (True, "ilk_kurulum")
    assert "cikanlar" in kadro_5() and rk.kadro_olustur(havuz([hs(1)]), RULES, eski, DONEM)["cikanlar"] == []


def test_kosu_tam_mi_veri_hatasi_payi_ve_main(tmp_path):
    ok = havuz([hs(i) for i in range(1, 11)])
    assert rk.kosu_tam_mi(ok, RULES) == (True, None)
    kotu = havuz([hs(i) for i in range(1, 9)] + [hs(9, gecti=False, neden="veri_hatasi"), hs(10, gecti=False, neden="veri_hatasi")])
    assert rk.kosu_tam_mi(kotu, RULES)[0] is False                                                  # %20 > %10
    assert rk.kosu_tam_mi({**ok, "evren_toplam": 0}, RULES)[0] is False and rk.kosu_tam_mi(havuz([], tarama=False), RULES) == (True, None)
    yol = tmp_path / "havuz.json"
    yol.write_text(json.dumps(ok), encoding="utf-8")
    assert rk.main(["--havuz", str(yol), "--donem", DONEM]) == 0
    kadro = json.loads((tmp_path / "kadro.json").read_text(encoding="utf-8"))
    assert len(kadro["satirlar"]) == 5 and kadro["sema"] == rk.SEMA
    yol.write_text(json.dumps(kotu), encoding="utf-8")
    assert rk.main(["--havuz", str(yol), "--cikti", str(tmp_path / "k2.json")]) == 2 and not (tmp_path / "k2.json").exists()


# ------------------------------------------------------------------------------------------------ motor tarafı: sade kadro
def saha() -> kd.Saha:
    return kd.Saha({**RULES, "radar_saha_max": 5, "radar_canli_slot_min_usd": 200}, 1000.0)


def sade_kadro(adresler: list[int], kosu=KOSU, cikanlar=None) -> dict:
    return {"sema": rk.SEMA, "radar_surum": "v5", "sade": True, "kosu_ms": kosu, "satirlar": [{"adres": adr(i), "sira": n} for n, i in enumerate(adresler, 1)], "cikanlar": cikanlar or []}


def test_saha_sade_kadro_bes_uye_hemen_girer_kadro_dosyasi_yetkilidir():
    s = saha()
    kararlar, durum = s.degerlendir(sade_kadro([1, 2, 3, 4, 5, 6]), KOSU + 1000)
    assert durum == "ok" and [k.adres for k in kararlar if k.tur == "giris"] == [adr(i) for i in range(1, 6)] and set(s.uyeler) == {adr(i) for i in range(1, 6)}
    assert s.sade and s.to_json()["sade"] is True and kd.Saha(RULES, 1000.0, s.to_json()).sade
    # kadro dosyasında olmayan üye iner (sonuç dışı: trader kapatana kadar izlenir), boş slot kadro sırasıyla dolar
    kararlar2, _ = s.degerlendir(sade_kadro([1, 2, 3, 4, 7], KOSU + 3 * GUN, [{"adres": adr(5), "cikis_ms": KOSU + 3 * GUN}]), KOSU + 3 * GUN + 1000)
    assert [(k.tur, k.adres, k.sonuc) for k in kararlar2 if k.tur == "dus"] == [("dus", adr(5), False)] and adr(5) in s.inen and adr(5) not in s.bekleme
    assert [k.adres for k in kararlar2 if k.tur == "giris"] == [adr(7)] and not [k for k in kararlar2 if k.tur == "inen_kapat"]
    assert s.anlik(KOSU, lambda a: 1.0, sade_kadro([1])) == []                                   # slot düşüş stopu / kaldıraç kuralları bu kipte radarda


def test_saha_sade_kadro_az_uye_bos_slot_ve_bayatta_islem_yok_dusmesi_yok():
    s = saha()
    s.degerlendir(sade_kadro([1, 2]), KOSU + 1)
    assert len(s.uyeler) == 2 and s.eksik == {"saha": 2, "n": 5, "neden": "uygun_aday_yok"}
    kararlar, durum = s.degerlendir(sade_kadro([1, 2], KOSU), KOSU + 100 * HOUR)               # bayat (36 sa): yeni giriş yok, 72 sa kuralı yok
    assert durum == "kadro_bayat" and kararlar == [] and len(s.uyeler) == 2


def test_r6_eski_kadro_bayat_ya_da_yokken_islem_yok_72_saat_dusmesi_calisir():
    """(test_denetim_secim_b8'den taşındı) Eski (sade olmayan) kadrolar için R-6 davranışı aynen: kadro bayat/yokken de 72 sa işlem yok düşmesi."""
    from tests.test_canli_motor import RULES as MR, SAAT, T0, adr as madr, hazir_11, n_kadro

    def kur():
        s = hazir_11()
        for i in range(1, 11):
            s.islem_gordu(madr(i), T0 + 2 * SAAT)
        s.islem_gordu(madr(11), T0 - 50 * SAAT)
        return s
    s = kur()
    karar, durum = s.degerlendir(n_kadro(11, T0), T0 + 37 * SAAT)
    assert durum == "kadro_bayat" and [(k.tur, k.adres, k.neden, k.sonuc) for k in karar] == [("dus", madr(11), "islem_yok", False)]
    assert madr(11) not in s.uyeler and madr(11) not in s.bekleme and len(s.uyeler) == 10 and madr(11) in s.inen
    s2 = kur()
    karar2, durum2 = s2.degerlendir(None, T0 + 22 * SAAT)
    assert durum2 == "kadro_yok" and [(k.adres, k.neden) for k in karar2] == [(madr(11), "islem_yok")]
    assert kur().degerlendir(None, T0 + 22 * SAAT - 1) == ([], "kadro_yok")
    assert kd.Saha(MR, 1000.0).degerlendir(None, T0) == ([], "kadro_yok")
