"""Regression examples from the resume-readiness review."""
from datetime import datetime, timezone

import pytest

from kxsurv.api import KalshiPublic
from kxsurv.controls.c1_prerelease import _mid_at, _trades_between
from kxsurv.db import init_schema, upsert_candles, upsert_markets, upsert_trades
from kxsurv.export import ExportError, export_run
from kxsurv.runs import (begin_snapshot_refresh, finish_snapshot_refresh,
                         reset_snapshot_inputs)
from kxsurv.validation import timestamp_us
from tests.fixtures import candle, market, trade
from tests.test_c2 import P2, _mk, run as run_c2
from tests.test_export import P, _complete_run


def test_old_run_export_cannot_borrow_a_new_snapshots_corpus(conn):
    upsert_markets(conn, [market("OLD", "KXCPI-OLD", 1)])
    run_id = _complete_run(conn)
    token = begin_snapshot_refresh(conn)
    reset_snapshot_inputs(conn, token)
    upsert_markets(conn, [market("NEW1", "KXFED-NEW", 1),
                          market("NEW2", "KXFED-NEW", 2)])
    finish_snapshot_refresh(conn, token)
    with pytest.raises(ExportError, match="inputs do not match"):
        export_run(conn, run_id)


def test_export_rejects_different_parameters_for_same_snapshot(conn):
    run_id = _complete_run(conn)
    changed = dict(P, c4_monotonicity={"min_inversion_dollars": 0.10})
    with pytest.raises(ExportError, match="parameters do not match"):
        export_run(conn, run_id, changed)
    assert export_run(conn, run_id, P)["run"]["run_id"] == run_id


def test_export_never_recomputes_old_coverage_with_new_code(conn, monkeypatch):
    run_id = _complete_run(conn)
    monkeypatch.setattr("kxsurv.export.code_hash", lambda: "different-code")
    monkeypatch.setattr("kxsurv.export._coverage",
                        lambda *_: pytest.fail("cannot recalculate old coverage"))
    doc = export_run(conn, run_id)
    assert doc["run"]["code_drift"] is True
    assert doc["coverage"] == {}


def test_fractional_and_offset_timestamps_obey_exact_half_open_windows(conn):
    upsert_trades(conn, [
        trade("before", "K1", "2026-08-12T11:59:59.999999Z", 10, .5),
        trade("start", "K1", "2026-08-12T12:00:00Z", 20, .5),
        trade("inside", "K1", "2026-08-12T08:00:00.500-04:00", 30, .5),
        trade("last", "K1", "2026-08-12T12:29:59.999999Z", 40, .5),
        trade("end", "K1", "2026-08-12T12:30:00Z", 50, .5),
        trade("after", "K1", "2026-08-12T12:30:00.500Z", 60, .5),
    ])
    rows = _trades_between(conn, "K1", datetime(2026, 8, 12, 12, tzinfo=timezone.utc),
                           datetime(2026, 8, 12, 12, 30, tzinfo=timezone.utc))
    assert [r["count_fp"] for r in rows] == [20, 30, 40]


def test_quote_context_does_not_use_trade_after_requested_instant(conn):
    upsert_trades(conn, [
        trade("old", "K1", "2026-08-12T11:59:59Z", 10, .4),
        trade("future", "K1", "2026-08-12T12:00:00.001Z", 10, .9),
    ])
    assert _mid_at(conn, "K1", datetime(2026, 8, 12, 12, tzinfo=timezone.utc)) == .4


def test_c2_excludes_post_halt_trade_that_would_reverse_the_move(conn):
    _mk(conn, ["yes"] * 4, [.40, .45, .50, .55])
    upsert_trades(conn, [trade("late", "KXCPI-26AUG-T1",
                              "2026-08-12T12:25:00.500Z", 100, .01)])
    alerts = run_c2(conn, P2)
    assert len(alerts) == 1
    assert alerts[0].evidence["price_close"] == .55
    assert alerts[0].evidence["trade_count"] == 4


@pytest.mark.parametrize("field,value", [
    ("yes_price_dollars", None), ("yes_price_dollars", "bad"),
    ("yes_price_dollars", "NaN"), ("yes_price_dollars", "Infinity"),
    ("yes_price_dollars", "1.01"), ("no_price_dollars", "-0.1"),
    ("count_fp", None), ("count_fp", "-1"), ("count_fp", "0"),
])
def test_bad_trade_numerics_reject_the_entire_batch(conn, field, value):
    valid = trade("valid", "K1", "2026-08-12T12:00:00Z", 100, .5)
    invalid = dict(valid, trade_id="bad", **{field: value})
    with pytest.raises(ValueError, match=field):
        upsert_trades(conn, [valid, invalid])
    assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [
    ("volume_fp", "bad"), ("open_interest_fp", "NaN"),
    ("volume_fp", "-1"), ("open_interest_fp", None),
    ("end_period_ts", 100.5),
])
def test_bad_candle_numerics_cannot_become_zero(conn, field, value):
    raw = candle("K1", 100, 10, 100)
    raw[field] = value
    with pytest.raises((ValueError, RuntimeError), match=field):
        upsert_candles(conn, [KalshiPublic._canonical_candlestick(raw)])
    assert conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0] == 0


def test_zero_candle_volume_and_nullable_quotes_are_valid(conn):
    upsert_candles(conn, [candle("K1", 100, 0, 0)])
    assert conn.execute("SELECT volume_fp, yes_bid_close FROM candles").fetchone() == (0, None)


def test_naive_trade_timestamp_is_rejected(conn):
    with pytest.raises(ValueError, match="UTC offset"):
        upsert_trades(conn, [trade("bad", "K1", "2026-08-12T12:00:00", 100, .5)])


def test_timestamp_backfill_keeps_original_text(conn):
    row = trade("old", "K1", "2026-08-12T08:00:00.500-04:00", 100, .5)
    upsert_trades(conn, [row])
    conn.execute("DROP INDEX idx_trades_ticker_time_us")
    conn.execute("ALTER TABLE trades DROP COLUMN created_time_us")
    init_schema(conn)
    assert conn.execute("SELECT created_time, created_time_us FROM trades").fetchone() == (
        row["created_time"], timestamp_us("2026-08-12T12:00:00.500Z"))
    init_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1
