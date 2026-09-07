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
| Generated | 55 |
| Triaged | 55 |
| **Escalated** | **0** |
| No action | 51 |
| Monitor | 4 |

**Nothing was escalated, and that is the honest result** — no alert survived its
documented false-positive mode on public data. Every disposition carries a
written rationale. See `cases/` for worked investigation files.

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

**A control that earns its filter.** C4's spread test suppressed **16** candidate
inversions, all sitting inside the combined half-spread of adjacent strikes —
quote staleness, not distortion. Zero false escalations. See
`cases/CONTROL-NOTE-C4.md`.

**A settlement-concentration risk hidden by naming.** `settlement_sources`
declares both `Bureau of Labor Statistics` and `BLS`. They are one provider. Any
concentration measure taken from the raw field is wrong. Normalised, BLS resolves
**4 of 5 series and 310 of 408 markets — 76% of the corpus** — so one provider
outage is a correlated settlement event across three quarters of these markets.

**A control deficiency, recorded rather than patched.** All four C1 alerts ranked
100th percentile, but against nulls of 5–11 samples a top rank is 8–17% likely by
chance, and the surprise-weighted scores were negligible because those markets
were already priced at 0.93–0.995. C1 v1.0.0 has a percentile threshold with no
absolute score floor. **Parameters were not altered after seeing these results** —
a score floor and a 20-sample null minimum are proposed for v1.1.0.

## Pre-registration

Every free parameter is frozen in `config/params.yaml`, hashed, and recorded in
the `params` table before any control runs. The runner refuses to execute on
drift. In research this guards against p-hacking; in surveillance it guards
against tuning thresholds until the alerts tell the story you wanted. See
`SURVEILLANCE_PLAN.md`.

## Reproducing

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q                                   # 59 tests
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
4. C4 evaluates a single snapshot; the persistence requirement is untested.
5. C5 divergence monitoring is inventory-only without an independent corroborating feed.
6. The 66-day tape horizon bounds C1 and C2 to recent markets.
7. Order-book reconstruction and spoofing/layering detection are out of scope.

## Stack

Python 3.13, stdlib `sqlite3` (WAL), `requests`, `PyYAML`, `pytest`. No numpy or
pandas — sample sizes are small and the dependency surface stays honest.
