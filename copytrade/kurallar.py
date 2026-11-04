"""Kurallar yükleyici ve sabit tutar eğrisi.  Eşikler kurallar.yaml'da.  (Eski aday süzgeci `evaluate` T1'de silindi.)"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


RULES = Path(__file__).with_name("kurallar.yaml")


def load_rules(path: Path = RULES) -> dict[str, float | int]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


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
