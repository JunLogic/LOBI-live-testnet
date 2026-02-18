# LOBI Live Binance Spot Testnet Bot

This repo runs a live (REST polling) Binance Spot Testnet bot with causal execution:

- Signal is computed at poll `t`.
- The action executed is the pending signal from poll `t-1`.
- Uses `/v3/...` paths because `.env` base URL already includes `/api`.

## Strategy

- Baseline signal is L1 order book imbalance from `bookTicker`:
  - `imbalance = (bidQty - askQty) / (bidQty + askQty)`
- Thresholded signal:
  - `imbalance > +thr` -> `BUY`
  - `imbalance < -thr` -> `SELL`
  - otherwise `HOLD`
- Default threshold is loaded from `research/lobi_rule_report.json`:
  - `rule.selected_threshold = 0.06` (FI-2010 tuning artifact)

Optional:
- Set `USE_DEPTH=true` to compute imbalance from `/v3/depth` top levels.

## Safety Defaults

- `DRY_RUN=true` by default (no real order placement).
- Cooldown between trades.
- Max notional per trade.
- Max absolute BTC position.
- Exchange filter checks (`minQty`, `stepSize`, `minNotional`).
- Consecutive error stop.
- 429/418 backoff.
- Best-effort cancel of open orders on shutdown.

## Setup

1. Activate the existing venv:

```powershell
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Ensure `.env` contains:

- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`
- `BINANCE_TESTNET_BASE_URL=https://testnet.binance.vision/api`

## Run

```powershell
python -m src.run_live
```

The bot appends one row per poll to `outputs/trades.csv`.

In `DRY_RUN=true`, it also maintains an in-memory paper portfolio and writes:
- `paper_btc`, `paper_usdt`
- `paper_equity_usdt`, `paper_pnl_usdt`
- `paper_trade_notional_usdt`, `paper_fee_usdt`

## Environment Variables

- `DRY_RUN` (default `true`)
- `SYMBOL` (default `BTCUSDT`)
- `THRESHOLD` (default from FI-2010 artifact, usually `0.06`)
- `POLL_INTERVAL_SECONDS` (default `2.0`)
- `USE_DEPTH` (default `false`)
- `DEPTH_LEVELS` (default `10`)
- `COOLDOWN_SECONDS` (default `15`)
- `MAX_NOTIONAL_PER_TRADE_USDT` (default `10`)
- `MAX_ABS_POSITION_BTC` (default `0.001`)
- `MAX_CONSECUTIVE_ERRORS` (default `5`)
- `RESYNC_EVERY_N_POLLS` (default `30`)
- `PRINT_EVERY_N_POLLS` (default `1`)
- `BACKOFF_BASE_SECONDS` (default `2`)
- `BACKOFF_CAP_SECONDS` (default `60`)
- `MAX_POLLS` (default `0`, meaning run continuously)
- `PAPER_START_USDT` (default `10000`)
- `PAPER_START_BTC` (default `0`)
- `PAPER_FEE_RATE` (default `0.0`)
- `PAPER_SLIPPAGE_BPS` (default `0.0`)

For live testnet execution, set `DRY_RUN=false`.

## Paper PnL Summary

```powershell
python -m scripts.summarize_paper_pnl
```

Optional plot (only if matplotlib is installed):

```powershell
python -m scripts.summarize_paper_pnl --plot
```
