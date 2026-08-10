from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Iterable

from forex_trader.domain.models import CurrencyFundamentals, FundamentalAssessment


_COMPONENT_WEIGHTS = {
    "policy": Decimal("0.35"),
    "inflation": Decimal("0.20"),
    "growth": Decimal("0.15"),
    "labor": Decimal("0.15"),
    "news": Decimal("0.15"),
}
# Directional influence should decay as markets digest the information.
_COMPONENT_HALF_LIVES = {
    "policy": timedelta(days=21),
    "inflation": timedelta(hours=72),
    "growth": timedelta(hours=72),
    "labor": timedelta(hours=48),
    "news": timedelta(hours=6),
}
# Evidence coverage is distinct from directional alpha. Official monthly/quarterly
# data remains valid coverage through its normal reporting interval, while the
# directional impulse above decays much faster. maximum_age still hard-expires
# non-policy components after 30 days by default.
_COMPONENT_CONFIDENCE_HALF_LIVES = {
    "policy": timedelta(days=365),
    "inflation": timedelta(days=180),
    "growth": timedelta(days=180),
    "labor": timedelta(days=90),
    "news": timedelta(hours=6),
}
_POSITIVE_PHRASES = {
    "hawkish": Decimal("1.0"),
    "higher for longer": Decimal("1.0"),
    "restrictive policy": Decimal("0.8"),
    "inflation remains elevated": Decimal("0.55"),
    "strong growth": Decimal("0.7"),
    "labor market remains strong": Decimal("0.7"),
    "beats expectations": Decimal("0.65"),
    "upside surprise": Decimal("0.65"),
    "rate hike": Decimal("0.9"),
    "tightening": Decimal("0.8"),
}
_NEGATIVE_PHRASES = {
    "dovish": Decimal("1.0"),
    "rate cut": Decimal("0.9"),
    "easing": Decimal("0.8"),
    "weak growth": Decimal("0.7"),
    "recession": Decimal("0.9"),
    "misses expectations": Decimal("0.65"),
    "downside surprise": Decimal("0.65"),
    "inflation is cooling": Decimal("0.55"),
    "labor market is weakening": Decimal("0.7"),
}
_SINGLE_TERMS = {
    "hawkish": Decimal("0.8"), "strong": Decimal("0.35"), "accelerates": Decimal("0.45"),
    "beats": Decimal("0.45"), "higher": Decimal("0.20"), "tightening": Decimal("0.55"),
    "resilient": Decimal("0.40"), "expands": Decimal("0.35"), "upgrade": Decimal("0.35"),
    "dovish": Decimal("-0.8"), "weak": Decimal("-0.35"), "slows": Decimal("-0.40"),
    "misses": Decimal("-0.45"), "lower": Decimal("-0.20"), "easing": Decimal("-0.55"),
    "recession": Decimal("-0.70"), "contracts": Decimal("-0.35"), "downgrade": Decimal("-0.35"),
}
_NEGATIONS = {"not", "no", "never", "neither", "without", "unlikely"}
_UNCERTAINTY = {"may", "might", "could", "uncertain", "possibly", "rumor", "unconfirmed"}


