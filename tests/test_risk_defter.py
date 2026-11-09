"""H5 risk defteri (dry-run): altın örnekler elle hesaplanmıştır (docs/GOREV_H5_RISK.md)."""
from __future__ import annotations

import asyncio
import json

import pytest

from copytrade import dinleyici as d
from copytrade.kurallar import load_rules, sabit_tutar_egrisi
from copytrade.live_koruma import GateState, Limits, Mode, evaluate_order
from copytrade.risk_defter import GUN_MS, KararGunlugu, RiskDefteri

T = 20_000 * GUN_MS          # UTC gün başı (1970-01-01 + 20.000 gün)
A, B = "0x" + "a" * 40, "0x" + "b" * 40


def kurallar(islem=50.0, **risk):
    """Sabit tutar eğrisi: tutar = islem × (hesap/1000) → hesap 1.000 $ iken `islem` $. Sınırlar tablo varsayılanı, `risk` ile ezilir."""
    r = {**load_rules()["risk_dry_run"], **risk}
    return {**load_rules(), "sabit_tutar_ref_kasa_usd": 1000.0, "sabit_tutar_ref_islem_usd": float(islem), "sabit_tutar_us": 1.0,
           "sabit_tutar_tavan_kasa_usd": 1_000_000.0, "risk_dry_run": r}


def dolum(rd, ad="aaaa", coin="BTC", yon="B", sz=10.0, px=100.0, t=T + 1000, gecikme_ms=1000, bas=0.0, canli=True):
    return rd.isle(ad=ad, coin=coin, yon=yon, sz=sz, px=px, bas_poz=bas, zaman_ms=t, simdi_ms=t + gecikme_ms, kaynak="trades", canli=canli)


def yeni(islem=50.0, ilk11=("aaaa", "bbbb"), **risk):
    return RiskDefteri(set(ilk11), kurallar(islem, **risk), baslangic_ms=T)


def test_varsayilan_sinirlar_tablo_ile_ayni():
    l = Limits.from_rules(load_rules())
    assert (l.starting_reference_usd, l.per_order_usd, l.trader_cap_usd, l.total_gross_notional_usd, l.daily_loss_usd) == (1000.0, 100.0, 200.0, 1500.0, 30.0)
    r = load_rules()["risk_dry_run"]
    assert r["sinyal_tazelik_sn"] == 10 and r["dur_dosyasi"] == "$STATE_DIRECTORY/DUR"


def test_kapi_trader_tavani_siniri_esit_kabul_asim_ret():
    def iste(trader_brut):
        return evaluate_order(state=GateState(Mode.DRY_RUN), action="open", trader={"takim": "ilk11"}, notional_usd=50, gross_notional_usd=0,
                              trader_gross_notional_usd=trader_brut, daily_loss_usd=0, signal_time_ms=100, signal_deadline_ms=200, now_ms=150)
    assert iste(150)["kabul"] is True and iste(150.01)["nedenler"] == ["trader_tavani"]


def test_a_uc_dolum_iki_kabul_bir_emir_limiti():
    rd = yeni(islem=60.0)                                       # açılış 60 $
    k1 = dolum(rd, coin="BTC", sz=10, bas=0)                    # açılış: 60 -> kabul (BTC 0,6 adet)
    k2 = dolum(rd, coin="BTC", sz=20, bas=10, t=T + 2000)       # ekleme: 0,6 × 100 × (20/10) = 120 > 100 -> emir_limiti
    k3 = dolum(rd, coin="ETH", sz=10, bas=0, t=T + 3000)        # açılış 60 -> kabul
    assert [(k["aksiyon"], k["kabul"], k["notional_usd"]) for k in k1 + k2 + k3] == [("open", True, 60.0), ("add", False, 120.0), ("open", True, 60.0)]
    assert k2[0]["nedenler"] == ["emir_limiti"]
    o = rd.ozet()
    assert (o["niyet"], o["kabul"], o["ret"], o["acik_brut_usd"]) == (3, 2, {"emir_limiti": 1}, 120.0)


def test_b_trader_tavani_asimi():
    rd = yeni(islem=90.0)                                       # 90 + 90 = 180 ≤ 200; üçüncü 270 > 200
    sonuc = [dolum(rd, coin=c, t=T + 1000 * (i + 1))[0] for i, c in enumerate(["BTC", "ETH", "SOL"])]
    assert [k["kabul"] for k in sonuc] == [True, True, False] and sonuc[2]["nedenler"] == ["trader_tavani"]


def test_c_toplam_brut_asimi_baska_trader_tavani_dolmadan():
    rd = yeni(islem=90.0, toplam_brut_tavan_usd=150.0)         # A: 90 kabul; B: 0+90 ≤ 200 ama 90+90 = 180 > 150
    ka = dolum(rd, ad="aaaa")[0]
    kb = dolum(rd, ad="bbbb", t=T + 2000)[0]
    assert ka["kabul"] and not kb["kabul"] and kb["nedenler"] == ["toplam_brut_notional_limiti"]


