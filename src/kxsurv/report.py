"""Report generation: funnel summary and investigation case files."""
from __future__ import annotations

import json

from .controls import ESCALATION_LANGUAGE
from .triage import funnel


def funnel_markdown(conn, run_id: int | None = None) -> str:
    f = funnel(conn, run_id)
    selected = run_id
    if selected is None:
        row = conn.execute(
            "SELECT run_id FROM control_runs WHERE status = 'complete'"
            " ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        selected = row[0] if row else None
    lines = [
        "## Triage funnel", "",
        "| Stage | Count |", "|---|---|",
        "| Generated | {} |".format(f["generated"]),
        "| Triaged | {} |".format(f["triaged"]),
        "| Escalated | {} |".format(f["escalated"]),
        "| No action | {} |".format(f["no_action"]),
        "| Monitor | {} |".format(f["monitor"]),
        "| Untriaged | {} |".format(f["untriaged"]),
        "", "### By control", "",
        "| Control | Generated | Triaged | Escalated | No action | Monitor |",
        "|---|---|---|---|---|---|",
    ]
    for c in sorted(f["by_control"]):
        r = f["by_control"][c]
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            c, r["generated"], r["triaged"], r["escalated"], r["no_action"],
            r["monitor"]))
    if selected is not None:
        run = conn.execute(
            "SELECT params_hash, input_hash, code_hash, status, started_at, finished_at"
            " FROM control_runs WHERE run_id = ?", (selected,)
        ).fetchone()
        if run:
            execution = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(status = 'complete'), 0)"
                " FROM control_executions WHERE run_id = ?", (selected,)
            ).fetchone()
            lines.extend([
                "", "### Run provenance", "",
                "| Field | Value |", "|---|---|",
                "| Run ID | {} |".format(selected),
                "| Parameters SHA-256 | `{}` |".format(run[0]),
                "| Input fingerprint | `{}` |".format(run[1]),
                "| Code fingerprint | `{}` |".format(run[2]),
                "| Status | {} |".format(run[3]),
                "| Started | {} |".format(run[4]),
                "| Finished | {} |".format(run[5] or "—"),
            ])
            if execution[0]:
                lines.append("| Controls complete | {}/{} |".format(
                    execution[1], execution[0]))
    return "\n".join(lines)


def case_file_markdown(conn, alert_id: int, timeline: str,
                       alternatives: str, limitations: str) -> str:
    a = conn.execute(
        "SELECT control_id, target, score, percentile, evidence, created_at"
        " FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
    d = conn.execute(
        "SELECT action, rationale FROM dispositions WHERE alert_id = ?"
        " ORDER BY disposition_id DESC LIMIT 1", (alert_id,)).fetchone()
    control, target, score, pct, evidence, created = a
    action, rationale = d if d else ("untriaged", "not yet reviewed")

    ev = json.loads(evidence) if evidence else {}
    ev_lines = "\n".join("- `{}`: {}".format(k, ev[k]) for k in sorted(ev))

    disposition_text = rationale
    if action == "escalated":
        disposition_text = "{} — {}".format(rationale, ESCALATION_LANGUAGE)

    return """# CASE-{aid:04d} — {control} / {target}

**Opened:** {created}
**Control:** {control}
**Alert score:** {score}{pctstr}

## Summary

Control {control} raised an alert on `{target}`. This is an alert warranting
investigation. It is not a finding, and it asserts no conclusion about the
conduct of any market participant.

## Timeline

{timeline}

## Evidence

{ev_lines}

## Alternative innocent explanations

{alternatives}

## Limitations

Kalshi's public tape carries no counterparty identity. This analysis cannot
identify or link accounts, establish common beneficial ownership, demonstrate
coordination, or establish intent.

{limitations}

## Disposition

**{action}** — {disposition_text}
""".format(aid=alert_id, control=control, target=target, created=created,
           score=score,
           pctstr="" if pct is None else " (percentile {:.1f})".format(pct),
           timeline=timeline, ev_lines=ev_lines or "- (none recorded)",
           alternatives=alternatives, limitations=limitations,
           action=action, disposition_text=disposition_text)
