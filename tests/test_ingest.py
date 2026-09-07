from kxsurv.db import upsert_trades, upsert_candles
from kxsurv.ingest import check_completeness
from tests.fixtures import trade, candle


def test_completeness_passes_when_tape_matches_candles(conn):
    upsert_trades(conn, [trade("t1", "K1", "2026-08-12T09:00:00Z", 600, 0.5),
                         trade("t2", "K1", "2026-08-12T10:00:00Z", 400, 0.5)])
    upsert_candles(conn, [candle("K1", 100, 1000, 5000)])
    ok, div = check_completeness(conn, "K1")
    assert ok is True
    assert div == 0.0


def test_completeness_tolerates_boundary_divergence(conn):
    # observed real-world divergence was 1.08%, attributable to window edges
    upsert_trades(conn, [trade("t1", "K1", "2026-08-12T09:00:00Z", 989, 0.5)])
    upsert_candles(conn, [candle("K1", 100, 1000, 5000)])
    ok, div = check_completeness(conn, "K1", tolerance_pct=2.0)
    assert ok is True
    assert 1.0 < div < 1.2


def test_completeness_fails_on_truncated_tape(conn):
    upsert_trades(conn, [trade("t1", "K1", "2026-08-12T09:00:00Z", 500, 0.5)])
    upsert_candles(conn, [candle("K1", 100, 1000, 5000)])
    ok, div = check_completeness(conn, "K1", tolerance_pct=2.0)
    assert ok is False
    assert div == 50.0


def test_completeness_records_result_in_ingest_log(conn):
    upsert_trades(conn, [trade("t1", "K1", "2026-08-12T09:00:00Z", 1000, 0.5)])
    upsert_candles(conn, [candle("K1", 100, 1000, 5000)])
    check_completeness(conn, "K1")
    row = conn.execute(
        "SELECT tape_volume, candle_volume, complete FROM ingest_log"
    ).fetchone()
    assert row == (1000.0, 1000.0, 1)
