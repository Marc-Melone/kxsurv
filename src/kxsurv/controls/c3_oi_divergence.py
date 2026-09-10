"""C3 - volume / open-interest divergence. CFTC DCM Core Principle 12.

A trade between a new buyer and a new seller raises open interest. A trade
closing both sides lowers it. A trade where the same beneficial owner sits on
both sides generates volume while leaving open interest unchanged.

OBSERVED NON-SPECIFIC SIGNATURE RATE (2026-09-07): flat OI despite volume
occurs in 26.0% of volume-bearing candles on KXCPI-26JUL-T0.3 and 16.2% on
KXPAYROLLS-26AUG-T60000. Public data does not label these observations benign;
open interest can stay flat when one participant closes while an unrelated
participant opens, an ordinary position transfer common in liquid two-sided
markets.

D is therefore a SCREENING PROXY, never evidence. Alerts require jointly: a
volume floor, a percentile computed WITHIN liquidity tier rather than globally,
and persistence across consecutive periods.
"""
from __future__ import annotations

from . import Alert, percentile_of

CONTROL_ID = "C3"

# Candles are ingested hourly; measured modal spacing is 3600s.
PERIOD_SECONDS = 3600


def liquidity_tier(oi: float, tiers: list[float]) -> int:
    t = 0
    for cut in tiers:
        if oi >= cut:
            t += 1
    return t


def divergence_series(candles: list[dict], epsilon: float) -> list[dict]:
    """Candles must be ascending by `end_period_ts`."""
    out: list[dict] = []
    prev = None
    for c in candles:
        vol = float(c.get("volume_fp") or 0.0)
        oi = float(c.get("open_interest_fp") or 0.0)
        # Delta OI must describe the same hourly interval as the volume. A
        # missing candle otherwise pairs one hour of volume with several hours
        # of OI movement and can anchor a spurious persistent alert.
        adjacent = (prev is not None
                    and c["end_period_ts"] - prev[0] == PERIOD_SECONDS)
        if adjacent and vol > 0:
            delta = oi - prev[1]
            out.append({
                "end_period_ts": c["end_period_ts"],
                "volume": vol, "delta_oi": delta, "open_interest": oi,
                "d": vol / (abs(delta) + epsilon),
            })
        prev = (c["end_period_ts"], oi)
    return out


def _candles_for(conn, ticker: str) -> list[dict]:
    cur = conn.execute(
        "SELECT end_period_ts, volume_fp, open_interest_fp FROM candles"
        " WHERE ticker = ? ORDER BY end_period_ts ASC", (ticker,))
    return [{"end_period_ts": r[0], "volume_fp": r[1], "open_interest_fp": r[2]}
            for r in cur.fetchall()]


def _populations(conn, p: dict) -> tuple[dict[str, list[dict]], dict[int, list[float]]]:
    """Build the exact within-tier population used by C3 scoring."""
    tiers = p["liquidity_tiers"]
    tickers = [r[0] for r in conn.execute(
        "SELECT DISTINCT c.ticker FROM candles c"
        " JOIN markets m ON m.ticker = c.ticker").fetchall()]
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
    return per_ticker, tier_pop


def coverage(conn, params: dict) -> dict[str, int]:
    """Report C3's scored population and percentile gate before persistence.

    This keeps headline selectivity figures reproducible from the same function
    that supplies `run`, rather than from a separate exploratory script.
    """
    p = params["c3_oi_divergence"]
    per_ticker, tier_pop = _populations(conn, p)
    scoreable = 0
    percentile_qualified = 0
    for rows in per_ticker.values():
        for r in rows:
            scoreable += 1
            if percentile_of(r["d"], tier_pop[r["tier"]]) >= p["percentile_threshold"]:
                percentile_qualified += 1
    return {"scoreable": scoreable, "percentile_qualified": percentile_qualified}


def run(conn, params: dict) -> list[Alert]:
    p = params["c3_oi_divergence"]

    # Pass 1: build per-tier populations so percentiles are ranked within tier.
    per_ticker, tier_pop = _populations(conn, p)

    # Pass 2: alert on runs that clear the tier percentile AND are adjacent in
    # time. Adjacency is the point of a persistence requirement -- counting
    # consecutive entries in the volume-filtered list let candles 36 days apart
    # count as "consecutive" (88 of 102 alerts, corrected 2026-09-07).
    alerts: list[Alert] = []
    for tk, rows in per_ticker.items():
        run_rows: list[dict] = []
        for r in rows:
            pct = percentile_of(r["d"], tier_pop.get(r["tier"], []))
            r["percentile"] = pct
            qualifies = pct >= p["percentile_threshold"]
            adjacent = (run_rows
                        and r["end_period_ts"] - run_rows[-1]["end_period_ts"]
                        == PERIOD_SECONDS)
            if qualifies and (not run_rows or adjacent):
                run_rows.append(r)
                continue
            if len(run_rows) >= p["min_persistence_periods"]:
                alerts.append(_alert(tk, run_rows, p))
            run_rows = [r] if qualifies else []
        if len(run_rows) >= p["min_persistence_periods"]:
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
            "span_hours": (rows[-1]["end_period_ts"] - rows[0]["end_period_ts"]) / 3600.0,
            "base_rate_note": "flat-OI signature frequency was 16.2-26.0% in "
                              "two cited market samples; public data does not "
                              "label it benign; this is a screening proxy, not "
                              "evidence",
        })
