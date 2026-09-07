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


# --- source-name normalisation (added 2026-09-07 second review) ------------
# The BLS naming finding was the README's headline C5 result but no code
# produced it -- it was spotted by reading output. A finding attributed to a
# control the control does not compute is not a finding.

from kxsurv.controls.c5_settlement import acronym, alias_groups, run


def test_acronym_is_built_from_significant_words():
    assert acronym("Bureau of Labor Statistics") == "BLS"
    assert acronym("Federal Reserve Board of Governors") == "FRBG"


def test_an_acronym_and_its_long_form_are_recognised_as_one_entity():
    groups = alias_groups(["Bureau of Labor Statistics", "BLS",
                           "Federal Reserve Board of Governors"])
    assert groups["BLS"] == groups["Bureau of Labor Statistics"]
    assert groups["Federal Reserve Board of Governors"] != groups["BLS"]


def test_case_and_punctuation_do_not_create_a_separate_entity():
    groups = alias_groups(["U.S. Bureau of Labor Statistics",
                           "us bureau of labor statistics"])
    assert len(set(groups.values())) == 1


def test_run_flags_a_provider_declared_under_two_names(conn):
    from kxsurv.params import register
    P = {"version": "t", "c5_settlement": {"divergence_tolerance": 0.0,
                                           "inventory_only": False}}
    register(conn, P)
    upsert_markets(conn, [market("KXCPI-26JUL-T0.1", "KXCPI-26JUL", 0.1),
                          market("KXU3-26JUL-T4.0", "KXU3-26JUL", 4.0)])
    build_inventory(conn, FakeApi(), ["KXCPI", "KXU3", "KXFED"])
    conn.execute("UPDATE settlement_sources SET source_name='BLS'"
                 " WHERE series_ticker='KXU3'")
    conn.commit()
    out = run(conn, P)
    aliases = [a for a in out if a.evidence.get("issue") == "provider declared under multiple names"]
    assert len(aliases) == 1
    assert set(aliases[0].evidence["declared_names"]) == {"BLS", "Bureau of Labor Statistics"}


def test_no_alias_alert_when_names_are_consistent(conn):
    from kxsurv.params import register
    P = {"version": "t", "c5_settlement": {"divergence_tolerance": 0.0,
                                           "inventory_only": False}}
    register(conn, P)
    upsert_markets(conn, [market("KXCPI-26JUL-T0.1", "KXCPI-26JUL", 0.1)])
    build_inventory(conn, FakeApi(), ["KXCPI", "KXU3", "KXFED"])
    assert [a for a in run(conn, P)
            if a.evidence.get("issue") == "provider declared under multiple names"] == []
