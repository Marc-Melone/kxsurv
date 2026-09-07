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
    out = KalshiPublic().trades(ticker="K1")
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


def test_pagination_stops_on_a_repeated_cursor(monkeypatch):
    """_paginate looped while a cursor was returned. An endpoint echoing the
    same cursor with a non-empty batch would spin forever accumulating
    duplicates."""
    def fake_get(self, path, params=None):
        return {"trades": [{"trade_id": "a"}], "cursor": "STUCK"}
    monkeypatch.setattr(KalshiPublic, "_get", fake_get)
    out = KalshiPublic().trades(ticker="K1")
    assert len(out) < 50, "a repeated cursor must terminate the loop"


def test_pagination_is_capped(monkeypatch):
    n = {"i": 0}
    def fake_get(self, path, params=None):
        n["i"] += 1
        return {"trades": [{"trade_id": str(n["i"])}], "cursor": "c{}".format(n["i"])}
    monkeypatch.setattr(KalshiPublic, "_get", fake_get)
    out = KalshiPublic().trades(ticker="K1")
    assert len(out) <= 1000, "unbounded pagination must be capped"
