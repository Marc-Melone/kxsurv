from kxsurv.controls.c4_monotonicity import find_inversions

# strike, bid, ask
CLEAN = [(0.1, 0.935, 0.945), (0.2, 0.915, 0.925),
         (0.3, 0.870, 0.880)]


def test_monotone_ladder_yields_no_inversions():
    assert find_inversions(CLEAN, min_inversion=0.01,
                           require_exceeds_half_spread=True) == []


def test_detects_planted_inversion_beyond_spread():
    rows = [(0.1, 0.895, 0.905), (0.2, 0.945, 0.955),
            (0.3, 0.795, 0.805)]
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
    rows = [(50000.0, 0.525, 0.545), (60000.0, 0.535, 0.555)]
    assert find_inversions(rows, min_inversion=0.01,
                           require_exceeds_half_spread=True) == []


def test_same_case_surfaces_when_spread_filter_disabled():
    rows = [(50000.0, 0.525, 0.545), (60000.0, 0.535, 0.555)]
    out = find_inversions(rows, min_inversion=0.01,
                          require_exceeds_half_spread=False)
    assert len(out) == 1


def test_equal_prices_are_not_an_inversion():
    rows = [(0.1, 0.495, 0.505), (0.2, 0.495, 0.505)]
    assert find_inversions(rows, min_inversion=0.01,
                           require_exceeds_half_spread=True) == []


def test_inversion_equal_to_combined_spread_is_not_an_alert():
    """The remaining OOS C4 candidate was a binary-float boundary error.

    The upper-strike bid equals the lower-strike ask at five cents, so the
    midpoint inversion is exactly equal to the combined half-spread. It does
    not *exceed* the spread and must not alert.
    """
    rows = [(3.0, 0.04, 0.05), (3.5, 0.05, 0.06)]
    assert find_inversions(rows, min_inversion=0.01,
                           require_exceeds_half_spread=True) == []


def test_exact_one_cent_inversion_still_meets_the_minimum_without_spread_gate():
    """Boundary hardening must not silently change the inclusive 1c floor."""
    rows = [(3.0, 0.04, 0.05), (3.5, 0.05, 0.06)]
    out = find_inversions(rows, min_inversion=0.01,
                          require_exceeds_half_spread=False)
    assert len(out) == 1
    assert out[0]["magnitude"] == 0.01


# --- period alignment (fix 2026-09-07) -------------------------------------
# An earlier implementation took each strike's most recent quote independently.
# Across 28 events, 12 had strike quotes spanning >24h (worst: 194h), so the
# control compared a strike quoted eight days ago against one quoted an hour
# ago. A shared hourly endpoint removes that mismatch but does not prove the
# underlying quote updates happened simultaneously within the period.

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
    # hourly periods. 1: clean.  2: inverted.  -> only 1 period inverted
    upsert_candles(conn, [
        candle("KXT-26SEP-T0.1", 1 * 3600, 0, 0, bid=0.90, ask=0.91),
        candle("KXT-26SEP-T0.2", 1 * 3600, 0, 0, bid=0.80, ask=0.81),
        candle("KXT-26SEP-T0.1", 2 * 3600, 0, 0, bid=0.70, ask=0.71),
        candle("KXT-26SEP-T0.2", 2 * 3600, 0, 0, bid=0.90, ask=0.91),
    ])
    assert run(conn, P) == [], "a single inverted period must not alert"

    # period 3, the adjacent hour, also inverted -> 2 consecutive, alert fires
    upsert_candles(conn, [
        candle("KXT-26SEP-T0.1", 3 * 3600, 0, 0, bid=0.70, ask=0.71),
        candle("KXT-26SEP-T0.2", 3 * 3600, 0, 0, bid=0.90, ask=0.91),
    ])
    out = run(conn, P)
    assert len(out) == 1
    assert out[0].evidence["snapshots_persisted"] == 2
    # the run's bounds live on the Alert; evidence carries the peak snapshot
    assert (out[0].window_start, out[0].window_end) == ("7200", "10800")
    assert out[0].evidence["peak_snapshot_ts"] == 7200
    assert out[0].evidence["period_seconds"] == 3600
    assert "do not establish" in out[0].evidence["timing_limitation"]
    assert "within the period" in out[0].evidence["timing_limitation"]


def test_strike_count_describes_the_peak_period(conn):
    """Peak evidence must not borrow a strike count from the firing period."""
    p = {"c4_monotonicity": {
        "min_inversion_dollars": 0.01,
        "require_exceeds_half_spread": False,
        "min_persistence_snapshots": 2,
    }}
    _ladder(conn)
    upsert_candles(conn, [
        candle("KXT-26SEP-T0.1", 3600, 0, 0, bid=.39, ask=.41),
        candle("KXT-26SEP-T0.2", 3600, 0, 0, bid=.59, ask=.61),
        candle("KXT-26SEP-T0.3", 3600, 0, 0, bid=.19, ask=.21),
        candle("KXT-26SEP-T0.1", 7200, 0, 0, bid=.49, ask=.51),
        candle("KXT-26SEP-T0.2", 7200, 0, 0, bid=.59, ask=.61),
    ])
    candidate = next(a for a in run(conn, p)
                     if a.target == "KXT-26SEP:0.1>0.2")
    assert candidate.evidence["peak_snapshot_ts"] == 3600
    assert candidate.evidence["strikes_in_snapshot"] == 3


