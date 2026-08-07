# v0.7.2 — Research Promotion Evidence

v0.7.2 adds a fail-closed evidence layer between offline research and any future strategy-authority discussion. It does not change OANDA Practice authority and introduces no live-money path.

## Added

- setup-family-isolated chronological research reports;
- SHA-256 identity for the exact decision/outcome evidence corpus;
- a research-promotion evidence model covering sample volume, validation Brier/ECE, untouched holdout economics, EV-selected holdout metrics, provider/evaluation error rate, controlled ablations, deterministic replay and optional paired Phase-D evidence;
- deterministic evidence-bundle digests;
- explicit `insufficient_evidence`, `rejected` and `shadow_candidate` dispositions;
- an offline `scripts/assess_research_promotion.py` assessor;
- regression coverage proving that research promotion cannot expand the machine-readable Practice authority manifest.

## Integrity hardening

A required ablation is comparable only when it references the exact primary `dataset_id`, uses the exact untouched-test sample count, and reproduces the primary full-policy untouched expectancy within the configured serialization tolerance. An ablation that materially outperforms the full policy, uses another dataset, or changes the denominator is a hard failure.

Replay reproducibility is also identity-bound. Before repeated result files are hashed, each must identify the same setup-family filter, policy fingerprint and immutable dataset ID as the primary report. Canonical JSON hashing removes formatting/key-order noise without allowing an unrelated identical report to satisfy reproducibility.

Low sample volume is deliberately not treated as a failed strategy. Missing or undersized evidence produces `insufficient_evidence`; observed bad calibration/economics/data integrity/reproducibility produces `rejected`.

## Authority boundary

The strongest possible result is `shadow_candidate`. The assessor never edits `config/system-policy-v0.7.json`, never grants Practice authority, never submits a broker order and never creates a live-money execution path.

If an entry/management change is proposed, the exact Phase-D policy must additionally survive the paired chronological development/untouched-holdout process from v0.7.1 with a positive lower confidence bound before the research bundle can be complete.

## Next research milestone

The next missing evidence layer is a prospective paired ablation collector that produces full/no-fundamentals/no-flow/no-session/no-zone-quality/no-retest outcomes on the same point-in-time signal corpus. Until those real ablation artifacts exist, the promotion bundle correctly remains `insufficient_evidence` rather than inferring component value from feature importance or aggregate P/L.
