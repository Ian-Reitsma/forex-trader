from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from threading import RLock


@dataclass(frozen=True, slots=True)
class InstrumentMetadata:
    name: str
    pip_size: Decimal
    display_precision: int | None = None
    trade_units_precision: int | None = None
    minimum_trade_size: Decimal | None = None
    maximum_order_units: Decimal | None = None
    maximum_position_size: Decimal | None = None
    margin_rate: Decimal | None = None


_REGISTRY: dict[str, InstrumentMetadata] = {}
_LOCK = RLock()


def register_instrument(
    name: str,
    *,
    pip_size: Decimal,
    display_precision: int | None = None,
    trade_units_precision: int | None = None,
    minimum_trade_size: Decimal | None = None,
    maximum_order_units: Decimal | None = None,
    maximum_position_size: Decimal | None = None,
    margin_rate: Decimal | None = None,
) -> InstrumentMetadata:
    if pip_size <= 0:
        raise ValueError("pip_size must be positive")
    metadata = InstrumentMetadata(
        name=name.upper(),
        pip_size=pip_size,
        display_precision=display_precision,
        trade_units_precision=trade_units_precision,
        minimum_trade_size=minimum_trade_size,
        maximum_order_units=maximum_order_units,
        maximum_position_size=maximum_position_size,
        margin_rate=margin_rate,
    )
    with _LOCK:
        _REGISTRY[metadata.name] = metadata
    return metadata


def register_spec(spec: object) -> InstrumentMetadata:
    name = str(getattr(spec, "name")).upper()
    pip = getattr(spec, "pip_size")
    return register_instrument(
        name,
        pip_size=Decimal(str(pip)),
        display_precision=getattr(spec, "display_precision", None),
        trade_units_precision=getattr(spec, "trade_units_precision", None),
        minimum_trade_size=getattr(spec, "minimum_trade_size", None),
        maximum_order_units=getattr(spec, "maximum_order_units", None),
        maximum_position_size=getattr(spec, "maximum_position_size", None),
        margin_rate=getattr(spec, "margin_rate", None),
    )


def metadata_for(name: str) -> InstrumentMetadata | None:
    with _LOCK:
        return _REGISTRY.get(name.upper())


def pip_size_for(name: str) -> Decimal:
    metadata = metadata_for(name)
    if metadata is not None:
        return metadata.pip_size
    # Safe fallback for offline fixtures only. Runtime broker adapters register
    # authoritative metadata before strategy/risk calculations are performed.
    return Decimal("0.01") if name.upper().endswith("_JPY") else Decimal("0.0001")


def clear_registry() -> None:
    with _LOCK:
        _REGISTRY.clear()