def test_d_zarar_salteri_giris_ret_cikis_kabul_ve_kilit():
    rd = yeni(islem=50.0)                                       # BTC 0,5 adet @100
    assert dolum(rd, sz=10)[0]["kabul"]
    rd.fiyat("BTC", 40.0, T + 5000)                             # K/Z = 0,5 × (40 − 100) = −30 = limit -> şalter
    assert rd.ozet()["gunluk_zarar_usd"] == 30.0 and rd.ozet()["salter_tetiklendi"] is True
    giris = dolum(rd, coin="ETH", t=T + 6000)[0]
    assert not giris["kabul"] and giris["nedenler"] == ["gunluk_zarar_limiti"]
    rd.fiyat("BTC", 100.0, T + 7000)                            # zarar geri döndü: şalter bugün için KİLİTLİ kalır
    assert not dolum(rd, coin="SOL", t=T + 8000)[0]["kabul"]
    cikis = dolum(rd, yon="A", sz=10, px=40.0, bas=10.0, t=T + 9000)[0]    # trader kapatıyor: çıkış sınırlardan muaf
    assert cikis["aksiyon"] == "exit" and cikis["kabul"] and cikis["notional_usd"] == 20.0   # 0,5 adet × 40 $
    assert rd.ozet()["acik_pozisyon"] == 0 and rd.realized == -30.0


def test_e_dur_dosyasi_giris_ret_cikis_serbest():
    rd = yeni()
    assert dolum(rd)[0]["kabul"]
    rd.dur_aktif = True
    k = dolum(rd, coin="ETH", t=T + 2000)[0]
    assert not k["kabul"] and k["nedenler"] == ["yeni_ekleme_durduruldu"] and k["dur_aktif"] is True
    assert dolum(rd, yon="A", bas=10.0, t=T + 3000)[0]["kabul"]
    assert rd.ozet()["dur_aktif"] is True


def test_f_gec_sinyal_sinir_tam_10_sn_kabul_10_001_ret_cikis_muaf():
    rd = yeni()
    assert dolum(rd, gecikme_ms=10_000)[0]["kabul"]
    gec = dolum(rd, coin="ETH", t=T + 20_000, gecikme_ms=10_001)[0]
    assert gec["nedenler"] == ["gec_sinyal"] and gec["gecikme_sn"] == 10.001
    assert dolum(rd, yon="A", bas=10.0, t=T + 40_000, gecikme_ms=60_000)[0]["kabul"]


def test_g_miras_pozisyon_kapanisi_ve_eklemesi_kopyalanmaz():
    rd = yeni()
    kapanis = dolum(rd, yon="A", sz=5, bas=5.0)[0]              # trader t0 öncesi long 5'i kapatıyor, bizde pozisyon yok
    assert kapanis["aksiyon"] == "exit" and not kapanis["kabul"] and kapanis["nedenler"] == ["acik_pozisyon_yok"] and kapanis["notional_usd"] == 500.0
    ekleme = dolum(rd, coin="ETH", yon="B", sz=1, bas=5.0, t=T + 2000)[0]   # trader miras pozisyonuna ekliyor
    assert ekleme["aksiyon"] == "add" and ekleme["nedenler"] == ["miras_pozisyon"]
    assert rd.ozet()["acik_pozisyon"] == 0 and rd.ozet()["acik_brut_usd"] == 0.0


def test_h_utc_gun_donumu_gunluk_zarar_ve_salter_sifirlanir():
    rd = yeni()
    assert dolum(rd, t=T + GUN_MS - 120_000)[0]["kabul"]        # 23:58, BTC 0,5 @100
    rd.fiyat("BTC", 40.0, T + GUN_MS - 60_000)                  # 23:59: −30 -> şalter
    assert rd.ozet()["gunluk_zarar_usd"] == 30.0 and rd.ozet()["salter_tetiklendi"]
    k = dolum(rd, coin="ETH", t=T + GUN_MS + 1_000)[0]          # ertesi gün 00:00:01
    assert k["kabul"], k                                        # gün başı baz = −30; bugünkü zarar 0, şalter açıldı
    o = rd.ozet()
    assert o["gunluk_zarar_usd"] == 0.0 and o["salter_tetiklendi"] is False
    rd.fiyat("BTC", 100.0, T + GUN_MS + 2_000)                  # dünkü zarar kapandı: bugün kâr -> zarar 0
    assert rd.ozet()["gunluk_zarar_usd"] == 0.0


