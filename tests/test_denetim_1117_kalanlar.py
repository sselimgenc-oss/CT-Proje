"""Denetim 2026-11-17 ADIM 8: O4 ilk mutabakat, O10 WS geri çekilme, O11 hakem kaçanı, D2 niyet yarım satır, D3 HL değeri NaN, D4 çözülen dolumda gerçek fiyat/ücret, D5 hl_oz_ms,
D6 stopsuz tolerans 1800, D8 workflow token kapsamı, Telegram grup beyaz listesi, ortam dosyası izni."""
import asyncio
import inspect
import os
import stat

import pytest
import yaml

from copytrade import dinleyici as d
from copytrade import kurallar
from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from copytrade.canli.niyet import Niyet
from tests.test_canli_g7 import G7Sim
from tests.test_canli_motor import SahteTG, TOKEN, adr, kayitlar, olay
from tests.test_canli_t4b import HLADR, BorsaSim, kur_gercek
from tests.test_dinleyici import IZ, Saat, calistir


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _acik_poz(tmp_path, monkeypatch, sim=None):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim or BorsaSim())
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dakika()
    return m, sim, saat, tgp


# ------------------------------------------------------------------ O4
def test_o4_calis_kacanlari_tamamlamadan_once_ilk_mutabakat_cagirir_tam_dakika_degil():
    kaynak = inspect.getsource(mt.calis)
    assert kaynak.index("motor.ilk_mutabakat()") < kaynak.index("motor.kacanlari_tamamla()") and "motor.dakika()" not in kaynak


def test_o4_motor_kapaliyken_stop_tetiklendi_ilk_mutabakat_acilisi_kapali_tutar_defteri_duzeltir(tmp_path, monkeypatch):
    """Eski hata: motor kapalıyken ETH/BTC stopu tetiklendi (borsa 0, defter +0,27273); kaçan dolum oynatması bayat biz_sz ile AÇILIŞ üretirdi. Şimdi önce borsa mutabakatı: sorun → açılış kapalı;
    borsa stop eşitlemesi kaybolan stopu teyitli kapanışla defterden temizler."""
    m, sim, saat, tgp = _acik_poz(tmp_path, monkeypatch)
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.27273, abs=1e-5) and m.risk.acilis_durdu.get("mutabakat") is False
    sim.stop_tetikle("BTC")                                                  # "motor kapalıyken" borsada tetiklendi
    saat.ms += 60_000
    m.ilk_mutabakat()                                                        # calis başı: tam dakika() DEĞİL
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9) and kayitlar(tmp_path, "harici_kapanis")      # stop eşitleme defteri borsayla uzlaştırdı
    assert m.risk.acilis_durdu.get("mutabakat") is True and kayitlar(tmp_path, "ilk_mutabakat")                  # mutabakat farkı gördü: açılış kapalı
    sim.trader_poz[adr(1)] = {"BTC": 600.0}
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 300.0, saat))
    assert [(x.karar, x.neden) for x in s] == [("engel", "mutabakat")]       # kaçan dolum oynatması bu durumda açılış yapmaz
    saat.ms += 60_000
    m.dakika()                                                               # temiz mutabakat bayrağı kaldırır
    assert m.risk.acilis_durdu.get("mutabakat") is False


def test_o4_hl_okunamazsa_acilis_kapali_kalir(tmp_path, monkeypatch):
    m, sim, saat, tgp = _acik_poz(tmp_path, monkeypatch)
    gercek = m.post

    def bozuk(y):
        if y["type"] == "clearinghouseState" and y["user"] == HLADR:
            raise OSError("ag")
        return gercek(y)
    m.post = bozuk
    saat.ms += 60_000
    m.ilk_mutabakat()
    assert m.risk.acilis_durdu.get("mutabakat") is True and kayitlar(tmp_path, "ilk_mutabakat_yok")


