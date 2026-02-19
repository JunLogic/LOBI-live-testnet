from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from src.settings import RuntimeSettings

WARMUP = "WARMUP"
CALIBRATING = "CALIBRATING"
TRADING = "TRADING"

MODE_WARMUP_THEN_TRADE = "warmup_then_trade"
MODE_ROLLING_WALK_FORWARD = "rolling_walk_forward"


@dataclass(frozen=True)
class LabeledObservation:
    imbalance: float
    forward_return: float


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_mid(best_bid: float, best_ask: float) -> float:
    if best_bid <= 0 or best_ask <= 0:
        return 0.0
    return (best_bid + best_ask) / 2.0


def _std_sample(values: list[float], mean: float) -> float:
    n = len(values)
    if n <= 1:
        return 0.0
    var = sum((x - mean) * (x - mean) for x in values) / (n - 1)
    if var <= 0:
        return 0.0
    return math.sqrt(var)


class WalkForwardCalibrator:
    def __init__(self, settings: RuntimeSettings) -> None:
        self.mode = settings.calibration_mode
        self.window_size = settings.calibration_w_polls
        self.trade_horizon = settings.calibration_h_polls
        self.grid_min = settings.thresh_grid_min
        self.grid_max = settings.thresh_grid_max
        self.grid_step = settings.thresh_grid_step
        self.min_trades = settings.calibration_min_trades
        self.turnover_penalty_alpha = settings.calibration_turnover_penalty_alpha
        self.ema_lambda = settings.calibration_ema_lambda
        self.horizon_polls = settings.calibration_horizon_polls

        self.state = WARMUP
        self.last_report: dict[str, Any] = {}

        self._labeled_obs: deque[LabeledObservation] = deque(maxlen=self.window_size)
        self._pending_obs: deque[tuple[float, float]] = deque()
        self._theta_hat: Optional[float] = None
        self._theta_live: Optional[float] = None
        self._trade_polls_since_calibration = 0

    def update(self, snapshot: Any) -> None:
        if self.state == CALIBRATING:
            self.state = TRADING

        best_bid = _to_float(getattr(snapshot, "bid", 0.0))
        best_ask = _to_float(getattr(snapshot, "ask", 0.0))
        imbalance = _to_float(getattr(snapshot, "imbalance", 0.0))
        mid = _safe_mid(best_bid=best_bid, best_ask=best_ask)
        if mid <= 0:
            return

        self._pending_obs.append((imbalance, mid))
        if len(self._pending_obs) > self.horizon_polls:
            prev_imbalance, prev_mid = self._pending_obs.popleft()
            if prev_mid > 0:
                forward_return = (mid / prev_mid) - 1.0
                if math.isfinite(prev_imbalance) and math.isfinite(forward_return):
                    self._labeled_obs.append(
                        LabeledObservation(
                            imbalance=prev_imbalance,
                            forward_return=forward_return,
                        )
                    )

        if self.mode == MODE_WARMUP_THEN_TRADE:
            self._update_warmup_then_trade()
            return
        self._update_rolling_walk_forward()

    def current_threshold(self, default_threshold: float) -> float:
        threshold = self._theta_live if self._theta_live is not None else max(default_threshold, 0.0)
        if (
            self.mode == MODE_ROLLING_WALK_FORWARD
            and self._theta_live is not None
            and self.state in (TRADING, CALIBRATING)
        ):
            self._trade_polls_since_calibration += 1
        return threshold

    def _update_warmup_then_trade(self) -> None:
        if self._theta_live is not None:
            if self.state != CALIBRATING:
                self.state = TRADING
            return
        if len(self._labeled_obs) < self.window_size:
            self.state = WARMUP
            return
        self._attempt_calibration()

    def _update_rolling_walk_forward(self) -> None:
        if self._theta_live is None:
            if len(self._labeled_obs) < self.window_size:
                self.state = WARMUP
                return
            self._attempt_calibration()
            return

        if self._trade_polls_since_calibration >= self.trade_horizon:
            self._attempt_calibration()
            return

        if self.state != CALIBRATING:
            self.state = TRADING

    def _attempt_calibration(self) -> None:
        report = self._calibrate_threshold()
        self.last_report = report

        theta_hat = report.get("theta_hat")
        if theta_hat is None:
            if self._theta_live is None:
                self.state = WARMUP
            else:
                self.state = TRADING
                self._trade_polls_since_calibration = 0
            return

        self._theta_hat = float(theta_hat)
        if (self.ema_lambda > 0.0) and (self._theta_live is not None):
            theta_live = (self.ema_lambda * self._theta_hat) + (
                (1.0 - self.ema_lambda) * self._theta_live
            )
        else:
            theta_live = self._theta_hat

        self._theta_live = max(theta_live, 0.0)
        self._trade_polls_since_calibration = 0
        self.state = CALIBRATING
        self.last_report["theta_live"] = self._theta_live

    def _calibrate_threshold(self) -> dict[str, Any]:
        observations = list(self._labeled_obs)
        if len(observations) < self.window_size:
            return {
                "theta_hat": None,
                "score": float("-inf"),
                "score_adj": float("-inf"),
                "n": 0,
                "trade_rate": 0.0,
                "window_obs": len(observations),
                "reason": "insufficient_window",
            }

        grid = self._threshold_grid()
        if not grid:
            return {
                "theta_hat": None,
                "score": float("-inf"),
                "score_adj": float("-inf"),
                "n": 0,
                "trade_rate": 0.0,
                "window_obs": len(observations),
                "reason": "empty_grid",
            }

        best: Optional[dict[str, Any]] = None
        for theta in grid:
            n = 0
            signed_returns: list[float] = []
            for obs in observations:
                if obs.imbalance > theta:
                    signed_returns.append(obs.forward_return)
                    n += 1
                elif obs.imbalance < -theta:
                    signed_returns.append(-obs.forward_return)
                    n += 1

            if n < self.min_trades:
                continue

            mu = sum(signed_returns) / n
            sd = _std_sample(signed_returns, mean=mu)
            if sd == 0.0:
                score = float("inf") if mu > 0 else float("-inf")
            else:
                score = mu / (sd / math.sqrt(n))
            trade_rate = n / self.window_size
            score_adj = score - (self.turnover_penalty_alpha * trade_rate)

            candidate = {
                "theta_hat": theta,
                "score": score,
                "score_adj": score_adj,
                "n": n,
                "trade_rate": trade_rate,
                "window_obs": len(observations),
                "reason": "ok",
            }
            if best is None or candidate["score_adj"] > best["score_adj"]:
                best = candidate

        if best is None:
            return {
                "theta_hat": None,
                "score": float("-inf"),
                "score_adj": float("-inf"),
                "n": 0,
                "trade_rate": 0.0,
                "window_obs": len(observations),
                "reason": "no_valid_candidate",
            }
        return best

    def _threshold_grid(self) -> list[float]:
        grid: list[float] = []
        theta = self.grid_min
        max_steps = 10000
        steps = 0
        while theta <= (self.grid_max + 1e-12) and steps < max_steps:
            if theta > 0:
                grid.append(round(theta, 10))
            theta += self.grid_step
            steps += 1
        return grid
