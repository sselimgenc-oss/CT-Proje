"""Fixed, auditable candidate rules.  Thresholds live in kurallar.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


RULES = Path(__file__).with_name("kurallar.yaml")


def load_rules(path: Path = RULES) -> dict[str, float | int]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _number(metrics: dict[str, Any], name: str) -> float | None:
    value = metrics.get(name)
    return None if value is None else float(value)


def evaluate(metrics: dict[str, Any], rules: dict[str, float | int] | None = None) -> tuple[str, str]:
    """Return ``aday``, ``yetersiz`` or ``elendi`` and a stable reason string."""
    rules = rules or load_rules()
    insufficient = []
    for metric, limit in (("history_days", rules["min_history_days"]), ("closed_trades", rules["min_closed_trades"])):
        value = _number(metrics, metric)
        if value is None or value < limit:
            insufficient.append(f"{metric}<{limit}")
    if insufficient:
        return "yetersiz", ",".join(insufficient)

    checks = (
        ("profitable_month_ratio", ">=", rules["min_profitable_month_ratio"]),
        ("largest_trade_share", "<", rules["max_largest_trade_share"]),
        ("profit_factor_without_best", ">", rules["min_profit_factor_without_best"]),
        ("sortino", ">", rules["min_sortino"]),
        ("calmar", ">", rules["min_calmar"]),
        ("median_holding_hours", ">=", rules["min_median_holding_hours"]),
        ("median_leverage", "<=", rules["max_median_leverage"]),
        ("max_leverage", "<=", rules["max_leverage"]),
        ("liquid_coin_share", ">=", rules["min_liquid_coin_share"]),
    )
    failures = []
    for name, operator, limit in checks:
        value = _number(metrics, name)
        okay = value is not None and {">=": value >= limit, ">": value > limit, "<": value < limit, "<=": value <= limit}[operator]
        if not okay:
            failures.append(f"{name}{operator}{limit}")
    if metrics.get("martingale_signal"):
        failures.append("martingale_signal")
    return ("aday", "") if not failures else ("elendi", ",".join(failures))


def sabit_tutar_egrisi(rules: dict | None = None) -> Any:
    """Hesap değerinden sabit işlem tutarı üreten eğriyi döndürür."""
    rules = rules or load_rules()
    ref_kasa = float(rules["sabit_tutar_ref_kasa_usd"])
    ref_islem = float(rules["sabit_tutar_ref_islem_usd"])
    us = float(rules["sabit_tutar_us"])
    tavan = float(rules["sabit_tutar_tavan_kasa_usd"])

    def tutar(hesap_usd: float) -> float:
        e = max(1.0, min(float(hesap_usd), tavan))
        return ref_islem * (e / ref_kasa) ** us
    return tutar
