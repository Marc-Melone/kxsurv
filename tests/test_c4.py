from kxsurv.controls.c4_monotonicity import find_inversions

# strike, mid, half_spread
CLEAN = [(0.1, 0.94, 0.005), (0.2, 0.92, 0.005), (0.3, 0.875, 0.005)]


def test_monotone_ladder_yields_no_inversions():
    assert find_inversions(CLEAN, min_inversion=0.01,
                           require_exceeds_half_spread=True) == []


def test_detects_planted_inversion_beyond_spread():
    rows = [(0.1, 0.90, 0.005), (0.2, 0.95, 0.005), (0.3, 0.80, 0.005)]
    out = find_inversions(rows, min_inversion=0.01,
                          require_exceeds_half_spread=True)
    assert len(out) == 1
    assert out[0]["lower_strike"] == 0.1
    assert out[0]["upper_strike"] == 0.2
    assert abs(out[0]["magnitude"] - 0.05) < 1e-9


def test_ignores_one_cent_inversion_inside_the_spread():
    """The real KXPAYROLLS-26SEP case: 50000 @ 0.5350 below 60000 @ 0.5450.

    A 1c inversion sitting inside the combined half-spread is quote staleness,
    not distortion. This is the project's worked no-action example.
    """
    rows = [(50000.0, 0.5350, 0.010), (60000.0, 0.5450, 0.010)]
    assert find_inversions(rows, min_inversion=0.01,
                           require_exceeds_half_spread=True) == []


def test_same_case_surfaces_when_spread_filter_disabled():
    rows = [(50000.0, 0.5350, 0.010), (60000.0, 0.5450, 0.010)]
    out = find_inversions(rows, min_inversion=0.01,
                          require_exceeds_half_spread=False)
    assert len(out) == 1


def test_equal_prices_are_not_an_inversion():
    rows = [(0.1, 0.50, 0.005), (0.2, 0.50, 0.005)]
    assert find_inversions(rows, min_inversion=0.01,
                           require_exceeds_half_spread=True) == []
