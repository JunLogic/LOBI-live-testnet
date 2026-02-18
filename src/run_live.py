from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Optional

from src.binance_client import BinanceClient
from src.config import API_KEY, API_SECRET, BASE_URL
from src.execution import cancel_all_open_orders, execute_trade_decision, get_account_balances
from src.logger import TradeCsvLogger
from src.market_data import get_exchange_filters, get_market_snapshot
from src.paper import apply_dry_run_trade, create_paper_ledger
from src.risk import evaluate_pending_signal, risk_config_from_settings
from src.settings import RuntimeSettings, load_runtime_settings
from src.strategy import BUY, HOLD, SELL, signal_from_imbalance


def _extract_http_status(message: str) -> Optional[int]:
    match = re.search(r"failed\s+(\d{3})", message)
    if match:
        return int(match.group(1))
    return None


def _base_row(ts: str, pending_signal_prev: str) -> dict:
    return {
        "timestamp": ts,
        "bid": "",
        "ask": "",
        "mid": "",
        "bid_qty": "",
        "ask_qty": "",
        "imbalance": "",
        "signal_t": "",
        "pending_signal_prev": pending_signal_prev,
        "action_taken": "",
        "approved": "",
        "reject_reason": "",
        "orderId": "",
        "status": "",
        "executedQty": "",
        "cummulativeQuoteQty": "",
        "avgFillPx": "",
        "position_btc": "",
        "position_usdt": "",
        "pnl_proxy": "",
        "paper_btc": "",
        "paper_usdt": "",
        "paper_equity_usdt": "",
        "paper_pnl_usdt": "",
        "paper_trade_notional_usdt": "",
        "paper_fee_usdt": "",
        "error": "",
    }


def _print_settings(settings: RuntimeSettings) -> None:
    print(
        "SETTINGS:"
        f" symbol={settings.symbol}"
        f" dry_run={settings.dry_run}"
        f" threshold={settings.threshold}"
        f" poll_interval={settings.poll_interval_seconds}"
        f" cooldown={settings.cooldown_seconds}"
        f" max_notional={settings.max_notional_per_trade_usdt}"
        f" max_abs_position={settings.max_abs_position_btc}"
        f" use_depth={settings.use_depth}"
        f" max_errors={settings.max_consecutive_errors}"
        f" resync_every={settings.resync_every_n_polls}"
        f" max_polls={settings.max_polls}"
    )


def _print_heartbeat(
    settings: RuntimeSettings,
    poll_number: int,
    mid: float,
    imbalance: float,
    signal_t: str,
    pending_prev: str,
    decision_side: str,
    approved: bool,
    reason: str,
    position_btc: float,
    position_usdt: float,
) -> None:
    if (poll_number % settings.print_every_n_polls) != 0:
        return
    reason_text = reason or "-"
    print(
        f"[POLL {poll_number}]"
        f" mid={mid:.2f}"
        f" imb={imbalance:.6f}"
        f" signal_t={signal_t}"
        f" pending={pending_prev}"
        f" decision={decision_side}"
        f" approved={approved}"
        f" reason={reason_text}"
        f" pos_btc={position_btc:.8f}"
        f" pos_usdt={position_usdt:.2f}"
    )


def _print_trade_event(
    simulated: bool,
    side: str,
    qty_btc: float,
    quote_usdt: float,
    avg_fill_px: float,
    status: str,
    order_id: str,
) -> None:
    mode = "DRY_RUN(simulated)" if simulated else "LIVE"
    note = " (simulated; no balances should change)" if simulated else ""
    print(
        f"TRADE: {mode} {side}"
        f" qty={qty_btc:.8f}"
        f" quote={quote_usdt:.8f}"
        f" avg_fill_px={avg_fill_px:.8f}"
        f" status={status or '-'}"
        f" orderId={order_id or '-'}"
        f"{note}"
    )


