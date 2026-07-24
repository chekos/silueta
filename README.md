# silueta

**Profile the shape of your data — never the values.**

silueta turns a dataset — CSV, Parquet, and soon multi-tab Excel and databases — into a compact, machine-readable profile of its *shape*: types, nulls, cardinality, value-shape masks, semantic PII/PHI flags, and red-flag anomalies. The profile contains **no raw cell values, by construction**, so an AI agent (or a teammate, or a ticket) can work from it safely.

The motivating workflow: you get a vendor workbook full of PII/PHI and need to model it — dbt sources, Snowflake landing tables, relationships. Most of what modeling needs is *how the data behaves*, not what it says. silueta captures the behavior so an agent like Claude Code can scaffold the models for data it is never allowed to read.

```console
$ uvx silueta scan patients.csv --report report.md
wrote profile.json
wrote report.md
  patients: 30 rows, 7 columns, 2 alerts
```

The profile tells the agent things like:

- `mrn` — VARCHAR, 100% unique, mask `AAA-999999` → this is your key
- `ssn` — matches SSN structure at 100% with plausibility checks → **sensitive, alert**
- `amount` — typed as text but 100% castable numeric, magnitude 10^2 → DECIMAL, fix at landing
- `clinic` — constant column (and that is *all* it says about it)
- `visit_date` — dates spanning 2025 (year granularity only)

## The contract

A silueta profile never contains:

- raw cell values, sample rows, or frequent-value lists
- min/max for strings or dates (those *are* raw values) — numerics report order-of-magnitude and precision facts, dates report year spans
- serialized sketches or value hashes (hashing is not anonymization)
- any statistic derived from values observed in fewer than *k* rows (default 5); constant columns report nothing but their constancy

This contract is enforced by [tests](tests/test_contract.py) that scan every output for source values, and it travels inside the artifact itself (`profile.json → silueta.contract`).

**What it is and is not:** silueta protects against *accidental context leakage* — values ending up in an LLM conversation, a log, a pasted ticket. It does not claim formal anonymity (differential privacy) against an adversary reconstructing small populations from aggregates. The wording is "no raw values by construction," never "anonymized."

## Status

Early alpha — CSV and Parquet profiling work today. On deck (see issues): messy-Excel header/type recovery (the headline feature), cross-table foreign-key candidates via exact containment, dbt/Snowflake scaffold emitters, database connections.

## Install

```console
uvx silueta            # zero-install run
uv tool install silueta
pipx install silueta
```

## License

MIT
