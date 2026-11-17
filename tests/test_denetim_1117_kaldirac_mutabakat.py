"""Denetim 2026-11-17 ADIM 4: (a) gerçek kipte azami kaldıraç < 5 coinde açılış yok (K-67), (b) çözümde konan mutabakat bayrağı borsa=defter teyidine dek kalır, (c) açılışta orderStatus hatası niyeti 'çözüldü' yapmaz."""
import pytest

from copytrade import kurallar
from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from copytrade.canli import yurutucu as yu
from tests.test_canli_motor import CHAT, RULES, SAAT, TOKEN, Saat, SahteTG, adr, kadro, kayitlar, kur, olay, satir
from tests.test_canli_t4b import HLADR, BorsaSim


class KaldiracSim(BorsaSim):
    """BorsaSim + `meta`'da maxLeverage (BTC 40x, ETH 3x). `meta_hata` ise meta okunamaz."""
    meta_hata = False

    def post(self, y):
        if y["type"] == "meta":
            if self.meta_hata:
                raise OSError("meta yok")
            return {"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}, {"name": "ETH", "szDecimals": 4, "maxLeverage": 3}]}
        return super().post(y)


def _gercek(tmp_path, monkeypatch, sim, esik=5):
    monkeypatch.setenv("HL_HESAP_ADRESI", HLADR)
    rules = {**RULES, "canli_kasa_usd": 1000.0, "canli_min_azami_kaldirac": esik}
    saat, tgp = Saat(), SahteTG()
    k = kadro([satir(1, 1)], saat() - SAAT)
    sim.trader_poz[adr(1)] = {}
    m = mt.Motor(rules, yu.GercekYurutucu(sim, sim.post, rules), sim.post, tg.Telegram(TOKEN, CHAT, tgp), tmp_path / "durum", tmp_path / "kayit", lambda: k, saat)
    return m, sim, saat, tgp


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


# ------------------------------------------------------------------ 4a
def test_uretim_degeri_5_ve_atla_etiketleri():
    assert kurallar.load_rules_asil()["canli_min_azami_kaldirac"] == 5
    assert tg.atla_etiket("kaldirac_dusuk") != "kaldirac_dusuk" and tg.atla_etiket("kaldirac_bilinmiyor") != "kaldirac_bilinmiyor"


def test_gercek_azami_kaldirac_5ten_kucuk_coinde_acilis_yok_buyukte_var(tmp_path, monkeypatch):
    m, sim, saat, tgp = _gercek(tmp_path, monkeypatch, KaldiracSim())
    m.baslat()
    sim.trader_poz[adr(1)] = {"ETH": 150.0, "BTC": 300.0}
    s_eth = m.olay_isle(olay("a:1", adr(1), "ETH", "B", 150, 2000.0, 0.0, saat))
    assert [(x.karar, x.neden) for x in s_eth] == [("atlandi", "kaldirac_dusuk")] and not any(c.get("ETH") for c in m.hesap.poz.values()) and sim.siparisler == []
    s_btc = m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert s_btc[0].karar == "emir" and m.hesap.sz(adr(1), "BTC") > 0


def test_gercek_tablo_okunamazsa_bilinmiyor_acilis_yok_sonra_tablo_gelince_acilir(tmp_path, monkeypatch):
    sim = KaldiracSim()
    sim.meta_hata = True
    m, sim, saat, tgp = _gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert [(x.karar, x.neden) for x in s] == [("atlandi", "kaldirac_bilinmiyor")]
    sim.meta_hata = False
    saat.ms += 60_000
    m.dakika()                                                              # dakikalık okuma tabloyu getirir
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert s[0].karar == "emir"


def test_gercek_kapanis_dusuk_kaldiracli_coinde_serbest(tmp_path, monkeypatch):
    m, sim, saat, tgp = _gercek(tmp_path, monkeypatch, KaldiracSim())
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m._hl_maks_kaldirac["BTC"] = 3.0                                        # tablo sonradan düşük gösterse bile kapanış engellenmez
    sim.trader_poz[adr(1)] = {}
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)


def test_esik_sifir_veya_sanal_kipte_sizgec_yok(tmp_path, monkeypatch):
    m, sim, saat, tgp = _gercek(tmp_path, monkeypatch, KaldiracSim(), esik=0)
    m.baslat()
    sim.trader_poz[adr(1)] = {"ETH": 150.0}
    assert m.olay_isle(olay("a:1", adr(1), "ETH", "B", 150, 2000.0, 0.0, saat))[0].karar == "emir"
    ms, hl, saat2, _ = kur(tmp_path / "s", kurallar={"canli_min_azami_kaldirac": 5})          # sanal kip: değer 5 olsa da süzgeç yok (davranış değişmez)
    ms.baslat()
    assert ms.kaldirac_yetersiz("ETH") is None and ms.kaldirac_yetersiz("BTC") is None


