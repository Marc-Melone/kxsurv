import pytest

from kxsurv import cli
from kxsurv.db import upsert_candles, upsert_markets, upsert_trades
from kxsurv.params import ParamsDriftError, register


def _seed_snapshot(conn, series="S", include_candles=True):
    ticker = "{}-T".format(series)
    event = "{}-E".format(series)
    upsert_markets(conn, [{
        "ticker": ticker, "event_ticker": event, "series_ticker": series, "title": "t",
        "status": "finalized", "result": "yes", "close_time": "2026-09-07T00:00:00Z",
        "floor_strike": 1.0, "strike_type": "greater",
    }])
    upsert_trades(conn, [{
        "trade_id": "{}-trade".format(series), "ticker": ticker,
        "created_time": "2026-09-06T23:00:00Z",
        "count_fp": "1", "yes_price_dollars": "0.50", "no_price_dollars": "0.50",
        "taker_outcome_side": "yes",
    }])
    if include_candles:
        upsert_candles(conn, [{
            "ticker": ticker, "end_period_ts": 1, "volume_fp": "1",
            "open_interest_fp": "1",
        }])
    conn.execute(
        "INSERT INTO events (event_ticker, series_ticker, halt_time_utc)"
        " VALUES (?, ?, '2026-09-07T00:00:00Z')", (event, series)
    )
    conn.execute(
        "INSERT INTO settlement_sources (series_ticker, source_name) VALUES (?, 'Source')",
        (series,)
    )
    conn.execute(
        "INSERT INTO ingest_log (ticker, tape_volume, candle_volume, divergence_pct, complete, checked_at)"
        " VALUES (?, 1, ?, 0, 1, 't')", (ticker, 1 if include_candles else 0)
    )
    conn.commit()


class _StubControl:
    CONTROL_ID = "C0"

    @staticmethod
    def run(conn, params):
        return []


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
    _seed_snapshot(conn)

    def forbid_api(*args, **kwargs):
        raise AssertionError("--skip-ingest must not construct an API client")

    monkeypatch.setattr(cli, "load_params", lambda _: params)
    monkeypatch.setattr(cli, "connect", lambda _: conn)
    monkeypatch.setattr(cli, "KalshiPublic", forbid_api)
    monkeypatch.setattr(cli, "CONTROLS", [_StubControl])
    monkeypatch.setattr(cli, "c1_coverage", lambda *_: {})
    monkeypatch.setattr(cli, "c3_coverage", lambda *_: {})
    monkeypatch.setattr(cli, "funnel_markdown", lambda *_: "")

    assert cli.main(skip_ingest=True, series=["S"]) == 0
    assert conn.execute("SELECT status FROM control_runs").fetchone()[0] == "complete"


def test_full_ingest_rejects_an_empty_requested_series_before_run(conn, monkeypatch):
    params = {"version": "cli-empty"}
    register(conn, params)
    monkeypatch.setattr(cli, "load_params", lambda _: params)
    monkeypatch.setattr(cli, "connect", lambda _: conn)
    monkeypatch.setattr(cli, "KalshiPublic", lambda: object())
    monkeypatch.setattr(
        cli, "ingest_series",
        lambda *args: {"series": "EMPTY", "markets": 0, "trades": 0, "candles": 0})

    with pytest.raises(RuntimeError, match="no markets"):
        cli.main(series=["EMPTY"])
    assert conn.execute("SELECT status FROM snapshot_state").fetchone()[0] == "failed"
    assert conn.execute("SELECT COUNT(*) FROM control_runs").fetchone()[0] == 0


def test_finish_validation_failure_marks_the_cli_run_failed(conn, monkeypatch):
    params = {"version": "cli-finish-failure"}
    register(conn, params)
    _seed_snapshot(conn)
    monkeypatch.setattr(cli, "load_params", lambda _: params)
    monkeypatch.setattr(cli, "connect", lambda _: conn)
    monkeypatch.setattr(cli, "CONTROLS", [_StubControl])
    monkeypatch.setattr(cli, "c1_coverage", lambda *_: {})
    monkeypatch.setattr(cli, "c3_coverage", lambda *_: {})
    monkeypatch.setattr(cli, "funnel_markdown", lambda *_: "")
    monkeypatch.setattr(
        cli, "finish_run",
        lambda *_: (_ for _ in ()).throw(RuntimeError("completion rejected")))

    with pytest.raises(RuntimeError, match="completion rejected"):
        cli.main(skip_ingest=True, series=["S"])
    assert conn.execute(
        "SELECT status, failure FROM control_runs"
    ).fetchone() == ("failed", "RuntimeError: completion rejected")


def test_custom_database_and_series_are_used_for_an_oos_run(conn, monkeypatch):
    params = {"version": "cli-oos"}
    register(conn, params)
    calls = {"db": [], "series": [], "inventory": []}

    def connect_at(path):
        calls["db"].append(path)
        return conn

    def ingest_selected(target, api, series):
        calls["series"].append(series)
        _seed_snapshot(target, series)
        return {"series": series, "markets": 1, "candles": 1}

    monkeypatch.setattr(cli, "load_params", lambda _: params)
    monkeypatch.setattr(cli, "connect", connect_at)
    monkeypatch.setattr(cli, "KalshiPublic", lambda: object())
    monkeypatch.setattr(cli, "ingest_series", ingest_selected)
    monkeypatch.setattr(cli, "build_events", lambda *_: 1)
    monkeypatch.setattr(
        cli.c5_settlement, "build_inventory",
        lambda target, api, series: calls["inventory"].extend(series))
    monkeypatch.setattr(cli, "CONTROLS", [_StubControl])
    monkeypatch.setattr(cli, "c1_coverage", lambda *_: {})
    monkeypatch.setattr(cli, "c3_coverage", lambda *_: {})
    monkeypatch.setattr(cli, "funnel_markdown", lambda *_: "")

    assert cli.main(db_path="out/oos.db", series=["kxgdp", "kxhighny"]) == 0
    assert calls == {
        "db": ["out/oos.db"],
        "series": ["KXGDP", "KXHIGHNY"],
        "inventory": ["KXGDP", "KXHIGHNY"],
    }
    for series in calls["series"]:
        assert conn.execute(
            "SELECT COUNT(*) FROM markets WHERE series_ticker = ?", (series,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE series_ticker = ?", (series,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM candles c JOIN markets m ON m.ticker = c.ticker"
            " WHERE m.series_ticker = ?", (series,)
        ).fetchone()[0] == 1


def test_snapshot_validation_cannot_hide_a_candleless_requested_series(conn):
    _seed_snapshot(conn, "S1")
    _seed_snapshot(conn, "S2", include_candles=False)

    with pytest.raises(RuntimeError, match="S2 has no candles"):
        cli._validate_snapshot(conn, ["S1", "S2"])


def test_snapshot_scope_rejects_unrequested_series_that_controls_would_score(conn):
    _seed_snapshot(conn, "S1")
    _seed_snapshot(conn, "S2")

    with pytest.raises(RuntimeError, match="unrequested market series: S2"):
        cli._validate_snapshot(conn, ["S1"])
