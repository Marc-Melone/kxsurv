import sqlite3

import pytest

from kxsurv.db import connect, init_schema


def test_legacy_alerts_migrate_without_a_preexisting_natural_key_index():
    """A partially constructed v1 database still gains run-scoped history."""
    conn = connect(":memory:")
    conn.executescript("""
        CREATE TABLE trades (
          trade_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, created_time TEXT NOT NULL,
          count_fp REAL NOT NULL, yes_price REAL NOT NULL, no_price REAL NOT NULL,
          taker_side TEXT NOT NULL, taker_book_side TEXT, is_block_trade INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE params (
          params_hash TEXT PRIMARY KEY, registered_at TEXT NOT NULL,
          version TEXT NOT NULL, content TEXT NOT NULL
        );
        CREATE TABLE alerts (
          alert_id INTEGER PRIMARY KEY AUTOINCREMENT, control_id TEXT NOT NULL,
          target TEXT NOT NULL, window_start TEXT, window_end TEXT, score REAL,
          percentile REAL, threshold REAL, evidence TEXT, params_hash TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE dispositions (
          disposition_id INTEGER PRIMARY KEY AUTOINCREMENT, alert_id INTEGER NOT NULL,
          action TEXT NOT NULL, rationale TEXT NOT NULL, created_at TEXT NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO params VALUES ('legacy-hash', '2026-09-07T00:00:00Z', '1.0.0', '{}')"
    )
    conn.execute(
        "INSERT INTO alerts (control_id, target, params_hash, created_at)"
        " VALUES ('C4', 'T', 'legacy-hash', '2026-09-07T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO dispositions (alert_id, action, rationale, created_at)"
        " VALUES (1, 'no_action', 'historical record', '2026-09-07T00:00:00Z')"
    )
    conn.commit()

    init_schema(conn)
    run_id = conn.execute("SELECT run_id FROM alerts WHERE alert_id = 1").fetchone()[0]
    assert conn.execute(
        "SELECT status, input_hash, code_hash FROM control_runs WHERE run_id = ?", (run_id,)
    ).fetchone() == ("complete", "legacy-input-unavailable", "legacy-code-unavailable")
    assert conn.execute("SELECT COUNT(*) FROM dispositions").fetchone()[0] == 1

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE alerts SET score = 1.0 WHERE alert_id = 1")

    # A second initialization is safe and does not manufacture another legacy run.
    init_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM control_runs").fetchone()[0] == 1


def test_migration_rejects_an_ambiguous_legacy_parameter_version():
    conn = connect(":memory:")
    conn.execute("""
        CREATE TABLE params (
          params_hash TEXT PRIMARY KEY, registered_at TEXT NOT NULL,
          version TEXT NOT NULL, content TEXT NOT NULL
        )
    """)
    conn.executemany(
        "INSERT INTO params VALUES (?, '2026-09-07T00:00:00Z', '1.0.0', '{}')",
        [("hash-a",), ("hash-b",)],
    )
    conn.commit()

    with pytest.raises(RuntimeError, match="more than one hash"):
        init_schema(conn)
