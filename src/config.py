import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET")
BASE_URL = os.getenv("BINANCE_TESTNET_BASE_URL")

if not API_KEY or not API_SECRET or not BASE_URL:
    raise ValueError("Missing environment variables. Check your .env file.")
