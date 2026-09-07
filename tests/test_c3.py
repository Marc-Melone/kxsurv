from kxsurv.controls.c3_oi_divergence import divergence_series, liquidity_tier


def test_matched_open_close_yields_low_divergence():
    c = [{"end_period_ts": 1, "volume_fp": 0.0, "open_interest_fp": 100.0},
         {"end_period_ts": 2, "volume_fp": 50.0, "open_interest_fp": 150.0}]
    out = divergence_series(c, epsilon=1.0)
    assert len(out) == 1
    assert out[0]["d"] < 1.1          # 50 / (50 + 1)


def test_flat_oi_with_volume_yields_high_divergence():
    c = [{"end_period_ts": 1, "volume_fp": 0.0, "open_interest_fp": 880.49},
         {"end_period_ts": 2, "volume_fp": 101.0, "open_interest_fp": 880.49}]
    out = divergence_series(c, epsilon=1.0)
    assert out[0]["delta_oi"] == 0.0
    assert out[0]["d"] == 101.0


def test_zero_volume_periods_are_skipped():
    c = [{"end_period_ts": 1, "volume_fp": 0.0, "open_interest_fp": 100.0},
         {"end_period_ts": 2, "volume_fp": 0.0, "open_interest_fp": 100.0}]
    assert divergence_series(c, epsilon=1.0) == []


def test_first_candle_has_no_predecessor_and_is_skipped():
    c = [{"end_period_ts": 1, "volume_fp": 500.0, "open_interest_fp": 100.0}]
    assert divergence_series(c, epsilon=1.0) == []


def test_liquidity_tiers_partition_by_open_interest():
    tiers = [100.0, 1000.0, 10000.0]
    assert liquidity_tier(50.0, tiers) == 0
    assert liquidity_tier(500.0, tiers) == 1
    assert liquidity_tier(5000.0, tiers) == 2
    assert liquidity_tier(50000.0, tiers) == 3
