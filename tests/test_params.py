import pytest
from kxsurv.params import load_params, params_hash, register, verify, ParamsDriftError


def test_hash_is_stable_across_key_order():
    a = {"version": "1.0.0", "x": {"b": 2, "a": 1}}
    b = {"x": {"a": 1, "b": 2}, "version": "1.0.0"}
    assert params_hash(a) == params_hash(b)


def test_hash_changes_when_a_value_changes():
    a = {"version": "1.0.0", "c3": {"min_candle_volume": 50.0}}
    b = {"version": "1.0.0", "c3": {"min_candle_volume": 51.0}}
    assert params_hash(a) != params_hash(b)


def test_verify_passes_for_registered_params(conn):
    p = {"version": "1.0.0", "c4": {"min_inversion_dollars": 0.01}}
    register(conn, p)
    verify(conn, p)  # must not raise


def test_verify_raises_on_unregistered_drift(conn):
    p = {"version": "1.0.0", "c4": {"min_inversion_dollars": 0.01}}
    register(conn, p)
    drifted = {"version": "1.0.0", "c4": {"min_inversion_dollars": 0.02}}
    with pytest.raises(ParamsDriftError):
        verify(conn, drifted)


def test_real_params_file_loads_and_has_all_five_controls():
    p = load_params("config/params.yaml")
    for k in ("c1_prerelease", "c2_prehalt", "c3_oi_divergence",
              "c4_monotonicity", "c5_settlement"):
        assert k in p, f"missing {k}"
    assert p["version"] == "1.0.0"
