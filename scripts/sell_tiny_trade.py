import json
import os

from src.config import BASE_URL, API_KEY, API_SECRET
from src.binance_client import BinanceClient

SYMBOL = "BTCUSDT"


def _dry_run_enabled() -> bool:
    return os.getenv("DRY_RUN", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def main():
    c = BinanceClient(base_url=BASE_URL, api_key=API_KEY, api_secret=API_SECRET)
    dry_run = _dry_run_enabled()
    print(f"DRY_RUN={dry_run}")

    acct_before = c.get("/v3/account", signed=True)
    bal_before = {b["asset"]: (b["free"], b["locked"]) for b in acct_before["balances"]}

    print("\n--- BEFORE ---")
    print("USDT:", bal_before.get("USDT"))
    print("BTC :", bal_before.get("BTC"))

    # In DRY_RUN mode use order/test only. Real order requires DRY_RUN=false.
    order_path = "/v3/order/test" if dry_run else "/v3/order"
    order = c.post(
        order_path,
        signed=True,
        params={
            "symbol": SYMBOL,
            "side": "SELL",
            "type": "MARKET",
            "quantity": "0.00014",
        },
    )
    if dry_run:
        print("\nDRY_RUN active: used /v3/order/test (no balance changes expected).")

    print("\n--- ORDER RESPONSE ---")
    print(json.dumps(order, indent=2))

    acct_after = c.get("/v3/account", signed=True)
    bal_after = {b["asset"]: (b["free"], b["locked"]) for b in acct_after["balances"]}

    print("\n--- AFTER ---")
    print("USDT:", bal_after.get("USDT"))
    print("BTC :", bal_after.get("BTC"))


if __name__ == "__main__":
    main()
