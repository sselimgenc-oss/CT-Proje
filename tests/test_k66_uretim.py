"""K-66 Form Radarı üretim değerleri (testlerde conftest v1 boyut/risk değerlerini yükler; burada dosyadaki gerçek değerler `load_rules_asil`) + sanal 2.200 $ kasa
(gerçek para sınırı 1.000 $ değişmez) + brüt tavanın sanal kasayı bağlamaması + açılış eşiği (K-56'dan korunan sadık boyut)."""
from pathlib import Path

import pytest

from copytrade import boyut
from copytrade.canli import motor as mt
from copytrade.kurallar import load_rules, load_rules_asil

ROOT = Path(__file__).resolve().parents[1]


def test_k66_kurallar_dosyada():
    r = load_rules_asil()
    assert (r["radar_saha_max"], r["radar_canli_slot_min_usd"], r["radar_slot_tavan_carpan"], r["radar_min_emir_yuvarla_alt"]) == (11, 200, 1.5, 5.5)
    assert (r["canli_slot_dusus_oran"], r["canli_bekleme_gun"], r["canli_islem_yok_saat"]) == (0.20, 14, 72)             # slot stop %20 korunur; bekleme / işlem yok RADAR_V1 §5
    assert (r["canli_gunluk_kayip_oran"], r["canli_zirve_dusus_oran"]) == (0.05, 0.20)                                   # risk kilitleri değişmez
    assert (r["radar_kadro_toplam"], r["radar_kadro_ilk"], r["radar_pencere_saat"], r["radar_surum"]) == (30, 11, 168, "v3")
    assert (r["canli_kasa_ust_usd"], r["canli_sanal_kasa_ust_usd"]) == (1000, 10000)                                        # gerçek para ≤ 1.000 $ (K-22/K-26)
    assert boyut.saha_sayisi(10000.0, r) == 11 and boyut.slot_usd(10000.0, r) == pytest.approx(10000.0 / 11)
    assert boyut.saha_sayisi(1000.0, r) == 5 and boyut.slot_usd(1000.0, r) == pytest.approx(200.0)
    assert mt.radar_surum_oku() == "v3"
    assert "--sanal-kasa-usd 10000 " in (ROOT / ".github/workflows/canli_vardiya.yml").read_text(encoding="utf-8")


def test_k66_sanal_kasa_2200_gercek_kasa_1000_ustu_reddedilir():
    r = load_rules_asil()
    assert mt.kasa_ust(r, "gercek") == 1000.0 and mt.kasa_ust(r, "sanal") == 10000.0
    assert mt.kasa_belirle(r, "sanal", {}, 2200) == (2200.0, "arg")
    with pytest.raises(mt.KipHatasi):
        mt.kasa_belirle(r, "sanal", {}, 10000.01)
    assert mt.kasa_belirle(r, "gercek", {"CANLI_KASA_USD": "1000"}) == (1000.0, "ortam")
    for kotu in ("1000.01", "2200"):                                                                       # sanal sınır gerçek kipe sızmaz
        with pytest.raises(mt.KipHatasi, match="CANLI_KASA_USD"):
            mt.kasa_belirle(r, "gercek", {"CANLI_KASA_USD": kotu})
    with pytest.raises(mt.KipHatasi, match="yalnız sanal kipte"):
        mt.kasa_belirle(r, "gercek", {"CANLI_KASA_USD": "1000"}, 2200)
    from copytrade.canli.risk import Risk
    risk = Risk(r, 2200.0)
    assert risk.kasa_siniri_asildi(2200.0) is True                                                         # varsayılan = gerçek para sınırı (sıkı)
    assert risk.kasa_siniri_asildi(2200.0, mt.kasa_ust(r, "sanal")) is False and risk.kasa_siniri_asildi(1000.01, mt.kasa_ust(r, "gercek")) is True


def test_k66_gercek_kipte_1000_ustu_kasa_ile_motor_baslamaz(tmp_path):
    from tests.test_canli_motor import kur_kip
    m, _ = kur_kip(tmp_path, "gercek", 2200.0)
    m.rules = {**m.rules, **{k: load_rules_asil()[k] for k in ("canli_kasa_ust_usd", "canli_sanal_kasa_ust_usd")}}
    with pytest.raises(mt.KipHatasi, match="gercek kip"):
        m.baslat()


