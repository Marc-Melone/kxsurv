"""Entry point: explicitly register, ingest, or locally re-run controls."""
from __future__ import annotations

import argparse
import sys
import time

from .api import KalshiPublic
from .controls import run_control
from .controls import (c1_prerelease, c2_prehalt, c3_oi_divergence,
                       c4_monotonicity, c5_settlement)
from .db import connect, init_schema
from .events import build_events
from .ingest import ingest_series
from .params import load_params, register, verify
from .runs import (begin_run, begin_snapshot_refresh, fail_run,
                   fail_snapshot_refresh, finish_run, finish_snapshot_refresh,
                   reset_snapshot_inputs, verify_snapshot_ready)
from .controls.c1_prerelease import coverage as c1_coverage
from .controls.c3_oi_divergence import coverage as c3_coverage
from .export import write_export
from .report import funnel_markdown
from .validation import timestamp_us

SERIES = ["KXCPI", "KXCPIYOY", "KXPAYROLLS", "KXU3", "KXFED"]
DEFAULT_DB_PATH = "out/kxsurv.db"
CONTROLS = [c4_monotonicity, c3_oi_divergence, c1_prerelease,
            c2_prehalt, c5_settlement]
# Trades can legitimately be absent in an acquisition window, and an empty
# settlement-source inventory is itself a C5 condition. Do not mistake either
# condition for an incomplete snapshot.
REQUIRED_SNAPSHOT_TABLES = ("markets", "events", "candles", "ingest_log")


def _validate_snapshot(conn, selected_series) -> None:
    """Require a structurally complete database scoped to requested series."""
    selected = set(selected_series)
    missing = [table for table in REQUIRED_SNAPSHOT_TABLES
               if conn.execute("SELECT COUNT(*) FROM {}".format(table)).fetchone()[0] == 0]
    if missing:
        raise RuntimeError(
            "snapshot is incomplete; missing {}".format(", ".join(missing)))
    unlogged = conn.execute(
        "SELECT COUNT(*) FROM markets m LEFT JOIN ingest_log i USING(ticker)"
        " WHERE i.ticker IS NULL"
    ).fetchone()[0]
    if unlogged:
        raise RuntimeError(
            "snapshot is incomplete; {} market(s) are missing a completeness record"
            .format(unlogged))

    stored = {row[0] for row in conn.execute(
        "SELECT DISTINCT series_ticker FROM markets WHERE series_ticker IS NOT NULL"
    ).fetchall()}
    extra = sorted(stored - selected)
    if extra:
        raise RuntimeError(
            "snapshot contains unrequested market series: {}; use a separate database "
            "or select the complete stored scope".format(", ".join(extra)))
    if conn.execute(
            "SELECT COUNT(*) FROM markets WHERE series_ticker IS NULL").fetchone()[0]:
        raise RuntimeError("snapshot contains market(s) without a series ticker")

    extra_sources = [row[0] for row in conn.execute(
        "SELECT DISTINCT series_ticker FROM settlement_sources WHERE series_ticker NOT IN ({})"
        .format(",".join("?" * len(selected))), tuple(sorted(selected))
    ).fetchall()]
    if extra_sources:
        raise RuntimeError(
            "snapshot contains settlement metadata for unrequested series: {}"
            .format(", ".join(sorted(extra_sources))))

    for table in ("trades", "candles", "ingest_log"):
        orphaned = conn.execute(
            "SELECT COUNT(*) FROM {} x LEFT JOIN markets m ON m.ticker = x.ticker"
            " WHERE m.ticker IS NULL".format(table)
        ).fetchone()[0]
        if orphaned:
            raise RuntimeError(
                "snapshot contains {} orphaned {} row(s)".format(orphaned, table))

    issues = []
    for series in selected_series:
        market_count = conn.execute(
            "SELECT COUNT(*) FROM markets WHERE series_ticker = ?", (series,)
        ).fetchone()[0]
        event_count = conn.execute(
            "SELECT COUNT(DISTINCT e.event_ticker) FROM events e"
            " JOIN markets m ON m.event_ticker = e.event_ticker"
            " WHERE e.series_ticker = ? AND m.series_ticker = ?", (series, series)
        ).fetchone()[0]
        candle_count = conn.execute(
            "SELECT COUNT(*) FROM candles c JOIN markets m ON m.ticker = c.ticker"
            " WHERE m.series_ticker = ?", (series,)
        ).fetchone()[0]
        missing_logs = conn.execute(
            "SELECT COUNT(*) FROM markets m LEFT JOIN ingest_log i USING(ticker)"
            " WHERE m.series_ticker = ? AND i.ticker IS NULL", (series,)
        ).fetchone()[0]
        if market_count == 0:
            issues.append("{} has no markets".format(series))
        if event_count == 0:
            issues.append("{} has no events".format(series))
        if candle_count == 0:
            issues.append("{} has no candles".format(series))
        if missing_logs:
            issues.append("{} has {} market(s) without completeness records".format(
                series, missing_logs))
    if issues:
        raise RuntimeError(
            "snapshot is incomplete for requested series: {}".format("; ".join(issues)))


