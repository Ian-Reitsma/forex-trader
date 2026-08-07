# 11 — Security and Compliance

## 1. Security principles

- least privilege;
- environment separation;
- no secrets in source control;
- immutable audit records;
- explicit live-trading approval;
- dependency and image scanning;
- controlled network egress;
- rapid credential revocation;
- licensed use of market and news data.

## 2. Secrets

Store broker, data-provider, and model credentials in a managed secret store. Requirements:

- practice and live keys separated;
- live key accessible only to execution service;
- read-only keys for research where possible;
- rotation;
- access logging;
- no secrets in logs;
- no secrets in notebooks;
- no copying production tokens into developer machines.

## 3. Account controls

- allowlisted account IDs;
- allowlisted instruments;
- maximum order size enforced both in risk and adapter;
- order-rate limits;
- environment banner and mode assertion;
- live mode requires explicit configuration plus operator activation;
- optional hardware-backed approval for production changes.

## 4. Service identity

Each service receives only required permissions:

- ingestion can write events but not orders;
- strategy can emit candidates but not call broker;
- risk can authorize intent but not alter market data;
- execution can call broker but cannot change strategy weights;
- reporting is read-only.

## 5. Supply chain

- pinned dependencies;
- lockfiles;
- vulnerability scanning;
- signed artifacts;
- protected main branch;
- reviewed changes;
- build provenance;
- rollback artifacts;
- minimal runtime images.

## 6. Data licensing

Market depth, futures data, news, and economic feeds may restrict storage, redistribution, derived data, and display. Before implementation:

- document provider terms;
- distinguish personal from commercial use;
- define retention;
- restrict raw-feed access;
- prevent unlicensed public redistribution;
- track derived-data obligations;
- budget for production licenses.

## 7. Regulatory boundary

The project is initially for the owner’s own account. Before managing external capital, copying trades, selling signals, or offering the system to others, obtain jurisdiction-specific legal advice. Requirements can change based on location, instrument type, customer relationship, and compensation.

## 8. Audit trail

Retain:

- code/config versions;
- deployment approvals;
- model approvals;
- decision traces;
- order and fill events;
- risk-state changes;
- manual actions;
- credential changes;
- incidents;
- data-source versions.

Audit records must be tamper-evident.

## 9. Disaster recovery

- encrypted backups;
- tested restore;
- defined recovery point and time objectives;
- broker truth used for live-position recovery;
- recovery starts halted;
- operator verifies positions before re-enable.

## 10. Threat scenarios

- stolen broker token;
- malicious dependency;
- compromised news source;
- injected false event;
- replayed order request;
- duplicated message;
- insider configuration change;
- public repository secret leak;
- denial of service;
- time synchronization attack.

Each scenario must map to preventive, detective, and recovery controls.
