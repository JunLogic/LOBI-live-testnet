import requests
from src.config import BASE_URL


def test_ping():
    r = requests.get(f"{BASE_URL}/v3/ping")
    print("Ping:", r.status_code, r.json())


def test_time():
    r = requests.get(f"{BASE_URL}/v3/time")
    print("Server time:", r.json())


def test_bookticker():
    r = requests.get(f"{BASE_URL}/v3/ticker/bookTicker", params={"symbol": "BTCUSDT"})
    print("BookTicker:", r.json())


if __name__ == "__main__":
    test_ping()
    test_time()
    test_bookticker()
