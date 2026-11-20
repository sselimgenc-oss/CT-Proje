"""HL ↔ Binance fiyat farkı ölçümü (copytrade/olcum/fiyat_farki.py): ağ YOK, her şey sahte."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from copytrade.olcum import fiyat_farki as ff

T0 = 1_760_000_000_000          # sabit zaman (ms)


def _olcum(tmp_path, hedef=600):
    return ff.Olcum(tmp_path / "cikti", hedef, lambda: T0 + 10_000)


def _emir(coin="BTC", yon="B", px=100.0, t0=T0, **ek):
    return {"olay": "emir", "coin": coin, "yon": yon, "trader_px": px, "trader_dolum_ms": t0, "dolum_px": px * 1.0001, "kayma_trader": 0.0001, "durum": "dolu", "eylem": "ac", "kaynak": "canli", **ek}


def _satirlar(o):
    out = []
    for y in sorted(o.cikti.glob("*.jsonl")):
        out += [json.loads(s) for s in y.read_text().splitlines()]
    return out


# ---- fark hesabı ve yön
def test_fark_yon_alista_ask_satista_bid():
    assert ff.fark_bp("B", 100.0, 99.9, 100.1) == (100.1 - 100.0) / 100.0 * 1e4        # alış: ask, +10 bp (kötü)
    assert abs(ff.fark_bp("A", 100.0, 99.9, 100.1) - 10.0) < 1e-9                       # satış: bid altında → +10 bp (kötü)
    assert ff.fark_bp("A", 100.0, 100.2, 100.3) < 0                                     # Binance bid daha yüksek → satış lehimize
    assert ff.fark_bp("B", 100.0, 99.5, 99.6) < 0
    assert ff.fark_bp("X", 100.0, 1, 1) is None and ff.fark_bp("B", 0.0, 1, 1) is None


def test_bekleyen_dolum_hedef_anindaki_kote_ile_olculur(tmp_path):
    o = _olcum(tmp_path)
    o.ornek("BTCUSDT", T0 - 50, 99.0, 99.2)          # t0 öncesi
    o.ornek("BTCUSDT", T0 + 590, 100.0, 100.1)       # hedef (T0+600) öncesi son kote
    o.ornek("BTCUSDT", T0 + 900, 120.0, 120.1)       # hedeften sonra: kullanılmaz
    o.emir_isle(_emir("BTC", "B", 100.0))
    assert o.bekleyenleri_isle(T0 + 700) == 0         # hedef + pay dolmadı: bekler
    assert o.bekleyenleri_isle(T0 + 900) == 1
    f = [s for s in _satirlar(o) if s["olay"] == "fark"][0]
    assert abs(f["fark_bp"] - 10.0) < 1e-6            # (100,1-100)/100
    assert abs(f["fark_t0_bp"] - (99.2 - 100.0) / 100.0 * 1e4) < 1e-6
    assert f["bn_yas_ms"] == 10 and f["yon"] == "B" and f["hl_kayma_bp"] == 1.0 and f["sym"] == "BTCUSDT"


def test_satis_bid_kullanir(tmp_path):
    o = _olcum(tmp_path)
    o.ornek("ETHUSDT", T0 + 100, 99.8, 100.4)
    o.emir_isle(_emir("ETH", "A", 100.0))
    o.bekleyenleri_isle(T0 + 2000)
    f = [s for s in _satirlar(o) if s["olay"] == "fark"][0]
    assert abs(f["fark_bp"] - 20.0) < 1e-6


def test_ornek_yoksa_neden_yazilir(tmp_path):
    o = _olcum(tmp_path)
    o.ornek("BTCUSDT", T0 + 5000, 100.0, 100.1)       # t0'dan çok sonra: hedefte kote yok
    o.emir_isle(_emir("BTC", "B", 100.0))
    o.bekleyenleri_isle(T0 + 2000)
    f = [s for s in _satirlar(o) if s["olay"] == "fark"][0]
    assert f["fark_bp"] is None and f["neden"] == "binance_ornek_yok"


def test_trader_px_olmayan_emir_atlanir(tmp_path):
    o = _olcum(tmp_path)
    o.emir_isle({"olay": "emir", "coin": "BTC", "yon": "B", "kaynak": "tasfiye"})
    assert o.bekleyen == [] and o.say["atlanan"] == 1


# ---- HIP-3 eşleme
def test_hip3_esleme_ve_dogrulanmayanlar():
    assert ff.binance_sembol("xyz:NVDA") == ("NVDAUSDT", True)
    assert ff.binance_sembol("io:NVDA") == ("NVDAUSDT", True)
    assert ff.binance_sembol("io:SNDK")[0] == "SNDKUSDT" and ff.binance_sembol("io:SNDK")[1] is False
    assert ff.binance_sembol("xyz:ANT") == ("ANTHROPICUSDT", False)
    assert ff.binance_sembol("xyz:XYZ100") == (None, False)
    assert ff.binance_sembol("xyz:YENI") == ("YENIUSDT", False)        # bilinmeyen HIP-3: varsayılan ad, doğrulanmamış
    assert ff.binance_sembol("kPEPE") == ("1000PEPEUSDT", True)
    assert ff.binance_sembol("@107") == (None, False)
    assert ff.binance_sembol("BTC") == ("BTCUSDT", True)


def test_eslesmeyen_coin_dolumu_neden_ile_yazilir(tmp_path):
    o = _olcum(tmp_path)
    o.emir_isle(_emir("xyz:XYZ100", "B", 100.0))
    o.bekleyenleri_isle(T0 + 2000)
    f = [s for s in _satirlar(o) if s["olay"] == "fark"][0]
    assert f["neden"] == "binance_eslesme_yok" and f["sym"] is None


# ---- WS mesajı
def test_ws_mesaji_ornek_olur(tmp_path):
    o = _olcum(tmp_path)
    msg = {"stream": "btcusdt@bookTicker", "data": {"e": "bookTicker", "s": "BTCUSDT", "b": "100.0", "B": "1", "a": "100.1", "A": "1", "T": T0 + 5, "E": T0 + 6}}
    o.ws_mesaj(json.dumps(msg), T0 + 140)
    assert o.tampon.kote("BTCUSDT", T0 + 10) == (T0 + 6, 100.0, 100.1)
    assert list(o.gecikme_ms) == [134]
    o.ws_mesaj("bozuk{", T0)                           # bozuk mesaj sessizce atlanır
    o.ws_mesaj(json.dumps({"data": {"s": "X"}}), T0)


# ---- yüzdelik ve özet
def test_yuzdelik():
    v = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert ff.yuzdelik(v, 50) == 5.5
    assert abs(ff.yuzdelik(v, 90) - 9.1) < 1e-9
    assert ff.yuzdelik([], 50) is None and ff.yuzdelik([7], 90) == 7


def test_ozet_medyan_p90_coin_bazinda_ve_hl_karsilastirma(tmp_path):
    o = _olcum(tmp_path)
    o.yaz({"olay": "erisim", "kanal": "rest", "durum": "ok", "http": 200, "govde": "{}"}, T0)
    for i in range(10):
        o.yaz({"olay": "fark", "coin": "BTC", "sym": "BTCUSDT", "sym_dogrulandi": True, "fark_bp": float(i + 1), "fark_t0_bp": 0.5, "hl_kayma_bp": 0.4, "bn_spread_bp": 0.2, "neden": None}, T0 + i)
    o.yaz({"olay": "fark", "coin": "xyz:ANT", "sym": "ANTHROPICUSDT", "sym_dogrulandi": False, "fark_bp": None, "neden": "binance_ornek_yok"}, T0)
    o.yaz({"olay": "mid", "coinler": {"BTC": {"hl": 1, "bn": 1, "bp": -2.0}}, "ws_gecikme_ms": 130}, T0)
    ozet = ff.ozet_hazirla(ff._satirlari_oku(o.cikti))
    assert ozet["fark"]["n"] == 10 and ozet["fark"]["med"] == 5.5 and abs(ozet["fark"]["p90"] - 9.1) < 1e-9
    assert ozet["coinler"]["BTC"]["fark"]["med"] == 5.5 and ozet["coinler"]["BTC"]["hl"]["med"] == 0.4
    assert ozet["coinler"]["xyz:ANT"]["olculen"] == 0 and ozet["nedenler"] == {"binance_ornek_yok": 1}
    md = ff.ozet_yaz(o.cikti)
    assert "5.50" in md and "ANTHROPICUSDT (doğrulanmadı)" in md and "ok" in md and (o.cikti / "OZET.md").exists()
    assert ozet["mid"]["BTC"]["med"] == -2.0 and ozet["ws_gecikme_med"] == 130.0


# ---- erişim: 451 → tek uyarı, çıkış
def _args(tmp_path, **ek):
    d = dict(durum_dizin=str(tmp_path / "durum"), kayit_dizin=str(tmp_path / "kayit"), cikti_dizin=str(tmp_path / "cikti"), sure_saat=0.001, hedef_ms=600, coin=["BTC"], ozet=False, gun=None)
    d.update(ek)
    return argparse.Namespace(**d)


def test_451_tek_telegram_ve_cikis_ws_acilmaz(tmp_path):
    postlar, baglanti = [], []

    def get(url, params=None):
        return 451, '{"code":0,"msg":"Service unavailable from a restricted location"}'

    def baglan(url):
        baglanti.append(url)
        raise AssertionError("WS açılmamalı")

    kod = asyncio.run(ff.calistir(_args(tmp_path), get=get, baglan=baglan, telegram=lambda u, y: postlar.append((u, y)), env={"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "C"}))
    assert kod == ff.CIKIS_ERISIM_YOK and baglanti == []
    assert len(postlar) == 1 and "⚠️" in postlar[0][1]["text"] and "451" in postlar[0][1]["text"]
    s = [json.loads(x) for y in (tmp_path / "cikti").glob("*.jsonl") for x in y.read_text().splitlines()]
    e = [x for x in s if x["olay"] == "erisim"]
    assert len(e) == 1 and e[0]["durum"] == "yok" and e[0]["http"] == 451 and "restricted" in e[0]["govde"]
    assert ff.ozet_hazirla(s)["erisim"]["yok"] is True


def test_telegram_anahtar_yoksa_sessiz():
    assert ff.telegram_uyari("x", lambda u, y: (_ for _ in ()).throw(AssertionError), env={}) is False


def test_ws_el_sikisma_451_tek_uyari_ve_cikis(tmp_path):
    postlar = []

    class Yanit:
        status_code = 451

    class Hata(Exception):
        response = Yanit()

    class Baglanti:
        async def __aenter__(self):
            raise Hata()

        async def __aexit__(self, *a):
            return False

    def get(url, params=None):
        return 200, json.dumps({"symbol": "BTCUSDT", "bidPrice": "1", "askPrice": "1.1", "time": T0})

    kod = asyncio.run(ff.calistir(_args(tmp_path), get=get, baglan=lambda url: Baglanti(), telegram=lambda u, y: postlar.append(y), env={"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "C"}))
    assert kod == ff.CIKIS_ERISIM_YOK and len(postlar) == 1


# ---- sahte WS ile uçtan uca + motor dosyalarına dokunmama
def _hash_dizin(d: Path):
    return {str(p.relative_to(d)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in sorted(d.rglob("*")) if p.is_file()}


def test_uctan_uca_sahte_ws_ve_motor_dosyalarina_yazmaz(tmp_path):
    import time
    simdi = lambda: int(time.time() * 1000)            # noqa: E731
    durum, kayit = tmp_path / "durum", tmp_path / "kayit"
    durum.mkdir()
    kayit.mkdir()
    (durum / "hesap.json").write_text(json.dumps({"poz": {"0xabc": {"ETH": {}, "xyz:NVDA": {}}}}))
    gun = ff.gun(simdi())
    kayit_dosya = kayit / f"{gun}.jsonl"
    kayit_dosya.write_text(json.dumps({"olay": "emir", "coin": "OLD", "yon": "B", "trader_px": 1, "trader_dolum_ms": simdi() - 99999}) + "\n")
    once = _hash_dizin(tmp_path)

    class WS:
        def __init__(self):
            self.gonderilen, self.adim = [], 0

        async def send(self, m):
            self.gonderilen.append(m)

        async def recv(self):
            self.adim += 1
            if self.adim == 2:                         # motor yeni emir yazar
                with kayit_dosya.open("a") as f:
                    f.write(json.dumps(_emir("ETH", "B", 100.0, t0=simdi() - 100)) + "\n")
                    f.write(json.dumps(_emir("DOGE", "A", 0.5, t0=simdi() - 100)) + "\n")       # yeni coin → abone
            if self.adim > 2:
                await asyncio.sleep(0.1)
            return json.dumps({"data": {"e": "bookTicker", "s": "ETHUSDT", "b": "100.0", "a": "100.1", "E": simdi()}})

    ws = WS()

    class Baglanti:
        async def __aenter__(self):
            return ws

        async def __aexit__(self, *a):
            return False

    urller = []

    def get(url, params=None):
        return 200, json.dumps({"symbol": "ETHUSDT", "bidPrice": "100", "askPrice": "100.1", "time": simdi()})

    def baglan(url):
        urller.append(url)
        return Baglanti()

    a = _args(tmp_path, durum_dizin=str(durum), kayit_dizin=str(kayit), coin=[], sure_saat=0.0012)
    kod = asyncio.run(ff.calistir(a, get=get, baglan=baglan, hl=lambda y: {"ETH": "100.05", "xyz:NVDA": "200"}, telegram=lambda u, y: None, env={}))
    assert kod == 0
    assert any("ethusdt@bookTicker" in u and "nvdausdt@bookTicker" in u for u in urller)      # hesap.json coinleri abone
    assert any("dogeusdt@bookTicker" in m for m in ws.gonderilen)                              # kuyrukta görülen yeni coin dinamik abone
    s = [json.loads(x) for y in (tmp_path / "cikti").glob("*.jsonl") for x in y.read_text().splitlines()]
    farklar = [x for x in s if x["olay"] == "fark"]
    assert "OLD" not in [x["coin"] for x in farklar]                                           # açılışta mevcut içerik atlanır
    eth = [x for x in farklar if x["coin"] == "ETH"][0]
    assert abs(eth["fark_bp"] - 10.0) < 1e-6
    assert any(x["olay"] == "mid" for x in s) and any(x["olay"] == "bitis" for x in s)
    # motor dosyaları: kayit/<gün>.jsonl'e testin KENDİ eklediği 2 satır dışında hiçbir şey değişmez; durum/ aynen; yeni dosya yok
    sonra = _hash_dizin(tmp_path)
    for yol, v in once.items():
        if not yol.startswith("cikti") and yol != f"kayit/{gun}.jsonl":
            assert sonra[yol] == v, yol
    assert not [p for p in sonra if p.startswith(("durum/", "kayit/")) and p not in once]


def test_kuyruk_yarim_satiri_bekler_ve_acilista_atlar(tmp_path):
    d = tmp_path / "k"
    d.mkdir()
    yol = d / f"{ff.gun(T0)}.jsonl"
    yol.write_text('{"olay":"emir","coin":"A"}\n')
    q = ff.KayitKuyrugu(d)
    assert q.oku(T0) == []
    with yol.open("a") as f:
        f.write('{"olay":"emir","coin":"B"')
    assert q.oku(T0) == []
    with yol.open("a") as f:
        f.write('}\n{"olay":"diger"}\n')
    assert [x["coin"] for x in q.oku(T0)] == ["B"]


# ---- gruplar ve otomatik değerlendirme (kabul ölçütü)
E = ff.esikler({})        # varsayılanlar; yaml ile aynı olduğu aşağıda ayrıca sınanır


def _ist(n, med, ort, p90):
    return {"n": n, "med": med, "ort": ort, "p90": p90}


def test_esikler_yaml_ile_ayni_ve_kurallarda_var():
    from copytrade.kurallar import load_rules
    r = load_rules()
    assert ff.esikler(r) == ff.esikler({}) and all(k in r for k in ff.ESIK_VARSAYILAN)


def test_siniflandirma_gec_gri_dur_ve_sinirlar():
    assert ff.siniflandir(_ist(100, 1.0, 1.5, 10.0), E) == "GEÇ"             # sınır dahil
    assert ff.siniflandir(_ist(100, 1.01, 1.0, 5.0), E) == "GRİ"
    assert ff.siniflandir(_ist(100, 0.5, 1.6, 5.0), E) == "GRİ"
    assert ff.siniflandir(_ist(100, 0.5, 1.0, 10.1), E) == "GRİ"
    assert ff.siniflandir(_ist(100, 2.0, 1.0, 5.0), E) == "GRİ"              # DUR için ">" 2
    assert ff.siniflandir(_ist(100, 2.01, 1.0, 5.0), E) == "DUR"
    assert ff.siniflandir(_ist(100, 0.5, 1.0, 15.01), E) == "DUR"            # tek koşul yeter
    assert ff.siniflandir(_ist(100, 0.5, 3.01, 5.0), E) == "DUR"
    assert ff.siniflandir(_ist(29, 0.1, 0.1, 1.0), E) == "KARAR YOK"          # n < 30
    assert ff.siniflandir(_ist(30, 0.1, 0.1, 1.0), E) == "GEÇ"


def test_genel_hukum_ornek_yetersiz():
    iyi = _ist(500, 0.5, 0.5, 5.0)
    assert ff.degerlendir(iyi, 500, 3, 15, E) == "GEÇ"
    assert ff.degerlendir(iyi, 299, 3, 15, E) == "ÖRNEK YETERSİZ"
    assert ff.degerlendir(iyi, 500, 2, 15, E) == "ÖRNEK YETERSİZ"
    assert ff.degerlendir(iyi, 500, 3, 14, E) == "ÖRNEK YETERSİZ"
    assert ff.degerlendir(_ist(500, 5, 5, 20), 100, 1, 1, E) == "ÖRNEK YETERSİZ"      # yetersiz örnekte DUR da denmez


def test_grup_adi():
    assert ff.grup_adi("BTC") == "majör" and ff.grup_adi("xyz:NVDA") == "tradfi" and ff.grup_adi("io:SNDK") == "tradfi" and ff.grup_adi("WLFI") == "altcoin"


def test_ozet_gruplari_ayri_ve_hukum(tmp_path):
    o = _olcum(tmp_path)
    gun_ms = ff.gun(T0)
    ms = [T0 + i * 86_400_000 for i in range(3)]                       # 3 ayrı gün
    for i in range(300):                                               # majör: 5 coin, düşük fark → GEÇ
        o.yaz({"olay": "fark", "t0_ms": ms[i % 3], "coin": ["BTC", "ETH", "SOL", "XRP", "BNB"][i % 5], "sym": "X", "fark_bp": 0.5, "hl_kayma_bp": 0.4, "neden": None}, ms[i % 3])
    for i in range(40):                                                # altcoin: 10 coin, p90 yüksek → DUR
        o.yaz({"olay": "fark", "t0_ms": ms[i % 3], "coin": f"A{i % 10}", "sym": "X", "fark_bp": 20.0 if i % 10 < 2 else 0.5, "neden": None}, ms[i % 3])
    for i in range(10):                                                # tradfi: 10 dolum → KARAR YOK
        o.yaz({"olay": "fark", "t0_ms": ms[0], "coin": "xyz:NVDA", "sym": "NVDAUSDT", "fark_bp": 3.0, "neden": None}, ms[0])
    ozet = ff.ozet_hazirla(ff._satirlari_oku(o.cikti), E)
    g = ozet["gruplar"]
    assert g["majör"]["n"] == 300 and g["majör"]["hukum"] == "GEÇ" and g["majör"]["p95"] == 0.5
    assert g["altcoin"]["n"] == 40 and g["altcoin"]["hukum"] == "DUR"
    assert g["tradfi"]["n"] == 10 and g["tradfi"]["hukum"] == "KARAR YOK"
    assert ozet["n_gun"] == 3 and ozet["n_coin"] == 16 and gun_ms
    assert ozet["hukum"] in ("GEÇ", "GRİ", "DUR")                      # 350 dolum, 3 gün, 16 coin: yeterli
    md = ff.ozet_markdown(ozet)
    assert "Otomatik değerlendirme" in md and "KARAR YOK" in md and "Genel hüküm" in md and "p95" in md


def test_ozet_az_ornekte_yetersiz(tmp_path):
    o = _olcum(tmp_path)
    o.yaz({"olay": "fark", "t0_ms": T0, "coin": "BTC", "sym": "BTCUSDT", "fark_bp": 0.1, "neden": None}, T0)
    assert ff.ozet_hazirla(ff._satirlari_oku(o.cikti), E)["hukum"] == "ÖRNEK YETERSİZ"
    assert "ÖRNEK YETERSİZ" in ff.ozet_yaz(o.cikti)


def test_varsayilan_sure_96_saat():
    import re
    kaynak = Path(ff.__file__).read_text(encoding="utf-8")
    assert re.search(r'"--sure-saat", type=float, default=96\.0', kaynak)
    birim = (Path(ff.__file__).parents[2] / "deploy/sg-sanal-olcum.service").read_text(encoding="utf-8")
    assert "RuntimeMaxSec=96h" in birim and "--sure-saat 95.5" in birim
