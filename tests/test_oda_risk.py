"""Oda risk bayrakları (``copytrade/oda_risk.py``): altın örnekler — funding-arbitraj profili bayraklanır, yönsel profil bayraklanmaz; kalabalık elle doğrulanır."""
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from copytrade import izleme_motoru as m
from copytrade import oda_risk as r
from copytrade.kurallar import load_rules
from tests.test_izleme import ADDRESS, NOW, Client, T0, fill, position

RULES = load_rules()
ROOT = Path(__file__).resolve().parents[1]
NOW_MS = int(pd.Timestamp("2026-10-30T12:00:00Z").timestamp() * 1000)


def vol(px, sz, crossed, t=NOW_MS - 1000, coin="BTC"):
    return {"time": t, "coin": coin, "px": str(px), "sz": str(sz), "crossed": crossed}


def test_funding_arbitraj_profili_bayraklanir_yonsel_profil_bayraklanmaz():
    # Arbitraj: funding geliri 800 $ / toplam kâr 1000 $ = 0,80 > 0,50; spot 10 ETH uzun, perp 10 ETH kısa → örtüşme 1,0 > 0,80; maker %95
    arb = r.yonsuz_bayrak(800.0, 1000.0, {"UETH": 10.0}, {"ETH": -10.0}, [vol(100, 95, False), vol(100, 5, True)], NOW_MS, RULES)
    assert arb["bayrak"] is True and arb["funding_payi"] == {"deger": 0.8, "esik": 0.5, "asildi": True}
    assert arb["spot_perp_ters"]["asildi"] is True and arb["spot_perp_ters"]["coin"] == "ETH" and arb["maker_payi"]["deger"] == pytest.approx(0.95) and arb["maker_payi"]["asildi"]
    # Yönsel: funding 50 $ / kâr 1000 $ = 0,05; spot yok (boş); perp uzun; maker %30
    yon = r.yonsuz_bayrak(50.0, 1000.0, {}, {"BTC": 2.0}, [vol(100, 30, False), vol(100, 70, True)], NOW_MS, RULES)
    assert yon["bayrak"] is False and yon["funding_payi"]["deger"] == pytest.approx(0.05) and yon["spot_perp_ters"]["deger"] == 0.0 and yon["maker_payi"]["deger"] == pytest.approx(0.30)
    assert yon["sezgisel"] is True and yon["pencere_gun"] == 90


def test_esik_sinirlari_tam_esit_bayrak_degil_ve_negatif_funding():
    assert r.funding_payi(500.0, 1000.0, RULES)["asildi"] is False             # tam 0,50: eşit, aşmaz
    assert r.funding_payi(501.0, 1000.0, RULES)["asildi"] is True
    assert r.funding_payi(-900.0, 1000.0, RULES)["asildi"] is False             # ödenen funding pay değildir
    assert r.funding_payi(5.0, 0.0, RULES)["deger"] == pytest.approx(5.0)        # toplam kâr 0 → payda ε = 1 $
    assert r.funding_payi(None, 100.0, RULES)["asildi"] is None and r.funding_payi(5.0, None, RULES)["deger"] is None
    # spot↔perp: S=10, P=−8 → 8/10 = 0,80 tam eşik: aşmaz; P=−8,1 → 0,81 aşar; aynı yön (S×P > 0) örtüşme sayılmaz
    assert r.spot_perp_ters({"ETH": 10.0}, {"ETH": -8.0}, RULES)["asildi"] is False
    assert r.spot_perp_ters({"ETH": 10.0}, {"ETH": -8.1}, RULES)["asildi"] is True
    assert r.spot_perp_ters({"ETH": 10.0}, {"ETH": 10.0}, RULES)["deger"] == 0.0 and r.spot_perp_ters(None, {"ETH": -1.0}, RULES)["deger"] is None


def test_maker_payi_pencere_ve_crossed_alani():
    eski = vol(100, 1000, False, t=NOW_MS - 91 * 86_400_000)                   # 90 gün dışı: sayılmaz
    assert r.maker_payi([eski, vol(100, 1, True)], NOW_MS, RULES)["deger"] == 0.0
    assert r.maker_payi([{"time": NOW_MS - 5, "coin": "BTC", "px": "1", "sz": "1"}], NOW_MS, RULES)["deger"] is None     # crossed alanı yok → uydurma yok
    assert r.maker_payi([], NOW_MS, RULES)["deger"] is None


def test_toplam_kar_portfoy_pnl_farki():
    pf = [["allTime", {"pnlHistory": [[NOW_MS - 120 * 86_400_000, "100"], [NOW_MS - 91 * 86_400_000, "150"], [NOW_MS - 10 * 86_400_000, "900"], [NOW_MS, "1150"]]}]]
    assert r.toplam_kar(pf, NOW_MS, RULES) == pytest.approx(1000.0)            # 1150 − (90 gün öncesinden önceki son değer 150)
    assert r.toplam_kar([], NOW_MS, RULES) is None


