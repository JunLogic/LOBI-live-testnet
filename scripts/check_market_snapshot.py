from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from statistics import mean, pstdev
from typing import Optional


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _summary(values: list[float]) -> tuple[float, float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0, 0.0
    return mean(values), pstdev(values), min(values), max(values)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check market snapshot fields in trades CSV.")
    parser.add_argument("--csv", default="outputs/trades.csv", help="Path to trades.csv")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    n_rows = len(rows)
    if n_rows == 0:
        print("rows=0")
        return

    depth_ids = [_to_int((row.get("depth_update_id") or "").strip()) for row in rows]
    depth_valid = [d for d in depth_ids if d is not None]
    missing_depth = sum(1 for d in depth_ids if d is None)
    pct_missing_depth = (missing_depth / n_rows) * 100.0

    imbalances = []
    bid_qty = []
    ask_qty = []
    best_quotes = set()

    for row in rows:
        imb = _to_float(row.get("imbalance", ""))
        if (imb is not None) and math.isfinite(imb):
            imbalances.append(imb)

        bq = _to_float(row.get("bid_qty", ""))
        if (bq is not None) and math.isfinite(bq):
            bid_qty.append(bq)

        aq = _to_float(row.get("ask_qty", ""))
        if (aq is not None) and math.isfinite(aq):
            ask_qty.append(aq)

        best_bid = _to_float(row.get("best_bid", ""))
        best_ask = _to_float(row.get("best_ask", ""))
        if (best_bid is not None) and (best_ask is not None):
            best_quotes.add((best_bid, best_ask))

    imb_mean, imb_std, imb_min, imb_max = _summary(imbalances)
    bq_mean, bq_std, bq_min, bq_max = _summary(bid_qty)
    aq_mean, aq_std, aq_min, aq_max = _summary(ask_qty)
    pct_abs_imb_gt_09 = (
        (sum(1 for x in imbalances if abs(x) > 0.9) / len(imbalances)) * 100.0
        if imbalances
        else 0.0
    )

    print(f"rows={n_rows}")
    print(f"depth_update_id_valid_rows={len(depth_valid)}")
    print(f"depth_update_id_missing_pct={pct_missing_depth:.2f}")
    print(
        "imbalance_summary:"
        f" count={len(imbalances)}"
        f" mean={imb_mean:.8f}"
        f" std={imb_std:.8f}"
        f" min={imb_min:.8f}"
        f" max={imb_max:.8f}"
        f" pct_abs_gt_0.9={pct_abs_imb_gt_09:.2f}"
    )
    print(
        "bid_qty_summary:"
        f" count={len(bid_qty)}"
        f" mean={bq_mean:.8f}"
        f" std={bq_std:.8f}"
        f" min={bq_min:.8f}"
        f" max={bq_max:.8f}"
    )
    print(
        "ask_qty_summary:"
        f" count={len(ask_qty)}"
        f" mean={aq_mean:.8f}"
        f" std={aq_std:.8f}"
        f" min={aq_min:.8f}"
        f" max={aq_max:.8f}"
    )
    print(f"unique_best_bid_ask={len(best_quotes)}")


if __name__ == "__main__":
    main()
