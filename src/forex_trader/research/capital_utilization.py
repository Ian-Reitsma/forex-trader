from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class CapitalUtilizationObservation:
    trace_id: str
    instrument: str
    authorized_units: int
    risk_amount: Decimal
    risk_budget: Decimal
    risk_utilization_fraction: Decimal
    raw_risk_budget_units: int
    configured_max_units: int
    broker_maximum_position_units: int | None
    binding_limit: str | None
    entry_price: Decimal
    quote_currency_notional: Decimal
    margin_rate: Decimal | None
    quote_currency_estimated_margin: Decimal | None

    def to_jsonable(self) -> dict[str, object]:
        return {
            "trace_id": self.trace_id,
            "instrument": self.instrument,
            "authorized_units": self.authorized_units,
            "risk_amount": str(self.risk_amount),
            "risk_budget": str(self.risk_budget),
            "risk_utilization_fraction": str(self.risk_utilization_fraction),
            "raw_risk_budget_units": self.raw_risk_budget_units,
            "configured_max_units": self.configured_max_units,
            "broker_maximum_position_units": self.broker_maximum_position_units,
            "binding_limit": self.binding_limit,
            "entry_price": str(self.entry_price),
            "quote_currency_notional": str(self.quote_currency_notional),
            "margin_rate": None if self.margin_rate is None else str(self.margin_rate),
            "quote_currency_estimated_margin": (
                None
                if self.quote_currency_estimated_margin is None
                else str(self.quote_currency_estimated_margin)
            ),
        }


def analyze_trace_capital_utilization(
    trace: Mapping[str, object],
    *,
    risk_fraction: Decimal,
    configured_max_units: int,
) -> CapitalUtilizationObservation | None:
    if risk_fraction <= 0:
        raise ValueError("risk_fraction must be positive")
    if configured_max_units < 1:
        raise ValueError("configured_max_units must be positive")

    risk = _mapping(trace.get("risk"))
    if str(risk.get("disposition") or "").lower() != "granted":
        return None
    units = abs(_integer(risk.get("units")))
    risk_amount = _decimal(risk.get("risk_amount"))
    if units < 1 or risk_amount <= 0:
        return None

    candidate = _mapping(trace.get("candidate"))
    entry_price = _decimal(candidate.get("entry_price"))
    if entry_price <= 0:
        return None

    metadata = _mapping(trace.get("metadata"))
    account = _mapping(metadata.get("account_snapshot"))
    balance = _decimal(account.get("balance"))
    nav = _decimal(account.get("nav"))
    capital_base = min(balance, nav)
    if capital_base <= 0:
        return None

    risk_budget = capital_base * risk_fraction
    per_unit_loss = risk_amount / Decimal(units)
    if per_unit_loss <= 0:
        return None
    raw_units = int((risk_budget / per_unit_loss).to_integral_value(rounding=ROUND_FLOOR))

    spec = _mapping(metadata.get("instrument_spec"))
    broker_max_raw = _optional_decimal(spec.get("maximum_position_size"))
    broker_max_units = (
        int(broker_max_raw)
        if broker_max_raw is not None and broker_max_raw > 0
        else None
    )
    margin_rate = _optional_decimal(spec.get("margin_rate"))

    binding_limit: str | None = None
    if raw_units > units:
        if units >= configured_max_units and raw_units > configured_max_units:
            binding_limit = "configured_max_units"
        elif broker_max_units is not None and units >= broker_max_units and raw_units > broker_max_units:
            binding_limit = "broker_maximum_position_size"
        else:
            binding_limit = "other_or_downstream_constraint"

    notional = Decimal(units) * entry_price
    estimated_margin = None if margin_rate is None else notional * margin_rate
    return CapitalUtilizationObservation(
        trace_id=str(trace.get("trace_id") or ""),
        instrument=str(trace.get("instrument") or candidate.get("instrument") or "").upper(),
        authorized_units=units,
        risk_amount=risk_amount,
        risk_budget=risk_budget,
        risk_utilization_fraction=risk_amount / risk_budget,
        raw_risk_budget_units=raw_units,
        configured_max_units=configured_max_units,
        broker_maximum_position_units=broker_max_units,
        binding_limit=binding_limit,
        entry_price=entry_price,
        quote_currency_notional=notional,
        margin_rate=margin_rate,
        quote_currency_estimated_margin=estimated_margin,
    )


def summarize_capital_utilization(
    traces: Iterable[Mapping[str, object]],
    *,
    risk_fraction: Decimal,
    configured_max_units: int,
) -> dict[str, object]:
    observations = tuple(
        observation
        for trace in traces
        if (
            observation := analyze_trace_capital_utilization(
                trace,
                risk_fraction=risk_fraction,
                configured_max_units=configured_max_units,
            )
        )
        is not None
    )
    if not observations:
        return {
            "schema": "capital-utilization-study-v1",
            "observations": 0,
            "broker_write_authority": False,
            "rows": [],
        }

    utilization = [item.risk_utilization_fraction for item in observations]
    binding = [item for item in observations if item.binding_limit is not None]
    underutilized = [item for item in observations if item.risk_utilization_fraction < Decimal("0.90")]
    return {
        "schema": "capital-utilization-study-v1",
        "broker_write_authority": False,
        "observations": len(observations),
        "configured_risk_fraction": str(risk_fraction),
        "configured_max_units": configured_max_units,
        "average_risk_utilization_fraction": str(sum(utilization, Decimal("0")) / Decimal(len(utilization))),
        "minimum_risk_utilization_fraction": str(min(utilization)),
        "maximum_risk_utilization_fraction": str(max(utilization)),
        "under_90_percent_risk_budget_count": len(underutilized),
        "binding_limit_count": len(binding),
        "binding_limit_fraction": str(Decimal(len(binding)) / Decimal(len(observations))),
        "binding_limits": _count_bindings(binding),
        "rows": [item.to_jsonable() for item in observations],
    }


def _count_bindings(observations: Iterable[CapitalUtilizationObservation]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in observations:
        if item.binding_limit is None:
            continue
        counts[item.binding_limit] = counts.get(item.binding_limit, 0) + 1
    return dict(sorted(counts.items()))


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _integer(value: object) -> int:
    try:
        return int(str(value))
    except Exception:
        return 0
