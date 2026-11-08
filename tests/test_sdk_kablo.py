"""G-22: HL resmi SDK (kilitli sürüm, `requirements-canli.lock`) ile AĞSIZ kablo biçimi testi. CI `canli_sdk` işi kilitten kurar ve `SDK_ZORUNLU=1` ile çalıştırır (SDK yoksa HATA);
yerelde SDK kurulu değilse modül atlanır. Ağ yok: `Exchange` meta verisi enjekte, HTTP oturumu sahte (gönderilen yük yakalanır). Anahtar test için üretilmiş sabit, gerçek DEĞİL.

Altın değerler (elle): BTC en iyi satış 100, bant 0,005 → 100,5; szDecimals 5 → tick max(0,01, 0,1) = 0,1 → limit "100.5"; 100 $ / 100 = 1 BTC → "1"."""
from __future__ import annotations

import inspect
import os

import pytest

try:
    import hyperliquid  # noqa: F401
except ImportError:
    if os.environ.get("SDK_ZORUNLU") == "1":
        raise
    pytest.skip("hyperliquid-python-sdk kurulu değil (CI canli_sdk işi kilitten kurar)", allow_module_level=True)

from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from hyperliquid.utils.signing import order_request_to_order_wire, sign_l1_action
from hyperliquid.utils.types import Cloid

from copytrade.canli import yurutucu as yu
from copytrade.canli.niyet import cloid_uret
from copytrade.kurallar import load_rules

TEST_ANAHTAR = "0x" + "4c" * 32                      # test sabiti (gerçek cüzdan değil)
HESAP = "0x" + "ab" * 20
META = {"universe": [{"name": "BTC", "szDecimals": 5}, {"name": "ETH", "szDecimals": 4}]}
SPOT_META = {"universe": [], "tokens": []}


def test_cloid_bizim_uretecimizi_kabul_eder():
    c = cloid_uret("0xabc:123", "ac")
    assert len(c) == 34 and Cloid.from_str(c).to_raw() == c and yu.cloid_nesne(c).to_raw() == c
    with pytest.raises(TypeError):
        Cloid.from_str(c[:-2])                         # 15 bayt: reddedilir


def test_emir_kablosu_altin():
    c = Cloid.from_str(cloid_uret("k", "kapat"))
    tel = order_request_to_order_wire({"coin": "BTC", "is_buy": False, "sz": 0.00099, "limit_px": 99.5, "order_type": yu.TIF_IOC, "reduce_only": True, "cloid": c}, 0)
    assert tel == {"a": 0, "b": False, "p": "99.5", "s": "0.00099", "r": True, "t": {"limit": {"tif": "Ioc"}}, "c": c.to_raw()}


def test_exchange_imzasi_timeout_ve_account_address():
    p = inspect.signature(Exchange.__init__).parameters
    assert {"wallet", "base_url", "meta", "account_address", "spot_meta", "perp_dexs", "timeout"} <= set(p)
    assert list(inspect.signature(Exchange.order).parameters)[:7] == ["self", "name", "is_buy", "sz", "limit_px", "order_type", "reduce_only"]
    assert "cloid" in inspect.signature(Exchange.order).parameters
    assert list(inspect.signature(Exchange.update_leverage).parameters) == ["self", "leverage", "name", "is_cross"]


class SahteYanit:
    def __init__(self, veri):
        self.status_code, self.veri, self.text, self.headers = 200, veri, "", {}

    def json(self):
        return self.veri


class SahteOturum:
    def __init__(self):
        self.cagrilar, self.headers = [], {}

    def post(self, url, json=None, timeout=None):
        self.cagrilar.append({"url": url, "yuk": json, "timeout": timeout})
        if json["action"]["type"] == "updateLeverage":
            return SahteYanit({"status": "ok", "response": {"type": "default"}})
        return SahteYanit({"status": "ok", "response": {"type": "order", "data": {"statuses": [{"filled": {"totalSz": "1.0", "avgPx": "100.2", "oid": 7}}]}}})


def info_post(y):
    if y["type"] == "l2Book":
        return {"coin": y["coin"], "time": 0, "levels": [[{"px": "99.9", "sz": "50"}], [{"px": "100", "sz": "50"}]]}
    if y["type"] == "meta":
        return META
    raise AssertionError(y)


def test_gercek_yurutucu_kablo_imza_ve_zaman_asimi(monkeypatch):
    monkeypatch.setattr(Info, "spot_meta", lambda self: SPOT_META)                   # ağ yok
    monkeypatch.setattr(Info, "meta", lambda self, dex="": META)
    monkeypatch.delenv("HL_HESAP_ADRESI", raising=False)                              # gerçek ücret araması (userFillsByTime) yapılmaz
    rules = load_rules()
    yur = yu.gercek_yurutucu_olustur(info_post, rules, ortam={"HL_API_CUZDAN_ANAHTARI": TEST_ANAHTAR, "HL_HESAP_ADRESI": HESAP})
    ex = yur.exchange
    assert ex.base_url == constants.MAINNET_API_URL and ex.account_address == HESAP and ex.timeout == float(rules["canli_emir_zaman_asimi_sn"])
    oturum = SahteOturum()
    ex.session = oturum
    cloid = cloid_uret("0xabc:1", "ac")
    d = yur.emir("BTC", "B", 100.0, cloid=cloid)
    assert d.durum == "dolu" and d.sz == 1.0 and d.px == 100.2
    kaldirac, emir = oturum.cagrilar
    assert all(c["url"] == constants.MAINNET_API_URL + "/exchange" and c["timeout"] == float(rules["canli_emir_zaman_asimi_sn"]) for c in oturum.cagrilar)
    assert kaldirac["yuk"]["action"] == {"type": "updateLeverage", "asset": 0, "isCross": False, "leverage": int(rules["canli_marj_kaldirac"])}
    a = emir["yuk"]["action"]
    assert a == {"type": "order", "orders": [{"a": 0, "b": True, "p": "100.5", "s": "1", "r": False, "t": {"limit": {"tif": "Ioc"}}, "c": cloid}], "grouping": "na"}
    assert emir["yuk"]["vaultAddress"] is None and isinstance(emir["yuk"]["nonce"], int)
    imza = emir["yuk"]["signature"]
    assert set(imza) == {"r", "s", "v"}
    assert imza == sign_l1_action(ex.wallet, a, None, emir["yuk"]["nonce"], None, True)          # deterministik imza: aynı girdi → aynı imza (ana ağ)
    assert TEST_ANAHTAR not in str(oturum.cagrilar)
