from copytrade.live_koruma import Action, GateState, Limits, Mode, evaluate_order, transition


def request(**overrides):
    values = dict(state=GateState(Mode.DRY_RUN), action="open",
                  trader={"takim": "ilk11", "pozisyon_acik": False},
                  notional_usd=50, gross_notional_usd=100, daily_loss_usd=0,
                  signal_time_ms=100, signal_deadline_ms=200, now_ms=150)
    values.update(overrides)
    return evaluate_order(**values)


def test_dry_run_kabul_sabit_limitleri_ve_emir_gondermeme():
    got = request()
    assert got["kabul"] is True
    assert got["emir_gonderildi"] is False
    assert got["referans_sermaye_usd"] == 100
    assert Limits().daily_loss_usd == 10
    assert Limits().total_gross_notional_usd == 300
    assert Limits().per_order_usd == 100


def test_live_gecis_kilitli_ve_halt_yeni_islemi_durdurur():
    live, reason = transition(GateState(Mode.DRY_RUN), "live_locked")
    assert live.mode == Mode.LIVE_LOCKED and live.halt_new_adds
    assert reason == "gercek_islem_kilitli"
    assert request(state=GateState(Mode.HALTED))["nedenler"] == ["dry_run_aktif_degil", "yeni_ekleme_durduruldu"]


def test_ilk11_taze_sinyal_ve_limitler_giris_kapisidir():
    assert "yalniz_ilk11" in request(trader={"takim": "yedek11"})["nedenler"]
    assert "gec_sinyal" in request(now_ms=201)["nedenler"]
    assert "gunluk_zarar_limiti" in request(daily_loss_usd=10)["nedenler"]
    assert "emir_limiti" in request(notional_usd=100.01)["nedenler"]
    assert "toplam_brut_notional_limiti" in request(gross_notional_usd=251)["nedenler"]


def test_toplam_notional_tavaninda_esitlik_kabul_asim_ret():
    assert request(gross_notional_usd=250, notional_usd=50)["kabul"] is True
    assert "toplam_brut_notional_limiti" in request(gross_notional_usd=250.01, notional_usd=50)["nedenler"]


def test_halt_esnasinda_cikis_serbest_yeni_ve_ekleme_bloklu():
    halted = GateState(Mode.HALTED, True)
    assert request(state=halted, action="add")["kabul"] is False
    got = request(state=halted, action=Action.EXIT,
                  trader={"takim": "paf", "pozisyon_acik": True},
                  daily_loss_usd=99, notional_usd=500, gross_notional_usd=500,
                  now_ms=500, signal_deadline_ms=200)
    assert got["kabul"] is True
    assert got["emir_gonderildi"] is False


def test_cikis_acik_pozisyon_gerektirir():
    got = request(action="exit", trader={"pozisyon_acik": False})
    assert got["nedenler"] == ["acik_pozisyon_yok"]
