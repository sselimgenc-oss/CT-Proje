"""R3-2: haber.ton alt-dize eşleşmesi: 'issue'->'sue', 'bank'->'ban', 'against'->'gain', 'enterprise'->'rise' yanlış ton üretir."""
from copytrade.canli import haber


def test_ton_masum_basliklar_notr_olmali():
    for b in ("Circle issues new statement on reserves", "Bitcoin ETF flows against expectations", "Major bank opens crypto desk", "Enterprise adoption of Bitcoin grows"):
        assert haber.ton(b) in ("notr", "pozitif"), (b, haber.ton(b))
    assert haber.ton("Circle issues new statement on reserves") == "notr"
    assert haber.ton("Major bank opens crypto desk") == "notr"   # 'bank' -> 'ban' negatif


def test_haber_ters_filtresi_yanlis_negatifle_long_atlatir(tmp_path):
    from tests.test_canli_motor import adr, kur
    m, hl, saat, _ = kur(tmp_path, kurallar={"sanal_rejim_filtre": False, "sanal_duygu_filtre": False, "sanal_haber_filtre": True})
    m.baslat()
    t = saat()
    m.haber_anlik = {"haber_ms": t, "haberler": [{"t": t - 1000, "b": "Bitcoin issue tracker reopens", "ton": haber.ton("Bitcoin issue tracker reopens")},
                                                 {"t": t - 2000, "b": "Bitcoin bank adds custody", "ton": haber.ton("Bitcoin bank adds custody")}]}
    neden, _c = m._sanal_acilis_filtresi(adr(1), "BTC", True, t)
    assert neden is None, neden


def test_ton_dogru_pozitifler_ve_negatifler_korunur():
    for b, t in (("Bitcoin surges after ETF approved", "pozitif"), ("SEC bans exchange", "negatif"), ("Banned token plunges", "negatif"), ("Market sell-off deepens", "negatif"),
                 ("Whale liquidations hit ETH", "negatif"), ("Prices rising again", "pozitif"), ("BTC SURGE", "pozitif"), ("Firm to sue exchange over hack", "negatif"),
                 ("Bank adopts bitcoin", "pozitif")):
        assert haber.ton(b) == t, (b, haber.ton(b))
