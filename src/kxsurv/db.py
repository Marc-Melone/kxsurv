"""SQLite store and schema migrations for the surveillance data set."""
from __future__ import annotations

import json
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
  taker_outcome_side TEXT NOT NULL CHECK (taker_outcome_side IN ('yes', 'no')),
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

CREATE TABLE IF NOT EXISTS control_runs (
  run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  params_hash  TEXT NOT NULL REFERENCES params(params_hash),
  input_hash   TEXT NOT NULL,
  code_hash    TEXT NOT NULL,
  expected_controls TEXT NOT NULL,
  status       TEXT NOT NULL,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  failure      TEXT
);
CREATE INDEX IF NOT EXISTS idx_control_runs_finished
  ON control_runs(status, run_id DESC);

CREATE TABLE IF NOT EXISTS control_executions (
  run_id       INTEGER NOT NULL REFERENCES control_runs(run_id),
  control_id   TEXT NOT NULL,
  status       TEXT NOT NULL,
  alert_count  INTEGER,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  failure      TEXT,
  PRIMARY KEY (run_id, control_id)
);
CREATE INDEX IF NOT EXISTS idx_control_executions_run
  ON control_executions(run_id, status);

CREATE TABLE IF NOT EXISTS alerts (
  alert_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id       INTEGER REFERENCES control_runs(run_id),
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
CREATE INDEX IF NOT EXISTS idx_dispositions_alert_id
  ON dispositions(alert_id, disposition_id DESC);

CREATE TABLE IF NOT EXISTS params (
  params_hash   TEXT PRIMARY KEY,
  registered_at TEXT NOT NULL,
  version       TEXT NOT NULL UNIQUE,
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

CREATE TABLE IF NOT EXISTS snapshot_state (
  state_id       INTEGER PRIMARY KEY CHECK (state_id = 1),
  status         TEXT NOT NULL CHECK (status IN ('ready', 'refreshing', 'failed', 'legacy_ready')),
  refresh_token  TEXT,
  generation     INTEGER NOT NULL DEFAULT 0,
  started_at     TEXT,
  completed_at   TEXT,
  failure        TEXT
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
    _migrate_schema(conn)
    conn.commit()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info({})".format(table))}


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Bring an existing local analysis database forward without losing history."""
    if "taker_outcome_side" not in _columns(conn, "trades"):
        conn.execute("ALTER TABLE trades ADD COLUMN taker_outcome_side TEXT")
        conn.execute(
            "UPDATE trades SET taker_outcome_side = taker_side"
            " WHERE taker_outcome_side IS NULL")
    invalid_sides = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE taker_outcome_side IS NULL"
        " OR taker_outcome_side NOT IN ('yes', 'no')"
    ).fetchone()[0]
    if invalid_sides:
        raise RuntimeError(
            "{} stored trade(s) have no valid taker_outcome_side; repair or "
            "remove those records before running controls".format(invalid_sides))

    # A fresh database has a CHECK constraint.  SQLite cannot add that
    # constraint in place to a legacy table, so use triggers there as well.
    conn.execute("DROP TRIGGER IF EXISTS trades_require_valid_outcome_side_insert")
    conn.execute("DROP TRIGGER IF EXISTS trades_require_valid_outcome_side_update")
    conn.execute(
        "CREATE TRIGGER trades_require_valid_outcome_side_insert "
        "BEFORE INSERT ON trades "
        "WHEN NEW.taker_outcome_side IS NULL "
        " OR NEW.taker_outcome_side NOT IN ('yes', 'no') "
        "BEGIN SELECT RAISE(ABORT, 'trade requires valid taker_outcome_side'); END")
    conn.execute(
        "CREATE TRIGGER trades_require_valid_outcome_side_update "
        "BEFORE UPDATE OF taker_outcome_side ON trades "
        "WHEN NEW.taker_outcome_side IS NULL "
        " OR NEW.taker_outcome_side NOT IN ('yes', 'no') "
        "BEGIN SELECT RAISE(ABORT, 'trade requires valid taker_outcome_side'); END")

    if "run_id" not in _columns(conn, "alerts"):
        conn.execute("ALTER TABLE alerts ADD COLUMN run_id INTEGER")

    # SQLite cannot alter an index in place.  Build this only after `run_id`
    # exists, so even a partially constructed legacy database can migrate.
    # Alert identity is scoped to a run rather than silently retaining stale
    # prior-run evidence. COALESCE keeps NULL windows (C4/C5) from defeating
    # the constraint.
    conn.execute("DROP INDEX IF EXISTS idx_alerts_natural")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_natural ON alerts("
        " COALESCE(run_id, 0), control_id, target, COALESCE(window_start,''),"
        " COALESCE(window_end,''), params_hash)")

    # Dispositions are an audit trail, so several revisions are allowed. Funnel
    # reporting selects the latest one per alert rather than counting history.
    conn.execute("DROP INDEX IF EXISTS idx_dispositions_one_per_alert")

    run_columns = _columns(conn, "control_runs")
    if "code_hash" not in run_columns:
        conn.execute("ALTER TABLE control_runs ADD COLUMN code_hash TEXT")
        conn.execute(
            "UPDATE control_runs SET code_hash = 'legacy-code-unavailable'"
            " WHERE code_hash IS NULL")
    if "failure" not in run_columns:
        conn.execute("ALTER TABLE control_runs ADD COLUMN failure TEXT")
    if "expected_controls" not in run_columns:
        # Preserve old runs without inventing controls they did not record. New
        # runs always persist a non-empty manifest in begin_run().
        conn.execute("ALTER TABLE control_runs ADD COLUMN expected_controls TEXT")
        for (run_id,) in conn.execute("SELECT run_id FROM control_runs").fetchall():
            controls = [row[0] for row in conn.execute(
                "SELECT control_id FROM control_executions WHERE run_id = ?"
                " ORDER BY control_id", (run_id,)).fetchall()]
            conn.execute(
                "UPDATE control_runs SET expected_controls = ? WHERE run_id = ?",
                (json.dumps(controls, separators=(",", ":")), run_id),
            )

    duplicate_versions = conn.execute(
        "SELECT version FROM params GROUP BY version HAVING COUNT(DISTINCT params_hash) > 1"
    ).fetchall()
    if duplicate_versions:
        raise RuntimeError(
            "legacy parameter history has more than one hash for version(s): {}. "
            "Resolve those records explicitly before running controls.".format(
                ", ".join(r[0] for r in duplicate_versions)))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_params_version_unique ON params(version)")

    # Registration history is evidence. A corrected parameter set is a new row
    # with a new version, never an edit or deletion of the old record.
    conn.execute("DROP TRIGGER IF EXISTS params_are_immutable_update")
    conn.execute("DROP TRIGGER IF EXISTS params_are_immutable_delete")
    conn.execute(
        "CREATE TRIGGER params_are_immutable_update BEFORE UPDATE ON params "
        "BEGIN SELECT RAISE(ABORT, 'registered parameters are immutable'); END")
    conn.execute(
        "CREATE TRIGGER params_are_immutable_delete BEFORE DELETE ON params "
        "BEGIN SELECT RAISE(ABORT, 'registered parameters are immutable'); END")

    # Disposition revisions are appended and reporting selects the latest row.
    # Editing history in place would defeat that audit trail.
    conn.execute("DROP TRIGGER IF EXISTS dispositions_require_valid_insert")
    conn.execute("DROP TRIGGER IF EXISTS dispositions_are_immutable_update")
    conn.execute("DROP TRIGGER IF EXISTS dispositions_are_immutable_delete")
    conn.execute(
        "CREATE TRIGGER dispositions_require_valid_insert "
        "BEFORE INSERT ON dispositions WHEN NEW.action NOT IN "
        "('no_action', 'monitor', 'escalated') OR NEW.rationale IS NULL "
        "OR trim(NEW.rationale) = '' "
        "BEGIN SELECT RAISE(ABORT, 'disposition requires a valid action and rationale'); END")
    conn.execute(
        "CREATE TRIGGER dispositions_are_immutable_update BEFORE UPDATE ON dispositions "
        "BEGIN SELECT RAISE(ABORT, 'disposition history is immutable'); END")
    conn.execute(
        "CREATE TRIGGER dispositions_are_immutable_delete BEFORE DELETE ON dispositions "
        "BEGIN SELECT RAISE(ABORT, 'disposition history is immutable'); END")

    state_columns = _columns(conn, "snapshot_state")
    if "refresh_token" not in state_columns:
        conn.execute("ALTER TABLE snapshot_state ADD COLUMN refresh_token TEXT")
    if "generation" not in state_columns:
        conn.execute(
            "ALTER TABLE snapshot_state ADD COLUMN generation INTEGER NOT NULL DEFAULT 0")

    # Databases created before the refresh lifecycle did not record whether a
    # saved data set was complete.  Seed a visibly legacy-ready marker only
    # when its structural prerequisites are present; future CLI refreshes use
    # the stronger ready/refreshing/failed lifecycle below.
    state = conn.execute("SELECT status FROM snapshot_state WHERE state_id = 1").fetchone()
    if state is None:
        required = ("markets", "events", "candles", "ingest_log")
        populated = all(
            conn.execute("SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]
            for table in required)
        unlogged = conn.execute(
            "SELECT COUNT(*) FROM markets m LEFT JOIN ingest_log i USING(ticker)"
            " WHERE i.ticker IS NULL"
        ).fetchone()[0]
        if populated and not unlogged:
            conn.execute(
                "INSERT INTO snapshot_state (state_id, status, completed_at)"
                " VALUES (1, 'legacy_ready', datetime('now'))")

    # ALTER TABLE cannot add the foreign key for an existing alerts table. These
    # triggers keep migrated databases as strict as a fresh schema.
    conn.execute("DROP TRIGGER IF EXISTS alerts_require_active_matching_run")
    conn.execute("DROP TRIGGER IF EXISTS alerts_are_immutable")
    conn.execute("DROP TRIGGER IF EXISTS alerts_are_undeletable")
    conn.execute(
        "CREATE TRIGGER alerts_require_active_matching_run BEFORE INSERT ON alerts "
        "WHEN NEW.run_id IS NULL OR NOT EXISTS ("
        " SELECT 1 FROM control_runs WHERE run_id = NEW.run_id"
        " AND params_hash = NEW.params_hash AND status = 'running') "
        "BEGIN SELECT RAISE(ABORT, 'alert requires a matching running control run'); END")
    # Migration binds historical NULL-run alerts below.  Once bound, an alert is
    # immutable: a correction is a new run, and triage is an append-only
    # disposition record.  This closes the same gap for raw SQL as for the
    # application-level save path.
    conn.execute(
        "CREATE TRIGGER alerts_are_immutable BEFORE UPDATE ON alerts "
        "WHEN OLD.run_id IS NOT NULL "
        "BEGIN SELECT RAISE(ABORT, 'alerts are immutable once assigned to a run'); END")
    conn.execute(
        "CREATE TRIGGER alerts_are_undeletable BEFORE DELETE ON alerts "
        "WHEN OLD.run_id IS NOT NULL "
        "BEGIN SELECT RAISE(ABORT, 'alerts are immutable once assigned to a run'); END")

    # A zero-alert control is still an executed control.  The run record must
    # distinguish it from a control that was never reached or failed.
    conn.execute("DROP TRIGGER IF EXISTS control_execution_requires_running_run")
    conn.execute(
        "CREATE TRIGGER control_execution_requires_running_run "
        "BEFORE INSERT ON control_executions "
        "WHEN NEW.status != 'running' OR NOT EXISTS ("
        " SELECT 1 FROM control_runs WHERE run_id = NEW.run_id"
        " AND status = 'running') "
        "BEGIN SELECT RAISE(ABORT, 'control execution must start in a running control run'); END")
    conn.execute("DROP TRIGGER IF EXISTS completed_control_execution_is_immutable_update")
    conn.execute("DROP TRIGGER IF EXISTS completed_control_execution_is_immutable_delete")
    conn.execute("DROP TRIGGER IF EXISTS control_execution_transition_is_valid")
    conn.execute("DROP TRIGGER IF EXISTS control_execution_identity_is_immutable")
    conn.execute(
        "CREATE TRIGGER completed_control_execution_is_immutable_update "
        "BEFORE UPDATE ON control_executions "
        "WHEN OLD.status != 'running' OR NOT EXISTS ("
        " SELECT 1 FROM control_runs WHERE run_id = OLD.run_id"
        " AND status = 'running') "
        "BEGIN SELECT RAISE(ABORT, 'terminal control execution is immutable'); END")
    conn.execute(
        "CREATE TRIGGER completed_control_execution_is_immutable_delete "
        "BEFORE DELETE ON control_executions "
        "BEGIN SELECT RAISE(ABORT, 'control execution records are immutable'); END")
    conn.execute(
        "CREATE TRIGGER control_execution_transition_is_valid "
        "BEFORE UPDATE ON control_executions "
        "WHEN OLD.status = 'running' AND (NEW.status NOT IN ('complete', 'failed')"
        " OR NEW.finished_at IS NULL"
        " OR (NEW.status = 'complete' AND (NEW.alert_count IS NULL OR NEW.failure IS NOT NULL))"
        " OR (NEW.status = 'failed' AND (NEW.failure IS NULL OR trim(NEW.failure) = ''))) "
        "BEGIN SELECT RAISE(ABORT, 'invalid control execution status transition'); END")
    conn.execute(
        "CREATE TRIGGER control_execution_identity_is_immutable "
        "BEFORE UPDATE OF run_id, control_id, started_at ON control_executions "
        "BEGIN SELECT RAISE(ABORT, 'control execution identity is immutable'); END")

    # A run's identity is fixed at creation. Only a single running-to-terminal
    # status transition may add its completion timestamp and failure detail.
    for trigger in (
            "control_run_identity_is_immutable", "terminal_control_run_is_immutable",
            "control_run_transition_is_valid", "control_runs_are_undeletable",
            "control_run_must_start_running"):
        conn.execute("DROP TRIGGER IF EXISTS {}".format(trigger))
    conn.execute(
        "CREATE TRIGGER control_run_identity_is_immutable "
        "BEFORE UPDATE OF params_hash, input_hash, code_hash, expected_controls, started_at "
        "ON control_runs "
        "BEGIN SELECT RAISE(ABORT, 'control run identity is immutable'); END")
    conn.execute(
        "CREATE TRIGGER terminal_control_run_is_immutable "
        "BEFORE UPDATE ON control_runs WHEN OLD.status != 'running' "
        "BEGIN SELECT RAISE(ABORT, 'terminal control run is immutable'); END")
    conn.execute(
        "CREATE TRIGGER control_run_transition_is_valid "
        "BEFORE UPDATE ON control_runs WHEN OLD.status = 'running' AND ("
        " NEW.status NOT IN ('complete', 'failed') OR NEW.finished_at IS NULL"
        " OR (NEW.status = 'complete' AND NEW.failure IS NOT NULL)"
        " OR (NEW.status = 'failed' AND (NEW.failure IS NULL OR trim(NEW.failure) = ''))) "
        "BEGIN SELECT RAISE(ABORT, 'invalid control run status transition'); END")
    conn.execute(
        "CREATE TRIGGER control_runs_are_undeletable BEFORE DELETE ON control_runs "
        "BEGIN SELECT RAISE(ABORT, 'control run records are immutable'); END")

    # Raw detector inputs are a snapshot while a control run is active. These
    # guards cover direct SQL and helper calls as well as the CLI refresh path.
    for table in ("trades", "candles", "markets", "events", "ingest_log",
                  "settlement_sources"):
        for operation in ("INSERT", "UPDATE", "DELETE"):
            trigger = "{}_deny_{}_during_run".format(table, operation.lower())
            conn.execute("DROP TRIGGER IF EXISTS {}".format(trigger))
            conn.execute(
                ("CREATE TRIGGER {} BEFORE {} ON {} "
                 "WHEN EXISTS (SELECT 1 FROM control_runs WHERE status = 'running') "
                 "BEGIN SELECT RAISE(ABORT, "
                 "'snapshot inputs cannot change during a running control run'); END")
                .format(trigger, operation, table))

    # Historical v1 alerts predate execution records.  Preserve them as a
    # labelled legacy run instead of mixing them into a later re-run's funnel.
    legacy = conn.execute(
        "SELECT params_hash, MIN(created_at) FROM alerts WHERE run_id IS NULL"
        " GROUP BY params_hash").fetchall()
    for params_hash, created_at in legacy:
        exists = conn.execute(
            "SELECT 1 FROM params WHERE params_hash = ?", (params_hash,)).fetchone()
        if not exists:
            continue
        cur = conn.execute(
            "INSERT INTO control_runs (params_hash, input_hash, code_hash, expected_controls,"
            " status, started_at, finished_at)"
            " VALUES (?, 'legacy-input-unavailable', 'legacy-code-unavailable', '[]',"
            " 'complete', ?, ?)",
            (params_hash, created_at, created_at))
        conn.execute("UPDATE alerts SET run_id = ? WHERE run_id IS NULL AND params_hash = ?",
                     (cur.lastrowid, params_hash))

    # Legacy binding is complete. From this point onward every alert, including
    # an unbound malformed legacy row, is immutable. New unbound alerts are
    # rejected by the insert trigger above.
    conn.execute("DROP TRIGGER IF EXISTS alerts_are_immutable")
    conn.execute("DROP TRIGGER IF EXISTS alerts_are_undeletable")
    conn.execute(
        "CREATE TRIGGER alerts_are_immutable BEFORE UPDATE ON alerts "
        "BEGIN SELECT RAISE(ABORT, 'alerts are immutable'); END")
    conn.execute(
        "CREATE TRIGGER alerts_are_undeletable BEFORE DELETE ON alerts "
        "BEGIN SELECT RAISE(ABORT, 'alerts are immutable'); END")

    # The migration above is the sole exception: application-created runs must
    # start in the running state and reach a terminal state through the guarded
    # transition triggers.
    conn.execute(
        "CREATE TRIGGER control_run_must_start_running BEFORE INSERT ON control_runs "
        "WHEN NEW.status != 'running' "
        "BEGIN SELECT RAISE(ABORT, 'control run must start in running state'); END")


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def upsert_trades(conn, rows: list[dict]) -> int:
    payload = []
    pending: dict[str, tuple] = {}
    for r in rows:
        # Kalshi's canonical field is taker_outcome_side.  Keep the deprecated
        # field only as a compatibility fallback, and fail closed if neither
        # provides an unambiguous direction.
        side = r.get("taker_outcome_side") or r.get("taker_side")
        if side not in {"yes", "no"}:
            raise ValueError("trade {} has no valid taker outcome side".format(
                r.get("trade_id", "<unknown>")))
        record = (
            r["trade_id"], r["ticker"], r["created_time"],
            _f(r.get("count_fp")), _f(r.get("yes_price_dollars")),
            _f(r.get("no_price_dollars")), side, side,
            r.get("taker_book_side"), 1 if r.get("is_block_trade") else 0,
        )
        # Trade IDs are immutable event identifiers.  A duplicate may be a
        # routine re-fetch; a changed detector input under the same ID is a
        # data-integrity conflict that must be investigated rather than silently
        # preserving whichever version arrived first.
        relevant = (record[1], record[2], record[3], record[4], record[5], record[7])
        prior = pending.get(record[0])
        if prior is not None:
            if prior != relevant:
                raise ValueError("conflicting detector inputs for trade {}".format(record[0]))
            continue
        existing = conn.execute(
            "SELECT ticker, created_time, count_fp, yes_price, no_price, "
            "taker_outcome_side FROM trades WHERE trade_id = ?", (record[0],)
        ).fetchone()
        if existing is not None:
            if tuple(existing) != relevant:
                raise ValueError("conflicting detector inputs for trade {}".format(record[0]))
            continue
        pending[record[0]] = relevant
        payload.append(record)
    try:
        conn.executemany(
            "INSERT INTO trades (trade_id, ticker, created_time, count_fp,"
            " yes_price, no_price, taker_side, taker_outcome_side, taker_book_side,"
            " is_block_trade) VALUES (?,?,?,?,?,?,?,?,?,?)", payload)
    except Exception:
        conn.rollback()
        raise
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
