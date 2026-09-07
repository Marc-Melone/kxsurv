# kxsurv — Market Surveillance Program for Kalshi

A market-surveillance program implementing five abuse-detection controls over
KalshiEX LLC's **public** market data, each mapped to a CFTC Designated Contract
Market Core Principle (17 CFR Part 38).

> **This is a methodology demonstration on public data.** It is not an audit of
> Kalshi, not an allegation of misconduct, and not a claim to have detected
> abuse. It uses only unauthenticated public endpoints — no API key, no
> authenticated request, no order placement, no non-public information — within
> Kalshi's published rate limits.
>
> Kalshi's public tape carries no counterparty identity. This program therefore
> **cannot** identify accounts, establish beneficial ownership, demonstrate
> coordination, or establish intent. Every output is an alert warranting
> investigation, never a finding.

## Controls

| Control | Typology detected | Core Principle |
|---|---|---|
| **C1** Pre-release informed trading | Insider trading / embargo front-running | CP 12 |
| **C2** Pre-halt price pressure | Settlement-price manipulation | CP 4 |
| **C3** Volume / open-interest divergence | Wash-trade proxy | CP 12 |
| **C4** Ladder monotonicity coherence | Price distortion across related contracts | CP 4 |
| **C5** Settlement-source integrity | Disruption of the settlement process | CP 4 |

## Results — 2026-09-07

Corpus: **408 markets** across 5 economic series, **100,494 trades**,
**248,912 candlestick periods**, 28 events.

| Stage | Count |
|---|---|
| Generated | 59 |
| Triaged | 59 |
| **Escalated** | **0** |
| No action | 45 |
| Monitor | 14 |

| Control | Generated | No action | Monitor |
|---|---|---|---|
| C1 pre-release informed trading | 4 | 4 | 0 |
| C2 pre-halt price pressure | 0 | — | — |
| C3 volume / open-interest divergence | 13 | 8 | 5 |
| C4 ladder monotonicity | 42 | 33 | 9 |
| C5 settlement-source integrity | 0 | — | — |

**Nothing was escalated.** No alert survived its documented false-positive mode
on public data with the evidence public data can supply. Every disposition
carries a written rationale; see `cases/` for worked investigation files.

> **These figures supersede an earlier run.** A self-review found two controls
> whose central computation was invalid — C4 compared strikes quoted up to 194
> hours apart, and C3's persistence requirement counted non-adjacent periods as
> consecutive. Both are corrected. See `cases/CONTROL-NOTE-C4.md` and
> **Corrections** below.

## What the run actually established

**A data-availability constraint, found by the completeness gate.** Kalshi's
public trade tape retains ~**66 days**; candlestick aggregates reach back 89 and
outlive the trades that produced them. Comparing the two over their full ranges
failed 261 of 408 markets spuriously. Reconciling from each market's first
available trade forward matches **exactly, 0.00%**. Final: **406/408 reconcile**,
2 genuine gaps blocked from scoring.

**A market-structure correction.** Kalshi's economic series are
`strike_type: "greater"` threshold ladders, not mutually exclusive partitions —
`KXCPI-26SEP` mids sum to **7.54**. A sum-to-$1 coherence check would fire on
every healthy market. The correct constraint is monotonicity.

**A ladder-pricing incoherence, once the control was fixed.** C4 now finds 42
inversions, 9 of them at 2× the combined half-spread or more, persisting across
consecutive snapshots — the largest at 5.0× on `KXCPIYOY-26NOV:4.5>4.6`. The
discriminator is spread-relative magnitude, not raw size: the two largest
inversions by magnitude closed no-action because they sit against very wide
quotes.

**A settlement-concentration risk hidden by naming.** `settlement_sources`
declares both `Bureau of Labor Statistics` and `BLS`. They are one provider. Any
concentration measure taken from the raw field is wrong. Normalised, BLS resolves
**4 of 5 series and 310 of 408 markets — 76% of the corpus** — so one provider
outage is a correlated settlement event across three quarters of these markets.

**A control deficiency, recorded rather than patched.** All four C1 alerts ranked
100th percentile, but against nulls of 5–11 samples a top rank is 8–17% likely by
chance, and the surprise-weighted scores were negligible because those markets
were already priced at 0.93–0.995. C1's alert rate is 4/77 = **5.2%** against a
95th-percentile threshold — precisely the false-positive rate of a detector
finding no signal. C1 v1.0.0 has a percentile threshold with no absolute score
floor. **Parameters were not altered after seeing these results** — a score floor
and a 20-sample null minimum are proposed for v1.1.0.

**Aggressor flow is contrarian on average.** Mean informed-flow score is negative
at every lag from the halt (−0.02 to −0.14), i.e. aggressive takers point away
from the eventual outcome. Consistent with takers paying the spread and being
largely uninformed.

## Corrections

This programme corrected itself in public rather than quietly. The commit history
carries each fix.

| Defect | Effect | Fix |
|---|---|---|
| C4 compared each strike's most recent quote independently | 12 of 28 events had strike quotes spanning >24h (worst 194h); the control reported 0 alerts and the zero was an artifact | Quotes grouped by candle period; only strikes in the same period compared |
| C3 counted "consecutive periods" over the volume-filtered list | 88 of 102 alerts violated the intended semantics; one claimed 4 consecutive periods across 863 hours | Runs now require adjacent hourly periods |
| Alert writes were not idempotent | Re-running controls doubled the table, 51 → 102 | Natural key `(control, target, window, params_hash)` with `INSERT OR IGNORE` |
| C4's alert `target` was the event alone | Several strike pairs inverting in one window collapsed, discarding 4 real alerts | `target` identifies the strike pair |
| `RELEASE_TIMES` was defined but never read | `release_time_utc` was always NULL while the docs claimed statutory-time alignment | Computed and stored; C1 records the halt-to-publication gap |
| No control had an end-to-end test | The framework claimed fixture validation that did not exist | Per-control fixture tests: plant a signature and assert it fires, plant a clean tape and assert it does not |

## Pre-registration

Every free parameter is frozen in `config/params.yaml`, hashed, and recorded in
the `params` table before any control runs. The runner refuses to execute on
drift. In research this guards against p-hacking; in surveillance it guards
against tuning thresholds until the alerts tell the story you wanted. See
`SURVEILLANCE_PLAN.md`.

## Reproducing

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q                                   # 74 tests
PYTHONPATH=src .venv/bin/python -m kxsurv.cli         # ingest + run all controls
```

`--skip-ingest` re-runs the controls against the existing database.

## Documents

| File | Contents |
|---|---|
| `SURVEILLANCE_FRAMEWORK.md` | The program document: scope, typologies, parameters and rationale, escalation matrix, data lineage, limitations |
| `SURVEILLANCE_PLAN.md` | Pre-registration — frozen parameters and why each value |
| `cases/` | Investigation case files and the C4 control-validation note |

## Limitations

1. **No counterparty identity** — the binding constraint on every control.
2. C1 rests on **9 independent information events**; no statistical claim is made.
3. C3's proxy has a measured **18–27% benign base rate**; it is a screen, not evidence.
4. C4's persistence requirement is exercised across the snapshots present in a
   single ingest; a longer collection would test it harder.
5. C5 divergence monitoring is inventory-only without an independent corroborating feed.
6. The 66-day tape horizon bounds C1 and C2 to recent markets.
7. Order-book reconstruction and spoofing/layering detection are out of scope.

## Stack

Python 3.13, stdlib `sqlite3` (WAL), `requests`, `PyYAML`, `pytest`. No numpy or
pandas — sample sizes are small and the dependency surface stays honest.
