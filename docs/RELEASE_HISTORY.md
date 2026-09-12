# Release and validation history

The records below describe the published baseline at source commit `6b11825`
and the development history retained at `687457c`. They do not report the
results of the later reliability update.

## 2026-09-11 reliability update

- Exact integer microseconds replace text ordering in C1/C2 trade windows.
- Required numeric observations reject missing, malformed, non-finite, and
  out-of-range values; valid zero-volume candles and missing quotes remain valid.
- Exports require matching snapshot inputs and parameters. Code drift suppresses
  recomputed coverage. Reads share one SQLite transaction.
- The viewer reports closed and monitored cases separately.
- Fixed acquisition intervals, a future-evaluation manifest, and a repeatable
  public-tape case supplement make later review reproducible.

Detection parameters remain at `1.1.0`; the source and input fingerprints identify
these implementation changes. Existing databases gain an indexed
`created_time_us` column, which is included in new input fingerprints. Preserve
an original database copy before migration when retaining its old fingerprint is
necessary. Previously published JSON remains a historical record; a migrated
database needs a new run before export.

## Original v1.1 validation posture

**v1.1.0 is a corrective release, not prospective validation.** It changes
control mechanics after adversarial review: C1 now weights each trade at its
execution price and requires a known publication time, C2 requires flow/price
direction to agree, C3 requires a directly preceding hourly candle for its
open-interest delta, C4 uses decimal-safe quoted-price boundaries, and execution
records are run-scoped. Re-analysis of the saved
2026-09-07 database is a regression check against known data. A separate
three-series challenge corpus exposed further defects and became remediation
data; it is not independent validation of the corrected code. Prospective
evaluation requires data not used to design or correct that release.

The databases are deliberately excluded from Git. A fresh clone can reproduce
the tests and pipeline mechanics and can create a **new** public-API measurement,
but it cannot re-derive a dated result table from raw data in this repository
alone. Public data evolve, the live/historical partition cutoff moves, and a new
ingest may produce different coverage and alert counts.

Exact historical counts therefore ship as a **published snapshot artifact**:
`site/data/` holds the derived results of the current run — alerts, evidence,
dispositions, coverage and provenance — identified by its parameter, input and
code fingerprints and its source commit. Raw trades, candles and market rows
remain gitignored; only derived results are published. The exporter refuses to
write an artifact for any run that is not `complete`, so a published table
cannot describe an unfinished or failed run.

Current ingestion follows Kalshi's documented
[live/historical data partition](https://docs.kalshi.com/getting_started/historical_data):
it unions the live and historical market lists, routes each market's candles to
the appropriate tier, and merges both trade tiers by trade ID. It fails closed
on incomplete pagination, conflicting cross-tier records, or malformed required
candle fields.

## Historical v1.0.0 snapshot

The following is the **legacy v1.0.0** run over the local 2026-09-07 snapshot,
not the current v1.1 result. Its corpus contained 408 markets across five
economic series, 100,494 trades, 248,912 candlestick periods, and 28 events.

| Stage | Count |
|---|---:|
| Generated | 60 |
| Triaged | 60 |
| Escalated | 0 |
| No action | 45 |
| Monitor | 15 |

| Control | Generated | No action | Monitor |
|---|---:|---:|---:|
| C1 pre-release informed flow | 4 | 4 | 0 |
| C2 pre-halt price pressure | 0 | — | — |
| C3 volume / open-interest divergence | 13 | 8 | 5 |
| C4 ladder monotonicity | 42 | 33 | 9 |
| C5 settlement-source integrity | 1 | 0 | 1 |

These historical dispositions remain part of the audit trail. They are not
automatically carried into a v1.1 run because alerts, evidence, and
dispositions are scoped to an execution record.

## Original corrective-release record

The project retains its v1.0 correction history rather than silently rewriting
it. v1.1 adds the following material changes:

| Issue | v1.1 treatment |
|---|---|
| Routine execution auto-registered parameters | Registration is explicit; a version may map to only one parameter hash. |
| C1 used one start-of-window quote for all trade surprise | Surprise is computed at each execution price. |
| C2 ignored the sign of the price move | Signed flow must align with signed YES-price movement. |
| C3 could calculate an hourly delta across a missing hour | A divergence observation requires an immediate 3,600-second predecessor. |
| C1 treated any close time as a scheduled release | Events without a publication time materialized from the source-coded schedule are explicitly out of scope. |
| C4 admitted non-threshold contracts and floating-point boundary artifacts | Only `greater` strikes enter a ladder; quoted-price comparisons use decimal-safe boundaries. |
| Re-ingestion could leave stale alert evidence under one natural key | Alerts are unique within an immutable run; later runs retain separate evidence. |
| Fresh acquisition covered only the live market/candle tier | Market lists are unioned across tiers and archived candles use the historical endpoint. |
| Repeated ingestion accumulated prior detector inputs | A refresh generation replaces the raw snapshot before rebuilding it. |
| Missing/deprecated trade direction could be coerced into NO flow | `taker_outcome_side` is canonical and invalid directions fail closed. |
| C5 relied on acronym matching and summed normalized coverage | Every candidate name must declare the same single valid hostname; normalized counts use set unions. |
