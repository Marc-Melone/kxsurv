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


def save_alerts(conn, alerts: list[Alert], params: dict) -> int:
    h = params_hash(params)
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "INSERT INTO alerts (control_id, target, window_start, window_end,"
        " score, percentile, threshold, evidence, params_hash, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(a.control_id, a.target, a.window_start, a.window_end, a.score,
          a.percentile, a.threshold, json.dumps(a.evidence, sort_keys=True),
          h, now) for a in alerts])
    conn.commit()
    return len(alerts)


def run_control(conn, module, params: dict) -> list[Alert]:
    """Verify pre-registration, then run. Drifted parameters never execute."""
    verify(conn, params)
    alerts = module.run(conn, params)
    save_alerts(conn, alerts, params)
    return alerts


def percentile_of(value: float, population: list[float]) -> float:
    if not population:
        return 0.0
    below = sum(1 for x in population if x < value)
    return 100.0 * below / len(population)
