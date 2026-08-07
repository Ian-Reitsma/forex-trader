"""Read-only OANDA Practice smoke test.

Run with OANDA_API_TOKEN and optionally OANDA_ACCOUNT_ID set. This script never sends an order.
"""
from forex_trader.config import AppConfig
from forex_trader.adapters.oanda import OandaPracticeClient

config = AppConfig.from_env()
if not config.oanda_token:
    raise SystemExit("OANDA_API_TOKEN is required")
client = OandaPracticeClient(
    token=config.oanda_token,
    account_id=config.oanda_account_id,
    rest_url=config.oanda_rest_url,
)
try:
    print(client.account())
    print(client.quote("EUR_USD"))
    print(f"completed candles: {len(client.candles('EUR_USD', 'M5', 10))}")
finally:
    client.close()
