import pytest
from kxsurv.controls import Alert, save_alerts, run_control
from kxsurv.params import register, ParamsDriftError

P = {"version": "1.0.0", "c4_monotonicity": {"min_inversion_dollars": 0.01}}


def test_alert_persists_with_params_hash(conn):
    register(conn, P)
    save_alerts(conn, [Alert("C4", "KXCPI-26SEP", None, None, 0.01, 99.0, 0.01,
                             {"strike": 0.3})], P)
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
        run_control(conn, Mod, P)


def test_run_control_executes_when_registered(conn):
    register(conn, P)

    class Mod:
        @staticmethod
        def run(conn, params):
            return [Alert("C4", "T", None, None, 1.0, 99.0, 0.5, {})]
    out = run_control(conn, Mod, P)
    assert len(out) == 1 and out[0].control_id == "C4"


def test_saving_the_same_alert_twice_does_not_duplicate(conn):
    """Re-running controls previously doubled the alert table: 51 alerts
    became 102, so the published funnel figures no longer matched the data."""
    register(conn, P)
    a = Alert("C4", "KXCPI-26SEP", "1000", "2000", 0.05, 99.0, 0.01, {"m": 1})
    save_alerts(conn, [a], P)
    save_alerts(conn, [a], P)
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1


def test_a_different_window_is_a_different_alert(conn):
    register(conn, P)
    save_alerts(conn, [Alert("C4", "T", "1000", "2000", 0.05, None, 0.01, {})], P)
    save_alerts(conn, [Alert("C4", "T", "3000", "4000", 0.05, None, 0.01, {})], P)
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 2
