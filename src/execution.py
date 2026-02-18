from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from src.binance_client import BinanceClient
from src.risk import TradeDecision
from src.settings import RuntimeSettings
from src.strategy import BUY, HOLD, SELL


@dataclass(frozen=True)
class OrderResult:
    action_taken: str
    approved: bool
    reject_reason: str = ""
    order_id: str = ""
    status: str = ""
    executed_qty: float = 0.0
    cummulative_quote_qty: float = 0.0
    avg_fill_px: float = 0.0
    error: str = ""
    placed: bool = False
    filled: bool = False


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_qty(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def _avg_fill_from_order(order: Dict[str, Any]) -> float:
    fills = order.get("fills") or []
    if fills:
        total_qty = 0.0
        total_quote = 0.0
        for fill in fills:
            qty = _to_float(fill.get("qty"))
            px = _to_float(fill.get("price"))
            total_qty += qty
            total_quote += qty * px
        if total_qty > 0:
            return total_quote / total_qty

    executed = _to_float(order.get("executedQty"))
    cquote = _to_float(order.get("cummulativeQuoteQty"))
    if executed > 0:
        return cquote / executed
    return 0.0


def get_account_balances(
    client: BinanceClient,
    base_asset: str,
    quote_asset: str,
) -> Tuple[float, float]:
    account = client.get("/v3/account", signed=True)
    base_balance = 0.0
    quote_balance = 0.0
    for item in account.get("balances", []):
        asset = item.get("asset")
        total = _to_float(item.get("free")) + _to_float(item.get("locked"))
        if asset == base_asset:
            base_balance = total
        if asset == quote_asset:
            quote_balance = total
    return base_balance, quote_balance


def execute_trade_decision(
    client: BinanceClient,
    symbol: str,
    decision: TradeDecision,
    settings: RuntimeSettings,
) -> OrderResult:
    if decision.side == HOLD:
        return OrderResult(action_taken=HOLD, approved=False, reject_reason="hold")

    if not decision.approved:
        return OrderResult(
            action_taken=f"SKIP_{decision.side}",
            approved=False,
            reject_reason=decision.reject_reason,
        )

    if settings.dry_run:
        return OrderResult(
            action_taken=f"DRY_RUN_{decision.side}",
            approved=True,
            reject_reason="",
            order_id="SIMULATED",
            status="DRY_RUN",
        )

    params: Dict[str, str] = {
        "symbol": symbol,
        "side": decision.side,
        "type": "MARKET",
    }
    if decision.side == BUY:
        params["quoteOrderQty"] = _format_qty(decision.quote_order_qty)
    elif decision.side == SELL:
        params["quantity"] = _format_qty(decision.quantity)
    else:
        return OrderResult(
            action_taken="UNKNOWN_SIGNAL",
            approved=False,
            reject_reason="unknown_side",
        )

    order = client.post("/v3/order", signed=True, params=params)
    status = str(order.get("status", ""))
    executed_qty = _to_float(order.get("executedQty"))
    cquote = _to_float(order.get("cummulativeQuoteQty"))
    avg_fill = _avg_fill_from_order(order)
    return OrderResult(
        action_taken=decision.side,
        approved=True,
        order_id=str(order.get("orderId", "")),
        status=status,
        executed_qty=executed_qty,
        cummulative_quote_qty=cquote,
        avg_fill_px=avg_fill,
        placed=True,
        filled=(status == "FILLED"),
    )


def cancel_all_open_orders(
    client: BinanceClient,
    symbol: str,
) -> int:
    open_orders = client.get("/v3/openOrders", signed=True, params={"symbol": symbol})
    canceled = 0
    for order in open_orders:
        order_id = order.get("orderId")
        if order_id is None:
            continue
        try:
            client.delete(
                "/v3/order",
                signed=True,
                params={"symbol": symbol, "orderId": order_id},
            )
            canceled += 1
        except Exception:
            # Best effort: continue canceling remaining orders.
            continue
    return canceled
