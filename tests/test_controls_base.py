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
