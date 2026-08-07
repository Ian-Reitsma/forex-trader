from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from forex_trader.application.campaign_policy import (
    campaign_policy_context,
    campaign_policy_fingerprint,
    select_campaign_universe,
)
from forex_trader.config import AppConfig, build_engine
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.models import CurrencyFundamentals, FundamentalAssessment
from forex_trader.domain.strategy import SignalFusionPolicy


def test_policy_fingerprint_is_canonical_and_order_independent() -> None:
    left = {"strategy": {"minimum": Decimal("0.66"), "flags": ["a", "b"]}, "mode": "paper"}
    right = {"mode": "paper", "strategy": {"flags": ["a", "b"], "minimum": Decimal("0.66")}}
    assert campaign_policy_fingerprint(left) == campaign_policy_fingerprint(right)


def test_real_engine_policy_context_is_secret_free_and_changes_with_policy(tmp_path) -> None:
    first = build_engine(
        AppConfig(database_path=str(tmp_path / "a.db"), minimum_score=Decimal("0.66"))
    )
    second = build_engine(
        AppConfig(database_path=str(tmp_path / "b.db"), minimum_score=Decimal("0.72"))
    )
    context = campaign_policy_context(first)
    serialized = json.dumps(context, default=str).lower()
    assert "oanda_api_token" not in serialized
    assert "api_token" not in serialized
    assert "account_id" not in serialized
    assert context["fusion"]["minimum_score"] == Decimal("0.66")  # type: ignore[index]
    assert campaign_policy_fingerprint(context) != campaign_policy_fingerprint(
        campaign_policy_context(second)
    )


def test_universe_preflight_without_filter_keeps_normalized_unique_pairs() -> None:
    engine = SimpleNamespace()
    selection = select_campaign_universe(
        engine,  # type: ignore[arg-type]
        ["eur_usd", "EUR_USD", "GBP_USD"],
        require_fundamental_coverage=False,
    )
    assert selection.discovered == ("EUR_USD", "GBP_USD")
    assert selection.selected == selection.discovered
    assert selection.excluded == {}


def test_universe_preflight_excludes_missing_or_low_confidence_fundamentals() -> None:
    now = datetime.now(UTC)
    book = FundamentalBook(
        [
            CurrencyFundamentals("EUR", confidence=Decimal("0.90"), as_of=now),
            CurrencyFundamentals("USD", confidence=Decimal("0.90"), as_of=now),
            CurrencyFundamentals("GBP", confidence=Decimal("0.10"), as_of=now),
        ]
    )
    engine = SimpleNamespace(
        fundamentals=book,
        fusion_policy=SignalFusionPolicy(minimum_fundamental_confidence=Decimal("0.50")),
    )
    selection = select_campaign_universe(
        engine,  # type: ignore[arg-type]
        ["EUR_USD", "GBP_USD", "AUD_USD"],
        require_fundamental_coverage=True,
        as_of=now,
    )
    assert selection.selected == ("EUR_USD",)
    assert selection.excluded_count == 2
    assert "below" in selection.excluded["GBP_USD"]
    assert "missing fundamental state" in selection.excluded["AUD_USD"]


def test_universe_preflight_fails_closed_on_fundamental_assessment_error() -> None:
    class BrokenBook:
        def assess_pair(self, instrument: str, *, as_of):  # type: ignore[no-untyped-def]
            if instrument == "GBP_USD":
                raise RuntimeError("source broken")
            return FundamentalAssessment(
                instrument,
                Decimal("0.1"),
                Decimal("0"),
                Decimal("0.1"),
                Decimal("0.9"),
                ("ok",),
            )

    engine = SimpleNamespace(
        fundamentals=BrokenBook(),
        fusion_policy=SignalFusionPolicy(minimum_fundamental_confidence=Decimal("0.50")),
    )
    selection = select_campaign_universe(
        engine,  # type: ignore[arg-type]
        ["EUR_USD", "GBP_USD"],
        require_fundamental_coverage=True,
    )
    assert selection.selected == ("EUR_USD",)
    assert selection.excluded["GBP_USD"].startswith("fundamental preflight failed: RuntimeError")
