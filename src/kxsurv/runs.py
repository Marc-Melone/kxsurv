"""Immutable execution records and input fingerprints for surveillance runs."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .params import params_hash, verify


_SNAPSHOT_TABLES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("trades", ("trade_id", "ticker", "created_time", "count_fp", "yes_price",
                "no_price", "taker_outcome_side", "taker_book_side", "is_block_trade"),
     ("trade_id",)),
    ("candles", ("ticker", "end_period_ts", "volume_fp", "open_interest_fp",
                 "yes_bid_close", "yes_ask_close"), ("ticker", "end_period_ts")),
    ("markets", ("ticker", "event_ticker", "series_ticker", "title", "status",
                 "result", "close_time", "floor_strike", "strike_type"), ("ticker",)),
    ("events", ("event_ticker", "series_ticker", "release_time_utc", "halt_time_utc",
                "outcome_ticker"), ("event_ticker",)),
    ("ingest_log", ("ticker", "tape_volume", "candle_volume", "divergence_pct",
                    "complete"), ("ticker",)),
    ("settlement_sources", ("series_ticker", "source_name", "source_url", "category"),
     ("series_ticker", "source_name")),
)

_READY_SNAPSHOT_STATUSES = frozenset({"ready", "legacy_ready"})


def input_hash(conn) -> str:
    """Hash detector inputs, excluding alerts, dispositions, and parameter history."""
    h = hashlib.sha256()
    for table, columns, order in _SNAPSHOT_TABLES:
        h.update((table + "\0").encode())
        sql = "SELECT {} FROM {} ORDER BY {}".format(
            ", ".join(columns), table, ", ".join(order))
        for row in conn.execute(sql):
            h.update(json.dumps(list(row), separators=(",", ":"), ensure_ascii=True,
                                default=str).encode())
            h.update(b"\n")
    return h.hexdigest()


def code_hash() -> str:
    """Fingerprint the detector code that generated a run's alerts."""
    root = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        h.update(str(path.relative_to(root)).encode())
        h.update(b"\0")
        h.update(path.read_bytes())
    return h.hexdigest()


def begin_snapshot_refresh(conn) -> None:
    """Mark raw data as in-progress before any public-API mutation occurs."""
    conn.execute(
        "INSERT INTO snapshot_state (state_id, status, started_at, completed_at, failure)"
        " VALUES (1, 'refreshing', ?, NULL, NULL)"
        " ON CONFLICT(state_id) DO UPDATE SET status = 'refreshing',"
        " started_at = excluded.started_at, completed_at = NULL, failure = NULL",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()


def finish_snapshot_refresh(conn) -> None:
    cur = conn.execute(
        "UPDATE snapshot_state SET status = 'ready', completed_at = ?"
        " WHERE state_id = 1 AND status = 'refreshing'",
        (datetime.now(timezone.utc).isoformat(),),
    )
    if cur.rowcount != 1:
        conn.rollback()
        raise RuntimeError("cannot mark a non-refreshing snapshot ready")
    conn.commit()


def fail_snapshot_refresh(conn, exc: Exception) -> None:
    cur = conn.execute(
        "UPDATE snapshot_state SET status = 'failed', completed_at = ?, failure = ?"
        " WHERE state_id = 1 AND status = 'refreshing'",
        (datetime.now(timezone.utc).isoformat(),
         "{}: {}".format(type(exc).__name__, exc)),
    )
    if cur.rowcount != 1:
        conn.rollback()
        raise RuntimeError("cannot mark a non-refreshing snapshot failed")
    conn.commit()


def verify_snapshot_ready(conn) -> None:
    """Refuse local control execution against a failed or partial refresh."""
    row = conn.execute(
        "SELECT status, failure FROM snapshot_state WHERE state_id = 1"
    ).fetchone()
    if row is None:
        raise RuntimeError("--skip-ingest requires a completed snapshot; run a full ingest first")
    if row[0] not in _READY_SNAPSHOT_STATUSES:
        suffix = " ({})".format(row[1]) if row[1] else ""
        raise RuntimeError("--skip-ingest refuses snapshot state {}{}; run a full ingest first"
                           .format(row[0], suffix))


def begin_run(conn, params: dict) -> int:
    """Open a run only after its pre-registered parameter set has been verified."""
    verify(conn, params)
    cur = conn.execute(
        "INSERT INTO control_runs (params_hash, input_hash, code_hash, status, started_at)"
        " VALUES (?, ?, ?, 'running', ?)",
        (params_hash(params), input_hash(conn), code_hash(),
         datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn, run_id: int) -> None:
    unfinished = conn.execute(
        "SELECT control_id FROM control_executions WHERE run_id = ?"
        " AND status != 'complete' ORDER BY control_id", (run_id,)
    ).fetchall()
    if unfinished:
        raise RuntimeError("cannot complete run {} while control execution(s) are unfinished: {}"
                           .format(run_id, ", ".join(row[0] for row in unfinished)))
    cur = conn.execute(
        "UPDATE control_runs SET status = 'complete', finished_at = ?"
        " WHERE run_id = ? AND status = 'running'",
        (datetime.now(timezone.utc).isoformat(), run_id))
    if cur.rowcount != 1:
        conn.rollback()
        raise RuntimeError("cannot complete a non-running control run {}".format(run_id))
    conn.commit()


def fail_run(conn, run_id: int, exc: Exception) -> None:
    cur = conn.execute(
        "UPDATE control_runs SET status = 'failed', finished_at = ?, failure = ?"
        " WHERE run_id = ? AND status = 'running'",
        (datetime.now(timezone.utc).isoformat(),
         "{}: {}".format(type(exc).__name__, exc), run_id))
    if cur.rowcount != 1:
        conn.rollback()
        raise RuntimeError("cannot fail a non-running control run {}".format(run_id))
    conn.commit()


def latest_run_id(conn) -> int | None:
    row = conn.execute(
        "SELECT run_id FROM control_runs WHERE status = 'complete'"
        " ORDER BY run_id DESC LIMIT 1").fetchone()
    return int(row[0]) if row else None
