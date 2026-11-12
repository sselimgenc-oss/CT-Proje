"""K-65: seçimde veri düzeltmeleri (perp pnl, taze birleşik seri, `veri_bayat`, motor paydası) ve geçici güvenlik vetoları (ömür perp zararı, zarara ekleme). Ağsız; elle hesaplanmış örnekler."""
import pytest

from copytrade import secim_d as s
from copytrade.canli import kadro as kd
from tests.test_canli_motor import T0, adr, hazir_11, kadro, satir
from tests.test_canli_motor import GUN as MGUN
from tests.test_canli_motor import SAAT as MSAAT
from tests.test_radar_tarama import A1, A2, HOUR, MIN, RULES, dolum
from tests.test_secim_d import SahteP, _karli_dolumlar
from tests.test_v11_kurallar import lider_ay

GUN = 24 * HOUR
T = 400 * GUN                                                               # "şimdi" (1971-02-04)
AY = "1971-02"


def seri(f, gun=100, son=T, bas=0.0):
    kum, out = bas, []
    for i in range(gun + 1):
        kum += f(i)
        out.append([son - (gun - i) * GUN, str(kum)])
    return out


def pf2(perp_gunluk, toplam_gunluk=None, hesap=20_000.0, perp_bas=0.0):
    """Gerçek HL biçimi: allTime (toplam: perp + spot) ve perpAllTime (yalnız perp; accountValueHistory birleşik hesapta 0)."""
    tp, pp = seri(toplam_gunluk or perp_gunluk), seri(perp_gunluk, bas=perp_bas)
    return [["allTime", {"pnlHistory": tp, "accountValueHistory": [[t, str(hesap)] for t, _ in tp]}],
            ["perpAllTime", {"pnlHistory": pp, "accountValueHistory": [[t, "0.0"] for t, _ in pp]}]]


ISTIKRAR = lambda i: 20.0 + (i % 5) * 3.0                                   # noqa: E731 — evren kapılarını geçer (testler/test_secim_d)


# ------------------------------------------------------------------------------------------------------------------------------ veri (Faz 0)
def test_pnl_yalniz_perp_serisinden_hesap_toplam_seriden():
    """Toplam pnl günde +100 $ (spot dahil), perp günde +20 $ → ölçüler perp'ten: 30 g pnl 600 $, ömür perp pnl 2.020 $ (101 nokta × 20); hesap toplam seriden 20.000 $ (perp av = 0)."""
    o = s.portfolio_olculeri(pf2(lambda i: 20.0, lambda i: 100.0), T, RULES)
    assert o["pnl_kaynak"] == "perp" and o["pnl_30g"] == pytest.approx(600.0) and o["omur_perp_pnl"] == pytest.approx(2020.0) and o["pnl_kum"] == pytest.approx(2020.0)
    assert o["hesap_usd"] == 20_000.0 and o["veri_yas_saat"] == 0.0
    eski = [["allTime", pf2(lambda i: 20.0, lambda i: 100.0)[0][1]]]               # perp dönemi yoksa (eski biçim) toplam seri yedeği
    assert s.portfolio_olculeri(eski, T, RULES)["pnl_kaynak"] == "toplam" and s.portfolio_olculeri(eski, T, RULES)["pnl_30g"] == pytest.approx(3000.0)


