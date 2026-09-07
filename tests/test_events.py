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
