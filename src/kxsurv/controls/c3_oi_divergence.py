"""C3 - volume / open-interest divergence. CFTC DCM Core Principle 12.

A trade between a new buyer and a new seller raises open interest. A trade
closing both sides lowers it. A trade where the same beneficial owner sits on
both sides generates volume while leaving open interest unchanged.

MEASURED BASE RATE (2026-09-07): flat OI despite volume occurs in 27% of
volume-bearing candles on KXCPI-26JUL-T0.3 and 18% on KXPAYROLLS-26AUG-T60000.
Open interest also stays flat when one participant closes while an unrelated
participant opens - ordinary position transfer, common in liquid two-sided
markets.

D is therefore a SCREENING PROXY, never evidence. Alerts require jointly: a
volume floor, a percentile computed WITHIN liquidity tier rather than globally,
and persistence across consecutive periods.
"""
from __future__ import annotations

from . import Alert, percentile_of

CONTROL_ID = "C3"


def liquidity_tier(oi: float, tiers: list[float]) -> int:
    t = 0
    for cut in tiers:
        if oi >= cut:
            t += 1
    return t


def divergence_series(candles: list[dict], epsilon: float) -> list[dict]:
    """Candles must be ascending by `end_period_ts`."""
    out: list[dict] = []
    prev_oi = None
    for c in candles:
        vol = float(c.get("volume_fp") or 0.0)
        oi = float(c.get("open_interest_fp") or 0.0)
        if prev_oi is not None and vol > 0:
            delta = oi - prev_oi
            out.append({
                "end_period_ts": c["end_period_ts"],
                "volume": vol, "delta_oi": delta, "open_interest": oi,
                "d": vol / (abs(delta) + epsilon),
            })
        prev_oi = oi
    return out


def _candles_for(conn, ticker: str) -> list[dict]:
    cur = conn.execute(
        "SELECT end_period_ts, volume_fp, open_interest_fp FROM candles"
        " WHERE ticker = ? ORDER BY end_period_ts ASC", (ticker,))
    return [{"end_period_ts": r[0], "volume_fp": r[1], "open_interest_fp": r[2]}
            for r in cur.fetchall()]


def run(conn, params: dict) -> list[Alert]:
    p = params["c3_oi_divergence"]
    tiers = p["liquidity_tiers"]
    tickers = [r[0] for r in conn.execute(
        "SELECT DISTINCT ticker FROM candles").fetchall()]

    # Pass 1: build per-tier populations so percentiles are ranked within tier.
    per_ticker: dict[str, list[dict]] = {}
    tier_pop: dict[int, list[float]] = {}
    for tk in tickers:
        rows = [r for r in divergence_series(_candles_for(conn, tk), p["epsilon"])
                if r["volume"] >= p["min_candle_volume"]]
        per_ticker[tk] = rows
        for r in rows:
            tier = liquidity_tier(r["open_interest"], tiers)
            r["tier"] = tier
            tier_pop.setdefault(tier, []).append(r["d"])

    # Pass 2: alert on runs that clear the tier percentile and persist.
    alerts: list[Alert] = []
    for tk, rows in per_ticker.items():
        run_len = 0
        run_rows: list[dict] = []
        for r in rows:
            pct = percentile_of(r["d"], tier_pop.get(r["tier"], []))
            r["percentile"] = pct
            if pct >= p["percentile_threshold"]:
                run_len += 1
                run_rows.append(r)
                continue
            if run_len >= p["min_persistence_periods"]:
                alerts.append(_alert(tk, run_rows, p))
            run_len, run_rows = 0, []
        if run_len >= p["min_persistence_periods"]:
            alerts.append(_alert(tk, run_rows, p))
    return alerts


def _alert(ticker: str, rows: list[dict], p: dict) -> Alert:
    peak = max(rows, key=lambda r: r["d"])
    return Alert(
        control_id=CONTROL_ID, target=ticker,
        window_start=str(rows[0]["end_period_ts"]),
        window_end=str(rows[-1]["end_period_ts"]),
        score=peak["d"], percentile=peak["percentile"],
        threshold=p["percentile_threshold"],
        evidence={
            "periods": len(rows),
            "total_volume": sum(r["volume"] for r in rows),
            "peak_d": peak["d"], "peak_delta_oi": peak["delta_oi"],
            "liquidity_tier": peak["tier"],
            "base_rate_note": "flat-OI base rate measured at 18-27%; "
                              "this is a screening proxy, not evidence",
        })
