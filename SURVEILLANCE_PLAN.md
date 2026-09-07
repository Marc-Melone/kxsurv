# kxsurv — Pre-registration

**Version 1.0.0 — registered before any control was run.**

Parameters in `config/params.yaml` are frozen as of this document. The runner
verifies the SHA-256 of the canonical parameter set against the `params` table
and refuses to execute on drift. Changing any value requires a version bump and
a new registration row; prior rows are retained.

## Why

A surveillance control whose thresholds move after seeing outcomes is not a
control. Freezing parameters in advance is what separates an alert from a
post-hoc story.

## Frozen parameters and rationale

| Control | Parameter | Value | Rationale |
|---|---|---|---|
| C1 | `window_minutes` | 120 | Pre-halt window. Long enough to contain measurable flow (observed 7–24 trades) without spanning unrelated sessions. |
| C1 | `null_windows` | 20 | Matched control windows from the same market's own history. |
| C1 | `percentile_threshold` | 95.0 | Standard screening percentile against the market's own null. |
| C1 | `min_window_volume` | 100.0 | Deep out-of-money brackets show zero pre-halt flow; below this a score is noise. |
| C2 | `window_minutes` | 30 | Final pre-halt interval. |
| C2 | `min_imbalance_ratio` | 0.70 | One-sidedness required before flow is remarkable. |
| C2 | `min_price_displacement` | 0.05 | 5¢ move; below this is ordinary quote movement. |
| C2 | `max_thinness_volume` | 500.0 | Marking-the-close risk concentrates in thin markets. |
| C3 | `min_candle_volume` | 50.0 | Volume floor. Flat-OI candles occur at 18–27% base rate (measured), so a raw trigger is unusable; the floor removes trivial volume. |
| C3 | `percentile_threshold` | 95.0 | Ranked **within liquidity tier**, not globally. |
| C3 | `min_persistence_periods` | 2 | Single-period divergence is usually position transfer. |
| C3 | `liquidity_tiers` | 100/1k/10k | Open-interest cut points; false-positive rate rises with liquidity. |
| C4 | `min_inversion_dollars` | 0.01 | Minimum tick. |
| C4 | `require_exceeds_half_spread` | true | A 1¢ inversion inside the combined spread is quote staleness, not distortion. |
| C4 | `min_persistence_snapshots` | 2 | Transient inversions are stale quotes. |
| C5 | `divergence_tolerance` | 0.0 | Any settlement-value divergence is material. |

## Aggressor derivation (validated, not assumed)

`taker_side == "yes"` means the aggressor bought YES. Validated 2026-09-07 on
`KXCPI-26JUL-T0.3` (686 trades, `result='no'`, 0.250 → 0.010): signed volume
agreed with realized price direction in 5/5 sequential blocks. Re-run if the
tape schema changes.

## Known sample-size limitation

C1's unit of analysis is the information event, not the market. Kalshi's API
retains only recent settled events: **9 distinct events** across all five
economic series (132 settled markets, but brackets within an event are not
independent). C1 therefore makes **no population-level statistical claim**. It
is validated by fixture detection behaviour and analyst triage.