class FundamentalBook:
    """Currency evidence with per-component timestamps/confidence and point-aware decay."""

    def __init__(self, snapshots: Iterable[CurrencyFundamentals] | None = None) -> None:
        self._states: dict[str, CurrencyFundamentals] = {}
        self._component_times: dict[str, dict[str, datetime]] = {}
        self._component_confidence: dict[str, dict[str, Decimal]] = {}
        self._release_history: dict[tuple[str, str], list[Decimal]] = {}
        self._last_actual: dict[tuple[str, str], Decimal] = {}
        self._last_central_bank_text: dict[str, str] = {}
        for snapshot in snapshots or []:
            self.upsert(snapshot)

    def upsert(self, snapshot: CurrencyFundamentals) -> None:
        currency = snapshot.currency.upper()
        self._states[currency] = snapshot
        self._component_times.setdefault(currency, {component: snapshot.as_of for component in _COMPONENT_WEIGHTS})
        self._component_confidence.setdefault(currency, {component: snapshot.confidence for component in _COMPONENT_WEIGHTS})

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
        currency = currency.upper()
        timestamp = observed_at or datetime.now(UTC)
        state = self.get(currency) or CurrencyFundamentals(currency=currency, as_of=timestamp)
        category_key = category.lower()
        component = _component_for_category(category_key)
        history_key = (currency, category_key)
        raw_surprise = actual - forecast
        history = self._release_history.setdefault(history_key, [])
        if len(history) >= 5:
            historical_scale = Decimal(str(median(history[-24:])))
        else:
            historical_scale = Decimal("0")
        fallback_scale = max(abs(forecast - previous), abs(forecast) * Decimal("0.01"), Decimal("0.0001"))
        scale = max(historical_scale, fallback_scale)
        surprise = raw_surprise / scale
        last_actual = self._last_actual.get(history_key)
        revision = Decimal("0") if last_actual is None else (previous - last_actual) / scale
        combined = surprise + revision * Decimal("0.35")
        if not higher_is_positive:
            combined = -combined
        bounded_importance = max(Decimal("0"), min(Decimal("1"), importance))
        combined = max(Decimal("-1"), min(Decimal("1"), combined)) * bounded_importance
        history.append(abs(raw_surprise))
        self._last_actual[history_key] = actual

        updates: dict[str, Decimal | datetime] = {
            component: _blend(getattr(state, component), combined),
            "as_of": max(state.as_of, timestamp),
        }
        confidence = min(Decimal("1"), Decimal("0.50") + bounded_importance * Decimal("0.40"))
        next_state = replace(state, **updates, confidence=max(state.confidence, confidence))
        self._states[currency] = next_state
        self._component_times.setdefault(currency, {})[component] = timestamp
        self._component_confidence.setdefault(currency, {})[component] = confidence
        return next_state

    def apply_indicator(
        self,
        *,
        currency: str,
        category: str,
        actual: Decimal,
        previous: Decimal | None,
        higher_is_positive: bool,
        importance: Decimal = Decimal("1"),
        source_confidence: Decimal = Decimal("1"),
        observed_at: datetime | None = None,
    ) -> CurrencyFundamentals:
        """Apply verified official state/trend evidence without inventing consensus.

        If the publisher exposes a prior comparable value, actual-vs-previous supplies a
        directional trend. If it exposes only the current policy level, ``previous=None``
        records full first-party evidence coverage with a neutral directional contribution
        instead of fabricating a historical comparison.
        """
        currency = currency.upper()
        timestamp = observed_at or datetime.now(UTC)
        state = self.get(currency) or CurrencyFundamentals(currency=currency, as_of=timestamp)
        component = _component_for_category(category.lower())
        if previous is None:
            direction = Decimal("0")
        else:
            delta = actual - previous
            if delta > 0:
                direction = Decimal("1")
            elif delta < 0:
                direction = Decimal("-1")
            else:
                direction = Decimal("0")
            if not higher_is_positive:
                direction = -direction
        bounded_importance = max(Decimal("0"), min(Decimal("1"), importance))
        signal = direction * bounded_importance
        confidence = (
            max(Decimal("0"), min(Decimal("1"), source_confidence))
            * (Decimal("0.75") + bounded_importance * Decimal("0.25"))
        )
        next_state = replace(
            state,
            **{
                component: _blend(getattr(state, component), signal, old_weight=Decimal("0.35")),
                "confidence": max(state.confidence, confidence),
                "as_of": max(state.as_of, timestamp),
            },
        )
        self._states[currency] = next_state
        self._component_times.setdefault(currency, {})[component] = timestamp
        self._component_confidence.setdefault(currency, {})[component] = confidence
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
        currency = currency.upper()
        timestamp = observed_at or datetime.now(UTC)
        state = self.get(currency) or CurrencyFundamentals(currency=currency, as_of=timestamp)
        score, lexical_confidence, evidence = interpret_fx_text(f"{headline}. {body}")
        weight = max(Decimal("0"), min(Decimal("1"), source_weight))
        confidence = lexical_confidence * weight
        next_state = replace(
            state,
            news=_blend(state.news, score * weight, old_weight=Decimal("0.65")),
            confidence=max(state.confidence, confidence),
            as_of=max(state.as_of, timestamp),
        )
        self._states[currency] = next_state
        self._component_times.setdefault(currency, {})["news"] = timestamp
        self._component_confidence.setdefault(currency, {})["news"] = confidence
        return next_state

    def apply_central_bank(
        self,
        *,
        currency: str,
        headline: str,
        body: str = "",
        source_weight: Decimal = Decimal("0.9"),
        observed_at: datetime | None = None,
    ) -> CurrencyFundamentals:
        currency = currency.upper()
        timestamp = observed_at or datetime.now(UTC)
        state = self.get(currency) or CurrencyFundamentals(currency=currency, as_of=timestamp)
        text = f"{headline}. {body}".strip()
        current_score, lexical_confidence, _ = interpret_fx_text(text)
        previous_text = self._last_central_bank_text.get(currency, "")
        previous_score = interpret_fx_text(previous_text)[0] if previous_text else Decimal("0")
        statement_delta = current_score - previous_score
        policy_signal = max(
            Decimal("-1"),
            min(Decimal("1"), current_score * Decimal("0.65") + statement_delta * Decimal("0.35")),
        )
        weight = max(Decimal("0"), min(Decimal("1"), source_weight))
        confidence = min(
            Decimal("1"),
            lexical_confidence * weight + (Decimal("0.15") if previous_text else Decimal("0")),
        )
        next_state = replace(
            state,
            policy=_blend(state.policy, policy_signal * weight, old_weight=Decimal("0.55")),
            news=_blend(state.news, current_score * weight, old_weight=Decimal("0.80")),
            confidence=max(state.confidence, confidence),
            as_of=max(state.as_of, timestamp),
        )
        self._states[currency] = next_state
        times = self._component_times.setdefault(currency, {})
        conf = self._component_confidence.setdefault(currency, {})
        times["policy"] = timestamp
        times["news"] = timestamp
        conf["policy"] = confidence
        conf["news"] = confidence
        self._last_central_bank_text[currency] = text
        return next_state

    def assess_pair(
        self,
        instrument: str,
        *,
        as_of: datetime | None = None,
        maximum_age: timedelta = timedelta(days=30),
    ) -> FundamentalAssessment:
        base, quote = instrument.upper().split("_", maxsplit=1)
        base_state = self.get(base)
        quote_state = self.get(quote)
        if base_state is None or quote_state is None:
            missing = [c for c, state in ((base, base_state), (quote, quote_state)) if state is None]
            return FundamentalAssessment(
                instrument.upper(),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                (f"missing fundamental state for {', '.join(missing)}",),
            )
        observed_at = as_of or datetime.now(UTC)
        if observed_at.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        base_score, base_confidence, base_reasons = self._effective_currency(base, base_state, observed_at, maximum_age)
        quote_score, quote_confidence, quote_reasons = self._effective_currency(quote, quote_state, observed_at, maximum_age)
        differential = max(Decimal("-2"), min(Decimal("2"), base_score - quote_score))
        confidence = min(base_confidence, quote_confidence)
        return FundamentalAssessment(
            instrument=instrument.upper(),
            base_score=base_score,
            quote_score=quote_score,
            differential=differential,
            confidence=confidence,
            reasons=(
                f"{base} effective composite={base_score}",
                f"{quote} effective composite={quote_score}",
                f"currency-strength differential={differential}",
                *base_reasons,
                *quote_reasons,
            ),
        )

    def _effective_currency(
        self,
        currency: str,
        state: CurrencyFundamentals,
        as_of: datetime,
        maximum_age: timedelta,
    ) -> tuple[Decimal, Decimal, tuple[str, ...]]:
        times = self._component_times.get(currency, {})
        confidences = self._component_confidence.get(currency, {})
        weighted_score = Decimal("0")
        weighted_confidence = Decimal("0")
        covered_weight = Decimal("0")
        future_components: list[str] = []
        for component, weight in _COMPONENT_WEIGHTS.items():
            timestamp = times.get(component, state.as_of)
            if timestamp > as_of:
                future_components.append(component)
                continue
            age = as_of - timestamp
            if age > maximum_age and component != "policy":
                score_freshness = Decimal("0")
                confidence_freshness = Decimal("0")
            else:
                score_freshness = _decay(age, _COMPONENT_HALF_LIVES[component])
                confidence_freshness = _decay(age, _COMPONENT_CONFIDENCE_HALF_LIVES[component])
            value = Decimal(str(getattr(state, component)))
            weighted_score += value * weight * score_freshness
            confidence = confidences.get(component, Decimal("0")) * confidence_freshness
            weighted_confidence += confidence * weight
            covered_weight += weight
        if covered_weight <= 0:
            return Decimal("0"), Decimal("0"), (f"{currency} has no point-in-time eligible components",)
        score = max(Decimal("-1"), min(Decimal("1"), weighted_score / covered_weight))
        confidence = max(Decimal("0"), min(Decimal("1"), weighted_confidence / covered_weight))
        reasons: list[str] = []
        if future_components:
            reasons.append(f"{currency} excluded future components: {','.join(sorted(future_components))}")
        return score, confidence, tuple(reasons)

    def snapshots(self) -> list[CurrencyFundamentals]:
        return sorted(self._states.values(), key=lambda item: item.currency)