def test_k66_brut_tavan_yalniz_h5_defterinde_sanal_kasayi_baglamaz(tmp_path):
    """`risk_dry_run.toplam_brut_tavan_usd` (1.500 $) = 1,5 × referans kasa (1.000 $) ve yalnız H5 dinleyici defterinde (risk_defter/live_koruma) okunur; canlı motor okumaz.
    Uçtan uca: sanal 2.200 $ kasada (N 11, slot 200 $) 9 trader BTC/ETH/SOL'de toplam 1.950 $ brüt açar (her coin ≤ max(%30 × 2.200, 1,5 × 200) = 660 $); 1.500 $'da kesilmez."""
    r = load_rules_asil()
    assert r["risk_dry_run"]["toplam_brut_tavan_usd"] == pytest.approx(1.5 * r["risk_dry_run"]["referans_kasa_usd"])
    for yol in sorted((ROOT / "copytrade/canli").glob("*.py")):
        metin = yol.read_text(encoding="utf-8")
        assert "toplam_brut_tavan_usd" not in metin and "risk_dry_run" not in metin, yol.name
    from tests.conftest import V1_BOYUT_RISK
    from tests.test_canli_motor import SahteHL, adr, kadro, kur, olay, satir

    class HL(SahteHL):
        def __call__(self, y):
            if y["type"] == "meta":
                return {"universe": [{"name": "BTC", "szDecimals": 5}, {"name": "ETH", "szDecimals": 4}, {"name": "SOL", "szDecimals": 2}]}
            return super().__call__(y)

    k = kadro([satir(i, i, 90.0 - i) for i in range(1, 10)])
    m, _, saat, _ = kur(tmp_path, kadro_=k, kasa=2200.0, hl=HL(), kurallar={**{x: r[x] for x in V1_BOYUT_RISK}, "canli_sanal_kasa_ust_usd": r["canli_sanal_kasa_ust_usd"]})
    k["kosu_ms"] = saat() - 3_600_000
    m.baslat()
    assert m.saha.n == 11 and m.saha.slot == pytest.approx(200.0) and len(m.saha.uyeler) == 9
    acilis = [(1, "BTC", 1250, 100.0), (2, "BTC", 1250, 100.0), (3, "BTC", 750, 100.0), (4, "ETH", 62.5, 2000.0), (5, "ETH", 62.5, 2000.0), (6, "ETH", 37.5, 2000.0),
              (7, "SOL", 1250, 100.0), (8, "SOL", 1250, 100.0), (9, "SOL", 750, 100.0)]          # trader hesap 100.000 $: 250 / 250 / 150 $ hedef (≤ 1,5 × 200)
    for i, coin, sz, px in acilis:
        assert [(x.eylem, x.karar) for x in m.olay_isle(olay(f"k66:{i}", adr(i), coin, "B", sz, px, 0.0, saat))] == [("ac", "emir")]
    brut = m.hesap.brut_toplam(m.marks)
    assert brut == pytest.approx(1950.0, rel=0.01) and brut > 1500.0


def test_k66_acilis_esigi_5_5_alti_acilmaz_ustu_11e_yuvarlanir():
    r = {**load_rules_asil()}
    # slot 200 $, trader hesap 100.000 $: hedef = 200 × nosyonel / 100.000
    assert boyut.hedef_emir("ac", 0, 2.0, 100_000, 0, 200, 1_000.0, r) == (0.0, "min_emir_atlandi")
    assert boyut.hedef_emir("ac", 0, 3.0, 100_000, 0, 200, 1_000.0, r) == (11.0, "min_emir_yuvarlandi")       # hedef 6 $ ≥ 5,5 → 11 $
    assert boyut.hedef_emir("ac", 0, 2.75, 100_000, 0, 200, 1_000.0, r) == (11.0, "min_emir_yuvarlandi")      # tam 5,5 sınır dahil
    assert boyut.hedef_emir("ac", 0, 200.0, 100_000, 0, 200, 1_000.0, r) == (300.0, "tavan_kirpildi")        # 400 $ → tavan 1,5 × 200
    v1 = load_rules()                                                                                         # testlerde v1 (alt sınır 0): her küçük hedef yuvarlanır
    assert boyut.hedef_emir("ac", 0, 2.0, 100_000, 0, 200, 1_000.0, v1) == (11.0, "min_emir_yuvarlandi")


def test_k66_motor_uctan_uca_uretim_boyutuyla(tmp_path):
    """Fable ek gözlemi (denetim 10.11): motor uçtan uca ÜRETİM boyutuyla (conftest'in v1 yaması olmadan; dosyadaki 7 anahtar).
    Kasa 1.000 $, N = min(11, 1.000 / 200) = 5 → slot 200 $. Trader hesap 100.000 $:
    - 300 BTC × 100 $ = 30.000 $ (oran 0,30) → açılış 200 × 0,30 = 60 $.
    - +10 BTC (310 → hedef 62 $, fark 2 $) ve +40 BTC (350 → hedef 70 $, fark 10 $ < en küçük emir) → artırma atlanır (min_emir_atlandi).
    - +1.000 BTC (1.350 → hedef 270 $ ≤ tavan 1,5 × 200 = 300 $) → artırma 270 − 60 = 210 $.
    - 20 ETH × 100 $ = 2.000 $ → hedef 4 $ < 5,5 $ → açılmaz; 40 SOL × 100 $ = 4.000 $ → hedef 8 $ ≥ 5,5 $ → en küçük emre (11 $) yuvarlanır."""
    from tests.conftest import V1_BOYUT_RISK
    from tests.test_canli_motor import adr, kayitlar, kur, olay
    asil = load_rules_asil()
    m, _, saat, _ = kur(tmp_path, kurallar={k: asil[k] for k in V1_BOYUT_RISK})
    m.baslat()
    assert m.saha.slot == pytest.approx(200.0)
    adim = [("a:1", 300, 0.0, ("ac", "emir")), ("a:2", 10, 300.0, ("artir", "atlandi")), ("a:3", 40, 310.0, ("artir", "atlandi")), ("a:4", 1000, 350.0, ("artir", "emir"))]
    for kimlik, sz, once, beklenen in adim:
        assert [(x.eylem, x.karar) for x in m.olay_isle(olay(kimlik, adr(1), "BTC", "B", sz, 100.0, once, saat))] == [beklenen]
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(2.7)
    assert [(x.karar, x.neden) for x in m.olay_isle(olay("b:1", adr(1), "ETH", "B", 20, 100.0, 0.0, saat))] == [("atlandi", "min_emir_atlandi")]
    assert [(x.karar, x.neden) for x in m.olay_isle(olay("b:2", adr(1), "SOL", "B", 40, 100.0, 0.0, saat))] == [("emir", "min_emir_yuvarlandi")]
    assert [(e["coin"], e["usd_istenen"]) for e in kayitlar(tmp_path, "emir")] == [("BTC", pytest.approx(60.0)), ("BTC", pytest.approx(210.0)), ("SOL", pytest.approx(11.0))]
