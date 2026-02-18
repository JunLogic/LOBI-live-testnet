from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = [
    "paper_trade_notional_usdt",
    "paper_equity_usdt",
    "paper_pnl_usdt",
]


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize paper PnL from trades.csv")
    parser.add_argument("--csv", default="outputs/trades.csv", help="Path to trades.csv")
    parser.add_argument("--plot", action="store_true", help="Plot paper equity if matplotlib exists")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required paper columns: {missing}")

    trade_notional = _safe_numeric(df["paper_trade_notional_usdt"]).fillna(0.0)
    equity = _safe_numeric(df["paper_equity_usdt"]).dropna()
    pnl = _safe_numeric(df["paper_pnl_usdt"]).dropna()

    total_paper_trades = int((trade_notional > 0).sum())
    final_paper_equity = float(equity.iloc[-1]) if len(equity) else 0.0
    final_paper_pnl = float(pnl.iloc[-1]) if len(pnl) else 0.0

    if len(equity):
        running_peak = equity.cummax()
        drawdown = running_peak - equity
        max_drawdown = float(drawdown.max())
    else:
        max_drawdown = 0.0

    print(f"total_paper_trades={total_paper_trades}")
    print(f"final_paper_equity={final_paper_equity}")
    print(f"paper_pnl={final_paper_pnl}")
    print(f"max_drawdown={max_drawdown}")

    if args.plot:
        try:
            import matplotlib.pyplot as plt
        except Exception:
            print("plot skipped: matplotlib is not installed")
            return

        equity_plot = _safe_numeric(df["paper_equity_usdt"])
        plt.figure(figsize=(10, 4))
        plt.plot(equity_plot.index, equity_plot.values)
        plt.title("Paper Equity Curve")
        plt.xlabel("Row")
        plt.ylabel("USDT")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()


if __name__ == "__main__":
    main()
