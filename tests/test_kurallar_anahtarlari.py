"""Kalan kodun `load_rules()` ile okuduğu her anahtar `kurallar.yaml`'da bulunmalı (T1: silinen koddan kalan/eksik anahtar kırığı olmasın).

Kaynak taraması: `rules['x']`, `kural['x']`, `RULES['x']`, `load_rules()['x']`, `.get('x')` biçimleri (alt-anahtar okumaları bu testin kapsamı dışı).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from copytrade.kurallar import load_rules

ROOT = Path(__file__).resolve().parents[1]
KURAL_ADLARI = {"rules", "kural", "kurallar", "RULES"}


def _kural_nesnesi(node: ast.AST) -> bool:
    if isinstance(node, ast.BoolOp):                      # (rules or load_rules())['x']
        return any(_kural_nesnesi(v) for v in node.values)
    if isinstance(node, ast.Name):
        return node.id in KURAL_ADLARI
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "load_rules"


def okunan_anahtarlar(path: Path) -> set[str]:
    bulunan = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Subscript) and _kural_nesnesi(node.value) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            bulunan.add(node.slice.value)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and _kural_nesnesi(node.func.value)
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            bulunan.add(node.args[0].value)
    return bulunan


def test_tarama_gercekten_anahtar_buluyor():
    """Tarayıcı boş dönmesin: bilinen okumalar yakalanmalı."""
    assert {"maliyet_taker", "maliyet_kayma"} <= okunan_anahtarlar(ROOT / "copytrade/hl_ortak.py")
    assert "veri_tazelik_dk" in okunan_anahtarlar(ROOT / "copytrade/izleme_motoru.py")


@pytest.mark.parametrize("yol", sorted((ROOT / "copytrade").glob("*.py")), ids=lambda p: p.name)
def test_kodun_okudugu_her_kural_anahtari_yaml_da_var(yol):
    eksik = sorted(okunan_anahtarlar(yol) - set(load_rules()))
    assert not eksik, f"{yol.name}: kurallar.yaml'da olmayan anahtar(lar): {eksik}"
