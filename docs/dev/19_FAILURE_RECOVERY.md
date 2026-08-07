# Failure Modes and Recovery Runbooks

## 1. Failure principle

Every dependency has an explicit failure mode. “Retry forever” is not a policy. New trading stops before uncertainty can create uncontrolled exposure.

## 2. Matrix

| Failure | New candidates | New orders | Open-position action |
|---|---|---|---|
| broker quote stale | reject affected pairs | halt | manage from broker state; consider flatten policy |
| transaction stream down | may continue shadow only | halt | poll authoritative endpoints and reconcile |
| economic calendar down | blackout event-sensitive strategies | halt affected strategies | keep existing protection |
| news feed down | disable news-required policies | no effect on non-news policies if approved | preserve thesis monitoring limits |
| futures proxy down | disable flow-required setups | halt those setups | use predefined degraded management |
| database unavailable | stop | stop | broker-native protection remains; recover state |
| event bus unavailable | stop dependent workflows | stop | reconcile after recovery |
| clock drift | stop event-driven evaluation | halt | alert and preserve protection |
| risk service unavailable | candidates may be traced | halt | no risk expansion |
| unknown broker response | no equivalent new intent | halt affected account/instrument | reconcile before retry |
| missing protection | global/account halt | halt | repair immediately or emergency close |

## 3. Provider reconnect

Reconnect uses exponential backoff with jitter and a cap. After reconnect, the adapter validates clock, requests snapshot/history from the last durable checkpoint, deduplicates, reports gaps, and only then declares healthy.

## 4. Unknown order runbook

1. mark lifecycle `UNKNOWN`;
2. block equivalent submissions;
3. query by client/provider ID;
4. fetch recent transactions and open orders/positions;
5. map any fill and create/verify protection;
6. if still unresolved, halt account and escalate;
7. never assume timeout means rejection.

## 5. Missing protection runbook

1. activate account halt;
2. obtain authoritative position;
3. attempt approved stop repair with current risk constraints;
4. if repair cannot be confirmed within the policy window, close exposure;
5. reconcile fill and P/L;
6. create severity-one incident;
7. require human release after root cause and paper regression.

## 6. Restart runbook

Processes start read-only, replay event inbox/outbox, restore checkpoints, reconcile provider state, validate protection, and compare risk book. Only an explicit readiness transition allows new orders.

## 7. Data correction

A late correction creates a new event and feature version. Historical decisions are not rewritten. Analytics may compute counterfactual impact separately.

## 8. Disaster recovery

Restore database and object manifests to an isolated environment, validate checksums, start execution/reconciliation without trading permission, query broker authority, repair state, then decide whether positions require intervention. Recovery drills occur before live promotion and periodically thereafter.
