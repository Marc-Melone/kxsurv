import json
from kxsurv.report import case_file_markdown, funnel_markdown
from kxsurv.triage import disposition


def _alert(conn):
    conn.execute(
        "INSERT INTO alerts (control_id, target, score, percentile, evidence,"
        " params_hash, created_at) VALUES ('C4','KXPAYROLLS-26SEP',0.01,NULL,?,"
        " 'h','2026-09-07T00:00:00Z')", (json.dumps({"magnitude": 0.01}),))
    conn.commit()
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
