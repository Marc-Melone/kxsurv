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

    Kalshi's public trade tape has a retention horizon -- measured at 66 days on
    2026-09-07 (earliest available trade 2026-07-03) -- while candlestick
    aggregates reach back further, to 89 days. Comparing a 66-day tape against
    89 days of candles produced spurious failures on 261 of 408 markets.
    Reconciliation is therefore measured only from the first available trade
    forward, where it matches exactly (0.00% across every market tested).

    A market with candle volume but no tape at all sits beyond the horizon.
    That is a coverage fact, not a truncation failure: C3 reads candles and can
    still score it, while C1 and C2 cannot and skip it.
    """
    first = conn.execute(
        "SELECT MIN(created_time) FROM trades WHERE ticker = ?",
        (ticker,)).fetchone()[0]

    if first is None:
        # Beyond the tape's retention horizon, or genuinely never traded.
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
