"""Synthetic tape and candle builders.

Real labelled abuse is unavailable, so planted signatures are the only way to
demonstrate a control detects what it claims. Every control test uses these.
"""
from __future__ import annotations


def trade(tid, ticker, ts, size, yes_price, taker_side="yes", block=False):
    return {
        "trade_id": tid, "ticker": ticker, "created_time": ts,
        "count_fp": str(size), "yes_price_dollars": "{:.4f}".format(yes_price),
        "no_price_dollars": "{:.4f}".format(1 - yes_price),
        "taker_side": taker_side, "taker_book_side": "bid",
        "is_block_trade": block,
    }


def candle(ticker, ts, volume, oi, bid=None, ask=None):
    c = {"ticker": ticker, "end_period_ts": ts,
         "volume_fp": str(volume), "open_interest_fp": str(oi)}
    if bid is not None:
        c["yes_bid"] = {"close_dollars": "{:.4f}".format(bid)}
    if ask is not None:
        c["yes_ask"] = {"close_dollars": "{:.4f}".format(ask)}
    return c


def market(ticker, event, strike, status="finalized", result="no",
           close_time="2026-08-12T12:25:00Z", strike_type="greater"):
    return {"ticker": ticker, "event_ticker": event, "series_ticker": event.split("-")[0],
            "title": ticker, "status": status, "result": result,
            "close_time": close_time, "floor_strike": strike,
            "strike_type": strike_type}
