from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from src.market_data import SymbolFilters
from src.settings import RuntimeSettings
from src.strategy import BUY, SELL


@dataclass(frozen=True)
class RiskConfig:
    cooldown_seconds: float
    max_notional_per_trade_usdt: float
    max_abs_position_btc: float
    max_consecutive_errors: int


@dataclass(frozen=True)
class TradeDecision:
    side: str
    approved: bool
    reject_reason: str = ""
    quote_order_qty: float = 0.0
    quantity: float = 0.0


def risk_config_from_settings(settings: RuntimeSettings) -> RiskConfig:
    return RiskConfig(
        cooldown_seconds=settings.cooldown_seconds,
        max_notional_per_trade_usdt=settings.max_notional_per_trade_usdt,
        max_abs_position_btc=settings.max_abs_position_btc,
        max_consecutive_errors=settings.max_consecutive_errors,
    )


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(value))


def round_down_step(quantity: float, step_size: float) -> float:
    if step_size <= 0:
        return max(quantity, 0.0)
    q = _to_decimal(max(quantity, 0.0))
    step = _to_decimal(step_size)
    units = (q / step).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return float(units * step)


def _cooldown_active(
    now_ts: float, last_trade_ts: Optional[float], cooldown_seconds: float
) -> bool:
    if last_trade_ts is None:
        return False
    return (now_ts - last_trade_ts) < cooldown_seconds


def evaluate_pending_signal(
    pending_signal: str,
    mid: float,
    position_btc: float,
    position_usdt: float,
    filters: SymbolFilters,
    now_ts: float,
    last_trade_ts: Optional[float],
    cfg: RiskConfig,
) -> TradeDecision:
    if pending_signal not in (BUY, SELL):
        return TradeDecision(side=pending_signal, approved=False, reject_reason="hold")

    if mid <= 0:
        return TradeDecision(side=pending_signal, approved=False, reject_reason="bad_mid")

    if _cooldown_active(now_ts, last_trade_ts, cfg.cooldown_seconds):
        return TradeDecision(
            side=pending_signal, approved=False, reject_reason="cooldown_active"
        )

    if pending_signal == BUY:
        quote_qty = cfg.max_notional_per_trade_usdt
        if quote_qty < filters.min_notional:
            return TradeDecision(
                side=BUY, approved=False, reject_reason="below_min_notional_buy"
            )
        if position_usdt < quote_qty:
            return TradeDecision(side=BUY, approved=False, reject_reason="insufficient_usdt")

        est_qty = quote_qty / mid
        if est_qty < filters.min_qty:
            return TradeDecision(side=BUY, approved=False, reject_reason="below_min_qty_buy")
        if filters.max_qty > 0 and est_qty > filters.max_qty:
            return TradeDecision(side=BUY, approved=False, reject_reason="above_max_qty_buy")
        if (position_btc + est_qty) > cfg.max_abs_position_btc:
            return TradeDecision(
                side=BUY, approved=False, reject_reason="max_abs_position_exceeded"
            )

        return TradeDecision(side=BUY, approved=True, quote_order_qty=quote_qty)

    available_btc = max(position_btc, 0.0)
    if available_btc <= 0:
        return TradeDecision(side=SELL, approved=False, reject_reason="insufficient_btc")

    max_sell_qty = cfg.max_notional_per_trade_usdt / mid
    raw_qty = min(available_btc, max_sell_qty)
    qty = round_down_step(raw_qty, filters.step_size)
    if qty <= 0:
        return TradeDecision(side=SELL, approved=False, reject_reason="rounded_to_zero")
    if qty < filters.min_qty:
        return TradeDecision(side=SELL, approved=False, reject_reason="below_min_qty_sell")
    if filters.max_qty > 0 and qty > filters.max_qty:
        qty = round_down_step(filters.max_qty, filters.step_size)
        if qty < filters.min_qty:
            return TradeDecision(side=SELL, approved=False, reject_reason="above_max_qty_sell")

    if qty * mid < filters.min_notional:
        return TradeDecision(side=SELL, approved=False, reject_reason="below_min_notional_sell")

    return TradeDecision(side=SELL, approved=True, quantity=qty)
