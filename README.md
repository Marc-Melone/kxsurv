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

## Current status

**v1.1.0 is a corrective release, not prospective validation.** It changes
control mechanics after an adversarial review of v1.0.0: C1 now weights each
trade at its execution price, C2 requires flow/price direction to agree, C3
requires a directly preceding hourly candle for its open-interest delta, and
execution records are run-scoped. Re-analysis of the saved 2026-09-07 database
is a regression check against known data. The first newly ingested run after
explicit v1.1 registration is the prospective evaluation.

The database is deliberately excluded from Git. A fresh clone can run the
tests and create a **new** public-API measurement, but it cannot reproduce a
dated result table from this repository alone. Public endpoints are mutable and
the retained trade tape changes over time.

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
| Generated | 58 |
| Triaged | 58 |
| Escalated | 0 |
| No action | 43 |
| Monitor | 15 |

| Control | Generated | No action | Monitor |
|---|---:|---:|---:|
| C1 pre-release informed flow | 3 | 3 | 0 |
| C2 pre-halt price pressure | 0 | — | — |
| C3 volume / open-interest divergence | 12 | 7 | 5 |
| C4 ladder monotonicity | 42 | 33 | 9 |
| C5 settlement-source integrity | 1 | 0 | 1 |

These historical dispositions remain part of the audit trail. They are not
automatically carried into a v1.1 run because alerts, evidence, and
dispositions are scoped to an execution record.

## v1.1 re-analysis of the saved snapshot

Using the corrected v1.1 controls against that same saved database produces
**58 candidates**. They are intentionally shown without a funnel or
dispositions: a v1.1 run requires fresh analyst triage.

| Control | Generated candidates | v1.1 disposition |
|---|---:|---|
| C1 | 3 | Untriaged |
| C2 | 0 | — |
| C3 | 12 | Untriaged |
| C4 | 42 | Untriaged |
| C5 | 1 | Untriaged |
| **Total** | **58** | **Untriaged** |

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

## What the saved snapshot shows

- **C1 is a limited screen, not a statistical claim.** It has nine independent
  information events. C1 discounts each trade by the probability already
  implied by that trade's execution price, not by one opening quote. It cannot
  separate superior public-information processing from non-public information.

- **C2 now measures directionally coherent pressure.** A candidate requires
  signed YES-side aggressor flow and the signed change in YES execution price to
  agree, in addition to imbalance, displacement, and thinness.

- **C3 is deliberately non-specific.** In the two cited samples, flat open
  interest occurred in 26.0% (44/169) and 16.2% (12/74) of contiguous,
  volume-bearing hourly observations. That is an observed signature frequency,
  not a non-specific signature rate or evidence of wash trading. Of 9,793 scoreable C3
  observations, 480 clear the percentile gate and 12 survive persistence. The
  control's `coverage()` summary emits the first two counts from the same
  population used for alerting.

- **C4 detects price incoherence, not participant conduct.** The corrected
  method finds 42 persistent ladder inversions in the saved snapshot. Their
  v1.1 disposition is deliberately unreported until re-triaged.

- **C5 identifies an operational metadata issue.** `Bureau of Labor Statistics`
  and `BLS` form an acronym candidate corroborated by the shared declared domain
  `www.bls.gov`. The normalized, set-union count is 4 of 5 series and 310 of
  408 markets (76%). This is a declared-source concentration dependency, not a
  finding about trading conduct or an independently verified provider identity.

## Corrective-release record

The project retains its v1.0 correction history rather than silently rewriting
it. v1.1 adds the following material changes:

| Issue | v1.1 treatment |
|---|---|
| Routine execution auto-registered parameters | Registration is explicit; a version may map to only one parameter hash. |
| C1 used one start-of-window quote for all trade surprise | Surprise is computed at each execution price. |
| C2 ignored the sign of the price move | Signed flow must align with signed YES-price movement. |
| C3 could calculate an hourly delta across a missing hour | A divergence observation requires an immediate 3,600-second predecessor. |
| Re-ingestion could leave stale alert evidence under one natural key | Alerts are unique within an immutable run; later runs retain separate evidence. |
| Missing/deprecated trade direction could be coerced into NO flow | `taker_outcome_side` is canonical and invalid directions fail closed. |
| C5 relied on acronym matching and summed normalized coverage | Candidate aliases require one declared source domain; normalized counts use set unions. |

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

`--skip-ingest` evaluates the currently stored data and creates a new run
record only when the snapshot is marked ready. The CLI marks a refresh
`refreshing` before public-API writes and `failed` if that refresh aborts, so a
partial ingestion cannot be silently evaluated with `--skip-ingest`. It is
useful for controlled re-analysis of a local database; it does not recover the
unavailable historical snapshot in a fresh clone.

## Documents

| File | Contents |
|---|---|
| `SURVEILLANCE_FRAMEWORK.md` | Current v1.1 methodology, governance, lineage, and limitations |
| `SURVEILLANCE_PLAN.md` | v1.1 parameter-registration record and threshold rationale |
| `cases/` | Historical v1.0 investigation records; not v1.1 dispositions |
| `docs/superpowers/` | Archived v1.0 design and implementation material, not operating documentation |

## Limitations

1. No counterparty identity — the binding constraint on participant-conduct screens.
2. C1 has nine independent information events and makes no population-level claim.
3. C3 observes aggregate volume and open interest, not beneficial ownership.
4. C4 currently scopes to `strike_type = "greater"` ladders.
5. C5 has no independent corroborating reference-data feed and does not perform
   settlement-value divergence monitoring.
6. The public trade-tape retention horizon limits C1 and C2.
7. Order-book reconstruction, spoofing, layering, and account-level linkage are out of scope.

## Stack

Python 3.13, stdlib `sqlite3` (WAL), `requests`, PyYAML, and pytest.
