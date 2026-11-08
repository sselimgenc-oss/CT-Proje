"""G-14 (bayat snapshot poz_tr'yi eziyor), G-17a (sessiz kopma), G-17b (kopma dolumu emir üretmiyor), S-1 (senkronda kısmi azaltma). Denetim: docs/DENETIM_PROJE_2026-11-08.md.

Altın örnekler elle: kasa 1.000 $ → slot 90,909 $; trader hesabı 100.000 $; trader 300 BTC × 100 $ açar → oran 0,30 → emir 27,2727 $ → 0,272727 BTC (ask 100).
Trader 300 → 150 (yarıya) → hedef 90,909 × 150 × 100 / 100.000 = 13,6364 $; bizde 27,2727 $ → azalt 13,6364 $ (bid 99,9) → kalan 0,272727 − 13,6364 / 99,9 BTC."""
import asyncio
import json
import time

import pytest

from copytrade import dinleyici as d
from copytrade.canli import motor as mt
from tests.test_canli_motor import SAAT, SahteHL, SahteWS, adr, kayitlar, kur, olay, userfills


def snap_olay(kimlik, adres, coin, yon, sz, px, bas_poz, zaman_ms, alma_ms, kaynak="userFills"):
    return d.Olay(kimlik, adres[:12], adres, zaman_ms, alma_ms, kaynak, kaynak == "userFills", f"userFills:{adres}" if kaynak == "userFills" else coin, coin, px, sz, yon, bas_poz)


# ------------------------------------------------------------------------------------------------ G-14 (a): eşikten eski snapshot dolumu poz_tr'yi değiştirmez
def test_g14_altin_senkrondan_eski_snapshot_dolumu_poz_tr_degistirmez_yenisi_uygulanir(tmp_path):
    hl = SahteHL(pozlar={adr(1): {"BTC": 300.0}})
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.baslat()                                                                     # REST: trader 300 BTC (okuma anı = saat())
    m.senkron_uygula(m.senkron_oku())
    assert m.poz_tr[adr(1)] == {"BTC": 300.0}
    eski = snap_olay(f"{adr(1)}:900", adr(1), "BTC", "B", 300, 100.0, 0.0, saat() - 10 * SAAT, saat())     # 10 sa önceki açılış dolumu (bas_poz 0 → 300) snapshot'la yeniden geldi
    assert m.olay_isle(eski, canli=False) == []
    assert m.poz_tr[adr(1)] == {"BTC": 300.0}                                      # eski kod: once = bas_poz 0, sonra 300 (aynı) — trades kanalı kopyasıyla 600 olurdu
    eski_trades = snap_olay(f"{adr(1)}:901", adr(1), "BTC", "B", 300, 100.0, None, saat() - 10 * SAAT, saat(), kaynak="trades")
    m.olay_isle(eski_trades, canli=False)
    assert m.poz_tr[adr(1)] == {"BTC": 300.0}                                      # eski kod: 300 + 300 = 600 (iz: 0xda9f BTC 0,662 → 1,325, tam 2×)
    saat.ms += 5_000
    yeni = snap_olay(f"{adr(1)}:902", adr(1), "BTC", "A", 100, 100.0, 300.0, saat() - 1_000, saat())        # senkrondan SONRA olan dolum: uygulanır
    m.olay_isle(yeni, canli=False)
    assert m.poz_tr[adr(1)] == {"BTC": 200.0}


def test_g14_altin_yeniden_baslatmada_listeden_dusmus_eski_dolum_poz_tr_ezmez(tmp_path):
    """Gerçek iz 11-08 00:20 0x323f BTC [2,90 → 0]: vardiya sonunda poz_tr doğru (kapalı); yeni vardiyanın snapshot'ı `islenen`den düşmüş eski açılışı (0 → 2,90) yeniden getirdi."""
    m, _, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("x:1", adr(1), "BTC", "B", 2.9, 100.0, 0.0, saat))           # açılış
    m.olay_isle(olay("x:2", adr(1), "BTC", "A", 2.9, 100.0, 2.9, saat))           # kapanış
    assert adr(1) not in m.poz_tr or "BTC" not in m.poz_tr[adr(1)]
    m.durum_yaz()
    saat.ms += 30 * 60_000
    m2, _, _, _ = kur(tmp_path, saat=saat)                                         # yeniden başlatma: poz_tr ve eşikler motor.json'dan
    m2.baslat()
    eski = snap_olay(f"{adr(1)}:777", adr(1), "BTC", "B", 2.9, 100.0, 0.0, saat() - 40 * 60_000, saat())   # `islenen`de YOK (eski kod uygulardı → 2,90)
    assert m2.olay_isle(eski, canli=False) == []
    assert m2.poz_tr.get(adr(1), {}).get("BTC", 0.0) == 0.0
    yaz = json.loads((tmp_path / "durum" / "motor.json").read_text())                # eşikler kalıcı (G-14)
    assert yaz["poz_tr_ms"][f"{adr(1)}|BTC"] == saat() - 30 * 60_000 - 1000 and adr(1) in yaz["poz_tr_senk_ms"]


