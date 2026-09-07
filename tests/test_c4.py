from kxsurv.controls.c4_monotonicity import find_inversions

# strike, mid, half_spread
CLEAN = [(0.1, 0.94, 0.005), (0.2, 0.92, 0.005), (0.3, 0.875, 0.005)]


def test_monotone_ladder_yields_no_inversions():
    assert find_inversions(CLEAN, min_inversion=0.01,
                           require_exceeds_half_spread=True) == []


def test_detects_planted_inversion_beyond_spread():
    rows = [(0.1, 0.90, 0.005), (0.2, 0.95, 0.005), (0.3, 0.80, 0.005)]
    out = find_inversions(rows, min_inversion=0.01,
                          require_exceeds_half_spread=True)
    assert len(out) == 1
    assert out[0]["lower_strike"] == 0.1
    assert out[0]["upper_strike"] == 0.2
    assert abs(out[0]["magnitude"] - 0.05) < 1e-9


def test_ignores_one_cent_inversion_inside_the_spread():
    """The real KXPAYROLLS-26SEP case: 50000 @ 0.5350 below 60000 @ 0.5450.

    A 1c inversion sitting inside the combined half-spread is quote staleness,
    not distortion. This is the project's worked no-action example.
    """
    rows = [(50000.0, 0.5350, 0.010), (60000.0, 0.5450, 0.010)]
    assert find_inversions(rows, min_inversion=0.01,
                           require_exceeds_half_spread=True) == []


def test_same_case_surfaces_when_spread_filter_disabled():
    rows = [(50000.0, 0.5350, 0.010), (60000.0, 0.5450, 0.010)]
    out = find_inversions(rows, min_inversion=0.01,
                          require_exceeds_half_spread=False)
    assert len(out) == 1


def test_equal_prices_are_not_an_inversion():
    rows = [(0.1, 0.50, 0.005), (0.2, 0.50, 0.005)]
    assert find_inversions(rows, min_inversion=0.01,
                           require_exceeds_half_spread=True) == []


# --- snapshot consistency (fix 2026-09-07) ---------------------------------
# An earlier implementation took each strike's most recent quote independently.
# Across 28 events, 12 had strike quotes spanning >24h (worst: 194h), so the
# control compared a strike quoted eight days ago against one quoted an hour
# ago. Monotonicity is only meaningful on a simultaneous snapshot.

from kxsurv.db import upsert_markets, upsert_candles
from kxsurv.controls.c4_monotonicity import snapshots, run
from kxsurv.params import register
from tests.fixtures import market, candle


def _ladder(conn, event="KXT-26SEP", strikes=(0.1, 0.2, 0.3)):
    upsert_markets(conn, [market(f"{event}-T{s}", event, s, status="active",
                                 result="") for s in strikes])


def test_snapshots_group_quotes_by_candle_period(conn):
    _ladder(conn)
    for ts in (1000, 2000):
        upsert_candles(conn, [
            candle("KXT-26SEP-T0.1", ts, 0, 0, bid=0.90, ask=0.92),
            candle("KXT-26SEP-T0.2", ts, 0, 0, bid=0.80, ask=0.82),
            candle("KXT-26SEP-T0.3", ts, 0, 0, bid=0.70, ask=0.72),
        ])
    snaps = snapshots(conn, "KXT-26SEP")
    assert [s[0] for s in snaps] == [1000, 2000]
    assert len(snaps[0][1]) == 3


def test_strike_quoted_in_a_different_period_is_not_compared(conn):
    """The core bug: a stale strike must not be compared against a fresh one."""
    _ladder(conn)
    upsert_candles(conn, [
        candle("KXT-26SEP-T0.1", 1000, 0, 0, bid=0.90, ask=0.92),
        candle("KXT-26SEP-T0.2", 9000, 0, 0, bid=0.99, ask=0.99),  # 8 days later
    ])
    for ts, rows in snapshots(conn, "KXT-26SEP"):
        assert len(rows) == 1, "strikes from different periods must not co-occur"


def test_run_requires_the_inversion_to_persist_across_snapshots(conn):
    """min_persistence_snapshots was previously untestable; now it bites."""
    P = {"version": "t", "c4_monotonicity": {
        "min_inversion_dollars": 0.01, "require_exceeds_half_spread": True,
        "min_persistence_snapshots": 2}}
    register(conn, P)
    _ladder(conn)
    # snapshot 1: clean.  snapshot 2: inverted.  -> only 1 snapshot inverted
    upsert_candles(conn, [
        candle("KXT-26SEP-T0.1", 1000, 0, 0, bid=0.90, ask=0.91),
        candle("KXT-26SEP-T0.2", 1000, 0, 0, bid=0.80, ask=0.81),
        candle("KXT-26SEP-T0.1", 2000, 0, 0, bid=0.70, ask=0.71),
        candle("KXT-26SEP-T0.2", 2000, 0, 0, bid=0.90, ask=0.91),
    ])
    assert run(conn, P) == [], "a single inverted snapshot must not alert"

    # snapshot 3 also inverted -> 2 consecutive, alert fires
    upsert_candles(conn, [
        candle("KXT-26SEP-T0.1", 3000, 0, 0, bid=0.70, ask=0.71),
        candle("KXT-26SEP-T0.2", 3000, 0, 0, bid=0.90, ask=0.91),
    ])
    out = run(conn, P)
    assert len(out) == 1
    assert out[0].evidence["snapshots_persisted"] == 2
    # the run's bounds live on the Alert; evidence carries the peak snapshot
    assert (out[0].window_start, out[0].window_end) == ("2000", "3000")
    assert out[0].evidence["peak_snapshot_ts"] == 2000


def test_distinct_strike_pairs_in_one_window_are_distinct_alerts(conn):
    """Alerts are deduplicated on (control, target, window, params_hash). If
    `target` were only the event, simultaneous inversions at different strikes
    would silently collapse -- 4 real alerts were lost this way."""
    P = {"version": "t", "c4_monotonicity": {
        "min_inversion_dollars": 0.01, "require_exceeds_half_spread": True,
        "min_persistence_snapshots": 1}}
    register(conn, P)
    upsert_markets(conn, [market(f"KXT-26SEP-T{s}", "KXT-26SEP", s,
                                 status="active", result="")
                          for s in (0.1, 0.2, 0.3, 0.4)])
    # two separate inversions in the SAME snapshot: 0.1>0.2 and 0.3>0.4
    upsert_candles(conn, [
        candle("KXT-26SEP-T0.1", 1000, 0, 0, bid=0.60, ask=0.61),
        candle("KXT-26SEP-T0.2", 1000, 0, 0, bid=0.80, ask=0.81),
        candle("KXT-26SEP-T0.3", 1000, 0, 0, bid=0.30, ask=0.31),
        candle("KXT-26SEP-T0.4", 1000, 0, 0, bid=0.50, ask=0.51),
    ])
    out = run(conn, P)
    assert len(out) == 2
    assert len({a.target for a in out}) == 2, "targets must be distinguishable"