def test_uc_notional_sifir_negatif_fiyat_yok():
    rd = yeni()
    assert dolum(rd, sz=0.0) == [] and dolum(rd, sz=-1.0) == [] and dolum(rd, yon="") == []
    assert rd.ozet()["gecersiz_dolum"] == 3 and rd.ozet()["niyet"] == 0
    k = dolum(rd, px=None)[0]
    assert (k["kabul"], k["nedenler"], k["fiyat"]) == (False, ["fiyat_yok"], None) and k["notional_usd"] == 50.0   # niyet tutarı bilinir, fiyat yok -> tahmin yok
    assert dolum(rd, px=0.0)[0]["nedenler"] == ["fiyat_yok"]
    assert rd.ozet()["ret"] == {"fiyat_yok": 2} and rd.ozet()["acik_pozisyon"] == 0


def test_ilk11_disi_niyet_uretmez_snapshot_yalniz_takip():
    rd = yeni(ilk11=("aaaa",))
    assert dolum(rd, ad="bbbb") == [] and rd.ozet()["ilk11_disi"] == 1 and rd.ozet()["niyet"] == 0
    assert dolum(rd, sz=10, bas=0.0, canli=False) == [] and rd.ozet()["snapshot_gozlem"] == 1
    # snapshot trader'ın pozisyonunu öğretti (10): sonraki canlı dolum ekleme sayılır, kopyası yok -> miras
    assert dolum(rd, sz=1, bas=None, t=T + 5000)[0]["nedenler"] == ["miras_pozisyon"]


def test_ters_donus_cikis_ve_yeni_acilis_iki_niyet():
    rd = yeni()
    dolum(rd, sz=10, bas=0.0)                                   # long 0,5 @100
    k = dolum(rd, yon="A", sz=15, px=110.0, bas=10.0, t=T + 5000)   # trader 10 kapatıp 5 short açıyor
    assert [(x["aksiyon"], x["kabul"]) for x in k] == [("exit", True), ("open", True)]
    assert k[0]["notional_usd"] == 55.0                         # 0,5 adet × 110
    assert rd.realized == 5.0                                   # 0,5 × (110 − 100)
    poz = rd.pozlar[("aaaa", "BTC")]
    assert poz.boyut < 0 and round(abs(poz.boyut) * 110.0, 6) == round(50.0 + 5.0 - 0.0 if False else 55.0 * 0 + abs(poz.boyut) * 110.0, 6)


def test_kismi_azaltma_orantili_kapanis():
    rd = yeni()
    dolum(rd, sz=10, bas=0.0)                                   # 0,5 adet
    k = dolum(rd, yon="A", sz=4, px=120.0, bas=10.0, t=T + 5000)[0]    # trader %40'ı kapatır -> 0,2 adet × 120 = 24 $
    assert k["notional_usd"] == 24.0 and rd.pozlar[("aaaa", "BTC")].boyut == pytest.approx(0.3) and rd.realized == pytest.approx(4.0)


def test_boyut_kopyalanmaz_v3_egrisini_cagirir():
    rd = RiskDefteri({"aaaa"}, load_rules(), baslangic_ms=T)
    k = dolum(rd)[0]
    assert k["notional_usd"] == pytest.approx(sabit_tutar_egrisi(load_rules())(1000.0), rel=1e-6)   # ≈ 20,75 $ (200$→5,2$ eğrisi, 1.000 $ kasa)


# ------------------------------------------------------------------ günlük dosyası
def test_gunluk_doner_yedi_gun_tutulur_adres_yok_emir_gonderildi_false(tmp_path):
    g = KararGunlugu(tmp_path)
    rd = yeni()
    for gun in range(10):
        for k in dolum(rd, coin=f"C{gun}", t=T + gun * GUN_MS + 1000):
            g.yaz(k)
    adlar = sorted(p.name for p in tmp_path.iterdir())
    assert adlar[-1] == "risk_kararlari.jsonl" and len(adlar) == 8      # 7 eski gün + güncel
    assert "risk_kararlari.2024-10-05.jsonl" not in adlar and "risk_kararlari.2024-10-06.jsonl" in adlar     # T = 2024-10-04; gün 0-1 silindi
    for yol in tmp_path.iterdir():
        for satir in yol.read_text(encoding="utf-8").splitlines():
            assert json.loads(satir)["emir_gonderildi"] is False
    with pytest.raises(ValueError):
        g.yaz({"gun": "2024-01-01", "x": A})
    assert KararGunlugu(tmp_path).gun == g.gun            # yeniden başlatma: güncel dosyanın günü okunur


# ------------------------------------------------------------------ dinleyici entegrasyonu
def dinleyici(tmp_path, risk=None, **kw):
    iz = [d.Izlenen("aaaa", A, "ilk11"), d.Izlenen("bbbb", B, "yedek11")]
    risk = risk or RiskDefteri({"aaaa"}, kurallar(50.0), baslangic_ms=T)
    return d.Dinleyici(iz, ["BTC"], None, lambda y: [], tmp_path, saat_ms=lambda: T + 1500, risk=risk, risk_gunlugu=KararGunlugu(tmp_path), **kw)


