import pytest
from kxsurv.triage import disposition, funnel, open_alerts, ACTIONS


_seq = iter(range(1, 1000))


def _alert(conn, control="C4"):
    """Distinct target per call: alerts carry a natural key of
    (control, target, window_start, window_end, params_hash), so identical rows
    are deduplicated by design."""
    conn.execute(
        "INSERT INTO alerts (control_id, target, score, params_hash, created_at)"
        " VALUES (?, ?, 1.0, 'h', '2026-09-07T00:00:00Z')",
        (control, "T{}".format(next(_seq))))
    conn.commit()
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
    f = funnel(conn)
    assert f["generated"] == 3
    assert f["triaged"] == 2
    assert f["escalated"] == 1
    assert f["no_action"] == 1
    assert f["untriaged"] == 1


def test_funnel_breaks_down_by_control(conn):
    a1 = _alert(conn, "C4")
    _alert(conn, "C3")
    disposition(conn, a1, "no_action", "stale quote")
    f = funnel(conn)
    assert f["by_control"]["C4"]["generated"] == 1
    assert f["by_control"]["C3"]["generated"] == 1


def test_open_alerts_excludes_dispositioned(conn):
    a1, a2 = _alert(conn), _alert(conn)
    disposition(conn, a1, "monitor", "watch next snapshot")
    assert [a["alert_id"] for a in open_alerts(conn)] == [a2]
