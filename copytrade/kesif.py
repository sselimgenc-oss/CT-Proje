"""Keşif verisi: ilişkili hesap işaretleri ve ``kesif.json``.

Yalnız herkese açık Hyperliquid verisi; emir, anahtar, cüzdan yok. İlişkili hesap kontrolü puanı değiştirmez,
yalnız işaret koyar (kaynak: ``arastirma/copytrade/argon_hazir_servis_iliskili_hesap.md``). Şema:
``docs/GOREV_TRADER_SECIMI.md`` (kesif.json v1; adım 8 kümeleme henüz uygulanmadığından ``adimlar`` 1–7'dir).
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from copytrade.kapi import classify_style
from copytrade.kurallar import load_rules
from copytrade.tarama import PublicClient, RateLimitError, RateLimiter

ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
TRANSFER_TYPES = {"internaltransfer", "subaccounttransfer", "spottransfer", "send", "vaultdeposit", "vaultwithdraw"}
RANK = {"kopyalanabilir": 0, "izleme_adayi": 1}


def counterparties(ledger: list[dict], address: str) -> list[str]:
    """Defter satırlarındaki iç transfer karşı adresleri (kendi adresi ve yatırma/çekme hariç)."""
    own, found = address.lower(), []
    for row in ledger:
        delta = row.get("delta", {})
        if not isinstance(delta, dict) or str(delta.get("type", "")).lower() not in TRANSFER_TYPES:
            continue
        for key in ("user", "destination", "sender", "vault"):
            value = str(delta.get(key, row.get(key, "")) or "")
            if ADDRESS.match(value) and value.lower() != own and value.lower() not in found:
                found.append(value.lower())
    return found


def related_accounts(client: PublicClient, address: str, now: datetime) -> dict[str, Any]:
    """Alt hesaplar, vault ilişkileri, ajanlar ve iç transfer karşı adresleri. Her istek ayrı korunur."""
    related: list[str] = []
    notes: list[str] = []
    failed: list[str] = []
    agents: list[str] = []

    def add(values: list[str]) -> None:
        for value in values:
            if value and value.lower() != address.lower() and value.lower() not in related:
                related.append(value.lower())

    def attempt(name: str, call):
        try:
            return call()
        except (RateLimitError, requests.RequestException, ValueError, TypeError, KeyError):
            failed.append(name)
            return None

    subs = attempt("subAccounts", lambda: client.sub_accounts(address)) or []
    subs = [str(x.get("subAccountUser", "")) for x in subs if isinstance(x, dict)]
    add(subs)
    if subs:
        notes.append(f"alt hesap {len(subs)}")
    equities = attempt("userVaultEquities", lambda: client.vault_equities(address)) or []
    led = other = 0
    for item in [x for x in equities if isinstance(x, dict)][:10]:
        vault = str(item.get("vaultAddress", ""))
        details = attempt("vaultDetails", lambda v=vault: client.vault_details(v)) or {}
        leader = str(details.get("leader", "") or "")
        if leader.lower() == address.lower():
            led += 1; add([vault])
        elif vault:
            other += 1; add([vault, leader])
    if led:
        notes.append(f"vault lideri {led}")
    if other:
        notes.append(f"başka vault'ta pay {other}")
    extra = attempt("extraAgents", lambda: client.extra_agents(address)) or []
    agents = [str(x.get("address", "")).lower() for x in extra if isinstance(x, dict) and x.get("address")]
    if agents:
        notes.append(f"API ajanı {len(agents)}")
    start = int((now - timedelta(days=365)).timestamp() * 1000)
    ledger = attempt("userNonFundingLedgerUpdates", lambda: client.non_funding_ledger(address, start)) or []
    partners = counterparties(ledger, address)
    add(partners)
    if partners:
        notes.append(f"iç transfer karşı adres {len(partners)}")
    if failed:
        notes.append("kontrol edilemedi: " + ",".join(sorted(set(failed))))
    return {"adresler": related, "ajanlar": agents, "transfer": partners, "not": "; ".join(notes)}


def link_candidates(info: dict[str, dict[str, Any]]) -> None:
    """Adaylar arası bağlar: ortak API ajanı veya aday adresle iç transfer. ``info`` yerinde güncellenir."""
    by_agent: dict[str, list[str]] = {}
    for address, item in info.items():
        for agent in item["ajanlar"]:
            by_agent.setdefault(agent, []).append(address)
    for address, item in info.items():
        extra = []
        for agent in item["ajanlar"]:
            for other in by_agent[agent]:
                if other.lower() != address.lower() and other.lower() not in item["adresler"]:
                    item["adresler"].append(other.lower()); extra.append("ortak API ajanı")
        for other in info:
            if other.lower() != address.lower() and other.lower() in item["transfer"]:
                extra.append("aday adresle iç transfer")
        if extra:
            item["not"] = "; ".join(filter(None, [item["not"]] + sorted(set(extra))))


def weekly_curve(portfolio: list, days: int = 365) -> list[list]:
    """Son ``days`` gün, haftalık kümülatif PnL / hesap değeri (penceredeki pozitif hesap değerlerinin medyanı)."""
    periods = {name: value for name, value in portfolio if isinstance(value, dict)} if portfolio else {}
    data = periods.get("allTime") or {}
    points = data.get("pnlHistory", [])
    if len(points) < 2:
        return []
    pnl = pd.Series({pd.to_datetime(t, unit="ms", utc=True): float(v) for t, v in points}).sort_index()
    values = pd.Series({pd.to_datetime(t, unit="ms", utc=True): float(v) for t, v in data.get("accountValueHistory", [])})
    since = pnl.index[-1] - pd.Timedelta(days=days)
    before, window = pnl[pnl.index < since], pnl[pnl.index >= since]
    if window.empty:
        return []
    base = float(before.iloc[-1]) if len(before) else float(window.iloc[0])
    positive = values[(values.index >= since) & (values > 0)]
    denominator = float(positive.median()) if len(positive) else 0.0
    if denominator <= 0:
        return []
    weekly = (window.resample("W").last().dropna() - base) / denominator
    return [[str(day.date()), float(value)] for day, value in weekly.items()]


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def step_reasons(row: dict[str, Any], rules: dict | None = None) -> dict[str, dict[str, str]]:
    """Adım 1–7 durumları ve kısa nedenleri (satır değerlerinden; hesap yeniden yapılmaz)."""
    rules = rules or load_rules()
    num = lambda name: _num(row.get(name))
    out: dict[str, dict[str, str]] = {}
    for i in range(1, 8):
        status, reason = str(row.get(f"adim{i}") or "Yetersiz"), ""
        if status != "Geçti":
            if i == 1:
                reason = f"mum kapsamı %{100 * (num('candle_coverage') or 0):.0f} (< %{100 * rules['mum_kapsami_min']:.0f})"
            elif i == 2:
                parts = [f"{n} {v}" for n, v, lim in (("geçmiş gün", num("history_days"), rules["min_history_days"]),
                                                       ("kapanan işlem", num("closed_trades"), rules["min_closed_trades"]),
                                                       ("aktif ay", num("active_months"), rules["min_active_months"])) if v is None or v < lim]
                if row.get("aktif") in (False, "False", "false"):
                    need = rules["aktif_son90_dongu"]["swing" if _str(row.get("tarz")) == "swing" else "intraday"]
                    parts.append(f"aktiflik: son 90 g {num('son90_dongu')} döngü (≥ {need}), son işlem {num('son_islem_gun')} gün (≤ {rules['aktif_son_islem_max_gun']})")
                reason = "yetersiz kanıt: " + ", ".join(parts)
            elif i == 3:
                tarz, parts = _str(row.get("tarz")), []
                if tarz not in ("intraday", "swing"):
                    parts.append("tarz scalp/belirsiz (medyan tutma < 1 sa)")
                if (num("kisa_islem_payi") or 0) > float(rules["kisa_islem_payi_max"]):
                    parts.append(f"kısa işlem payı > %{100 * rules['kisa_islem_payi_max']:.0f}")
                if (num("median_leverage") or math.inf) > float(rules["kapi_max_medyan_kaldirac"]):
                    parts.append(f"medyan kaldıraç > {rules['kapi_max_medyan_kaldirac']:g}x")
                if (num("max_leverage") or math.inf) > float(rules["kapi_max_kaldirac"]):
                    parts.append(f"en yüksek kaldıraç > {rules['kapi_max_kaldirac']:g}x")
                delay = int(_num(row.get("kapi_gecikme_dk")) or rules["kopya_gecikme_dk"]["intraday"])
                if (num(f"gecikme_{delay}dk_net") or 0) <= 0:
                    parts.append(f"{delay} dk gecikmeli kopya net ≤ 0")
                reason = "; ".join(parts)
            elif i == 4:
                parts = []
                if (num("profitable_month_ratio") or 0) < rules["adim4_min_karli_ay_orani"]:
                    parts.append(f"kârlı ay < %{100 * rules['adim4_min_karli_ay_orani']:.0f}")
                if (num("largest_trade_share") if num("largest_trade_share") is not None else 1) >= rules["max_largest_trade_share"]:
                    parts.append(f"en büyük işlem ≥ %{100 * rules['max_largest_trade_share']:.0f}")
                if (num("profit_factor_without_best") or 0) <= rules["min_profit_factor_without_best"]:
                    parts.append(f"PF (en iyisiz) ≤ {rules['min_profit_factor_without_best']:g}")
                if row.get("martingale_signal") in (True, "True", "true"): parts.append("martingale işareti")
                reason = "; ".join(parts)
            elif i == 5:
                p = num("plasebo_p")
                reason = (f"p = {p:.3f} > {rules['plasebo_p_max']}" if p is not None else
                          (_str(row.get("plasebo_hata")) or "plasebo hesaplanmadı (adım 3–4 geçmedi)"))
            elif i == 6:
                alpha, t = num("alfa_yillik"), num("nw_t")
                reason = ("alfa hesaplanamadı" if alpha is None else f"alfa ≤ 0 ({_str(row.get('alfa_kiyas'))})" if alpha <= 0
                          else f"NW t = {t:.2f} < {rules['alfa_t_min']:g}")
            elif i == 7:
                q = num("bhy_q")
                reason = f"BHY q = {q:.3f} > {rules['bhy_q_max']:g}" if q is not None else "plaseboya ulaşmadı"
        out[str(i)] = {"durum": status, "neden": reason}
    return out


def build_entry(row: dict[str, Any], curve: list[list], related: dict[str, Any] | None, rules: dict | None = None) -> dict[str, Any]:
    rules = rules or load_rules()
    num = lambda name: _num(row.get(name))
    shares = {name: num(f"pay_{name}") for name in ("kripto", "hisse", "endeks", "emtia")}
    adaylar_not = (related or {}).get("not", "")
    return {
        "adres": row["address"], "tarz": _str(row.get("tarz")) or classify_style(num("median_holding_hours"), rules),
        "katman": row["katman"], "genc_aday": row.get("genc_aday") in (True, "True", "true", 1),
        "gecmis_gun": num("gecmis_gun"), "kapanan_islem": num("closed_trades"), "aktif_ay": num("active_months"),
        "hesap_degeri": num("account_value"),
        "piyasa_payi": {k: v for k, v in shares.items() if v},
        "binance_payi": num("binance_payi"),
        "medyan_tutma_sa": num("median_holding_hours"), "kisa_islem_payi": num("kisa_islem_payi"),
        "medyan_kaldirac": num("median_leverage"), "max_kaldirac": num("max_leverage"),
        "kopya": {"g30": num("gecikme_30dk_net"), "g120": num("gecikme_120dk_net"), "g480": num("gecikme_480dk_net")},
        "karli_ay_orani": num("profitable_month_ratio"), "en_buyuk_islem_payi": num("largest_trade_share"),
        "pf_en_iyisiz": num("profit_factor_without_best"), "max_dusus": num("max_drawdown"), "getiri_12a": num("return_12m"),
        "plasebo_p": num("plasebo_p"), "alfa_t": num("nw_t"), "alfa_kiyas": _str(row.get("alfa_kiyas")) or None,
        "bhy_q": num("bhy_q"),
        "adimlar": step_reasons(row, rules),
        "iliskili_adresler": ";".join((related or {}).get("adresler", [])),
        "iliskili_not": adaylar_not, "egri": curve,
    }


def build_kesif(table: pd.DataFrame, now: datetime, evren: int | None, curves: dict[str, list[list]],
                related: dict[str, dict[str, Any]], rules: dict | None = None) -> dict[str, Any]:
    """Yalnız katmanı ``yok`` olmayanlar; sıra: katman, genç olmayanlar önce, ``alfa_t`` azalan."""
    rules = rules or load_rules()
    rows = [r for r in table.to_dict("records") if r.get("katman") in RANK]
    entries = [build_entry(r, curves.get(r["address"], []), related.get(r["address"]), rules) for r in rows]
    entries.sort(key=lambda e: (RANK[e["katman"]], e["genc_aday"], -(e["alfa_t"] if e["alfa_t"] is not None else -math.inf)))
    return {"surum": 1, "uretildi": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "evren": evren, "islenen": int(len(table)), "adaylar": entries}


def related_pool(table: pd.DataFrame) -> list[str]:
    """İlişkili hesap işareti aday katmanından önceki kapı havuzunun tamamında çalışır."""
    needed = {"address", "adim1", "adim2"}
    if not needed <= set(table):
        return []
    return table.loc[(table["adim1"] == "Geçti") & (table["adim2"] == "Geçti"), "address"].astype(str).tolist()


def run(root: Path, output: Path, client: PublicClient, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    rules = load_rules()
    paths = sorted((root / "kapi").glob("*/sonuc.csv"))
    if not paths:
        raise FileNotFoundError("sonuc.csv yok; önce kapı koşusu gerekli.")
    path = paths[-1]
    table = pd.read_csv(path)
    if "katman" not in table:
        table["katman"] = "yok"
    evren_path = path.parent / "evren.json"
    evren = int(json.loads(evren_path.read_text(encoding="utf-8"))["evren"]) if evren_path.exists() else None
    chosen = table[table["katman"].isin(list(RANK))]
    curves: dict[str, list[list]] = {}
    related: dict[str, dict[str, Any]] = {}
    # Eğriler yalnız yayımlanan adaylar içindir; ilişkili hesap keşfi ise kapı
    # havuzunun tamamındadır. Böylece katman eşiği bağlantı kanıtını gizlemez.
    for address in chosen["address"]:
        try:
            curves[address] = weekly_curve(client.portfolio(address))
        except (RateLimitError, requests.RequestException, ValueError, TypeError, KeyError):
            curves[address] = []
    for address in related_pool(table):
        related[address] = related_accounts(client, address, now)
    link_candidates(related)
    table["iliskili_adresler"] = table["address"].map(lambda a: ";".join(related[a]["adresler"]) if a in related else "")
    table["iliskili_not"] = table["address"].map(lambda a: related[a]["not"] if a in related else "")
    table.to_csv(path, index=False)
    result = build_kesif(table, now, evren, curves, related, rules)
    output.mkdir(parents=True, exist_ok=True)
    (output / "kesif.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("copytrade"))
    parser.add_argument("--output", type=Path, default=Path("kesif"))
    args = parser.parse_args(argv)
    result = run(args.root, args.output, PublicClient(limiter=RateLimiter(1000)))
    print(f"Keşif: {len(result['adaylar'])} aday (işlenen {result['islenen']} / evren {result['evren']}).")


if __name__ == "__main__":
    main()
