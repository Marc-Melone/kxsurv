from kxsurv.controls.c3_oi_divergence import divergence_series, liquidity_tier


def test_matched_open_close_yields_low_divergence():
    c = [{"end_period_ts": 3600, "volume_fp": 0.0, "open_interest_fp": 100.0},
         {"end_period_ts": 7200, "volume_fp": 50.0, "open_interest_fp": 150.0}]
    out = divergence_series(c, epsilon=1.0)
    assert len(out) == 1
    assert out[0]["d"] < 1.1          # 50 / (50 + 1)


def test_flat_oi_with_volume_yields_high_divergence():
    c = [{"end_period_ts": 3600, "volume_fp": 0.0, "open_interest_fp": 880.49},
         {"end_period_ts": 7200, "volume_fp": 101.0, "open_interest_fp": 880.49}]
    out = divergence_series(c, epsilon=1.0)
    assert out[0]["delta_oi"] == 0.0
    assert out[0]["d"] == 101.0


def test_zero_volume_periods_are_skipped():
    c = [{"end_period_ts": 3600, "volume_fp": 0.0, "open_interest_fp": 100.0},
         {"end_period_ts": 7200, "volume_fp": 0.0, "open_interest_fp": 100.0}]
    assert divergence_series(c, epsilon=1.0) == []


def test_first_candle_has_no_predecessor_and_is_skipped():
    c = [{"end_period_ts": 3600, "volume_fp": 500.0, "open_interest_fp": 100.0}]
    assert divergence_series(c, epsilon=1.0) == []


def test_liquidity_tiers_partition_by_open_interest():
    tiers = [100.0, 1000.0, 10000.0]
    assert liquidity_tier(50.0, tiers) == 0
    assert liquidity_tier(500.0, tiers) == 1
    assert liquidity_tier(5000.0, tiers) == 2
    assert liquidity_tier(50000.0, tiers) == 3


# --- temporal adjacency (fix 2026-09-07) -----------------------------------
# The first implementation counted "consecutive periods" over the volume-
# filtered list, so observations separated by multi-day gaps counted as
# consecutive.

from kxsurv.db import upsert_candles, upsert_markets
from kxsurv.controls.c3_oi_divergence import coverage, run
from kxsurv.params import register
from tests.fixtures import candle, market

P = {"version": "t", "c3_oi_divergence": {
    "min_candle_volume": 50.0, "percentile_threshold": 0.0,
    "min_persistence_periods": 2, "liquidity_tiers": [100.0], "epsilon": 1.0}}
H = 3600


def _seed_market(conn):
    upsert_markets(conn, [market("K1", "K1-E", 1.0)])


def test_adjacent_hours_form_a_run(conn):
    register(conn, P)
    _seed_market(conn)
    upsert_candles(conn, [
        candle("K1", 1 * H, 0, 500),
        candle("K1", 2 * H, 900, 500),     # flat OI, high volume
        candle("K1", 3 * H, 900, 500),     # adjacent hour, still flat
    ])
    out = run(conn, P)
    assert len(out) == 1
    assert out[0].evidence["periods"] == 2


def test_a_36_day_gap_is_not_a_run(conn):
    """A multi-day gap must not satisfy the persistence requirement."""
    register(conn, P)
    _seed_market(conn)
    upsert_candles(conn, [
        candle("K1", 1 * H, 0, 500),
        candle("K1", 2 * H, 900, 500),
        candle("K1", 866 * H, 900, 500),   # 36 days later
    ])
    assert run(conn, P) == [], "non-adjacent periods must not form a run"


def test_a_single_missing_hour_breaks_the_run(conn):
    register(conn, P)
    _seed_market(conn)
    upsert_candles(conn, [
        candle("K1", 1 * H, 0, 500),
        candle("K1", 2 * H, 900, 500),
        candle("K1", 4 * H, 900, 500),     # hour 3 absent
    ])
    assert run(conn, P) == []


def test_missing_predecessor_does_not_create_a_divergence_observation():
    candles = [
        {"end_period_ts": 1 * H, "volume_fp": 0.0, "open_interest_fp": 500.0},
        {"end_period_ts": 3 * H, "volume_fp": 900.0, "open_interest_fp": 500.0},
    ]
    assert divergence_series(candles, epsilon=1.0) == []


def test_coverage_uses_the_same_population_as_control_scoring(conn):
    register(conn, P)
    _seed_market(conn)
    upsert_candles(conn, [
        candle("K1", 1 * H, 0, 500),
        candle("K1", 2 * H, 900, 500),
        candle("K1", 3 * H, 900, 500),
    ])
    assert coverage(conn, P) == {"scoreable": 2, "percentile_qualified": 2}
