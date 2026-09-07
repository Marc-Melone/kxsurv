"""Shared control plumbing.

No alert is a finding. Every alert means "warranting investigation" and nothing
more; public data cannot establish intent, coordination, or account identity.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..params import params_hash, verify

ESCALATION_LANGUAGE = (
    "escalated — resolution requires account-level data held only by the exchange")


@dataclass
class Alert:
    control_id: str
    target: str
    window_start: str | None
    window_end: str | None
    score: float
    percentile: float | None
    threshold: float | None
    evidence: dict = field(default_factory=dict)


def save_alerts(conn, alerts: list[Alert], params: dict, run_id: int) -> int:
    """Persist one control's alerts for an immutable run.

    Duplicate natural keys are a detector defect, not a harmless retry: silently
    ignoring them would make the CLI's generated count disagree with the stored
    count.  The run therefore fails closed and can be investigated or rerun as
    a new execution.
    """
    h = params_hash(params)
    run = conn.execute(
        "SELECT params_hash, status FROM control_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if run is None or run[0] != h or run[1] != "running":
        raise ValueError("alerts require a matching running control run")
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.executemany(
            "INSERT INTO alerts (run_id, control_id, target, window_start,"
            " window_end, score, percentile, threshold, evidence, params_hash, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(run_id, a.control_id, a.target, a.window_start, a.window_end, a.score,
              a.percentile, a.threshold, json.dumps(a.evidence, sort_keys=True),
              h, now) for a in alerts])
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return len(alerts)


def _start_execution(conn, control_id: str, params: dict, run_id: int) -> None:
    h = params_hash(params)
    run = conn.execute(
        "SELECT 1 FROM control_runs WHERE run_id = ? AND params_hash = ?"
        " AND status = 'running'", (run_id, h)
    ).fetchone()
    if run is None:
        raise ValueError("control execution requires a matching running control run")
    conn.execute(
        "INSERT INTO control_executions (run_id, control_id, status, started_at)"
        " VALUES (?, ?, 'running', ?)",
        (run_id, control_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def _finish_execution(conn, control_id: str, run_id: int, alert_count: int) -> None:
    cur = conn.execute(
        "UPDATE control_executions SET status = 'complete', alert_count = ?,"
        " finished_at = ? WHERE run_id = ? AND control_id = ? AND status = 'running'",
        (alert_count, datetime.now(timezone.utc).isoformat(), run_id, control_id),
    )
    if cur.rowcount != 1:
        conn.rollback()
        raise RuntimeError("cannot complete control execution {} in run {}".format(
            control_id, run_id))
    conn.commit()


def _fail_execution(conn, control_id: str, run_id: int, exc: Exception) -> None:
    cur = conn.execute(
        "UPDATE control_executions SET status = 'failed', finished_at = ?, failure = ?"
        " WHERE run_id = ? AND control_id = ? AND status = 'running'",
        (datetime.now(timezone.utc).isoformat(),
         "{}: {}".format(type(exc).__name__, exc), run_id, control_id),
    )
    if cur.rowcount != 1:
        conn.rollback()
        raise RuntimeError("cannot fail control execution {} in run {}".format(
            control_id, run_id))
    conn.commit()


def run_control(conn, module, params: dict, run_id: int) -> list[Alert]:
    """Verify, execute, and record one control, including a zero result."""
    verify(conn, params)
    control_id = getattr(module, "CONTROL_ID", None)
    if not isinstance(control_id, str) or not control_id:
        raise ValueError("control module must declare a non-empty CONTROL_ID")
    _start_execution(conn, control_id, params, run_id)
    try:
        alerts = module.run(conn, params)
        if any(alert.control_id != control_id for alert in alerts):
            raise ValueError("control {} emitted an alert for another control".format(
                control_id))
        saved = save_alerts(conn, alerts, params, run_id)
    except Exception as exc:
        _fail_execution(conn, control_id, run_id, exc)
        raise
    _finish_execution(conn, control_id, run_id, saved)
    return alerts


def percentile_of(value: float, population: list[float]) -> float:
    if not population:
        return 0.0
    below = sum(1 for x in population if x < value)
    return 100.0 * below / len(population)
