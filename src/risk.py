from __future__ import annotations

import math
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
    min_notional_per_trade_usdt: float
    max_abs_position_btc: float
    max_consecutive_errors: int
    enable_position_sizing: bool
    position_sizing_mode: str


@dataclass(frozen=True)
class TradeDecision:
    side: str
    approved: bool
    reject_reason: str = ""
    quote_order_qty: float = 0.0
    quantity: float = 0.0
    notional_target_usdt: float = 0.0


def risk_config_from_settings(settings: RuntimeSettings) -> RiskConfig:
    return RiskConfig(
        cooldown_seconds=settings.cooldown_seconds,
        max_notional_per_trade_usdt=settings.max_notional_per_trade_usdt,
        min_notional_per_trade_usdt=settings.min_notional_per_trade_usdt,
        max_abs_position_btc=settings.max_abs_position_btc,
        max_consecutive_errors=settings.max_consecutive_errors,
        enable_position_sizing=settings.enable_position_sizing,
        position_sizing_mode=settings.position_sizing_mode,
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


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def compute_notional_target_usdt(
    imbalance: float,
    threshold_used: float,
    cfg: RiskConfig,
) -> float:
    if not cfg.enable_position_sizing:
        return cfg.max_notional_per_trade_usdt

    if not math.isfinite(imbalance):
        return float("nan")

    abs_imb = _clamp(abs(imbalance), 0.0, 1.0)
    if cfg.position_sizing_mode == "linear_abs":
        scale = abs_imb
    else:
        denom = 1.0 - threshold_used
        if denom <= 0.0:
            scale = 0.0
        else:
            scale = _clamp((abs_imb - threshold_used) / denom, 0.0, 1.0)

    return _clamp(cfg.max_notional_per_trade_usdt * scale, 0.0, cfg.max_notional_per_trade_usdt)


def evaluate_pending_signal(
    pending_signal: str,
    mid: float,
    imbalance: float,
    threshold_used: float,
    position_btc: float,
    position_usdt: float,
    filters: SymbolFilters,
    now_ts: float,
    last_trade_ts: Optional[float],
    cfg: RiskConfig,
) -> TradeDecision:
    notional_target = compute_notional_target_usdt(
        imbalance=imbalance,
        threshold_used=threshold_used,
        cfg=cfg,
    )
    if pending_signal not in (BUY, SELL):
        return TradeDecision(
            side=pending_signal,
            approved=False,
            reject_reason="hold",
            notional_target_usdt=notional_target,
        )

    if mid <= 0:
        return TradeDecision(
            side=pending_signal,
            approved=False,
            reject_reason="bad_mid",
            notional_target_usdt=notional_target,
        )

    if cfg.enable_position_sizing and (not math.isfinite(notional_target)):
        return TradeDecision(
            side=pending_signal,
            approved=False,
            reject_reason="invalid_imbalance",
            notional_target_usdt=0.0,
        )

    if _cooldown_active(now_ts, last_trade_ts, cfg.cooldown_seconds):
        return TradeDecision(
            side=pending_signal,
            approved=False,
            reject_reason="cooldown_active",
            notional_target_usdt=notional_target,
        )

    quote_qty = (
        notional_target
        if cfg.enable_position_sizing
        else cfg.max_notional_per_trade_usdt
    )
    if cfg.enable_position_sizing and (
        quote_qty < cfg.min_notional_per_trade_usdt
    ):
        return TradeDecision(
            side=pending_signal,
            approved=False,
            reject_reason="notional_below_min",
            notional_target_usdt=quote_qty,
        )

    if pending_signal == BUY:
        if quote_qty < filters.min_notional:
            return TradeDecision(
                side=BUY,
                approved=False,
                reject_reason="below_min_notional_buy",
                notional_target_usdt=quote_qty,
            )
        if position_usdt < quote_qty:
            return TradeDecision(
                side=BUY,
                approved=False,
                reject_reason="insufficient_usdt",
                notional_target_usdt=quote_qty,
            )

        est_qty = quote_qty / mid
        if est_qty < filters.min_qty:
            return TradeDecision(
                side=BUY,
                approved=False,
                reject_reason="below_min_qty_buy",
                notional_target_usdt=quote_qty,
            )
        if filters.max_qty > 0 and est_qty > filters.max_qty:
            return TradeDecision(
                side=BUY,
                approved=False,
                reject_reason="above_max_qty_buy",
                notional_target_usdt=quote_qty,
            )
        if (position_btc + est_qty) > cfg.max_abs_position_btc:
            return TradeDecision(
                side=BUY,
                approved=False,
                reject_reason="max_abs_position_exceeded",
                notional_target_usdt=quote_qty,
            )
        if est_qty <= 0:
            return TradeDecision(
                side=BUY,
                approved=False,
                reject_reason="qty_is_zero",
                notional_target_usdt=quote_qty,
            )

        return TradeDecision(
            side=BUY,
            approved=True,
            quote_order_qty=quote_qty,
            quantity=est_qty,
            notional_target_usdt=quote_qty,
        )

    available_btc = max(position_btc, 0.0)
    if available_btc <= 0:
        return TradeDecision(
            side=SELL,
            approved=False,
            reject_reason="insufficient_btc",
            notional_target_usdt=quote_qty,
        )

    max_sell_qty = quote_qty / mid
    raw_qty = min(available_btc, max_sell_qty)
    qty = round_down_step(raw_qty, filters.step_size)
    if qty <= 0:
        return TradeDecision(
            side=SELL,
            approved=False,
            reject_reason="rounded_to_zero",
            notional_target_usdt=quote_qty,
        )
    if qty < filters.min_qty:
        return TradeDecision(
            side=SELL,
            approved=False,
            reject_reason="below_min_qty_sell",
            notional_target_usdt=quote_qty,
        )
    if filters.max_qty > 0 and qty > filters.max_qty:
        qty = round_down_step(filters.max_qty, filters.step_size)
        if qty < filters.min_qty:
            return TradeDecision(
                side=SELL,
                approved=False,
                reject_reason="above_max_qty_sell",
                notional_target_usdt=quote_qty,
            )

    if qty * mid < filters.min_notional:
        return TradeDecision(
            side=SELL,
            approved=False,
            reject_reason="below_min_notional_sell",
            notional_target_usdt=quote_qty,
        )

    return TradeDecision(
        side=SELL,
        approved=True,
        quantity=qty,
        notional_target_usdt=quote_qty,
    )
