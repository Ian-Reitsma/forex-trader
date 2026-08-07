# ADR 0009 — LLMs Perform Structured Extraction Only

## Status
Accepted

## Decision
Language models may extract and classify news or official documents with evidence. They may not call broker tools, bypass gates, size trades, or emit order intents.

## Rationale
This preserves auditability and limits prompt injection, hallucination, and model drift risk.

## Consequences
All outputs use strict schemas, evidence spans, calibration, and abstention. Strategy consumes typed assessments.
