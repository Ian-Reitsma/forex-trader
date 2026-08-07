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
    FILLED = "filled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class ProviderKind(StrEnum):
    SIMULATION = "simulation"
    OANDA = "oanda"
