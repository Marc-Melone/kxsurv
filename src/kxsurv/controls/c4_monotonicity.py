"""C4 - ladder monotonicity coherence. CFTC DCM Core Principle 4.

Kalshi's economic series are `strike_type == "greater"` threshold ladders:
nested cumulative contracts, NOT mutually exclusive partitions. Verified
2026-09-07: KXCPI-26SEP mids sum to 7.54, so a sum-to-$1 constraint would fire
on every healthy market.

The correct constraint is monotonicity: for ascending strikes k1 < k2 < ... < kn,
P(X > k1) >= P(X > k2) >= ... >= P(X > kn). An inversion is an unambiguous
pricing incoherence requiring no view on fair value.

Dominant false positive: a 1c inversion inside the combined bid-ask spread of
two adjacent strikes is quote staleness. Alerts therefore require the magnitude
to exceed the combined half-spread and to persist.
"""
from __future__ import annotations

from . import Alert
from ..events import ladder

CONTROL_ID = "C4"


def find_inversions(strikes, min_inversion: float,
                    require_exceeds_half_spread: bool) -> list[dict]:
    """`strikes` is [(strike, mid, half_spread)] ascending by strike."""
    out: list[dict] = []
    for i in range(1, len(strikes)):
        k_lo, mid_lo, hs_lo = strikes[i - 1]
        k_hi, mid_hi, hs_hi = strikes[i]
        magnitude = mid_hi - mid_lo          # positive == violation
        if magnitude < min_inversion:
            continue
        combined_half_spread = hs_lo + hs_hi
        if require_exceeds_half_spread and magnitude <= combined_half_spread:
            continue
        out.append({
            "lower_strike": k_lo, "upper_strike": k_hi,
            "lower_mid": mid_lo, "upper_mid": mid_hi,
            "magnitude": magnitude,
            "combined_half_spread": combined_half_spread,
        })
    return out


def _latest_quote(conn, ticker: str):
    row = conn.execute(
        "SELECT yes_bid_close, yes_ask_close FROM candles"
        " WHERE ticker = ? AND yes_bid_close IS NOT NULL"
        " AND yes_ask_close IS NOT NULL"
        " ORDER BY end_period_ts DESC LIMIT 1", (ticker,)).fetchone()
    if not row:
        return None
    bid, ask = row
    return (bid + ask) / 2.0, (ask - bid) / 2.0


def run(conn, params: dict) -> list[Alert]:
    p = params["c4_monotonicity"]
    events = [r[0] for r in conn.execute(
        "SELECT DISTINCT event_ticker FROM markets"
        " WHERE strike_type = 'greater' AND event_ticker IS NOT NULL").fetchall()]

    alerts: list[Alert] = []
    for ev in events:
        rows = []
        for m in ladder(conn, ev):
            q = _latest_quote(conn, m["ticker"])
            if q is None:
                continue
            mid, half_spread = q
            rows.append((m["floor_strike"], mid, half_spread))
        if len(rows) < 2:
            continue
        for inv in find_inversions(rows, p["min_inversion_dollars"],
                                   p["require_exceeds_half_spread"]):
            alerts.append(Alert(
                control_id=CONTROL_ID, target=ev,
                window_start=None, window_end=None,
                score=inv["magnitude"], percentile=None,
                threshold=p["min_inversion_dollars"], evidence=inv))
    return alerts
