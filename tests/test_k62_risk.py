"""K-62 (11.11, Fable "dengeli" risk listesi): günlük sert fren, felaket stopu, sığ coin tavanı."""
import pytest

from copytrade.canli import risk as rk
from tests.test_canli_motor import RULES, GUN, SAAT, T0, adr, kayitlar, kur, olay


def test_risk_gunluk_kapat_gunde_bir_kez_ve_gunluk_kayip_ile_birlikte():
    r = rk.Risk(RULES, 1000.0)
    assert r.ozsermaye_isle(1000.0, T0) == []
    assert r.ozsermaye_isle(950.0, T0 + SAAT) == ["gunluk_kayip"]                       # −%5: yalnız açılış durur
    assert r.ozsermaye_isle(900.0, T0 + 2 * SAAT) == ["gunluk_kapat"]                   # −%10: sert fren
    assert r.ozsermaye_isle(890.0, T0 + 3 * SAAT) == []                                 # aynı gün ikinci kez yok
    assert rk.Risk(RULES, 1000.0, r.to_json()).ozsermaye_isle(880.0, T0 + 4 * SAAT) == []   # yeniden başlatmada da yok
    assert not r.dur                                                                    # DUR değil


def test_risk_sig_coin_kirp():
    r = rk.Risk(RULES, 1000.0)
    assert r.sig_coin_kirp(200.0, 0.0, None) == (200.0, "")                             # hacim verisi yok: sınır yok
    assert r.sig_coin_kirp(200.0, 0.0, 5e8) == (200.0, "")                              # majör
    assert r.sig_coin_kirp(200.0, 0.0, 1e6) == (150.0, "sig_coin_kirpildi")             # sığ: 150 $ tavan
    assert r.sig_coin_kirp(50.0, 120.0, 1e6) == (30.0, "sig_coin_kirpildi")
    assert r.sig_coin_kirp(50.0, 148.0, 1e6) == (0.0, "sig_coin_tavani")                # kalan 2 $ < min emir


def test_motor_gunluk_sert_fren_hepsini_kapatir_dur_yok_ertesi_gun_acilir(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    hl.pozlar[adr(1)] = {"BTC": 300.0}                                                  # trader pozisyonu (senkron kapatmasın)
    assert m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))[0].karar == "emir"
    m.dakika()                                                                          # gün başı kaydı
    m.hesap.realize["x"] = -110.0                                                       # −%11
    m.dakika()
    assert not any(m.hesap.poz.values()) and m.risk.acilis_durdu["gunluk_kayip"] and not m.risk.dur and not (tmp_path / "durum" / "DUR").exists()
    assert any(x["olay"] == "gunluk_kapat" and x["kapanan"] == 1 for x in kayitlar(tmp_path)) and any("sert fren" in x for x in tgp.gonderilen)
    assert m.olay_isle(olay("a:2", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat))[0].neden == "gunluk_kayip"
    saat.ms += GUN                                                                       # ertesi UTC günü: bayrak iner
    m.dakika()
    assert not m.risk.acilis_durdu["gunluk_kayip"]


def test_motor_felaket_stopu_yuzde_20_aleyhe_pozisyonu_kapatir_trader_sahada_kalir(tmp_path):
    m, hl, saat, tgp = kur(tmp_path, kurallar={"canli_slot_dusus_oran": 0.9})              # slot kuralı bu testte devre dışı: yalnız felaket stopu sınanır
    m.baslat()
    hl.pozlar[adr(1)] = {"SOL": 500.0}                                                  # trader 50.000 $ SOL long (hesap 100.000 $) → bizde ~100 $
    assert m.olay_isle(olay("a:1", adr(1), "SOL", "B", 500, 100.0, 0.0, saat))[0].karar == "emir"
    sz = m.hesap.sz(adr(1), "SOL")
    hl.mids["SOL"] = "80.5"                                                             # −%19,5: kapanmaz
    m.dakika()
    assert m.hesap.sz(adr(1), "SOL") == sz and sz > 0
    hl.mids["SOL"] = "80"                                                               # −%20: kapanır
    hl.kitaplar["SOL"] = {"levels": [[{"px": "79.9", "sz": "100000"}], [{"px": "80", "sz": "100000"}]]}
    m.dakika()
    assert m.hesap.sz(adr(1), "SOL") == 0.0 and adr(1) in m.saha.uyeler
    assert any(x["olay"] == "felaket_stop" and x["coin"] == "SOL" and x["kapandi"] for x in kayitlar(tmp_path)) and any("felaket stopu" in x for x in tgp.gonderilen)


def test_risk_sig_coin_tavani_slotla_olceklenir_f01():
    """F-01: tavan = 0,75 × slot. Gerçek kip 1.000 $ / 5 slot (200 $) → 150 $ (eski mutlak değer); sanal 10.000 $ / 11 slot (909,09 $) → 681,82 $."""
    from copytrade.kurallar import load_rules_asil
    uretim = load_rules_asil()
    assert uretim["canli_sig_coin_tavan_slot_oran"] == 0.75
    r = rk.Risk(uretim, 10000.0)
    assert r.sig_coin_tavan(200.0) == pytest.approx(150.0) and r.sig_coin_tavan(10000 / 11) == pytest.approx(681.818, abs=1e-3)
    assert r.sig_coin_kirp(1000.0, 0.0, 1e6, 10000 / 11) == (pytest.approx(681.818, abs=1e-3), "sig_coin_kirpildi")
    assert r.sig_coin_kirp(600.0, 0.0, 1e6, 10000 / 11) == (600.0, "")                  # 909 $ slotta 600 $ sığ coin pozisyonu artık kırpılmaz (eskiden 150 $)
    assert r.sig_coin_kirp(200.0, 0.0, 1e6, 200.0) == (150.0, "sig_coin_kirpildi")
    assert r.sig_coin_tavan(None) == 150.0                                              # slot yok: mutlak yedek


def test_motor_sig_coin_tavani_trader_basina_150(tmp_path):
    m, hl, saat, _ = kur(tmp_path, kurallar={"radar_canli_slot_min_usd": 200})            # F-01: gerçek kip ölçeği 1.000 $ / 5 slot (200 $) → tavan 0,75 × 200 = 150 $
    m.baslat()
    m._coin_hacim = {"BTC": 1e9, "ETH": 1e6}                                            # ETH bu testte sığ
    s = m.olay_isle(olay("a:1", adr(1), "ETH", "B", 100, 2000.0, 0.0, saat))            # trader 200.000 $ / hesap 100.000 $ → hedef 400 $ (slot 200 $) → sığ: 0,75 × 200 = 150 $
    assert s[0].karar == "emir" and s[0].neden == "sig_coin_kirpildi" and abs(m.hesap.sz(adr(1), "ETH")) * 2000.0 == pytest.approx(150.0, rel=0.01)
    assert m.olay_isle(olay("a:2", adr(1), "ETH", "B", 10, 2000.0, 100.0, saat))[0].neden == "sig_coin_tavani"    # artırma: tavan dolu
    b = m.olay_isle(olay("a:3", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))             # majör: tavansız
    assert b[0].karar == "emir"
