import sqlite3

import pytest
from kxsurv.controls import Alert, save_alerts, run_control
from kxsurv.params import register, ParamsDriftError
from kxsurv.runs import begin_run, finish_run
from kxsurv.triage import funnel

P = {"version": "1.0.0", "c4_monotonicity": {"min_inversion_dollars": 0.01}}


def test_alert_persists_with_params_hash(conn):
    register(conn, P)
    run_id = begin_run(conn, P, ("C4",))
    save_alerts(conn, [Alert("C4", "KXCPI-26SEP", None, None, 0.01, 99.0, 0.01,
                             {"strike": 0.3})], P, run_id)
    row = conn.execute(
        "SELECT control_id, target, score, evidence, params_hash FROM alerts"
    ).fetchone()
    assert row[0] == "C4" and row[1] == "KXCPI-26SEP" and row[2] == 0.01
    assert '"strike": 0.3' in row[3]
    assert len(row[4]) == 64


def test_run_control_refuses_unregistered_params(conn):
    class Mod:
        @staticmethod
        def run(conn, params): return []
    with pytest.raises(ParamsDriftError):
        run_control(conn, Mod, P, 1)


def test_run_control_executes_when_registered(conn):
    register(conn, P)
    run_id = begin_run(conn, P, ("C4",))

    class Mod:
        CONTROL_ID = "C4"

        @staticmethod
        def run(conn, params):
            return [Alert("C4", "T", None, None, 1.0, 99.0, 0.5, {})]
    out = run_control(conn, Mod, P, run_id)
    assert len(out) == 1 and out[0].control_id == "C4"
    assert conn.execute(
        "SELECT status, alert_count FROM control_executions"
    ).fetchone() == ("complete", 1)


def test_zero_alert_control_is_recorded_as_complete(conn):
    register(conn, P)
    run_id = begin_run(conn, P, ("C2",))

    class Mod:
        CONTROL_ID = "C2"

        @staticmethod
        def run(conn, params):
            return []

    assert run_control(conn, Mod, P, run_id) == []
    assert conn.execute(
        "SELECT control_id, status, alert_count FROM control_executions"
    ).fetchone() == ("C2", "complete", 0)
    finish_run(conn, run_id)
    assert funnel(conn)["by_control"]["C2"]["generated"] == 0


def test_failed_control_has_its_own_audit_record(conn):
    register(conn, P)
    run_id = begin_run(conn, P, ("C3",))

    class Broken:
        CONTROL_ID = "C3"

        @staticmethod
        def run(conn, params):
            raise RuntimeError("planted failure")

    with pytest.raises(RuntimeError, match="planted"):
        run_control(conn, Broken, P, run_id)
    assert conn.execute(
        "SELECT status, failure FROM control_executions"
    ).fetchone() == ("failed", "RuntimeError: planted failure")
    with pytest.raises(RuntimeError, match="unfinished"):
        finish_run(conn, run_id)


def test_saving_the_same_alert_twice_fails_closed_without_a_second_row(conn):
    """Re-running one control must not duplicate its alert rows."""
    register(conn, P)
    run_id = begin_run(conn, P, ("C4",))
    a = Alert("C4", "KXCPI-26SEP", "1000", "2000", 0.05, 99.0, 0.01, {"m": 1})
    assert save_alerts(conn, [a], P, run_id) == 1
    with pytest.raises(sqlite3.IntegrityError):
        save_alerts(conn, [a], P, run_id)
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1


def test_a_different_window_is_a_different_alert(conn):
    register(conn, P)
    run_id = begin_run(conn, P, ("C4",))
    save_alerts(conn, [Alert("C4", "T", "1000", "2000", 0.05, None, 0.01, {})], P, run_id)
    save_alerts(conn, [Alert("C4", "T", "3000", "4000", 0.05, None, 0.01, {})], P, run_id)
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 2


def test_later_run_keeps_revised_evidence_separate(conn):
    register(conn, P)
    first, second = begin_run(conn, P, ("C4",)), begin_run(conn, P, ("C4",))
    old = Alert("C4", "T", "1000", "2000", 0.01, None, 0.01, {"v": "old"})
    new = Alert("C4", "T", "1000", "2000", 0.50, None, 0.01, {"v": "new"})
    save_alerts(conn, [old], P, first)
    save_alerts(conn, [new], P, second)
    rows = conn.execute("SELECT run_id, score, evidence FROM alerts ORDER BY run_id").fetchall()
    assert rows == [(first, 0.01, '{"v": "old"}'), (second, 0.5, '{"v": "new"}')]


def test_save_alerts_rejects_a_completed_run(conn):
    register(conn, P)
    run_id = begin_run(conn, P, ("C4",))
    # a run can only complete once a control has actually executed
    conn.execute("INSERT INTO control_executions (run_id, control_id, status, started_at)"
                 " VALUES (?, 'C4', 'running', 't')", (run_id,))
    conn.execute("UPDATE control_executions SET status = 'complete', alert_count = 0,"
                 " finished_at = 't' WHERE run_id = ? AND control_id = 'C4'", (run_id,))
    conn.commit()
    finish_run(conn, run_id)
    with pytest.raises(ValueError, match="matching running"):
        save_alerts(conn, [Alert("C4", "T", None, None, 1.0, None, None, {})],
                    P, run_id)


def test_save_alerts_rejects_a_run_registered_for_other_parameters(conn):
    other = {"version": "2.0.0", "c4_monotonicity": {"min_inversion_dollars": 0.02}}
    register(conn, P)
    register(conn, other)
    run_id = begin_run(conn, P, ("C4",))
    with pytest.raises(ValueError, match="matching running"):
        save_alerts(conn, [Alert("C4", "T", None, None, 1.0, None, None, {})],
                    other, run_id)
