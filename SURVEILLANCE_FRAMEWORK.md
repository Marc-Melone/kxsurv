# kxsurv — Surveillance Program Framework

**Version 1.0.0 · 2026-09-07**

---

## 1. Scope and posture

`kxsurv` implements five market-abuse detection controls over the public market
data of KalshiEX LLC, a CFTC-designated contract market. Each control is mapped
to a DCM Core Principle, carries pre-registered parameters, and feeds a triage
queue with recorded dispositions.

**This is a methodology demonstration on public data.** It is not an audit of
Kalshi, not an allegation of misconduct, and not a claim to have detected abuse.

**Data accessed:** unauthenticated public endpoints only — `/markets`,
`/events`, `/series`, `/markets/trades`, `/series/{s}/markets/{m}/candlesticks`.
No API key is held, no authenticated request is sent, no order is placed, and no
non-public information is accessed. Kalshi's published Basic-tier rate limits
(200 read tokens/sec, 10 tokens per request) are respected with a 10 req/s cap
and bounded exponential backoff on HTTP 429 and 5xx.

## 2. The counterparty-identity limitation

Kalshi's public tape does not carry counterparty identity. This is a hard
boundary on what the data can support, not an engineering gap.

`kxsurv` **cannot** identify or link accounts, establish common beneficial
ownership, demonstrate coordination between participants, establish intent, or
conclude that abuse occurred.

Every control therefore produces **alerts warranting investigation, never
findings**. Any alert surviving triage carries fixed escalation language:
*"escalated — resolution requires account-level data held only by the exchange."*

## 3. Regulatory framing

KalshiEX LLC was designated a contract market by the CFTC in November 2020,
placing it alongside CME and ICE as a DCM subject to the Core Principles at
17 CFR Part 38, with acceptable-practices guidance at Appendix B.

| Control | Typology | Core Principle |
|---|---|---|
| C1 Pre-release informed trading | Insider trading / embargo front-running | CP 12 — Protection of Markets and Market Participants |
| C2 Pre-halt price pressure | Settlement-price manipulation | CP 4 — Prevention of Market Disruption |
| C3 Volume / open-interest divergence | Wash-trade proxy | CP 12 |
| C4 Ladder monotonicity coherence | Price distortion across related contracts | CP 4 |
| C5 Settlement-source integrity | Disruption of the settlement process | CP 4 |

## 4. Data lineage and integrity

**Corpus (2026-09-07):** 408 markets across 5 series, 100,494 trades, 248,912
candlestick periods, 28 events. SQLite (WAL), 51.7 MB.

**Tape-completeness assertion.** Conclusions drawn on a truncated tape are
worthless, so every market's tape volume is reconciled against the independent
candlestick endpoint before it may be scored.

**Retention horizon — measured, and it drove a correction.** Kalshi's public
trade tape retains approximately **66 days** (earliest available trade
2026-07-03 as of 2026-09-07). Candlestick aggregates reach back **89 days** and
outlive the individual trade records that produced them.

A naive full-range comparison failed **261 of 408 markets**. Reconciling only
from each market's first available trade forward matches **exactly — 0.00%
divergence** on every market tested. Final state: **406 of 408 reconcile**; the
2 genuine gaps are blocked from scoring.

| Coverage | Markets | Controls available |
|---|---|---|
| Tape present | 396 | C1, C2, C3, C4 |
| Beyond tape horizon (candles only) | 11 | C3 |
| Failed reconciliation (blocked) | 2 | none |

**Guarantees.** Raw tables are append-only and idempotent on primary key.
Detectors are pure functions of stored data, so a run reproduces from the
database alone. Every alert stores pointers to the trades or candle periods that
produced it.

## 5. Controls

### C1 — Pre-release informed trading (CP 12)

Kalshi halts economic-release markets before the print: `KXCPI-26JUL` closes at
12:25:00Z, five minutes ahead of the BLS 08:30 ET publication. C1 asks whether
that window is adequate.

The naive metric is wrong — a trade at $0.99 on the eventual winner is
consensus, not information. C1 scores size-weighted directional correctness
discounted by surprise, `1 - p_0`, against a null of the market's own earlier
windows.

