from __future__ import annotations

import argparse
import json
from typing import cast
from uuid import uuid4

from forex_trader.application.autonomous import RUNTIME_STATE_KEY
from forex_trader.application.risk_breaker import (
    RiskBreakerRepository,
    review_loss_streak_breaker,
    risk_breaker_status,
)
from forex_trader.application.sync import BrokerStateSynchronizer, TransactionRepository, TransactionSource
from forex_trader.config import AppConfig, build_engine
from forex_trader.domain.enums import OperatingMode, ProviderKind
from forex_trader.domain.models import jsonable
from forex_trader.domain.risk_advanced import EnhancedRiskPolicy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operator-reviewed recovery for the OANDA Practice loss-streak circuit breaker."
    )
    parser.add_argument("--reason", required=True, help="Human review rationale stored in the durable audit record.")
    parser.add_argument("--review-id", default=None, help="Unique review ID; generated when omitted.")
    parser.add_argument(
        "--confirm-practice-resume",
        action="store_true",
        help="Required acknowledgement that this creates a new Practice loss-streak observation epoch.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.confirm_practice_resume:
        raise SystemExit("refusing recovery without --confirm-practice-resume")

    config = AppConfig.from_env()
    errors = config.validate()
    if errors:
        raise SystemExit("; ".join(errors))
    if config.provider is not ProviderKind.OANDA:
        raise SystemExit("breaker recovery is supported only for the OANDA provider")
    if config.mode is not OperatingMode.PAPER or not config.enable_paper_orders:
        raise SystemExit("breaker recovery is restricted to OANDA Practice paper-order mode")

    engine = build_engine(config)
    if not isinstance(engine.risk_policy, EnhancedRiskPolicy):
        raise SystemExit("configured risk policy does not expose the advanced loss-streak breaker")

    repository = cast(RiskBreakerRepository, engine.repository)
    lease_owner_reader = getattr(engine.repository, "runtime_lease_owner", None)
    if lease_owner_reader is None:
        raise SystemExit("repository does not expose the durable autonomous runner lease")
    lease_owner = lease_owner_reader(RUNTIME_STATE_KEY)
    if lease_owner:
        raise SystemExit(
            "autonomous Practice runtime is still running; stop it before reviewing the breaker "
            f"(lease owner {lease_owner})"
        )

    synchronizer = BrokerStateSynchronizer(
        cast(TransactionSource, engine.broker),
        cast(TransactionRepository, engine.repository),
    )
    synchronizer.catch_up()
    account = engine.broker.account()
    positions = [position for position in engine.broker.positions() if position.net_units != 0]
    if positions:
        instruments = ", ".join(sorted(position.instrument for position in positions))
        raise SystemExit(f"refusing breaker recovery with open broker positions: {instruments}")

    cursor_reader = getattr(engine.repository, "get_broker_cursor", None)
    if cursor_reader is None:
        raise SystemExit("repository does not expose the reconciled broker transaction cursor")
    broker_cursor = cursor_reader("oanda.transactions")
    if not broker_cursor:
        raise SystemExit("broker reconciliation did not establish a transaction cursor")

    before = risk_breaker_status(
        repository,
        account_id=account.account_id,
        nav=account.nav,
        max_loss_streak=engine.risk_policy.max_loss_streak,
    )
    review = review_loss_streak_breaker(
        repository,
        account_id=account.account_id,
        nav=account.nav,
        max_loss_streak=engine.risk_policy.max_loss_streak,
        broker_cursor=str(broker_cursor),
        review_id=str(args.review_id or f"operator-{uuid4().hex[:16]}"),
        reason=str(args.reason),
    )
    # Reconciliation consumes the reviewed epoch immediately so the command exits
    # with the exact durable risk state the next autonomous daemon will observe.
    synchronizer.catch_up()
    refreshed_account = engine.broker.account()
    after = risk_breaker_status(
        repository,
        account_id=refreshed_account.account_id,
        nav=refreshed_account.nav,
        max_loss_streak=engine.risk_policy.max_loss_streak,
    )
    print(
        json.dumps(
            jsonable({"before": before, "review": review, "after": after}),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
