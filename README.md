# kxsurv — Market Surveillance Program for Kalshi

A market-surveillance methodology implementing five screening controls over
KalshiEX LLC's **public** market data, each mapped to a CFTC Designated Contract
Market Core Principle (17 CFR Part 38).

> **This is a methodology demonstration on public data.** It is not an audit of
> Kalshi, an allegation of misconduct, or a claim to have detected abuse. It
> uses unauthenticated public endpoints only: no API key, authenticated request,
> order placement, or non-public information.
>
> Kalshi's public tape carries no counterparty identity. The program cannot
> identify accounts, establish beneficial ownership, demonstrate coordination,
> or establish intent. A participant-facing output is therefore an alert
> warranting investigation, never a finding.

## Published results

**[Live results viewer → marc-melone.github.io/kxsurv](https://marc-melone.github.io/kxsurv/)**

The complete triaged output of the current saved-snapshot run: every alert with
its evidence and written disposition, the screened-population coverage for each
control, and the run's parameter, input and code fingerprints. The viewer is a
static page and read-only by construction — it cannot start a run, reach
Kalshi's API, or record a disposition.

## Current status

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

## Controls

| Control | Screening purpose | Core Principle |
|---|---|---|
| **C1** Pre-release informed flow | Pre-release information screen | CP 12 |
| **C2** Pre-halt price pressure | Directionally aligned, thin-market pressure screen | CP 4 |
| **C3** Volume / open-interest divergence | Wash-trade screening proxy | CP 12 |
| **C4** Ladder monotonicity coherence | Price-quality screen across related contracts | CP 4 |
| **C5** Settlement-source integrity | Settlement metadata and resolution-consistency screen | CP 4 |

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

## v1.1 re-analysis of the saved snapshot

Applying all current corrective boundaries to that same saved database produces
**30 candidates**, all reviewed: 14 no-action, 16 monitor, and 0 escalated. Each
row carries a written rationale scoped to this run; no disposition is inherited
from an earlier run by database linkage. The 28 C4 rows removed by the
monetary-boundary correction had all previously been disposed `no_action`, so no
C4 monitor decision was silently discarded.

Every figure in the table below is rendered from the same exported record the
[results viewer](https://marc-melone.github.io/kxsurv/) serves, so the published
numbers and the published artifact cannot disagree.

| Control | Generated | No action | Monitor | Escalated |
|---|---:|---:|---:|---:|
| C1 | 3 | 2 | 1 | 0 |
| C2 | 0 | — | — | — |
| C3 | 12 | 7 | 5 | 0 |
| C4 | 14 | 5 | 9 | 0 |
| C5 | 1 | 0 | 1 | 0 |
| **Total** | **30** | **14** | **16** | **0** |

C1 scores 69 of 408 markets in this saved snapshot: 276 lack a settlement
label, 61 fall below the volume floor, and 2 have too small a null population.
Its **3/69 = 4.35% observed candidate rate** is not a false-positive-rate
estimate. With small, discrete null populations, a 95th-percentile result is
often simply the maximum rank.

Each completed run records its parameter hash, deterministic fingerprints of
the stored detector inputs and detector code, timestamps, status, and
run-scoped alert rows. It also records every control execution, including a
zero-alert result, so a silent control is not mistaken for an unrun one. This
prevents a later re-ingest from silently replacing earlier alert evidence. It
does **not** preserve a full source-data or source code snapshot; a published
result should also name its source commit or release tag.

The current saved-snapshot record is run 8 at source commit `2772000` (5/5 controls
complete), code fingerprint `760839ab76ada33a0db862be242dbf69324dc9429e2d82235142cf81e936c82e`. Its
full fingerprints and timestamps are retained in `out/saved-snapshot.log`, which
is generated from the run record rather than written by hand, and the complete
run is published at `site/data/run-8.json`. The identified database remains
gitignored.

## What the saved snapshot shows

- **C1 is a limited screen, not a statistical claim.** Its 132 settled markets
  belong to nine settled ladders representing five distinct scheduled releases;
  ladders sharing a publication are not independent. Events without a publication
  time materialized from the source-coded schedule are out of scope. C1 discounts
  each trade by the probability already implied by that trade's execution price,
  not by one opening quote. It cannot separate superior public-information
  processing from non-public information.

- **C2 now measures directionally coherent pressure.** A candidate requires
  signed YES-side aggressor flow and the signed change in YES execution price to
  agree, in addition to imbalance, displacement, and thinness.

- **C3 is deliberately non-specific.** In the two cited samples, flat open
  interest occurred in 26.0% (44/169) and 16.2% (12/74) of contiguous,
  volume-bearing hourly observations. That is an observed non-specific signature
  frequency, not a measured benign base rate or evidence of wash trading. Of
  9,793 scoreable C3 observations, 480 clear the percentile gate and 12 survive
  persistence. The control's `coverage()` summary emits the first two counts
  from the same population used for alerting.

- **C4 screens for period-aligned quote-close incoherence, not participant
  conduct.** The corrected method finds 14 persistent ladder inversions in the
  saved snapshot. Decimal-safe quote comparisons ensure that values equal to
  the combined half-spread do not pass because of binary floating-point
  representation. Shared hourly candle endpoints do not establish when each
  market's quote last changed within the period, so these are not proof of an
  exactly simultaneous, executable inconsistency.

- **C5 flags a candidate operational metadata issue.** `Bureau of Labor
  Statistics` and `BLS` form an acronym candidate corroborated by the shared
  declared domain `www.bls.gov`. Grouping the candidate names produces a
  set-union coverage of 4 of 5 series and 310 of 408 markets (76%). That is a
  conditional concentration scenario pending identity confirmation, not a
  finding about trading conduct or a verified provider identity.

## Corrective-release record

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

## Parameter registration and running the program

Every free parameter is versioned in `config/params.yaml`. Register a version
explicitly before controls execute; changing that canonical configuration
requires a version bump and a new registration row.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
PYTHONPATH=src .venv/bin/python -m kxsurv.cli --register-params
PYTHONPATH=src .venv/bin/python -m kxsurv.cli
```

To render the published results locally, serve the `site/` directory and open
the address it prints:

```bash
python3 -m http.server --directory site
```

`--skip-ingest` evaluates the currently stored data and creates a new run
record only when the snapshot is marked ready. A full ingest claims a refresh
generation, clears the prior detector-input tables, retains markets whose close
is within or after the 90-day observation window, and retrieves trades and
candles inside that window. The CLI marks an interrupted refresh `failed`, so
neither a partial replacement nor an additive stale cache can be silently
evaluated with `--skip-ingest`. The option is useful for controlled re-analysis
of a local database; it does not recover the unavailable historical snapshot in
a fresh clone.

## Documents

| File | Contents |
|---|---|
| `SURVEILLANCE_FRAMEWORK.md` | Current v1.1 methodology, governance, lineage, and limitations |
| `SURVEILLANCE_PLAN.md` | v1.1 parameter-registration record and threshold rationale |
| `cases/` | Selected analyst records from the saved-snapshot corrective run |
| `site/` | Static results viewer and the published run artifact it renders |

## Limitations

1. No counterparty identity — the binding constraint on participant-conduct screens.
2. C1 has five distinct scheduled releases represented by nine settled ladders
   and makes no population-level claim.
3. C3 observes aggregate volume and open interest, not beneficial ownership.
4. C4 currently scopes to `strike_type = "greater"` ladders.
5. C5 has no independent corroborating reference-data feed and does not perform
   settlement-value divergence monitoring.
6. The saved snapshot's live-tier-only trade acquisition limits C1 and C2;
   current ingestion covers Kalshi's live/historical market, candle, and trade
   partitions.
7. Order-book reconstruction, spoofing, layering, and account-level linkage are out of scope.

## Stack

Python 3.13, stdlib `sqlite3` (WAL), `requests`, PyYAML, and pytest.