def interpret_fx_text(text: str) -> tuple[Decimal, Decimal, tuple[str, ...]]:
    cleaned = " ".join(text.lower().split())
    if not cleaned:
        return Decimal("0"), Decimal("0"), ()
    score = Decimal("0")
    evidence: list[str] = []
    for phrase, weight in _POSITIVE_PHRASES.items():
        if phrase in cleaned:
            score += weight
            evidence.append(f"+{phrase}")
    for phrase, weight in _NEGATIVE_PHRASES.items():
        if phrase in cleaned:
            score -= weight
            evidence.append(f"-{phrase}")
    tokens = [token.strip(".,:;!?()[]{}\"'") for token in cleaned.split()]
    for index, token in enumerate(tokens):
        if token not in _SINGLE_TERMS:
            continue
        local = _SINGLE_TERMS[token]
        preceding = set(tokens[max(0, index - 3) : index])
        if preceding & _NEGATIONS:
            local = -local
            evidence.append(f"negated:{token}")
        score += local
    score = max(
        Decimal("-1"),
        min(Decimal("1"), score / max(Decimal("1"), Decimal(len(evidence)) * Decimal("0.75"))),
    )
    uncertainty_count = sum(token in _UNCERTAINTY for token in tokens)
    confidence = min(Decimal("0.85"), Decimal("0.25") + Decimal(len(evidence)) * Decimal("0.12"))
    confidence *= max(Decimal("0.25"), Decimal("1") - Decimal(uncertainty_count) * Decimal("0.20"))
    return score, confidence, tuple(evidence)


def _component_for_category(category: str) -> str:
    if category in {"rate", "policy", "rates", "central_bank"}:
        return "policy"
    if category in {"inflation", "cpi", "pce", "ppi"}:
        return "inflation"
    if category in {"labor", "employment", "jobs", "wages", "nfp"}:
        return "labor"
    return "growth"


def _blend(old: Decimal, new: Decimal, old_weight: Decimal = Decimal("0.5")) -> Decimal:
    value = old * old_weight + new * (Decimal("1") - old_weight)
    return max(Decimal("-1"), min(Decimal("1"), value))


def _decay(age: timedelta, half_life: timedelta) -> Decimal:
    if age <= timedelta(0):
        return Decimal("1")
    fraction = age.total_seconds() / max(1.0, half_life.total_seconds())
    return Decimal(str(0.5 ** fraction))
