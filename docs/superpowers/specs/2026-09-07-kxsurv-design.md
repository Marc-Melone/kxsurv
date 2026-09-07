# kxsurv — Market Surveillance Program for Kalshi

**Design document — 2026-09-07**
**Status:** archived v1.0.0 design record; superseded for operation by v1.1.0

> **Archive notice:** this document captures the pre-v1.1 design and contains
> obsolete algorithms, including C1's single-`p0` weighting and the original C5
> independent-feed scope. It is retained as development history, not as current
> surveillance methodology. Read `README.md`, `SURVEILLANCE_FRAMEWORK.md`, and
> `SURVEILLANCE_PLAN.md` for the current public description.

---

## 1. Purpose and posture

`kxsurv` is a market-surveillance program built against Kalshi's public market-data
API. It implements five abuse-detection controls, each mapped to a recognized market-
abuse typology and to a CFTC Designated Contract Market Core Principle, and it
produces the artifacts a real surveillance function produces: an alert queue, a
documented triage funnel, and written investigation case files.

**What this is:** a methodology demonstration on public data.

**What this is not:** an audit of Kalshi, an allegation of misconduct, or a claim to
have detected abuse. The program has no access to non-public information.

### 1.1 The counterparty-identity limitation

Kalshi's public tape does not include counterparty identity. This is not a gap to be
engineered around; it is a hard boundary on what the data can support.

Consequently `kxsurv` **cannot**:

- identify or link accounts,
- establish common beneficial ownership,
- demonstrate coordination between participants,
- establish intent, or
- conclude that abuse occurred.

Every control therefore produces *alerts warranting investigation*, never findings.
Any alert that survives triage dispositions as **escalated — resolution requires
account-level data held only by the exchange.** This limitation is stated in the
README, in the framework document, and in a dedicated section of every case file.

Stating the boundary precisely is itself a deliverable. Knowing what your data can
and cannot prove is the substance of surveillance work.

---

## 2. Regulatory framing

**KalshiEX LLC** was designated a contract market by the CFTC in November 2020 (CFTC
Order of Designation; press release 8302-20), placing it alongside CME and ICE as a
DCM. It is therefore subject to the DCM Core Principles codified at 17 CFR Part 38, with acceptable-practices guidance at
Appendix B to Part 38. Two are directly load-bearing here:

- **Core Principle 4 — Prevention of Market Disruption.** Requires methods and
  resources appropriate to the market's structure to detect trade-practice and market
  abuses and to discipline such behavior. Covers manipulation, price distortion, and
  disruption of the settlement process.
- **Core Principle 12 — Protection of Markets and Market Participants.** Requires
  rules promoting fair and equitable trading and protecting participants from
  fraudulent, noncompetitive, or unfair actions.

Controls are mapped to Core Principles in §3. The mapping is the organizing principle
of the framework document, not decoration: it is how an exchange's surveillance
program is actually structured and reviewed.

**Verification obligation.** Citations here were drawn from eCFR and Cornell LII.
Before relying on them in an interview or written submission, read Appendix B to Part
38 directly and confirm each mapping.

---

## 3. The five controls

| ID | Control | Typology | Primary evidence | Core Principle |
|----|---------|----------|------------------|----------------|
| C1 | Pre-release informed trading | Insider trading / embargo front-running | Trade tape vs. statutory release time | CP 12 |
| C2 | Pre-halt price pressure | Settlement-price manipulation ("marking the close") | Trade tape + `close_time` | CP 4 |
| C3 | Volume / open-interest divergence | Wash-trade proxy | `volume_fp` vs `open_interest_fp` | CP 12 |
| C4 | Ladder monotonicity coherence | Price distortion across related contracts | All strikes within an event | CP 4 |
| C5 | Settlement-source integrity | Disruption of the settlement process | Primary vs. corroborating reference data | CP 4 |

All five controls are in scope. **Priority revised 2026-09-07 after measuring available
sample sizes.**

- **C3 and C4 are the workhorses.** Both apply to every market on the exchange —
  candles exist per market per period, and every threshold ladder is scorable. They
  generate the alert volume that makes a triage funnel meaningful.
- **C1 is the marquee control, not the statistical backbone.** Highest regulatory
  salience, but `n = 9` events. Carried on fixture validation and analyst triage.
- **C5 is cheap and distinctive** — the settlement-source inventory is close to free
  given the metadata, and nothing else in the portfolio resembles it.