# ------------------------------------------------------------------ O10
def _bekleme_olc(monkeypatch, tmp_path, **ayar_kw):
    bekler = []
    asil = asyncio.wait_for

    async def wf(aw, timeout=None):
        if getattr(getattr(aw, "cr_code", None), "co_name", "") == "wait":      # Event.wait() (geri çekilme beklemesi)
            bekler.append(timeout)
            aw.close()
            return None
        return await asil(aw, timeout)
    uniform = []
    monkeypatch.setattr(d.random, "uniform", lambda a, b: uniform.append((a, b)) or 1.0)
    monkeypatch.setattr(d.asyncio, "wait_for", wf)
    ayar = d.Ayar(rest_dolum_ara_sn=0.0, rest_poz_ara_sn=0.0, sure_sn=0.3, geri_cekilme_ilk_sn=0.01, geri_cekilme_max_sn=10.0, **ayar_kw)
    calistir(IZ, [[]] * 6, tmp_path, ayar=ayar)
    return bekler, uniform


def test_o10_baglanip_hemen_kopan_oturum_geri_cekilmeyi_sifirlamaz_ustel_artar_ve_jitter(tmp_path, monkeypatch):
    """Eski hata: bekleme abonelikten hemen sonra ilk değere dönerdi (hep 0,01 sn → abonelik fırtınası). Şimdi 60 sn kararlı oturum yoksa 0,01 → 0,02 → 0,04 → 0,08 …"""
    bekler, uniform = _bekleme_olc(monkeypatch, tmp_path)
    assert bekler[:5] == pytest.approx([0.01, 0.02, 0.04, 0.08, 0.16]) and set(uniform) == {(0.5, 1.5)}


def test_o10_kararli_oturumdan_sonra_sifirlanir(tmp_path, monkeypatch):
    bekler, _ = _bekleme_olc(monkeypatch, tmp_path, kararli_oturum_sn=0.0)           # her oturum "kararlı" sayılır → eski davranış (hep ilk değer)
    assert bekler[:5] == pytest.approx([0.01] * 5)
    assert d.Ayar().kararli_oturum_sn == 60.0


# ------------------------------------------------------------------ O11
def test_o11_olcum_kacan_perp_dolumu_dolgu_olarak_kuyruga_alir_spot_hip3_degil():
    o = d.Olcum(IZ)
    o.abone_coinler = {"BTC"}
    o.kopma_araliklari = [(50_000, 60_000)]
    rest = [{"tid": 1, "time": 55_000, "coin": "BTC"}, {"tid": 2, "time": 70_000, "coin": "BTC"}, {"tid": 4, "time": 55_000, "coin": "zzz:Y"}, {"tid": 6, "time": 55_000, "coin": "PURR/USDC"}]
    assert o.rest_karsilastir("aaaa", "0xa", rest, 10_000_000, 120_000) == 1
    assert [f["tid"] for _, f in o.dolgu_yeni] == [1, 2]                              # kopma_araligi + gercek kaçan; hip3/spot yok
    o.dolgu_yeni.clear()
    assert o.rest_karsilastir("aaaa", "0xa", rest, 10_000_000, 120_000) == 0 and o.dolgu_yeni == []        # ikinci turda çift yok


def test_o11_hakem_turu_kacan_kapanisi_motor_hattina_verir(tmp_path):
    gelen = []

    class KayitDin(d.Dinleyici):
        def risk_isle(self, o, canli, simdi_ms, kaynak=None):
            gelen.append((o.kimlik, o.kaynak, o.coin, o.yon))
    saat = Saat(ms=10_000_000)
    rest = [{"tid": 77, "time": 9_000_000, "coin": "BTC", "px": "100", "sz": "1", "side": "A", "startPosition": "1"}]
    din = KayitDin(IZ, ["BTC"], None, lambda y: rest, tmp_path, d.Ayar(rest_dolum_ara_sn=0.0, rest_poz_ara_sn=0.0), saat.saat_ms, saat.mono)
    din.olcum.abone_coinler = {"BTC"}
    asyncio.run(din.rest_karsilastir(yeniden=False))
    assert gelen and gelen[0][0].endswith(":77") and gelen[0][1:] == ("dolgu", "BTC", "A")       # kapanış geç de olsa işlenir (motor açılışı canli_olay_stale_sn ile reddeder)


