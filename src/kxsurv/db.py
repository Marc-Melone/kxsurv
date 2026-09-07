"""SQLite store. Raw tables are append-only and written only by the ingester."""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
  trade_id        TEXT PRIMARY KEY,
  ticker          TEXT NOT NULL,
  created_time    TEXT NOT NULL,
  count_fp        REAL NOT NULL,
  yes_price       REAL NOT NULL,
  no_price        REAL NOT NULL,
  taker_side      TEXT NOT NULL,
  taker_book_side TEXT,
  is_block_trade  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_trades_ticker_time ON trades(ticker, created_time);

CREATE TABLE IF NOT EXISTS candles (
  ticker           TEXT NOT NULL,
  end_period_ts    INTEGER NOT NULL,
  volume_fp        REAL NOT NULL,
  open_interest_fp REAL NOT NULL,
  yes_bid_close    REAL,
  yes_ask_close    REAL,
  PRIMARY KEY (ticker, end_period_ts)
);

CREATE TABLE IF NOT EXISTS markets (
  ticker        TEXT PRIMARY KEY,
  event_ticker  TEXT,
  series_ticker TEXT,
  title         TEXT,
  status        TEXT,
  result        TEXT,
  close_time    TEXT,
  floor_strike  REAL,
  strike_type   TEXT
);
CREATE INDEX IF NOT EXISTS idx_markets_event ON markets(event_ticker);

CREATE TABLE IF NOT EXISTS events (
  event_ticker     TEXT PRIMARY KEY,
  series_ticker    TEXT,
  release_time_utc TEXT,
  halt_time_utc    TEXT,
  outcome_ticker   TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
  alert_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  control_id   TEXT NOT NULL,
  target       TEXT NOT NULL,
  window_start TEXT,
  window_end   TEXT,
  score        REAL,
  percentile   REAL,
  threshold    REAL,
  evidence     TEXT,
  params_hash  TEXT NOT NULL,
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dispositions (
  disposition_id INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_id       INTEGER NOT NULL REFERENCES alerts(alert_id),
  action         TEXT NOT NULL,
  rationale      TEXT NOT NULL,
  created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS params (
  params_hash   TEXT PRIMARY KEY,
  registered_at TEXT NOT NULL,
  version       TEXT NOT NULL,
  content       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_log (
  ticker         TEXT PRIMARY KEY,
  tape_volume    REAL,
  candle_volume  REAL,
  divergence_pct REAL,
  complete       INTEGER,
  checked_at     TEXT
);

CREATE TABLE IF NOT EXISTS settlement_sources (
  series_ticker TEXT NOT NULL,
  source_name   TEXT NOT NULL,
  source_url    TEXT,
  category      TEXT,
  market_count  INTEGER,
  PRIMARY KEY (series_ticker, source_name)
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def upsert_trades(conn, rows: list[dict]) -> int:
    payload = [(
        r["trade_id"], r["ticker"], r["created_time"],
        _f(r.get("count_fp")), _f(r.get("yes_price_dollars")),
        _f(r.get("no_price_dollars")), r.get("taker_side", ""),
        r.get("taker_book_side"), 1 if r.get("is_block_trade") else 0,
    ) for r in rows]
    conn.executemany(
        "INSERT OR IGNORE INTO trades (trade_id, ticker, created_time, count_fp,"
        " yes_price, no_price, taker_side, taker_book_side, is_block_trade)"
        " VALUES (?,?,?,?,?,?,?,?,?)", payload)
    conn.commit()
    return len(payload)


def upsert_candles(conn, rows: list[dict]) -> int:
    payload = []
    for r in rows:
        bid = (r.get("yes_bid") or {}).get("close_dollars")
        ask = (r.get("yes_ask") or {}).get("close_dollars")
        payload.append((
            r["ticker"], int(r["end_period_ts"]),
            _f(r.get("volume_fp")), _f(r.get("open_interest_fp")),
            _f(bid, None) if bid is not None else None,
            _f(ask, None) if ask is not None else None,
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO candles (ticker, end_period_ts, volume_fp,"
        " open_interest_fp, yes_bid_close, yes_ask_close) VALUES (?,?,?,?,?,?)",
        payload)
    conn.commit()
    return len(payload)


def upsert_markets(conn, rows: list[dict]) -> int:
    payload = [(
        r["ticker"], r.get("event_ticker"), r.get("series_ticker"),
        r.get("title"), r.get("status"), r.get("result"), r.get("close_time"),
        _f(r.get("floor_strike"), None) if r.get("floor_strike") is not None else None,
        r.get("strike_type"),
    ) for r in rows]
    conn.executemany(
        "INSERT OR REPLACE INTO markets (ticker, event_ticker, series_ticker,"
        " title, status, result, close_time, floor_strike, strike_type)"
        " VALUES (?,?,?,?,?,?,?,?,?)", payload)
    conn.commit()
    return len(payload)
