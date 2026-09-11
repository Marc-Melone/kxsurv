"""Ingestion. The only module that writes raw tables."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .db import upsert_candles, upsert_markets, upsert_trades


def _to_unix(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def check_completeness(conn, ticker: str, tolerance_pct: float = 2.0):
    """Cross-validate the trade tape against the independent candle endpoint.

    A market whose tape does not reconcile WITHIN THE WINDOW THE TAPE COVERS is
    blocked from scoring: conclusions drawn on a truncated tape are worthless.

    The saved 2026-09-07 snapshot was collected from the live trade endpoint
    only: its first retrieved trade was about 66 days old while candlesticks
    reached about 89 days. Comparing those unlike acquisition windows produced
    spurious failures on 261 of 408 markets. Current ingestion uses both
    Kalshi market/candlestick storage tiers and both public trade tiers.
    Reconciliation is still measured only from the first retrieved trade
    forward so a never-traded prefix is not mistaken for missing data.

    A market with candle volume but no tape at all sits beyond the horizon.
    That is a coverage fact, not a truncation failure: C3 reads candles and can
    still score it, while C1 and C2 cannot and skip it.
    """
    first = conn.execute(
        "SELECT MIN(created_time) FROM trades WHERE ticker = ?",
        (ticker,)).fetchone()[0]

    if first is None:
        # No retrieved trades in the acquisition window, or genuinely never traded.
        cand_all = conn.execute(
            "SELECT COALESCE(SUM(volume_fp), 0) FROM candles WHERE ticker = ?",
            (ticker,)).fetchone()[0]
        conn.execute(
            "INSERT OR REPLACE INTO ingest_log (ticker, tape_volume,"
            " candle_volume, divergence_pct, complete, checked_at)"
            " VALUES (?,?,?,?,?,?)",
            (ticker, 0.0, cand_all, 0.0, 1,
             datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return True, 0.0

    tape = conn.execute(
        "SELECT COALESCE(SUM(count_fp), 0) FROM trades WHERE ticker = ?",
        (ticker,)).fetchone()[0]
    cand = conn.execute(
        "SELECT COALESCE(SUM(volume_fp), 0) FROM candles"
        " WHERE ticker = ? AND end_period_ts >= ?",
        (ticker, _to_unix(first))).fetchone()[0]
    div = abs(tape - cand) / cand * 100.0 if cand else (0.0 if not tape else 100.0)
    ok = div <= tolerance_pct
    conn.execute(
        "INSERT OR REPLACE INTO ingest_log (ticker, tape_volume, candle_volume,"
        " divergence_pct, complete, checked_at) VALUES (?,?,?,?,?,?)",
        (ticker, tape, cand, div, 1 if ok else 0,
         datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return ok, round(div, 4)


def ingest_series(conn, api, series_ticker: str, days: int = 90) -> dict:
    """Ingest one series into an already reset bounded snapshot.

    ``api.markets`` returns both Kalshi storage tiers.  The list endpoints do
    not share a close-time filter, so enforce the requested acquisition window
    locally before making one tape/candle request per market.
    """
    end_ts = int(time.time())
    start_ts = end_ts - days * 86400
    candidates = api.markets(series_ticker=series_ticker)
    mkts = []
    for market in candidates:
        close_time = market.get("close_time")
        if not isinstance(close_time, str) or not close_time:
            raise ValueError(
                "market {} has no valid close_time".format(
                    market.get("ticker", "<unknown>")))
        if _to_unix(close_time) >= start_ts:
            mkts.append(market)
    upsert_markets(conn, [dict(m, series_ticker=series_ticker) for m in mkts])

    n_tr = n_cd = 0
    complete = 0
    for m in mkts:
        tk = m["ticker"]
        tr = api.trades(ticker=tk, min_ts=start_ts, max_ts=end_ts)
        n_tr += upsert_trades(conn, [dict(t, ticker=tk) for t in tr])
        cd = api.candlesticks(
            series_ticker, tk, start_ts, end_ts, 60,
            historical=bool(m.get("_kxsurv_historical")))
        n_cd += upsert_candles(conn, [dict(c, ticker=tk) for c in cd])
        ok, _ = check_completeness(conn, tk)
        complete += 1 if ok else 0

    return {"series": series_ticker, "markets": len(mkts), "trades": n_tr,
            "candles": n_cd, "complete_markets": complete}
