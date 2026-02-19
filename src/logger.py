from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


CSV_FIELDS = [
    "timestamp",
    "best_bid",
    "best_ask",
    "bid",
    "ask",
    "mid",
    "spread",
    "bid_qty",
    "ask_qty",
    "imbalance",
    "threshold_used",
    "calib_state",
    "theta_hat",
    "calib_score",
    "calib_n",
    "signal_t",
    "pending_signal_prev",
    "action_taken",
    "approved",
    "reject_reason",
    "orderId",
    "status",
    "executedQty",
    "cummulativeQuoteQty",
    "avgFillPx",
    "position_btc",
    "position_usdt",
    "pnl_proxy",
    "paper_btc",
    "paper_usdt",
    "paper_equity_usdt",
    "paper_pnl_usdt",
    "paper_trade_notional_usdt",
    "paper_fee_usdt",
    "error",
]


class TradeCsvLogger:
    def __init__(self, path: str = "outputs/trades.csv") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def append(self, row: Dict[str, Any]) -> None:
        data = {field: row.get(field, "") for field in CSV_FIELDS}
        with self.path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writerow(data)

    def _ensure_header(self) -> None:
        if (not self.path.exists()) or self.path.stat().st_size == 0:
            self._write_header()
            return

        with self.path.open("r", newline="", encoding="utf-8") as f:
            first_line = f.readline().strip()
        current_header = ",".join(CSV_FIELDS)
        if first_line == current_header:
            return

        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup = self.path.with_name(f"{self.path.stem}_backup_{stamp}{self.path.suffix}")
        self.path.rename(backup)
        self._write_header()

    def _write_header(self) -> None:
        with self.path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
