"""C2 - pre-halt price pressure ("marking the close"). Core Principle 4.

Aggressive one-sided flow that displaces price in the final minutes before a
halt, concentrated in thin markets. Imbalance, displacement and thinness must
co-occur: each alone is unremarkable.

Known false-positive mode: genuine late information arrival, and ordinary
position-squaring ahead of a halt.
"""
from __future__ import annotations

from datetime import timedelta

from . import Alert
from .c1_prerelease import _iso, _parse

CONTROL_ID = "C2"


def imbalance_ratio(trades: list[dict]) -> tuple[float, float]:
    """Returns (|signed| / total, total). 1.0 means perfectly one-sided."""
    total = sum(float(t["count_fp"]) for t in trades)
    if total <= 0:
        return 0.0, 0.0
    signed = sum(float(t["count_fp"]) * (1 if t["taker_side"] == "yes" else -1)
                 for t in trades)
    return abs(signed) / total, total


def run(conn, params: dict) -> list[Alert]:
    p = params["c2_prehalt"]
    N = timedelta(minutes=p["window_minutes"])
    alerts: list[Alert] = []

    rows = conn.execute(
        "SELECT m.ticker, m.close_time FROM markets m"
        " JOIN ingest_log i USING(ticker)"
        " WHERE m.close_time IS NOT NULL AND i.complete = 1 AND i.tape_volume > 0"
    ).fetchall()

    for ticker, close_str in rows:
        halt = _parse(close_str)
        window = conn.execute(
            "SELECT count_fp, taker_side, yes_price, created_time FROM trades"
            " WHERE ticker = ? AND created_time >= ? AND created_time <= ?"
            " ORDER BY created_time ASC",
            (ticker, _iso(halt - N), _iso(halt))).fetchall()
        if len(window) < 2:
            continue

        trades = [{"count_fp": r[0], "taker_side": r[1]} for r in window]
        ratio, total = imbalance_ratio(trades)
        displacement = abs(window[-1][2] - window[0][2])

        if (ratio >= p["min_imbalance_ratio"]
                and displacement >= p["min_price_displacement"]
                and total <= p["max_thinness_volume"]):
            alerts.append(Alert(
                control_id=CONTROL_ID, target=ticker,
                window_start=window[0][3], window_end=window[-1][3],
                score=ratio * displacement, percentile=None,
                threshold=p["min_imbalance_ratio"],
                evidence={
                    "imbalance_ratio": ratio, "displacement": displacement,
                    "window_volume": total, "trade_count": len(window),
                    "price_open": window[0][2], "price_close": window[-1][2],
                    "limitation": "late public information and ordinary "
                                  "position-squaring produce this signature",
                }))
    return alerts
