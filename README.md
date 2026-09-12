# kxsurv — Public Prediction-Market Surveillance

Five screening controls over public Kalshi data, with a Python/SQL ingestion
pipeline, evidence records, analyst dispositions, and a results viewer.
The published snapshot covers **408 markets, 100,494 trades, and 248,912 hourly
candles** across five economic series.

**[View results](https://marc-melone.github.io/kxsurv/) ·
[Read a featured investigation](cases/CASE-0637.md) ·
[Inspect its seven trades](cases/CASE-0637-TAPE.md)**

> An independent methodology demonstration using public data. Screening
> candidates warrant review; public data cannot establish participant identity,
> beneficial ownership, coordination, or intent. No account credentials or order
> placement are involved.

## Published result

**30 candidates reviewed: 14 closed, 16 retained for monitoring, 0 escalated.**
This is run 8, a re-analysis of the saved 2026-09-07 snapshot at source commit
`6b11825`. It is a published baseline, not a measurement of the newer reliability
changes or an independently validated detection rate.

| Control | Generated | No action | Monitor | Escalated |
|---|---:|---:|---:|---:|
| C1 | 3 | 2 | 1 | 0 |
| C2 | 0 | — | — | — |
| C3 | 12 | 7 | 5 | 0 |
| C4 | 14 | 5 | 9 | 0 |
| C5 | 1 | 0 | 1 | 0 |
| **Total** | **30** | **14** | **16** | **0** |

The table agrees with [the published run artifact](site/data/run-8.json).
C1 scored **69 of 408** markets. Its 3/69 candidate rate is descriptive, not a
false-positive estimate. C3 had **9,793 scoreable** observations; 480 passed its
percentile gate before 12 persistent sequences became candidates.

## Featured investigation: pre-release payroll flow

[CASE-0637](cases/CASE-0637.md) examines seven trades totaling 212.18 contracts
before a payroll publication. The execution-price-weighted C1 score was 0.3450,
above all 16 non-empty comparison windows. The disposition is **monitor**:
public nowcasting and thin-market execution remain plausible explanations.

A [fresh public-tape retrieval](cases/CASE-0637-TAPE.md) reproduced the published
trade count, volume, score, comparison count, and percentile. It shows each
trade's contribution and all 20 comparison intervals, including four empty
ones. A single 90-contract YES trade at $0.34 accounts for about 81% of the net
score, making its execution context central to follow-up. This retrieval checks
one case's summary; it does not reconstruct the original full database.

## Controls and workflow

| Control | Question screened | Regulatory framing |
|---|---|---|
| C1 — Pre-release informed flow | Did aggressive flow anticipate the outcome from prices that did not already imply it? | DCM Core Principle 12 |
| C2 — Pre-halt price pressure | Did one-sided flow and price movement align in a thin market before its halt? | DCM Core Principle 4 |
| C3 — Volume / open-interest divergence | Did unusually high turnover relative to net OI change persist? | DCM Core Principle 12 |
| C4 — Ladder monotonicity | Did related threshold contracts show a persistent inversion beyond their combined half-spread? | DCM Core Principle 4 |
| C5 — Settlement metadata | Are source declarations or settled threshold-ladder outcomes inconsistent? | DCM Core Principle 4 |

1. Retrieve live and historical public markets, trades, and hourly candles.
2. Validate inputs and reconcile trade volume against the candle endpoint.
3. Register parameters and run controls against a fingerprinted snapshot.
4. Review evidence, alternative explanations, and follow-up needs.
5. Publish run-specific candidates and dispositions in a static viewer.

The framework discusses how the controls map to 17 CFR Part 38. A mapping does
not establish a regulatory breach.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
PYTHONPATH=src .venv/bin/python -m kxsurv.cli --register-params
PYTHONPATH=src .venv/bin/python -m kxsurv.cli
```

The default command acquires a rolling 90-day snapshot. To request a fixed,
completed interval, use `--start` and `--end` together, aligned to UTC hours:

```bash
PYTHONPATH=src .venv/bin/python -m kxsurv.cli --register-params --db out/fixed.db
PYTHONPATH=src .venv/bin/python -m kxsurv.cli --db out/fixed.db \
  --start 2026-09-08T00:00:00Z --end 2026-09-11T00:00:00Z
```

The client defaults to Kalshi's recommended production endpoint. Its documented
[compatibility endpoint](https://docs.kalshi.com/getting_started/api_environments)
can be selected before a run if the default host is unavailable:

```bash
export KXSURV_API_BASE=https://api.elections.kalshi.com/trade-api/v2
```

To view the already published baseline locally:

```bash
python3 -m http.server --directory site
```

To regenerate the featured case supplement from the public API:

```bash
PYTHONPATH=src .venv/bin/python -m kxsurv.case_evidence \
  --alert 697 --output out/CASE-0637-TAPE.md
```

## Reliability and reproducibility

- C1/C2 compare exact integer UTC microseconds, including fractional seconds and
  equivalent offset representations. Original timestamp text is retained.
- Required prices, sizes, volume, and OI reject invalid values rather than
  silently converting them to zero.
- Each run records input, parameter, and code fingerprints. Alerts and
  dispositions retain their history across later runs.
- Exporting an old run against different inputs or parameters is rejected.
  Coverage is omitted when the current code differs from the run's code.
- Full raw datasets remain excluded from Git. Preserve each evaluation database;
  fingerprints identify inputs but cannot restore them. Selected public trade
  observations appear in the featured case supplement.

`--skip-ingest` creates a new run from a ready local snapshot. It cannot recover
an absent historical database. A full ingest replaces raw input tables, so use
separate databases for retained evaluations. The timestamp migration adds a
hashed input column; old runs remain available in their published JSON, and a
migrated database needs a new run to export with the corrected code.

## Evaluation and limitations

The saved snapshot and the three-series development challenge informed code
corrections. Neither demonstrates prospective performance. The new
[frozen evaluation workflow](EVALUATION.md) records the code, parameters,
environment, series, and a future interval before data collection. It refuses
changed configurations and collection before that interval finishes. No
prospective result is claimed yet.

C1's baseline contains five distinct publication times; contracts sharing a
release are dependent. C3 cannot distinguish ordinary position transfer from
common-owner trading. C4 compares hourly quote closes and cannot prove exact
simultaneity or executability. C5 has no independent settlement-value feed.
Order-book reconstruction, spoofing, layering, and account-level linkage are
outside this project's scope.

## Further reading

| Document | Contents |
|---|---|
| [Surveillance framework](SURVEILLANCE_FRAMEWORK.md) | Control mechanics, governance, lineage, and limitations |
| [Parameter plan](SURVEILLANCE_PLAN.md) | Registered thresholds and their rationale |
| [Case studies](cases/) | Evidence, alternatives, and analyst decisions |
| [Evaluation protocol](EVALUATION.md) | Freeze, acquire, retain, and review a later dataset |
| [Release history](docs/RELEASE_HISTORY.md) | Original results and disclosed corrective work |

Python, stdlib SQLite (WAL), requests, PyYAML, and pytest. CI runs on Python 3.13.
