# Fundamental and NLP Pipeline

## 1. Principle

Language models extract structured meaning and evidence; they do not predict trades directly and never produce broker commands. Numerical release data and market repricing remain first-class inputs.

## 2. Scheduled-release workflow

```text
pre-release snapshot
-> actual observed
-> official-source verification
-> surprise/revision calculation
-> market reaction window
-> currency-horizon update
-> persistence re-evaluation
```

### Surprise calculation

For indicator `i`:

```text
raw_surprise = directionality_i * (actual - consensus)
normalized_surprise = raw_surprise / robust_historical_surprise_scale_i
revision_effect = directionality_i * (revised_previous - prior_known_previous)
```

Units, seasonal adjustment, and indicator directionality are metadata, not guessed by the model.

## 3. Official-document workflow

For central-bank statements, minutes, and speeches:

1. retrieve official text and metadata;
2. compare with the prior same-document type;
3. segment into claims;
4. extract stance changes with exact evidence spans;
5. classify affected policy dimensions;
6. detect negation, uncertainty, and conditional language;
7. assign supported/ambiguous/contradictory disposition;
8. calibrate confidence against labeled history;
9. publish structured output and model/prompt version.

## 4. Required extraction schema

- document identity and authority;
- currencies and institutions;
- event type;
- policy dimensions: inflation, labor, growth, rates, balance sheet, FX, financial stability;
- stance delta per dimension;
- timeframe;
- conditions and caveats;
- evidence span offsets and text hashes;
- contradiction links;
- confidence and calibration bucket;
- abstention reason.

## 5. Prompt and model governance

- prompts are versioned artifacts;
- temperature is zero or minimum deterministic setting for extraction;
- model responses are validated against a strict schema;
- unsupported claims fail closed;
- prompts and outputs exclude secrets and account data;
- provider outage or model drift switches affected features to unavailable;
- model upgrades require offline replay and human review before shadow use.

## 6. News clustering

Use deterministic fingerprints and semantic similarity to group syndicated articles. The cluster has one event identity, multiple sources, earliest publication, authoritative-source priority, and evolving facts. Repeated copies increase source coverage, not independent evidence.

## 7. Currency vector

For each currency and horizon, store components rather than only a scalar:

- policy-rate bias;
- inflation impulse;
- labor impulse;
- growth impulse;
- risk sensitivity;
- external balance;
- terms of trade where relevant;
- positioning/repricing context;
- confidence and freshness.

Pair bias is base minus quote after horizon weighting.

## 8. Reaction versus interpretation

The engine keeps separate:

- semantic interpretation of the event;
- magnitude of release surprise;
- observed cross-asset repricing;
- immediate FX price reaction;
- later persistence.

A hawkish statement with dovish market repricing is a conflict, not a value to average away.

## 9. Evaluation dataset

The labeled dataset includes documents, prior versions, evidence spans, stance labels, ambiguity, event outcomes, and publication/receipt timestamps. Train/validation/test splits are chronological and institution-aware. Evaluation measures extraction accuracy, evidence faithfulness, calibration, abstention quality, latency, and stability across model versions.