def test_g14_eski_bicim_motor_json_gecisi_esik_son_olay_ms(tmp_path):
    (tmp_path / "durum").mkdir()
    (tmp_path / "durum" / "motor.json").write_text(json.dumps({"islenen": [], "poz_tr": {adr(1): {"ZEC": -100.0}}, "son_olay_ms": 1_000}))
    m, _, saat, _ = kur(tmp_path)
    assert m._poz_tr_senk_ms == {adr(1): 1_000}
    m.olay_isle(snap_olay(f"{adr(1)}:5", adr(1), "ZEC", "A", 50, 300.0, 0.0, 999, saat()), canli=False)        # eşikten eski: −100 kalır (iz 0x8730 ZEC −50/−100)
    assert m.poz_tr[adr(1)] == {"ZEC": -100.0}


def test_g14_islenen_adres_basina_yogun_adres_digerini_dusurmez(tmp_path):
    m, _, saat, _ = kur(tmp_path, kurallar={"canli_islenen_adres_sakla": 3})
    m._gorulduysa_isaretle(f"{adr(1)}:1")
    for i in range(10):
        m._gorulduysa_isaretle(f"{adr(2)}:{i}")
    assert f"{adr(1)}:1" in m.islenen and [k for k in m.islenen if k.startswith(adr(2))] == [f"{adr(2)}:{i}" for i in (7, 8, 9)]
    m.durum_yaz()
    m2, _, _, _ = kur(tmp_path, saat=saat, kurallar={"canli_islenen_adres_sakla": 3})
    assert m2._gorulduysa_isaretle(f"{adr(1)}:1") and not m2._gorulduysa_isaretle(f"{adr(2)}:6")


# ------------------------------------------------------------------------------------------------ G-14 (b): aynı tid iki kanaldan bir kez
def test_g14_altin_ayni_tid_iki_kanaldan_bir_kez_uygulanir(tmp_path):
    m, _, saat, _ = kur(tmp_path)
    m.baslat()
    k = f"{adr(1)}:42"
    trades = d.Olay(k, adr(1)[:12], adr(1), saat() - 1000, saat(), "trades", False, "BTC", "BTC", 100.0, 300.0, "B", None)
    uf = d.Olay(k, adr(1)[:12], adr(1), saat() - 1000, saat(), "userFills", False, f"userFills:{adr(1)}", "BTC", 100.0, 300.0, "B", 0.0)
    assert [(s.eylem, s.karar) for s in m.olay_isle(trades)] == [("ac", "emir")]
    assert m.olay_isle(uf) == []
    assert m.poz_tr[adr(1)] == {"BTC": 300.0} and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.272727, abs=1e-6) and m.sayac["emir"] == 1
    k2 = f"{adr(1)}:43"                                                            # snapshot iki kanaldan: poz_tr bir kez (300 → 400, 500 değil)
    saat.ms += 1
    m.olay_isle(d.Olay(k2, adr(1)[:12], adr(1), saat(), saat(), "trades", True, "BTC", "BTC", 100.0, 100.0, "B", None), canli=False)
    m.olay_isle(d.Olay(k2, adr(1)[:12], adr(1), saat(), saat(), "userFills", True, f"userFills:{adr(1)}", "BTC", 100.0, 100.0, "B", 300.0), canli=False)
    assert m.poz_tr[adr(1)] == {"BTC": 400.0}


def test_g14_dinleyici_ayni_tid_trades_ve_userfills_tek_olay(tmp_path):
    kuyruk: asyncio.Queue = asyncio.Queue()
    din = mt.CanliDinleyici(kuyruk, [d.Izlenen(adr(1)[:12], adr(1))], ["BTC"], None, lambda y: [], tmp_path, d.Ayar(), saat_ms=lambda: 1_000_000)
    din.olcum.abone = {"BTC": 0, f"userFills:{adr(1)}": 0}
    din.mesaj_isle(json.dumps({"channel": "trades", "data": [{"coin": "BTC", "px": "100", "sz": "300", "time": 999_000, "tid": 7, "users": [adr(1), adr(2)]}]}))
    din.mesaj_isle(json.dumps(userfills(adr(1), 7, 999_000)))
    assert kuyruk.qsize() == 1 and din.olcum.genel["tekrar"] == 1


