"""The exporter is the boundary between a database row and a published claim.

Its invariants exist because this project has already produced documented
results whose provenance records did not exist. A number reaches the published
artifact only by way of a complete run in a live database.
"""
import json

import pytest

from kxsurv.controls import Alert, save_alerts
from kxsurv.export import ExportError, export_run
from kxsurv.params import register
from kxsurv.runs import begin_run, code_hash, fail_run, finish_run
from kxsurv.triage import disposition, funnel

P = {"version": "export-test-1",
     "c4_monotonicity": {"min_inversion_dollars": 0.01}}


def _record_execution(conn, run_id, control_id="C4", alert_count=0):
    conn.execute("INSERT INTO control_executions (run_id, control_id, status,"
                 " started_at) VALUES (?,?,?,?)", (run_id, control_id, "running", "t"))
    conn.execute("UPDATE control_executions SET status = 'complete', alert_count = ?,"
                 " finished_at = 't' WHERE run_id = ? AND control_id = ?",
                 (alert_count, run_id, control_id))
    conn.commit()


def _complete_run(conn, targets=("a", "b"), controls=("C4",)):
    register(conn, P)
    run_id = begin_run(conn, P, controls)
    alerts = [Alert("C4", t, None, None, 1.0, None, 0.01, {"k": t}) for t in targets]
    save_alerts(conn, alerts, P, run_id)
    _record_execution(conn, run_id, "C4", len(alerts))
    for extra in controls[1:]:
        _record_execution(conn, run_id, extra, 0)
    finish_run(conn, run_id)
    return run_id


def test_refuses_a_run_that_is_still_running(conn):
    register(conn, P)
    run_id = begin_run(conn, P, ("C4",))
    with pytest.raises(ExportError, match="complete"):
        export_run(conn, run_id)


def test_refuses_a_failed_run(conn):
    register(conn, P)
    run_id = begin_run(conn, P, ("C4",))
    fail_run(conn, run_id, RuntimeError("boom"))
    with pytest.raises(ExportError, match="complete"):
        export_run(conn, run_id)


def test_refuses_an_unknown_run(conn):
    with pytest.raises(ExportError, match="no run"):
        export_run(conn, 4242)


def test_refuses_when_no_complete_run_exists(conn):
    with pytest.raises(ExportError, match="no complete run"):
        export_run(conn)


def test_defaults_to_the_latest_complete_run(conn):
    first = _complete_run(conn, ("a",))
    second = _complete_run(conn, ("b",))
    assert second > first
    assert export_run(conn)["run"]["run_id"] == second


def test_includes_only_the_requested_runs_alerts(conn):
    first = _complete_run(conn, ("only-first",))
    _complete_run(conn, ("only-second",))
    targets = [a["target"] for a in export_run(conn, first)["alerts"]]
    assert targets == ["only-first"]


def test_carries_the_runs_stored_fingerprints(conn):
    run_id = _complete_run(conn)
    stored = conn.execute(
        "SELECT params_hash, input_hash, code_hash FROM control_runs WHERE run_id = ?",
        (run_id,)).fetchone()
    run = export_run(conn, run_id)["run"]
    assert (run["params_hash"], run["input_hash"], run["code_hash"]) == tuple(stored)


def test_reports_no_drift_when_the_tree_matches_the_run(conn):
    run = export_run(conn, _complete_run(conn))["run"]
    assert run["code_hash_current"] == code_hash()
    assert run["code_drift"] is False


def test_flags_code_drift_when_the_tree_no_longer_matches(conn, monkeypatch):
    """A run's identity columns are immutable, so the *current* tree moves.

    This is the real scenario: the run is history, and the checkout has since
    changed. Publishing a result under a code fingerprint the tree no longer
    matches would misdescribe what produced it.
    """
    run_id = _complete_run(conn)
    stored = conn.execute("SELECT code_hash FROM control_runs WHERE run_id = ?",
                          (run_id,)).fetchone()[0]
    monkeypatch.setattr("kxsurv.export.code_hash", lambda: "moved-on")

    run = export_run(conn, run_id)["run"]
    assert run["code_drift"] is True
    assert run["code_hash"] == stored
    assert run["code_hash_current"] == "moved-on"


def test_attaches_only_the_latest_disposition(conn):
    run_id = _complete_run(conn, ("a",))
    alert_id = conn.execute("SELECT alert_id FROM alerts WHERE run_id = ?",
                            (run_id,)).fetchone()[0]
    disposition(conn, alert_id, "monitor", "first look")
    disposition(conn, alert_id, "no_action", "revised after review")

    alert = export_run(conn, run_id)["alerts"][0]
    assert alert["disposition"]["action"] == "no_action"
    assert alert["disposition"]["rationale"] == "revised after review"


def test_reports_an_untriaged_alert_as_having_no_disposition(conn):
    alert = export_run(conn, _complete_run(conn, ("a",)))["alerts"][0]
    assert alert["disposition"] is None


def test_keeps_a_zero_alert_control_in_the_execution_record(conn):
    """A silent control must not be mistaken for one that never ran."""
    run_id = _complete_run(conn, ("a",), controls=("C4", "C2"))
    executions = {e["control_id"]: e for e in export_run(conn, run_id)["executions"]}
    assert executions["C2"]["alert_count"] == 0
    assert executions["C2"]["status"] == "complete"


def test_funnel_matches_the_triage_module(conn):
    run_id = _complete_run(conn, ("a", "b"))
    alert_id = conn.execute("SELECT MIN(alert_id) FROM alerts WHERE run_id = ?",
                            (run_id,)).fetchone()[0]
    disposition(conn, alert_id, "monitor", "watch it")
    assert export_run(conn, run_id)["funnel"] == funnel(conn, run_id)


def test_publishes_derived_results_only(conn):
    """Raw market data stays out of the published artifact."""
    doc = export_run(conn, _complete_run(conn))
    blob = json.dumps(doc)
    for forbidden in ("trade_id", "yes_bid_close", "open_interest_fp", "count_fp"):
        assert forbidden not in blob
    assert set(doc["corpus"]) >= {"markets", "trades", "candles", "events"}
    assert all(isinstance(v, int) for k, v in doc["corpus"].items() if k != "series")


def test_round_trips_through_json(conn):
    doc = export_run(conn, _complete_run(conn))
    assert json.loads(json.dumps(doc)) == doc


def test_records_the_source_commit_when_supplied(conn):
    doc = export_run(conn, _complete_run(conn), source_commit="abc1234")
    assert doc["run"]["source_commit"] == "abc1234"


# The viewer reads these keys. Renaming one without updating site/app.js would
# publish a blank page; this test makes that a test failure instead.
CONTRACT = {"export_schema", "generated_at", "run", "corpus", "executions",
            "funnel", "coverage", "controls", "alerts", "disclaimer"}
RUN_CONTRACT = {"run_id", "status", "params_version", "params_hash", "input_hash",
                "code_hash", "code_hash_current", "code_drift", "source_commit",
                "source_dirty", "started_at", "finished_at", "controls_complete",
                "controls_expected"}
ALERT_CONTRACT = {"alert_id", "control_id", "target", "window_start", "window_end",
                  "score", "percentile", "threshold", "evidence", "disposition"}


def test_top_level_contract_is_stable(conn):
    assert set(export_run(conn, _complete_run(conn))) == CONTRACT


def test_run_contract_is_stable(conn):
    assert set(export_run(conn, _complete_run(conn))["run"]) == RUN_CONTRACT


def test_alert_contract_is_stable(conn):
    doc = export_run(conn, _complete_run(conn, ("a",)))
    assert set(doc["alerts"][0]) == ALERT_CONTRACT
