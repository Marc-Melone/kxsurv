from kxsurv.controls.c2_prehalt import imbalance_ratio


def t(size, side):
    return {"count_fp": size, "taker_side": side}


def test_balanced_flow_has_low_imbalance():
    ratio, total = imbalance_ratio([t(100, "yes"), t(100, "no")])
    assert ratio == 0.0 and total == 200.0


def test_one_sided_flow_has_maximal_imbalance():
    ratio, total = imbalance_ratio([t(100, "yes"), t(300, "yes")])
    assert ratio == 1.0 and total == 400.0


def test_partial_imbalance_is_proportional():
    ratio, _ = imbalance_ratio([t(850, "yes"), t(150, "no")])
    assert abs(ratio - 0.70) < 1e-9


def test_empty_window_is_zero():
    assert imbalance_ratio([]) == (0.0, 0.0)


# --- end-to-end fixture validation (added 2026-09-07 second review) --------
# C2 reported zero alerts with no test proving it could fire. A silent control
# and a working one are indistinguishable from output alone -- the lesson C4
# taught, applied here.

from datetime import datetime, timedelta, timezone
from kxsurv.db import upsert_markets, upsert_trades
from kxsurv.controls.c2_prehalt import run
from kxsurv.params import register
from tests.fixtures import market, trade

HALT = "2026-08-12T12:25:00Z"
H = datetime(2026, 8, 12, 12, 25, tzinfo=timezone.utc)
P2 = {"version": "t", "c2_prehalt": {
    "window_minutes": 30, "min_imbalance_ratio": 0.70,
    "min_price_displacement": 0.05, "max_thinness_volume": 500.0}}


def _mk(conn, sides, prices):
    register(conn, P2)
    upsert_markets(conn, [market("KXCPI-26AUG-T1", "KXCPI-26AUG", 1.0,
                                 close_time=HALT)])
    conn.execute("INSERT OR REPLACE INTO ingest_log (ticker, tape_volume,"
                 " candle_volume, divergence_pct, complete, checked_at)"
                 " VALUES ('KXCPI-26AUG-T1',1.0,1.0,0.0,1,'x')")
    for i, (side, px) in enumerate(zip(sides, prices)):
        upsert_trades(conn, [trade(f"x{i}", "KXCPI-26AUG-T1",
                                   (H - timedelta(minutes=20 - i * 5))
                                   .isoformat().replace("+00:00", "Z"),
                                   100, px, taker_side=side)])


def test_planted_one_sided_pressure_in_a_thin_market_fires(conn):
    _mk(conn, ["yes"] * 4, [0.40, 0.45, 0.50, 0.55])
    out = run(conn, P2)
    assert len(out) == 1, "one-sided flow displacing price in a thin market must alert"
    assert out[0].evidence["imbalance_ratio"] == 1.0
    assert abs(out[0].evidence["displacement"] - 0.15) < 1e-9
    assert out[0].score == out[0].evidence["displacement"]
    assert out[0].threshold == P2["c2_prehalt"]["min_price_displacement"]
    assert out[0].evidence["registered_gates"]["min_imbalance_ratio"] == 0.70


def test_aggressive_no_buying_aligned_with_falling_yes_price_fires(conn):
    _mk(conn, ["no"] * 4, [0.55, 0.50, 0.45, 0.40])
    out = run(conn, P2)
    assert len(out) == 1
    assert out[0].evidence["signed_imbalance"] == -1.0
    assert out[0].evidence["price_change"] < 0


def test_exact_five_cent_displacement_meets_the_inclusive_floor(conn):
    _mk(conn, ["yes"] * 4, [0.40, 0.41, 0.42, 0.45])
    out = run(conn, P2)
    assert len(out) == 1
    assert out[0].score == 0.05


def test_balanced_flow_does_not_fire(conn):
    _mk(conn, ["yes", "no", "yes", "no"], [0.40, 0.45, 0.50, 0.55])
    assert run(conn, P2) == [], "displacement without imbalance must not alert"


def test_one_sided_flow_without_displacement_does_not_fire(conn):
    _mk(conn, ["yes"] * 4, [0.40, 0.40, 0.40, 0.41])
    assert run(conn, P2) == [], "imbalance without displacement must not alert"


def test_one_sided_flow_against_the_price_move_does_not_fire(conn):
    _mk(conn, ["yes"] * 4, [0.55, 0.50, 0.45, 0.40])
    assert run(conn, P2) == [], "pressure must agree with the direction of flow"


def test_a_liquid_market_is_out_of_scope(conn):
    _mk(conn, ["yes"] * 4, [0.40, 0.45, 0.50, 0.55])
    conn.execute("UPDATE trades SET count_fp = 1000")   # far above thinness cap
    conn.commit()
    assert run(conn, P2) == [], "marking-the-close risk is scoped to thin markets"
