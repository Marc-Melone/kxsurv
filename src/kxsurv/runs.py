"""Immutable execution records and input fingerprints for surveillance runs."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

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


def begin_snapshot_refresh(conn) -> str:
    """Claim a new raw-data refresh and return its persisted owner token."""
    token = uuid4().hex
    try:
        # Serialize the check with begin_run(). A refresh may not begin after a
        # run has fingerprinted its inputs but before its controls read them.
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT run_id FROM control_runs WHERE status = 'running'"
            " ORDER BY run_id LIMIT 1"
        ).fetchone()
        if active is not None:
            raise RuntimeError(
                "cannot refresh snapshot while control run {} is active".format(active[0]))
        state = conn.execute(
            "SELECT status FROM snapshot_state WHERE state_id = 1"
        ).fetchone()
        if state is not None and state[0] == "refreshing":
            raise RuntimeError(
                "cannot begin snapshot refresh while another refresh is active")
        conn.execute(
            "INSERT INTO snapshot_state (state_id, status, refresh_token, generation,"
            " started_at, completed_at, failure)"
            " VALUES (1, 'refreshing', ?, 1, ?, NULL, NULL)"
            " ON CONFLICT(state_id) DO UPDATE SET status = 'refreshing',"
            " refresh_token = excluded.refresh_token, generation = snapshot_state.generation + 1,"
            " started_at = excluded.started_at, completed_at = NULL, failure = NULL",
            (token, datetime.now(timezone.utc).isoformat()),
        )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return token


def finish_snapshot_refresh(conn, token: str) -> None:
    """Mark a refresh ready only when `token` owns the active generation."""
    cur = conn.execute(
        "UPDATE snapshot_state SET status = 'ready', completed_at = ?"
        " WHERE state_id = 1 AND status = 'refreshing' AND refresh_token = ?",
        (datetime.now(timezone.utc).isoformat(), token),
    )
    if cur.rowcount != 1:
        conn.rollback()
        raise RuntimeError("cannot finish a snapshot refresh not owned by this token")
    conn.commit()


def fail_snapshot_refresh(conn, token: str, exc: Exception) -> None:
    """Mark a refresh failed only when `token` owns the active generation."""
    cur = conn.execute(
        "UPDATE snapshot_state SET status = 'failed', completed_at = ?, failure = ?"
        " WHERE state_id = 1 AND status = 'refreshing' AND refresh_token = ?",
        (datetime.now(timezone.utc).isoformat(),
         "{}: {}".format(type(exc).__name__, exc), token),
    )
    if cur.rowcount != 1:
        conn.rollback()
        raise RuntimeError("cannot fail a snapshot refresh not owned by this token")
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


def _expected_manifest(expected_controls) -> list[str]:
    controls = list(expected_controls)
    if not controls or any(not isinstance(control, str) or not control
                           for control in controls):
        raise ValueError("a run requires at least one non-empty expected control ID")
    if len(set(controls)) != len(controls):
        raise ValueError("expected control IDs must be unique")
    return controls


def begin_run(conn, params: dict, expected_controls) -> int:
    """Open a run with a durable expected-control manifest and input hash.

    A run cannot exist without an explicit ready snapshot marker. Unit and
    library callers must establish that lifecycle state just like the CLI.
    """
    verify(conn, params)
    expected = _expected_manifest(expected_controls)
    try:
        # This lock makes the snapshot-state check, content hash, and run insert
        # atomic with begin_snapshot_refresh() and all raw input writes.
        conn.execute("BEGIN IMMEDIATE")
        state = conn.execute(
            "SELECT status FROM snapshot_state WHERE state_id = 1"
        ).fetchone()
        if state is None:
            raise RuntimeError("cannot begin control run without a ready snapshot")
        if state[0] not in _READY_SNAPSHOT_STATUSES:
            raise RuntimeError(
                "cannot begin control run while snapshot state is {}".format(state[0]))
        cur = conn.execute(
            "INSERT INTO control_runs (params_hash, input_hash, code_hash,"
            " expected_controls, status, started_at)"
            " VALUES (?, ?, ?, ?, 'running', ?)",
            (params_hash(params), input_hash(conn), code_hash(),
             json.dumps(expected, separators=(",", ":")),
             datetime.now(timezone.utc).isoformat()))
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn, run_id: int) -> None:
    """Mark a run complete only if its immutable manifest actually executed.

    An earlier version checked only for executions with status != 'complete'.
    With zero executions that check passes vacuously, so a run in which every
    control failed to start recorded as complete with no failure. A provenance
    record asserting completion while nothing ran is worse than no record.
    """
    try:
        # Freeze writers while checking that the snapshot and execution records
        # still match what begin_run() registered.
        conn.execute("BEGIN IMMEDIATE")
        run = conn.execute(
            "SELECT input_hash, code_hash, expected_controls, status"
            " FROM control_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run is None or run[3] != "running":
            raise RuntimeError("cannot complete a non-running control run {}".format(run_id))

        state = conn.execute(
            "SELECT status FROM snapshot_state WHERE state_id = 1"
        ).fetchone()
        if state is None:
            raise RuntimeError(
                "cannot complete run {} without a ready snapshot".format(run_id))
        if state[0] not in _READY_SNAPSHOT_STATUSES:
            raise RuntimeError(
                "cannot complete run {} while snapshot state is {}".format(run_id, state[0]))
        if input_hash(conn) != run[0]:
            raise RuntimeError(
                "cannot complete run {}: detector inputs changed during execution".format(run_id))
        if code_hash() != run[1]:
            raise RuntimeError(
                "cannot complete run {}: detector code changed during execution".format(run_id))

        try:
            expected = _expected_manifest(json.loads(run[2]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "cannot complete run {}: invalid expected-control manifest".format(run_id)
            ) from exc

        executions = conn.execute(
            "SELECT control_id, status, alert_count FROM control_executions WHERE run_id = ?"
            " ORDER BY control_id", (run_id,)
        ).fetchall()
        unfinished = [control for control, status, _ in executions if status != "complete"]
        if unfinished:
            raise RuntimeError(
                "cannot complete run {} while control execution(s) are unfinished: {}"
                .format(run_id, ", ".join(unfinished)))

        done = {control for control, _, _ in executions}
        missing = sorted(set(expected) - done)
        unexpected = sorted(done - set(expected))
        if missing or unexpected:
            detail = []
            if missing:
                detail.append("missing {}".format(", ".join(missing)))
            if unexpected:
                detail.append("unexpected {}".format(", ".join(unexpected)))
            raise RuntimeError(
                "cannot complete run {}: control manifest mismatch ({})".format(
                    run_id, "; ".join(detail)))

        actual_counts = dict(conn.execute(
            "SELECT control_id, COUNT(*) FROM alerts WHERE run_id = ?"
            " GROUP BY control_id", (run_id,)).fetchall())
        mismatched_counts = [
            "{} recorded {} actual {}".format(control, recorded, actual_counts.get(control, 0))
            for control, _, recorded in executions
            if recorded != actual_counts.get(control, 0)
        ]
        mismatched_counts.extend(
            "{} has {} alert(s) without an execution".format(control, actual_counts[control])
            for control in sorted(set(actual_counts) - done)
        )
        if mismatched_counts:
            raise RuntimeError(
                "cannot complete run {}: alert count mismatch ({})".format(
                    run_id, "; ".join(mismatched_counts)))

        cur = conn.execute(
            "UPDATE control_runs SET status = 'complete', finished_at = ?"
            " WHERE run_id = ? AND status = 'running'",
            (datetime.now(timezone.utc).isoformat(), run_id))
        if cur.rowcount != 1:
            raise RuntimeError("cannot complete a non-running control run {}".format(run_id))
    except Exception:
        conn.rollback()
        raise
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
