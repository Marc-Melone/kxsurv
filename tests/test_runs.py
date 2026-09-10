import sqlite3

import pytest

from kxsurv.controls import Alert, save_alerts
from kxsurv.db import connect, init_schema
from kxsurv.params import params_hash, register
from kxsurv.runs import (begin_run, begin_snapshot_refresh, fail_run,
                         fail_snapshot_refresh, finish_run, finish_snapshot_refresh,
                         input_hash, latest_run_id, verify_snapshot_ready)
from kxsurv.triage import funnel


P = {"version": "run-test-1", "c4_monotonicity": {"min_inversion_dollars": 0.01}}
P2 = {"version": "run-test-2", "c4_monotonicity": {"min_inversion_dollars": 0.02}}


def _alert(target: str) -> Alert:
    return Alert("C4", target, None, None, 1.0, None, 0.01, {})


def _record_execution(conn, run_id, control_id="C4", alert_count=0):
    """A run can only complete if a control actually executed."""
    conn.execute("INSERT INTO control_executions (run_id, control_id, status,"
                 " started_at) VALUES (?,?,?,?)",
                 (run_id, control_id, "running", "t"))
    conn.execute("UPDATE control_executions SET status = 'complete', alert_count = ?,"
                 " finished_at = 't' WHERE run_id = ? AND control_id = ?",
                 (alert_count, run_id, control_id))
    conn.commit()


def test_database_trigger_rejects_an_insert_into_a_completed_run(conn):
    register(conn, P)
    run_id = begin_run(conn, P, ("C4",))
    _record_execution(conn, run_id)
    finish_run(conn, run_id)

    with pytest.raises(sqlite3.IntegrityError, match="matching running"):
        conn.execute(
            "INSERT INTO alerts (run_id, control_id, target, score, params_hash, created_at)"
            " VALUES (?, 'C4', 'direct', 1.0, ?, 't')",
            (run_id, params_hash(P)),
        )


def test_unbound_alert_cannot_bypass_completed_run_integrity(conn):
    register(conn, P)
    run_id = begin_run(conn, P, ("C4",))
    _record_execution(conn, run_id)
    finish_run(conn, run_id)

    with pytest.raises(sqlite3.IntegrityError, match="matching running"):
        conn.execute(
            "INSERT INTO alerts (run_id, control_id, target, score, params_hash, created_at)"
            " VALUES (NULL, 'C4', 'unbound', 1.0, ?, 't')",
            (params_hash(P),),
        )
    assert conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE run_id = ?", (run_id,)
    ).fetchone()[0] == 0


def test_database_trigger_makes_alert_run_and_parameter_binding_immutable(conn):
    register(conn, P)
    register(conn, P2)
    first = begin_run(conn, P, ("C4",))
    second = begin_run(conn, P, ("C4",))
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
    complete = begin_run(conn, P, ("C4",))
    save_alerts(conn, [_alert("complete")], P, complete)
    _record_execution(conn, complete, alert_count=1)
    finish_run(conn, complete)

    failed = begin_run(conn, P, ("C4",))
    save_alerts(conn, [_alert("failed")], P, failed)
    fail_run(conn, failed, RuntimeError("planted control failure"))

    assert latest_run_id(conn) == complete
    assert funnel(conn)["generated"] == 1
    assert funnel(conn, failed)["generated"] == 1
    assert conn.execute("SELECT status, failure FROM control_runs WHERE run_id = ?", (failed,)).fetchone() == (
        "failed", "RuntimeError: planted control failure",
    )


def test_snapshot_refresh_lifecycle_blocks_partial_or_failed_local_runs(conn):
    conn.execute("DELETE FROM snapshot_state")
    conn.commit()
    with pytest.raises(RuntimeError, match="completed snapshot"):
        verify_snapshot_ready(conn)

    first = begin_snapshot_refresh(conn)
    with pytest.raises(RuntimeError, match="refreshing"):
        verify_snapshot_ready(conn)
    fail_snapshot_refresh(conn, first, RuntimeError("planted ingest failure"))
    with pytest.raises(RuntimeError, match="failed"):
        verify_snapshot_ready(conn)

    second = begin_snapshot_refresh(conn)
    finish_snapshot_refresh(conn, second)
    verify_snapshot_ready(conn)
    assert conn.execute(
        "SELECT refresh_token, generation FROM snapshot_state"
    ).fetchone() == (second, 2)


