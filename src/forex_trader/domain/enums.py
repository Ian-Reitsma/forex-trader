from enum import StrEnum


class OperatingMode(StrEnum):
    SHADOW = "shadow"
    PAPER = "paper"


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class DecisionDisposition(StrEnum):
    TRADE = "trade"
    ABSTAIN = "abstain"


class RiskDisposition(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"


class OrderStatus(StrEnum):
    CREATED = "created"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    PROTECTED = "protected"
    CLOSING = "closing"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    EMERGENCY_CLOSE = "emergency_close"


class ProviderKind(StrEnum):
    SIMULATION = "simulation"
    OANDA = "oanda"
