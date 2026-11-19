"""2. denetim K-1 (altın örnekler): motor KAPALIYKEN yapılan yatırma/çekme açılışta ofsete girer (sahte günlük fren / DUR / zirve şişmesi yok); ledger okunamazsa açılış bayrağı `ofset`,
risk yerel defterle (DUR yok); transfer türleri; bayrak yeniden başlatmada bayatlamaz; açıklanamayan sıçrama diske yazılır. Risk oranları üretim kurallarından (`load_rules`, yalnız boyut anahtarları v1)."""
from __future__ import annotations

import pytest

from copytrade.canli import motor as mt
from tests.test_canli_motor import kayitlar
from tests.test_canli_t4b import HLADR
from tests.test_canli_t4b import kur_gercek as _kur
from tests.test_k41_ofset import LedgerSim, _satir

DIGER = "0x" + "cd" * 20


@pytest.fixture(autouse=True)
def _m():
    yield
    mt.MASKE.clear()


class HataliLedgerSim(LedgerSim):
    ledger_hata = False

    def post(self, y):
        if y["type"] == "userNonFundingLedgerUpdates" and self.ledger_hata:
            raise RuntimeError("ledger down")
        return super().post(y)


def _calisan(tmp_path, monkeypatch, sim):
    m, sim, saat, tgp = _kur(tmp_path, monkeypatch, sim)
    m.baslat()
    m.dakika()
    saat.ms += 60_000
    m.dakika()
    assert m.hl_ofset == pytest.approx(0.0) and m.risk.zirve == pytest.approx(1000.0) and m.ledger_son_ms is not None
    m.durum_yaz()
    return m, sim, saat, tgp


def _yeniden(tmp_path, monkeypatch, sim, saat, tgp=None):
    m2, _, _, tgp2 = _kur(tmp_path, monkeypatch, sim, saat=saat, tgp=tgp)
    m2.baslat()
    return m2, tgp2


def _dakikalar(m, saat, n=3):
    cikti = []
    for _ in range(n):
        m.dakika()
        cikti.append((round(m.ozsermaye(), 6), m.hl_ofset, round(m.risk.zirve, 6), m.risk.dur, m.dur_dosyasi.exists()))
        saat.ms += 60_000
    return cikti


def test_motor_kapaliyken_cekim_300_ofset_eksi300_ozsermaye_1000_dur_yok_zirve_1000(tmp_path, monkeypatch):
    """HL 1.000, kasa 1.000, ofset 0, zirve 1.000. Motor kapalıyken 300 $ çekim (HL 700): açılışta ofset −300, özsermaye 700 − (−300) = 1.000, DUR yok, zirve 1.000; günlük fren yok."""
    sim = HataliLedgerSim(deger=1000.0)
    m, sim, saat, _ = _calisan(tmp_path, monkeypatch, sim)
    saat.ms += 600_000
    sim.ledger.append(_satir(saat.ms, 300.0, "withdraw"))
    sim.deger = 700.0
    saat.ms += 600_000
    m2, _ = _yeniden(tmp_path, monkeypatch, sim, saat)
    m2.ilk_mutabakat()
    assert m2.hl_ofset == pytest.approx(-300.0) and m2.ozsermaye() == pytest.approx(1000.0)
    assert not m2.risk.acilis_durdu.get("ofset") and not m2.risk.acilis_durdu.get("mutabakat")
    for oz, ofset, zirve, dur, dosya in _dakikalar(m2, saat):
        assert (oz, ofset, zirve, dur, dosya) == (pytest.approx(1000.0), pytest.approx(-300.0), pytest.approx(1000.0), False, False)
    assert not [k for k in kayitlar(tmp_path, "risk")] and not kayitlar(tmp_path, "hl_sicrama")


def test_motor_kapaliyken_yatirma_300_zirve_sismez_iki_dakika_sonra_dur_yok(tmp_path, monkeypatch):
    sim = HataliLedgerSim(deger=1000.0)
    m, sim, saat, _ = _calisan(tmp_path, monkeypatch, sim)
    saat.ms += 600_000
    sim.ledger.append(_satir(saat.ms, 300.0, "deposit"))
    sim.deger = 1300.0
    saat.ms += 600_000
    m2, _ = _yeniden(tmp_path, monkeypatch, sim, saat)
    m2.ilk_mutabakat()
    assert m2.hl_ofset == pytest.approx(300.0)
    for oz, ofset, zirve, dur, dosya in _dakikalar(m2, saat, 4):
        assert (oz, zirve, dur, dosya) == (pytest.approx(1000.0), pytest.approx(1000.0), False, False)
    assert not kayitlar(tmp_path, "risk")


