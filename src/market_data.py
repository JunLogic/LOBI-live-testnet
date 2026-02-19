from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.binance_client import BinanceClient
from src.settings import RuntimeSettings


@dataclass(frozen=True)
class SymbolFilters:
    symbol: str
    base_asset: str
    quote_asset: str
    min_qty: float
    max_qty: float
    step_size: float
    min_notional: float


@dataclass(frozen=True)
class MarketSnapshot:
    timestamp: str
    bid: float
    ask: float
    mid: float
    bid_qty: float
    ask_qty: float
    imbalance: float
    depth_update_id: Optional[int] = None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _imbalance_ratio(bid_qty: float, ask_qty: float) -> float:
    denom = bid_qty + ask_qty
    if denom <= 0:
        return 0.0
    return (bid_qty - ask_qty) / denom


def get_exchange_filters(client: BinanceClient, symbol: str) -> SymbolFilters:
    info = client.get("/v3/exchangeInfo", params={"symbol": symbol})
    symbols = info.get("symbols") or []
    if not symbols:
        raise RuntimeError(f"No exchangeInfo returned for symbol={symbol}")

    symbol_info = symbols[0]
    filter_map: Dict[str, Dict[str, Any]] = {
        f.get("filterType", ""): f for f in symbol_info.get("filters", [])
    }
    market_lot_filter = filter_map.get("MARKET_LOT_SIZE") or {}
    lot_filter = filter_map.get("LOT_SIZE") or {}
    notional_filter = filter_map.get("MIN_NOTIONAL") or filter_map.get("NOTIONAL") or {}

    min_notional = _to_float(
        notional_filter.get("minNotional", notional_filter.get("notional", 0))
    )
    min_qty = _to_float(market_lot_filter.get("minQty"))
    max_qty = _to_float(market_lot_filter.get("maxQty"))
    step_size = _to_float(market_lot_filter.get("stepSize"))

    # Some symbols expose MARKET_LOT_SIZE step/min as zero; fallback to LOT_SIZE.
    if min_qty <= 0:
        min_qty = _to_float(lot_filter.get("minQty"))
    if max_qty <= 0:
        max_qty = _to_float(lot_filter.get("maxQty"))
    if step_size <= 0:
        step_size = _to_float(lot_filter.get("stepSize"))

    return SymbolFilters(
        symbol=symbol_info.get("symbol", symbol),
        base_asset=symbol_info.get("baseAsset", "BTC"),
        quote_asset=symbol_info.get("quoteAsset", "USDT"),
        min_qty=min_qty,
        max_qty=max_qty,
        step_size=step_size,
        min_notional=min_notional,
    )


def get_book_ticker(client: BinanceClient, symbol: str) -> Dict[str, Any]:
    return client.get("/v3/ticker/bookTicker", params={"symbol": symbol})


def get_depth(client: BinanceClient, symbol: str, limit: int) -> Dict[str, Any]:
    return client.get("/v3/depth", params={"symbol": symbol, "limit": limit})


def compute_depth_imbalance(
    bids: List[List[str]], asks: List[List[str]], levels: int
) -> float:
    bid_sum, ask_sum = compute_depth_qty_sums(bids=bids, asks=asks, levels=levels)
    return _imbalance_ratio(bid_sum, ask_sum)


def compute_depth_qty_sums(
    bids: List[List[str]], asks: List[List[str]], levels: int
) -> Tuple[float, float]:
    top_bids: List[Tuple[float, float]] = [
        (_to_float(px), _to_float(qty)) for px, qty in bids[:levels]
    ]
    top_asks: List[Tuple[float, float]] = [
        (_to_float(px), _to_float(qty)) for px, qty in asks[:levels]
    ]
    bid_sum = sum(qty for _, qty in top_bids)
    ask_sum = sum(qty for _, qty in top_asks)
    return bid_sum, ask_sum


def get_market_snapshot(
    client: BinanceClient,
    symbol: str,
    settings: RuntimeSettings,
) -> MarketSnapshot:
    bt = get_book_ticker(client, symbol=symbol)
    bid = _to_float(bt.get("bidPrice"))
    ask = _to_float(bt.get("askPrice"))
    bid_qty = _to_float(bt.get("bidQty"))
    ask_qty = _to_float(bt.get("askQty"))
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0
    imbalance = _imbalance_ratio(bid_qty, ask_qty)
    depth_update_id: Optional[int] = None

    if settings.use_depth:
        depth = get_depth(client, symbol=symbol, limit=settings.depth_levels)
        depth_update_id = _to_int(depth.get("lastUpdateId"))
        depth_bids = depth.get("bids", [])
        depth_asks = depth.get("asks", [])
        bid_qty, ask_qty = compute_depth_qty_sums(
            bids=depth_bids,
            asks=depth_asks,
            levels=settings.depth_levels,
        )
        imbalance = _imbalance_ratio(bid_qty, ask_qty)
        if settings.debug_depth_sums:
            first_level_bid_qty = (
                _to_float(depth_bids[0][1]) if depth_bids and len(depth_bids[0]) > 1 else 0.0
            )
            first_level_ask_qty = (
                _to_float(depth_asks[0][1]) if depth_asks and len(depth_asks[0]) > 1 else 0.0
            )
            print(
                "DEPTH_DEBUG:"
                f" levels={settings.depth_levels}"
                f" sum_bid_qty={bid_qty:.8f}"
                f" sum_ask_qty={ask_qty:.8f}"
                f" imbalance={imbalance:.8f}"
                f" first_level_bid_qty={first_level_bid_qty:.8f}"
                f" first_level_ask_qty={first_level_ask_qty:.8f}"
            )

    return MarketSnapshot(
        timestamp=datetime.now(timezone.utc).isoformat(),
        bid=bid,
        ask=ask,
        mid=mid,
        bid_qty=bid_qty,
        ask_qty=ask_qty,
        imbalance=imbalance,
        depth_update_id=depth_update_id,
    )
