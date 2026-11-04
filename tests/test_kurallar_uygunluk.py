"""Tek kural kaynağı ve uygunluk (görev 23): görev belgesindeki kullanıcı kararları ile kurallar.yaml aynı; kodda karar eşiği yok."""
from __future__ import annotations

import ast
from collections import Counter
import re
from pathlib import Path

import pytest

from copytrade.kurallar import load_rules

ROOT = Path(__file__).resolve().parents[1]
RULES = load_rules()








def test_kurallar_yaml_ust_duzey_anahtarlari_yinelenmez():
    """YAML yükleyicisi son anahtarı sessizce ezdiği için ham metni de denetler."""
    keys = [line.split(":", 1)[0].strip() for line in (ROOT / "copytrade/kurallar.yaml").read_text(encoding="utf-8").splitlines()
            if line and not line[0].isspace() and not line.startswith("#") and ":" in line]
    duplicate = sorted(key for key, count in Counter(keys).items() if count > 1)
    assert not duplicate, f"kurallar.yaml yinelenen üst düzey anahtarlar: {', '.join(duplicate)}"








# Karar eşikleri koda gömülmez: karşılaştırmalarda "anlamlı" sayı sabiti yok (0, 1, işaret ve sayısal epsilon hariç)
ALLOWED = {0, 1, -1, 2, 100}
ALLOWED_BY_FILE: dict[str, set] = {}
CHECKED = ["defter.py", "olcut.py"]


def numeric_comparisons(path: Path):
    allowed = ALLOWED | ALLOWED_BY_FILE.get(path.name, set())
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                if isinstance(side, ast.Constant) and isinstance(side.value, (int, float)) and not isinstance(side.value, bool):
                    value = side.value
                    if abs(value) < 1e-9 or value in allowed:
                        continue
                    yield node.lineno, value


@pytest.mark.parametrize("name", CHECKED)
def test_no_decision_threshold_literals_in_code(name):
    found = list(numeric_comparisons(ROOT / "copytrade" / name))
    assert not found, f"{name}: karşılaştırmada sayı sabiti (eşik kurallar.yaml'da olmalı): {found}"


