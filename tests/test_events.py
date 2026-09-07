from kxsurv.db import upsert_markets
from kxsurv.events import build_events, event_outcome, ladder, RELEASE_TIMES
from tests.fixtures import market


def _load(conn):
    upsert_markets(conn, [
        market("KXCPI-26JUL-T0.1", "KXCPI-26JUL", 0.1, result="yes"),
        market("KXCPI-26JUL-T0.3", "KXCPI-26JUL", 0.3, result="no"),
        market("KXCPI-26JUL-T0.2", "KXCPI-26JUL", 0.2, result="yes"),
    ])


def test_release_times_cover_all_five_series():
    for s in ("KXCPI", "KXCPIYOY", "KXPAYROLLS", "KXU3", "KXFED"):
        assert s in RELEASE_TIMES


def test_build_events_creates_one_row_per_event(conn):
    _load(conn)
    assert build_events(conn) == 1
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_outcome_is_highest_strike_settling_yes(conn):
    _load(conn)
    build_events(conn)
    assert event_outcome(conn, "KXCPI-26JUL") == "KXCPI-26JUL-T0.2"


def test_ladder_returns_strikes_ascending(conn):
    _load(conn)
    assert [m["floor_strike"] for m in ladder(conn, "KXCPI-26JUL")] == [0.1, 0.2, 0.3]


# --- statutory release times (fix 2026-09-07) ------------------------------
# RELEASE_TIMES was defined but never read; release_time_utc was always NULL,
# while the framework claimed C1 aligned markets to their statutory publication
# time. Now computed and stored.

from kxsurv.events import release_time_for


def test_bls_release_is_0830_et_on_the_halt_date(conn):
    # KXCPI-26JUL halted 2026-08-12T12:25:00Z == 08:25 EDT
    rel = release_time_for("KXCPI", "2026-08-12T12:25:00Z")
    assert rel == "2026-08-12T12:30:00Z"          # 08:30 EDT


def test_fomc_release_is_1400_et():
    rel = release_time_for("KXFED", "2026-07-29T17:55:00Z")
    assert rel == "2026-07-29T18:00:00Z"          # 14:00 EDT


def test_unknown_series_has_no_statutory_time():
    assert release_time_for("KXNOTREAL", "2026-08-12T12:25:00Z") is None


def test_build_events_stores_the_release_time(conn):
    _load(conn)
    build_events(conn)
    row = conn.execute(
        "SELECT release_time_utc, halt_time_utc FROM events").fetchone()
    assert row[0] == "2026-08-12T12:30:00Z"
    assert row[1] == "2026-08-12T12:25:00Z"
