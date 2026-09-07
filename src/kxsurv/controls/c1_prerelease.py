"""C1 - pre-release informed trading. CFTC DCM Core Principle 12.

Kalshi halts economic-release markets before the print (KXCPI-26JUL close_time
12:25:00Z == 08:25 ET, five minutes ahead of the BLS 08:30 ET publication).
C1 asks whether that window is adequate, not whether it exists.

The naive metric -- "did pre-release flow predict the outcome" -- is wrong: a
trade at $0.99 on the eventual winner is consensus, not information. The
informed signature is aggressive flow toward the eventual outcome FROM AN
EXECUTION PRICE THAT DID NOT ALREADY IMPLY IT, hence the surprise weighting.

SAMPLE SIZE: 9 distinct information events across all five economic series
(132 settled markets, but brackets within an event are not independent). C1
makes NO population-level statistical claim. It is validated by fixture
detection behaviour and analyst triage.

COVERAGE: C1 reads the trade tape, which Kalshi retains for ~66 days. Markets
beyond that horizon cannot be scored and are skipped.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import Alert, percentile_of
from ..events import ladder

CONTROL_ID = "C1"


def taker_outcome_side(trade: dict) -> str:
    """Return the canonical direction, rejecting ambiguity rather than guessing."""
    side = trade.get("taker_outcome_side", trade.get("taker_side"))
    if side not in {"yes", "no"}:
        raise ValueError("trade has no valid taker_outcome_side")
    return side


def aggressor_direction(taker_side: str, settled_yes: bool) -> int:
    """+1 when the aggressor bought the side that ultimately settled YES."""
    if taker_side not in {"yes", "no"}:
        raise ValueError("trade has no valid taker_outcome_side")
    bought_yes = (taker_side == "yes")
    return 1 if bought_yes == settled_yes else -1


def informed_flow_score(trades: list[dict], p0: float, settled_yes: bool) -> float:
    """Size-weighted correctness, discounted by each trade's execution price.

    `p0` is retained only as a fallback for legacy/unit-test rows that lack a
    price. A single start-of-window quote cannot describe what the market knew
    two hours later, so live scores use `yes_price` per trade.
    """
    total = sum(float(t["count_fp"]) for t in trades)
    if total <= 0:
        return 0.0
    signed_surprise = 0.0
    for t in trades:
        price = float(t.get("yes_price", p0))
        surprise = 1.0 - (price if settled_yes else 1.0 - price)
        signed_surprise += (float(t["count_fp"])
                            * aggressor_direction(taker_outcome_side(t), settled_yes)
                            * surprise)
    return signed_surprise / total


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _trades_between(conn, ticker: str, start: datetime, end: datetime) -> list[dict]:
    cur = conn.execute(
        "SELECT count_fp, taker_outcome_side, yes_price FROM trades WHERE ticker = ?"
        " AND created_time >= ? AND created_time <= ?",
        (ticker, _iso(start), _iso(end)))
    return [{"count_fp": r[0], "taker_outcome_side": r[1], "yes_price": r[2]}
            for r in cur.fetchall()]


def _mid_at(conn, ticker: str, when: datetime) -> float | None:
    row = conn.execute(
        "SELECT yes_bid_close, yes_ask_close FROM candles WHERE ticker = ?"
        " AND end_period_ts <= ? AND yes_bid_close IS NOT NULL"
        " AND yes_ask_close IS NOT NULL ORDER BY end_period_ts DESC LIMIT 1",
        (ticker, int(when.timestamp()))).fetchone()
    if row:
        return (row[0] + row[1]) / 2.0
    last = conn.execute(
        "SELECT yes_price FROM trades WHERE ticker = ? AND created_time <= ?"
        " ORDER BY created_time DESC LIMIT 1",
        (ticker, _iso(when))).fetchone()
    return last[0] if last else None


def coverage(conn, params: dict) -> dict:
    """Why each market was or was not scored.

    C1's alert rate is only interpretable against the number of markets the
    control actually scores. Reporting it against any other denominator -- as an
    earlier ad-hoc calculation did -- misstates the false-positive rate.
    """
    p = params["c1_prerelease"]
    L = timedelta(minutes=p["window_minutes"])
    tally = {"considered": 0, "no_result": 0, "gate_blocked": 0,
             "low_volume": 0, "no_p0": 0, "null_too_small": 0, "scored": 0}

    for event_ticker, halt_str in conn.execute(
            "SELECT event_ticker, halt_time_utc FROM events"
            " WHERE halt_time_utc IS NOT NULL").fetchall():
        halt = _parse(halt_str)
        for m in ladder(conn, event_ticker):
            tk = m["ticker"]
            tally["considered"] += 1
            if m["result"] not in ("yes", "no"):
                tally["no_result"] += 1
                continue
            gate = conn.execute(
                "SELECT complete, tape_volume FROM ingest_log WHERE ticker = ?",
                (tk,)).fetchone()
            if not gate or not gate[0] or gate[1] == 0:
                tally["gate_blocked"] += 1
                continue
            window = _trades_between(conn, tk, halt - L, halt)
            if sum(float(t["count_fp"]) for t in window) < p["min_window_volume"]:
                tally["low_volume"] += 1
                continue
            if _mid_at(conn, tk, halt - L) is None:
                tally["no_p0"] += 1
                continue
            n = 0
            for i in range(1, p["null_windows"] + 1):
                end = halt - L * i
                if (_trades_between(conn, tk, end - L, end)
                        and _mid_at(conn, tk, end - L) is not None):
                    n += 1
            if n < 3:
                tally["null_too_small"] += 1
                continue
            tally["scored"] += 1
    return tally


def run(conn, params: dict) -> list[Alert]:
    p = params["c1_prerelease"]
    L = timedelta(minutes=p["window_minutes"])
    alerts: list[Alert] = []

    events = conn.execute(
        "SELECT event_ticker, halt_time_utc, release_time_utc FROM events"
        " WHERE halt_time_utc IS NOT NULL").fetchall()

    for event_ticker, halt_str, release_str in events:
        halt = _parse(halt_str)
        # How much warning does the halt actually give? KXCPI-26JUL halts at
        # 08:25 ET against an 08:30 ET BLS publication -- five minutes.
        gap = ((_parse(release_str) - halt).total_seconds() / 60.0
               if release_str else None)
        for m in ladder(conn, event_ticker):
            tk, result = m["ticker"], m["result"]
            if result not in ("yes", "no"):
                continue
            # Skip markets blocked by the completeness gate or beyond the
            # tape's retention horizon.
            gate = conn.execute(
                "SELECT complete, tape_volume FROM ingest_log WHERE ticker = ?",
                (tk,)).fetchone()
            if not gate or not gate[0] or gate[1] == 0:
                continue
            settled_yes = (result == "yes")

            window = _trades_between(conn, tk, halt - L, halt)
            volume = sum(float(t["count_fp"]) for t in window)
            if volume < p["min_window_volume"]:
                continue
            p0 = _mid_at(conn, tk, halt - L)
            if p0 is None:
                continue
            score = informed_flow_score(window, p0, settled_yes)

            # Null: same-length windows earlier in this market's own history.
            null = []
            for i in range(1, p["null_windows"] + 1):
                end = halt - L * i
                w = _trades_between(conn, tk, end - L, end)
                if not w:
                    continue
                q0 = _mid_at(conn, tk, end - L)
                if q0 is None:
                    continue
                null.append(informed_flow_score(w, q0, settled_yes))
            if len(null) < 3:
                continue

            pct = percentile_of(score, null)
            if pct >= p["percentile_threshold"]:
                alerts.append(Alert(
                    control_id=CONTROL_ID, target=tk,
                    window_start=_iso(halt - L), window_end=_iso(halt),
                    score=score, percentile=pct,
                    threshold=p["percentile_threshold"],
                    evidence={
                        "event": event_ticker, "settled": result,
                        "p0": p0, "window_volume": volume,
                        "surprise_price": "per-trade execution price",
                        "halt_to_release_minutes": gap,
                        "trade_count": len(window), "null_samples": len(null),
                        "limitation": "cannot distinguish superior public-"
                                      "information processing from misuse of "
                                      "non-public information; n=9 events",
                    }))
    return alerts
