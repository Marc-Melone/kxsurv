import pytest
from kxsurv.api import KalshiPublic, RateLimiter


def test_rate_limiter_spaces_calls(monkeypatch):
    now = {"t": 0.0}
    slept = []
    monkeypatch.setattr("kxsurv.api.time.monotonic", lambda: now["t"])
    monkeypatch.setattr("kxsurv.api.time.sleep", lambda s: slept.append(s))
    rl = RateLimiter(rate_per_sec=10.0)
    rl.acquire()
    rl.acquire()
    assert slept and slept[0] == pytest.approx(0.1, abs=1e-6)


def test_paginates_until_cursor_empty(monkeypatch):
    pages = [
        {"trades": [{"trade_id": "a"}], "cursor": "c1"},
        {"trades": [{"trade_id": "b"}], "cursor": ""},
    ]
    calls = []

    def fake_get(self, path, params=None):
        calls.append(params or {})
        return pages[len(calls) - 1]

    monkeypatch.setattr(KalshiPublic, "_get", fake_get)
    out = KalshiPublic()._paginate("/markets/trades", "trades",
                                   {"limit": 1000, "ticker": "K1"})
    assert [t["trade_id"] for t in out] == ["a", "b"]
    assert calls[1]["cursor"] == "c1"


def test_retries_on_429_then_succeeds(monkeypatch):
    import kxsurv.api as api

    class Resp:
        def __init__(self, code, body=None):
            self.status_code = code
            self._b = body or {}
        def json(self): return self._b
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http error")

    seq = [Resp(429), Resp(200, {"series": {"ticker": "KXCPI"}})]
    monkeypatch.setattr(api.time, "sleep", lambda s: None)
    c = KalshiPublic()
    monkeypatch.setattr(c._session, "get", lambda *a, **k: seq.pop(0))
    assert c.series("KXCPI")["ticker"] == "KXCPI"


def test_client_never_sends_auth_headers():
    c = KalshiPublic()
    keys = {k.lower() for k in c._session.headers}
    assert "authorization" not in keys
    assert not any("key" in k for k in keys)


def test_pagination_fails_on_a_repeated_cursor(monkeypatch):
    """_paginate looped while a cursor was returned. An endpoint echoing the
    same cursor with a non-empty batch would spin forever accumulating
    duplicates."""
    def fake_get(self, path, params=None):
        return {"trades": [{"trade_id": "a"}], "cursor": "STUCK"}
    monkeypatch.setattr(KalshiPublic, "_get", fake_get)
    with pytest.raises(RuntimeError, match="cursor repeated"):
        KalshiPublic()._paginate("/markets/trades", "trades", {"limit": 1000})


def test_pagination_is_capped(monkeypatch):
    n = {"i": 0}
    def fake_get(self, path, params=None):
        n["i"] += 1
        return {"trades": [{"trade_id": str(n["i"])}], "cursor": "c{}".format(n["i"])}
    monkeypatch.setattr(KalshiPublic, "_get", fake_get)
    with pytest.raises(RuntimeError, match="exceeded 200 pages"):
        KalshiPublic()._paginate("/markets/trades", "trades", {"limit": 1000})


def test_empty_page_with_nonterminal_cursor_fails_closed(monkeypatch):
    monkeypatch.setattr(
        KalshiPublic, "_get",
        lambda *_args, **_kwargs: {"trades": [], "cursor": "MORE"},
    )
    with pytest.raises(RuntimeError, match="empty page"):
        KalshiPublic()._paginate("/markets/trades", "trades", {"limit": 1000})


def test_trades_merge_live_and_historical_tiers(monkeypatch):
    calls = []

    def fake_paginate(self, path, key, params, max_pages=200):
        calls.append((path, dict(params)))
        if path == "/historical/trades":
            return [{"trade_id": "old", "created_time": "2026-01-01T00:00:00Z"}]
        return [{"trade_id": "new", "created_time": "2026-02-01T00:00:00Z"}]

    monkeypatch.setattr(KalshiPublic, "_paginate", fake_paginate)
    out = KalshiPublic().trades(ticker="K1", min_ts=10, max_ts=20)
    assert [row["trade_id"] for row in out] == ["old", "new"]
    assert [path for path, _ in calls] == ["/markets/trades", "/historical/trades"]
    assert all(params["ticker"] == "K1" and params["min_ts"] == 10
               and params["max_ts"] == 20 for _, params in calls)


def test_markets_merge_live_and_historical_tiers(monkeypatch):
    calls = []

    def fake_paginate(self, path, key, params, max_pages=200):
        calls.append((path, dict(params)))
        if path == "/historical/markets":
            return [{"ticker": "OLD", "event_ticker": "E1", "result": "yes"}]
        return [{"ticker": "NEW", "event_ticker": "E2", "result": ""}]

    monkeypatch.setattr(KalshiPublic, "_paginate", fake_paginate)
    out = KalshiPublic().markets(series_ticker="KXQ")
    assert [row["ticker"] for row in out] == ["NEW", "OLD"]
    assert {row["ticker"]: row["_kxsurv_historical"] for row in out} == {
        "NEW": False, "OLD": True,
    }
    assert [path for path, _ in calls] == ["/markets", "/historical/markets"]
    assert all(params["series_ticker"] == "KXQ" for _, params in calls)


def test_market_tier_disagreement_fails_closed(monkeypatch):
    def fake_paginate(self, path, key, params, max_pages=200):
        result = "no" if path == "/historical/markets" else "yes"
        return [{"ticker": "K1", "event_ticker": "E", "result": result}]

    monkeypatch.setattr(KalshiPublic, "_paginate", fake_paginate)
    with pytest.raises(RuntimeError, match="disagree for market K1"):
        KalshiPublic().markets(series_ticker="KXQ")


def test_open_market_query_does_not_scan_historical_tier(monkeypatch):
    calls = []

    def fake_paginate(self, path, key, params, max_pages=200):
        calls.append(path)
        return []

    monkeypatch.setattr(KalshiPublic, "_paginate", fake_paginate)
    assert KalshiPublic().markets(series_ticker="KXQ", status="open") == []
    assert calls == ["/markets"]


def test_historical_candles_are_routed_and_normalized(monkeypatch):
    calls = []

    def fake_get(self, path, params=None):
        calls.append((path, params))
        return {"candlesticks": [{
            "end_period_ts": 123,
            "volume": "10.00",
            "open_interest": "20.00",
            "yes_bid": {"close": "0.40"},
            "yes_ask": {"close": "0.44"},
        }]}

    monkeypatch.setattr(KalshiPublic, "_get", fake_get)
    out = KalshiPublic().candlesticks(
        "KXQ", "KXQ-E-T1", 100, 200, historical=True)
    assert calls[0][0] == "/historical/markets/KXQ-E-T1/candlesticks"
    assert out[0]["volume_fp"] == "10.00"
    assert out[0]["open_interest_fp"] == "20.00"
    assert out[0]["yes_bid"]["close_dollars"] == "0.40"
    assert out[0]["yes_ask"]["close_dollars"] == "0.44"


def test_candle_missing_required_volume_fails_closed(monkeypatch):
    monkeypatch.setattr(
        KalshiPublic, "_get",
        lambda *_args, **_kwargs: {
            "candlesticks": [{"end_period_ts": 123, "open_interest_fp": "1"}]},
    )
    with pytest.raises(RuntimeError, match="volume_fp"):
        KalshiPublic().candlesticks("KXQ", "T", 100, 200)