**Aggressor derivation, validated not assumed:** `taker_side == "yes"` means the
aggressor bought YES. Confirmed on `KXCPI-26JUL-T0.3` (686 trades, `result='no'`,
0.250 → 0.010) where signed volume agreed with realised price direction in 5/5
sequential blocks.

**Sample size:** 9 independent information events. C1 makes **no
population-level statistical claim** and is validated by fixture detection
behaviour and analyst triage.

**Statutory release times** are computed from the halt date and the source's
fixed Eastern publication time, and stored per event; C1 records the
halt-to-publication gap in every alert. For BLS series that gap is 5 minutes.

**Empirical observations.** C1's alert rate is 4/77 = **5.2%** against a
95th-percentile threshold — the false-positive rate expected of a detector
finding no signal. Mean informed-flow score is **negative at every lag** from the
halt (−0.02 to −0.14): aggressive takers point away from the eventual outcome on
average, consistent with takers paying the spread and being largely uninformed. A
hypothesis that the pre-halt window would score systematically highest through
convergence was tested and **rejected** (lag 0 mean −0.029 vs lag 8 mean −0.021).

**False-positive mode:** cannot distinguish superior processing of public
information from misuse of non-public information.

### C2 — Pre-halt price pressure (CP 4)

One-sided aggressor imbalance, price displacement, and market thinness must
co-occur; each alone is unremarkable. **False-positive mode:** late public
information and ordinary position-squaring into a halt.

### C3 — Volume / open-interest divergence (CP 12)

A trade between a new buyer and new seller raises open interest; a trade where
the same beneficial owner sits on both sides generates volume while leaving it
unchanged.

**Measured base rate:** flat open interest despite volume occurs in **27%** of
volume-bearing candles on `KXCPI-26JUL-T0.3` and **18%** on
`KXPAYROLLS-26AUG-T60000`. This signature is common, not exceptional.

**False-positive mode — dominant:** open interest also stays flat when one
participant closes while an unrelated participant opens. `D` is a **screening
proxy, never evidence**, and its reliability *falls* as liquidity rises.
Percentiles are therefore ranked within liquidity tier, with a volume floor and
a persistence requirement.

**Corrected 2026-09-07.** Persistence was counted over the volume-filtered list
rather than over time, so candles far apart counted as consecutive: **88 of 102
alerts** violated the intended semantics, one claiming 4 consecutive periods
across **863 hours**. Runs now require adjacent hourly periods (measured modal
candle spacing 3600s). C3 fell from 51 alerts to **13**, all genuinely adjacent.

### C4 — Ladder monotonicity coherence (CP 4)

Kalshi's economic series are `strike_type: "greater"` threshold ladders — nested
cumulative contracts, **not** mutually exclusive partitions. `KXCPI-26SEP` mids
sum to 7.54, so a sum-to-$1 constraint would fire on every healthy market. The
correct constraint is monotonicity: `P(X > k₁) ≥ P(X > k₂) ≥ … ≥ P(X > kₙ)`.

**Corrected 2026-09-07 — the control was previously non-functional.** The first
implementation took each strike's most recent quote independently. Across 28
events, 12 had strike quotes spanning more than 24 hours (worst: **194 hours**),
so the control compared a strike quoted eight days ago against one quoted an hour
ago. It reported **0 alerts**, and that zero was an artifact, not a clean result.

Quotes are now grouped by candle period and only strikes present in the same
period are compared, which also makes `min_persistence_snapshots` operative for
the first time. **C4 now finds 42 inversions**, 9 at ≥2× the combined
half-spread, the largest at 5.0×.

**False-positive mode — dominant:** wide two-sided quoting in adjacent strikes.
The discriminator is **spread-relative** magnitude: the two largest inversions by
raw size (0.2250) sit against half-spreads of ~0.20 and closed no-action, while a
0.095 inversion against a 0.025 half-spread is retained. Full account in
`cases/CONTROL-NOTE-C4.md`.

