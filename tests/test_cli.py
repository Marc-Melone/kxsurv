import pytest

from kxsurv import cli
from kxsurv.db import upsert_candles, upsert_markets, upsert_trades
from kxsurv.params import ParamsDriftError, register


def test_main_verifies_parameters_before_constructing_an_api_client(conn, monkeypatch):
    params = {"version": "cli-unregistered"}
    calls = []

    def forbid_api(*args, **kwargs):
        calls.append("api")
        raise AssertionError("parameter verification must happen before API construction")

    monkeypatch.setattr(cli, "load_params", lambda _: params)
    monkeypatch.setattr(cli, "connect", lambda _: conn)
    monkeypatch.setattr(cli, "KalshiPublic", forbid_api)
    monkeypatch.setattr(cli, "ingest_series", lambda *args: calls.append("ingest"))

    with pytest.raises(ParamsDriftError):
        cli.main()
    assert calls == []


def test_skip_ingest_runs_locally_without_constructing_an_api_client(conn, monkeypatch):
    params = {"version": "cli-skip"}
    register(conn, params)
    upsert_markets(conn, [{
        "ticker": "T", "event_ticker": "E", "series_ticker": "S", "title": "t",
        "status": "finalized", "result": "yes", "close_time": "2026-09-07T00:00:00Z",
        "floor_strike": 1.0, "strike_type": "greater",
    }])
    upsert_trades(conn, [{
        "trade_id": "t", "ticker": "T", "created_time": "2026-09-06T23:00:00Z",
        "count_fp": "1", "yes_price_dollars": "0.50", "no_price_dollars": "0.50",
        "taker_outcome_side": "yes",
    }])
    upsert_candles(conn, [{
        "ticker": "T", "end_period_ts": 1, "volume_fp": "1", "open_interest_fp": "1",
    }])
    conn.execute(
        "INSERT INTO events (event_ticker, series_ticker, halt_time_utc) VALUES ('E', 'S', '2026-09-07T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO settlement_sources (series_ticker, source_name) VALUES ('S', 'Source')"
    )
    conn.execute(
        "INSERT INTO ingest_log (ticker, tape_volume, candle_volume, divergence_pct, complete, checked_at)"
        " VALUES ('T', 1, 1, 0, 1, 't')"
    )
    conn.commit()

    def forbid_api(*args, **kwargs):
        raise AssertionError("--skip-ingest must not construct an API client")

    monkeypatch.setattr(cli, "load_params", lambda _: params)
    monkeypatch.setattr(cli, "connect", lambda _: conn)
    monkeypatch.setattr(cli, "KalshiPublic", forbid_api)
    # One trivial control, not an empty list: a run that executes nothing
    # cannot complete, and this test is about the API client, not coverage.
    class _StubControl:
        CONTROL_ID = "C0"

        @staticmethod
        def run(conn, params):
            return []

    monkeypatch.setattr(cli, "CONTROLS", [_StubControl])
    monkeypatch.setattr(cli, "c1_coverage", lambda *_: {})
    monkeypatch.setattr(cli, "c3_coverage", lambda *_: {})
    monkeypatch.setattr(cli, "funnel_markdown", lambda *_: "")

    assert cli.main(skip_ingest=True) == 0
    assert conn.execute("SELECT status FROM control_runs").fetchone()[0] == "complete"
