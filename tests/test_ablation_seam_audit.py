from __future__ import annotations

from pathlib import Path

import pytest

from forex_trader.research.seam_audit import (
    COMPONENT_PATTERNS,
    assert_required_seams,
    audit_production_seams,
    top_seams,
)


def test_repository_has_production_candidates_for_every_required_ablation_component() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "forex_trader"
    candidates = audit_production_seams(root)
    assert_required_seams(candidates)
    observed = {item.component for item in candidates}
    assert observed == set(COMPONENT_PATTERNS)
    assert all(not item.module.startswith("research") for item in candidates)


def test_top_seams_is_deterministic_and_bounded() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "forex_trader"
    first = top_seams(audit_production_seams(root), per_component=3)
    second = top_seams(audit_production_seams(root), per_component=3)
    assert first == second
    assert set(first) == set(COMPONENT_PATTERNS)
    assert all(len(values) <= 3 for values in first.values())


def test_research_directory_cannot_satisfy_production_seam_audit(tmp_path) -> None:
    root = tmp_path / "forex_trader"
    research = root / "research"
    research.mkdir(parents=True)
    (research / "fake.py").write_text(
        "def fake(fundamental, flow, session, zone_quality, retest):\n"
        "    return fundamental, flow, session, zone_quality, retest\n",
        encoding="utf-8",
    )
    assert audit_production_seams(root) == ()
    with pytest.raises(ValueError, match="found no candidates"):
        assert_required_seams(())


def test_unknown_component_and_invalid_limit_fail_closed(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown ablation components"):
        audit_production_seams(tmp_path, components=("fundamentals", "imaginary"))
    with pytest.raises(ValueError, match="per_component must be positive"):
        top_seams((), per_component=0)
