from __future__ import annotations

import json

from forex_trader.application.campaign import PracticeCampaignRunner
from forex_trader.config import AppConfig, build_engine
from forex_trader.domain.enums import OperatingMode, ProviderKind


def test_real_engine_campaign_executes_one_simulated_order_and_keeps_scanning(tmp_path) -> None:
    """Permanent end-to-end rehearsal for the post-credential Practice workflow.

    This uses the actual TradingEngine, structure/fundamental/risk/execution path and
    SimulatedPaperBroker. The campaign may submit exactly one paper order, then must keep
    evaluating the rest of the pair list in shadow without creating additional risk.
    """
    evidence = tmp_path / "campaign.jsonl"
    config = AppConfig(
        provider=ProviderKind.SIMULATION,
        mode=OperatingMode.PAPER,
        database_path=str(tmp_path / "campaign.db"),
        instruments=("EUR_USD", "GBP_USD", "USD_JPY"),
        enable_paper_orders=True,
    )
    engine = build_engine(config)
    runner = PracticeCampaignRunner(
        engine,
        config.instruments,
        execute=True,
        max_new_orders_per_cycle=1,
        evidence_path=evidence,
    )

    report = runner.run_cycle(1)

    assert report.instruments_requested == 3
    assert report.instruments_evaluated == 3
    assert report.orders_submitted == 1
    assert report.orders_unknown == 0
    assert report.orders_rejected == 0
    assert report.orders_protected + report.orders_filled == 1
    assert report.errors == 0

    lines = evidence.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    persisted = json.loads(lines[0])
    assert persisted["cycle"] == 1
    assert persisted["instruments_evaluated"] == 3
    assert persisted["orders_submitted"] == 1
    assert persisted["orders_unknown"] == 0

    # The simulated broker itself confirms only one position/order was created even
    # though the remaining instruments were still evaluated after the order budget.
    orders = getattr(engine.broker, "orders")
    assert len(orders) == 1
    assert len(engine.broker.positions()) == 1
