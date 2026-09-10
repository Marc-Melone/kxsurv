"""C2 - pre-halt price pressure ("marking the close"). Core Principle 4.

Aggressive one-sided flow that displaces price in the final minutes before a
halt, concentrated in thin markets. Imbalance, displacement and thinness must
co-occur: each alone is unremarkable.

Known false-positive modes: bid-ask bounce or trade sequencing in a wide,
thin market, genuine late public information, and ordinary position-squaring
ahead of a halt.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from . import Alert
from .c1_prerelease import _iso, _parse, taker_outcome_side

CONTROL_ID = "C2"


def imbalance_ratio(trades: list[dict]) -> tuple[float, float]:
    """Returns (|signed| / total, total). 1.0 means perfectly one-sided."""
    total = sum(float(t["count_fp"]) for t in trades)
    if total <= 0:
        return 0.0, 0.0
    signed = sum(float(t["count_fp"]) * (1 if taker_outcome_side(t) == "yes" else -1)
                 for t in trades)
    return abs(signed) / total, total


def signed_imbalance(trades: list[dict]) -> float:
    """YES-positive net aggressor flow, scaled to [-1, 1]."""
    total = sum(float(t["count_fp"]) for t in trades)
    if total <= 0:
        return 0.0
    signed = sum(float(t["count_fp"]) * (1 if taker_outcome_side(t) == "yes" else -1)
                 for t in trades)
    return signed / total


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
            "SELECT count_fp, taker_outcome_side, yes_price, created_time FROM trades"
            " WHERE ticker = ? AND created_time >= ? AND created_time < ?"
            " ORDER BY created_time ASC",
            (ticker, _iso(halt - N), _iso(halt))).fetchall()
        if len(window) < 2:
            continue

        trades = [{"count_fp": r[0], "taker_outcome_side": r[1]} for r in window]
        ratio, total = imbalance_ratio(trades)
        net_flow = signed_imbalance(trades)
        # Quoted prices are decimal monetary values stored in SQLite REALs.
        # Reconstruct their shortest decimal representation before applying an
        # inclusive cent boundary; binary subtraction can turn 0.45 - 0.40 into
        # 0.049999... and wrongly reject an exact five-cent move.
        price_change_decimal = (Decimal(str(window[-1][2]))
                                - Decimal(str(window[0][2])))
        displacement_decimal = abs(price_change_decimal)
        price_change = float(price_change_decimal)
        displacement = float(displacement_decimal)
        directionally_aligned = (
            (net_flow > 0 and price_change_decimal > 0)
            or (net_flow < 0 and price_change_decimal < 0)
        )

        if (ratio >= p["min_imbalance_ratio"]
                and displacement_decimal >= Decimal(str(p["min_price_displacement"]))
                and total <= p["max_thinness_volume"]
                and directionally_aligned):
            alerts.append(Alert(
                control_id=CONTROL_ID, target=ticker,
                window_start=window[0][3], window_end=window[-1][3],
                # The control is a conjunction, so no single threshold covers
                # every gate. Report displacement as the score and its
                # like-for-like floor as threshold; retain the other registered
                # gates in evidence.
                score=displacement, percentile=None,
                threshold=p["min_price_displacement"],
                evidence={
                    "imbalance_ratio": ratio, "signed_imbalance": net_flow,
                    "price_change": price_change, "displacement": displacement,
                    "window_volume": total, "trade_count": len(window),
                    "price_open": window[0][2], "price_close": window[-1][2],
                    "registered_gates": {
                        "min_imbalance_ratio": p["min_imbalance_ratio"],
                        "min_price_displacement": p["min_price_displacement"],
                        "max_thinness_volume": p["max_thinness_volume"],
                        "directional_alignment": True,
                    },
                    "limitation": "bid-ask bounce, trade sequencing, late "
                                  "public information, and ordinary position-"
                                  "squaring can produce this signature",
                }))
    return alerts
