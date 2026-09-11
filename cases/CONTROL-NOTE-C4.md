# Control correction note — C4 ladder monotonicity

**Opened:** 2026-09-07 · **Control:** C4 (CFTC DCM Core Principle 4)
**Status:** historical staged correction record; current saved-snapshot result noted below

> This note preserves the initial v1.0.0 correction history. Its 42-alert and
> 33/9-disposition figures describe an intermediate source revision. Decimal-
> safe spread-boundary comparisons later removed 28 binary-floating-point false
> positives, all previously `no_action`. The current saved-snapshot result is 14
> C4 candidates: 5 no-action and 9 monitor.

## Summary

C4 originally reported **zero alerts across 28 events**, and an earlier version
of this note presented that as evidence the control was working. **That
conclusion was wrong.** The control was not working. Its central comparison was
invalid, and the zero was an artifact of the defect.

## The defect

The theoretical monotonicity condition is a statement about **simultaneous**
prices: for a `greater` ladder, `P(X > k₁) ≥ P(X > k₂)` must hold *at a
given moment*. The public candlestick feed supports only period alignment, not
that stronger timing claim. The first implementation took each strike's most
recent quote **independently**:

```sql
SELECT yes_bid_close, yes_ask_close FROM candles
 WHERE ticker = ? AND yes_bid_close IS NOT NULL
 ORDER BY end_period_ts DESC LIMIT 1     -- per strike, independently
```

Strikes are not quoted on a common schedule. Measured across the corpus:

| Spread between strikes' last-quote timestamps | Events |
|---|---|
| > 1 hour | 16 of 28 |
| > 24 hours | 12 of 28 |
| worst case (`KXCPIYOY-26NOV`) | **194 hours** |

So the control assembled ladders from quotes spanning as much as eight days,
with adjacent strikes sometimes separated by several days, and treated them as
one cross-section. Any result it produced — including the zero — was
meaningless.

## The correction

Quote closes are now grouped by a shared hourly candle endpoint, and only
strikes present **in the same period** are compared. Monotonicity is transitive,
so a strike missing from a period is simply absent and its neighbours may still
be compared. A common endpoint does not reveal when each market's quote last
changed within the hour; the corrected output is therefore a period-aligned
coherence candidate, not proof of simultaneous executable prices.

This also made `min_persistence_snapshots` operative for the first time: an
inversion must now survive consecutive snapshots to alert. Previously the
parameter was registered but unreachable.

A second defect surfaced during the fix. In v1.0.0, alerts were deduplicated on
`(control, target, window, params_hash)`, and `target` was the event alone — so
several strike pairs inverting in one event and window collapsed into a single
row, silently discarding **4 candidate rows**. That count is reproducible by
grouping the later run-6 C4 rows by event and window and summing the three
groups' duplicates. `target` was changed to identify the strike pair. Current
v1.1 alert identity is additionally scoped to `run_id`, so revised data or
evidence is retained in a later run rather than silently conflated with the
earlier alert.

## Result

At the initial period-alignment correction stage:

| | Before | After |
|---|---|---|
| C4 alerts | 0 | **42** |
| Inversions ≥ 2× combined half-spread | — | 9 |
| Largest ratio to spread | — | 5.0× (`KXCPIYOY-26NOV:4.5>4.6`) |

Of the 42, **33 closed no-action** — their magnitude only marginally exceeds the
combined half-spread, which is ordinary wide quoting — and **9 are retained for
monitoring** at 2× the spread or more.

A later challenge against mixed contract types added two further safeguards:
only `greater` contracts may enter a monotone ladder, and quoted-price boundaries
are compared using decimal-safe values. The latter showed that 28 apparent
exceedances were exactly equal to the combined half-spread and had passed only
because of binary floating-point representation. Removing those false positives
leaves 14 saved-snapshot C4 candidates. The surviving alert rows and rationales
were matched to the corrected output; the 5 no-action / 9 monitor split is not an
aggregate disposition carried forward blindly.

The discriminator is **not raw magnitude**. The two largest inversions by size
(0.2250) sit against half-spreads of 0.195 and 0.205 and closed no-action, while
a 0.095 inversion against a 0.025 half-spread stays open. Spread-relative
magnitude is the meaningful quantity; absolute magnitude is misleading.

## Why the v1.0 parameters did not change

Pre-registration froze the C4 thresholds before the v1.0.0 run. **That
correction changed code, not thresholds** — `min_inversion_dollars`,
`require_exceeds_half_spread`, and `min_persistence_snapshots` were retained in
v1.1.0. v1.1 is nonetheless a distinct corrective release because control
mechanics and execution governance changed elsewhere. Its saved-snapshot
re-analysis is not prospective validation. Later dispositions are run-scoped;
where a prior rationale remains relevant to a surviving alert, it is explicitly
matched and re-reviewed rather than inherited automatically.

## What this says about the programme

A control that returns nothing is indistinguishable, from its output alone, from
a control that is broken. The zero was reported as a clean result and it was not
one. Two safeguards would have caught this earlier and are now in place:

1. **End-to-end fixture tests per control** — plant a known signature, assert
   the control fires; plant a matched clean tape, assert it does not. The
   framework claimed this validation existed; it did not. It does now.
2. **Treating a null result as a hypothesis to test**, not a finding to report.

Both are recorded in `SURVEILLANCE_FRAMEWORK.md`.
