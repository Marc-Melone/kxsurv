"""Run-scoped analyst dispositions for surveillance candidates.

Transparent written rationales show why each alert was closed, retained for
monitoring, or escalated without turning a screening output into a finding.
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
    cur = conn.execute(
        "INSERT INTO dispositions (alert_id, action, rationale, created_at)"
        " VALUES (?,?,?,?)",
        (alert_id, action, rationale.strip(),
         datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return int(cur.lastrowid)


def _selected_run(conn, run_id: int | None) -> int | None:
    if run_id is not None:
        return run_id
    row = conn.execute(
        "SELECT run_id FROM control_runs WHERE status = 'complete'"
        " ORDER BY run_id DESC LIMIT 1").fetchone()
    return int(row[0]) if row else None


def funnel(conn, run_id: int | None = None) -> dict:
    selected = _selected_run(conn, run_id)
    clause, values = (("WHERE a.run_id = ?", (selected,)) if selected is not None
                      else ("WHERE a.run_id IS NULL", ()))
    generated = conn.execute("SELECT COUNT(*) FROM alerts a " + clause, values).fetchone()[0]
    latest = (" AND d.disposition_id = (SELECT MAX(d2.disposition_id) FROM dispositions d2"
              " WHERE d2.alert_id = a.alert_id)")
    rows = conn.execute(
        "SELECT d.action, COUNT(*) FROM dispositions d JOIN alerts a USING(alert_id) "
        + clause + latest + " GROUP BY d.action", values).fetchall()
    by_action = {a: n for a, n in rows}
    triaged = sum(by_action.values())

    per_control: dict[str, dict] = {}
    if selected is not None:
        for (control,) in conn.execute(
                "SELECT control_id FROM control_executions WHERE run_id = ?"
                " ORDER BY control_id", (selected,)):
            per_control[control] = {"generated": 0, "triaged": 0,
                                    "escalated": 0, "no_action": 0, "monitor": 0}
    for control, n in conn.execute(
            "SELECT a.control_id, COUNT(*) FROM alerts a " + clause +
            " GROUP BY a.control_id", values):
        per_control.setdefault(control, {"generated": 0, "triaged": 0,
                                         "escalated": 0, "no_action": 0,
                                         "monitor": 0})["generated"] = n
    for control, action, n in conn.execute(
            "SELECT a.control_id, d.action, COUNT(*) FROM alerts a"
            " JOIN dispositions d USING(alert_id) " + clause +
            latest + " GROUP BY a.control_id, d.action", values):
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


def open_alerts(conn, run_id: int | None = None) -> list[dict]:
    selected = _selected_run(conn, run_id)
    clause, values = (("a.run_id = ?", (selected,)) if selected is not None
                      else ("a.run_id IS NULL", ()))
    cur = conn.execute(
        "SELECT alert_id, control_id, target, score, percentile, evidence"
        " FROM alerts a WHERE " + clause +
        " AND NOT EXISTS (SELECT 1 FROM dispositions d WHERE d.alert_id = a.alert_id)"
        " ORDER BY alert_id ASC", values)
    return [{"alert_id": r[0], "control_id": r[1], "target": r[2],
             "score": r[3], "percentile": r[4],
             "evidence": json.loads(r[5]) if r[5] else {}}
            for r in cur.fetchall()]
