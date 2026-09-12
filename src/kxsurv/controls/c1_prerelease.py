"""C1 - pre-release informed trading. CFTC DCM Core Principle 12.

Kalshi halts economic-release markets before the print (KXCPI-26JUL close_time
12:25:00Z == 08:25 ET, five minutes ahead of the BLS 08:30 ET publication).
C1 asks whether that window is adequate, not whether it exists.

The naive metric -- "did pre-release flow predict the outcome" -- is wrong: a
trade at $0.99 on the eventual winner is consensus, not information. The
informed signature is aggressive flow toward the eventual outcome FROM AN
EXECUTION PRICE THAT DID NOT ALREADY IMPLY IT, hence the surprise weighting.

SAMPLE SIZE: 5 distinct scheduled release timestamps represented by 9 settled
event ladders across the five economic series (132 settled markets, but brackets
within a ladder and ladders sharing a publication are not independent). C1 makes
NO population-level statistical claim. It is validated by fixture detection
behaviour and analyst triage.

COVERAGE: C1 requires retrieved trades in its test and comparison windows.
Current ingestion combines Kalshi's live and historical public trade tiers;
the saved 2026-09-07 snapshot used only the live tier and therefore has narrower
C1 coverage than a newly acquired two-tier snapshot may have.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import Alert, percentile_of
from ..events import ladder
from ..validation import timestamp_us

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


def informed_flow_score(trades: list[dict], p0: float | None,
                        settled_yes: bool) -> float:
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
        raw_price = t.get("yes_price")
        if raw_price is None:
            if p0 is None:
                raise ValueError("trade has no execution price or legacy fallback price")
            raw_price = p0
        price = float(raw_price)
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
    """Return trades in the half-open interval ``[start, end)``.

    Adjacent current/null windows share boundaries. A closed interval on both
    ends would count the same boundary trade twice and leak it between the test
    window and its comparison population.
    """
    cur = conn.execute(
        "SELECT count_fp, taker_outcome_side, yes_price FROM trades WHERE ticker = ?"
        " AND created_time_us >= ? AND created_time_us < ?"
        " ORDER BY created_time_us, trade_id",
        (ticker, timestamp_us(start), timestamp_us(end)))
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
        "SELECT yes_price FROM trades WHERE ticker = ? AND created_time_us <= ?"
        " ORDER BY created_time_us DESC, trade_id DESC LIMIT 1",
        (ticker, timestamp_us(when))).fetchone()
    return last[0] if last else None


def coverage(conn, params: dict) -> dict:
    """Why each market was or was not scored.

    C1's alert rate is only interpretable against the number of markets the
    control actually scores. Reporting it against any other denominator -- as an
    earlier ad-hoc calculation did -- misstates the false-positive rate.
    """
    p = params["c1_prerelease"]
    L = timedelta(minutes=p["window_minutes"])
    tally = {"considered": 0, "release_time_unknown": 0,
             "no_result": 0, "gate_blocked": 0,
             "low_volume": 0, "null_too_small": 0, "scored": 0}

    for event_ticker, halt_str, release_str in conn.execute(
            "SELECT event_ticker, halt_time_utc, release_time_utc FROM events"
            " WHERE halt_time_utc IS NOT NULL").fetchall():
        halt = _parse(halt_str)
        for m in ladder(conn, event_ticker):
            tk = m["ticker"]
            tally["considered"] += 1
            # C1 is a pre-publication screen. A close time alone does not prove
            # that an event has a scheduled information release; weather and
            # other continuously resolving markets therefore stay out of scope.
            if release_str is None:
                tally["release_time_unknown"] += 1
                continue
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
            n = 0
            for i in range(1, p["null_windows"] + 1):
                end = halt - L * i
                if _trades_between(conn, tk, end - L, end):
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
        " WHERE halt_time_utc IS NOT NULL AND release_time_utc IS NOT NULL").fetchall()
    # The effective sample unit is the scheduled publication, not the market or
    # event ticker. CPI/CPIYOY and payroll/U3 ladders share releases and are not
    # independent observations. Count only release times represented by at least
    # one settled ladder, since unsettled future events cannot enter C1 scoring.
    scheduled_release_population, settled_ladder_population = conn.execute(
        "SELECT COUNT(DISTINCT e.release_time_utc), COUNT(DISTINCT e.event_ticker)"
        " FROM events e WHERE e.halt_time_utc IS NOT NULL"
        " AND e.release_time_utc IS NOT NULL AND EXISTS ("
        " SELECT 1 FROM markets m WHERE m.event_ticker = e.event_ticker"
        " AND m.floor_strike IS NOT NULL AND m.result IN ('yes', 'no'))"
    ).fetchone()

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
            # available acquisition window.
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
            # Opening midpoint is retained as optional analyst context only.
            # It is not an input to the corrected per-execution-price score and
            # therefore cannot be a hidden eligibility gate.
            p0 = _mid_at(conn, tk, halt - L)
            score = informed_flow_score(window, p0, settled_yes)

            # Null: same-length windows earlier in this market's own history.
            null = []
            for i in range(1, p["null_windows"] + 1):
                end = halt - L * i
                w = _trades_between(conn, tk, end - L, end)
                if not w:
                    continue
                null.append(informed_flow_score(w, None, settled_yes))
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
                        "scheduled_release_population": scheduled_release_population,
                        "settled_ladder_population": settled_ladder_population,
                        "limitation": "cannot distinguish superior public-"
                                      "information processing from misuse of "
                                      "non-public information; candidate rates "
                                      "are descriptive, not calibrated false-"
                                      "positive rates",
                    }))
    return alerts
