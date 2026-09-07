"""Ingestion. The only module that writes raw tables."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .db import upsert_candles, upsert_markets, upsert_trades


def check_completeness(conn, ticker: str, tolerance_pct: float = 2.0):
    """Cross-validate the trade tape against the independent candle endpoint.

    A market whose tape does not reconcile is blocked from scoring: surveillance
    conclusions drawn on a truncated tape are worthless.
    """
    tape = conn.execute(
        "SELECT COALESCE(SUM(count_fp), 0) FROM trades WHERE ticker = ?",
        (ticker,)).fetchone()[0]
    cand = conn.execute(
        "SELECT COALESCE(SUM(volume_fp), 0) FROM candles WHERE ticker = ?",
        (ticker,)).fetchone()[0]
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
    """Ingest every market in a series plus its tape and candles."""
    mkts = api.markets(series_ticker=series_ticker)
    upsert_markets(conn, [dict(m, series_ticker=series_ticker) for m in mkts])

    end_ts = int(time.time())
    start_ts = end_ts - days * 86400
    n_tr = n_cd = 0
    complete = 0
    for m in mkts:
        tk = m["ticker"]
        tr = api.trades(ticker=tk)
        n_tr += upsert_trades(conn, [dict(t, ticker=tk) for t in tr])
        cd = api.candlesticks(series_ticker, tk, start_ts, end_ts, 60)
        n_cd += upsert_candles(conn, [dict(c, ticker=tk) for c in cd])
        ok, _ = check_completeness(conn, tk)
        complete += 1 if ok else 0

    return {"series": series_ticker, "markets": len(mkts), "trades": n_tr,
            "candles": n_cd, "complete_markets": complete}
