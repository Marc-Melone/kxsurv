"""Kalshi public market-data client.

Unauthenticated endpoints only. This program holds no API key, sends no
authenticated request, and places no order. Rate limits follow Kalshi's
published Basic tier (200 read tokens/sec, 10 tokens per request => 20 req/s);
we cap at 10 req/s for headroom and back off on 429/5xx.
"""
from __future__ import annotations

import time

import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"


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
        """Follow cursors to exhaustion, with two termination guards.

        An endpoint echoing the same cursor alongside a non-empty batch would
        otherwise spin forever accumulating duplicates, and an endpoint issuing
        endlessly fresh cursors would never return.
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
            if not cursor or not batch or cursor in seen:
                return out
            seen.add(cursor)
        return out

    def series(self, ticker: str) -> dict:
        return self._get("/series/" + ticker).get("series", {})

    def market(self, ticker: str) -> dict:
        return self._get("/markets/" + ticker).get("market", {})

    def markets(self, **filters) -> list[dict]:
        params = {"limit": 200}
        params.update({k: v for k, v in filters.items() if v is not None})
        return self._paginate("/markets", "markets", params)

    def trades(self, ticker: str | None = None, limit: int = 1000) -> list[dict]:
        params: dict = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        return self._paginate("/markets/trades", "trades", params)

    def candlesticks(self, series: str, ticker: str, start_ts: int,
                     end_ts: int, period_interval: int = 60) -> list[dict]:
        d = self._get(
            "/series/{}/markets/{}/candlesticks".format(series, ticker),
            {"start_ts": start_ts, "end_ts": end_ts,
             "period_interval": period_interval})
        return d.get("candlesticks", []) or []