def test_birlesik_seri_taze_kuyruk_ve_veri_bayat():
    """perpAllTime son noktası T−3 g (bayat); perpMonth / perpWeek (her dönem kendi başından 0'dan sayar) T'ye dek. Gerçek pnl: her gün +20 $ (i. gün değeri 20·i).
    Elle: allTime son (T−3 g) = 20·97 = 1.940; month T−3 g'de 20·27 = 540 → fark 1.400 → month T = 600 + 1.400 = 2.000; week T'de 140 → fark 1.860 → T = 2.000 (= 20·100)."""
    at = [[T - (100 - i) * GUN, str(20.0 * i)] for i in range(98)]
    ay = [[T - (30 - j) * GUN, str(20.0 * j)] for j in range(31)]
    hf = [[T - (7 - j) * GUN, str(20.0 * j)] for j in range(8)]
    av = lambda pts, v: [[t, str(v)] for t, _ in pts]                       # noqa: E731
    pf = [["allTime", {"pnlHistory": at, "accountValueHistory": av(at, 20_000)}], ["month", {"pnlHistory": ay, "accountValueHistory": av(ay, 21_000)}],
          ["perpAllTime", {"pnlHistory": at, "accountValueHistory": av(at, 0)}], ["perpMonth", {"pnlHistory": ay, "accountValueHistory": av(ay, 0)}],
          ["perpWeek", {"pnlHistory": hf, "accountValueHistory": av(hf, 0)}]]
    birlesik, kaynak = s.pnl_serisi(pf)
    assert kaynak == "perp" and birlesik[-1] == (T, pytest.approx(2000.0)) and s.deger(birlesik, T - 7 * GUN) == pytest.approx(1860.0)
    assert s.deger(birlesik, T - 50 * GUN) == pytest.approx(1000.0)                                     # eski kısım allTime'dan aynen
    o = s.portfolio_olculeri(pf, T, RULES)
    assert o["pnl_kum"] == pytest.approx(2000.0) and o["pnl_30g"] == pytest.approx(600.0) and o["veri_yas_saat"] == 0.0 and o["hesap_usd"] == 21_000.0   # hesap da taze (month)
    yalniz_at = [["perpAllTime", {"pnlHistory": at}], ["allTime", {"pnlHistory": at, "accountValueHistory": av(at, 20_000)}]]
    ob = s.portfolio_olculeri(yalniz_at, T, RULES)
    assert ob["veri_yas_saat"] == 72.0 and s.evren_kapisi(ob, RULES) == "veri_bayat"                   # birleştirmesiz: 3 g eski → bayat
    sinir = s.portfolio_olculeri(pf2(ISTIKRAR), T + GUN, RULES)                                         # tam 24 sa: sınır dahil geçer
    assert sinir["veri_yas_saat"] == 24.0 and s.evren_kapisi(sinir, RULES) is None
    assert s.evren_kapisi(s.portfolio_olculeri(pf2(ISTIKRAR), T + GUN + 1, RULES), RULES) == "veri_bayat"


class Durum:
    """`info` yüzeyi: clearinghouseState (dex başına accountValue) + spotClearinghouseState."""

    def __init__(self, perp, spot):
        self.perp, self.spot, self.cagri = perp, spot, []

    def info(self, yuk, weight=20):
        self.cagri.append(yuk["type"])
        if yuk["type"] == "clearinghouseState":
            return {"marginSummary": {"accountValue": str(self.perp[yuk.get("dex", "")])}}
        if yuk["type"] == "spotClearinghouseState":
            return {"balances": [{"coin": c, "total": str(v)} for c, v in self.spot.items()]}
        raise AssertionError(yuk)


def test_motor_paydasi_tanimi_ve_duzeltme_esigi():
    """Motor tanımı (canli/motor.py hesap_degeri_oku): tüm perp dex + spot USDC; USDC dışı spot sayılmaz. 15.000 + 2.000 + 3.000 = 20.000."""
    c = Durum({"": 15_000.0, "xyz": 2_000.0}, {"USDC": 3_000.0, "HYPE": 9_999.0})
    assert s.motor_hesap_oku(c, A1, ["xyz"]) == pytest.approx(20_000.0) and s.motor_hesap_oku(c, A1, None) is None
    assert s.payda_karar(20_000.0, 19_700.0, RULES)["payda_duzeltildi"] is False                       # %1,5 fark: seri kalır
    assert s.payda_karar(20_400.0, 20_000.0, RULES)["payda_duzeltildi"] is False                       # tam %2: sınır dahil seri kalır
    k = s.payda_karar(25_000.0, 20_000.0, RULES)
    assert k == {"seri_hesap_usd": 25_000.0, "motor_hesap_usd": 20_000.0, "payda_oran": 1.25, "payda_duzeltildi": True}
    o = s.payda_uygula({"hesap_usd": 25_000.0, "dusus_90g": 0.16, "zirve_dusus": 0.08}, k)               # düşüş $ = 4.000 / 2.000 → motor paydasıyla 0,20 / 0,10
    assert o["hesap_usd"] == 20_000.0 and o["dusus_90g"] == pytest.approx(0.20) and o["zirve_dusus"] == pytest.approx(0.10) and o["payda_oran"] == 1.25
    assert s.payda_karar(20_000.0, None, RULES) == {"seri_hesap_usd": 20_000.0, "motor_hesap_usd": None, "payda_oran": None, "payda_duzeltildi": False}