def _selected_series(series) -> list[str]:
    selected = list(SERIES if series is None else series)
    if not selected or any(not isinstance(item, str) or not item.strip()
                           for item in selected):
        raise ValueError("at least one non-empty series ticker is required")
    selected = [item.strip().upper() for item in selected]
    if len(set(selected)) != len(selected):
        raise ValueError("series tickers must be unique")
    return selected


def main(skip_ingest: bool = False, register_params: bool = False,
         db_path: str = DEFAULT_DB_PATH, series=None,
         export_path: str | None = None, export_run_id: int | None = None,
         start_time: str | None = None, end_time: str | None = None) -> int:
    bounds = {}
    if start_time is not None or end_time is not None:
        if not start_time or not end_time:
            raise ValueError("--start and --end must be supplied together")
        if skip_ingest or register_params or export_path:
            raise ValueError("--start/--end apply only to a new acquisition")
        start_us, end_us = timestamp_us(start_time), timestamp_us(end_time)
        if start_us % 3_600_000_000 or end_us % 3_600_000_000:
            raise ValueError("acquisition bounds must align to whole UTC hours")
        if start_us >= end_us or end_us > int(time.time()) * 1_000_000:
            raise ValueError("acquisition must be a non-empty, completed interval")
        bounds = {"start_ts": start_us // 1_000_000, "end_ts": end_us // 1_000_000}
    params = load_params("config/params.yaml")
    selected_series = _selected_series(series)
    conn = connect(db_path)
    init_schema(conn)
    if export_path:
        # Publishing reads an existing run. It never registers parameters,
        # contacts the API, or opens a run of its own.
        doc = write_export(conn, export_path, export_run_id, params)
        run = doc["run"]
        print("exported run {} ({} alerts, {} triaged) to {}".format(
            run["run_id"], doc["funnel"]["generated"],
            doc["funnel"]["triaged"], export_path))
        if run["code_drift"]:
            print("warning: working tree code hash differs from the run's")
        if run["source_dirty"]:
            print("warning: working tree has uncommitted changes")
        return 0
    if register_params:
        register(conn, params)
        print("registered parameter version {}".format(params["version"]))
        return 0
    # Fail before an API call or raw-data mutation when the parameters were not
    # explicitly registered in advance.
    verify(conn, params)

    if not skip_ingest:
        refresh_token = begin_snapshot_refresh(conn)
        try:
            reset_snapshot_inputs(conn, refresh_token)
            api = KalshiPublic()
            for s in selected_series:
                result = ingest_series(conn, api, s, **bounds)
                print(result, flush=True)
                if not isinstance(result, dict) or result.get("markets", 0) <= 0:
                    raise RuntimeError(
                        "ingest returned no markets for requested series {}".format(s))
                if result.get("candles", 0) <= 0:
                    raise RuntimeError(
                        "ingest returned no candles for requested series {}".format(s))
            print("events:", build_events(conn))
            c5_settlement.build_inventory(conn, api, selected_series)
            _validate_snapshot(conn, selected_series)
        except Exception as exc:
            fail_snapshot_refresh(conn, refresh_token, exc)
            raise
        else:
            finish_snapshot_refresh(conn, refresh_token)
    else:
        verify_snapshot_ready(conn)
        _validate_snapshot(conn, selected_series)

    expected_controls = [module.CONTROL_ID for module in CONTROLS]
    run_id = begin_run(conn, params, expected_controls)
    try:
        for mod in CONTROLS:
            alerts = run_control(conn, mod, params, run_id)
            print("{}: {} alerts".format(mod.CONTROL_ID, len(alerts)), flush=True)
        finish_run(conn, run_id)
    except Exception as exc:
        # Preserve a failed run record for audit; it is excluded from the
        # default funnel because it is not complete.
        fail_run(conn, run_id, exc)
        raise

    print()
    print("C1 coverage:", c1_coverage(conn, params))
    print("C3 population:", c3_coverage(conn, params))
    print()
    print(funnel_markdown(conn, run_id))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run kxsurv against a registered parameter set and data snapshot.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--skip-ingest", action="store_true",
                       help="run locally against an existing snapshot; make no API calls")
    group.add_argument("--register-params", action="store_true",
                       help="explicitly register the current new parameter version, then exit")
    group.add_argument("--export", metavar="PATH", default=None,
                       help="write a complete run to PATH as a published results artifact")
    parser.add_argument("--db", default=DEFAULT_DB_PATH,
                        help="SQLite database path (default: %(default)s)")
    parser.add_argument("--run", type=int, default=None, metavar="N",
                        help="run to export (default: the latest complete run)")
    parser.add_argument("--series", nargs="+", default=None, metavar="TICKER",
                        help="exact database series scope (ingested unless --skip-ingest) "
                             "(default: the five registered series)")
    parser.add_argument("--start", help="fixed acquisition start (UTC hour, ISO 8601)")
    parser.add_argument("--end", help="fixed acquisition end (UTC hour, ISO 8601)")
    args = parser.parse_args()
    sys.exit(main(skip_ingest=args.skip_ingest, register_params=args.register_params,
                  db_path=args.db, series=args.series,
                  export_path=args.export, export_run_id=args.run,
                  start_time=args.start, end_time=args.end))
