"""Freeze one complete run into a publishable, self-describing artifact.

A published number must be traceable to a database row, not to a log file. This
project has twice produced documented results whose provenance records did not
exist: `out/oos.log` recorded five crashed controls beneath a heading of
completed work, and a cited saved-snapshot run was absent from the database it
named. The exporter is the narrow gate that prevents a third instance. It reads
a live database, refuses anything but a complete run, and carries that run's own
fingerprints into the artifact so a reader can check the claim rather than
trust it.

Only derived results leave: alerts, evidence, dispositions, coverage, and
provenance. Raw trades, candles, and market rows stay in the gitignored
database and appear here only as counts.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

from .controls import ESCALATION_LANGUAGE
from .runs import code_hash, latest_run_id
from .triage import funnel

EXPORT_SCHEMA = 1

DISCLAIMER = (
    "A methodology demonstration on public Kalshi market data. Not an audit, an "
    "allegation of misconduct, or a claim to have detected abuse. The public tape "
    "carries no counterparty identity, so the program cannot identify accounts, "
    "establish beneficial ownership, demonstrate coordination, or establish "
    "intent. Every participant-facing output is an alert warranting "
    "investigation, never a finding."
)

CONTROLS = {
    "C1": {"name": "Pre-release informed flow",
           "purpose": "Pre-release information screen",
           "core_principle": "CP 12 — Protection of Markets and Market Participants"},
    "C2": {"name": "Pre-halt price pressure",
           "purpose": "Directionally aligned, thin-market pressure screen",
           "core_principle": "CP 4 — Prevention of Market Disruption"},
    "C3": {"name": "Volume / open-interest divergence",
           "purpose": "Wash-trade screening proxy",
           "core_principle": "CP 12 — Protection of Markets and Market Participants"},
    "C4": {"name": "Ladder monotonicity coherence",
           "purpose": "Price-quality screen across related contracts",
           "core_principle": "CP 4 — Prevention of Market Disruption"},
    "C5": {"name": "Settlement-source integrity",
           "purpose": "Settlement metadata and resolution-consistency screen",
           "core_principle": "CP 4 — Prevention of Market Disruption"},
}

_CORPUS_TABLES = ("markets", "trades", "candles", "events")


class ExportError(RuntimeError):
    """Raised when a run cannot be published as a result."""


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(("git",) + args, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _source_commit() -> tuple[str | None, bool | None]:
    """Resolve the working tree's commit and whether it carries local changes."""
    commit = _git("rev-parse", "--short", "HEAD")
    if commit is None:
        return None, None
    status = _git("status", "--porcelain")
    return commit, bool(status) if status is not None else None


def _coverage(conn, params: dict | None) -> dict:
    """Per-control screened population, when the caller supplied parameters.

    Coverage is what makes an alert count interpretable: three C1 candidates
    mean one thing against 69 scored markets and another against 408.
    """
    if not params:
        return {}
    out: dict[str, dict] = {}
    if "c1_prerelease" in params:
        from .controls.c1_prerelease import coverage as c1_coverage
        out["C1"] = c1_coverage(conn, params)
    if "c3_oi_divergence" in params:
        from .controls.c3_oi_divergence import coverage as c3_coverage
        out["C3"] = c3_coverage(conn, params)
    return out


def _alerts(conn, run_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT alert_id, control_id, target, window_start, window_end, score,"
        " percentile, threshold, evidence FROM alerts WHERE run_id = ?"
        " ORDER BY control_id, alert_id", (run_id,)).fetchall()
    out = []
    for row in rows:
        alert_id = row[0]
        # The latest disposition wins, matching triage.funnel. An alert may be
        # reviewed more than once; only the standing decision is published.
        disp = conn.execute(
            "SELECT action, rationale, created_at FROM dispositions"
            " WHERE alert_id = ? ORDER BY disposition_id DESC LIMIT 1",
            (alert_id,)).fetchone()
        out.append({
            "alert_id": alert_id,
            "control_id": row[1],
            "target": row[2],
            "window_start": row[3],
            "window_end": row[4],
            "score": row[5],
            "percentile": row[6],
            "threshold": row[7],
            "evidence": json.loads(row[8]) if row[8] else {},
            "disposition": None if disp is None else {
                "action": disp[0], "rationale": disp[1], "created_at": disp[2]},
        })
    return out