class SahteD(SahteP):
    """SahteP + motor tanımıyla hesap okuması (adres → (perp accountValue, spot USDC))."""

    def __init__(self, *a, durum=None, **kw):
        super().__init__(*a, **kw)
        self.durum = durum or {}

    def info(self, payload, weight=20):
        if payload["type"] == "clearinghouseState":
            return {"marginSummary": {"accountValue": str(self.durum[payload["user"]][0])}}
        if payload["type"] == "spotClearinghouseState":
            return {"balances": [{"coin": "USDC", "total": str(self.durum[payload["user"]][1])}]}
        return super().info(payload, weight)


def _kopya_ortami():
    bas = T - int(RULES["secim_kopya_gun"]) * GUN
    fiyat = lambda coin, ts: 110.0 if (ts - bas - HOUR) % (24 * HOUR) >= 90 * MIN else 100.0     # noqa: E731
    return bas, fiyat


def test_kos_payda_duzeltmesi_kaydedilir_giris_hesabi_motor_degeri():
    """Seri 20.000 $, motor 15.000 + 1.000 = 16.000 $ → oran 1,25 > %2 → motor değeri; aday reddedilmez, giriş hesabı 16.000 $. A2: motor 19.800 + 0 → oran 1,0101 → seri kalır."""
    bas, fiyat = _kopya_ortami()
    c = SahteD([lider_ay(A1, 20_000, 100, 5_000, 600), lider_ay(A2, 20_000, 100, 5_000, 600)], {A1: _karli_dolumlar(bas), A2: _karli_dolumlar(bas)},
               {A1: pf2(ISTIKRAR), A2: pf2(ISTIKRAR)}, fiyat, durum={A1: (15_000.0, 1_000.0), A2: (19_800.0, 0.0)})
    havuz, kadro_ = s.kos(c, T, None, RULES, log=lambda *_: None)
    a1, a2 = (next(x for x in havuz["satirlar"] if x["adres"] == a) for a in (A1, A2))
    assert a1["payda_duzeltildi"] is True and a1["payda_oran"] == pytest.approx(1.25) and a1["seri_hesap_usd"] == 20_000.0 and a1["motor_hesap_usd"] == 16_000.0
    assert a1["hesap_usd"] == 16_000.0 and a1["neden"] is None
    assert a2["payda_duzeltildi"] is False and a2["payda_oran"] == pytest.approx(20_000 / 19_800) and a2["hesap_usd"] == 20_000.0
    g = {x["adres"]: x["giris_hesap_usd"] for x in kadro_["satirlar"]}
    assert g == {A1: 16_000.0, A2: 20_000.0} and havuz["veri_surum"] == 2 and kadro_["veri_surum"] == 2


# ------------------------------------------------------------------------------------------------------------------------------ vetolar (Faz 1)
def _ekleme_dolumlari(t, kayipli=2):
    """Long BTC 1 @100, sonra 5 ekleme (her biri ayrı emir). kayipli=2: 97 (−%3 zararda), 99, 95 (−%3,7 zararda), 100, 101 → 2/5 = 0,40.
    kayipli=1: ikinci zarardaki ekleme 98'e (ortalama 98,67 → −%0,7 > −%2: zararda sayılmaz) → 1/5 = 0,20."""
    fiyatlar = [97.0, 99.0, 95.0 if kayipli == 2 else 98.0, 100.0, 101.0]
    out = [dolum(t, "BTC", "B", 1, 0, 100.0)]
    for k, px in enumerate(fiyatlar, 1):
        out.append(dolum(t + k * HOUR, "BTC", "B", 1, k, px))
    out.append(dolum(t + 7 * HOUR, "BTC", "A", 6, 6, 101.0, kapanan=10.0))
    return out