# ------------------------------------------------------------------------------------------------ G-17b (c): kopukken olan dolum snapshot + REST → dolgu → emir
def test_g17b_altin_kopma_dolumu_snapshotta_gelse_de_dolguyla_emir_uretir(tmp_path):
    """Bağlantı 1 tid 1'i (açılış 0 → 300) canlı görür, kopar. Kopukken trader kapattı (tid 2: 300 → 0). Bağlantı 2'nin snapshot'ı tid 1 + tid 2'yi verir; REST'te tid 2 var.
    Beklenen: tid 2 önce snapshot (canlı değil, emir yok, poz_tr 0), sonra dolgu (canlı) → motor KAPAT emri verir; bizim BTC 0,272727 → 0. Eski kod: dolgu tid 2'yi `gorulen` diye atlıyordu (pozisyon açık kalırdı)."""
    m, _, saat, _ = kur(tmp_path)
    m.baslat()
    t = saat()
    f1 = {"coin": "BTC", "px": "100", "sz": "300", "side": "B", "time": t, "tid": 1, "startPosition": "0"}
    f2 = {"coin": "BTC", "px": "100", "sz": "300", "side": "A", "time": t, "tid": 2, "startPosition": "300"}
    ws = [SahteWS([{"channel": "userFills", "data": {"isSnapshot": False, "user": adr(1), "fills": [f1]}}]),
          SahteWS([{"channel": "userFills", "data": {"isSnapshot": True, "user": adr(1), "fills": [f1, f2]}}], "bekle")]
    sira = {"i": 0}

    async def baglan():
        w = ws[min(sira["i"], 1)]
        sira["i"] += 1
        return w

    def post(y):
        return [f1, f2] if y["type"] == "userFillsByTime" else []
    kuyruk: asyncio.Queue = asyncio.Queue()
    din = mt.CanliDinleyici(kuyruk, [d.Izlenen(adr(1)[:12], adr(1))], ["BTC"], baglan, post, tmp_path / "din",
                            d.Ayar(rest_dolum_ara_sn=0.0, rest_poz_ara_sn=0.0, sure_sn=0.5, geri_cekilme_ilk_sn=0.01, geri_cekilme_max_sn=0.02), saat_ms=saat)
    asyncio.run(din.calis())
    olaylar = []
    while not kuyruk.empty():
        olaylar.append(kuyruk.get_nowait())
    assert [(o.kimlik, o.kaynak, canli) for o, canli in olaylar] == [(f"{adr(1)}:1", "userFills", True), (f"{adr(1)}:2", "userFills", False), (f"{adr(1)}:2", "dolgu", True)]
    sonuclar = [m.olay_isle(o, canli) for o, canli in olaylar]
    assert [[(s.eylem, s.karar) for s in x] for x in sonuclar] == [[("ac", "emir")], [], [("kapat", "emir")]]
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-12) and m.poz_tr.get(adr(1), {}).get("BTC", 0.0) == 0.0 and m.sayac["emir"] == 2


def test_g17b_olcum_dolgu_yalniz_canli_goruleni_atlar():
    o = d.Olcum([d.Izlenen("a", adr(1))])
    o.abone = {f"userFills:{adr(1)}": 2_000}
    canli = d.Olay(f"{adr(1)}:1", "a", adr(1), 2_100, 2_200, "userFills", False, f"userFills:{adr(1)}", "BTC", 1.0, 1.0, "B", 0.0)
    snap = d.Olay(f"{adr(1)}:2", "a", adr(1), 1_500, 2_200, "userFills", True, f"userFills:{adr(1)}", "BTC", 1.0, 1.0, "B", 1.0)
    assert o.olay(canli) and o.olay(snap)
    rest = [{"coin": "BTC", "px": "1", "sz": "1", "side": "B", "time": z, "tid": t, "startPosition": "0"} for t, z in ((1, 2_100), (2, 1_500))]
    assert o.dolgu("a", adr(1), rest, 1_000, 3_000) == 1 and [f["tid"] for _, f in o.dolgu_yeni] == [2]
    o.dolgu_yeni = []
    assert o.dolgu("a", adr(1), rest, 1_000, 3_000) == 0                          # ikinci dolgu aynı dolumu tekrar vermez


