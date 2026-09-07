"""Release calendar and outcome labelling for threshold ladders."""
from __future__ import annotations

# (hour, minute) in US Eastern, the statutory publication time of the source.
# BLS releases CPI, payrolls and unemployment at 08:30 ET; the FOMC statement
# lands at 14:00 ET.
RELEASE_TIMES: dict[str, tuple[int, int]] = {
    "KXCPI": (8, 30),
    "KXCPIYOY": (8, 30),
    "KXPAYROLLS": (8, 30),
    "KXU3": (8, 30),
    "KXFED": (14, 0),
}


def build_events(conn) -> int:
    """Materialise one row per event from the markets table."""
    rows = conn.execute(
        "SELECT event_ticker, series_ticker, MIN(close_time)"
        " FROM markets WHERE event_ticker IS NOT NULL"
        " GROUP BY event_ticker, series_ticker").fetchall()
    n = 0
    for event_ticker, series_ticker, halt in rows:
        conn.execute(
            "INSERT OR REPLACE INTO events (event_ticker, series_ticker,"
            " release_time_utc, halt_time_utc, outcome_ticker)"
            " VALUES (?,?,?,?,?)",
            (event_ticker, series_ticker, None, halt,
             event_outcome(conn, event_ticker)))
        n += 1
    conn.commit()
    return n


def ladder(conn, event_ticker: str) -> list[dict]:
    """Strikes of an event, ascending. Only rows carrying a strike."""
    cur = conn.execute(
        "SELECT ticker, floor_strike, strike_type, result, status, close_time"
        " FROM markets WHERE event_ticker = ? AND floor_strike IS NOT NULL"
        " ORDER BY floor_strike ASC", (event_ticker,))
    return [{"ticker": r[0], "floor_strike": r[1], "strike_type": r[2],
             "result": r[3], "status": r[4], "close_time": r[5]}
            for r in cur.fetchall()]


def event_outcome(conn, event_ticker: str) -> str | None:
    """For a 'greater' ladder the realised value sits just above the highest
    strike that settled YES, so that market identifies the outcome."""
    rows = [m for m in ladder(conn, event_ticker) if m["result"] == "yes"]
    return rows[-1]["ticker"] if rows else None