def test_veto_omur_zarar_ve_zarara_ekleme_esikleri():
    assert s.veto_kodu(0.0, 0.0, 0, RULES) == "veto_omur_zarar" and s.veto_kodu(-5.0, None, None, RULES) == "veto_omur_zarar"
    assert s.veto_kodu(0.01, 0.0, 0, RULES) is None and s.veto_kodu(None, None, None, RULES) is None     # ölçülemeyen vetolamaz
    assert RULES["martingale_min_additions"] == 5 and RULES["secim_veto_zarara_ekleme_oran"] == 0.40
    assert s.veto_kodu(1.0, 0.40, 5, RULES) == "veto_zarara_ekleme"                                      # iki sınır dahil
    assert s.veto_kodu(1.0, 0.3999, 5, RULES) is None and s.veto_kodu(1.0, 0.9, 4, RULES) is None
    t = T - 5 * GUN
    assert s.zarara_ekleme(_ekleme_dolumlari(t), T - 28 * GUN, T, RULES) == (pytest.approx(0.40), 5)
    assert s.zarara_ekleme(_ekleme_dolumlari(t, kayipli=1), T - 28 * GUN, T, RULES) == (pytest.approx(0.20), 5)
    assert s.zarara_ekleme(_ekleme_dolumlari(t), T - 28 * GUN, t + 3 * HOUR, RULES)[1] == 2               # pencere dışı dolum sayılmaz
    assert s.veto_kodu(1.0, *s.zarara_ekleme(_ekleme_dolumlari(t), T - 28 * GUN, T, RULES), RULES) == "veto_zarara_ekleme"


M10 = {**RULES, "secim_veto_min_aday": 10}                                                               # askıya alma düzeneği (min > 0) ayrıca sınanır; varsayılan 0 (K-65 eki "veto kesin")


def _iki_aday(rules):
    """A1 temiz; A2 kapıları geçer ama ömür perp pnl'i −10.000 + 2.300 < 0 (eski büyük zarar; toplam pnl spot kârıyla pozitif)."""
    bas, fiyat = _kopya_ortami()
    c = SahteP([lider_ay(A1, 20_000, 100, 5_000, 600), lider_ay(A2, 20_000, 100, 5_000, 600)], {A1: _karli_dolumlar(bas), A2: _karli_dolumlar(bas)},
               {A1: pf2(ISTIKRAR), A2: pf2(ISTIKRAR, lambda i: 200.0, perp_bas=-10_000.0)}, fiyat)
    return s.kos(c, T, None, rules, log=lambda *_: None)


def test_veto_askida_havuz_min_adaydan_azsa_eski_davranis():
    havuz, kadro_ = _iki_aday(M10)                                                                         # temiz havuz 1 < 10 → askıda
    a2 = next(x for x in havuz["satirlar"] if x["adres"] == A2)
    assert a2["veto"] == "veto_omur_zarar" and a2["neden"] is None and a2["omur_perp_pnl"] < 0 and a2["zarara_ekleme_oran"] == 0.0 and a2["zarara_ekleme_sayi"] == 0
    assert havuz["veto_askida"] is True and havuz["veto_sayi"] == 1 and havuz["veto"]["kaynak"] == "bu_kosu"
    assert {x["adres"] for x in kadro_["satirlar"]} == {A1, A2} and kadro_["veto_havuz"]["sayi"] == 1 and kadro_["veto_havuz"]["askida"] is True


def test_veto_etkin_aday_elenir():
    havuz, kadro_ = _iki_aday({**RULES, "secim_veto_min_aday": 1})
    a2 = next(x for x in havuz["satirlar"] if x["adres"] == A2)
    assert a2["neden"] == "veto_omur_zarar" and a2["secildi"] is False and havuz["veto_askida"] is False
    assert [x["adres"] for x in kadro_["satirlar"]] == [A1]
    havuz3, kadro3 = _iki_aday({**RULES, "secim_veto_min_aday": 1, "secim_veto_acik": False})              # kapalı: veto yalnız bilgi
    assert {x["adres"] for x in kadro3["satirlar"]} == {A1, A2} and havuz3["veto_askida"] is False and havuz3["veto"]["sayi"] == 1


def _uye_kadrosu(veto_havuz, doldurma_ay=AY):
    k = {"radar_surum": "v2", "veri_surum": 2, "doldurma_ay": doldurma_ay,
         "satirlar": [{"adres": A1, "sira": 1, "form": 3.0, "giris_ms": T - 20 * GUN, "giris_hesap_usd": 20_000.0, "giris_pnl_kum": -8_000.0, "zirve_pnl": -8_000.0}]}
    if veto_havuz is not None:
        k["veto_havuz"] = veto_havuz
    return k