# ------------------------------------------------------------------------------------------------ G-17a (d): sessiz soket → alma_zaman_asimi_sn içinde yeniden bağlanma
def test_g17a_sessiz_soket_alma_zaman_asiminda_yeniden_baglanir(tmp_path):
    class OluWS:                     # yarı açık TCP: send hata vermez, recv hiç dönmez
        async def send(self, ham):
            pass

        async def recv(self):
            await asyncio.sleep(3600)

        async def close(self):
            pass
    anlar = []

    async def baglan():
        anlar.append(time.monotonic())
        return OluWS()
    ayar = d.Ayar(rest_dolum_ara_sn=0.0, rest_poz_ara_sn=0.0, sure_sn=1.2, ping_sn=0.2, alma_zaman_asimi_sn=0.3, rest_aralik_sn=999, geri_cekilme_ilk_sn=0.05, geri_cekilme_max_sn=0.05)
    din = d.Dinleyici([d.Izlenen("a", adr(1))], ["BTC"], baglan, lambda y: [], tmp_path, ayar)
    g = asyncio.run(din.calis())["genel"]
    assert g["kopma"] >= 2 and g["yeniden_baglanma"] >= 2 and g["alma_zaman_asimi"] == g["kopma"]
    assert anlar[1] - anlar[0] < 0.3 + 0.05 + 0.25                                # zaman aşımı + geri çekilme (+ zamanlama payı)


def test_g17a_mesaj_akarken_zaman_asimi_yok(tmp_path):
    class AkanWS:
        async def send(self, ham):
            pass

        async def recv(self):
            await asyncio.sleep(0.05)
            return json.dumps({"channel": "pong"})

        async def close(self):
            pass

    async def baglan():
        return AkanWS()
    din = d.Dinleyici([d.Izlenen("a", adr(1))], ["BTC"], baglan, lambda y: [], tmp_path, d.Ayar(sure_sn=0.8, alma_zaman_asimi_sn=0.3, rest_aralik_sn=999))
    assert asyncio.run(din.calis())["genel"]["kopma"] == 0


def test_g17a_ws_baglan_protokol_pingi_acik(monkeypatch):
    import websockets.asyncio.client as wc
    alinan = {}

    async def sahte_connect(url, **k):
        alinan.update(k)
        return object()
    monkeypatch.setattr(wc, "connect", sahte_connect)
    asyncio.run(d.ws_baglan("wss://ornek"))
    assert alinan["ping_interval"] == 20 and alinan["ping_timeout"] == 20


# ------------------------------------------------------------------------------------------------ S-1: senkronda kaçan kısmi azaltma
def test_s1_altin_senkron_rest_kucukse_hedef_tabanli_azaltir(tmp_path):
    hl = SahteHL()
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.piyasa_oku(saat())
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.272727, abs=1e-6)
    hl.pozlar = {adr(1): {"BTC": 150.0}}                                           # trader yarıya indi; azaltma dolumu WS'te kaçtı
    saat.ms += 60_000
    m.senkron_uygula(m.senkron_oku())
    e = kayitlar(tmp_path, "emir")[-1]
    assert e["eylem"] == "azalt" and e["yon"] == "A" and e["reduce_only"] is True and e["usd_istenen"] == pytest.approx(13.6364, abs=1e-4)
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.272727 - 13.6364 / 99.9, abs=1e-5)
    assert kayitlar(tmp_path, "senkron_azalt")[0]["karar"] == "emir" and m.poz_tr[adr(1)] == {"BTC": 150.0}
    m.senkron_uygula(m.senkron_oku())                                              # tutarlı: ikinci azaltma YOK
    assert len(kayitlar(tmp_path, "emir")) == 2


def test_s1_trader_buyurse_ya_da_bizde_pozisyon_yoksa_senkron_emir_vermez(tmp_path):
    hl = SahteHL()
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.piyasa_oku(saat())
    hl.pozlar = {adr(1): {"BTC": 450.0, "ETH": 5.0}}                               # büyüme senkronda kopyalanmaz (açılış yalnız canlı dolumla)
    saat.ms += 60_000
    m.poz_tr[adr(1)]["ETH"] = 10.0                                                 # ETH: bizde pozisyon yok → emir yok
    m.senkron_uygula(m.senkron_oku())
    assert len(kayitlar(tmp_path, "emir")) == 1 and not kayitlar(tmp_path, "senkron_azalt")
