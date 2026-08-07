# Deployment Architecture

## 1. Initial deployment target

Use containers on a single well-managed host or small container platform for research/shadow. Keep interfaces portable to Kubernetes, but do not require Kubernetes before operational complexity warrants it.

Local and first shared environment:

- Docker/Podman Compose;
- PostgreSQL + TimescaleDB;
- NATS JetStream;
- MinIO or cloud S3;
- OpenTelemetry Collector;
- Prometheus-compatible metrics and dashboard stack;
- process-role containers from one image.

## 2. Environment separation

- separate projects/accounts/namespaces for research, shadow, paper, and live;
- separate broker accounts and secrets;
- separate event subjects or NATS accounts;
- separate database credentials and preferably instances for live;
- separate object prefixes and encryption keys;
- separate operator roles.

## 3. High availability by phase

### Shadow

Single instance per role is acceptable with automatic restart and no order risk.

### Paper

Durable bus/database, execution singleton, reconciliation worker, tested restart, and backup are required.

### Limited live

- redundant infrastructure for database/bus as justified;
- execution leader election or explicit singleton failover;
- external uptime and clock monitoring;
- independent emergency access to broker;
- tested restore and credential rotation;
- deployment freeze around high-risk events unless explicitly approved.

## 4. Secrets

Use cloud secret manager, Vault, or OS-secure store. Mount or inject secrets only to the role that needs them. Never bake into images or environment dumps. Broker write credentials are not present in the control API, strategy, risk, or research roles.

## 5. Networking

Default-deny inbound. Only control API and dashboards are reachable through authenticated ingress. Egress allowlists restrict providers and broker. Database, bus, and object store remain private.

## 6. Time synchronization

Hosts use reliable NTP/chrony and expose offset metrics. Event-driven strategy readiness fails when drift exceeds policy. Container time is never independently modified.

## 7. Capacity and upgrades

Capacity planning uses measured event rates, retention, replay demand, and trace volume. Rolling upgrades are allowed for read-only roles. Execution/risk upgrades require compatibility checks, state handoff, or a controlled halt.

## 8. Operator access

No direct production database editing. Break-glass access is time-limited, audited, and cannot be the normal control path. Broker-native UI remains available for emergency verification and intervention.
