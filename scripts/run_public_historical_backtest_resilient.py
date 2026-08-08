from __future__ import annotations

from forex_trader.research.gdelt_history import ResilientGdeltDocHistoryClient

import scripts.run_public_historical_backtest as campaign


# The campaign module intentionally keeps its downloader dependency injectable so
# production research can swap a licensed PIT news provider later. For the public
# GDELT campaign, use the hardened parser that handles publisher-originated invalid
# JSON escapes without weakening timestamp or schema validation.
campaign.GdeltDocHistoryClient = ResilientGdeltDocHistoryClient  # type: ignore[misc]


if __name__ == "__main__":
    raise SystemExit(campaign.main())