def test_distinct_strike_pairs_in_one_window_are_distinct_alerts(conn):
    """Alerts are deduplicated on (control, target, window, params_hash). If
    `target` were only the event, same-period inversions at different strikes
    would silently collapse -- 4 real alerts were lost this way."""
    P = {"version": "t", "c4_monotonicity": {
        "min_inversion_dollars": 0.01, "require_exceeds_half_spread": True,
        "min_persistence_snapshots": 1}}
    register(conn, P)
    upsert_markets(conn, [market(f"KXT-26SEP-T{s}", "KXT-26SEP", s,
                                 status="active", result="")
                          for s in (0.1, 0.2, 0.3, 0.4)])
    # two separate inversions in the same period: 0.1>0.2 and 0.3>0.4
    upsert_candles(conn, [
        candle("KXT-26SEP-T0.1", 1000, 0, 0, bid=0.60, ask=0.61),
        candle("KXT-26SEP-T0.2", 1000, 0, 0, bid=0.80, ask=0.81),
        candle("KXT-26SEP-T0.3", 1000, 0, 0, bid=0.30, ask=0.31),
        candle("KXT-26SEP-T0.4", 1000, 0, 0, bid=0.50, ask=0.51),
    ])
    out = run(conn, P)
    assert len(out) == 2
    assert len({a.target for a in out}) == 2, "targets must be distinguishable"


def test_snapshots_far_apart_do_not_form_a_persistent_run(conn):
    """C3 had this defect and it was fixed there; C4 was left unguarded and
    passed only because this corpus happens to be densely quoted."""
    P = {"version": "t", "c4_monotonicity": {
        "min_inversion_dollars": 0.01, "require_exceeds_half_spread": True,
        "min_persistence_snapshots": 2}}
    register(conn, P)
    upsert_markets(conn, [market(f"KXT-26SEP-T{s}", "KXT-26SEP", s,
                                 status="active", result="") for s in (0.1, 0.2)])
    upsert_candles(conn, [
        candle("KXT-26SEP-T0.1", 3600, 0, 0, bid=0.70, ask=0.71),
        candle("KXT-26SEP-T0.2", 3600, 0, 0, bid=0.90, ask=0.91),
        candle("KXT-26SEP-T0.1", 3600 * 200, 0, 0, bid=0.70, ask=0.71),
        candle("KXT-26SEP-T0.2", 3600 * 200, 0, 0, bid=0.90, ask=0.91),
    ])
    assert run(conn, P) == [], "snapshots 199h apart are not consecutive"


def test_only_greater_strikes_enter_the_ladder(conn):
    """Found by an out-of-sample run against KXHIGHNY (2026-09-07).

    run() selected events having at least one 'greater' market, but snapshots()
    filtered only on event_ticker and floor_strike -- so 'between' and 'less'
    contracts in the same event were compared as if they formed one monotone
    ladder. A 'between' contract's probability is not monotone in its floor
    strike. 76 of 77 out-of-sample C4 alerts came from such mixed events. The
    in-sample corpus is 100% 'greater', so this could not surface there.
    """
    P = {"version": "t", "c4_monotonicity": {
        "min_inversion_dollars": 0.01, "require_exceeds_half_spread": True,
        "min_persistence_snapshots": 1}}
    register(conn, P)
    upsert_markets(conn, [
        market("KXM-26SEP-G1", "KXM-26SEP", 0.1, status="active", result=""),
        market("KXM-26SEP-G2", "KXM-26SEP", 0.2, status="active", result=""),
        # a 'between' contract in the same event, priced far above both
        dict(market("KXM-26SEP-B1", "KXM-26SEP", 0.15, status="active", result=""),
             strike_type="between"),
    ])
    upsert_candles(conn, [
        candle("KXM-26SEP-G1", 3600, 0, 0, bid=0.90, ask=0.91),
        candle("KXM-26SEP-G2", 3600, 0, 0, bid=0.80, ask=0.81),
        candle("KXM-26SEP-B1", 3600, 0, 0, bid=0.99, ask=0.99),
    ])
    rows = snapshots(conn, "KXM-26SEP")[0][1]
    assert [r[0] for r in rows] == [0.1, 0.2], \
        "only 'greater' strikes may enter the ladder"
    assert run(conn, P) == [], "the 'between' contract must not create an inversion"
