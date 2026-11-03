"""H2 dinleyici (copytrade/dinleyici.py): ELLE hesaplı altın örnekler (docs/GOREV_H2_DINLEYICI.md) + uç durumlar. Ağ yok: sahte WS ve sahte REST."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from copytrade import dinleyici as d

A, B, C = "0x" + "a" * 40, "0x" + "b" * 40, "0x" + "c" * 40
IZ = [d.Izlenen("aaaa", A), d.Izlenen("bbbb", B)]
IZD = {i.adres: i for i in IZ}


def trades(*satirlar):
    """satirlar: (tid, zaman_ms, [kullanıcılar])"""
    return {"channel": "trades", "data": [{"coin": "BTC", "side": "B", "px": "1", "sz": "1", "time": t, "hash": "0x0", "tid": tid, "users": users} for tid, t, users in satirlar]}


def userfills(adres, *satirlar, snapshot=False):
    return {"channel": "userFills", "data": {"isSnapshot": snapshot, "user": adres, "fills": [{"coin": "BTC", "px": "1", "sz": "1", "side": "B", "time": t, "tid": tid} for tid, t in satirlar]}}


# ------------------------------------------------------------------------------------------------ altın örnekler
def test_golden_gecikme_medyan_ve_p95_en_yakin_sira():
    """Gecikmeler [0,4; 0,6; 1,0; 2,0; 5,0] sn -> medyan 1,0; p95: sıra = ceil(0,95·5) = 5 -> 5,0."""
    t = d.TraderOlcum(gecikme=[2.0, 0.4, 5.0, 0.6, 1.0])
    o = t.ozet()
    assert (o["n"], o["gecikme_medyan_sn"], o["gecikme_p95_sn"], o["gecikme_max_sn"]) == (5, 1.0, 5.0, 5.0)
    assert d.p_sira([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == 10 and d.p_sira([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.5) == 5 and d.p_sira([], 0.95) is None


def test_golden_isSnapshot_kabul_ve_gecikme_ornegi_sifir():
    o = d.Olcum(IZ)
    for ev in d.userfills_olaylari(userfills(A, (1, 1000), (2, 2000), snapshot=True), IZD, 9_999_000):
        assert o.olay(ev) is True                                  # yeni dolum ama snapshot
    t = o.toplam["aaaa"]
    assert t.snapshot == 2 and t.gecikme == [] and t.negatif == 0 and o.saat["aaaa"].snapshot == 2


def test_golden_rest_5_dolum_ws_4_kacan_1():
    o = d.Olcum(IZ)
    for tid in (1, 2, 3, 4):
        o.olay(d.Olay(f"{A}:{tid}", "aaaa", A, 1000 + tid, 1100 + tid, "trades"))
    rest = [{"tid": tid, "time": 1000 + tid} for tid in (1, 2, 3, 4, 5)]
    assert o.rest_karsilastir("aaaa", A, rest, simdi_ms=10_000_000, tolerans_ms=120_000) == 1
    assert o.toplam["aaaa"].kacan == 1 and o.saat["aaaa"].kacan == 1
    assert o.rest_karsilastir("aaaa", A, rest, 10_000_000, 120_000) == 0       # kaçan görülmüş sayılır: ikinci kez sayılmaz
    # çok yeni dolum (tolerans içinde) kaçan sayılmaz
    assert o.rest_karsilastir("aaaa", A, [{"tid": 99, "time": 9_950_000}], 10_000_000, 120_000) == 0


def test_golden_ayni_tid_trades_ve_userfills_tekil_1():
    o = d.Olcum(IZ)
    bir = d.trades_olaylari(trades((7, 5000, [A, C])), IZD, 5300)
    iki = d.userfills_olaylari(userfills(A, (7, 5000)), IZD, 5900)
    assert [e.kimlik for e in bir] == [e.kimlik for e in iki] == [f"{A}:7"]
    assert o.olay(bir[0]) is True and o.olay(iki[0]) is False
    assert o.genel["tekrar"] == 1 and o.toplam["aaaa"].gecikme == [0.3]        # ilk gelen (trades, 300 ms) ölçülür


def test_negatif_gecikme_saat_kaymasi_ayri_sayilir_gecikmeye_girmez():
    o = d.Olcum(IZ)
    o.olay(d.Olay(f"{A}:1", "aaaa", A, 5000, 4000, "trades"))                    # alma anı dolum zamanından ÖNCE
    o.olay(d.Olay(f"{A}:2", "aaaa", A, 5000, 5500, "trades"))
    t = o.toplam["aaaa"]
    assert t.negatif == 1 and t.gecikme == [0.5]
    ozet = o.ozet(10_000, 0)
    assert ozet["negatif_gecikme_toplam"] == 1 and ozet["saat_kaymasi_uyarisi"] is True


def test_trades_users_suzme_iki_izlenen_iki_olay_izlenmeyen_yok():
    m = trades((1, 1000, [A, B]), (2, 1000, [C, "0x" + "d" * 40]), (3, 1000, [A, A]), {"x": 1} and (4, 1000, None))
    ev = d.trades_olaylari(m, IZD, 1500)
    assert sorted(e.kimlik for e in ev) == sorted([f"{A}:1", f"{B}:1", f"{A}:3"])        # kendi kendine işlem tek olay; users alanı yoksa atlanır
    assert d.trades_olaylari({"channel": "trades", "data": [{"tid": 1, "time": 1}]}, IZD, 1) == []


def test_sifir_dolumlu_trader_ozeti_ve_ozet_adres_icermez(tmp_path):
    o = d.Olcum(IZ)
    o.olay(d.Olay(f"{A}:1", "aaaa", A, 1000, 1400, "trades"))
    ozet = o.ozet(2000, 0)
    assert ozet["toplam"]["bbbb"] == {"n": 0, "gecikme_medyan_sn": None, "gecikme_p95_sn": None, "gecikme_max_sn": None, "kacan": 0, "kacan_sinif": {}, "snapshot": 0, "negatif_gecikme": 0}
    assert ozet["toplam"]["aaaa"]["gecikme_medyan_sn"] == 0.4
    d.ozet_yaz(tmp_path / "ozet.json", ozet)
    metin = (tmp_path / "ozet.json").read_text()
    assert "0x" not in metin and json.loads(metin)["surum"] == 1
    with pytest.raises(ValueError, match="adres"):
        d.ozet_yaz(tmp_path / "x.json", {"adres": A})


def test_rest_sayfalama_tam_sayfa_sinirinda_ikinci_sayfa():
    sayfa1 = [{"tid": i, "time": 1000 + i} for i in range(d.REST_SAYFA)]                  # tam sayfa (2000): devam edilir
    sayfa2 = [{"tid": 5000, "time": 1000 + d.REST_SAYFA + 5}]
    cagrilar = []

    def post(yuk):
        cagrilar.append(yuk["startTime"])
        return sayfa1 if len(cagrilar) == 1 else sayfa2
    sonuc = d.rest_dolumlar(post, A, 1000, 10 ** 9)
    assert len(sonuc) == d.REST_SAYFA + 1 and cagrilar == [1000, 1000 + d.REST_SAYFA - 1]
    assert d.rest_dolumlar(lambda y: [], A, 1000, 2000) == [] and d.rest_dolumlar(lambda y: sayfa2, A, 5000, 4000) == []   # bas > bit: istek yok
    with pytest.raises(ValueError, match="ilerlemiyor"):
        d.rest_dolumlar(lambda y: [{"tid": i, "time": 500} for i in range(d.REST_SAYFA)], A, 1000, 10 ** 9)
    with pytest.raises(ValueError, match="liste"):
        d.rest_dolumlar(lambda y: {"hata": 1}, A, 1000, 2000)


# ------------------------------------------------------------------------------------------------ liste (fail-closed)
def liste_yaz(yol: Path, satirlar):
    yol.write_text(yaml.safe_dump({"traderlar": satirlar}))


def test_liste_oku_k12_8_kapsami_takma_ad_ve_fail_closed(tmp_path):
    satirlar = [{"id": "K0001", "adres": A, "takma_ad": "aaaa", "durum": "izlemede", "t0": "2026-11-01", "takim": "ilk11", "snapshot_id": "f" * 64, "takim_hafta": "2026-11-01"},
                {"id": "R1", "adres": B, "takma_ad": "aaaa", "durum": "izlemede", "t0": "2026-10-28", "kol": "referans_oda", "kollar": ["referans_oda"]}]
    liste_yaz(tmp_path / "l.yaml", satirlar)
    iz = d.liste_oku(tmp_path / "l.yaml")
    assert [i.ad for i in iz] == ["aaaa-K0001", "aaaa-R1"] and [i.adres for i in iz] == [A, B]       # yinelenen takma ad id ile ayrılır
    with pytest.raises(ValueError, match="fail-closed"):
        d.liste_oku(tmp_path / "yok.yaml")
    liste_yaz(tmp_path / "bos.yaml", [])
    with pytest.raises(ValueError, match="boş"):
        d.liste_oku(tmp_path / "bos.yaml")
    with pytest.raises(ValueError, match="boş"):
        d.Dinleyici([], [], None, None, tmp_path)
    with pytest.raises(ValueError, match="benzersiz"):
        d.Dinleyici([d.Izlenen("x", A), d.Izlenen("y", A)], [], None, None, tmp_path)


def test_dinleyici_pandas_gerektirmez():
    kod = "import sys, copytrade.dinleyici; assert 'pandas' not in sys.modules and 'numpy' not in sys.modules, sorted(m for m in sys.modules if m in ('pandas','numpy'))"
    assert subprocess.run([sys.executable, "-c", kod], capture_output=True, text=True).returncode == 0


# ------------------------------------------------------------------------------------------------ çalıştırıcı (sahte WS / REST / saat)
class SahteWS:
    def __init__(self, mesajlar, sonra="kes", saat=None):
        self.mesajlar, self.gonderilen, self.kapandi, self.sonra, self.saat = list(mesajlar), [], False, sonra, saat

    async def send(self, ham):
        self.gonderilen.append(json.loads(ham))

    async def recv(self):
        while self.mesajlar and isinstance(self.mesajlar[0], int):
            self.saat.ms += self.mesajlar.pop(0)               # tam sayı = sahte saati o kadar ms ilerlet (abonelikten SONRA gelen canlı olaylar için)
        if self.mesajlar:
            return json.dumps(self.mesajlar.pop(0))
        if self.sonra == "kes":
            raise ConnectionError("kapandı")
        await asyncio.sleep(3600)

    async def close(self):
        self.kapandi = True


class Saat:
    """Sahte saat: her okumada 'adim' ms ilerler (mono saniye cinsinden aynı akışı izler)."""
    def __init__(self, ms=1_000_000, adim=0):
        self.ms, self.adim = ms, adim

    def saat_ms(self):
        return self.ms

    def mono(self):
        return self.ms / 1000


def calistir(izlenen, mesajlar_listesi, tmp_path, post=lambda y: [], ayar=None, saat=None, coinler=("BTC", "ETH"), sahte_mono=False):
    """Her bağlantıda sıradaki mesaj listesiyle bir SahteWS; liste bitince 'bekle' (sure_sn ile biter)."""
    saat = saat or Saat()
    baglantilar = [SahteWS(m, "kes", saat) for m in mesajlar_listesi]
    sira = {"i": 0}

    async def baglan():
        if sira["i"] >= len(baglantilar):
            baglantilar.append(SahteWS([], "bekle", saat))
        ws = baglantilar[sira["i"]]
        sira["i"] += 1
        return ws
    ayar = ayar or d.Ayar(sure_sn=0.5, geri_cekilme_ilk_sn=0.01, geri_cekilme_max_sn=0.02)
    din = d.Dinleyici(izlenen, list(coinler), baglan, post, tmp_path, ayar, saat.saat_ms, saat.mono if sahte_mono else None)
    ozet = asyncio.run(din.calis())
    return din, baglantilar, ozet


def test_calistirici_abonelikler_olaylar_ve_ozet_dosyasi(tmp_path):
    saat = Saat(ms=1_000_000)
    mesajlar = [500, trades((1, 1_000_100, [A, C])), userfills(A, (1, 1_000_100), (2, 1_000_000)), {"channel": "subscriptionResponse", "data": {}}, {"channel": "error", "data": "x"},
                {"channel": "pong"}]
    din, ws, ozet = calistir(IZ, [mesajlar], tmp_path, saat=saat, ayar=d.Ayar(sure_sn=0.3, geri_cekilme_ilk_sn=0.01))
    abonelikler = [m["subscription"] for m in ws[0].gonderilen if m.get("method") == "subscribe"]
    assert [a for a in abonelikler if a["type"] == "trades"] == [{"type": "trades", "coin": "BTC"}, {"type": "trades", "coin": "ETH"}]
    assert [a["user"] for a in abonelikler if a["type"] == "userFills"] == [A, B] and ws[0].kapandi
    t = ozet["toplam"]["aaaa"]
    assert t["n"] == 2 and t["gecikme_medyan_sn"] == 0.45 and t["gecikme_max_sn"] == 0.5          # tid 1 (trades, 0,4 sn) + tid 2 (userFills, 0,5 sn); tid 1 tekrarı yok sayıldı
    assert ozet["genel"]["trades_mesaj"] == 1 and ozet["genel"]["userfills_mesaj"] == 1 and ozet["genel"]["subscription_response"] == 1 and ozet["genel"]["error"] == 1
    assert ozet["genel"]["tekrar"] == 1
    assert json.loads((tmp_path / "ozet.json").read_text())["toplam"]["aaaa"]["n"] == 2 and "0x" not in (tmp_path / "ozet.json").read_text()


def test_calistirici_kopma_yeniden_baglanma_ve_abonelikler_yeniden_gonderilir(tmp_path):
    saat = Saat(ms=1_000_000)
    din, ws, ozet = calistir(IZ, [[100, trades((1, 1_000_000, [A]))], [50, trades((2, 1_000_120, [B]))]], tmp_path, saat=saat,
                             ayar=d.Ayar(sure_sn=0.4, geri_cekilme_ilk_sn=0.01, geri_cekilme_max_sn=0.02))
    assert ozet["genel"]["kopma"] >= 2 and ozet["genel"]["yeniden_baglanma"] >= 1            # iki bağlantı koptu (ConnectionError), üçüncü bekler
    assert all(any(m["subscription"]["type"] == "trades" for m in w.gonderilen if m.get("method") == "subscribe") for w in ws[:3])
    assert ozet["toplam"]["aaaa"]["n"] == 1 and ozet["toplam"]["bbbb"]["n"] == 1 and all(w.kapandi for w in ws)


def test_calistirici_rest_hakem_kacani_sayar(tmp_path):
    saat = Saat(ms=1_000_000)
    rest = {A: [{"tid": t, "time": z, "coin": "BTC"} for t, z in ((1, 1_000_000), (2, 1_000_100), (3, 1_000_200))], B: []}
    din, ws, ozet = calistir(IZ, [[1_000_000, trades((1, 1_000_000, [A]), (2, 1_000_100, [A]))]], tmp_path, saat=saat,
                             post=lambda y: rest[y["user"]], ayar=d.Ayar(sure_sn=0.2, geri_cekilme_ilk_sn=0.01))
    assert ozet["toplam"]["aaaa"]["kacan"] == 1 and ozet["toplam"]["bbbb"]["kacan"] == 0       # REST 3 dolum, dinleyici 2


def test_calistirici_ping_ve_saatlik_ozet_penceresi(tmp_path):
    class IlerleyenSaat(Saat):
        def mono(self):
            self.ms += 20_000                     # her okumada 20 sn
            return self.ms / 1000
    saat = IlerleyenSaat(ms=0)
    ayar = d.Ayar(sure_sn=400.0, ping_sn=25.0, ozet_aralik_sn=100.0, rest_aralik_sn=10 ** 9, geri_cekilme_ilk_sn=0.01)
    din, ws, ozet = calistir(IZ, [[]], tmp_path, saat=saat, ayar=ayar, sahte_mono=True)
    ping = [m for w in ws for m in w.gonderilen if m == {"method": "ping"}]
    assert len(ping) >= 3 and ozet["genel"]["ping"] == len(ping)                              # uygulama ping'i
    assert (tmp_path / "ozet.json").exists()


def test_baslama_sayaci_restart_sayisi(tmp_path):
    yol = tmp_path / "s" / "durum.json"
    assert [d.baslama_sayaci(yol) for _ in range(3)] == [0, 1, 2]                            # ilk başlatma 0, her yeniden başlamada +1


def test_coin_listesi_silinmis_coinleri_atlar():
    assert d.coin_listesi(lambda y: [None] if y["type"] == "perpDexs" else {"universe": [{"name": "BTC"}, {"name": "OLD", "isDelisted": True}, {"name": "ETH"}]}) == ["BTC", "ETH"]


def test_golden_coin_evreni_ana_perp_ve_hip3_dexleri_spot_yok():
    """Elle: ana evren [BTC, ETH(silinmiş)], perpDexs [None, xyz, abc], xyz evreni [xyz:XYZ100, xyz:GOLD], abc evreni [abc:X, xyz:GOLD(tekrar)] -> 5 değil 4 benzersiz coin:
    BTC, xyz:XYZ100, xyz:GOLD, abc:X. Aynı evren izleme motorunun kopyaladığı evrendir: hiçbiri `olcut.asset_class` ile 'spot' değildir (kural 7)."""
    from copytrade.olcut import asset_class
    evrenler = {None: [{"name": "BTC"}, {"name": "ETH", "isDelisted": True}], "xyz": [{"name": "xyz:XYZ100"}, {"name": "xyz:GOLD"}],
                "abc": [{"name": "abc:X"}, {"name": "xyz:GOLD"}]}

    def post(y):
        if y["type"] == "perpDexs":
            return [None, {"name": "xyz"}, {"name": "abc"}]
        assert y["type"] == "meta"
        return {"universe": evrenler[y.get("dex")]}
    coinler = d.coin_listesi(post)
    assert coinler == ["BTC", "xyz:XYZ100", "xyz:GOLD", "abc:X"]
    assert all(asset_class(c) != "spot" for c in coinler)


# ------------------------------------------------------------------------------------------------ adım 0
def test_adim0_abonelik_yaniti_users_alani_ve_isabet(tmp_path):
    izl = [d.Izlenen(f"t{i:02d}", "0x" + f"{i:040x}") for i in range(1, 13)]
    yanitlar = [{"channel": "subscriptionResponse", "data": {"method": "subscribe", "subscription": {"type": "userFills", "user": izl[i].adres}}} for i in range(10)]
    yanitlar.append({"channel": "error", "data": f"Cannot track more than 10 users {izl[10].adres}"})
    yanitlar.append({"channel": "trades", "data": [{"tid": 1, "time": 1, "users": [izl[3].adres, C]}, {"tid": 2, "time": 2}]})
    ws = SahteWS(yanitlar, "bekle")

    async def baglan():
        return ws
    sayac = {"t": 0.0}

    def mono():
        sayac["t"] += 0.4
        return sayac["t"]
    sonuc = asyncio.run(d.adim0(izl, ["BTC"], baglan, sure_sn=5.0, mono=mono))
    assert [a["yanit"] for a in sonuc["abonelik"]] == ["ok"] * 10 + [None, None][:len(sonuc["abonelik"]) - 10]
    assert sonuc["error"] == 1 and sonuc["hata_metinleri"] == ["Cannot track more than 10 users t11"]            # adres takma adla maskelendi
    assert sonuc["trades"]["islem"] == 2 and sonuc["trades"]["users_alanli_islem"] == 1 and sonuc["trades"]["izlenen_adlar"] == ["t04"]
    assert sonuc["yorum"] == {"userfills_11_adres_hata_sayisi": 1, "trades_users_alani_var": True, "izlenen_dolum_gorundu": True}
    assert "0x" not in json.dumps(sonuc) and ws.kapandi
    assert len([m for m in ws.gonderilen if m["subscription"]["type"] == "userFills"]) == 11            # yalnız ilk 11 adres


# ------------------------------------------------------------------------------------------------ dağıtım dosyaları
ROOT = Path(__file__).resolve().parents[1]


def test_systemd_birimi_restart_on_failure_secretsiz_yalniz_state_dizinine_yazar():
    birim = (ROOT / "deploy/sg-dinleyici.service").read_text()
    assert "Restart=on-failure" in birim and "NoNewPrivileges=true" in birim and "ProtectSystem=strict" in birim and "ReadWritePaths=/var/lib/sg-dinleyici" in birim
    assert "-m copytrade.dinleyici calis --liste" in birim and "User=sg" in birim
    assert not any(k in birim.upper() for k in ("TOKEN", "SECRET", "PRIVATE_KEY", "PRIVATEKEY", "API_KEY", "PASSWORD", "WALLET"))
    gereksinim = (ROOT / "requirements-dinleyici.txt").read_text()
    assert "websockets==" in gereksinim and "PyYAML==" in gereksinim and "pandas==" not in gereksinim and "numpy==" not in gereksinim


def test_kurulum_rehberi_gerekli_adimlar_ve_gizli_bilgi_yazdirmaz():
    r = (ROOT / "docs/H2_KURULUM.md").read_text()
    for gerekli in ("ssh-keygen -t ed25519", "SGP1", "Ubuntu 24.04", "Basic 1 GB", "adduser", "apt install -y python3-venv git", "timedatectl", "git clone",
                    "pip install -r requirements-dinleyici.txt", "systemctl enable --now sg-dinleyici", "systemctl status sg-dinleyici", "journalctl -u sg-dinleyici -n 50",
                    "cat /var/lib/sg-dinleyici/ozet.json", "systemctl stop sg-dinleyici", "yalnız 22", "adim0"):
        assert gerekli in r, gerekli
    assert "id_ed25519.pub" in r and "type $env:USERPROFILE\\.ssh\\id_ed25519\n" not in r      # yalnız genel anahtar yazdırılır


# ------------------------------------------------------------------------------------------------ H2 PR denetimi: "kaçan" sınıflaması (gerçek ağ denemesinde 678 kaçan çıkmıştı)
def test_golden_abonelikten_onceki_trades_dolumu_snapshot_sayilir_gecikmeye_girmez():
    """Sunucu aboneliğin anında son işlemleri de gönderir: dolum zamanı < abonelik anı ise canlı değildir (gecikme 724 sn gibi uç değerlerin kaynağı)."""
    o = d.Olcum(IZ)
    o.abone["BTC"] = 5_000
    eski = d.trades_olaylari(trades((1, 4_000, [A])), IZD, 5_010)       # 1 sn önce olmuş, abonelikte gelen geçmiş
    canli = d.trades_olaylari(trades((2, 5_100, [A])), IZD, 5_300)      # abonelikten sonra, 0,2 sn gecikmeli
    assert all(ev.abone == "BTC" for ev in eski + canli)
    for ev in eski + canli:
        o.olay(ev)
    t = o.toplam["aaaa"]
    assert t.snapshot == 1 and t.gecikme == [0.2] and o.genel["abonelik_oncesi_snapshot_gibi"] == 1


def test_golden_rest_penceresi_ilk_abonelikten_onceyi_kapsamaz_ve_kacan_siniflanir():
    """Abonelik 10_000'de bitti. REST (altın girdi): tid1 t=9_000 (abonelik öncesi, perp BTC) -> sayılmaz; tid2 BTC canlı kaçan -> gercek;
    tid3 '@107' -> spot; tid4 'xyz:XYZ100' -> hip3; tid5 'YENICOIN' (abone evreninde yok) -> abonesiz_perp; tid6 'PURR/USDC' -> spot."""
    o = d.Olcum(IZ)
    o.abone_coinler = {"BTC", "ETH"}
    o.ilk_abone_bitis_ms = 10_000
    rest = [{"tid": 1, "time": 9_000, "coin": "BTC"}, {"tid": 2, "time": 11_000, "coin": "BTC"}, {"tid": 3, "time": 11_100, "coin": "@107"},
            {"tid": 4, "time": 11_200, "coin": "xyz:XYZ100"}, {"tid": 5, "time": 11_300, "coin": "YENICOIN"}, {"tid": 6, "time": 11_400, "coin": "PURR/USDC"}]
    assert o.rest_karsilastir("aaaa", A, rest, simdi_ms=10_000_000, tolerans_ms=120_000) == 1
    t = o.toplam["aaaa"]
    assert t.kacan == 1 and t.kacan_sinif == {"gercek": 1, "spot": 2, "hip3": 1, "abonesiz_perp": 1}
    assert o.genel["rest_abonelik_oncesi_atlanan"] == 1 and o.saat["aaaa"].kacan_sinif == t.kacan_sinif
    assert o.rest_karsilastir("aaaa", A, rest, 10_000_000, 120_000) == 0       # ikinci kez sayılmaz
    assert t.ozet()["kacan_sinif"] == {"abonesiz_perp": 1, "gercek": 1, "hip3": 1, "spot": 2}


def test_calistirici_abonelik_anlari_ve_ilk_abonelik_bitisi_kaydedilir(tmp_path):
    saat = Saat(ms=7_000)
    din, ws, ozet = calistir(IZ, [[]], tmp_path, saat=saat, ayar=d.Ayar(sure_sn=0.2, geri_cekilme_ilk_sn=0.01))
    assert din.olcum.abone["BTC"] == 7_000 and din.olcum.abone[f"userFills:{A}"] == 7_000 and din.olcum.ilk_abone_bitis_ms == 7_000
    assert din.olcum.abone_coinler == {"BTC", "ETH"}
