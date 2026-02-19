from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _pick_column(df: pd.DataFrame, primary: str, fallback: str) -> pd.Series:
    if primary in df.columns:
        return _to_numeric(df[primary])
    if fallback in df.columns:
        return _to_numeric(df[fallback])
    raise ValueError(f"Missing required column: {primary} (or fallback: {fallback})")


def _make_decile_table(data: pd.DataFrame) -> pd.DataFrame:
    bucketed = data.copy()
    bucketed["decile"] = (
        pd.qcut(bucketed["imbalance"], q=10, labels=False, duplicates="drop").astype(int) + 1
    )
    table = (
        bucketed.groupby("decile", observed=True)
        .agg(
            count=("r1", "size"),
            mean_r1=("r1", "mean"),
            hit_rate=("hit", "mean"),
        )
        .sort_index()
    )
    return table


def _print_table(title: str, table: pd.DataFrame) -> None:
    print(title)
    if table.empty:
        print("  (empty)")
        return
    display = table.copy()
    display["mean_r1"] = display["mean_r1"].map(lambda x: f"{x:.8f}")
    display["hit_rate"] = display["hit_rate"].map(lambda x: f"{x:.4f}")
    print(display.to_string())


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose LOBI edge using per-poll market CSV.")
    parser.add_argument(
        "csv",
        nargs="?",
        default="outputs/trades.csv",
        help="Path to per-poll CSV (e.g., outputs/trades.csv or outputs/market.csv).",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    if "imbalance" not in df.columns:
        raise ValueError("Missing required column: imbalance")

    best_bid = _pick_column(df, "best_bid", "bid")
    best_ask = _pick_column(df, "best_ask", "ask")
    imbalance = _to_numeric(df["imbalance"])
    spread = (
        _to_numeric(df["spread"]) if "spread" in df.columns else (best_ask - best_bid)
    )

    mid = (best_bid + best_ask) / 2.0
    r1 = mid.shift(-1) / mid - 1.0
    hit = (
        ((imbalance > 0) & (r1 > 0))
        | ((imbalance < 0) & (r1 < 0))
        | ((imbalance == 0) & (r1 == 0))
    )

    data = pd.DataFrame(
        {
            "imbalance": imbalance,
            "mid": mid,
            "spread": spread,
            "r1": r1,
            "hit": hit.astype(float),
        }
    )
    data = data.dropna(subset=["imbalance", "mid", "r1"])
    data = data[data["mid"] > 0]
    if data.empty:
        raise ValueError("No valid rows after cleaning. Check input CSV market fields.")

    ic = float(data["imbalance"].corr(data["r1"]))
    print(f"rows={len(data)}")
    print(f"IC={ic:.8f}")

    try:
        decile_table = _make_decile_table(data)
    except ValueError:
        print("Decile table skipped: insufficient unique imbalance values.")
    else:
        _print_table("Deciles (all rows):", decile_table)

    spread_data = data.dropna(subset=["spread"]).copy()
    if spread_data["spread"].nunique() > 1:
        spread_cut = float(spread_data["spread"].median())
        print(f"spread_median={spread_cut:.8f}")
        spread_data["spread_regime"] = spread_data["spread"].map(
            lambda x: "low_spread" if x <= spread_cut else "high_spread"
        )

        for regime in ("low_spread", "high_spread"):
            regime_rows = spread_data[spread_data["spread_regime"] == regime]
            if regime_rows.empty:
                continue
            try:
                regime_table = _make_decile_table(regime_rows)
            except ValueError:
                print(f"Decile table skipped for {regime}: insufficient unique values.")
                continue
            _print_table(f"Deciles ({regime}):", regime_table)
    else:
        print("Spread regime split skipped: spread column missing or non-varying.")


if __name__ == "__main__":
    main()
