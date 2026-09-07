# kxsurv — Parameter Registration and Versioning

**Version 1.1.0 · corrective configuration for the v1.1 control release**

## Status and purpose

This document records the parameter configuration that must be explicitly
registered before a v1.1 control run. It is not a claim that v1.1 was selected
prospectively: v1.1 corrects defects discovered while reviewing v1.0 output.
Re-analysis of the saved v1.0 database is a regression check; the first new
ingestion after registration is the prospective v1.1 evaluation.

The canonical v1.1 configuration hash is:

```text
b7ebfd8a51a871df8d9cd240afa24a956a9d077636e9bc6d28bfd571b00bb057
```

That value identifies the contents of `config/params.yaml`; it becomes a
registration record only when the following command is executed against the
target database:

```bash
PYTHONPATH=src .venv/bin/python -m kxsurv.cli --register-params
```

Normal execution verifies that hash before controls run. A version can identify
only one canonical parameter hash. Change a parameter, bump `version`, register
the new configuration explicitly, and retain the old row. A code or method
change also needs a new release/version record even when thresholds do not move;
the parameter hash does not identify source code.

## Why

A surveillance control whose thresholds move after seeing outcomes is not a
control. Freezing parameters limits threshold tuning and makes configuration
changes visible. It does not erase the need to disclose corrective,
post-review algorithm changes or to validate a new version prospectively.

## Frozen v1.1 parameters and rationale

| Control | Parameter | Value | Rationale |
|---|---|---:|---|
| C1 | `window_minutes` | 120 | Pre-halt window long enough to contain observable flow without spanning an unrelated session. |
| C1 | `null_windows` | 20 | Maximum number of earlier same-duration windows considered for the market-specific null. |
| C1 | `percentile_threshold` | 95.0 | Screening threshold within that market's null; small discrete nulls remain a stated limitation. |
| C1 | `min_window_volume` | 100.0 | Excludes windows where directional score is dominated by trivial volume. |
| C2 | `window_minutes` | 30 | Final pre-halt interval. |
| C2 | `min_imbalance_ratio` | 0.70 | Requires material one-sided aggressor flow. |
| C2 | `min_price_displacement` | 0.05 | Requires a 5-cent YES-price move as well as sign alignment. |
| C2 | `max_thinness_volume` | 500.0 | Keeps the screen focused on thin markets. |
| C3 | `min_candle_volume` | 50.0 | Removes trivial-volume hourly observations before ranking. |
| C3 | `percentile_threshold` | 95.0 | Ranks divergence within OI liquidity tier rather than globally. |
| C3 | `min_persistence_periods` | 2 | Requires adjacent qualifying hourly observations. |
| C3 | `liquidity_tiers` | 100 / 1k / 10k | Open-interest cut points for within-tier ranking. |
| C3 | `epsilon` | 1.0 | Stabilizes the divergence denominator when OI is unchanged. |
| C4 | `min_inversion_dollars` | 0.01 | Minimum price inversion. |
| C4 | `require_exceeds_half_spread` | true | Excludes an inversion contained in the combined half-spread. |
| C4 | `min_persistence_snapshots` | 2 | Requires the same strike pair across adjacent snapshots. |
| C5 | `inventory_only` | true | Restricts C5 to declared-source inventory/metadata and ladder-result consistency; no independent-feed divergence monitor is implemented. |

## Method constraints carried with the configuration

### Trade direction

`taker_outcome_side` is the canonical aggressor-direction field. The saved
legacy snapshot is backfilled from the deprecated `taker_side` field for
compatibility. New ingestion rejects a trade that supplies neither an
unambiguous `yes` nor `no` direction; missing direction is not treated as NO
flow. `taker_book_side` is not used as outcome direction.

### C1 execution-price weighting

C1 discounts each trade by the outcome probability implied by that trade's own
YES execution price. The start-of-window midpoint is a coverage/context check,
not a substitute for an execution price. This v1.1 correction changes the
saved-snapshot candidate set and requires a new disposition process.

### C2 sign alignment

C2 requires signed net aggressor flow and signed YES-price movement to agree.
An equal-size price move against the flow is not price-pressure evidence under
v1.1.

### C3 strict hourly construction

C3 computes `delta open interest` only from a directly preceding 3,600-second
candle and requires qualifying observations to persist across adjacent hours.
Its flat-OI frequency is an observed non-specific signature rate, not a benign
base rate: the saved-snapshot examples are 26.0% (44/169) and 16.2% (12/74).

### C5 scope

C5 does not compare settlement values to an independent feed. It inventories
declared sources, flags corroborated naming aliases, detects missing declared
sources, and checks settled `greater` ladders for logical contradictions. An
acronym match is only a candidate alias; it must share one normalized declared
source URL domain before alerting.

## Known validation limits

1. C1's effective unit is the information event: the saved snapshot contains
   nine, not 132 independent observations.
2. C1 has no absolute score floor and permits a three-sample minimum null under
   the current implementation. Its 95th-percentile score must not be described
   as a calibrated 5% false-positive rate.
3. C3 uses aggregate open interest and cannot establish common beneficial
   ownership or self-trading.
4. The v1.1 saved-snapshot re-analysis is not prospective validation. Publish a
   new public-API run separately, with its run ID, input fingerprint, parameter
   hash, source release, and freshly recorded dispositions.
