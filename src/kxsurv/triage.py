"""Triage. Real surveillance is overwhelmingly false positives.

A program reporting "37 alerts, 34 closed as benign, here is the reasoning for
each" demonstrates better judgement than one claiming detections. Mostly
no-action dispositions is the expected and acceptable result.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

ACTIONS = frozenset({"no_action", "escalated", "monitor"})


def disposition(conn, alert_id: int, action: str, rationale: str) -> int:
    if action not in ACTIONS:
        raise ValueError(
            "unknown action {!r}; expected one of {}".format(action, sorted(ACTIONS)))
    if not rationale or not rationale.strip():
        raise ValueError("a rationale is required for every disposition")
    conn.execute(
        "INSERT INTO dispositions (alert_id, action, rationale, created_at)"
        " VALUES (?,?,?,?)",
        (alert_id, action, rationale.strip(),
         datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return conn.execute("SELECT MAX(disposition_id) FROM dispositions").fetchone()[0]


def funnel(conn) -> dict:
    generated = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    rows = conn.execute(
        "SELECT d.action, COUNT(*) FROM dispositions d GROUP BY d.action"
    ).fetchall()
    by_action = {a: n for a, n in rows}
    triaged = sum(by_action.values())

    per_control: dict[str, dict] = {}
    for control, n in conn.execute(
            "SELECT control_id, COUNT(*) FROM alerts GROUP BY control_id"):
        per_control[control] = {"generated": n, "triaged": 0,
                                "escalated": 0, "no_action": 0, "monitor": 0}
    for control, action, n in conn.execute(
            "SELECT a.control_id, d.action, COUNT(*) FROM alerts a"
            " JOIN dispositions d USING(alert_id)"
            " GROUP BY a.control_id, d.action"):
        per_control[control][action] = n
        per_control[control]["triaged"] += n

    return {
        "generated": generated,
        "triaged": triaged,
        "untriaged": generated - triaged,
        "escalated": by_action.get("escalated", 0),
        "no_action": by_action.get("no_action", 0),
        "monitor": by_action.get("monitor", 0),
        "by_control": per_control,
    }


def open_alerts(conn) -> list[dict]:
    cur = conn.execute(
        "SELECT alert_id, control_id, target, score, percentile, evidence"
        " FROM alerts WHERE alert_id NOT IN (SELECT alert_id FROM dispositions)"
        " ORDER BY alert_id ASC")
    return [{"alert_id": r[0], "control_id": r[1], "target": r[2],
             "score": r[3], "percentile": r[4],
             "evidence": json.loads(r[5]) if r[5] else {}}
            for r in cur.fetchall()]
