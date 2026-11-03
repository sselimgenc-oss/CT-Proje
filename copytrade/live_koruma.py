"""Faz 3 emir koruması için saf dry-run karar motoru.

Bu modül yalnızca karar kaydı üretir. Ağ, cüzdan, imzalama veya emir gönderme
yüzeyi içermez. Gerçek işlem modu bu sürümde kilitlidir.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Any


class Mode(StrEnum):
    DISABLED = "disabled"
    DRY_RUN = "dry_run"
    HALTED = "halted"
    LIVE_LOCKED = "live_locked"


class Action(StrEnum):
    OPEN = "open"
    ADD = "add"
    EXIT = "exit"


@dataclass(frozen=True)
class Limits:
    starting_reference_usd: float = 100.0
    daily_loss_usd: float = 10.0
    total_gross_notional_usd: float = 300.0
    per_order_usd: float = 100.0
    trader_cap_usd: float = 200.0           # H5: trader başına açık brüt notional tavanı ($)

    @classmethod
    def from_rules(cls, rules: dict[str, Any] | None = None) -> "Limits":
        """`kurallar.yaml` `risk_dry_run` bloğundan (tek kaynak, kural 7)."""
        from copytrade.kurallar import load_rules
        r = (rules or load_rules())["risk_dry_run"]
        return cls(starting_reference_usd=float(r["referans_kasa_usd"]), daily_loss_usd=float(r["gunluk_zarar_usd"]),
                   total_gross_notional_usd=float(r["toplam_brut_tavan_usd"]), per_order_usd=float(r["emir_tavan_usd"]),
                   trader_cap_usd=float(r["trader_tavan_usd"]))


@dataclass(frozen=True)
class GateState:
    mode: Mode = Mode.DISABLED
    halt_new_adds: bool = False


def transition(state: GateState, target: str) -> tuple[GateState, str]:
    """Mode geçişi. live isteği her koşulda kilitlenir."""
    if target == Mode.LIVE_LOCKED:
        return GateState(Mode.LIVE_LOCKED, True), "gercek_islem_kilitli"
    if target == Mode.DRY_RUN:
        return GateState(Mode.DRY_RUN, state.halt_new_adds), "dry_run_aktif"
    if target == Mode.HALTED:
        return GateState(Mode.HALTED, True), "durduruldu"
    if target == Mode.DISABLED:
        return GateState(Mode.DISABLED, True), "devre_disi"
    raise ValueError("Bilinmeyen koruma modu")


def evaluate_order(*, state: GateState, action: str, trader: dict[str, Any],
                   notional_usd: float, gross_notional_usd: float,
                   daily_loss_usd: float, signal_time_ms: int,
                   signal_deadline_ms: int, now_ms: int,
                   limits: Limits = Limits(), trader_gross_notional_usd: float = 0.0) -> dict[str, Any]:
    """Dry-run emir kapısı; sonuç daima emir gönderilmediğini bildirir.

    EXIT yalnız halen açık pozisyon için ve pozitif notional ile kabul edilir.
    Giriş/ekleme İlk11, zaman tazeliği, durdurma ve tüm parasal limitlerden geçer.
    """
    try:
        kind = Action(action)
    except ValueError as exc:
        raise ValueError("action open, add veya exit olmalı") from exc
    numeric = (notional_usd, gross_notional_usd, daily_loss_usd, trader_gross_notional_usd)
    if any(not math.isfinite(float(x)) for x in numeric):
        raise ValueError("Notional ve zarar değerleri sonlu olmalı")
    if notional_usd <= 0 or gross_notional_usd < 0 or daily_loss_usd < 0 or trader_gross_notional_usd < 0:
        raise ValueError("Notional/zarar değerleri geçersiz")

    reasons: list[str] = []
    permitted_mode = state.mode in ({Mode.DRY_RUN, Mode.HALTED} if kind == Action.EXIT else {Mode.DRY_RUN})
    if not permitted_mode:
        reasons.append("dry_run_aktif_degil")
    if kind == Action.EXIT:
        if not trader.get("pozisyon_acik", False):
            reasons.append("acik_pozisyon_yok")
    else:
        if state.mode == Mode.HALTED or state.halt_new_adds:
            reasons.append("yeni_ekleme_durduruldu")
        if trader.get("takim") != "ilk11":
            reasons.append("yalniz_ilk11")
        if signal_time_ms > now_ms or now_ms > signal_deadline_ms or signal_time_ms > signal_deadline_ms:
            reasons.append("gec_sinyal")
        if daily_loss_usd >= limits.daily_loss_usd:
            reasons.append("gunluk_zarar_limiti")
        if notional_usd > limits.per_order_usd:
            reasons.append("emir_limiti")
        if trader_gross_notional_usd + notional_usd > limits.trader_cap_usd:
            reasons.append("trader_tavani")
        if gross_notional_usd + notional_usd > limits.total_gross_notional_usd:
            reasons.append("toplam_brut_notional_limiti")

    accepted = not reasons
    return {
        "mod": state.mode.value,
        "aksiyon": kind.value,
        "kabul": accepted,
        "nedenler": reasons,
        "notional_usd": float(notional_usd),
        "referans_sermaye_usd": limits.starting_reference_usd,
        "emir_gonderildi": False,
    }
