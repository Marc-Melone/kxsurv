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
resolution consistency. Public data can support a candidate naming issue or a
logical result inconsistency, but neither is a finding about trading conduct.

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
fixes measurement and provenance defects; it is not a prospective validation
exercise. The v1.1 re-analysis of the saved data is a regression check. A later
three-series challenge corpus exposed additional scope and comparison defects
and therefore became remediation data, not an independent test set. Prospective
evaluation requires a subsequent corpus not used to design or correct the code.

Every free parameter lives in `config/params.yaml`. A parameter set must be
explicitly registered before controls can run. The registry allows exactly one
canonical hash per version; changing a parameter requires a version bump and a
new registration row. This constrains threshold drift, but it does not by itself
make a later code correction independent validation. Published results must
identify the source commit or release tag as well as their parameter and input
identities. Configuration version `1.1.0` identifies the frozen parameter set;
corrective source revisions under that configuration remain distinct through
their code fingerprints and source commits.

## 4. Data lineage and execution provenance

### Saved 2026-09-07 snapshot

The local v1.0 snapshot contained 408 markets across five series, 100,494
trades, 248,912 candlestick periods, and 28 events. It is gitignored. A fresh
clone can reproduce tests and pipeline mechanics and retrieve current public
data, but it cannot reproduce this dated snapshot or its result counts without
the retained snapshot artifact. Public data evolve and Kalshi's live/historical
partition cutoff moves, so a fresh ingest is a new measurement rather than a
reproduction of the historical one.

After claiming a refresh generation, each full ingest clears the mutable
detector-input tables, retains markets whose close is within or after the
90-day observation window, and retrieves trades and candles inside that window;
it is not an additive cache. The database is therefore not an immutable source
archive. A completed control run instead records its parameter hash, input
fingerprint, code fingerprint, status, and timestamps; alert identity is scoped
to that run. This prevents later refreshed data from silently overwriting the evidence of an
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

