from __future__ import annotations

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


def signal_from_imbalance(imbalance: float, threshold: float) -> str:
    if imbalance > threshold:
        return BUY
    if imbalance < -threshold:
        return SELL
    return HOLD