def test_ledger_okunamadi_acilis_bayragi_ofset_dur_yok_risk_yerel_3_hatada_alarm_sonra_duzelir(tmp_path, monkeypatch):
    """Ledger kapalı + 300 $ çekim: ofset bilinmiyor → açılış bayrağı `ofset`, risk YEREL defterle (HL 700'e rağmen 1.000), DUR yok; 3. başarısız okumada alarm; ledger gelince ofset −300, bayrak kalkar."""
    sim = HataliLedgerSim(deger=1000.0)
    m, sim, saat, _ = _calisan(tmp_path, monkeypatch, sim)
    saat.ms += 600_000
    sim.ledger.append(_satir(saat.ms, 300.0, "withdraw"))
    sim.deger = 700.0
    saat.ms += 600_000
    sim.ledger_hata = True
    m2, tgp2 = _yeniden(tmp_path, monkeypatch, sim, saat)
    m2.ilk_mutabakat()
    assert m2.risk.acilis_durdu["ofset"] is True
    assert m2.ozsermaye() == pytest.approx(1000.0) and not m2.risk.dur and not m2.risk.acilis_durdu.get("mutabakat")
    assert not any("okunamıyor" in x for x in tgp2.gonderilen)                   # 1. hata: alarm yok
    for _ in range(3):
        m2.dakika()                                                            # her dakika yeniden denenir (HL koşulundan bağımsız)
        saat.ms += 60_000
        assert m2.risk.acilis_durdu["ofset"] is True and not m2.risk.dur and m2.ozsermaye() == pytest.approx(1000.0) and not m2.dur_dosyasi.exists()
    assert sum("okunamıyor" in x for x in tgp2.gonderilen) == 1                  # 3. ardışık başarısızlıkta tek alarm
    assert not [k for k in kayitlar(tmp_path, "risk")]
    sim.ledger_hata = False
    m2.dakika()
    assert m2.risk.acilis_durdu["ofset"] is False and m2.hl_ofset == pytest.approx(-300.0) and m2.ozsermaye() == pytest.approx(1000.0) and not m2.risk.dur


def test_ofset_alarmi_6_saatte_bir_yinelenir(tmp_path, monkeypatch):
    sim = HataliLedgerSim(deger=1000.0)
    m, sim, saat, _ = _calisan(tmp_path, monkeypatch, sim)
    sim.ledger_hata = True
    m2, tgp2 = _yeniden(tmp_path, monkeypatch, sim, saat)
    m2.ilk_mutabakat()
    for _ in range(125):
        saat.ms += 60_000
        m2.dakika()
    assert sum("okunamıyor" in x for x in tgp2.gonderilen) == 1                  # 3. dakikada; aynı uyarı 6 saatte bir (ortak `Telegram.uyar`)


@pytest.mark.parametrize("satir,net", [
    ({"type": "internalTransfer", "usdc": "50", "user": DIGER, "destination": HLADR}, 50.0),
    ({"type": "internalTransfer", "usdc": "50", "user": HLADR, "destination": DIGER}, -50.0),
    ({"type": "subAccountTransfer", "usdc": "40", "user": HLADR.upper().replace("0X", "0x"), "destination": DIGER}, -40.0),
    ({"type": "spotTransfer", "token": "USDC", "amount": "25", "user": DIGER, "destination": HLADR}, 25.0),
    ({"type": "send", "token": "USDC", "amount": "30", "user": HLADR, "destination": DIGER}, -30.0),
])
def test_transfer_turleri_ofseti_yonuyle_kaydirir(tmp_path, monkeypatch, satir, net):
    sim = HataliLedgerSim(deger=1000.0)
    m, sim, saat, _ = _calisan(tmp_path, monkeypatch, sim)
    sim.deger = 1000.0 + net
    sim.ledger.append({"time": saat.ms + 1000, "hash": "0xt", "delta": satir})
    saat.ms += 60_000
    m.dakika()
    assert m.hl_ofset == pytest.approx(net) and m.ozsermaye() == pytest.approx(1000.0) and not m.risk.dur and not m.risk.acilis_durdu.get("mutabakat")
    assert not kayitlar(tmp_path, "hl_sicrama")