# ------------------------------------------------------------------ 4b
def test_cozumde_konan_mutabakat_bayragi_fark_10_usd_altinda_bile_teyide_dek_kalir(tmp_path, monkeypatch):
    """Eski hata: belirsiz_niyet_yok bayrağı koyar, aynı dakikadaki `_mutabakat` (fark 5 $ < 10 $ eşiği) bayrağı hemen siler. Şimdi borsa = defter olana dek kalır."""
    m, sim, saat, tgp = _gercek(tmp_path, monkeypatch, KaldiracSim(), esik=0)
    m.baslat()
    sim.poz["BTC"] = 0.05                                                    # borsada 0,05 BTC = 5 $, defterde yok
    m.hesap.belirsiz["0xyok"] = {"ms": saat() - 100_000, "deneme": 0, "adres": adr(1), "coin": "BTC"}      # niyet satırı yok (bozulma)
    saat.ms += 60_000
    m.dakika()
    assert kayitlar(tmp_path, "belirsiz_niyet_yok") and m.risk.acilis_durdu.get("mutabakat") is True and "belirsiz_niyet_yok:BTC" in m.mutabakat_tutan
    saat.ms += 60_000
    m.dakika()
    assert m.risk.acilis_durdu.get("mutabakat") is True                      # hâlâ teyitsiz
    m.durum_yaz()
    assert "belirsiz_niyet_yok:BTC" in __import__("json").loads((tmp_path / "durum" / "motor.json").read_text())["mutabakat_tutan"]      # kalıcı
    sim.poz["BTC"] = 0.0                                                     # borsa = defter
    saat.ms += 60_000
    m.dakika()
    assert m.risk.acilis_durdu.get("mutabakat") is False and not m.mutabakat_tutan and kayitlar(tmp_path, "mutabakat_not_temizlendi")


# ------------------------------------------------------------------ 4c
def test_acilista_orderstatus_hatasi_niyeti_cozuldu_yapmaz_belirsiz_olarak_yeniden_denenir(tmp_path, monkeypatch):
    """Eski hata: orderStatus hatası → niyet 'cozuldu:orderstatus_hata' (kapandı); dolmuş emir defterde yok = yetim. Şimdi niyet açık, belirsiz_coz her dakika yeniden sorar; açılış kapalı."""
    m, sim, saat, tgp = _gercek(tmp_path, monkeypatch, KaldiracSim(), esik=0)
    m.baslat()
    from copytrade.canli.niyet import cloid_uret
    cloid = cloid_uret("a:1", "ac")
    m.niyet.niyet_yaz(kimlik="a:1", eylem="ac", adres=adr(1), coin="BTC", yon="B", usd=27.0, reduce_only=False, cloid=cloid, ms=saat() - 120_000)
    sim.poz["BTC"] = 0.27273                                                 # emir borsada DOLDU (çökmeden önce)
    sim.trader_poz[adr(1)] = {"BTC": 300.0}                                  # trader pozisyonu açık (senkron kapatmasın)
    gercek = m.post
    durum = {"hata": True}

    def post(y):
        if y["type"] == "orderStatus" and durum["hata"]:
            raise OSError("zaman asimi")
        return gercek(y)
    m.post = post
    m.niyetleri_coz(saat())
    assert [x["cloid"] for x in m.niyet.sonucsuz()] == [cloid]               # niyet AÇIK (çözüldü yazılmadı)
    assert cloid in m.hesap.belirsiz and m.risk.acilis_durdu.get("belirsiz") is True and m.risk.acilis_durdu.get("mutabakat") is True
    assert m.risk.acilis_izni(adr(1), "BTC", True, saat())[0] is False       # o coinde (ve genel) açılış kapalı
    assert kayitlar(tmp_path, "niyet_coz_hata") and any("sorgulanamadı" in x for x in tgp.gonderilen)
    durum["hata"] = False                                                    # HL geri geldi: dakikalık yol çözer
    sim.durumlar[cloid] = {"status": "order", "order": {"order": {"coin": "BTC", "side": "B", "limitPx": "100.5", "sz": "0.0", "origSz": "0.27273", "oid": 7}, "status": "filled"}}
    saat.ms += 60_000
    m.dakika()
    assert cloid not in m.hesap.belirsiz and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.27273, abs=1e-9)    # dolum deftere işlendi (yetim kalmadı)
    assert kayitlar(tmp_path, "belirsiz_cozuldu")