- **C2 is general-purpose** and applies wherever `close_time` exists.

Should time compress, the degradation order is **C2 → C5 → C1**, with C3 and C4
protected on sample-size grounds. Documentation quality is never traded for control count —
two controls with excellent framework and case files beat five with thin write-ups.

### C1 — Pre-release informed trading

**Universe.** Settled markets in `KXCPI`, `KXCPIYOY`, `KXPAYROLLS`, `KXU3`, `KXFED`.

**Structure.** These markets halt before their release. Observed: `KXCPI-26JUL`
brackets carry `close_time` of `2026-08-12T12:25:00Z` — 08:25 ET, five minutes ahead
of the BLS 08:30 ET publication. The halt is an existing exchange control; C1 asks
whether the window is adequate, not whether it exists.

**Definitions.** For event `E` with mutually exclusive brackets `B1..Bn`:

- `T_halt` = `close_time` (per market metadata)
- `T_pub` = statutory publication time (BLS 08:30 ET; FOMC 14:00 ET)
- Pre-halt window `W = [T_halt - L, T_halt]`, where `L` is a pre-registered
  parameter (§6); default 120 min
- Outcome: the bracket that settled YES

**Metric — Informed Flow Score.** The naive formulation ("did pre-release flow predict
the outcome") is wrong, because a trade at $0.99 on the eventual winner is consensus,
not information. The informed signature is aggressive flow toward the eventual outcome
*from a price level that did not already imply it*.

For each trade `t` in `W`:

- **aggressor direction** `d(t) ∈ {+1, -1}`. The tape exposes three related fields —
  `taker_side`, `taker_outcome_side`, and `taker_book_side`. Observed samples show
  `taker_side` and `taker_outcome_side` agreeing, with `taker_book_side` varying
  independently (`bid`/`ask`). Derivation rule: `d(t) = +1` when the aggressor's
  outcome side matches the side that ultimately settled YES, else `-1`.
- **`p_0`** = midpoint of best bid and best ask at window open, taken from the candle
  covering `T_halt - 120min`; falls back to last trade price when no two-sided quote
  exists. `surprise(t) = 1 - p_0`.
- contribution = `count_fp(t) × d(t) × surprise(t)`

**Field semantics — RESOLVED 2026-09-07.** This was a blocking prerequisite, since an
inverted derivation flips every C1 conclusion. Validated empirically on
`KXCPI-26JUL-T0.3` (686 trades, `result='no'`, price 0.250 → 0.010) by partitioning the
tape into sequential blocks and correlating signed `taker_side` volume against realized
price movement:

**`taker_side == "yes"` means the aggressor bought YES.** Positive imbalance accompanies
rising price, negative accompanies falling. Agreement was 5/5 blocks, including a
−12,605 contract imbalance against a 0.250 → 0.200 move. The derivation in §3/C1 stands
as written. Re-run this validation if Kalshi changes its tape schema.

`IFS(E) = Σ contributions / Σ count_fp`, i.e. size-weighted directional correctness
discounted by how much the price already knew.

**Null distribution.** For each market, compute `IFS` over `K` earlier same-duration
windows in that market's own history (`K` pre-registered, §6; default 20). The alert statistic is the pre-halt window's
percentile rank against its own market's null. This controls for markets that simply
drift toward their outcome.

**Alert.** `IFS` percentile exceeds the frozen threshold (§6) and window volume clears
a materiality floor.

**Sample size — measured 2026-09-07, and it constrains the claim.** Kalshi's API
retains only the most recent settled events per series. Across all five economic
series: **132 settled markets but only 9 distinct information events** (KXCPI 3,
KXCPIYOY 2, KXPAYROLLS 2, KXU3 2, KXFED 1 — deep pagination returns no more). Brackets
within an event are not independent: all resolve off one release, so the effective
`n` is 9, not 132.

Pre-halt flow in the active brackets is thin but real — measured 7–24 trades and
roughly 1,900–2,900 contracts in the two-hour pre-halt window, with deep out-of-money
brackets showing zero.

**Consequence: C1 makes no population-level statistical claim, and the spec forbids
presenting one.** Nine events cannot support a p-value about informed trading on
Kalshi. C1 is instead validated the way exchange controls actually are:

1. it fires on planted signatures in synthetic fixtures (§7),
2. it does not fire on matched clean fixtures,
3. its real-data output is triaged by an analyst and dispositioned.

This is the correct validation strategy for a surveillance control regardless of
sample size — a control is judged by detection behavior and false-positive rate, not
by a population effect estimate. The `n = 9` figure is stated plainly in the README,
the framework document, and every C1 case file.

**Known false-positive mode.** Legitimate forecasting — nowcast models, private
survey data, skilled analysis of already-public inputs — produces the same signature.
C1 cannot distinguish superior public-information processing from misuse of non-public
information. This is the central limitation and belongs in every C1 case file.

### C2 — Pre-halt price pressure

Final `N` minutes before `close_time` (`N` pre-registered, §6). Metric combines one-sided aggressor imbalance
with realized price displacement, scaled by market thinness (recent volume and
displayed depth). Alerts require imbalance, displacement, *and* thinness together —
each alone is unremarkable.

**Known false-positive mode.** Genuine late information arrival, and ordinary
position-squaring ahead of a halt.

### C3 — Volume / open-interest divergence

**Mechanism.** Kalshi's candlestick endpoint returns `volume_fp` and
`open_interest_fp` per period. A trade between a new buyer and a new seller raises
open interest. A trade closing both sides lowers it. A trade where the same beneficial
owner sits on both sides generates volume while leaving open interest unchanged.

For each candle: `ΔOI = open_interest_fp(t) - open_interest_fp(t-1)`, divergence
`D = volume_fp / (|ΔOI| + ε)`. Alert on high `D` with material volume.

**Measured base rate — 2026-09-07.** Flat open interest despite non-zero volume is
common, not exceptional:

| Market | Candles w/ volume > 0 | OI moved | OI flat | Flat rate |
|--------|----------------------|----------|---------|-----------|
| `KXCPI-26JUL-T0.3` | 170 | 124 | 46 | **27%** |
| `KXPAYROLLS-26AUG-T60000` | 102 | 84 | 18 | **18%** |

Open interest otherwise tracks volume tightly (`vol=2867 → ΔOI=+2850`;
`vol=13 → ΔOI=+13`), so the mechanism is sound — but a raw flat-OI trigger would alert
on roughly a fifth to a quarter of all active candles.

**Known false-positive mode — dominant.** Open interest also stays flat when one
participant closes while an unrelated participant opens an equal position. In liquid
two-sided markets this is ordinary position transfer.

**Threshold design consequence.** `D` alone is unusable. Alerts require, jointly: a
volume floor well above the median candle, `D` above a percentile computed **within
liquidity tier** rather than globally, and persistence across consecutive periods. `D`
is a screening proxy, never evidence, and every C3 case file states the measured base
rate so a reader can calibrate how much weight the alert carries.

### C4 — Ladder monotonicity coherence

**Market structure — corrected 2026-09-07.** An earlier draft modeled Kalshi events as
mutually exclusive partitions summing to $1. That is wrong for the economic series and
would have fired on every healthy market. Verified empirically: `KXCPI-26SEP` mids sum
to **7.54**, because these are `strike_type: "greater"` threshold ladders — nested,
cumulative contracts ("Will CPI rise more than −0.4%", "more than −0.3%", …), not a
partition.

**The correct constraint is monotonicity.** For a `greater` ladder with ascending
strikes `k_1 < k_2 < … < k_n`, implied probabilities must be non-increasing:

```
P(X > k_1) ≥ P(X > k_2) ≥ … ≥ P(X > k_n)
```

An inversion is an unambiguous pricing incoherence, internally arbitrageable, and
requires no view on fair value to identify.

**Empirical base rate (2026-09-07 snapshot).**

| Event | Strikes | Inversions |
|-------|---------|-----------|
| `KXCPI-26SEP` | 11 | 0 |
| `KXU3-26SEP` | 14 | 0 |
| `KXPAYROLLS-26SEP` | 13 | 1 (strike 50,000 @ $0.5350 below strike 60,000 @ $0.5450) |

One inversion in 38 strikes. A low base rate is exactly what a usable control needs.

**Metric.** Per event snapshot: count of inversions, magnitude of the largest, its
duration across snapshots, and whether volume accompanied it. Persistence and
accompanying volume separate a real distortion from a stale quote.

**Known false-positive mode — dominant.** A 1¢ inversion sitting inside the bid-ask
spread of two adjacent strikes carries no economic content; it is quote staleness. The
observed `KXPAYROLLS` case is almost certainly this, and it becomes the project's
worked no-action case file. Alerts require inversion magnitude to exceed the combined
half-spread of the two strikes, and to persist across consecutive snapshots.

**Structural note.** Kalshi also runs genuine mutually exclusive events elsewhere.
Control logic branches on `strike_type`: `greater` ladders are scored for monotonicity;
true partitions are scored for sum-to-$1 deviation.

### C5 — Settlement-source integrity

Kalshi markets resolve against external reference data. A source that is unavailable,
delayed, revised after publication, or inconsistent with corroborating sources creates
settlement risk — expressly within Core Principle 4's concern for disruption of the
settlement process.

**Metadata support — confirmed 2026-09-07, stronger than assumed.** Settlement sources
are exposed programmatically. `GET /series/{ticker}` returns a `settlement_sources`
array of `{name, url}` — e.g. `KXCPI` → `[{"name": "Bureau of Labor Statistics",
"url": "https://www.bls.gov/cpi/"}]`. Market metadata adds `rules_primary`,
`rules_secondary`, `expiration_value`, `expiration_time`, and
`settlement_timer_seconds`.

v1 scope, in two parts:

1. **Settlement-source inventory.** Enumerate every series and its declared settlement
   source into a table: source name, URL, series count, market count, category. This
   surfaces **source concentration risk** — how much of the exchange's open interest
   resolves against a single external provider. An outage or methodology change at one
   provider is a correlated settlement event across every market it resolves. This is a
   compliance artifact in its own right and is cheap to produce.
2. **Divergence monitoring.** For markets with a primary source and an independent
   corroborating source, compare the settlement-relevant value and flag divergence,
   post-publication revision, or source unavailability during the resolution window.

Alerts from C5 are operational settlement-risk events rather than participant-conduct
alerts, and route to a separate disposition track.

---

## 3.6 Data integrity and API-usage compliance

**Tape completeness — verified 2026-09-07.** Surveillance conclusions are worthless on
a truncated tape, so completeness was cross-validated against an independent endpoint.
Exhaustive cursor pagination of `KXCPI-26JUL-T0.3` returned 686 trades totalling
63,794.88 contracts; the candlestick endpoint independently reports 64,494.38 for the
same market. **Divergence 1.08%**, attributable to window-boundary effects. No
truncation, no pagination cap. This check runs as an ingestion assertion per market,
and a divergence beyond tolerance blocks that market from scoring.

**API-usage compliance.** `kxsurv` uses only unauthenticated public market-data
endpoints, which Kalshi's developer documentation designates as the intended path for
market data. The program holds no API key, sends no authenticated request, places no
order, and accesses no non-public information. Documented rate limits (Basic tier: 200
read tokens/sec, 10 tokens per request) are respected, with HTTP 429 handled by bounded
exponential backoff per Kalshi's published guidance.

This is recorded because the project analyses a venue's markets for signs of abuse.
The posture must be unimpeachable and stated plainly rather than assumed.

---

## 4. Architecture

Single shared ingester feeding five independent detectors over one SQLite database
(WAL mode). Detectors read; they never write to raw tables.

```
Kalshi public API
   /markets  /events  /series  /markets/trades  /…/candlesticks
        │
        ▼
   ingest/          immutable raw capture (trades, candles, market metadata)
        │
        ▼
   events/          release calendar: statutory publication times, halt times, outcomes
        │
        ▼
   controls/        C1 … C5, each: score → null → threshold → alert rows
        │
        ▼
   triage/          alert queue, disposition records, funnel statistics
        │
        ▼
   report/          framework doc, case files, summary tables
```

Each control is a separate module exposing one interface (`score(event) -> Alert |
None`) so controls can be added, tuned, or disabled without touching the others.

### 4.1 Schema

| Table | Purpose |
|-------|---------|
| `trades` | Raw tape, immutable. `trade_id` PK. |
| `candles` | Per-period `volume_fp`, `open_interest_fp`, bid/ask. |
| `markets` | Market metadata: tickers, `close_time`, status, result. |
| `events` | Event-level: series, statutory release time, halt time, outcome ticker. |
| `alerts` | `control_id`, target, window, score, percentile, threshold, status. |
| `dispositions` | `alert_id`, action, rationale, timestamp. Append-only. |
| `params` | Frozen thresholds, version, `registered_at`, content hash. |

### 4.2 Data flow guarantees

- Raw tables are append-only; re-ingestion is idempotent on primary key.
- Detectors are pure functions of stored data — a run is reproducible from the DB
  alone.
- Every alert stores pointers to the specific `trade_id`s or candle periods that
  produced it, so a case file can be reconstructed from evidence rather than memory.

---

## 5. Triage and case files

The alert queue is not the deliverable. The **funnel** is:

```
N generated → M triaged → K escalated → J closed no-action (with documented reasons)
```

Real surveillance is overwhelmingly false positives. A program reporting *"37 alerts,
34 closed as benign, here is the reasoning for each"* demonstrates better judgment
than one claiming detections. The expected and acceptable result of this project is
mostly no-action dispositions.

**Case file format** (one per escalated or otherwise instructive alert):

1. Summary
2. Timeline of relevant activity
3. Evidence (specific trades, candles, price levels)
4. **Alternative innocent explanations** — mandatory section
5. Limitations — what public data cannot establish here
6. Disposition and rationale

No case file states a conclusion about misconduct. Escalation language is fixed:
*"escalated — resolution requires account-level data held only by the exchange."*

---

## 6. Pre-registration

Thresholds, windows, and null models are fixed in `SURVEILLANCE_PLAN.md` **before any
detector runs**, and recorded in the `params` table with a content hash and
`registered_at` timestamp. This covers every free parameter named in §3 — C1's `L`,
`K`, percentile threshold and volume floor; C2's `N`, imbalance, displacement and
thinness cutoffs; C3's divergence threshold per liquidity tier and volume floor; C4's
deviation threshold and spread filter; C5's divergence tolerance. No parameter may be
introduced at runtime.

The runner refuses to execute if the live parameter set does not match a registered
hash without an explicit version bump. The discipline is mechanical, not merely
documented.

**Rationale.** In research this guards against p-hacking. In surveillance it guards
against something worse: tuning thresholds until the alerts tell the story you wanted.
A surveillance program whose parameters move after seeing outcomes is not a control.

---

## 7. Testing

- **Unit:** aggressor-direction derivation from `taker_side`/`taker_book_side`;
  `ΔOI` computation across period boundaries; surprise weighting at the `p_0 → 1`
  boundary; complement-sum arithmetic.
- **Synthetic fixtures:** hand-built tapes containing a known planted signature per
  control, asserting the control fires; and matched clean tapes asserting it does not.
- **Idempotence:** re-ingesting the same window produces no duplicate rows.
- **Reproducibility:** two runs over a frozen DB produce identical alert sets.

Synthetic fixtures matter more than usual here — real labeled abuse is unavailable, so
planted signatures are the only way to demonstrate a control detects what it claims.

---

## 8. Deliverables

1. `kxsurv/` — ingester, five controls, triage, SQLite store, tests.
2. `SURVEILLANCE_FRAMEWORK.md` — scope, typologies, per-control parameters and
   threshold rationale, escalation matrix, disposition codes, review cadence, data
   lineage, limitations.
3. `SURVEILLANCE_PLAN.md` — frozen pre-registration.
4. Investigation case files — 2–3, standard format.
5. `README.md` — posture statement, Core Principle mapping, funnel results,
   reproduction instructions.

---

## 8.1 Build sequencing

The documents carry more hiring value than the code, and a naive build order writes
them last — so a time overrun destroys the most valuable artifact. Sequencing is
therefore inverted:

1. `SURVEILLANCE_PLAN.md` — pre-registration. Required before any detector runs (§6),
   so this is genuinely first, not merely first by preference.
2. `SURVEILLANCE_FRAMEWORK.md` — drafted **before** the controls are built, from the
   design already settled here. Typologies, Core Principle mapping, parameters and
   rationale, escalation matrix, disposition codes, limitations.
3. Ingester and schema, with the completeness assertion of §3.6.
4. C3 and C4 — the workhorses.
5. C1, C2, C5.
6. Case files and funnel statistics, written against whatever controls landed.

A run that stops after step 4 still yields a complete surveillance framework with two
working, documented controls and real triage output. That is a better artifact than
five controls with thin documentation.

---

## 9. Out of scope

- Order-book reconstruction and spoofing/layering detection (requires high-frequency
  book capture not available historically).
- Any attempt to deanonymize or link participants.
- Live/real-time alerting. The program runs over historical settled events.
- Trading of any kind. `kxsurv` never places an order and holds no position.
