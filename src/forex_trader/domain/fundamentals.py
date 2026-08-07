from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Iterable

from forex_trader.domain.models import CurrencyFundamentals, FundamentalAssessment


_POSITIVE_TERMS = {
    "hawkish",
    "strong",
    "accelerates",
    "beats",
    "higher",
    "tightening",
    "resilient",
    "expands",
    "upgrade",
}
_NEGATIVE_TERMS = {
    "dovish",
    "weak",
    "slows",
    "misses",
    "lower",
    "easing",
    "recession",
    "contracts",
    "downgrade",
}


class FundamentalBook:
    def __init__(self, snapshots: Iterable[CurrencyFundamentals] | None = None) -> None:
        self._states = {snapshot.currency.upper(): snapshot for snapshot in snapshots or []}

    def upsert(self, snapshot: CurrencyFundamentals) -> None:
        self._states[snapshot.currency.upper()] = snapshot

    def get(self, currency: str) -> CurrencyFundamentals | None:
        return self._states.get(currency.upper())

    def apply_release(
        self,
        *,
        currency: str,
        category: str,
        actual: Decimal,
        forecast: Decimal,
        previous: Decimal,
        higher_is_positive: bool,
        importance: Decimal = Decimal("1"),
        observed_at: datetime | None = None,
    ) -> CurrencyFundamentals:
        state = self.get(currency) or CurrencyFundamentals(currency=currency.upper())
        scale = max(abs(forecast - previous), abs(forecast) * Decimal("0.01"), Decimal("0.0001"))
        surprise = max(Decimal("-1"), min(Decimal("1"), (actual - forecast) / scale))
        if not higher_is_positive:
            surprise = -surprise
        surprise *= max(Decimal("0"), min(Decimal("1"), importance))
        category_key = category.lower()
        updates: dict[str, Decimal | datetime] = {"as_of": observed_at or datetime.now(UTC)}
        if category_key in {"rate", "policy"}:
            updates["policy"] = _blend(state.policy, surprise)
        elif category_key in {"inflation", "cpi", "pce"}:
            updates["inflation"] = _blend(state.inflation, surprise)
        elif category_key in {"labor", "employment", "jobs"}:
            updates["labor"] = _blend(state.labor, surprise)
        else:
            updates["growth"] = _blend(state.growth, surprise)
        updates["confidence"] = min(Decimal("1"), max(state.confidence, Decimal("0.55") + importance * Decimal("0.30")))
        next_state = replace(state, **updates)
        self.upsert(next_state)
        return next_state

    def apply_news(
        self,
        *,
        currency: str,
        headline: str,
        body: str = "",
        source_weight: Decimal = Decimal("0.7"),
        observed_at: datetime | None = None,
    ) -> CurrencyFundamentals:
        state = self.get(currency) or CurrencyFundamentals(currency=currency.upper())
        tokens = {token.strip(".,:;!?()[]{}\"'").lower() for token in f"{headline} {body}".split()}
        positive = len(tokens & _POSITIVE_TERMS)
        negative = len(tokens & _NEGATIVE_TERMS)
        total = positive + negative
        sentiment = Decimal("0") if total == 0 else Decimal(positive - negative) / Decimal(total)
        weight = max(Decimal("0"), min(Decimal("1"), source_weight))
        next_state = replace(
            state,
            news=_blend(state.news, sentiment * weight, old_weight=Decimal("0.7")),
            confidence=max(state.confidence, Decimal("0.45") + weight * Decimal("0.30")),
            as_of=observed_at or datetime.now(UTC),
        )
        self.upsert(next_state)
        return next_state

    def assess_pair(
        self,
        instrument: str,
        *,
        as_of: datetime | None = None,
        maximum_age: timedelta = timedelta(days=7),
    ) -> FundamentalAssessment:
        base, quote = instrument.split("_", maxsplit=1)
        base_state = self.get(base)
        quote_state = self.get(quote)
        if base_state is None or quote_state is None:
            missing = [c for c, state in ((base, base_state), (quote, quote_state)) if state is None]
            return FundamentalAssessment(
                instrument,
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                (f"missing fundamental state for {', '.join(missing)}",),
            )
        observed_at = as_of or datetime.now(UTC)
        base_age = max(timedelta(0), observed_at - base_state.as_of)
        quote_age = max(timedelta(0), observed_at - quote_state.as_of)
        freshness = Decimal("1")
        oldest_age = max(base_age, quote_age)
        if oldest_age > maximum_age:
            freshness = Decimal("0")
        elif maximum_age.total_seconds() > 0:
            freshness = max(
                Decimal("0.25"),
                Decimal("1") - Decimal(str(oldest_age.total_seconds() / maximum_age.total_seconds())) * Decimal("0.50"),
            )
        differential = max(Decimal("-2"), min(Decimal("2"), base_state.score - quote_state.score))
        confidence = min(base_state.confidence, quote_state.confidence) * freshness
        freshness_reason = (
            f"fundamental freshness={freshness}"
            if freshness > 0
            else f"fundamental state is older than {maximum_age}"
        )
        return FundamentalAssessment(
            instrument=instrument,
            base_score=base_state.score,
            quote_score=quote_state.score,
            differential=differential,
            confidence=confidence,
            reasons=(
                f"{base} composite={base_state.score}",
                f"{quote} composite={quote_state.score}",
                f"currency-strength differential={differential}",
                freshness_reason,
            ),
        )

    def snapshots(self) -> list[CurrencyFundamentals]:
        return sorted(self._states.values(), key=lambda item: item.currency)


def _blend(old: Decimal, new: Decimal, old_weight: Decimal = Decimal("0.5")) -> Decimal:
    value = old * old_weight + new * (Decimal("1") - old_weight)
    return max(Decimal("-1"), min(Decimal("1"), value))
