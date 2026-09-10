from datetime import datetime, timezone

from kxsurv.db import upsert_trades, upsert_candles
from kxsurv.ingest import check_completeness
from tests.fixtures import trade, candle

T0 = "2026-08-12T09:00:00Z"
TS0 = int(datetime.fromisoformat(T0.replace("Z", "+00:00")).timestamp())
TS1 = TS0 + 3600          # one hour after the first trade
TS_OLD = TS0 - 30 * 86400  # a month before the tape begins


def test_completeness_passes_when_tape_matches_candles(conn):
    upsert_trades(conn, [trade("t1", "K1", T0, 600, 0.5),
                         trade("t2", "K1", "2026-08-12T10:00:00Z", 400, 0.5)])
    upsert_candles(conn, [candle("K1", TS1, 1000, 5000)])
    ok, div = check_completeness(conn, "K1")
    assert ok is True
    assert div == 0.0


def test_completeness_tolerates_boundary_divergence(conn):
    # observed real-world divergence was 1.08%, attributable to window edges
    upsert_trades(conn, [trade("t1", "K1", T0, 989, 0.5)])
    upsert_candles(conn, [candle("K1", TS1, 1000, 5000)])
    ok, div = check_completeness(conn, "K1", tolerance_pct=2.0)
    assert ok is True
    assert 1.0 < div < 1.2


def test_completeness_fails_on_truncated_tape(conn):
    upsert_trades(conn, [trade("t1", "K1", T0, 500, 0.5)])
    upsert_candles(conn, [candle("K1", TS1, 1000, 5000)])
    ok, div = check_completeness(conn, "K1", tolerance_pct=2.0)
    assert ok is False
    assert div == 50.0


def test_completeness_records_result_in_ingest_log(conn):
    upsert_trades(conn, [trade("t1", "K1", T0, 1000, 0.5)])
    upsert_candles(conn, [candle("K1", TS1, 1000, 5000)])
    check_completeness(conn, "K1")
    row = conn.execute(
        "SELECT tape_volume, candle_volume, complete FROM ingest_log"
    ).fetchone()
    assert row == (1000.0, 1000.0, 1)


def test_candles_predating_the_tape_are_not_counted_as_divergence(conn):
    """The saved 2026-09-07 acquisition used the live trade tier only; its
    retrieved trades covered ~66 days while candles covered ~89 days.

    Reconciling a 66-day tape against 89 days of candles produced spurious
    failures on 261 of 408 markets. Completeness must be measured only over the
    window the tape actually covers.
    """
    upsert_candles(conn, [
        candle("K1", TS_OLD, 500, 100),   # predates the tape entirely
        candle("K1", TS1, 1000, 600),     # inside the tape window
    ])
    upsert_trades(conn, [trade("t1", "K1", T0, 1000, 0.5)])
    ok, div = check_completeness(conn, "K1")
    assert ok is True, "candles older than the first trade must be excluded"
    assert div == 0.0


def test_market_with_candles_but_no_tape_is_flagged_not_failed(conn):
    """No retrieved trades is a coverage fact, not automatically a truncation
    failure; C3 can still score the candle data."""
    upsert_candles(conn, [candle("K1", TS_OLD, 157, 100)])
    ok, div = check_completeness(conn, "K1")
    assert ok is True
    row = conn.execute("SELECT tape_volume, complete FROM ingest_log").fetchone()
    assert row[0] == 0.0 and row[1] == 1
