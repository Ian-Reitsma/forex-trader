from __future__ import annotations

import json

import pytest

from scripts.assess_research_promotion import _load_replay


SETUP = "zone_continuation"
POLICY = "policy-v1"
DATASET = "dataset-v1"


def _result(*, setup: str = SETUP, policy: str = POLICY, dataset: str = DATASET) -> dict[str, object]:
    return {
        "research_only": True,
        "execution_authority": False,
        "policy_fingerprint": policy,
        "setup_family_filter": setup,
        "setup_families_observed": [setup],
        "dataset": {
            "dataset_id": dataset,
            "labeled_trades": 250,
            "train": 150,
            "validation": 50,
            "test": 50,
        },
        "untouched_test": {"all": {"expectancy_r": "0.25"}},
    }


def _write(path, payload: object) -> None:  # type: ignore[no-untyped-def]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_replay_results_are_bound_to_setup_policy_and_dataset(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write(manifest, {"git_commit": "abc", "dataset_id": DATASET})
    _write(first, _result())
    _write(second, _result())

    evidence = _load_replay(
        manifest,
        [first, second],
        expected_setup=SETUP,
        expected_policy_fingerprint=POLICY,
        expected_dataset_id=DATASET,
    )
    assert evidence is not None
    assert evidence.reproducible is True
    assert len(set(evidence.result_hashes)) == 1


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("setup", "sweep_reclaim", "setup mismatch"),
        ("policy", "other-policy", "policy fingerprint mismatch"),
        ("dataset", "other-dataset", "dataset mismatch"),
    ],
)
def test_replay_identity_mismatch_fails_closed(tmp_path, field: str, value: str, message: str) -> None:  # type: ignore[no-untyped-def]
    manifest = tmp_path / "manifest.json"
    result = tmp_path / "result.json"
    _write(manifest, {"git_commit": "abc", "dataset_id": DATASET})
    kwargs = {"setup": SETUP, "policy": POLICY, "dataset": DATASET}
    kwargs[field] = value
    _write(result, _result(**kwargs))

    with pytest.raises(SystemExit, match=message):
        _load_replay(
            manifest,
            [result],
            expected_setup=SETUP,
            expected_policy_fingerprint=POLICY,
            expected_dataset_id=DATASET,
        )


def test_replay_hash_is_canonical_across_json_key_order(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write(manifest, {"dataset_id": DATASET, "git_commit": "abc"})
    payload = _result()
    _write(first, payload)
    second.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")

    evidence = _load_replay(
        manifest,
        [first, second],
        expected_setup=SETUP,
        expected_policy_fingerprint=POLICY,
        expected_dataset_id=DATASET,
    )
    assert evidence is not None
    assert evidence.reproducible is True
