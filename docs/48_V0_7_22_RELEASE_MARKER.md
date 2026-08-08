# v0.7.22 Release Marker

Implementation identity: `0.7.22`

Release scope: sealed chronological semantic calibration/holdout infrastructure for the blinded central-bank annotation workflow.

Verified GitHub base for this release: `b9a98bf87809366c793b88e4074d2f440cadfac2` (`main`, merged PR #35).

The prior v0.7.19 annotation workflow was merged while the package runtime identity remained `0.7.18`. This release advances the authoritative package/runtime identity directly to `0.7.22`; it does not assert that runtime releases `0.7.20` or `0.7.21` existed or were deployed.

v0.7.22 adds:

- immutable source-batch-bound semantic holdout manifests;
- fixed chronological first-two-thirds calibration / final-one-third holdout partitioning;
- normal annotation-batch exports for each partition;
- complete-source reconstruction before partition finalization;
- cross-partition, incomplete, cherry-picked, tampered, or source-drifted evidence rejection;
- partition-specific audit lineage;
- direct Ruff, strict-mypy, and focused regression coverage in `Annotation integrity`.

v0.7.22 intentionally does **not** add:

- a semantic acceptance threshold;
- a real human-reviewed calibration or holdout corpus;
- a claim that v0.7.15 stance extraction is semantically valid;
- runtime fundamental weighting from central-bank stance;
- strategy or risk-policy changes;
- new OANDA Practice authority;
- broker writes;
- live-money authority;
- any profitability claim.

Authority remains:

```text
research_only = true
execution_authority = false
live_money_enabled = false
```

The next semantic evidence step is operational rather than another synthetic success claim: produce independent human calibration labels under the frozen annotation policy, evaluate calibration only, predeclare semantic acceptance criteria, freeze those criteria and evaluator identity, and only then open/finalize the holdout truth for one independent test.
