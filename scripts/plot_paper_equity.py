from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def _require_column(df: pd.DataFrame, column: str) -> None:
    if column in df.columns:
        return
    available = ", ".join(df.columns.tolist())
    raise ValueError(
        f"Missing required column: {column}. Available columns: {available}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot paper equity curve from trades CSV.")
    parser.add_argument("--csv", default="outputs/trades.csv", help="Path to trades.csv")
    parser.add_argument(
        "--out",
        default="outputs/equity_curve.png",
        help="Output path for equity PNG.",
    )
    parser.add_argument(
        "--drawdown-out",
        default=None,
        help="Optional output path for drawdown PNG.",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    _require_column(df, "paper_equity_usdt")

    equity = pd.to_numeric(df["paper_equity_usdt"], errors="coerce")
    rows_with_equity = int(equity.notna().sum())
    total_rows = int(len(df))
    if rows_with_equity == 0:
        raise ValueError("Column paper_equity_usdt has no numeric values.")

    start_equity = float(equity.dropna().iloc[0])
    end_equity = float(equity.dropna().iloc[-1])
    min_equity = float(equity.min(skipna=True))
    max_equity = float(equity.max(skipna=True))

    x = pd.RangeIndex(len(df))
    use_timestamp_axis = False
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        if int(ts.notna().sum()) > 0:
            x = ts
            use_timestamp_axis = True

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(x, equity, label="paper_equity_usdt", linewidth=1.5)

    if "paper_trade_notional_usdt" in df.columns:
        notional = pd.to_numeric(df["paper_trade_notional_usdt"], errors="coerce").fillna(0.0)
        trade_mask = notional > 0
        if bool(trade_mask.any()):
            trade_x = x[trade_mask]
            trade_y = equity[trade_mask]
            ax.scatter(
                trade_x,
                trade_y,
                s=10,
                c="tab:red",
                alpha=0.7,
                label="paper trades",
            )

    ax.set_title("Paper Equity Curve")
    ax.set_ylabel("USDT")
    ax.set_xlabel("timestamp" if use_timestamp_axis else "row")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)

    if args.drawdown_out:
        dd_path = Path(args.drawdown_out)
        dd_path.parent.mkdir(parents=True, exist_ok=True)
        rolling_max = equity.cummax()
        drawdown = equity - rolling_max

        fig_dd, ax_dd = plt.subplots(figsize=(12, 4))
        ax_dd.plot(x, drawdown, color="tab:orange", linewidth=1.5)
        ax_dd.set_title("Paper Equity Drawdown")
        ax_dd.set_ylabel("USDT")
        ax_dd.set_xlabel("timestamp" if use_timestamp_axis else "row")
        ax_dd.grid(True, alpha=0.25)
        fig_dd.tight_layout()
        fig_dd.savefig(dd_path, dpi=150)
        plt.close(fig_dd)

    print(f"total_rows={total_rows}")
    print(f"rows_with_equity={rows_with_equity}")
    print(f"start_equity={start_equity}")
    print(f"end_equity={end_equity}")
    print(f"min_equity={min_equity}")
    print(f"max_equity={max_equity}")
    print(f"equity_plot={out_path}")
    if args.drawdown_out:
        print(f"drawdown_plot={Path(args.drawdown_out)}")


if __name__ == "__main__":
    main()
