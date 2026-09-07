from kxsurv.controls.c2_prehalt import imbalance_ratio


def t(size, side):
    return {"count_fp": size, "taker_side": side}


def test_balanced_flow_has_low_imbalance():
    ratio, total = imbalance_ratio([t(100, "yes"), t(100, "no")])
    assert ratio == 0.0 and total == 200.0


def test_one_sided_flow_has_maximal_imbalance():
    ratio, total = imbalance_ratio([t(100, "yes"), t(300, "yes")])
    assert ratio == 1.0 and total == 400.0


def test_partial_imbalance_is_proportional():
    ratio, _ = imbalance_ratio([t(850, "yes"), t(150, "no")])
    assert abs(ratio - 0.70) < 1e-9


def test_empty_window_is_zero():
    assert imbalance_ratio([]) == (0.0, 0.0)
