import sqlite3

import pytest
from kxsurv.controls import Alert, save_alerts
from kxsurv.params import register
from kxsurv.runs import begin_run
from kxsurv.triage import disposition, funnel, open_alerts, ACTIONS


_seq = iter(range(1, 1000))
P = {"version": "triage-test"}


def _run_id(conn):
    row = conn.execute(
        "SELECT run_id FROM control_runs WHERE status = 'running' ORDER BY run_id DESC"
    ).fetchone()
    if row is not None:
        return row[0]
    register(conn, P)
    return begin_run(conn, P, ("C3", "C4"))


def _alert(conn, control="C4"):
    """Distinct target per call: alerts carry a natural key of
    (control, target, window_start, window_end, params_hash), so identical rows
    are deduplicated by design."""
    run_id = _run_id(conn)
    save_alerts(conn, [Alert(control, "T{}".format(next(_seq)), None, None,
                             1.0, None, None, {})], P, run_id)
    return conn.execute("SELECT MAX(alert_id) FROM alerts").fetchone()[0]


def test_actions_are_the_closed_disposition_vocabulary():
    assert ACTIONS == frozenset({"no_action", "escalated", "monitor"})


def test_disposition_requires_a_rationale(conn):
    aid = _alert(conn)
    with pytest.raises(ValueError, match="rationale"):
        disposition(conn, aid, "no_action", "   ")


def test_disposition_rejects_unknown_action(conn):
    aid = _alert(conn)
    with pytest.raises(ValueError, match="action"):
        disposition(conn, aid, "closed_lol", "because")


def test_funnel_counts_generated_triaged_and_escalated(conn):
    a1, a2, a3 = _alert(conn), _alert(conn), _alert(conn, "C3")
    disposition(conn, a1, "no_action", "1c inversion inside combined spread")
    disposition(conn, a2, "escalated", "persistent, volume-accompanied")
    f = funnel(conn, _run_id(conn))
    assert f["generated"] == 3
    assert f["triaged"] == 2
    assert f["escalated"] == 1
    assert f["no_action"] == 1
    assert f["untriaged"] == 1


def test_funnel_breaks_down_by_control(conn):
    a1 = _alert(conn, "C4")
    _alert(conn, "C3")
    disposition(conn, a1, "no_action", "stale quote")
    f = funnel(conn, _run_id(conn))
    assert f["by_control"]["C4"]["generated"] == 1
    assert f["by_control"]["C3"]["generated"] == 1


def test_open_alerts_excludes_dispositioned(conn):
    a1, a2 = _alert(conn), _alert(conn)
    disposition(conn, a1, "monitor", "watch next snapshot")
    assert [a["alert_id"] for a in open_alerts(conn, _run_id(conn))] == [a2]


def test_revising_a_disposition_does_not_inflate_the_funnel(conn):
    aid = _alert(conn)
    disposition(conn, aid, "monitor", "initial watch")
    disposition(conn, aid, "no_action", "later evidence resolved the concern")
    f = funnel(conn, _run_id(conn))
    assert f["generated"] == f["triaged"] == f["no_action"] == 1
    assert f["monitor"] == 0


def test_disposition_revisions_are_append_only(conn):
    aid = _alert(conn)
    did = disposition(conn, aid, "monitor", "initial review")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE dispositions SET rationale = 'rewritten' WHERE disposition_id = ?",
            (did,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM dispositions WHERE disposition_id = ?", (did,))
