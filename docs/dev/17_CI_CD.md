# CI, Release, and Promotion

## 1. Pull-request pipeline

1. documentation and link validation;
2. schema compatibility checks;
3. formatting and linting;
4. strict type checking;
5. unit/property tests;
6. architecture dependency tests;
7. migration tests;
8. contract tests with fixtures;
9. deterministic replay smoke test;
10. dependency, secret, license, and container scans;
11. build reproducible artifact and software bill of materials.

## 2. Main-branch pipeline

- build signed immutable image;
- publish schemas and documentation artifact;
- run full replay regression suite;
- deploy automatically to research/shadow only;
- require approval for paper;
- prohibit automatic live deployment.

## 3. Versioning

The platform uses semantic versions. Contracts, strategy policies, risk policies, models, datasets, and infrastructure have independent versions referenced by each decision trace.

## 4. Environment promotion

```text
research -> shadow -> paper -> limited-live
```

Promotion moves an immutable artifact and approved configuration; it does not rebuild. Each gate checks the acceptance matrix and open incidents.

## 5. Database release

Use expand/migrate/contract. Application versions declare compatible schema ranges. Migrations run as a controlled job before process rollout. Paper/live migrations require backup verification and rollback or forward-fix procedure.

## 6. Rollback

Rollback reactivates a previous image/config but does not erase new events. Execution compatibility with currently open orders and positions is verified before rollback. If incompatible, the system remains halted and operators follow a position-management runbook.

## 7. Supply-chain controls

- dependency hashes locked;
- signed commits/tags where configured;
- protected main branch;
- required review from risk owner for risk changes;
- generated SBOM;
- vulnerability thresholds;
- provenance attestation;
- no mutable container tags in deployment.

## 8. Release evidence

A release record includes commit, image digest, schemas, migrations, config versions, test reports, replay regression, security scan, approvers, deployment time, and rollback target.
