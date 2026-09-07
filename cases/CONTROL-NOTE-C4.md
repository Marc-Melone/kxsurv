# Control validation note — C4 ladder monotonicity

**Date:** 2026-09-07
**Control:** C4 — ladder monotonicity coherence (CFTC DCM Core Principle 4)

## Result

C4 generated **zero alerts** across 28 events. That is the control working, not
the control failing.

## What the spread filter suppressed

Running C4 with `require_exceeds_half_spread` disabled surfaces **16** candidate
inversions. Every one of them is a violation whose magnitude sits inside the
combined bid-ask half-spread of the two adjacent strikes — the signature of
quote staleness in a thinly quoted strike, not of price distortion.

| `require_exceeds_half_spread` | Alerts |
|---|---|
| `true` (registered value) | 0 |
| `false` | 16 |

## Worked example

`KXPAYROLLS-26SEP`, observed 2026-09-07: strike 50,000 quoted at mid $0.5350
while strike 60,000 quoted at mid $0.5450. Since P(X > 50,000) must be at least
P(X > 60,000), this is a formal monotonicity violation of 1¢.

It is also economically meaningless. The 1¢ magnitude does not exceed the
combined half-spread of the two strikes, no volume accompanied it, and it did
not persist. The correct disposition is no action, and the registered parameter
set reaches that conclusion automatically.

## Why this matters

A monotonicity control without a spread filter would have raised 16 alerts on a
healthy market. An analyst who escalated them would have burned credibility on
stale quotes. The filter is the difference between a control and a nuisance
generator, and its value is measurable: **16 alerts suppressed, 0 false
escalations.**

## Limitation

C4 evaluates the most recent quote snapshot per strike. Persistence across
snapshots (`min_persistence_snapshots`) is registered but cannot be exercised
against a single ingest; it requires repeated collection over time.