def test_control_run_requires_an_explicit_ready_snapshot(conn):
    register(conn, P)
    conn.execute("DELETE FROM snapshot_state")
    conn.commit()
    with pytest.raises(RuntimeError, match="without a ready snapshot"):
        begin_run(conn, P, ("C4",))


def test_only_the_refresh_owner_can_finish_or_fail_and_overlap_is_rejected(conn):
    token = begin_snapshot_refresh(conn)
    with pytest.raises(RuntimeError, match="another refresh is active"):
        begin_snapshot_refresh(conn)
    with pytest.raises(RuntimeError, match="owned by this token"):
        finish_snapshot_refresh(conn, "not-the-owner")
    with pytest.raises(RuntimeError, match="owned by this token"):
        fail_snapshot_refresh(conn, "not-the-owner", RuntimeError("wrong owner"))
    assert conn.execute(
        "SELECT status, refresh_token, generation FROM snapshot_state"
    ).fetchone() == ("refreshing", token, 1)

    finish_snapshot_refresh(conn, token)
    assert conn.execute(
        "SELECT status, refresh_token, generation FROM snapshot_state"
    ).fetchone() == ("ready", token, 1)


def test_two_database_connections_cannot_own_the_same_refresh(tmp_path):
    path = str(tmp_path / "refresh-race.db")
    first = connect(path)
    init_schema(first)
    second = connect(path)
    try:
        token = begin_snapshot_refresh(first)
        with pytest.raises(RuntimeError, match="another refresh is active"):
            begin_snapshot_refresh(second)
        finish_snapshot_refresh(first, token)
        assert second.execute(
            "SELECT status, generation FROM snapshot_state"
        ).fetchone() == ("ready", 1)
    finally:
        first.close()
        second.close()


# --- vacuous completion (found by an out-of-sample run, 2026-09-07) --------
# finish_run checked for executions with status != 'complete'. With zero
# executions that check passes vacuously, so a run in which every control
# failed to start recorded as status='complete', finished_at set, failure NULL.
# A provenance record that claims completion while nothing executed is worse
# than no record at all.

def test_a_run_with_no_executions_cannot_complete(conn):
    P = {"version": "t", "x": 1}
    register(conn, P)
    rid = begin_run(conn, P, ("C1", "C2"))
    with pytest.raises(RuntimeError, match="manifest mismatch"):
        finish_run(conn, rid)
    row = conn.execute("SELECT status, finished_at FROM control_runs WHERE run_id = ?",
                       (rid,)).fetchone()
    assert row[0] != "complete" and row[1] is None


def test_a_run_missing_an_expected_control_cannot_complete(conn):
    P = {"version": "t", "x": 1}
    register(conn, P)
    rid = begin_run(conn, P, ("C1", "C2"))
    _record_execution(conn, rid, "C1")
    with pytest.raises(RuntimeError, match="manifest mismatch"):
        finish_run(conn, rid)


def test_a_run_with_every_expected_control_completes(conn):
    P = {"version": "t", "x": 1}
    register(conn, P)
    rid = begin_run(conn, P, ("C1", "C2"))
    for cid in ("C1", "C2"):
        _record_execution(conn, rid, cid)
    finish_run(conn, rid)
    assert conn.execute("SELECT status FROM control_runs WHERE run_id = ?",
                        (rid,)).fetchone()[0] == "complete"