def main() -> None:
    settings = load_runtime_settings()
    risk_cfg = risk_config_from_settings(settings)

    client = BinanceClient(base_url=BASE_URL, api_key=API_KEY, api_secret=API_SECRET)
    trade_logger = TradeCsvLogger(path="outputs/trades.csv")

    # Connectivity checks using the expected /v3 paths.
    client.get("/v3/ping")
    client.get("/v3/time")
    filters = get_exchange_filters(client, settings.symbol)

    initial_snapshot = get_market_snapshot(
        client=client,
        symbol=settings.symbol,
        settings=settings,
    )
    position_btc, position_usdt = get_account_balances(
        client=client,
        base_asset=filters.base_asset,
        quote_asset=filters.quote_asset,
    )
    initial_equity_usdt = position_btc * initial_snapshot.mid + position_usdt
    paper_ledger = create_paper_ledger(settings=settings, initial_mid=initial_snapshot.mid)
    paper_equity_end, paper_pnl_end = paper_ledger.mark_to_market(initial_snapshot.mid)

    _print_settings(settings)

    polls = 0
    orders_placed = 0
    orders_filled = 0
    error_count = 0
    consecutive_errors = 0
    pending_signal = HOLD
    last_trade_ts: Optional[float] = None
    backoff_seconds = settings.backoff_base_seconds
    pnl_proxy_end = 0.0
    min_pnl_proxy = float("inf")
    max_pnl_proxy = float("-inf")

    try:
        while True:
            if settings.max_polls > 0 and polls >= settings.max_polls:
                break

            now = datetime.now(timezone.utc)
            row = _base_row(ts=now.isoformat(), pending_signal_prev=pending_signal)
            pending_prev = pending_signal
            polls += 1
            poll_had_error = False
            status_for_backoff: Optional[int] = None
            paper_trade_notional_usdt = 0.0
            paper_fee_usdt = 0.0

            try:
                snapshot = get_market_snapshot(
                    client=client,
                    symbol=settings.symbol,
                    settings=settings,
                )
                if polls == 1 or (polls % settings.resync_every_n_polls) == 0:
                    position_btc, position_usdt = get_account_balances(
                        client=client,
                        base_asset=filters.base_asset,
                        quote_asset=filters.quote_asset,
                    )
            except Exception as exc:
                poll_had_error = True
                error_count += 1
                consecutive_errors += 1
                msg = str(exc)
                row["error"] = msg
                row["action_taken"] = "POLL_ERROR"
                row["approved"] = False
                row["reject_reason"] = "poll_exception"
                status_for_backoff = _extract_http_status(msg)
                trade_logger.append(row)
                if (polls % settings.print_every_n_polls) == 0:
                    print(f"[POLL {polls}] ERROR reason=poll_exception msg={msg}")
                if consecutive_errors > settings.max_consecutive_errors:
                    print("Stopping: max consecutive errors exceeded.")
                    break
                if status_for_backoff in {418, 429}:
                    sleep_for = min(backoff_seconds, settings.backoff_cap_seconds)
                    print(f"Rate limit hit ({status_for_backoff}), sleeping {sleep_for:.1f}s")
                    time.sleep(sleep_for)
                    backoff_seconds = min(backoff_seconds * 2, settings.backoff_cap_seconds)
                else:
                    time.sleep(settings.poll_interval_seconds)
                continue

            signal_t = signal_from_imbalance(snapshot.imbalance, settings.threshold)
            row.update(
                {
                    "timestamp": snapshot.timestamp,
                    "bid": snapshot.bid,
                    "ask": snapshot.ask,
                    "mid": snapshot.mid,
                    "bid_qty": snapshot.bid_qty,
                    "ask_qty": snapshot.ask_qty,
                    "imbalance": snapshot.imbalance,
                    "signal_t": signal_t,
                    "pending_signal_prev": pending_prev,
                }
            )

            decision = evaluate_pending_signal(
                pending_signal=pending_prev,
                mid=snapshot.mid,
                position_btc=position_btc,
                position_usdt=position_usdt,
                filters=filters,
                now_ts=now.timestamp(),
                last_trade_ts=last_trade_ts,
                cfg=risk_cfg,
            )

            try:
                result = execute_trade_decision(
                    client=client,
                    symbol=settings.symbol,
                    decision=decision,
                    settings=settings,
                )
            except Exception as exc:
                poll_had_error = True
                error_count += 1
                consecutive_errors += 1
                msg = str(exc)
                status_for_backoff = _extract_http_status(msg)
                result_action = f"ERROR_{decision.side}"
                row.update(
                    {
                        "action_taken": result_action,
                        "approved": False,
                        "reject_reason": "execution_exception",
                        "error": msg,
                    }
                )
            else:
                row.update(
                    {
                        "action_taken": result.action_taken,
                        "approved": result.approved,
                        "reject_reason": result.reject_reason,
                        "orderId": result.order_id,
                        "status": result.status,
                        "executedQty": result.executed_qty,
                        "cummulativeQuoteQty": result.cummulative_quote_qty,
                        "avgFillPx": result.avg_fill_px,
                        "error": result.error,
                    }
                )
                if result.placed:
                    orders_placed += 1
                if result.filled:
                    orders_filled += 1
                if decision.approved and (
                    result.placed or result.action_taken.startswith("DRY_RUN_")
                ):
                    paper_trade = apply_dry_run_trade(
                        ledger=paper_ledger,
                        action_taken=result.action_taken,
                        approved=result.approved,
                        side=decision.side,
                        quote_order_qty=decision.quote_order_qty,
                        quantity=decision.quantity,
                        mid=snapshot.mid,
                    )
                    paper_trade_notional_usdt = paper_trade.trade_notional_usdt
                    paper_fee_usdt = paper_trade.fee_usdt

                    if result.action_taken.startswith("DRY_RUN_"):
                        trade_qty_btc = paper_trade.executed_qty_btc
                        trade_quote_usdt = paper_trade.trade_notional_usdt
                        trade_avg_fill = paper_trade.exec_px if paper_trade.exec_px > 0 else snapshot.mid
                        trade_status = "DRY_RUN_FILLED" if paper_trade.traded else "DRY_RUN_NO_FILL"
                    else:
                        trade_qty_btc = result.executed_qty
                        trade_quote_usdt = (
                            result.cummulative_quote_qty
                            if result.cummulative_quote_qty > 0
                            else decision.quote_order_qty
                        )
                        trade_avg_fill = result.avg_fill_px
                        trade_status = result.status

                    _print_trade_event(
                        simulated=result.action_taken.startswith("DRY_RUN_"),
                        side=decision.side,
                        qty_btc=trade_qty_btc,
                        quote_usdt=trade_quote_usdt,
                        avg_fill_px=trade_avg_fill,
                        status=trade_status,
                        order_id=result.order_id,
                    )
                if decision.approved and (
                    result.placed or result.action_taken.startswith("DRY_RUN_")
                ):
                    last_trade_ts = now.timestamp()
                if result.error:
                    poll_had_error = True
                    error_count += 1
                    consecutive_errors += 1

            pending_signal = signal_t

            if (not settings.dry_run) and row.get("orderId"):
                try:
                    position_btc, position_usdt = get_account_balances(
                        client=client,
                        base_asset=filters.base_asset,
                        quote_asset=filters.quote_asset,
                    )
                except Exception as exc:
                    poll_had_error = True
                    error_count += 1
                    consecutive_errors += 1
                    msg = str(exc)
                    if row["error"]:
                        row["error"] = f"{row['error']} | {msg}"
                    else:
                        row["error"] = msg
                    status_for_backoff = status_for_backoff or _extract_http_status(msg)

            pnl_proxy = (position_btc * snapshot.mid + position_usdt) - initial_equity_usdt
            row["position_btc"] = position_btc
            row["position_usdt"] = position_usdt
            row["pnl_proxy"] = pnl_proxy
            paper_equity_usdt, paper_pnl_usdt = paper_ledger.mark_to_market(snapshot.mid)
            row["paper_btc"] = paper_ledger.paper_btc
            row["paper_usdt"] = paper_ledger.paper_usdt
            row["paper_equity_usdt"] = paper_equity_usdt
            row["paper_pnl_usdt"] = paper_pnl_usdt
            row["paper_trade_notional_usdt"] = paper_trade_notional_usdt
            row["paper_fee_usdt"] = paper_fee_usdt
            pnl_proxy_end = pnl_proxy
            paper_equity_end = paper_equity_usdt
            paper_pnl_end = paper_pnl_usdt
            min_pnl_proxy = min(min_pnl_proxy, pnl_proxy)
            max_pnl_proxy = max(max_pnl_proxy, pnl_proxy)
            trade_logger.append(row)
            _print_heartbeat(
                settings=settings,
                poll_number=polls,
                mid=snapshot.mid,
                imbalance=snapshot.imbalance,
                signal_t=signal_t,
                pending_prev=pending_prev,
                decision_side=decision.side,
                approved=decision.approved,
                reason=decision.reject_reason,
                position_btc=position_btc,
                position_usdt=position_usdt,
            )

            if not poll_had_error:
                consecutive_errors = 0
                backoff_seconds = settings.backoff_base_seconds

            if consecutive_errors > settings.max_consecutive_errors:
                print("Stopping: max consecutive errors exceeded.")
                break

            if status_for_backoff in {418, 429}:
                sleep_for = min(backoff_seconds, settings.backoff_cap_seconds)
                print(f"Rate limit hit ({status_for_backoff}), sleeping {sleep_for:.1f}s")
                time.sleep(sleep_for)
                backoff_seconds = min(backoff_seconds * 2, settings.backoff_cap_seconds)
            else:
                time.sleep(settings.poll_interval_seconds)

    except KeyboardInterrupt:
        print("KeyboardInterrupt received; shutting down.")
    finally:
        canceled = 0
        if settings.dry_run:
            print("DRY_RUN=True, skipping cancel-all-open-orders on shutdown.")
        else:
            try:
                canceled = cancel_all_open_orders(client=client, symbol=settings.symbol)
            except Exception as exc:
                print(f"Cancel open orders failed (best effort): {exc}")

        if min_pnl_proxy == float("inf"):
            min_pnl_proxy = 0.0
            max_pnl_proxy = 0.0

        print("Exit summary:")
        print(f"polls={polls}")
        print(f"orders_placed={orders_placed}")
        print(f"orders_filled={orders_filled}")
        print(f"error_count={error_count}")
        print(f"pnl_proxy_end={pnl_proxy_end}")
        print(f"min_pnl_proxy={min_pnl_proxy}")
        print(f"max_pnl_proxy={max_pnl_proxy}")
        print(f"open_orders_canceled={canceled}")
        paper_trade_count = paper_ledger.trade_count
        paper_win_rate = (
            (paper_ledger.win_count / paper_trade_count) * 100.0
            if paper_trade_count > 0
            else 0.0
        )
        print("Paper summary:")
        print(f"paper_equity_end={paper_equity_end}")
        print(f"paper_pnl_end={paper_pnl_end}")
        print(f"paper_trades={paper_trade_count}")
        print(f"paper_win_rate_pct={paper_win_rate}")
        print(f"paper_max_drawdown_usdt={paper_ledger.max_drawdown_usdt}")


if __name__ == "__main__":
    main()
