# kxsurv — Surveillance Program Framework

**Version 1.1.0 · corrective release · 2026-09-07 saved-snapshot re-analysis**

---

## 1. Scope and posture

`kxsurv` implements five surveillance **screens** over public Kalshi market
data. The controls map to CFTC Designated Contract Market Core Principles and
feed a run-scoped alert queue with written analyst dispositions.

This is a methodology demonstration on public data, not an audit of Kalshi or
an allegation that market abuse occurred. The program uses unauthenticated
public endpoints only; it sends no authenticated request, places no order, and
uses no non-public information.

### The counterparty-identity boundary

Kalshi's public tape does not carry counterparty identity. `kxsurv` cannot
identify or link accounts, establish beneficial ownership, demonstrate
coordination, establish intent, or conclude that a participant committed
misconduct. Participant-facing outputs are alerts warranting investigation,
never findings. An escalated participant-conduct item requires account-level
data held by the exchange.

C5 is different in kind: it screens published settlement metadata and
resolution consistency. An operational metadata inconsistency can be recorded
from public data, but it is still not a finding about trading conduct.

## 2. Regulatory framing

KalshiEX LLC is a CFTC-designated contract market and is subject to the DCM Core
Principles at 17 CFR Part 38. The mappings below frame the controls; they do not
convert a public-data alert into proof of a regulatory breach.

| Control | Screening purpose | Core Principle |
|---|---|---|
| C1 — Pre-release informed flow | Pre-release information screen | CP 12 — Protection of Markets and Market Participants |
| C2 — Pre-halt price pressure | Directionally aligned, thin-market pressure screen | CP 4 — Prevention of Market Disruption |
| C3 — Volume / open-interest divergence | Wash-trade screening proxy | CP 12 |
| C4 — Ladder monotonicity coherence | Price-quality screen across related contracts | CP 4 |
| C5 — Settlement-source integrity | Settlement metadata and resolution-consistency screen | CP 4 |

## 3. Versioning, pre-registration, and validation posture

v1.1.0 is a **corrective release** written after reviewing v1.0.0 output. It
fixes measurement and provenance defects; it is not a prospective or
out-of-sample validation exercise. The v1.1 re-analysis of the saved data is a
regression check. The first new public-API ingestion executed after explicit
v1.1 registration is the prospective evaluation.

Every free parameter lives in `config/params.yaml`. A parameter set must be
explicitly registered before controls can run. The registry allows exactly one
canonical hash per version; changing a parameter requires a version bump and a
new registration row. This constrains threshold drift, but it does not by itself
make a later code correction independent validation. Published results must
identify the source commit or release tag as well as their parameter and input
identities.

## 4. Data lineage and execution provenance

### Saved 2026-09-07 snapshot

The local v1.0 snapshot contained 408 markets across five series, 100,494
trades, 248,912 candlestick periods, and 28 events. It is gitignored. A fresh
clone can execute the code and retrieve current public data, but it cannot
reproduce this dated snapshot or its result counts without separately receiving
the database artifact.

Markets and candles are refreshed on ingest; trade rows are deduplicated by
trade ID. The database is therefore not an immutable source archive. A completed
control run instead records its parameter hash, input fingerprint, code
fingerprint, status, and timestamps; alert identity is scoped to that run. This
prevents later refreshed data from silently overwriting the evidence of an
earlier run. Each control also receives an execution record, including a
zero-alert result, so the report can distinguish a tested null from an unrun
control. The fingerprints identify the stored inputs and detector code at
execution time, but do not archive those inputs or the source code.

The CLI records the raw-data refresh lifecycle separately: it marks a snapshot
`refreshing` before any public-API write, `ready` only after markets, events,
completeness, and settlement inventory finish, and `failed` on an interrupted
refresh. `--skip-ingest` refuses a non-ready snapshot. Existing v1.0 local data
that predates this marker is labelled `legacy_ready` only after structural
coverage checks; a new full ingest provides the stronger lifecycle evidence.

### Trade-tape completeness

The public trade tape has a measured retention horizon of roughly 66 days in
the saved snapshot, while the requested candle history reaches roughly 89 days.
A full-range tape/candle comparison spuriously failed 261 of 408 markets.
Completeness is instead assessed from each market's first available trade
forward.

This is a **trade-tape gate**, not a universal gate for all controls:

| Saved-snapshot classification | Markets | Effect |
|---|---:|---|
| Positive trade tape and passed reconciliation | 394 | Eligible for C1/C2 subject to their other conditions |
| No available trade tape but passed candle-only classification | 12 | C1/C2 unavailable; C3/C4 may use their candle inputs |
| Failed reconciliation | 2 | Excluded from C1/C2; C3/C4 retain their separate candle-data scope |

C3 and C4 use candle data; C5 uses stored settlement metadata. Do not read a
trade-tape reconciliation result as a claim that every control has the same
coverage.

## 5. Controls

### C1 — Pre-release informed flow (CP 12)

Economic-release markets halt before a configured expected publication time.
C1 asks whether flow in the pre-halt window looks unusually informed after
accounting for the price at which each trade actually executed.

