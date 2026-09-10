from kxsurv.controls import Alert, save_alerts
from kxsurv.params import register
from kxsurv.report import case_file_markdown, funnel_markdown
from kxsurv.runs import begin_run, finish_run
from kxsurv.triage import disposition


def _alert(conn):
    p = {"version": "report-test"}
    register(conn, p)
    run_id = begin_run(conn, p, ("C4",))
    save_alerts(conn, [Alert(
        "C4", "KXPAYROLLS-26SEP", None, None, .01, None, None,
        {"magnitude": .01},
    )], p, run_id)
    conn.execute(
        "INSERT INTO control_executions (run_id, control_id, status, started_at)"
        " VALUES (?, 'C4', 'running', 't')", (run_id,))
    conn.execute(
        "UPDATE control_executions SET status = 'complete', alert_count = 1,"
        " finished_at = 't' WHERE run_id = ? AND control_id = 'C4'", (run_id,))
    conn.commit()
    finish_run(conn, run_id)
    return conn.execute("SELECT MAX(alert_id) FROM alerts").fetchone()[0]


def test_funnel_markdown_reports_counts(conn):
    aid = _alert(conn)
    disposition(conn, aid, "monitor", "inside combined spread")
    md = funnel_markdown(conn)
    assert "Generated" in md and "Monitor" in md


def test_case_file_contains_every_mandatory_section(conn):
    aid = _alert(conn)
    disposition(conn, aid, "no_action", "1c inversion inside combined spread")
    md = case_file_markdown(
        conn, aid,
        timeline="Snapshot 2026-09-07.",
        alternatives="Adjacent-strike quote staleness.",
        limitations="No counterparty identity in public data.")
    for section in ("## Summary", "## Timeline", "## Evidence",
                    "## Alternative innocent explanations",
                    "## Limitations", "## Disposition"):
        assert section in md, "missing {}".format(section)


def test_escalated_case_uses_the_fixed_language(conn):
    aid = _alert(conn)
    disposition(conn, aid, "escalated", "persistent and volume-accompanied")
    md = case_file_markdown(conn, aid, timeline="t", alternatives="a",
                            limitations="l")
    assert "account-level data held only by the exchange" in md
