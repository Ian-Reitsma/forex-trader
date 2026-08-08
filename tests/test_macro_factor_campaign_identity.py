from __future__ import annotations

from decimal import Decimal

from forex_trader.application.campaign_policy import campaign_policy_context, campaign_policy_fingerprint
from forex_trader.config import AppConfig, build_engine


def test_macro_factor_policy_is_part_of_campaign_identity(tmp_path) -> None:  # type: ignore[no-untyped-def]
    first = build_engine(
        AppConfig(
            database_path=str(tmp_path / "first.db"),
            max_macro_factor_exposure_fraction=Decimal("2.5"),
        )
    )
    second = build_engine(
        AppConfig(
            database_path=str(tmp_path / "second.db"),
            max_macro_factor_exposure_fraction=Decimal("3.0"),
        )
    )
    first_context = campaign_policy_context(first)
    second_context = campaign_policy_context(second)

    assert first_context["schema"] == "campaign-policy-v2"
    assert first_context["risk_version"] == "practice-risk-v0.7.24"
    assert first_context["macro_factor"]["maximum_factor_exposure_fraction"] == "2.5"  # type: ignore[index]
    assert "EUR_USD" in first_context["macro_factor"]["instrument_factors"]  # type: ignore[index]
    assert campaign_policy_fingerprint(first_context) != campaign_policy_fingerprint(second_context)


def test_macro_factor_risk_can_be_explicitly_disabled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = build_engine(
        AppConfig(
            database_path=str(tmp_path / "disabled.db"),
            enable_macro_factor_risk=False,
        )
    )
    context = campaign_policy_context(engine)
    assert context["macro_factor"] is None