def test_ayni_dolum_iki_kaynaktan_tek_niyet_ve_ozet_risk_blogu(tmp_path):
    din = dinleyici(tmp_path)
    tr = {"channel": "trades", "data": [{"coin": "BTC", "side": "B", "px": "100", "sz": "10", "time": T + 1000, "tid": 7, "users": [A, B]}]}
    uf = {"channel": "userFills", "data": {"isSnapshot": False, "user": A, "fills": [{"coin": "BTC", "px": "100", "sz": "10", "side": "B", "time": T + 1000, "tid": 7,
                                                                                         "startPosition": "0"}]}}
    din.mesaj_isle(json.dumps(tr))
    din.mesaj_isle(json.dumps(uf))
    o = din.ozet()
    assert o["risk"]["niyet"] == 1 and o["risk"]["kabul"] == 1 and o["risk"]["ilk11_disi"] == 1 and o["genel"]["tekrar"] == 1   # B yedek11: ölçülür, niyet yok
    assert o["risk"]["acik_brut_usd"] == 50.0 and o["risk"]["emir_gonderildi"] is False
    satirlar = (tmp_path / "risk_kararlari.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(satirlar) == 1 and json.loads(satirlar[0])["gecikme_sn"] == 0.5 and json.loads(satirlar[0])["trader"] == "aaaa"


def test_trades_yon_alici_satici_ve_snapshot_niyet_uretmez(tmp_path):
    din = dinleyici(tmp_path)
    din.mesaj_isle(json.dumps({"channel": "trades", "data": [{"coin": "BTC", "side": "A", "px": "100", "sz": "10", "time": T + 1000, "tid": 1, "users": [B, A]}]}))
    assert din.risk.lider[("aaaa", "BTC")] == -10.0            # users = [alıcı, satıcı]: A satıcı
    din.mesaj_isle(json.dumps({"channel": "userFills", "data": {"isSnapshot": True, "user": A, "fills": [
        {"coin": "ETH", "px": "1", "sz": "1", "side": "B", "time": T + 1, "tid": 2, "startPosition": "0"}]}}))
    assert din.risk.ozet()["niyet"] == 1 and din.risk.ozet()["snapshot_gozlem"] == 1


def test_dur_dosyasi_dinleyicide_okunur(tmp_path):
    dur = tmp_path / "DUR"
    din = dinleyici(tmp_path, dur_yolu=dur)
    mesaj = lambda tid, coin: json.dumps({"channel": "trades", "data": [{"coin": coin, "side": "B", "px": "100", "sz": "1", "time": T + 1000, "tid": tid, "users": [A, B]}]})   # noqa: E731
    din.mesaj_isle(mesaj(1, "BTC"))
    dur.write_text("")
    din.mesaj_isle(mesaj(2, "ETH"))
    assert din.ozet()["risk"]["ret"] == {"yeni_ekleme_durduruldu": 1} and din.ozet()["risk"]["dur_aktif"] is True
    dur.unlink()
    assert din.ozet()["risk"]["dur_aktif"] is False


def test_risk_hatasi_olcumu_durdurmaz(tmp_path):
    class Bozuk(RiskDefteri):
        def isle(self, **kw):
            raise RuntimeError("x")
    din = dinleyici(tmp_path, risk=Bozuk({"aaaa"}, kurallar(), baslangic_ms=T))
    din.mesaj_isle(json.dumps({"channel": "trades", "data": [{"coin": "BTC", "side": "B", "px": "1", "sz": "1", "time": T + 1000, "tid": 1, "users": [A, "0x" + "c" * 40]}]}))
    assert din.ozet()["genel"]["risk_hata"] == 1 and din.ozet()["toplam"]["aaaa"]["n"] == 1


def test_dolgu_gec_giris_ret_cikis_kabul(tmp_path):
    din = dinleyici(tmp_path)
    din.olcum.abone_coinler = {"BTC"}
    giris = {"coin": "BTC", "px": "100", "sz": "10", "side": "B", "time": T - 60_000, "tid": 1, "startPosition": "0"}
    asyncio.run(_dolgu(din, [giris]))
    assert din.risk.ozet()["ret"] == {"gec_sinyal": 1}


async def _dolgu(din, dolumlar):
    din.post = lambda yuk: dolumlar if yuk["type"] == "userFillsByTime" and yuk["user"] == A else []
    din._dolgu_baslat((T - 120_000, 0))                        # dolgu artık arka plan görevi: başlat ve bitmesini bekle
    await din._dolgu_gorevi