def test_expected_control_manifest_is_required_and_persisted(conn):
    register(conn, P)
    with pytest.raises(ValueError, match="at least one"):
        begin_run(conn, P, ())
    rid = begin_run(conn, P, ("C4", "C5"))
    assert conn.execute(
        "SELECT expected_controls FROM control_runs WHERE run_id = ?", (rid,)
    ).fetchone()[0] == '["C4","C5"]'


def test_snapshot_refresh_and_raw_writes_are_blocked_during_a_run(conn):
    register(conn, P)
    rid = begin_run(conn, P, ("C4",))

    with pytest.raises(RuntimeError, match="while control run"):
        begin_snapshot_refresh(conn)
    with pytest.raises(sqlite3.IntegrityError, match="snapshot inputs cannot change"):
        conn.execute(
            "INSERT INTO markets (ticker, title) VALUES ('T', 'changed')")

    fail_run(conn, rid, RuntimeError("test cleanup"))
    begin_snapshot_refresh(conn)


def test_completion_rejects_an_input_hash_changed_outside_the_write_guard(conn):
    register(conn, P)
    conn.execute("INSERT INTO markets (ticker, title) VALUES ('T', 'before')")
    conn.commit()
    rid = begin_run(conn, P, ("C4",))
    _record_execution(conn, rid)

    # Simulate external corruption or an older writer that lacks the trigger.
    conn.execute("DROP TRIGGER markets_deny_update_during_run")
    conn.execute("UPDATE markets SET title = 'after' WHERE ticker = 'T'")
    conn.commit()
    with pytest.raises(RuntimeError, match="inputs changed"):
        finish_run(conn, rid)
    assert conn.execute(
        "SELECT status FROM control_runs WHERE run_id = ?", (rid,)
    ).fetchone()[0] == "running"


def test_control_execution_is_immutable_after_run_finishes(conn):
    register(conn, P)
    rid = begin_run(conn, P, ("C4",))
    _record_execution(conn, rid)
    finish_run(conn, rid)

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE control_executions SET alert_count = 99 WHERE run_id = ?", (rid,))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM control_executions WHERE run_id = ?", (rid,))


def test_completed_execution_is_immutable_while_parent_run_is_still_running(conn):
    register(conn, P)
    rid = begin_run(conn, P, ("C4", "C5"))
    _record_execution(conn, rid, "C4")

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE control_executions SET alert_count = 99"
            " WHERE run_id = ? AND control_id = 'C4'", (rid,))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "DELETE FROM control_executions WHERE run_id = ? AND control_id = 'C4'", (rid,))


def test_control_execution_identity_cannot_change_while_it_finishes(conn):
    register(conn, P)
    rid = begin_run(conn, P, ("C4",))
    conn.execute("INSERT INTO control_executions (run_id, control_id, status, started_at)"
                 " VALUES (?, 'C4', 'running', 't')", (rid,))
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
        conn.execute(
            "UPDATE control_executions SET control_id = 'C5', status = 'complete',"
            " alert_count = 0, finished_at = 't' WHERE run_id = ? AND control_id = 'C4'",
            (rid,))


def test_completion_rejects_an_execution_alert_count_mismatch(conn):
    register(conn, P)
    rid = begin_run(conn, P, ("C4",))
    conn.execute("INSERT INTO control_executions (run_id, control_id, status, started_at)"
                 " VALUES (?, 'C4', 'running', 't')", (rid,))
    conn.execute("UPDATE control_executions SET status = 'complete', alert_count = 1,"
                 " finished_at = 't' WHERE run_id = ? AND control_id = 'C4'", (rid,))
    conn.commit()

    with pytest.raises(RuntimeError, match="alert count mismatch"):
        finish_run(conn, rid)


def test_terminal_control_run_identity_and_history_are_immutable(conn):
    register(conn, P)
    rid = begin_run(conn, P, ("C4",))
    _record_execution(conn, rid)
    finish_run(conn, rid)

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE control_runs SET input_hash = 'changed' WHERE run_id = ?", (rid,))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE control_runs SET failure = 'changed' WHERE run_id = ?", (rid,))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM control_runs WHERE run_id = ?", (rid,))
