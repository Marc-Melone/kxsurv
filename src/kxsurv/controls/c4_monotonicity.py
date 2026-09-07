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

CORRECTED 2026-09-07. The first implementation took each strike's most recent
quote independently. Measured across 28 events, 12 had strike quotes spanning
more than 24 hours (worst: 194h), so the control was comparing a strike quoted
eight days ago against one quoted an hour ago. Monotonicity is a statement about
SIMULTANEOUS prices, so quotes are now grouped by candle period and only strikes
present in the same period are compared. This also makes
`min_persistence_snapshots` operative: an inversion must survive consecutive
snapshots to alert.
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


def snapshots(conn, event_ticker: str) -> list[tuple[int, list[tuple]]]:
    """Quotes grouped by candle period, ascending by period then strike.

    Monotonicity is a statement about simultaneous prices. Grouping by
    `end_period_ts` guarantees every comparison is snapshot-consistent. Strikes
    missing from a period are simply absent from that snapshot -- monotonicity
    is transitive, so comparing consecutive *present* strikes remains valid.
    """
    cur = conn.execute(
        "SELECT c.end_period_ts, m.floor_strike, c.yes_bid_close, c.yes_ask_close"
        " FROM candles c JOIN markets m ON m.ticker = c.ticker"
        " WHERE m.event_ticker = ? AND m.floor_strike IS NOT NULL"
        "   AND c.yes_bid_close IS NOT NULL AND c.yes_ask_close IS NOT NULL"
        " ORDER BY c.end_period_ts ASC, m.floor_strike ASC", (event_ticker,))
    grouped: dict[int, list[tuple]] = {}
    for ts, strike, bid, ask in cur.fetchall():
        grouped.setdefault(ts, []).append(
            (strike, (bid + ask) / 2.0, (ask - bid) / 2.0))
    return sorted(grouped.items())


def run(conn, params: dict) -> list[Alert]:
    """Alert only where the SAME adjacent-strike pair inverts across
    `min_persistence_snapshots` consecutive snapshots. A transient inversion is
    a stale quote; a persistent one is a standing incoherence."""
    p = params["c4_monotonicity"]
    need = p.get("min_persistence_snapshots", 1)
    events = [r[0] for r in conn.execute(
        "SELECT DISTINCT event_ticker FROM markets"
        " WHERE strike_type = 'greater' AND event_ticker IS NOT NULL").fetchall()]

    alerts: list[Alert] = []
    for ev in events:
        snaps = snapshots(conn, ev)
        # pair -> consecutive-snapshot run currently open
        streak: dict[tuple, list[dict]] = {}
        for ts, rows in snaps:
            if len(rows) < 2:
                streak = {}
                continue
            found = {}
            for inv in find_inversions(rows, p["min_inversion_dollars"],
                                       p["require_exceeds_half_spread"]):
                key = (inv["lower_strike"], inv["upper_strike"])
                found[key] = dict(inv, peak_snapshot_ts=ts)
            # extend runs that continue; drop those that broke
            streak = {k: streak.get(k, []) + [v] for k, v in found.items()}
            for key, run_rows in streak.items():
                if len(run_rows) == need:      # fire once, on reaching `need`
                    peak = max(run_rows, key=lambda r: r["magnitude"])
                    alerts.append(Alert(
                        control_id=CONTROL_ID,
                        # the strike pair identifies the alert: several pairs
                        # can invert in one event and window simultaneously
                        target="{}:{}>{}".format(ev, key[0], key[1]),
                        window_start=str(run_rows[0]["peak_snapshot_ts"]),
                        window_end=str(run_rows[-1]["peak_snapshot_ts"]),
                        score=peak["magnitude"], percentile=None,
                        threshold=p["min_inversion_dollars"],
                        evidence={**peak,
                                  "snapshots_persisted": len(run_rows),
                                  "strikes_in_snapshot": len(rows)}))
    return alerts
