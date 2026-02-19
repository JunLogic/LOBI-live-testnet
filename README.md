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

Optional threshold calibration (predictive, not PnL-based):
- Optimizes threshold on recent labeled observations using t-stat of signed forward returns.
- `WARMUP_THEN_TRADE`: warm up on `W`, calibrate once, then trade.
- `ROLLING_WALK_FORWARD`: calibrate on last `W`, trade next `H`, then recalibrate.

## Safety Defaults

- `DRY_RUN=true` by default (no real order placement).
- Cooldown between trades.
- Max notional per trade.
- Max absolute BTC position.
- Exchange filter checks (`minQty`, `stepSize`, `minNotional`).
- Consecutive error stop.
- 429/418 backoff.
- Best-effort cancel of open orders on shutdown.

## How To Run

1. Activate the existing venv:

```powershell
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Run a bounded dry-run session:

```powershell
$env:DRY_RUN="true"
$env:MAX_POLLS="50"
$env:POLL_INTERVAL_SECONDS="0.2"
python -m src.run_live
```

Per poll, the bot appends a row to `outputs/trades.csv` including market stream fields:
`timestamp`, `best_bid`, `best_ask`, `mid`, `spread`, `imbalance` (plus execution/risk/paper fields).

Ensure `.env` contains:

- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`
- `BINANCE_TESTNET_BASE_URL=https://testnet.binance.vision/api`

In `DRY_RUN=true`, the bot maintains an in-memory paper portfolio and writes:
- `paper_btc`, `paper_usdt`
- `paper_equity_usdt`, `paper_pnl_usdt`
- `paper_trade_notional_usdt`, `paper_fee_usdt`

## Safety

- Default behavior is safe: `DRY_RUN=true` means no real `/v3/order` placement.
- Live testnet order placement is only enabled when you explicitly set:

```powershell
$env:DRY_RUN="false"
python -m src.run_live
```

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
- `CONFIRMATION_M` (default `1`)
- `CONFIRMATION_K` (default `1`, clamped to `<= CONFIRMATION_M`)
- `ENABLE_THRESHOLD_CALIBRATION` (default `false`)
- `CALIBRATION_MODE` (`warmup_then_trade` or `rolling_walk_forward`)
- `CALIBRATION_W_POLLS` (default `300`)
- `CALIBRATION_H_POLLS` (default `500`, rolling mode only)
- `THRESH_GRID_MIN` (default `0.01`)
- `THRESH_GRID_MAX` (default `0.20`)
- `THRESH_GRID_STEP` (default `0.01`)
- `CALIBRATION_MIN_TRADES` (default `20`)
- `CALIBRATION_TURNOVER_PENALTY_ALPHA` (default `0.0`)
- `CALIBRATION_EMA_LAMBDA` (default `0.0`)
- `CALIBRATION_HORIZON_POLLS` (default `1`)

For live testnet execution, set `DRY_RUN=false`.

## Evaluation

Cost assumptions in paper trading:
- `PAPER_FEE_RATE` applies per simulated trade notional.
- `PAPER_SLIPPAGE_BPS` worsens fills after spread crossing (`BUY` from best ask, `SELL` from best bid).

Churn filter:
- Raw signals are confirmed by persistence before entering the 1-step delayed execution stream.
- `CONFIRMATION_M`: lookback window size.
- `CONFIRMATION_K`: minimum count of the same raw `BUY`/`SELL` in that window to emit tradeable signal.

Threshold calibration:
- Calibrates threshold on predictive score: t-stat of `s_t(theta) * r_{t+1}`.
- This does not alter live safety behavior; `DRY_RUN=true` remains default.

Paper PnL summary:

```powershell
python -m scripts.summarize_paper_pnl --csv outputs/trades.csv
```

Optional plot (only if matplotlib is installed):

```powershell
python -m scripts.summarize_paper_pnl --plot
```

Edge diagnostics:

```powershell
python -m scripts.diagnose_edge outputs/trades.csv
```

Smoke run with calibration enabled:

```powershell
$env:DRY_RUN="true"
$env:ENABLE_THRESHOLD_CALIBRATION="true"
$env:CALIBRATION_MODE="warmup_then_trade"
$env:CALIBRATION_W_POLLS="20"
$env:MAX_POLLS="60"
$env:POLL_INTERVAL_SECONDS="0.2"
python -m src.run_live
```

Smoke run with calibration disabled (baseline behavior):

```powershell
$env:DRY_RUN="true"
$env:ENABLE_THRESHOLD_CALIBRATION="false"
$env:MAX_POLLS="60"
$env:POLL_INTERVAL_SECONDS="0.2"
python -m src.run_live
```

Example output field formats:

```text
total_paper_trades=<int>
final_paper_equity=<float>
paper_pnl=<float>
max_drawdown=<float>
rows=<int>
IC=<float>
decile,count,mean_r1,hit_rate
```