def _uye_istemci():
    """A1 üye: ömür perp pnl < 0 (veto a); A2 lider tablosunda temiz aday."""
    bas, fiyat = _kopya_ortami()
    return SahteP([lider_ay(A2, 20_000, 100, 5_000, 600)], {A1: _karli_dolumlar(bas), A2: _karli_dolumlar(bas)},
                  {A1: pf2(ISTIKRAR, perp_bas=-10_000.0), A2: pf2(ISTIKRAR)}, fiyat)


def test_vetolu_uye_cikar_yeri_ayni_kosuda_dolar():
    """Ay içi (doldurma günü değil), önceki havuz 12 ≥ 10 → veto etkin: A1 `veto_omur_zarar` ile çıkar, yakın çıkan sayılır; yer aynı koşuda A2 ile dolar (K-59/K-61 yolu)."""
    havuz, k = s.kos(_uye_istemci(), T, _uye_kadrosu({"sayi": 12, "askida": False}), RULES, log=lambda *_: None)
    assert k["cikanlar"] == {A1: "veto_omur_zarar"} and A1 in k["cikanlar_gecmis"] and [x["adres"] for x in k["satirlar"]] == [A2]
    assert havuz["doldurma"] is True and havuz["veto"]["uye_kaynak"] == "onceki" and havuz["veto"]["uye_sayi"] == 12
    u = next(x for x in havuz["satirlar"] if x["adres"] == A1)
    assert u["tur"] == "uye" and u["neden"] == "veto_omur_zarar" and u["veto"] == "veto_omur_zarar" and u["zarara_ekleme_sayi"] == 0
    # önceki havuz askıda (3 < 10): üye kalır, doldurma yok
    havuz2, k2 = s.kos(_uye_istemci(), T, _uye_kadrosu({"sayi": 3, "askida": True}), M10, log=lambda *_: None)
    assert k2["cikanlar"] == {} and [x["adres"] for x in k2["satirlar"]] == [A1] and havuz2["doldurma"] is False and havuz2["veto"]["uye_kaynak"] == "onceki"
    assert k2["veto_havuz"] == {"sayi": 3, "askida": True}                                                # bilinen son sayı taşınır
    # sayı bilinmiyor: veto yine uygulanır ve kaydedilir
    havuz3, k3 = s.kos(_uye_istemci(), T, _uye_kadrosu(None), RULES, log=lambda *_: None)
    assert k3["cikanlar"] == {A1: "veto_omur_zarar"} and havuz3["veto"]["uye_kaynak"] == "bilinmiyor" and [x["adres"] for x in k3["satirlar"]] == [A2]


def test_doldurma_gununde_uye_vetosu_bu_kosunun_sayisiyla():
    """Ay başı doldurma: üye kararı ertelenir; bu koşunun temiz havuzu (A2 → 1) min 1 ile etkin → A1 çıkar, A2 girer. Min 10 ile askıda → A1 kalır."""
    havuz, k = s.kos(_uye_istemci(), T, _uye_kadrosu({"sayi": 50}, doldurma_ay="1971-01"), {**RULES, "secim_veto_min_aday": 1}, log=lambda *_: None)
    assert k["cikanlar"] == {A1: "veto_omur_zarar"} and [x["adres"] for x in k["satirlar"]] == [A2] and havuz["veto"]["uye_kaynak"] == "bu_kosu"
    havuz2, k2 = s.kos(_uye_istemci(), T, _uye_kadrosu({"sayi": 50}, doldurma_ay="1971-01"), M10, log=lambda *_: None)
    assert k2["cikanlar"] == {} and {x["adres"] for x in k2["satirlar"]} == {A1, A2} and havuz2["veto_askida"] is True and k2["veto_havuz"]["sayi"] == 1


