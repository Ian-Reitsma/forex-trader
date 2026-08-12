from __future__ import annotations

import json
from typing import cast

from forex_trader.application.risk_breaker import RiskBreakerRepository, risk_breaker_status
from forex_trader.config import AppConfig, build_engine
from forex_trader.domain.risk_advanced import EnhancedRiskPolicy
from forex_trader.domain.models import jsonable


def main() -> int:
    config = AppConfig.from_env()
    errors = config.validate()
    if errors:
        raise SystemExit("; ".join(errors))
    engine = build_engine(config)
    if not isinstance(engine.risk_policy, EnhancedRiskPolicy):
        raise SystemExit("configured risk policy does not expose the advanced loss-streak breaker")
    account = engine.broker.account()
    payload = risk_breaker_status(
        cast(RiskBreakerRepository, engine.repository),
        account_id=account.account_id,
        nav=account.nav,
        max_loss_streak=engine.risk_policy.max_loss_streak,
    )
    print(json.dumps(jsonable(payload), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
