from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if old not in text:
        raise RuntimeError(f"expected patch anchor not found in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1))


def replace_all(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if old not in text:
        raise RuntimeError(f"expected patch anchor not found in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new))


# Ruff findings from the full-tree command.
replace_once(
    "src/forex_trader/research/backtest.py",
    "    win_r = reward / risk\n",
    "",
)
replace_once(
    "src/forex_trader/research/return_reporting.py",
    "from datetime import date, datetime, time, timedelta\n",
    "from datetime import date, datetime, timedelta\n",
)
replace_once(
    "tests/test_macro_source_edge_cases.py",
    "from forex_trader.domain.context import DataQualitySnapshot, HealthState, ProviderHealth\n",
    "from forex_trader.domain.context import DataQualitySnapshot, HealthState\n",
)
replace_once(
    "tests/test_risk_day.py",
    "    import pytest\n\n",
    "",
)

# Strict typing: transaction stream protocol.
replace_once(
    "src/forex_trader/application/sync.py",
    "from datetime import UTC, datetime, timedelta\n",
    "from collections.abc import Iterator\nfrom datetime import UTC, datetime, timedelta\n",
)
replace_once(
    "src/forex_trader/application/sync.py",
    "    def transaction_stream(\n        self,\n        *,\n        max_events: int | None = None,\n        include_heartbeats: bool = False,\n    ): ...\n",
    "    def transaction_stream(\n        self,\n        *,\n        max_events: int | None = None,\n        include_heartbeats: bool = False,\n    ) -> Iterator[dict[str, object]]: ...\n",
)

# Strict typing: correlation timestamps are datetimes, not opaque objects.
replace_once(
    "src/forex_trader/domain/correlation_risk.py",
    "from dataclasses import dataclass\n",
    "from dataclasses import dataclass\nfrom datetime import datetime\n",
)
replace_once(
    "src/forex_trader/domain/correlation_risk.py",
    "    def _prices(self, instrument: str) -> dict[object, float]:\n",
    "    def _prices(self, instrument: str) -> dict[datetime, float]:\n",
)

# Strict typing: swing timestamps are produced from Candle.time and are datetimes.
replace_once(
    "src/forex_trader/domain/market_structure.py",
    "from dataclasses import dataclass\n",
    "from dataclasses import dataclass\nfrom datetime import datetime\n",
)
replace_once(
    "src/forex_trader/domain/market_structure.py",
    "    time: object\n",
    "    time: datetime\n",
)

# Strict typing: liquidity helpers operate on real dates and SwingPoint instances.
replace_once(
    "src/forex_trader/domain/liquidity.py",
    "from datetime import datetime, timedelta\n",
    "from datetime import date, datetime, timedelta\n",
)
replace_once(
    "src/forex_trader/domain/liquidity.py",
    "from forex_trader.domain.market_structure import SwingKind, find_swings\n",
    "from forex_trader.domain.market_structure import SwingKind, SwingPoint, find_swings\n",
)
replace_once(
    "src/forex_trader/domain/liquidity.py",
    "    source_time: object | None = None\n",
    "    source_time: datetime | None = None\n",
)
replace_once(
    "src/forex_trader/domain/liquidity.py",
    "            # A swing/session level cannot be swept by the same candle that creates it.\n            if level.source_time is not None and getattr(level.source_time, \"__gt__\", None) is not None:\n                try:\n                    if level.source_time >= candle.time:\n                        continue\n                except TypeError:\n                    pass\n",
    "            # A swing/session level cannot be swept by the same candle that creates it.\n            if level.source_time is not None and level.source_time >= candle.time:\n                continue\n",
)
replace_all(
    "src/forex_trader/domain/liquidity.py",
    "    groups: dict[object, list[Candle]] = defaultdict(list)\n",
    "    groups: dict[date, list[Candle]] = defaultdict(list)\n",
)
replace_once(
    "src/forex_trader/domain/liquidity.py",
    "def _recent_external_swings(points: list[object], kind: LiquidityKind, *, count: int = 5) -> list[LiquidityLevel]:\n",
    "def _recent_external_swings(points: list[SwingPoint], kind: LiquidityKind, *, count: int = 5) -> list[LiquidityLevel]:\n",
)
replace_once(
    "src/forex_trader/domain/liquidity.py",
    "                Decimal(str(getattr(point, \"price\"))),\n                strength,\n                getattr(point, \"time\", None),\n",
    "                point.price,\n                strength,\n                point.time,\n",
)
replace_once(
    "src/forex_trader/domain/liquidity.py",
    "def _equal_levels(points: list[object], kind: LiquidityKind, *, tolerance: Decimal) -> list[LiquidityLevel]:\n",
    "def _equal_levels(points: list[SwingPoint], kind: LiquidityKind, *, tolerance: Decimal) -> list[LiquidityLevel]:\n",
)
replace_once(
    "src/forex_trader/domain/liquidity.py",
    "        first_price = Decimal(str(getattr(first, \"price\")))\n        second_price = Decimal(str(getattr(second, \"price\")))\n",
    "        first_price = first.price\n        second_price = second.price\n",
)
replace_once(
    "src/forex_trader/domain/liquidity.py",
    "                    getattr(second, \"time\", None),\n",
    "                    second.time,\n",
)

# Strict typing: execution engine dynamic extension points are narrowed at their boundaries.
replace_once(
    "src/forex_trader/application/engine.py",
    "from forex_trader.domain.models import DecisionTrace, OrderRequest, OrderResult, Quote, jsonable\n",
    "from forex_trader.domain.models import (\n    AccountSnapshot,\n    DecisionTrace,\n    InstrumentSpec,\n    OrderRequest,\n    OrderResult,\n    Quote,\n    RiskAuthorization,\n    TradeCandidate,\n    jsonable,\n)\nfrom forex_trader.domain.portfolio import OpenPosition\n",
)
replace_once(
    "src/forex_trader/application/engine.py",
    "        positions_snapshot: list[object] = []\n",
    "        positions_snapshot: list[OpenPosition] = []\n",
)
replace_once(
    "src/forex_trader/application/engine.py",
    "    def _execute_candidate(\n        self,\n        *,\n        candidate,\n        initial_risk,\n        initial_account,\n        spec,\n        spread_limit: Decimal,\n    ):\n",
    "    def _execute_candidate(\n        self,\n        *,\n        candidate: TradeCandidate,\n        initial_risk: RiskAuthorization,\n        initial_account: AccountSnapshot,\n        spec: InstrumentSpec | None,\n        spread_limit: Decimal,\n    ) -> tuple[\n        TradeCandidate,\n        RiskAuthorization,\n        OrderResult | None,\n        Quote,\n        AccountSnapshot,\n        list[OpenPosition],\n    ]:\n",
)
replace_once(
    "src/forex_trader/application/engine.py",
    "    def _confirm_protection(self, order: OrderResult, candidate, account_id: str) -> OrderResult:\n",
    "    def _confirm_protection(\n        self,\n        order: OrderResult,\n        candidate: TradeCandidate,\n        account_id: str,\n    ) -> OrderResult:\n",
)
replace_once(
    "src/forex_trader/application/engine.py",
    "    def promotion_status(self) -> dict[str, object]:\n        if not hasattr(self.repository, \"promotion_metrics\"):\n            return {\"ready\": False, \"reasons\": [\"repository does not expose promotion metrics\"]}\n        metrics = self.repository.promotion_metrics()  # type: ignore[attr-defined]\n        return jsonable(self.promotion_policy.evaluate(metrics))\n",
    "    def promotion_status(self) -> dict[str, object]:\n        metrics_reader = getattr(self.repository, \"promotion_metrics\", None)\n        if metrics_reader is None:\n            return {\"ready\": False, \"reasons\": [\"repository does not expose promotion metrics\"]}\n        metrics = metrics_reader()\n        result = jsonable(self.promotion_policy.evaluate(metrics))\n        if not isinstance(result, dict):\n            raise TypeError(\"promotion evaluation must serialize to a mapping\")\n        return {str(key): value for key, value in result.items()}\n",
)
replace_once(
    "src/forex_trader/application/engine.py",
    "    def _apply_context_hard_gates(self, candidate, quote: Quote):\n",
    "    def _apply_context_hard_gates(\n        self,\n        candidate: TradeCandidate,\n        quote: Quote,\n    ) -> TradeCandidate:\n",
)
replace_once(
    "src/forex_trader/application/engine.py",
    "        return getter(\"global\") or getter(f\"execution:{account_id}\") or getter(f\"risk:{account_id}\")\n",
    "        reason = getter(\"global\") or getter(f\"execution:{account_id}\") or getter(f\"risk:{account_id}\")\n        return None if reason is None else str(reason)\n",
)
replace_once(
    "src/forex_trader/application/engine.py",
    "    def _observe_latched_loss(self, account, signal_time: datetime, capital_base: Decimal) -> bool:\n",
    "    def _observe_latched_loss(\n        self,\n        account: AccountSnapshot,\n        signal_time: datetime,\n        capital_base: Decimal,\n    ) -> bool:\n",
)
replace_once(
    "src/forex_trader/application/engine.py",
    "    def _instrument_spec(self, instrument: str):\n        getter = getattr(self.broker, \"instrument_spec\", None)\n        if getter is None:\n            return None\n        spec = getter(instrument)\n        register_spec(spec)\n        return spec\n",
    "    def _instrument_spec(self, instrument: str) -> InstrumentSpec | None:\n        getter = getattr(self.broker, \"instrument_spec\", None)\n        if getter is None:\n            return None\n        spec = getter(instrument)\n        if not isinstance(spec, InstrumentSpec):\n            raise TypeError(\"broker instrument_spec must return InstrumentSpec\")\n        register_spec(spec)\n        return spec\n",
)
replace_once(
    "src/forex_trader/application/engine.py",
    "    def _quote_for_units(self, instrument: str, units: int | None) -> Quote:\n        getter = getattr(self.broker, \"quote_for_units\", None)\n        if getter is not None:\n            return getter(instrument, units)\n        return self.market_data.quote(instrument)\n",
    "    def _quote_for_units(self, instrument: str, units: int | None) -> Quote:\n        getter = getattr(self.broker, \"quote_for_units\", None)\n        if getter is not None:\n            quote = getter(instrument, units)\n            if not isinstance(quote, Quote):\n                raise TypeError(\"broker quote_for_units must return Quote\")\n            return quote\n        return self.market_data.quote(instrument)\n",
)

# Strict override compatibility: accept the complete parent keyword surface while the
# external aggregator remains authoritative for the injected values.
replace_once(
    "src/forex_trader/application/external_context.py",
    "    def evaluate(\n        self,\n        technical: TechnicalAssessment,\n        fundamental: FundamentalAssessment,\n        quote: Quote,\n        *,\n        maximum_spread_pips: Decimal | None = None,\n        components: DecisionComponentPolicy = PRODUCTION_DECISION_COMPONENTS,\n    ) -> TradeCandidate:\n",
    "    def evaluate(\n        self,\n        technical: TechnicalAssessment,\n        fundamental: FundamentalAssessment,\n        quote: Quote,\n        *,\n        maximum_spread_pips: Decimal | None = None,\n        components: DecisionComponentPolicy = PRODUCTION_DECISION_COMPONENTS,\n        cross_asset_alignment: Decimal = Decimal(\"0\"),\n        cross_asset_source_ids: tuple[str, ...] = (),\n        institutional_flow_pressure: Decimal | None = None,\n        institutional_flow_source: str | None = None,\n        institutional_flow_confidence: Decimal = Decimal(\"0\"),\n    ) -> TradeCandidate:\n",
)

# Release identity.
replace_once(
    "src/forex_trader/__init__.py",
    '__version__ = "0.7.38"\n',
    '__version__ = "0.7.39"\n',
)
replace_all(
    "tests/test_version_identity.py",
    '0.7.38',
    '0.7.39',
)

# Make the exact full-tree commands from the operator workflow merge-blocking.
ci_path = Path(".github/workflows/ci.yml")
ci = ci_path.read_text()
anchor = "      - name: Test and coverage\n"
if "      - name: Full-tree lint\n" not in ci:
    if anchor not in ci:
        raise RuntimeError("CI insertion anchor not found")
    full_checks = (
        "      - name: Full-tree lint\n"
        "        run: ruff check src scripts tests\n"
        "      - name: Strict application/domain typing\n"
        "        run: python -m mypy --strict src/forex_trader/application src/forex_trader/domain\n"
    )
    ci = ci.replace(anchor, full_checks + anchor, 1)
ci_path.write_text(ci)
