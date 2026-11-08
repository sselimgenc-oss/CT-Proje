"""Denetim 08.11 S-9 (senkronda spot atlanır), S-10 (HL info ağırlıkları), S-24 (motor düzeyinde 00:00 UTC sınırı)."""
import pytest

from copytrade.canli import motor as mt
from tests.test_canli_motor import GUN, RULES, SAAT, T0, SahteHL, adr, kayitlar, kur


def test_s24_utc_gece_yarisi_siniri_motor_duzeyinde_gun_basi_ve_gunluk_kayip_yenilenir(tmp_path):
    """S-24 (motor düzeyi, 00:00 UTC): T0 = 2027-01-15 08:00 UTC. Kasa 1.000 $; 23:59:59.999'da realize −50 → özsermaye 950 → kayıp (1000 − 950) / 1000 = %5 ≥ sınır %5
    → `gunluk_kayip` (yeni açılış yok). 2027-01-16 00:00:00.000'da ilk `dakika`: gün = 2027-01-16, gün başı = 950 (o anki özsermaye), bayrak iner, açılış yeniden serbest;
    kayıt dosyası yeni güne (`2027-01-16.jsonl`) geçer."""
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.dakika()
    gece = (T0 // GUN + 1) * GUN                                                                # 2027-01-16 00:00:00.000 UTC
    assert gece - T0 == 16 * SAAT
    saat.ms = gece - 1                                                                          # 2027-01-15 23:59:59.999
    m.hesap.realize["x"] = -50.0
    m.dakika()
    assert m.risk.gun == "2027-01-15" and m.risk.gun_basi == pytest.approx(1000.0) and m.risk.acilis_durdu["gunluk_kayip"]
    assert m.risk.acilis_izni(adr(1), "BTC", True, saat())[0] is False
    saat.ms = gece                                                                              # sınır anı: yeni UTC günü
    m.dakika()
    assert m.risk.gun == "2027-01-16" and m.risk.gun_basi == pytest.approx(950.0) and not m.risk.acilis_durdu["gunluk_kayip"]
    assert m.risk.acilis_izni(adr(1), "BTC", True, saat())[0] is True
    m.kayit({"olay": "s24_deneme"})                                                             # sınır anındaki kayıt yeni günün dosyasına
    assert (tmp_path / "kayit" / "2027-01-15.jsonl").exists() and [x["olay"] for x in kayitlar(tmp_path)][-1] == "s24_deneme"
    assert "s24_deneme" in (tmp_path / "kayit" / "2027-01-16.jsonl").read_text(encoding="utf-8")


def test_s9_senkron_spot_coini_atlar_perp_kapanisi_surer(tmp_path):
    """S-9 (11-05 gerçek kaydı: 15 `senkron_kapanis`ın 9'u spot `@142`/`@107`/`@156`): REST `clearinghouseState` spot bakiyesini göstermez → spot coin senkronda
    trader'da 0 görünür. Spot (`@107`, `PURR/USDC`) atlanır: kapanış yok, `poz_senkron` farkı yok, izlenen değer korunur. Perp (BTC, trader REST'te 0) eskisi gibi `senkron_kapanis`."""
    hl = SahteHL(pozlar={adr(1): {}})
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.baslat()
    for coin, px in (("@107", 2.5), ("PURR/USDC", 0.2), ("BTC", 100.0)):                        # K‑42 öncesi kalıntı gibi doğrudan deftere
        m.hesap.uygula(adr(1), coin, "B", 10.0, px, 0.0, saat())
    m.poz_tr[adr(1)] = {"@107": 10.0, "PURR/USDC": 10.0}
    m.senkron_uygula(m.senkron_oku())
    assert [k["coin"] for k in kayitlar(tmp_path, "senkron_kapanis")] == ["BTC"]
    assert m.hesap.sz(adr(1), "@107") == pytest.approx(10.0) and m.hesap.sz(adr(1), "PURR/USDC") == pytest.approx(10.0)
    assert m.poz_tr[adr(1)] == {"@107": 10.0, "PURR/USDC": 10.0}
    assert not any(c in x["fark"] for x in kayitlar(tmp_path, "poz_senkron") for c in ("@107", "PURR/USDC"))
    assert m.senkron_uygula(m.senkron_oku()) == 0                                               # tekrar eden senkronda gürültü yok
    assert [k["coin"] for k in kayitlar(tmp_path, "senkron_kapanis")] == ["BTC"]


def test_s10_agirlik_tablosu_hl_belgesi():
    """S-10: HL info ağırlıkları (belge): l2Book/allMids/clearinghouseState/orderStatus/spotClearinghouseState 2, userRole 60, diğer belgeli türler 20 (bilinmeyen 20)."""
    assert mt.AGIRLIK["userRole"] == 60 and mt.AGIRLIK["spotClearinghouseState"] == 2
    istekler = []

    class Istemci:
        def info(self, yuk, weight):
            istekler.append((yuk["type"], weight))
            return {}
    post = mt.rest_post_olustur(RULES, Istemci())
    for t in ("userRole", "clearinghouseState", "extraAgents", "userFunding"):
        post({"type": t})
    assert istekler == [("userRole", 60), ("clearinghouseState", 2), ("extraAgents", 20), ("userFunding", 20)]


def test_s10_perpdexs_agirligi_20():
    """HL belgesinde ağırlık 2 olanlar: l2Book, allMids, clearinghouseState, orderStatus, spotClearinghouseState, exchangeStatus; perpDexs 20 (güvenli taraf)."""
    assert mt.AGIRLIK["perpDexs"] == 20
