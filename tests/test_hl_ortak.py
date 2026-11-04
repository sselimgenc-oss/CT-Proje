"""hl_ortak (eski kapı modülünden taşınan Binance eşleme ve spot USDC yardımcıları) — test_copytrade_kapi.py'den taşındı, davranış aynı."""
from __future__ import annotations

from datetime import UTC, datetime

from copytrade.hl_ortak import binance_availability, binance_symbol, write_binance_universe


def test_binance_mapping_and_blocked_response_are_information_only(tmp_path):
    class Blocked:
        status_code = 451
    symbols, note = write_binance_universe(tmp_path, datetime(2026, 10, 27, tzinfo=UTC), get=lambda *_a, **_k: Blocked())
    assert symbols is None and note == "HTTP 451"
    assert binance_symbol("kPEPE") == "1000PEPEUSDT"
    assert binance_availability("BTC", symbols) == "bilinmiyor"
    # HIP-3 önek atılır, ad aynı + USDT; Binance listesinde varsa "var" (eski sürüm hepsine "yok" diyordu).
    assert binance_availability("xyz:SPX", {"SPXUSDT"}) == "var"
    assert binance_availability("xyz:SPX", {"BTCUSDT"}) == "yok"