def test_sayilmayan_transfer_turleri_atlanir_sicrama_yakalar(tmp_path, monkeypatch):
    """USDC olmayan `send`, `accountClassTransfer`, yönü belirsiz `internalTransfer` ofseti KAYDIRMAZ (atlanan olarak kayıt)."""
    sim = HataliLedgerSim(deger=1000.0)
    m, sim, saat, _ = _calisan(tmp_path, monkeypatch, sim)
    t = saat.ms + 1000
    sim.ledger += [{"time": t, "hash": "0x1", "delta": {"type": "send", "token": "PURR", "amount": "9", "user": HLADR, "destination": DIGER}},
                   {"time": t + 1, "hash": "0x2", "delta": {"type": "accountClassTransfer", "usdc": "77", "toPerp": True}},
                   {"time": t + 2, "hash": "0x3", "delta": {"type": "internalTransfer", "usdc": "5"}}]
    saat.ms += 60_000
    m.dakika()
    assert m.hl_ofset == pytest.approx(0.0)
    assert kayitlar(tmp_path, "ofset_atlanan_tur")[-1]["turler"] == {"send": 1, "accountClassTransfer": 1, "internalTransfer": 1}


def test_bayat_ofset_bayragi_yeniden_baslatmada_kalkar(tmp_path, monkeypatch):
    """risk.json'da `ofset` bayrağı açık kalmış (önceki süreç ledger okuyamadı). Yeni süreç: yapıcıda bayat bayrak temizlenir; açılışta ledger okunursa kalkık kalır, okunamazsa yeniden konur."""
    sim = HataliLedgerSim(deger=1000.0)
    m, sim, saat, _ = _calisan(tmp_path, monkeypatch, sim)
    m.risk.bayrak("ofset", True)
    m.durum_yaz()
    m2, _ = _yeniden(tmp_path, monkeypatch, sim, saat)
    assert m2.risk.acilis_durdu.get("ofset") is False                             # ilk_mutabakat öncesi bile bayat değil
    m2.ilk_mutabakat()
    assert m2.risk.acilis_durdu["ofset"] is False and not m2.risk.acilis_durdu.get("mutabakat")
    m2.risk.bayrak("ofset", True)
    m2.durum_yaz()
    sim.ledger_hata = True
    m3, _ = _yeniden(tmp_path, monkeypatch, sim, saat)
    m3.ilk_mutabakat()
    assert m3.risk.acilis_durdu["ofset"] is True
    sim.ledger_hata = False
    m3.dakika()
    assert m3.risk.acilis_durdu["ofset"] is False


def test_acilista_aciklanamayan_sicrama_bayrak_alarm_dur_yok_ve_hafiza_diske_yazilir(tmp_path, monkeypatch):
    """Motor kapalıyken ledger'a yansımayan −200 $ (HL 800; transfer/tasfiye) > kasa × %10: `hl_sicrama` (bayrak + alarm), mutabakat bayrağı, DUR YOK. Hafıza `motor.json`da."""
    sim = HataliLedgerSim(deger=1000.0)
    m, sim, saat, _ = _calisan(tmp_path, monkeypatch, sim)
    import json
    kayit = json.loads((tmp_path / "durum" / "motor.json").read_text())
    assert kayit["hl_onceki"] == [pytest.approx(1000.0), pytest.approx(1000.0)]
    saat.ms += 600_000
    sim.deger = 800.0                                                            # ledger boş: açıklanamayan
    m2, tgp2 = _yeniden(tmp_path, monkeypatch, sim, saat)
    m2.ilk_mutabakat()
    assert m2._hl_sicrama is True and kayitlar(tmp_path, "hl_sicrama")[-1]["aciklanmayan_usd"] == pytest.approx(-200.0)
    assert m2.risk.acilis_durdu["mutabakat"] is True and any("sıçrama" in x for x in tgp2.gonderilen)
    m2.dakika()
    assert not m2.risk.dur and not m2.dur_dosyasi.exists()
    m2.durum_yaz()
    kayit = json.loads((tmp_path / "durum" / "motor.json").read_text())
    assert kayit["hl_sicrama"] is True and kayit["hl_sicrama_ms"] > 0
