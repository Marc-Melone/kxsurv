"""C5 - settlement-source integrity. CFTC DCM Core Principle 4.

Core Principle 4 covers disruption of the settlement process, and Kalshi
markets resolve against external reference data. GET /series/{ticker} exposes
settlement_sources as [{name, url}] -- e.g. KXCPI resolves against the Bureau
of Labor Statistics.

Part 1 is an inventory: which series resolve against which provider, and how
concentrated that is. An outage or methodology change at one provider is a
CORRELATED settlement event across every market it resolves.

Part 2 is divergence monitoring where an independent corroborating source
exists. Alerts here are operational settlement-risk events, not participant-
conduct alerts, and route to a separate disposition track.
"""
from __future__ import annotations

from . import Alert

CONTROL_ID = "C5"


def build_inventory(conn, api, series_tickers: list[str]) -> int:
    n = 0
    for st in series_tickers:
        s = api.series(st)
        category = s.get("category")
        count = conn.execute(
            "SELECT COUNT(*) FROM markets WHERE series_ticker = ?", (st,)
        ).fetchone()[0]
        for src in (s.get("settlement_sources") or []):
            conn.execute(
                "INSERT OR REPLACE INTO settlement_sources (series_ticker,"
                " source_name, source_url, category, market_count)"
                " VALUES (?,?,?,?,?)",
                (st, src.get("name", "unknown"), src.get("url"), category, count))
            n += 1
    conn.commit()
    return n


def concentration(conn) -> list[dict]:
    """Series and market counts per settlement source, most concentrated first."""
    cur = conn.execute(
        "SELECT source_name, COUNT(DISTINCT series_ticker) AS series_count,"
        " COALESCE(SUM(market_count), 0) AS market_count"
        " FROM settlement_sources GROUP BY source_name"
        " ORDER BY series_count DESC, market_count DESC")
    return [{"source_name": r[0], "series_count": r[1], "market_count": r[2]}
            for r in cur.fetchall()]


def run(conn, params: dict) -> list[Alert]:
    """Flag series that declare no settlement source at all.

    A market with no declared resolution source is a settlement-risk item on
    its face, and it is the one divergence check available without an
    independent corroborating feed.
    """
    alerts: list[Alert] = []
    rows = conn.execute(
        "SELECT DISTINCT m.series_ticker FROM markets m"
        " WHERE m.series_ticker IS NOT NULL AND m.series_ticker NOT IN"
        " (SELECT series_ticker FROM settlement_sources)").fetchall()
    for (st,) in rows:
        count = conn.execute(
            "SELECT COUNT(*) FROM markets WHERE series_ticker = ?", (st,)
        ).fetchone()[0]
        alerts.append(Alert(
            control_id=CONTROL_ID, target=st,
            window_start=None, window_end=None,
            score=float(count), percentile=None, threshold=None,
            evidence={"issue": "no declared settlement source",
                      "affected_markets": count,
                      "track": "operational settlement risk, not participant conduct"}))
    return alerts
