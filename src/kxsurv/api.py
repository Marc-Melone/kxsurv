"""Kalshi public market-data client.

Unauthenticated endpoints only. This program holds no API key, sends no
authenticated request, and places no order. The client uses a conservative
10-request/second local cap and bounded backoff on 429/5xx responses.
"""
from __future__ import annotations

import json
import time

import requests

BASE = "https://external-api.kalshi.com/trade-api/v2"


class RateLimiter:
    def __init__(self, rate_per_sec: float = 10.0):
        self._min_interval = 1.0 / rate_per_sec
        self._last = None

    def acquire(self) -> None:
        now = time.monotonic()
        if self._last is not None:
            wait = self._min_interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
                now = now + wait
        self._last = now


class KalshiPublic:
    def __init__(self, rate_per_sec: float = 10.0, max_attempts: int = 4):
        self._session = requests.Session()
        self._rl = RateLimiter(rate_per_sec)
        self._max_attempts = max_attempts

    def _get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(self._max_attempts):
            self._rl.acquire()
            r = self._session.get(BASE + path, params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(1.0 * (2 ** attempt))   # bounded exponential backoff
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("Kalshi unavailable after {} attempts: {}".format(
            self._max_attempts, path))

    def _paginate(self, path: str, key: str, params: dict,
                  max_pages: int = 200) -> list[dict]:
        """Follow cursors to exhaustion and fail closed on non-termination.

        An endpoint echoing the same cursor alongside a non-empty batch would
        otherwise spin forever, and an endpoint issuing endlessly fresh cursors
        would never return. Either condition means completeness is unknown, so
        returning the accumulated prefix would be unsafe for surveillance.
        """
        out: list[dict] = []
        cursor = ""
        seen: set[str] = set()
        for _ in range(max_pages):
            p = dict(params)
            if cursor:
                p["cursor"] = cursor
            d = self._get(path, p)
            batch = d.get(key, []) or []
            out.extend(batch)
            cursor = d.get("cursor", "") or ""
            if not cursor:
                return out
            if not batch:
                raise RuntimeError(
                    "pagination returned an empty page with a non-terminal cursor: {}"
                    .format(path))
            if cursor in seen:
                raise RuntimeError("pagination cursor repeated before exhaustion: {}"
                                   .format(path))
            seen.add(cursor)
        raise RuntimeError(
            "pagination exceeded {} pages before exhaustion: {}".format(max_pages, path))

    def series(self, ticker: str) -> dict:
        return self._get("/series/" + ticker).get("series", {})

    def market(self, ticker: str) -> dict:
        return self._get("/markets/" + ticker).get("market", {})

    def markets(self, **filters) -> list[dict]:
        params = {"limit": 200}
        params.update({k: v for k, v in filters.items() if v is not None})
        return self._paginate("/markets", "markets", params)

    def trades(self, ticker: str | None = None, limit: int = 1000,
               min_ts: int | None = None, max_ts: int | None = None) -> list[dict]:
        """Return the union of live- and historical-tier public trades.

        Kalshi partitions trades at a moving cutoff. Querying only the live
        endpoint silently truncates older windows, so both unauthenticated
        endpoints are queried and merged by immutable trade ID.
        """
        params: dict = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if min_ts is not None:
            params["min_ts"] = int(min_ts)
        if max_ts is not None:
            params["max_ts"] = int(max_ts)
        live = self._paginate("/markets/trades", "trades", params)
        historical = self._paginate("/historical/trades", "trades", params)

        by_id: dict[str, dict] = {}
        for row in historical + live:
            trade_id = row.get("trade_id")
            if not isinstance(trade_id, str) or not trade_id:
                raise RuntimeError("trade response omitted a non-empty trade_id")
            prior = by_id.get(trade_id)
            if prior is not None and json.dumps(prior, sort_keys=True) != json.dumps(
                    row, sort_keys=True):
                raise RuntimeError(
                    "live and historical endpoints disagree for trade {}".format(trade_id))
            by_id[trade_id] = row
        return sorted(by_id.values(), key=lambda row: (
            str(row.get("created_time", "")), row["trade_id"]))

    def candlesticks(self, series: str, ticker: str, start_ts: int,
                     end_ts: int, period_interval: int = 60) -> list[dict]:
        d = self._get(
            "/series/{}/markets/{}/candlesticks".format(series, ticker),
            {"start_ts": start_ts, "end_ts": end_ts,
             "period_interval": period_interval})
        return d.get("candlesticks", []) or []
