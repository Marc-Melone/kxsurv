# Control correction note — C4 ladder monotonicity

**Opened:** 2026-09-07 · **Control:** C4 (CFTC DCM Core Principle 4)
**Status:** defect found in the control itself, corrected, results superseded

## Summary

C4 originally reported **zero alerts across 28 events**, and an earlier version
of this note presented that as evidence the control was working. **That
conclusion was wrong.** The control was not working. Its central comparison was
invalid, and the zero was an artifact of the defect.

## The defect

Monotonicity is a statement about **simultaneous** prices: for a `greater`
ladder, `P(X > k₁) ≥ P(X > k₂)` must hold *at a given moment*. The first
implementation took each strike's most recent quote **independently**:

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

So the control was comparing a strike quoted eight days ago against one quoted
an hour ago and treating the difference as a monotonicity violation. Any result
it produced — including the zero — was meaningless.

## The correction

Quotes are now grouped by candle period, and only strikes present **in the same
period** are compared. Monotonicity is transitive, so a strike missing from a
snapshot is simply absent and its neighbours may still be compared.

This also made `min_persistence_snapshots` operative for the first time: an
inversion must now survive consecutive snapshots to alert. Previously the
parameter was registered but unreachable.

A second defect surfaced during the fix. Alerts are deduplicated on
`(control, target, window, params_hash)`, and `target` was the event alone — so
several strike pairs inverting in one event and window collapsed into a single
row, silently discarding **4 legitimate alerts**. `target` now identifies the
strike pair.

## Result

| | Before | After |
|---|---|---|
| C4 alerts | 0 | **42** |
| Inversions ≥ 2× combined half-spread | — | 9 |
| Largest ratio to spread | — | 5.0× (`KXCPIYOY-26NOV:4.5>4.6`) |

Of the 42, **33 closed no-action** — their magnitude only marginally exceeds the
combined half-spread, which is ordinary wide quoting — and **9 are retained for
monitoring** at 2× the spread or more.

The discriminator is **not raw magnitude**. The two largest inversions by size
(0.2250) sit against half-spreads of 0.195 and 0.205 and closed no-action, while
a 0.095 inversion against a 0.025 half-spread stays open. Spread-relative
magnitude is the meaningful quantity; absolute magnitude is misleading.

## Why the parameters did not change

Pre-registration froze the C4 thresholds before any control ran. **This
correction changed code, not parameters** — `min_inversion_dollars`,
`require_exceeds_half_spread` and `min_persistence_snapshots` are unchanged at
their registered v1.0.0 values. Had the fix required loosening a threshold to
produce alerts, that would have demanded a version bump and a new registration
row, and the change would be visible in the record.

## What this says about the programme

A control that returns nothing is indistinguishable, from its output alone, from
a control that is broken. The zero was reported as a clean result and it was not
one. Two safeguards would have caught this earlier and are now in place:

1. **End-to-end fixture tests per control** — plant a known signature, assert
   the control fires; plant a matched clean tape, assert it does not. The
   framework claimed this validation existed; it did not. It does now.
2. **Treating a null result as a hypothesis to test**, not a finding to report.

Both are recorded in `SURVEILLANCE_FRAMEWORK.md` §9.