# ------------------------------------------------------------------ kalabalık (elle doğrulanan örnek)
def uye(hesap, *pozisyonlar):
    return {"hesap_degeri": hesap, "pozisyonlar": [{"coin": c, "yon": y, "buyukluk_usd": v} for c, y, v in pozisyonlar]}


def test_kalabalik_elle_hesap():
    """Üç üye (eşit ağırlık sadeleşir). x = nosyonel / hesap: T1 hesap 1000: ETH long 500 (0,5), BTC long 250 (0,25); T2 hesap 2000: ETH long 1000 (0,5), SOL short 400 (0,2);
    T3 hesap 500: ETH short 100 (0,2). Σ|x| = 1,65; ETH net = 0,5 + 0,5 − 0,2 = 0,8 → pay 0,8/1,65 = 0,4848; BTC 0,25/1,65 = 0,1515; SOL 0,2/1,65 = 0,1212."""
    k = r.kalabalik([uye(1000, ("ETH", "long", 500), ("BTC", "long", 250)), uye(2000, ("ETH", "long", 1000), ("SOL", "short", 400)), uye(500, ("ETH", "short", 100))], RULES)
    eth, btc, sol = k["coinler"]
    assert (eth["coin"], eth["net_yon"], eth["ayni_yon"], eth["toplam"]) == ("ETH", "long", 2, 3) and eth["net_pay"] == pytest.approx(0.8 / 1.65)
    assert eth["cakisma"] == pytest.approx(2 / 3) and btc["net_pay"] == pytest.approx(0.25 / 1.65) and (sol["coin"], sol["net_yon"]) == ("SOL", "short") and sol["net_pay"] == pytest.approx(0.2 / 1.65)
    assert k["uyari"] is True and k["uyari_metni"] == "Kalabalık: ETH net long oda payı %48, 2/3 trader aynı yönde" and k["n_oda"] == 3


def test_kalabalik_uyari_yok_kaldirac_cift_sayilmaz_ve_yonsuz_uye_atlanir():
    # Dengeli: iki üye aynı coinde zıt yön eşit x → net 0; her coin %50 pay değil (net yok): ETH net 0, BTC long 0,3 / (0,3+0,2+0,2) ... elle: x: ETH +0,2 / −0,2, BTC +0,3 → Σ = 0,7, BTC pay 0,3/0,7 = 0,4286 > 0,35 → uyarı
    k = r.kalabalik([uye(1000, ("ETH", "long", 200), ("BTC", "long", 300)), uye(1000, ("ETH", "short", 200))], RULES)
    assert [c["coin"] for c in k["coinler"]] == ["BTC", "ETH"] and k["coinler"][1]["net_pay"] == 0.0 and k["coinler"][0]["net_pay"] == pytest.approx(0.3 / 0.7)
    sakin = r.kalabalik([uye(1000, (f"C{i}", "long" if i % 2 else "short", 100)) for i in range(4)], RULES)       # her coinde tek üye, pay 0,25 ≤ 0,35
    assert sakin["uyari"] is False and sakin["uyari_metni"] is None
    assert r.kalabalik([{"hesap_degeri": 0, "pozisyonlar": []}], RULES)["n_oda"] == 0                              # hesap değeri olmayan üye sayılmaz


def test_kalabalik_cakisma_ve_ayni_yon_sayisi_esikleri():
    # 6 üye, hepsi ETH long, ama net pay 1,0: pay eşiğinden zaten uyarı; esikleri ayrı sına: pay eşiğini yükselt
    yuksek = {**RULES, "kalabalik_net_pay_esik": 2.0}
    uyeler = [uye(1000, ("ETH", "long", 100)) for _ in range(5)] + [uye(1000, ("ETH", "short", 100))]        # 6 üye: çakışma 5/6 = 0,833 ≥ 0,80, N_c = 6 → uyarı
    assert r.kalabalik(uyeler, yuksek)["uyari"] is True
    assert r.kalabalik(uyeler[:4] + [uye(1000, ("ETH", "short", 100))], yuksek)["uyari"] is False                  # N_c = 5 < 6
    onlar = [uye(1000, (f"C{i}", "long", 1)) for i in range(10)]
    assert r.kalabalik(onlar, {**RULES, "kalabalik_net_pay_esik": 2.0})["uyari"] is False                          # her biri farklı coin: aynı yön sayısı 1
    assert r.kalabalik([uye(1000, ("ETH", "long", 100), ("X", "short", 900)) for _ in range(10)], {**RULES, "kalabalik_net_pay_esik": 2.0})["uyari"] is True     # 10 üye aynı coin/yön


