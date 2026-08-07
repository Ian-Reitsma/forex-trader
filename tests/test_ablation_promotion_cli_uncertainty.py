from __future__ import annotations

import json
from decimal import Decimal

from scripts.assess_research_promotion import _load_ablations


DATASET = "d" * 64


def test_promotion_loader_reads_uncertainty_fields(tmp_path) -> None:
    path = tmp_path / "ablations.json"
    path.write_text(
        json.dumps(
            {
                "ablations": [
                    {
                        "name": "no_flow",
                        "full_expectancy_r": "0.25",
                        "ablated_expectancy_r": "0.20",
                        "sample_size": 50,
                        "dataset_id": DATASET,
                        "lower_confidence_component_increment_r": "0.01",
                        "upper_confidence_component_increment_r": "0.09",
                        "paired_wins": 30,
                        "paired_losses": 15,
                        "paired_ties": 5,
                        "confidence": "0.90",
                        "bootstrap_iterations": 2000,
                        "bootstrap_seed": 20260807,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    evidence = _load_ablations(path, dataset_id=DATASET)
    assert len(evidence) == 1
    row = evidence[0]
    assert row.component_increment_r == Decimal("0.05")
    assert row.lower_confidence_component_increment_r == Decimal("0.01")
    assert row.upper_confidence_component_increment_r == Decimal("0.09")
    assert row.confidence == Decimal("0.90")
    assert row.bootstrap_iterations == 2000
    assert row.bootstrap_seed == 20260807
    assert row.uncertainty_complete is True


def test_legacy_mean_only_ablation_artifact_remains_loadable_but_has_no_uncertainty(tmp_path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "ablations": [
                    {
                        "name": "no_flow",
                        "full_expectancy_r": "0.25",
                        "ablated_expectancy_r": "0.20",
                        "sample_size": 50,
                        "dataset_id": DATASET,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    row = _load_ablations(path, dataset_id=DATASET)[0]
    assert row.uncertainty_complete is False
