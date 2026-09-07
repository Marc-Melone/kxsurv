from kxsurv.controls.c5_settlement import build_inventory, concentration
from kxsurv.db import upsert_markets
from tests.fixtures import market


class FakeApi:
    RESP = {
        "KXCPI": {"settlement_sources": [
            {"name": "Bureau of Labor Statistics", "url": "https://www.bls.gov/cpi/"}],
            "category": "Economics"},
        "KXU3": {"settlement_sources": [
            {"name": "Bureau of Labor Statistics", "url": "https://www.bls.gov/cps/"}],
            "category": "Economics"},
        "KXFED": {"settlement_sources": [
            {"name": "Federal Reserve", "url": "https://www.federalreserve.gov/"}],
            "category": "Economics"},
    }

    def series(self, t):
        return self.RESP[t]


def test_inventory_records_one_row_per_series_source(conn):
    assert build_inventory(conn, FakeApi(), ["KXCPI", "KXU3", "KXFED"]) == 3
    assert conn.execute("SELECT COUNT(*) FROM settlement_sources").fetchone()[0] == 3


def test_concentration_groups_series_by_source(conn):
    upsert_markets(conn, [market("KXCPI-26JUL-T0.1", "KXCPI-26JUL", 0.1),
                          market("KXU3-26JUL-T4.0", "KXU3-26JUL", 4.0)])
    build_inventory(conn, FakeApi(), ["KXCPI", "KXU3", "KXFED"])
    rows = {r["source_name"]: r for r in concentration(conn)}
    assert rows["Bureau of Labor Statistics"]["series_count"] == 2
    assert rows["Federal Reserve"]["series_count"] == 1


def test_concentration_is_ordered_most_concentrated_first(conn):
    build_inventory(conn, FakeApi(), ["KXCPI", "KXU3", "KXFED"])
    rows = concentration(conn)
    assert rows[0]["source_name"] == "Bureau of Labor Statistics"