# ------------------------------------------------------------------ motor entegrasyonu
class SpotClient(Client):
    def __init__(self, *a, spot_hata=False, **k):
        super().__init__(*a, **k)
        self.spot_hata, self.spot_okuma = spot_hata, 0

    def info(self, payload, weight=20):
        if payload["type"] == "spotClearinghouseState":
            self.spot_okuma += 1
            if self.spot_hata:
                raise RuntimeError("spot yanıtı yok")
            return {"balances": [{"coin": "UBTC", "total": "1.0"}, {"coin": "USDC", "total": "0"}]}
        return super().info(payload, weight)


def liste(tmp_path, kol):
    (tmp_path / "copytrade").mkdir()
    rows = [{"id": "T1", "adres": ADDRESS, "takma_ad": "Bir", "durum": "izlemede", "t0": str(T0.date())}] + [
        {"id": f"T{i}", "adres": "0x" + str(i) * 40, "takma_ad": f"T{i}", "durum": "izlemede", "t0": str(T0.date()), "kol": kol} for i in (2, 3)]
    rows[0]["kol"] = kol
    (tmp_path / "copytrade/izleme_listesi.yaml").write_text(yaml.safe_dump({"traderlar": rows}))
    return tmp_path


def test_motor_yonsuz_bayrak_gunde_bir_onbellek_ve_kalabalik_alani(tmp_path):
    root, client = liste(tmp_path, "oda"), SpotClient()
    bir = m.run(root, root / "out", client, NOW)
    t = bir["traderlar"][0]
    assert t["yonsuz_bayrak"]["bayrak"] is False and "hata" not in t["yonsuz_bayrak"] and set(t["yonsuz_bayrak"]) >= {"funding_payi", "spot_perp_ters", "maker_payi", "sezgisel"}
    assert bir["kalabalik"]["n_oda"] == 3 and "zaman" in bir["kalabalik"] and bir["kalabalik"]["sezgisel"] is True
    n = len(bir["traderlar"])
    okuma, funding_cagri = client.spot_okuma, sum(c["type"] == "userFunding" and c["startTime"] < m.millis(NOW) - 80 * m.DAY for c in client.calls)
    m.run(root, root / "out", client, NOW + pd.Timedelta(hours=1))                     # aynı gün: spot ve 90 günlük funding yeniden çekilmez
    # spot_okuma = saatlik `hesap_degeri_toplam` okuması (A2-4; her koşuda trader başına +1) + yönsüz önbelleği (günde 1): aynı gün yalnız saatlik okuma artar
    assert client.spot_okuma == okuma + n and sum(c["type"] == "userFunding" and c["startTime"] < m.millis(NOW) - 80 * m.DAY for c in client.calls) == funding_cagri
    m.run(root, root / "out", client, NOW + pd.Timedelta(days=1))                      # ertesi gün: yeniden
    assert client.spot_okuma == okuma + n + 2 * n                                      # ertesi gün: saatlik okuma + yönsüz önbelleğin yenilenmesi (trader başına)


def test_motor_spot_hatasi_gizlenmez_ve_gune_onbellege_girmez(tmp_path):
    root, client = liste(tmp_path, "kontrol"), SpotClient(spot_hata=True)
    sonuc = m.run(root, root / "out", client, NOW)
    b = sonuc["traderlar"][0]["yonsuz_bayrak"]
    assert "spot: spot yanıtı yok" in b["hata"] and b["spot_perp_ters"]["deger"] is None and b["bayrak"] is False
    assert "kalabalik" not in sonuc                                                      # kontrol üyeleri oda kalabalığına girmez
    assert "yonsuz_onbellek" not in json.loads((root / "out/motor.json").read_text())["traderlar"]["T1"]


def test_kolsuz_trader_ek_alan_almaz_ve_sozlesmede_yazili(tmp_path):
    root = liste(tmp_path, "taban")
    sonuc = m.run(root, root / "out", Client(), NOW)
    assert all("yonsuz_bayrak" not in t for t in sonuc["traderlar"]) and "kalabalik" not in sonuc
    metin = (ROOT / "docs/VERI_SOZLESMESI.md").read_text(encoding="utf-8")
    assert "yonsuz_bayrak" in metin and "`kalabalik`" in metin and "kaldıraç ikinci kez çarpılmaz" in metin


def test_yaml_esikleri_sezgisel_ve_belgeli():
    assert [RULES[x] for x in ("yonsuz_funding_payi_esik", "yonsuz_spot_perp_esik", "yonsuz_maker_payi_esik")] == [0.5, 0.8, 0.9]
    assert [RULES[x] for x in ("kalabalik_net_pay_esik", "kalabalik_min_trader", "kalabalik_cakisma_esik", "kalabalik_ayni_yon_sayi")] == [0.35, 6, 0.8, 10]
    yaml_metni = (ROOT / "copytrade/kurallar.yaml").read_text(encoding="utf-8")
    assert "Eşikler SEZGİSEL" in yaml_metni and "GOREV_ODA_RISK" in yaml_metni