def export_run(conn, run_id: int | None = None, params: dict | None = None,
               source_commit: str | None = None) -> dict:
    """Build the published document for one complete run.

    ``run_id`` defaults to the latest complete run. Raises ``ExportError``
    rather than emitting a partial result, because a published artifact that
    silently describes an unfinished run is the defect this module exists to
    prevent.
    """
    if run_id is None:
        run_id = latest_run_id(conn)
        if run_id is None:
            raise ExportError(
                "no complete run to export; run the controls before exporting")

    row = conn.execute(
        "SELECT run_id, status, params_hash, input_hash, code_hash, started_at,"
        " finished_at, expected_controls FROM control_runs WHERE run_id = ?",
        (run_id,)).fetchone()
    if row is None:
        raise ExportError("no run {}".format(run_id))
    if row[1] != "complete":
        raise ExportError(
            "refusing to export run {}: status is {!r}, not complete"
            .format(run_id, row[1]))

    current_code = code_hash()
    version = conn.execute(
        "SELECT version FROM params WHERE params_hash = ?", (row[2],)).fetchone()

    if source_commit is None:
        source_commit, source_dirty = _source_commit()
    else:
        _, source_dirty = _source_commit()

    executions = [
        {"control_id": e[0], "status": e[1], "alert_count": e[2],
         "started_at": e[3], "finished_at": e[4]}
        for e in conn.execute(
            "SELECT control_id, status, alert_count, started_at, finished_at"
            " FROM control_executions WHERE run_id = ? ORDER BY control_id",
            (run_id,))]

    corpus = {t: conn.execute("SELECT COUNT(*) FROM {}".format(t)).fetchone()[0]
              for t in _CORPUS_TABLES}
    corpus["series"] = [r[0] for r in conn.execute(
        "SELECT DISTINCT series_ticker FROM markets WHERE series_ticker IS NOT NULL"
        " ORDER BY series_ticker")]

    expected = row[7]
    return {
        "export_schema": EXPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": {
            "run_id": row[0],
            "status": row[1],
            "params_version": version[0] if version else None,
            "params_hash": row[2],
            "input_hash": row[3],
            "code_hash": row[4],
            "code_hash_current": current_code,
            "code_drift": row[4] != current_code,
            "source_commit": source_commit,
            "source_dirty": source_dirty,
            "started_at": row[5],
            "finished_at": row[6],
            "controls_complete": sum(1 for e in executions if e["status"] == "complete"),
            "controls_expected": len(json.loads(expected)) if expected else len(executions),
        },
        "corpus": corpus,
        "executions": executions,
        "funnel": funnel(conn, run_id),
        "coverage": _coverage(conn, params),
        "controls": CONTROLS,
        "alerts": _alerts(conn, run_id),
        "disclaimer": DISCLAIMER,
        }


def write_export(conn, path: str, run_id: int | None = None,
                 params: dict | None = None, source_commit: str | None = None) -> dict:
    """Write one run document and refresh the sibling index the viewer reads."""
    import os

    doc = export_run(conn, run_id, params, source_commit)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")

    name = os.path.basename(path)
    index_path = os.path.join(directory, "index.json")
    runs = []
    if os.path.exists(index_path):
        try:
            with open(index_path) as fh:
                runs = list(json.load(fh).get("runs", []))
        except (OSError, ValueError):
            runs = []
    if name not in runs:
        runs.append(name)
    with open(index_path, "w") as fh:
        json.dump({"latest": name, "runs": sorted(runs)}, fh, indent=2)
        fh.write("\n")
    return doc
