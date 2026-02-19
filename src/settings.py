from __future__ import annotations

import os
from dataclasses import dataclass


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RuntimeSettings:
    dry_run: bool
    symbol: str
    threshold: float
    poll_interval_seconds: float
    cooldown_seconds: float
    max_notional_per_trade_usdt: float
    max_abs_position_btc: float
    use_depth: bool
    depth_levels: int
    max_consecutive_errors: int
    resync_every_n_polls: int
    max_polls: int
    print_every_n_polls: int
    backoff_base_seconds: float
    backoff_cap_seconds: float
    paper_start_usdt: float
    paper_start_btc: float
    paper_fee_rate: float
    paper_slippage_bps: float
    confirmation_m: int
    confirmation_k: int


def load_runtime_settings() -> RuntimeSettings:
    confirmation_m = max(1, _parse_int(os.getenv("CONFIRMATION_M", "1"), 1))
    confirmation_k = max(1, _parse_int(os.getenv("CONFIRMATION_K", "1"), 1))
    if confirmation_k > confirmation_m:
        confirmation_k = confirmation_m

    return RuntimeSettings(
        dry_run=_parse_bool(os.getenv("DRY_RUN", "true")),
        symbol=os.getenv("SYMBOL", "BTCUSDT"),
        threshold=_parse_float(os.getenv("THRESHOLD", "0.06"), 0.06),
        poll_interval_seconds=max(
            0.1, _parse_float(os.getenv("POLL_INTERVAL_SECONDS", "2"), 2.0)
        ),
        cooldown_seconds=max(0.0, _parse_float(os.getenv("COOLDOWN_SECONDS", "15"), 15.0)),
        max_notional_per_trade_usdt=max(
            0.0, _parse_float(os.getenv("MAX_NOTIONAL_PER_TRADE_USDT", "10"), 10.0)
        ),
        max_abs_position_btc=max(
            0.0, _parse_float(os.getenv("MAX_ABS_POSITION_BTC", "0.001"), 0.001)
        ),
        use_depth=_parse_bool(os.getenv("USE_DEPTH", "false")),
        depth_levels=max(1, _parse_int(os.getenv("DEPTH_LEVELS", "10"), 10)),
        max_consecutive_errors=max(
            1, _parse_int(os.getenv("MAX_CONSECUTIVE_ERRORS", "5"), 5)
        ),
        resync_every_n_polls=max(
            1, _parse_int(os.getenv("RESYNC_EVERY_N_POLLS", "30"), 30)
        ),
        max_polls=max(0, _parse_int(os.getenv("MAX_POLLS", "0"), 0)),
        print_every_n_polls=max(
            1, _parse_int(os.getenv("PRINT_EVERY_N_POLLS", "1"), 1)
        ),
        backoff_base_seconds=max(
            0.1, _parse_float(os.getenv("BACKOFF_BASE_SECONDS", "2"), 2.0)
        ),
        backoff_cap_seconds=max(
            1.0, _parse_float(os.getenv("BACKOFF_CAP_SECONDS", "60"), 60.0)
        ),
        paper_start_usdt=max(0.0, _parse_float(os.getenv("PAPER_START_USDT", "10000"), 10000.0)),
        paper_start_btc=max(0.0, _parse_float(os.getenv("PAPER_START_BTC", "0"), 0.0)),
        paper_fee_rate=max(0.0, _parse_float(os.getenv("PAPER_FEE_RATE", "0.0"), 0.0)),
        paper_slippage_bps=max(
            0.0, _parse_float(os.getenv("PAPER_SLIPPAGE_BPS", "0.0"), 0.0)
        ),
        confirmation_m=confirmation_m,
        confirmation_k=confirmation_k,
    )
