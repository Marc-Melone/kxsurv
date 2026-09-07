import sqlite3

import pytest

from kxsurv.controls import Alert, save_alerts
from kxsurv.params import params_hash, register
from kxsurv.runs import (begin_run, begin_snapshot_refresh, fail_run,
                         fail_snapshot_refresh, finish_run, finish_snapshot_refresh,
                         input_hash, latest_run_id, verify_snapshot_ready)
from kxsurv.triage import funnel


P = {"version": "run-test-1", "c4_monotonicity": {"min_inversion_dollars": 0.01}}
P2 = {"version": "run-test-2", "c4_monotonicity": {"min_inversion_dollars": 0.02}}


def _alert(target: str) -> Alert:
    return Alert("C4", target, None, None, 1.0, None, 0.01, {})


def _record_execution(conn, run_id, control_id="C4"):
    """A run can only complete if a control actually executed."""
    conn.execute("INSERT INTO control_executions (run_id, control_id, status,"
                 " alert_count, started_at, finished_at) VALUES (?,?,?,?,?,?)",
                 (run_id, control_id, "complete", 0, "t", "t"))
    conn.commit()


def test_database_trigger_rejects_an_insert_into_a_completed_run(conn):
    register(conn, P)
    run_id = begin_run(conn, P)
    _record_execution(conn, run_id)
    finish_run(conn, run_id)

    with pytest.raises(sqlite3.IntegrityError, match="matching running"):
        conn.execute(
            "INSERT INTO alerts (run_id, control_id, target, score, params_hash, created_at)"
            " VALUES (?, 'C4', 'direct', 1.0, ?, 't')",
            (run_id, params_hash(P)),
        )


def test_database_trigger_makes_alert_run_and_parameter_binding_immutable(conn):
    register(conn, P)
    register(conn, P2)
    first = begin_run(conn, P)
    second = begin_run(conn, P)
    save_alerts(conn, [_alert("direct")], P, first)
    alert_id = conn.execute("SELECT alert_id FROM alerts").fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE alerts SET run_id = ? WHERE alert_id = ?", (second, alert_id))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE alerts SET params_hash = ? WHERE alert_id = ?",
                     (params_hash(P2), alert_id))

    assert conn.execute(
        "SELECT run_id, params_hash FROM alerts WHERE alert_id = ?", (alert_id,)
    ).fetchone() == (first, params_hash(P))


def test_input_hash_excludes_ingest_check_timestamp_but_not_detector_inputs(conn):
    conn.execute(
        "INSERT INTO ingest_log (ticker, tape_volume, candle_volume, divergence_pct, complete, checked_at)"
        " VALUES ('T', 10, 10, 0, 1, '2026-09-07T00:00:00Z')"
    )
    conn.commit()
    before = input_hash(conn)

    conn.execute("UPDATE ingest_log SET checked_at = '2026-09-08T00:00:00Z' WHERE ticker = 'T'")
    conn.commit()
    assert input_hash(conn) == before

    conn.execute("UPDATE ingest_log SET complete = 0 WHERE ticker = 'T'")
    conn.commit()
    assert input_hash(conn) != before


def test_failed_run_is_excluded_from_default_latest_run_and_funnel(conn):
    register(conn, P)
    complete = begin_run(conn, P)
    save_alerts(conn, [_alert("complete")], P, complete)
    _record_execution(conn, complete)
    finish_run(conn, complete)

    failed = begin_run(conn, P)
    save_alerts(conn, [_alert("failed")], P, failed)
    fail_run(conn, failed, RuntimeError("planted control failure"))

    assert latest_run_id(conn) == complete
    assert funnel(conn)["generated"] == 1
    assert funnel(conn, failed)["generated"] == 1
    assert conn.execute("SELECT status, failure FROM control_runs WHERE run_id = ?", (failed,)).fetchone() == (
        "failed", "RuntimeError: planted control failure",
    )


def test_snapshot_refresh_lifecycle_blocks_partial_or_failed_local_runs(conn):
    with pytest.raises(RuntimeError, match="completed snapshot"):
        verify_snapshot_ready(conn)

    begin_snapshot_refresh(conn)
    with pytest.raises(RuntimeError, match="refreshing"):
        verify_snapshot_ready(conn)
    fail_snapshot_refresh(conn, RuntimeError("planted ingest failure"))
    with pytest.raises(RuntimeError, match="failed"):
        verify_snapshot_ready(conn)

    begin_snapshot_refresh(conn)
    finish_snapshot_refresh(conn)
    verify_snapshot_ready(conn)


# --- vacuous completion (found by an out-of-sample run, 2026-09-07) --------
# finish_run checked for executions with status != 'complete'. With zero
# executions that check passes vacuously, so a run in which every control
# failed to start recorded as status='complete', finished_at set, failure NULL.
# A provenance record that claims completion while nothing executed is worse
# than no record at all.

import pytest
from kxsurv.runs import begin_run, finish_run
from kxsurv.params import register


def test_a_run_with_no_executions_cannot_complete(conn):
    P = {"version": "t", "x": 1}
    register(conn, P)
    rid = begin_run(conn, P)
    with pytest.raises(RuntimeError, match="no control executions"):
        finish_run(conn, rid, expected=("C1", "C2"))
    row = conn.execute("SELECT status, finished_at FROM control_runs WHERE run_id = ?",
                       (rid,)).fetchone()
    assert row[0] != "complete" and row[1] is None


def test_a_run_missing_an_expected_control_cannot_complete(conn):
    P = {"version": "t", "x": 1}
    register(conn, P)
    rid = begin_run(conn, P)
    conn.execute("INSERT INTO control_executions (run_id, control_id, status,"
                 " alert_count, started_at, finished_at) VALUES (?,?,?,?,?,?)",
                 (rid, "C1", "complete", 0, "t", "t"))
    conn.commit()
    with pytest.raises(RuntimeError, match="did not execute"):
        finish_run(conn, rid, expected=("C1", "C2"))


def test_a_run_with_every_expected_control_completes(conn):
    P = {"version": "t", "x": 1}
    register(conn, P)
    rid = begin_run(conn, P)
    for cid in ("C1", "C2"):
        conn.execute("INSERT INTO control_executions (run_id, control_id, status,"
                     " alert_count, started_at, finished_at) VALUES (?,?,?,?,?,?)",
                     (rid, cid, "complete", 0, "t", "t"))
    conn.commit()
    finish_run(conn, rid, expected=("C1", "C2"))
    assert conn.execute("SELECT status FROM control_runs WHERE run_id = ?",
                        (rid,)).fetchone()[0] == "complete"
