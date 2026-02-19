from __future__ import annotations

import math
from dataclasses import dataclass

from src.settings import RuntimeSettings
from src.strategy import BUY, SELL


@dataclass
class PaperTradeResult:
    traded: bool = False
    side: str = ""
    exec_px: float = 0.0
    executed_qty_btc: float = 0.0
    trade_notional_usdt: float = 0.0
    fee_usdt: float = 0.0
    trade_pnl_usdt: float = 0.0


@dataclass
class PaperLedger:
    paper_usdt: float
    paper_btc: float
    fee_rate: float
    slippage_bps: float
    initial_equity_usdt: float
    trade_count: int = 0
    win_count: int = 0
    equity_peak_usdt: float = 0.0
    max_drawdown_usdt: float = 0.0

    def mark_to_market(self, mid: float) -> tuple[float, float]:
        _ensure_finite("mid", mid)
        _ensure_finite("paper_usdt", self.paper_usdt)
        _ensure_finite("paper_btc", self.paper_btc)
        equity = self.paper_usdt + self.paper_btc * mid
        if equity > self.equity_peak_usdt:
            self.equity_peak_usdt = equity
        drawdown = self.equity_peak_usdt - equity
        if drawdown > self.max_drawdown_usdt:
            self.max_drawdown_usdt = drawdown
        pnl = equity - self.initial_equity_usdt
        _ensure_finite("paper_equity_usdt", equity)
        _ensure_finite("paper_pnl_usdt", pnl)
        return equity, pnl


def create_paper_ledger(settings: RuntimeSettings, initial_mid: float) -> PaperLedger:
    initial_equity = settings.paper_start_usdt + settings.paper_start_btc * initial_mid
    return PaperLedger(
        paper_usdt=settings.paper_start_usdt,
        paper_btc=settings.paper_start_btc,
        fee_rate=settings.paper_fee_rate,
        slippage_bps=settings.paper_slippage_bps,
        initial_equity_usdt=initial_equity,
        equity_peak_usdt=initial_equity,
    )


def _ensure_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"non_finite_{name}={value}")


def _ensure_finite_ledger(ledger: PaperLedger) -> None:
    _ensure_finite("paper_usdt", ledger.paper_usdt)
    _ensure_finite("paper_btc", ledger.paper_btc)


def _exec_px(best_bid: float, best_ask: float, side: str, slippage_bps: float) -> float:
    slip = max(slippage_bps, 0.0) / 10000.0
    if side == BUY:
        return best_ask * (1.0 + slip)
    if side == SELL:
        return best_bid * (1.0 - slip)
    return 0.0


def apply_dry_run_trade(
    ledger: PaperLedger,
    action_taken: str,
    approved: bool,
    side: str,
    quote_order_qty: float,
    quantity: float,
    best_bid: float,
    best_ask: float,
) -> PaperTradeResult:
    if not approved or (not action_taken.startswith("DRY_RUN_")):
        return PaperTradeResult()
    if side not in (BUY, SELL):
        return PaperTradeResult()
    if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
        return PaperTradeResult(side=side)

    mid = (best_bid + best_ask) / 2.0
    exec_px = _exec_px(
        best_bid=best_bid,
        best_ask=best_ask,
        side=side,
        slippage_bps=ledger.slippage_bps,
    )
    if exec_px <= 0:
        return PaperTradeResult(side=side, exec_px=exec_px)

    _ensure_finite_ledger(ledger)
    before_equity = ledger.paper_usdt + ledger.paper_btc * mid

    if side == BUY:
        spend_usdt = min(max(quote_order_qty, 0.0), ledger.paper_usdt)
        if spend_usdt <= 0:
            return PaperTradeResult(side=side, exec_px=exec_px)
        fee_usdt = spend_usdt * ledger.fee_rate
        net_usdt = max(0.0, spend_usdt - fee_usdt)
        bought_btc = net_usdt / exec_px

        ledger.paper_usdt -= spend_usdt
        ledger.paper_btc += bought_btc
        _ensure_finite_ledger(ledger)

        after_equity = ledger.paper_usdt + ledger.paper_btc * mid
        trade_pnl = after_equity - before_equity
        ledger.trade_count += 1
        if trade_pnl > 0:
            ledger.win_count += 1

        return PaperTradeResult(
            traded=True,
            side=side,
            exec_px=exec_px,
            executed_qty_btc=bought_btc,
            trade_notional_usdt=spend_usdt,
            fee_usdt=fee_usdt,
            trade_pnl_usdt=trade_pnl,
        )

    sell_qty = min(max(quantity, 0.0), ledger.paper_btc)
    if sell_qty <= 0:
        return PaperTradeResult(side=side, exec_px=exec_px)

    gross_usdt = sell_qty * exec_px
    fee_usdt = gross_usdt * ledger.fee_rate
    net_usdt = gross_usdt - fee_usdt

    ledger.paper_btc -= sell_qty
    ledger.paper_usdt += net_usdt
    _ensure_finite_ledger(ledger)

    after_equity = ledger.paper_usdt + ledger.paper_btc * mid
    trade_pnl = after_equity - before_equity
    ledger.trade_count += 1
    if trade_pnl > 0:
        ledger.win_count += 1

    return PaperTradeResult(
        traded=True,
        side=side,
        exec_px=exec_px,
        executed_qty_btc=sell_qty,
        trade_notional_usdt=gross_usdt,
        fee_usdt=fee_usdt,
        trade_pnl_usdt=trade_pnl,
    )
