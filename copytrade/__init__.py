"""Hyperliquid public-data candidate scanner.

This package deliberately has no signing, wallet, or order-placement code.

`calculate_metrics` tembelce (PEP 562) yüklenir: `copytrade.dinleyici` sunucuda pandas olmadan çalışır (requirements-dinleyici.txt).
"""

__all__ = ["calculate_metrics"]


def __getattr__(name):
    if name == "calculate_metrics":
        from .olcut import calculate_metrics
        return calculate_metrics
    raise AttributeError(f"module 'copytrade' has no attribute {name!r}")