def test_veri_surum_1_kadrosunda_giris_pnl_perp_seriden_yeniden_kurulur():
    """Önceki kadro toplam pnl ile yazılmış (giris_pnl_kum 9.999 = toplam): perp seride giriş anı (T−20 g, i = 80) değeri 20·81 = 1.620 (i = 0…80, 81 gün × 20 $); zirve = son nokta 20·101 = 2.020."""
    bas, fiyat = _kopya_ortami()
    pf = pf2(lambda i: 20.0, lambda i: 120.0)
    c = SahteP([], {A1: _karli_dolumlar(T - 10 * GUN, adet=5)}, {A1: pf}, fiyat)
    onceki = {"radar_surum": "v2", "doldurma_ay": AY, "satirlar": [{"adres": A1, "sira": 1, "form": 3.0, "giris_ms": T - 20 * GUN, "giris_hesap_usd": 20_000.0,
                                                                   "giris_pnl_kum": 9_999.0, "zirve_pnl": 12_000.0}]}
    havuz, k = s.kos(c, T, onceki, RULES, log=lambda *_: None)
    u = k["satirlar"][0]
    assert u["giris_pnl_kum"] == pytest.approx(1620.0) and u["zirve_pnl"] == pytest.approx(2020.0) and k["cikanlar"] == {}     # toplam tabanla giris_dusus yanlış alarm vermez
    assert next(x for x in havuz["satirlar"] if x["adres"] == A1)["veri_gocu"] is True


# ------------------------------------------------------------------------------------------------------------------------------ motor (K-61 yolu)
def test_motor_veto_cikisini_k61_gibi_hemen_uygular():
    assert set(s.ANINDA_VETO) <= set(kd.ANINDA_CIKIS) and "elle_cikarildi" in kd.ANINDA_CIKIS
    sa = hazir_11()
    ilk = [satir(i, i, 90 - i) for i in range(1, 12)]
    sa.degerlendir(kadro(ilk, T0 + MGUN + MSAAT), T0 + MGUN + 2 * MSAAT)                                  # günün ilk kadrosu
    ikinci = kadro([satir(i, i, 90 - i) for i in range(1, 11)] + [satir(12, 11)], T0 + MGUN + 7 * MSAAT)     # 11 vetoyla çıktı, yerine 12
    ikinci["cikanlar"] = {adr(11): "veto_zarara_ekleme"}
    karar, _ = sa.degerlendir(ikinci, T0 + MGUN + 8 * MSAAT)
    assert [(x.tur, x.adres, x.neden) for x in karar] == [("dus", adr(11), "veto_zarara_ekleme"), ("giris", adr(12), "bos_slot")]
    assert adr(11) not in sa.uyeler and sa.bekleme[adr(11)] > T0 + MGUN + 8 * MSAAT
    sb = hazir_11()                                                                                         # K-39'un sıradan çıkış nedeni hemen uygulanmaz (karşılaştırma)
    sb.degerlendir(kadro(ilk, T0 + MGUN + MSAAT), T0 + MGUN + 2 * MSAAT)
    ikinci["cikanlar"] = {adr(11): "giris_dusus"}
    assert sb.degerlendir(ikinci, T0 + MGUN + 8 * MSAAT)[0] == []


def test_k65_veto_kesin_varsayilan_hic_askiya_alinmaz_yer_bos_kalir():
    """K-65 eki (12.11 kullanıcı kararı): kurallar.yaml `secim_veto_min_aday` 0 → temiz havuz ne kadar küçük olursa olsun veto uygulanır.
    12.11 olayı: boş yere kapıyı geçen tek aday vetoluydu (temiz havuz 0) ve askıda kuralıyla girmişti; artık girmez, yer boş kalır."""
    assert RULES["secim_veto_min_aday"] == 0
    bas, fiyat = _kopya_ortami()
    c = SahteP([lider_ay(A2, 20_000, 100, 5_000, 600)], {A2: _karli_dolumlar(bas)}, {A2: pf2(ISTIKRAR, lambda i: 200.0, perp_bas=-10_000.0)}, fiyat)
    havuz, k = s.kos(c, T, None, RULES, log=lambda *_: None)
    a2 = next(x for x in havuz["satirlar"] if x["adres"] == A2)
    assert a2["neden"] == "veto_omur_zarar" and a2["secildi"] is False and havuz["veto_askida"] is False and havuz["veto_sayi"] == 0
    assert k["satirlar"] == [] and k["veto_havuz"]["askida"] is False
    # vetolu üye: önceki havuz askıda/küçük olsa da çıkar (yer aynı koşuda temiz adayla dolar)
    havuz2, k2 = s.kos(_uye_istemci(), T, _uye_kadrosu({"sayi": 0, "askida": True}), RULES, log=lambda *_: None)
    assert k2["cikanlar"] == {A1: "veto_omur_zarar"} and [x["adres"] for x in k2["satirlar"]] == [A2]
