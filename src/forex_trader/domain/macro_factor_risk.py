from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Mapping
import json

from forex_trader.domain.enums import Direction
from forex_trader.domain.portfolio import OpenPosition


@dataclass(frozen=True, slots=True)
class MacroFactorExposureReport:
    by_factor: dict[str, Decimal]
    gross_factor_exposure: Decimal
    unclassified_instruments: tuple[str, ...] = ()
    unpriced_instruments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MacroFactorRiskDecision:
    blocked: bool
    reason: str | None
    report: MacroFactorExposureReport
    maximum_factor: str | None = None
    maximum_factor_exposure: Decimal = Decimal("0")


class MacroFactorClusterGuard:
    """Cap gross exposure to explicit macro/event thesis clusters.

    This guard is deliberately separate from return correlation and currency-leg
    concentration.  The mapping is policy data, not inferred from recent prices:
    instruments that share a factor such as ``usd_rates`` accumulate gross
    account-currency notional in the same bucket even when pairwise correlation
    temporarily breaks down.
    """

    def __init__(
        self,
        factor_map: Mapping[str, Iterable[str]],
        *,
        maximum_factor_exposure_fraction: Decimal = Decimal("2.5"),
        require_classification: bool = True,
    ) -> None:
        if maximum_factor_exposure_fraction <= 0:
            raise ValueError("maximum_factor_exposure_fraction must be positive")
        normalized: dict[str, frozenset[str]] = {}
        for instrument, factors in factor_map.items():
            name = instrument.upper()
            values = frozenset(str(item).strip().lower() for item in factors if str(item).strip())
            if not values:
                raise ValueError(f"macro factor map for {name} must not be empty")
            normalized[name] = values
        if not normalized:
            raise ValueError("macro factor map must not be empty")
        self.factor_map = normalized
        self.maximum_factor_exposure_fraction = maximum_factor_exposure_fraction
        self.require_classification = require_classification

    @classmethod
    def from_json_file(
        cls,
        path: str | Path,
        *,
        maximum_factor_exposure_fraction: Decimal | None = None,
        require_classification: bool | None = None,
    ) -> "MacroFactorClusterGuard":
        payload = json.loads(Path(path).read_text())
        if not isinstance(payload, dict):
            raise ValueError("macro factor policy must be a JSON object")
        raw_map = payload.get("instrument_factors")
        if not isinstance(raw_map, dict):
            raise ValueError("macro factor policy requires instrument_factors")
        configured_limit = Decimal(str(payload.get("maximum_factor_exposure_fraction", "2.5")))
        configured_strict = bool(payload.get("require_classification", True))
        return cls(
            {str(key): value for key, value in raw_map.items()},
            maximum_factor_exposure_fraction=(
                configured_limit
                if maximum_factor_exposure_fraction is None
                else maximum_factor_exposure_fraction
            ),
            require_classification=(
                configured_strict if require_classification is None else require_classification
            ),
        )

    def evaluate_candidate(
        self,
        *,
        candidate_instrument: str,
        candidate_direction: Direction,
        candidate_units: int,
        candidate_entry_price: Decimal,
        positions: Iterable[OpenPosition],
        account_currency: str,
        capital_base: Decimal,
        conversion_rate: Callable[[str, str], Decimal | None],
        mark_price: Callable[[str], Decimal | None],
    ) -> MacroFactorRiskDecision:
        if capital_base <= 0:
            raise ValueError("capital_base must be positive")
        if candidate_units <= 0:
            raise ValueError("candidate_units must be positive")
        signed = Decimal(candidate_units if candidate_direction is Direction.LONG else -candidate_units)
        hypothetical = [
            *positions,
            OpenPosition(
                instrument=candidate_instrument.upper(),
                long_units=signed if signed > 0 else Decimal("0"),
                short_units=signed if signed < 0 else Decimal("0"),
                long_average_price=candidate_entry_price if signed > 0 else None,
                short_average_price=candidate_entry_price if signed < 0 else None,
            ),
        ]

        def local_mark(instrument: str) -> Decimal | None:
            if instrument.upper() == candidate_instrument.upper():
                return candidate_entry_price
            return mark_price(instrument)

        report = self.exposure_report(
            hypothetical,
            account_currency=account_currency,
            conversion_rate=conversion_rate,
            mark_price=local_mark,
        )
        if self.require_classification and report.unclassified_instruments:
            joined = ", ".join(report.unclassified_instruments)
            return MacroFactorRiskDecision(
                True,
                f"macro factor classification missing: {joined}",
                report,
            )
        if report.unpriced_instruments:
            joined = ", ".join(report.unpriced_instruments)
            return MacroFactorRiskDecision(
                True,
                f"macro factor exposure cannot be priced safely: {joined}",
                report,
            )
        if not report.by_factor:
            return MacroFactorRiskDecision(False, None, report)
        maximum_factor, maximum_exposure = max(report.by_factor.items(), key=lambda item: item[1])
        limit = capital_base * self.maximum_factor_exposure_fraction
        if maximum_exposure > limit:
            return MacroFactorRiskDecision(
                True,
                (
                    f"macro factor exposure limit exceeded: {maximum_factor} "
                    f"{maximum_exposure}>{limit}"
                ),
                report,
                maximum_factor,
                maximum_exposure,
            )
        return MacroFactorRiskDecision(False, None, report, maximum_factor, maximum_exposure)

    def exposure_report(
        self,
        positions: Iterable[OpenPosition],
        *,
        account_currency: str,
        conversion_rate: Callable[[str, str], Decimal | None],
        mark_price: Callable[[str], Decimal | None],
    ) -> MacroFactorExposureReport:
        account = account_currency.upper()
        factor_exposure: dict[str, Decimal] = {}
        unclassified: set[str] = set()
        unpriced: set[str] = set()
        for position in positions:
            if position.gross_units <= 0:
                continue
            instrument = position.instrument.upper()
            factors = self.factor_map.get(instrument)
            if not factors:
                unclassified.add(instrument)
                continue
            price = mark_price(instrument)
            if price is None or price <= 0:
                unpriced.add(instrument)
                continue
            _, quote_currency = instrument.split("_", maxsplit=1)
            rate = Decimal("1") if quote_currency == account else conversion_rate(quote_currency, account)
            if rate is None or rate <= 0:
                unpriced.add(instrument)
                continue
            gross_notional = position.gross_units * price * rate
            for factor in factors:
                factor_exposure[factor] = factor_exposure.get(factor, Decimal("0")) + gross_notional
        return MacroFactorExposureReport(
            by_factor=dict(sorted(factor_exposure.items())),
            gross_factor_exposure=sum(factor_exposure.values(), Decimal("0")),
            unclassified_instruments=tuple(sorted(unclassified)),
            unpriced_instruments=tuple(sorted(unpriced)),
        )
