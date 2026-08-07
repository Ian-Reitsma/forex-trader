# Contract Schemas

These YAML files are human-reviewable normative drafts for the future generated JSON Schema/OpenAPI/AsyncAPI contracts. Before implementation, convert them into machine-validated schemas without changing semantics.

Contract rules:

- all timestamps are UTC RFC 3339 strings;
- decimal market/account values serialize as strings;
- IDs are internal UUIDs unless explicitly named `provider_*`;
- unknown/unsupported states use explicit enums;
- every top-level contract has a semantic version;
- examples are synthetic.
