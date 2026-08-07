# Acceptance-Test Matrix

## Foundation

| ID | Acceptance condition |
|---|---|
| FND-001 | Same synthetic events and config produce identical semantic decision hashes. |
| FND-002 | Domain package has no external framework/provider imports. |
| FND-003 | Invalid environment/account/secret combinations fail startup. |
| FND-004 | Duplicate event delivery changes aggregate state once. |
| FND-005 | Schema breaking change fails compatibility CI. |

## Data

| ID | Acceptance condition |
|---|---|
| DAT-001 | Bid/ask, event time, observed time, and provider are preserved. |
| DAT-002 | Stream reconnect catches up or declares a visible gap. |
| DAT-003 | Bars are unavailable before close plus watermark. |
| DAT-004 | Pre-release forecast snapshot is preserved after revisions. |
| DAT-005 | Raw payload checksum maps to every normalized record. |
| DAT-006 | Data-quality degradation disables only policies that require the feed. |

## Features and strategy

| ID | Acceptance condition |
|---|---|
| STR-001 | Zone and swing algorithms pass no-future tests. |
| STR-002 | Sweep/reclaim golden scenario produces expected transitions. |
| STR-003 | Missing confirmation produces a stable rejection code. |
| STR-004 | Fundamental conflict follows the policy declaration. |
| STR-005 | Candidate expiry blocks later risk/execution use. |
| STR-006 | Decision trace names every input and policy version. |

## Risk

| ID | Acceptance condition |
|---|---|
| RSK-001 | Approved units never exceed loss cap under stressed fill. |
| RSK-002 | Currency legs aggregate across different pairs. |
| RSK-003 | Duplicate candidates do not reserve risk twice. |
| RSK-004 | Global halt blocks authorization before acknowledgment. |
| RSK-005 | Expired or forged authorization is rejected by execution. |
| RSK-006 | Restart reconstructs open and reserved risk exactly. |

## Execution

| ID | Acceptance condition |
|---|---|
| EXE-001 | Network timeout after broker acceptance does not duplicate order. |
| EXE-002 | Fill is followed by confirmed protection within policy limit. |
| EXE-003 | Missing protection triggers repair or emergency close and halt. |
| EXE-004 | Streaming and snapshot state reconcile after restart. |
| EXE-005 | Unknown provider object halts new account orders. |
| EXE-006 | Actual spread, slippage, fees, and latency are attributed. |

## Backtest and model

| ID | Acceptance condition |
|---|---|
| BKT-001 | Future availability injection is detected. |
| BKT-002 | Same manifest reproduces same result. |
| BKT-003 | Base and stressed cost results are reported. |
| BKT-004 | Walk-forward and untouched holdout are enforced. |
| NLP-001 | Every extracted stance claim has evidence or abstains. |
| NLP-002 | Prompt-injection corpus cannot cause tool/order behavior. |
| NLP-003 | Model upgrade passes replay, calibration, and stability gates. |

## Operations and security

| ID | Acceptance condition |
|---|---|
| OPS-001 | Provider outage produces documented degraded mode. |
| OPS-002 | Restore drill reconciles broker state before trading readiness. |
| OPS-003 | Every sensitive control mutation is audited. |
| SEC-001 | Non-live roles cannot access live broker secret. |
| SEC-002 | Live activation requires separate environment and two approvals. |
| SEC-003 | Logs/traces contain no seeded canary secret. |
