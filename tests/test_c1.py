from kxsurv.controls.c1_prerelease import aggressor_direction, informed_flow_score


def t(size, taker_side):
    return {"count_fp": size, "taker_side": taker_side}


def test_aggressor_direction_validated_semantics():
    """taker_side == 'yes' means the aggressor BOUGHT YES.

    Validated 2026-09-07 on KXCPI-26JUL-T0.3 (686 trades, result='no'):
    signed volume agreed with realised price direction in 5/5 blocks.
    """
    assert aggressor_direction("yes", settled_yes=True) == 1
    assert aggressor_direction("no", settled_yes=True) == -1
    assert aggressor_direction("no", settled_yes=False) == 1
    assert aggressor_direction("yes", settled_yes=False) == -1


def test_consensus_flow_scores_near_zero():
    """Buying the eventual winner at 0.99 is consensus, not information."""
    s = informed_flow_score([t(100, "yes")], p0=0.99, settled_yes=True)
    assert abs(s - 0.01) < 1e-9


def test_flow_from_an_unlikely_price_scores_high():
    s = informed_flow_score([t(100, "yes")], p0=0.20, settled_yes=True)
    assert abs(s - 0.80) < 1e-9


def test_flow_away_from_the_outcome_scores_negative():
    s = informed_flow_score([t(100, "no")], p0=0.20, settled_yes=True)
    assert abs(s + 0.80) < 1e-9


def test_score_is_size_weighted():
    trades = [t(900, "yes"), t(100, "no")]
    s = informed_flow_score(trades, p0=0.50, settled_yes=True)
    assert abs(s - 0.40) < 1e-9      # (900-100)/1000 * 0.5


def test_late_consensus_trade_is_discounted_at_its_own_execution_price():
    trade = {"count_fp": 100, "taker_side": "yes", "yes_price": 0.99}
    assert abs(informed_flow_score([trade], p0=0.20, settled_yes=True) - 0.01) < 1e-9


def test_empty_window_scores_zero():
    assert informed_flow_score([], p0=0.5, settled_yes=True) == 0.0


# --- end-to-end fixture validation (fix 2026-09-07) ------------------------
# The framework states C1 is "validated by fixture detection behaviour", but no
# test drove run() against a database. These plant a signature and assert the
# control fires, and plant a clean tape and assert it does not.

from datetime import datetime, timedelta, timezone

from kxsurv.db import upsert_markets, upsert_trades, upsert_candles
from kxsurv.controls.c1_prerelease import run
from kxsurv.events import build_events
from kxsurv.params import register
from tests.fixtures import market, trade, candle

HALT = "2026-08-12T12:25:00Z"
H = datetime(2026, 8, 12, 12, 25, tzinfo=timezone.utc)
P1 = {"version": "t", "c1_prerelease": {
    "window_minutes": 120, "null_windows": 6, "percentile_threshold": 95.0,
    "min_window_volume": 100.0}}


def _setup(conn, informed: bool):
    register(conn, P1)
    upsert_markets(conn, [market("KXCPI-26AUG-T1", "KXCPI-26AUG", 1.0,
                                 result="yes", close_time=HALT)])
    conn.execute("INSERT OR REPLACE INTO ingest_log (ticker, tape_volume,"
                 " candle_volume, divergence_pct, complete, checked_at)"
                 " VALUES ('KXCPI-26AUG-T1', 1.0, 1.0, 0.0, 1, 'x')")
    # quote at 0.20 throughout: the outcome is NOT priced in, so surprise is high
    for i in range(0, 9):
        ts = int((H - timedelta(minutes=120 * i)).timestamp())
        upsert_candles(conn, [candle("KXCPI-26AUG-T1", ts, 0, 0, bid=0.19, ask=0.21)])
    # null windows: balanced flow
    tid = 0
    for i in range(1, 7):
        base = H - timedelta(minutes=120 * i)
        for side in ("yes", "no"):
            tid += 1
            upsert_trades(conn, [trade(f"n{tid}", "KXCPI-26AUG-T1",
                                       (base - timedelta(minutes=60)).isoformat().replace("+00:00", "Z"),
                                       200, 0.20, taker_side=side)])
    # test window
    sides = ("yes", "yes") if informed else ("yes", "no")
    for k, side in enumerate(sides):
        upsert_trades(conn, [trade(f"t{k}", "KXCPI-26AUG-T1",
                                   (H - timedelta(minutes=60)).isoformat().replace("+00:00", "Z"),
                                   300, 0.20, taker_side=side)])
    build_events(conn)


def test_planted_informed_flow_fires_the_control(conn):
    _setup(conn, informed=True)
    out = run(conn, P1)
    assert len(out) == 1, "one-sided flow toward the outcome from 0.20 must alert"
    assert out[0].score > 0.5
    assert out[0].evidence["halt_to_release_minutes"] == 5.0


def test_matched_clean_tape_does_not_fire(conn):
    _setup(conn, informed=False)
    assert run(conn, P1) == [], "balanced flow must not alert"


# --- coverage funnel (added 2026-09-07 second review) ----------------------
# The published rate "4/77 = 5.2%" was computed by an ad-hoc script using a
# different filter than the control's own pipeline. The real denominator is the
# number of markets C1 actually scores, and it must come from the control.

from kxsurv.controls.c1_prerelease import coverage


def test_coverage_accounts_for_every_market_considered(conn):
    _setup(conn, informed=True)
    cov = coverage(conn, P1)
    assert cov["scored"] == 1
    assert sum(cov[k] for k in
               ("no_result", "gate_blocked", "low_volume", "no_p0",
                "null_too_small", "scored")) == cov["considered"]


def test_unsettled_markets_are_reported_not_silently_dropped(conn):
    _setup(conn, informed=True)
    upsert_markets(conn, [market("KXCPI-26AUG-T2", "KXCPI-26AUG", 2.0,
                                 status="active", result="", close_time=HALT)])
    cov = coverage(conn, P1)
    assert cov["no_result"] == 1
    assert cov["scored"] == 1
