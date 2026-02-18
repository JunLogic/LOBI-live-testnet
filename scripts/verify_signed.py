from src.config import BASE_URL, API_KEY, API_SECRET
from src.binance_client import BinanceClient


def main():
    c = BinanceClient(base_url=BASE_URL, api_key=API_KEY, api_secret=API_SECRET)

    # 1) Signed account endpoint
    acct = c.get("/v3/account", signed=True)
    print("Account OK. Balances sample:", acct["balances"][:5])

    # 2) Test order (does NOT trade)
    resp = c.post(
        "/v3/order/test",
        signed=True,
        params={
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": "10",  # spend 10 USDT (testnet)
        },
    )
    print("Order test OK:", resp)


if __name__ == "__main__":
    main()