For a trade with size `q`, direction `d` (+1 when the aggressor bought the
eventual outcome, −1 otherwise), and YES execution price `p`, C1 weights it by
the probability the execution price already assigned to the realised outcome:

```text
surprise = 1 - p                 if the market settled YES
surprise = p                     if the market settled NO
score = sum(q × d × surprise) / sum(q)
```

The start-of-window midpoint (`p0`) is retained as a coverage/context check;
it is not used to weight every live trade. Earlier equal-length windows in the
same market form the null population.

`taker_outcome_side` is the canonical stored aggressor direction. The saved
legacy snapshot is backfilled from the older `taker_side` field. New ingestion
prefers the canonical field and rejects a record with no unambiguous YES/NO
direction rather than treating it as NO flow.

The halt-to-publication gap is stored per event; it is not universally five
minutes. In this saved snapshot it is one minute for CPI YoY, payrolls, and U3,
and five minutes for CPI and FOMC events.

**Sample-size constraint:** the saved snapshot has nine independent information
events. C1 makes no population-level claim. Its 3/69 observed v1.1 candidate
rate is not a false-positive-rate estimate: with five to sixteen null samples,
a 95th-percentile alert is often the maximum rank, which has a much larger null
probability than 5%.

**Dominant innocent explanation:** superior processing of public information,
including nowcasts or public-data analysis, is observationally equivalent to
misuse of non-public information on the public tape.

### C2 — Pre-halt price pressure (CP 4)

C2 tests the final pre-halt window for all of the following: material one-sided
aggressor imbalance, a material YES-price move, thin total volume, and **sign
alignment** between net aggressor flow and the YES-price move. Net YES buying
must accompany a rising YES price; net NO selling must accompany a falling YES
price. Absolute displacement alone cannot establish price pressure.

**Dominant innocent explanation:** late public information or ordinary
position-squaring near the halt produces the same public signature.

### C3 — Volume / open-interest divergence (CP 12)

C3 measures the aggregate relation between candle volume and the change in
open interest:

```text
D = volume / (abs(delta open interest) + epsilon)
```

An observation exists only when the candle has an immediately preceding
3,600-second candle. A missing hour produces no `delta open interest` observation;
it cannot pair one hour of volume with several hours of OI movement. Candidates
also require a volume floor, a percentile within an OI liquidity tier, and
adjacent-hour persistence.

Flat OI is not evidence of wash trading. It can arise from ordinary offsetting
open/close activity among unrelated traders, and public data cannot establish
beneficial ownership. In the two cited contiguous-hour samples, flat OI occurred
in 44 of 169 (26.0%) and 12 of 74 (16.2%) volume-bearing observations. These are
observed non-specific signature frequencies, not non-specific signature rates.

For the saved snapshot, 9,793 observations are scoreable; 480 clear the
percentile gate and 12 survive the persistence rule. `C3.coverage()` emits the
first two values from the exact same population used by `C3.run()`. Selectivity
comes primarily from the time-adjacent construction and persistence requirement,
not from a standalone percentile.

### C4 — Ladder monotonicity coherence (CP 4)

The economic-series markets in this corpus use `strike_type: "greater"`
threshold ladders, not mutually exclusive partitions. For ascending strikes,
the implied YES prices should be non-increasing:

```text
P(X > k1) >= P(X > k2) >= ... >= P(X > kn)
```

C4 groups quotes by common candle period, compares adjacent available strikes
within that snapshot, and requires the same pair to invert across adjacent
hourly snapshots. It also requires the inversion to exceed the combined
half-spread. This identifies price incoherence, not a participant or intent.

The saved-snapshot re-analysis emits 42 C4 candidates. Their v1.1
dispositions are not inferred from the legacy v1.0 case files.

### C5 — Settlement-source integrity (CP 4)

C5 is restricted to **inventory and consistency checks** because no independent
corroborating reference-data feed is ingested. It does not perform
settlement-value divergence monitoring. Its checks are:

1. Candidate aliases in declared settlement-source names, corroborated by a
   single normalized declared source URL domain;
2. logically inconsistent results within a settled `greater` ladder; and
3. a series with no declared settlement source.

Per-source counts are coverage, not a partition. Normalized concentration uses
set unions of series and markets rather than summing alias coverage. In the
saved snapshot, `Bureau of Labor Statistics` and `BLS` are an acronym candidate
with the shared declared domain `www.bls.gov`; their normalized declared coverage
is 4 of 5 series and 310 of 408 markets (76%). This records a metadata
concentration dependency, not an independently verified provider identity or a
trading-conduct conclusion.

## 6. Alert handling

Allowed dispositions are `no_action`, `monitor`, and `escalated`; each requires
a written rationale. A disposition belongs to one alert row in one execution
run. A changed method or later input snapshot creates new alert rows, so prior
dispositions are historical evidence rather than automatic decisions for the
new run.

Escalation is appropriate only when the documented innocent explanation is
meaningfully weakened by evidence available to the exchange. Public data alone
normally cannot support escalation of a participant-conduct screen.

## 7. Results and their status

### Historical v1.0.0 run