# ------------------------------------------------------------------ D2
def test_d2_niyet_yarim_son_satir_yeni_niyeti_yutmaz(tmp_path):
    yol = tmp_path / "niyet.jsonl"
    n = Niyet(yol)
    n.niyet_yaz(kimlik="a:1", eylem="ac", adres="0x1", coin="BTC", yon="B", usd=10.0, reduce_only=False, cloid="0x01", ms=1)
    with yol.open("ab") as f:
        f.write(b'{"t":"niyet","kimlik":"yar')                                  # çökme: yarım satır, '\n' yok
    n.niyet_yaz(kimlik="a:2", eylem="ac", adres="0x1", coin="ETH", yon="B", usd=10.0, reduce_only=False, cloid="0x02", ms=2)
    assert [x["cloid"] for x in n.satirlar()] == ["0x01", "0x02"]                # eski: ikinci satır yarım satıra yapışıp ikisi de kaybolurdu
    n.sonuc_yaz("0x02", "dolu", 3)
    assert [x["cloid"] for x in n.sonucsuz()] == ["0x01"]


# ------------------------------------------------------------------ D3 / D5
def test_d3_hl_degeri_nan_inf_negatif_uygulanmaz_ayri_bayrak_kalici_deger_duzelince_kalkar(tmp_path, monkeypatch):
    m, sim, saat, tgp = _acik_poz(tmp_path, monkeypatch)
    oz0 = m.hl_oz
    for kotu in (float("nan"), float("inf"), -5.0):
        assert m.hl_uygula(kotu, saat.ms) is False
    assert m.hl_oz == oz0 and m.risk.acilis_durdu.get("hl_deger") is True and len(kayitlar(tmp_path, "hl_deger_gecersiz")) == 1 and any("geçersiz" in x for x in tgp.gonderilen)
    sim.deger = float("nan")                                                    # HL değeri bozuk gelirse dakikalık yol da (mutabakat dahil) bayrağı silmez
    for _ in range(2):
        saat.ms += 60_000
        m.dakika()
        assert m.risk.acilis_durdu.get("hl_deger") is True and m.risk.acilis_izni(adr(1), "ETH", True, saat.ms)[0] is False
    sim.deger = 1000.0
    saat.ms += 60_000
    m.dakika()
    assert m.risk.acilis_durdu.get("hl_deger") is False and kayitlar(tmp_path, "hl_deger_duzeldi")


def test_d3_mids_inf_ve_nan_filtrelenir(tmp_path, monkeypatch):
    sim = BorsaSim()
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    gercek = m.post
    m.post = lambda y: {"BTC": "inf", "ETH": "nan", "SOL": "5"} if y["type"] == "allMids" else gercek(y)
    assert m.mids_al() == {"SOL": 5.0}


def test_d5_hl_oz_ms_okumanin_gercek_zamani(tmp_path, monkeypatch):
    """Eski hata: hl_oz_ms döngü başı `simdi` idi (okuma onlarca sn sonra). Okumanın başladığı an (saat_ms) kullanılır."""
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    gercek = m.post

    def yavas(y):
        if y["type"] == "clearinghouseState":
            saat.ms += 40_000                                              # HL okuması döngü başlayalı 30 sn sonra (mids / kadro / hesap okumaları sürdü)
        return gercek(y)
    m.post = yavas
    simdi = saat.ms
    saat.ms += 30_000
    okuma_basi = saat.ms
    hl = m.hl_oku()
    m.hl_uygula(hl[1], simdi, m._hl_okuma_ms(hl, simdi))
    assert m.hl_oz_ms == okuma_basi != simdi


# ------------------------------------------------------------------ D4
class DolumSim(G7Sim):
    """BorsaSim + userFillsByTime satırları + orderStatus(cloid) (çökmeden kalan emir borsada DOLDU)."""