### C5 — Settlement-source integrity (CP 4)

Kalshi markets resolve against external reference data, and Core Principle 4
covers disruption of the settlement process. `GET /series/{ticker}` exposes
`settlement_sources` as `{name, url}`.

**Concentration finding.** As declared:

| Source (as declared) | Series | Markets |
|---|---|---|
| Bureau of Labor Statistics | 3 | 239 |
| Federal Reserve Board of Governors | 1 | 98 |
| BLS | 1 | 71 |

**`Bureau of Labor Statistics` and `BLS` are the same provider under two names.**
The declared inventory therefore *understates* concentration. Normalised, BLS
resolves **4 of 5 series and 310 of 408 markets — 76% of the corpus**.

A single provider outage, embargo failure, or methodology change is a
**correlated settlement event across three quarters of these markets**. Naming
inconsistency in settlement metadata is itself a reference-data control gap: any
concentration measure computed from the raw field is wrong.

## 6. Alert handling

**Disposition vocabulary:** `no_action`, `monitor`, `escalated`. A rationale is
mandatory and enforced in code — a disposition without one raises.

**Escalation matrix.** Escalate only where the alert survives its documented
false-positive mode on the available evidence. Where the dominant innocent
explanation remains unfalsified on public data, the correct disposition is
`no_action` or `monitor`. Escalating past that overstates what the evidence
supports.

**Expected outcome: mostly no-action.** Real surveillance is overwhelmingly
false positives. A programme reporting *"55 alerts, 51 closed benign, here is the
reasoning for each"* demonstrates better judgement than one claiming detections.

## 7. Results — 2026-09-07 run

These figures **supersede an earlier run** whose C3 and C4 results were produced
by defective controls (see the correction notes in §5 and `cases/`).

| Stage | Count |
|---|---|
| Generated | 59 |
| Triaged | 59 |
| Escalated | **0** |
| No action | 45 |
| Monitor | 14 |
| Untriaged | 0 |

| Control | Generated | No action | Monitor | Escalated |
|---|---|---|---|---|
| C1 | 4 | 4 | 0 | 0 |
| C2 | 0 | — | — | — |
| C3 | 13 | 8 | 5 | 0 |
| C4 | 42 | 33 | 9 | 0 |
| C5 | 0 | — | — | — |

**Nothing was escalated, and that is the honest result.** No alert survived its
documented false-positive mode on public data.

**A control deficiency was recorded rather than patched.** All four C1 alerts
ranked at the 100th percentile, but on null populations of 5–11 samples a top
rank is 8–17% likely by chance, and the surprise-weighted scores were negligible
(0.0029–0.0696) because those markets were already priced at 0.93–0.995. C1
v1.0.0 applies a percentile threshold with **no absolute score floor** and only a
3-sample minimum null.

Parameters are frozen under pre-registration and **were not altered after seeing
these results**. A score floor and a 20-sample null minimum are proposed for
v1.1.0. This is the pre-registration mechanism working as designed: the finding
is a documented deficiency, not a retuned threshold that would have made the
alerts disappear.

## 8. Review cadence

Controls re-run per ingest. C4's persistence requirement needs repeated
snapshots and cannot be exercised from a single collection. C1's sample grows
only as Kalshi settles further events, bounded by the 66-day tape horizon.

## 9. Known limitations

1. No counterparty identity — the binding constraint on every control.
2. C1 rests on 9 independent events; no statistical claim is made.
3. C3's proxy has an 18–27% benign base rate.
4. C4's persistence is exercised only across the snapshots contained in one
   ingest; a longer collection would test it harder.
5. C5 divergence monitoring is inventory-only without an independent corroborating feed.
6. The 66-day tape horizon bounds C1 and C2 to recent markets.
7. Order-book reconstruction, spoofing and layering detection are out of scope.
8. **A null result is not self-validating.** C4 returned zero for a defective
   reason and the zero was initially reported as a clean result. Every control
   now carries end-to-end fixture tests — plant a signature and assert it fires,
   plant a matched clean tape and assert it does not — because a silent control
   and a working one are indistinguishable from output alone.