The saved snapshot was collected from the live trade endpoint only and contains
roughly 66 days of retrieved trades versus roughly 89 days of candles. A
full-range comparison of those unlike acquisition windows spuriously failed 261
of 408 markets. Current ingestion follows Kalshi's
[historical-data partition guidance](https://docs.kalshi.com/getting_started/historical_data):
it unions live and historical markets, routes candlesticks by market tier, and
merges live and historical trades over the requested window. Cursor repetition,
a non-terminal empty page, or exhaustion of the pagination guard fails the
refresh rather than returning a partial prefix. Cross-tier identity conflicts
and malformed required candle fields also fail closed. Completeness is assessed
from each market's first retrieved trade forward.

This is a **trade-tape gate**, not a universal gate for all controls:

| Saved-snapshot classification | Markets | Effect |
|---|---:|---|
| Positive trade tape and passed reconciliation | 394 | Eligible for C1/C2 subject to their other conditions |
| No retrieved trade tape but passed candle-only classification | 12 | C1/C2 unavailable in the saved snapshot; C3/C4 may use their candle inputs |
| Failed reconciliation | 2 | Excluded from C1/C2; C3/C4 retain their separate candle-data scope |

C3 and C4 use candle data; C5 uses stored settlement metadata. Do not read a
trade-tape reconciliation result as a claim that every control has the same
coverage.

## 5. Controls

### C1 — Pre-release informed flow (CP 12)

Economic-release markets halt before a configured expected publication time.
C1 asks whether flow in the pre-halt window looks unusually informed after
accounting for the price at which each trade actually executed.

C1 requires both a halt time and a publication time materialized from the source-
coded release schedule. A close or halt time by itself does not establish a
discrete information release; continuously resolving markets and series without
a source-coded schedule are outside its scope.

For a trade with size `q`, direction `d` (+1 when the aggressor bought the
eventual outcome, −1 otherwise), and YES execution price `p`, C1 weights it by
the probability the execution price already assigned to the realised outcome:

```text
surprise = 1 - p                 if the market settled YES
surprise = p                     if the market settled NO
score = sum(q × d × surprise) / sum(q)
```

The start-of-window midpoint (`p0`) is retained as optional analyst context;
it does not affect eligibility or the corrected score. Earlier equal-length
windows in the same market form the null population.

`taker_outcome_side` is the canonical stored aggressor direction. The saved
legacy snapshot is backfilled from the older `taker_side` field. New ingestion
prefers the canonical field and rejects a record with no unambiguous YES/NO
direction rather than treating it as NO flow.

The halt-to-publication gap is stored per event; it is not universally five
minutes. In this saved snapshot it is one minute for CPI YoY, payrolls, and U3,
and five minutes for CPI and FOMC events.

**Sample-size constraint:** the saved snapshot's 132 settled markets belong to
nine settled ladders representing five distinct scheduled release timestamps.
Ladders sharing a publication are not independent. C1 makes no population-level
claim. Its 3/69 observed v1.1 candidate rate is not a false-positive-rate
estimate: with five to sixteen null samples, a 95th-percentile alert is often the
maximum rank, which has a much larger null probability than 5%.

**Dominant innocent explanation:** superior processing of public information,
including nowcasts or public-data analysis, is observationally equivalent to
misuse of non-public information on the public tape.

### C2 — Pre-halt price pressure (CP 4)

C2 tests the final pre-halt window for all of the following: material one-sided
aggressor imbalance, a material YES-price move, thin total volume, and **sign
alignment** between net aggressor flow and the YES-price move. Net YES buying
must accompany a rising YES price; net aggressive NO buying must accompany a
falling YES price. Absolute displacement alone cannot establish price pressure.

**Dominant innocent explanations:** first-to-last execution-price movement can
reflect bid-ask bounce or trade sequencing in a wide, thin market. Late public
information and ordinary position-squaring near the halt can also produce the
same signature.

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
observed non-specific signature frequencies, not measured benign base rates.

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

C4 groups quote closes by a shared hourly candle endpoint, compares adjacent
available strikes in that period, and requires the same pair to invert across
adjacent hourly end-period buckets. It also requires the inversion to exceed
the combined half-spread. This identifies a period-aligned market-quality
candidate, not a participant or intent. The feed does not reveal when each
market's quote last changed within the hour, so a common endpoint is not proof
that the quotes were simultaneously executable.

The current saved-snapshot re-analysis emits 14 C4 candidates. An earlier
corrective run emitted 42 because binary floating-point representation allowed
28 comparisons equal to the combined-half-spread boundary to pass. All 28
had been disposed `no_action`; removing them leaves the nine C4 monitor decisions
intact.

### C5 — Settlement-source integrity (CP 4)

C5 is restricted to **inventory and consistency checks** because no independent
corroborating reference-data feed is ingested. It does not perform
settlement-value divergence monitoring. Its checks are:

1. Candidate aliases in declared settlement-source names, where every candidate
   name independently declares the same single valid hostname;
2. logically inconsistent results within a settled `greater` ladder; and
3. a series with no declared settlement source.

Per-source counts are coverage, not a partition. Normalized concentration uses
set unions of series and markets rather than summing alias coverage. In the
saved snapshot, `Bureau of Labor Statistics` and `BLS` are an acronym candidate
with the shared declared domain `www.bls.gov`; their normalized declared coverage
is 4 of 5 series and 310 of 408 markets (76%). This is the conditional coverage
if authoritative review confirms that the names identify one provider; it is
not an independently verified identity or a trading-conduct conclusion.

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

Current corrected logic against the same saved database yields 30 candidates.
Run 8 reproduced the same alert fields as run 7 after acquisition-tier
hardening. That equality was checked before each row was reviewed again and
given a new run-scoped rationale: 14 no-action, 16 monitor, and 0 escalated.
Prior dispositions informed review but were not automatically inherited.

| Control | Generated | No action | Monitor | Escalated |
|---|---:|---:|---:|---:|
| C1 | 3 | 2 | 1 | 0 |
| C2 | 0 | — | — | — |
| C3 | 12 | 7 | 5 | 0 |
| C4 | 14 | 5 | 9 | 0 |
| C5 | 1 | 0 | 1 | 0 |
| **Total** | **30** | **14** | **16** | **0** |

Every alert carries a written rationale. None is escalated because the public
record supplies neither participant identity nor evidence that eliminates the
documented non-specific explanations; 16 are retained for monitoring.

**Why this differs from the v1.0.0 record.** The control mechanics were
corrected, not retuned. C1 previously weighted every trade in a 120-minute window
by a single start-of-window quote, crediting flow that arrived after the market
had already converged; surprise is now computed per trade from its own execution
price (4 → 3 alerts). C3 previously computed the change in open interest against
the previous *stored* candle, so across a gap one hour of volume was compared with
several hours of movement (13 → 12 alerts). C4 now makes decimal-safe quote
comparisons rather than allowing binary floating-point noise to turn equality
with the combined-half-spread boundary into an exceedance (42 → 14
alerts). C1 also rejects events with no publication time materialized from the
source-coded schedule; that scope guard does not change the saved economic-
corpus count. **No configured detection threshold changed** — every window,
percentile, floor and persistence value is identical to v1.0.0.

One parameter did change, and it went through the mechanism rather than around
it: `c5_settlement.inventory_only` was set to `true` (and the unused
`divergence_tolerance` removed) to declare that C5 performs inventory and
consistency checks only, since no independent corroborating feed is ingested.
That required a version bump to **1.1.0** and a new registration row; the v1.0.0
row is retained. Both registrations are visible in the `params` table, which is
the point of recording them.

**Current-run provenance.** This record comes from the completed current-source
rerun; `out/saved-snapshot.log` retains the compact command/result record.

| Field | Value |
|---|---|
| Run ID | 8 |
| Source commit | `6b11825` |
| Parameters SHA-256 | `b7ebfd8a51a871df8d9cd240afa24a956a9d077636e9bc6d28bfd571b00bb057` |
| Input fingerprint | `6bdc06093985193845082f3288f2fcbf62c6c656cb265b5302459f88533d2983` |
| Code fingerprint | `760839ab76ada33a0db862be242dbf69324dc9429e2d82235142cf81e936c82e` |
| Finished | 2026-09-11T15:45:18.415501+00:00 |
| Execution status | complete, 5/5 controls |

**Superseded run provenance.** The following record predates the C4 monetary-
boundary correction and supports the earlier 58-candidate corrective run. It is
retained as historical provenance, not presented as the current-code run.

| Field | Value |
|---|---|
| Run ID | 6 |
| Parameters SHA-256 | `b7ebfd8a51a871df8d9cd240afa24a956a9d077636e9bc6d28bfd571b00bb057` |
| Input fingerprint | `6bdc06093985193845082f3288f2fcbf62c6c656cb265b5302459f88533d2983` |
| Code fingerprint | `58e7cf469d5d24f5d85620bf5f5944e5be2d363331fe0d3e23d2e298c47bc7da` |
| Finished | 2026-09-07T22:56:05.227000+00:00 |

C1 scored 69 of 408 markets (276 unsettled, 61 below the volume floor, 2 with an
insufficient null). Its 3/69 = 4.3% candidate rate is descriptive only. With
small, discrete market-specific nulls, the 95th-percentile rule is not a
calibrated 5% false-positive test.

## 7.5 Challenge-corpus application and remediation

The corrective code and frozen v1.1.0 parameters were challenged against three
previously unseen series — `KXGDP`, `KXHIGHNY`, and `KXFEDDECISION`: **530
markets, 702,453 trades** in a separate local database. Because observations
from this corpus caused code changes, it is development/remediation evidence,
not independent validation of the resulting code. Like the main snapshot, the
database is gitignored; its exact counts require the retained hashed artifact,
while a fresh API ingest is a new measurement.

**It found a defect the in-sample corpus could not.** Every market in the
economic corpus is `strike_type = 'greater'`. `KXHIGHNY` mixes `greater`,
`between` and `less`; `KXFEDDECISION` uses `custom`. C4 selected events holding
at least one `greater` market but then admitted *every* strike in the event to
the ladder, so `between` contracts were compared as though their probability
were monotone in the floor strike. It is not.

| C4 alerts | Challenge corpus | Saved economic corpus |
|---|---|---|
| Superseded persisted runs | 77 (**76 from mixed-type events**) | 42 |
| Current persisted runs | **0** | **14** |

The current row applies both the strike-type scope correction and the separate
decimal-safe boundary correction. The transient one-alert intermediate result
is intentionally omitted because it was not preserved as a completed run.

**C3's persistence behavior differs across the two corpora.** The percentile
population is rebuilt within each evaluated database, so this is not a test of a
fixed empirical score threshold transferred from one family to another. The
percentile gate selected 480/9,793 (4.90%) scoreable observations in the saved
economic corpus and 846/16,984 (4.98%) in the challenge corpus. After adjacent-
hour persistence, alert density was 12/9,793 (1.23 per thousand scoreable
observations) versus 82/16,984 (4.83 per thousand), about 3.9 times higher. This
documents greater temporal clustering in the challenge corpus; it does not by
itself identify liquidity tiers or any other cause.

**The challenge exposed a C1 applicability defect.** All three series lacked a
publication time from the source-coded schedule. The earlier persisted run
nevertheless raised four alerts, all in temperature contracts, by treating close
time as sufficient. Those alerts do not validate a pre-release-information
screen. C1 now excludes events without a materialized publication time and
reports them as out of scope.

**C5 observed zero candidates** in this snapshot: its stored inputs contained
three distinct declared settlement sources, no candidate aliases, no missing
declarations, and no ladder settlement contradictions. Fixture tests separately
exercise each firing condition; the zero is not evidence that broader
settlement risk is absent.

The corrected challenge rerun is run 3 at source commit `6b11825`, with 5/5
controls complete. It produced C1 0, C2 0, C3 82, C4 0, and C5 0; all 82 C3
rows remain untriaged because this is a development corpus, not a published
performance result.

| Challenge provenance field | Value |
|---|---|
| Parameters SHA-256 | `b7ebfd8a51a871df8d9cd240afa24a956a9d077636e9bc6d28bfd571b00bb057` |
| Input fingerprint | `c997f294d10ce29f513cd1ce5df068fb63699fe1c04bb75c5c5c4eae522a8c68` |
| Code fingerprint | `760839ab76ada33a0db862be242dbf69324dc9429e2d82235142cf81e936c82e` |
| Finished | 2026-09-11T15:48:53.282593+00:00 |

## 8. Review cadence and known limitations

1. Controls may re-run after ingest, but every output must be interpreted within
   its run record and source-code release.
2. C1 has five scheduled releases represented by nine settled ladders and the
   saved snapshot's retention-limited tape.
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