def _niyet_yaz_ve_borsada_doldur(m, sim, saat, cloid_kimlik="a:1"):
    from copytrade.canli.niyet import cloid_uret
    cloid = cloid_uret(cloid_kimlik, "ac")
    m.niyet.niyet_yaz(kimlik=cloid_kimlik, eylem="ac", adres=adr(1), coin="BTC", yon="B", usd=27.0, reduce_only=False, cloid=cloid, ms=saat() - 120_000)
    sim.poz["BTC"] = 0.27273
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    sim.durumlar[cloid] = {"status": "order", "order": {"order": {"coin": "BTC", "side": "B", "limitPx": "100.5", "sz": "0.0", "origSz": "0.27273", "oid": 7}, "status": "filled"}}
    return cloid


def test_d4_niyetleri_coz_gercek_fiyat_ve_ucret_userfills_ten(tmp_path, monkeypatch):
    """Altın örnek: emir 100,5 (limitPx) bandıyla gitti ama 100,0'dan doldu (fee 0,012 $). Eski: defterde giriş 100,5, ücret 0. Şimdi giriş 100,0; ücret 0,012."""
    sim = DolumSim()
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    cloid = _niyet_yaz_ve_borsada_doldur(m, sim, saat)
    sim.fills = [{"coin": "BTC", "oid": 7, "cloid": cloid, "sz": "0.27273", "px": "100.0", "fee": "0.012"}]
    m.niyetleri_coz(saat())
    p = m.hesap.poz[adr(1)]["BTC"]
    assert p.sz == pytest.approx(0.27273, abs=1e-9) and p.giris == pytest.approx(100.0) and m.hesap.ucret[adr(1)] == pytest.approx(0.012)
    assert m.ucret_gercek_usd == pytest.approx(0.012) and not kayitlar(tmp_path, "dolum_px_yaklasik")


def test_d4_fills_bulunamazsa_limitpx_ve_mutabakat_notu(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, DolumSim())
    m.baslat()
    _niyet_yaz_ve_borsada_doldur(m, sim, saat)
    m.niyetleri_coz(saat())
    assert m.hesap.poz[adr(1)]["BTC"].giris == pytest.approx(100.5) and kayitlar(tmp_path, "dolum_px_yaklasik") and any(k["neden"] == "dolum_px_yaklasik" for k in m.mutabakat_tutan.values())


def test_d4_belirsiz_coz_gercek_fiyat_ve_ucret(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, DolumSim())
    m.baslat()
    cloid = _niyet_yaz_ve_borsada_doldur(m, sim, saat)
    m.hesap.belirsiz[cloid] = {"ms": saat() - 120_000, "deneme": 0, "adres": adr(1), "coin": "BTC"}
    sim.fills = [{"coin": "BTC", "oid": 7, "cloid": cloid, "sz": "0.27273", "px": "100.0", "fee": "0.012"}]
    assert m.belirsiz_coz(saat()) == 1
    assert m.hesap.poz[adr(1)]["BTC"].giris == pytest.approx(100.0) and m.hesap.ucret[adr(1)] == pytest.approx(0.012)


# ------------------------------------------------------------------ D6 / D8
def test_d6_stopsuz_tolerans_1800():
    assert kurallar.load_rules_asil()["canli_borsa_stop_korumasiz_sn"] == 1800


def test_d8_telegram_secretlari_isden_adimlara_tasindi_pip_install_gormez():
    yol = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "canli_vardiya.yml")
    wf = yaml.safe_load(open(yol, encoding="utf-8"))
    vardiya = wf["jobs"]["vardiya"]
    assert "TELEGRAM_BOT_TOKEN" not in vardiya["env"] and "TELEGRAM_CHAT_ID" not in vardiya["env"] and vardiya["env"]["TELEGRAM_KOMUT"] == "${{ vars.TELEGRAM_KOMUT }}"
    tokenli = [a.get("name") for a in vardiya["steps"] if "TELEGRAM_BOT_TOKEN" in (a.get("env") or {})]
    assert tokenli == ["Açılış kontrolü (anahtarsız, emir göndermez)", "Canlı motor (sanal kip)", "Alarm (Telegram, vardiya başarısız)"]
    for a in vardiya["steps"]:                                                            # üçüncü taraf kurulum adımları token görmez
        if "pip install" in str(a.get("run", "")):
            assert not (a.get("env") or {})
    motor = next(a for a in vardiya["steps"] if a.get("name") == "Canlı motor (sanal kip)")
    assert "copytrade.saglik" in motor["run"] and "TELEGRAM_CHAT_ID" in motor["env"]       # motor + içindeki sağlık döngüsü token'sız kalmaz
    assert wf["jobs"]["kontrol"]["steps"][-1]["env"]["TELEGRAM_BOT_TOKEN"] and wf["jobs"]["zincir"]["env"]["TELEGRAM_BOT_TOKEN"]


