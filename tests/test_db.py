import pytest

from kxsurv.controls import Alert, save_alerts
from kxsurv.db import upsert_trades, upsert_candles, upsert_markets
from kxsurv.params import register
from kxsurv.runs import begin_run

TRADE = {
    "trade_id": "t1", "ticker": "KXCPI-26JUL-T0.3",
    "created_time": "2026-08-12T09:21:12.398879Z",
    "count_fp": "285.68", "yes_price_dollars": "0.9900",
    "no_price_dollars": "0.0100", "taker_side": "yes",
    "taker_book_side": "bid", "is_block_trade": False,
}


def test_trades_roundtrip_preserves_fractional_size(conn):
    upsert_trades(conn, [TRADE])
    row = conn.execute("SELECT count_fp, yes_price FROM trades").fetchone()
    assert row[0] == 285.68
    assert row[1] == 0.99


def test_canonical_taker_outcome_side_is_stored_and_preferred(conn):
    row = dict(TRADE, taker_side="no", taker_outcome_side="yes")
    upsert_trades(conn, [row])
    assert conn.execute("SELECT taker_outcome_side FROM trades").fetchone()[0] == "yes"


def test_trade_without_a_valid_direction_fails_closed(conn):
    row = dict(TRADE, taker_side="")
    with pytest.raises(ValueError, match="outcome side"):
        upsert_trades(conn, [row])


def test_trade_upsert_is_idempotent(conn):
    upsert_trades(conn, [TRADE])
    upsert_trades(conn, [TRADE])
    assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1


def test_trade_id_with_changed_detector_input_fails_closed(conn):
    upsert_trades(conn, [TRADE])
    conflicting = dict(TRADE, yes_price_dollars="0.5000", no_price_dollars="0.5000")
    with pytest.raises(ValueError, match="conflicting detector inputs"):
        upsert_trades(conn, [conflicting])


def test_candle_upsert_is_idempotent_on_composite_key(conn):
    c = {"ticker": "K1", "end_period_ts": 100, "volume_fp": "10",
         "open_interest_fp": "500", "yes_bid": {"close_dollars": "0.40"},
         "yes_ask": {"close_dollars": "0.42"}}
    upsert_candles(conn, [c])
    upsert_candles(conn, [c])
    assert conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0] == 1


def test_market_stores_strike_type_and_result(conn):
    upsert_markets(conn, [{
        "ticker": "KXCPI-26JUL-T0.3", "event_ticker": "KXCPI-26JUL",
        "title": "CPI > 0.3%", "status": "finalized", "result": "no",
        "close_time": "2026-08-12T12:25:00Z", "floor_strike": 0.3,
        "strike_type": "greater",
    }])
    r = conn.execute("SELECT strike_type, result, floor_strike FROM markets").fetchone()
    assert r == ("greater", "no", 0.3)


def test_alerts_and_dispositions_link(conn):
    p = {"version": "db-link-test"}
    register(conn, p)
    run_id = begin_run(conn, p, ("C4",))
    save_alerts(conn, [Alert("C4", "KXCPI-26SEP", None, None, .5, None,
                             None, {})], p, run_id)
    aid = conn.execute("SELECT alert_id FROM alerts").fetchone()[0]
    conn.execute(
        "INSERT INTO dispositions (alert_id, action, rationale, created_at)"
        " VALUES (?,'no_action','within spread','2026-09-07T00:00:00Z')", (aid,))
    n = conn.execute(
        "SELECT COUNT(*) FROM dispositions d JOIN alerts a USING(alert_id)").fetchone()[0]
    assert n == 1
