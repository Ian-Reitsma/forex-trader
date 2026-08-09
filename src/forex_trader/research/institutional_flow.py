from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Iterable

from forex_trader.domain.enums import Direction
from forex_trader.ingestion.providers import OrderFlowSnapshot

_NON_INSTITUTIONAL = frozenset({"", "none", "broker_tick_proxy"})


class InstitutionalFlowFeature(StrEnum):
    DELTA = "delta"
    CVD_CHANGE = "cvd_change"
    CVD_DIVERGENCE = "cvd_divergence"
    ABSORPTION = "absorption"
    DEPTH_IMBALANCE = "depth_imbalance"
    VWAP_LOCATION = "vwap_location"
    POC_LOCATION = "poc_location"
    VOLUME_EXPANSION = "volume_expansion"


@dataclass(frozen=True, slots=True)
class InstitutionalFlowFeatureEvidence:
    feature: InstitutionalFlowFeature
    direction: Direction
    strength: Decimal
    reason: str

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.strength <= Decimal("1"):
            raise ValueError("institutional-flow feature strength must be in [0,1]")


@dataclass(frozen=True, slots=True)
class InstitutionalFlowAssessment:
    instrument: str
    source: str
    as_of: datetime
    observed_at: datetime | None
    directional_pressure: Decimal
    reported_directional_pressure: Decimal | None
    direction: Direction
    confidence: Decimal
    stale: bool
    features: tuple[InstitutionalFlowFeatureEvidence, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("institutional-flow assessment as_of must be timezone-aware")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("institutional-flow observed_at must be timezone-aware")
        if not Decimal("-1") <= self.directional_pressure <= Decimal("1"):
            raise ValueError("institutional-flow pressure must be in [-1,1]")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("institutional-flow confidence must be in [0,1]")

    @property
    def eligible_for_confirmation(self) -> bool:
        return (
            not self.stale
            and self.source.strip().lower() not in _NON_INSTITUTIONAL
            and self.confidence >= Decimal("0.50")
            and abs(self.directional_pressure) >= Decimal("0.20")
            and self.direction is not Direction.FLAT
        )


_FEATURE_WEIGHTS = {
    InstitutionalFlowFeature.DELTA: Decimal("0.15"),
    InstitutionalFlowFeature.CVD_CHANGE: Decimal("0.15"),
    InstitutionalFlowFeature.CVD_DIVERGENCE: Decimal("0.25"),
    InstitutionalFlowFeature.ABSORPTION: Decimal("0.20"),
    InstitutionalFlowFeature.DEPTH_IMBALANCE: Decimal("0.15"),
    InstitutionalFlowFeature.VWAP_LOCATION: Decimal("0.07"),
    InstitutionalFlowFeature.POC_LOCATION: Decimal("0.03"),
}


def assess_institutional_flow(
    snapshots: Iterable[OrderFlowSnapshot],
    *,
    instrument: str,
    as_of: datetime,
    current_price: Decimal,
    prior_price: Decimal | None = None,
    maximum_age_seconds: Decimal = Decimal("60"),
) -> InstitutionalFlowAssessment:
    """Decompose centralized flow into auditable research features.

    The provider's precomputed ``directional_pressure`` is intentionally *not* an input to
    the derived pressure. It is retained for disagreement diagnostics only. Direction is
    derived from delta, CVD change/divergence, normalized absorption/depth imbalance and
    price location relative to centralized VWAP/POC. Volume expansion affects confidence,
    not direction.

    No broker-tick proxy is accepted as institutional flow. This research assessment does
    not itself grant Practice authority; promotion requires leakage-controlled ablation.
    """

    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if prior_price is not None and prior_price <= 0:
        raise ValueError("prior_price must be positive")
    if maximum_age_seconds <= 0:
        raise ValueError("maximum_age_seconds must be positive")

    normalized = instrument.upper()
    eligible = [
        item
        for item in snapshots
        if item.instrument.upper() == normalized and item.observed_at <= as_of
    ]
    if not eligible:
        return _unavailable(normalized, as_of, "none", "no point-in-time institutional-flow snapshot")

    latest = max(eligible, key=lambda item: (item.observed_at, item.source))
    source = latest.source.strip()
    if source.lower() in _NON_INSTITUTIONAL:
        return _unavailable(normalized, as_of, source or "none", "source is not centralized institutional flow")

    age = Decimal(str((as_of - latest.observed_at).total_seconds()))
    if age < 0 or age > maximum_age_seconds:
        return InstitutionalFlowAssessment(
            instrument=normalized,
            source=source,
            as_of=as_of,
            observed_at=latest.observed_at,
            directional_pressure=Decimal("0"),
            reported_directional_pressure=latest.directional_pressure,
            direction=Direction.FLAT,
            confidence=Decimal("0"),
            stale=True,
            features=(),
            reasons=(f"centralized flow snapshot stale age={age}s",),
        )

    same_source = sorted(
        (item for item in eligible if item.source == latest.source),
        key=lambda item: item.observed_at,
    )
    previous = same_source[-2] if len(same_source) >= 2 else None
    features: list[InstitutionalFlowFeatureEvidence] = []

    if latest.delta is not None and latest.delta != 0:
        features.append(
            _evidence(
                InstitutionalFlowFeature.DELTA,
                latest.delta,
                _scale_against_previous(latest.delta, previous.delta if previous else None),
                f"executed delta={latest.delta}",
            )
        )

    cvd_change: Decimal | None = None
    if (
        latest.cumulative_delta is not None
        and previous is not None
        and previous.cumulative_delta is not None
    ):
        cvd_change = latest.cumulative_delta - previous.cumulative_delta
        if cvd_change != 0:
            features.append(
                _evidence(
                    InstitutionalFlowFeature.CVD_CHANGE,
                    cvd_change,
                    _scale_against_previous(cvd_change, previous.cumulative_delta),
                    f"CVD change={cvd_change}",
                )
            )

    if cvd_change is not None and prior_price is not None:
        price_change = current_price - prior_price
        if price_change != 0 and cvd_change != 0 and (price_change > 0) != (cvd_change > 0):
            direction = Direction.LONG if cvd_change > 0 else Direction.SHORT
            strength = min(
                Decimal("1"),
                Decimal("0.55") + min(Decimal("0.45"), abs(cvd_change) / max(abs(previous.cumulative_delta or Decimal("0")), Decimal("1"))),
            )
            features.append(
                InstitutionalFlowFeatureEvidence(
                    InstitutionalFlowFeature.CVD_DIVERGENCE,
                    direction,
                    strength,
                    f"price change={price_change} diverges from CVD change={cvd_change}",
                )
            )

    if latest.absorption is not None and latest.absorption != 0:
        bounded = max(Decimal("-1"), min(Decimal("1"), latest.absorption))
        features.append(
            _evidence(
                InstitutionalFlowFeature.ABSORPTION,
                bounded,
                abs(bounded),
                f"normalized absorption={bounded}",
            )
        )

    if latest.depth_imbalance is not None and latest.depth_imbalance != 0:
        bounded = max(Decimal("-1"), min(Decimal("1"), latest.depth_imbalance))
        features.append(
            _evidence(
                InstitutionalFlowFeature.DEPTH_IMBALANCE,
                bounded,
                abs(bounded),
                f"normalized depth imbalance={bounded}",
            )
        )

    if latest.vwap is not None and latest.vwap > 0 and current_price != latest.vwap:
        relative = abs(current_price - latest.vwap) / current_price
        strength = min(Decimal("1"), relative / Decimal("0.0015"))
        features.append(
            _evidence(
                InstitutionalFlowFeature.VWAP_LOCATION,
                current_price - latest.vwap,
                strength,
                f"price={current_price} versus centralized VWAP={latest.vwap}",
            )
        )

    if latest.point_of_control is not None and latest.point_of_control > 0 and current_price != latest.point_of_control:
        relative = abs(current_price - latest.point_of_control) / current_price
        strength = min(Decimal("1"), relative / Decimal("0.002"))
        features.append(
            _evidence(
                InstitutionalFlowFeature.POC_LOCATION,
                current_price - latest.point_of_control,
                strength,
                f"price={current_price} versus point of control={latest.point_of_control}",
            )
        )

    volume_strength = Decimal("0")
    if latest.volume_expansion is not None:
        if latest.volume_expansion < 0:
            raise ValueError("volume_expansion must be non-negative")
        if latest.volume_expansion > Decimal("1"):
            volume_strength = min(Decimal("1"), (latest.volume_expansion - Decimal("1")) / Decimal("2"))
            features.append(
                InstitutionalFlowFeatureEvidence(
                    InstitutionalFlowFeature.VOLUME_EXPANSION,
                    Direction.FLAT,
                    volume_strength,
                    f"centralized volume expansion ratio={latest.volume_expansion}",
                )
            )

    directional = [item for item in features if item.direction is not Direction.FLAT]
    pressure = _weighted_pressure(directional)
    direction = (
        Direction.LONG
        if pressure >= Decimal("0.20")
        else Direction.SHORT
        if pressure <= Decimal("-0.20")
        else Direction.FLAT
    )
    agreement = _agreement(directional, pressure)
    coverage = min(Decimal("1"), Decimal(len(directional)) / Decimal("4"))
    confidence = latest.confidence * coverage * (Decimal("0.50") + agreement * Decimal("0.50"))
    confidence *= Decimal("1") + volume_strength * Decimal("0.10")

    reasons = [
        f"derived from {len(directional)} directional centralized-flow features",
        f"feature agreement={agreement:.3f}",
        f"provider confidence={latest.confidence}",
    ]
    reported = latest.directional_pressure
    if reported is not None and pressure != 0 and reported != 0:
        if (reported > 0) != (pressure > 0):
            confidence *= Decimal("0.50")
            reasons.append(
                f"provider pressure={reported} conflicts with derived pressure={pressure}; confidence halved"
            )
        else:
            reasons.append(f"provider pressure={reported} agrees in sign with derived pressure={pressure}")
    confidence = max(Decimal("0"), min(Decimal("1"), confidence))

    return InstitutionalFlowAssessment(
        instrument=normalized,
        source=source,
        as_of=as_of,
        observed_at=latest.observed_at,
        directional_pressure=pressure,
        reported_directional_pressure=reported,
        direction=direction,
        confidence=confidence,
        stale=False,
        features=tuple(features),
        reasons=tuple(reasons),
    )


def _evidence(
    feature: InstitutionalFlowFeature,
    signed_value: Decimal,
    strength: Decimal,
    reason: str,
) -> InstitutionalFlowFeatureEvidence:
    direction = Direction.LONG if signed_value > 0 else Direction.SHORT if signed_value < 0 else Direction.FLAT
    return InstitutionalFlowFeatureEvidence(
        feature,
        direction,
        max(Decimal("0"), min(Decimal("1"), strength)),
        reason,
    )


def _scale_against_previous(value: Decimal, previous: Decimal | None) -> Decimal:
    if previous is None:
        return Decimal("0.50")
    denominator = abs(value) + abs(previous)
    if denominator <= 0:
        return Decimal("0")
    return min(Decimal("1"), abs(value) / denominator * Decimal("2"))


def _weighted_pressure(features: list[InstitutionalFlowFeatureEvidence]) -> Decimal:
    weighted = Decimal("0")
    total_weight = Decimal("0")
    for item in features:
        weight = _FEATURE_WEIGHTS[item.feature]
        sign = Decimal("1") if item.direction is Direction.LONG else Decimal("-1")
        weighted += sign * item.strength * weight
        total_weight += weight
    if total_weight <= 0:
        return Decimal("0")
    return max(Decimal("-1"), min(Decimal("1"), weighted / total_weight))


def _agreement(features: list[InstitutionalFlowFeatureEvidence], pressure: Decimal) -> Decimal:
    if not features or pressure == 0:
        return Decimal("0")
    positive = pressure > 0
    aligned = sum(
        1
        for item in features
        if (item.direction is Direction.LONG) == positive
    )
    return Decimal(aligned) / Decimal(len(features))


def _unavailable(instrument: str, as_of: datetime, source: str, reason: str) -> InstitutionalFlowAssessment:
    return InstitutionalFlowAssessment(
        instrument=instrument,
        source=source,
        as_of=as_of,
        observed_at=None,
        directional_pressure=Decimal("0"),
        reported_directional_pressure=None,
        direction=Direction.FLAT,
        confidence=Decimal("0"),
        stale=True,
        features=(),
        reasons=(reason,),
    )