# ------------------------------------------------------------------ Telegram grup beyaz listesi
def _tg(kip, izinli=None, chat="-100123"):
    ortam = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": chat}
    if izinli is not None:
        ortam["TELEGRAM_IZINLI_ID"] = izinli
    t = tg.Telegram(ortam=ortam, post=SahteTG())
    t.kip = kip
    return t


def _mesaj(chat, kimden, bot=False):
    return {"chat": {"id": int(chat)}, "from": {"id": kimden, "is_bot": bot}, "text": "/kapat"}


def test_telegram_gercek_kipte_grup_izinli_id_bos_ise_komut_reddedilir():
    t = _tg("gercek")
    assert t.yetkili_mi(_mesaj(-100123, 555)) is False


def test_telegram_gercek_kipte_grup_from_id_beyaz_liste():
    t = _tg("gercek", izinli="555, 777")
    assert t.yetkili_mi(_mesaj(-100123, 555)) is True and t.yetkili_mi(_mesaj(-100123, 777)) is True
    assert t.yetkili_mi(_mesaj(-100123, 999)) is False and t.yetkili_mi(_mesaj(-100123, 555, bot=True)) is False and t.yetkili_mi(_mesaj(-100999, 555)) is False


def test_telegram_sanal_kip_ve_ozel_sohbet_davranisi_ayni():
    assert _tg("sanal").yetkili_mi(_mesaj(-100123, 999)) is True                                   # sanal + grup: eski davranış (beyaz liste yok)
    ozel = _tg("gercek", chat="42")
    assert ozel.yetkili_mi(_mesaj(42, 42)) is True and ozel.yetkili_mi(_mesaj(42, 43)) is False    # özel sohbet: from.id == chat_id


# ------------------------------------------------------------------ ortam dosyası izni
def test_ortam_dosyasi_izni_gercek_kip_acilisinda_zorunlu(tmp_path):
    iyi, kotu = tmp_path / "iyi.env", tmp_path / "kotu.env"
    iyi.write_text("A=1\n")
    kotu.write_text("A=1\n")
    os.chmod(iyi, 0o600)
    os.chmod(kotu, 0o644)
    mt.ortam_izin_zorunlu((str(iyi), str(tmp_path / "yok.env")))                                    # 600 + olmayan dosya: geçer
    with pytest.raises(mt.KipHatasi, match="izni güvensiz"):
        mt.ortam_izin_zorunlu((str(iyi), str(kotu)))
    assert stat.S_IMODE(os.stat(kotu).st_mode) == 0o644                                             # dosyaya dokunulmaz


def test_ortam_dosyasi_telegram_izinli_id_taniniyor():
    from copytrade.canli import ortam_dosyasi as od
    assert od.denetle("TELEGRAM_BOT_TOKEN=x\nTELEGRAM_CHAT_ID=-100\nTELEGRAM_IZINLI_ID=1,2\n", "telegram") == []
    assert any("IZINLI_ID" in s for s in od.denetle("TELEGRAM_BOT_TOKEN=x\nTELEGRAM_CHAT_ID=-100\nTELEGRAM_IZINLI_ID=a\n", "telegram"))


def test_ortam_izin_main_gercek_acilista_cagrilir():
    kaynak = inspect.getsource(mt.main)
    assert kaynak.index("ortam_izin_zorunlu()") < kaynak.index("motor_kilidi_al(")
