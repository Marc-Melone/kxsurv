from kxsurv.controls.c1_prerelease import aggressor_direction, informed_flow_score


def t(size, taker_side):
    return {"count_fp": size, "taker_side": taker_side}


def test_aggressor_direction_validated_semantics():
    """taker_side == 'yes' means the aggressor BOUGHT YES.

    Validated 2026-09-07 on KXCPI-26JUL-T0.3 (686 trades, result='no'):
    signed volume agreed with realised price direction in 5/5 blocks.
    """
    assert aggressor_direction("yes", settled_yes=True) == 1
    assert aggressor_direction("no", settled_yes=True) == -1
    assert aggressor_direction("no", settled_yes=False) == 1
    assert aggressor_direction("yes", settled_yes=False) == -1


def test_consensus_flow_scores_near_zero():
    """Buying the eventual winner at 0.99 is consensus, not information."""
    s = informed_flow_score([t(100, "yes")], p0=0.99, settled_yes=True)
    assert abs(s - 0.01) < 1e-9


def test_flow_from_an_unlikely_price_scores_high():
    s = informed_flow_score([t(100, "yes")], p0=0.20, settled_yes=True)
    assert abs(s - 0.80) < 1e-9


def test_flow_away_from_the_outcome_scores_negative():
    s = informed_flow_score([t(100, "no")], p0=0.20, settled_yes=True)
    assert abs(s + 0.80) < 1e-9


def test_score_is_size_weighted():
    trades = [t(900, "yes"), t(100, "no")]
    s = informed_flow_score(trades, p0=0.50, settled_yes=True)
    assert abs(s - 0.40) < 1e-9      # (900-100)/1000 * 0.5


def test_empty_window_scores_zero():
    assert informed_flow_score([], p0=0.5, settled_yes=True) == 0.0