The legacy local snapshot produced 60 alerts, all triaged: 45 no-action, 15
monitor, and 0 escalated. By control, it recorded C1 4, C2 0, C3 13, C4 42, and
C5 1. These values remain a historical audit record only.

### v1.1 saved-snapshot re-analysis

Corrected v1.1 logic against the same saved database, fully triaged:

| Control | Generated | No action | Monitor | Escalated |
|---|---:|---:|---:|---:|
| C1 | 3 | 3 | 0 | 0 |
| C2 | 0 | — | — | — |
| C3 | 12 | 7 | 5 | 0 |
| C4 | 42 | 33 | 9 | 0 |
| C5 | 1 | 0 | 1 | 0 |
| **Total** | **58** | **43** | **15** | **0** |

Every alert carries a written rationale; none is escalated, because none survived
its documented non-specific explanation on the evidence public data supplies.

**Why this differs from the v1.0.0 record.** Two metrics were corrected, not
retuned. C1 previously weighted every trade in a 120-minute window by a single
start-of-window quote, crediting flow that arrived after the market had already
converged; surprise is now computed per trade from its own execution price
(4 → 3 alerts). C3 previously computed the change in open interest against the
previous *stored* candle, so across a gap one hour of volume was compared with
several hours of movement (13 → 12 alerts). **No detection threshold changed** —
both are code corrections, and every window, percentile, floor and persistence
value is identical to v1.0.0.

One parameter did change, and it went through the mechanism rather than around
it: `c5_settlement.inventory_only` was set to `true` (and the unused
`divergence_tolerance` removed) to declare that C5 performs inventory and
consistency checks only, since no independent corroborating feed is ingested.
That required a version bump to **1.1.0** and a new registration row; the v1.0.0
row is retained. Both registrations are visible in the `params` table, which is
the point of recording them.

**Run provenance.**

| Field | Value |
|---|---|
| Run ID | 6 |
| Parameters SHA-256 | `b7ebfd8a51a871df8d9cd240afa24a956a9d077636e9bc6d28bfd571b00bb057` |
| Input fingerprint | `6bdc06093985193845082f3288f2fcbf62c6c656cb265b5302459f88533d2983` |
| Code fingerprint | `58e7cf469d5d24f5d85620bf5f5944e5be2d363331fe0d3e23d2e298c47bc7da` |
| Finished | 2026-09-07T22:56:05.227000+00:00 |

C1 scored 69 of 408 markets (276 unsettled, 61 below the volume floor, 2 with an
insufficient null), so its alert rate is 3/69 = 4.3% against a 95th-percentile
threshold — the rate expected of a detector finding no signal.

## 7.5 Out-of-sample application

The v1.1 corrections were made after observing v1.0.0 output on the economic
corpus, so that corpus cannot validate them. The frozen v1.1.0 parameters and
code were therefore applied to three series the logic had never seen — `KXGDP`,
`KXHIGHNY`, and `KXFEDDECISION`: **530 markets, 702,453 trades**, in a separate
database with its own run record.

**It found a defect the in-sample corpus could not.** Every market in the
economic corpus is `strike_type = 'greater'`. `KXHIGHNY` mixes `greater`,
`between` and `less`; `KXFEDDECISION` uses `custom`. C4 selected events holding
at least one `greater` market but then admitted *every* strike in the event to
the ladder, so `between` contracts were compared as though their probability
were monotone in the floor strike. It is not.

| C4 alerts | Out-of-sample | In-sample |
|---|---|---|
| Before the fix | 77 (**76 from mixed-type events**) | 42 |
| After the fix | **1** | 42 — unchanged |

The correction is surgical: it removes only invalid comparisons and leaves the
all-`greater` corpus identical.

**C3 does not transfer across regimes.** Alert density differs roughly
eighteenfold — 0.05 alerts per thousand candles on the economic corpus against
0.92 on the out-of-sample set. Thresholds calibrated on one market family should
not be assumed to hold on another, and the liquidity tiers are the likely cause.
This is recorded, not corrected: changing them would require a version bump.

**C1 behaved consistently.** It scored 171 of 396 markets out-of-sample, against
69 of 408 in-sample, and raised 4 alerts — 2.3% against a 95th-percentile
threshold, below the ~5% a null detector produces. On a scored sample 2.5 times
larger it did not over-fire.

**C5 raised nothing**, correctly: three distinct settlement sources with no
aliasing, no missing declarations, and no ladder settlement contradictions.
Fixture tests establish it can fire, so this zero is a measurement.

## 8. Review cadence and known limitations

1. Controls may re-run after ingest, but every output must be interpreted within
   its run record and source-code release.
2. C1 has nine independent information events and a retention-limited tape.
3. C2 and C1 need usable reconciled trade tape; C3/C4 depend on their candle
   coverage instead.
4. C3 is an aggregate proxy, not evidence of self-trading or common ownership.
5. C4 currently scores `greater` ladders only.
6. C5 lacks an independent reference-data feed and therefore does not test
   settlement-value divergence.
7. Order-book reconstruction, spoofing/layering detection, and account linkage
   are out of scope.
8. The project retains its corrective history because a null result is not
   self-validating; every control needs both planted-signature and clean-case
   tests as well as analyst review.
