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


def test_an_acronym_and_its_long_form_form_a_candidate_group():
    groups = alias_groups(["Bureau of Labor Statistics", "BLS",
                           "Federal Reserve Board of Governors"])
    assert groups["BLS"] == groups["Bureau of Labor Statistics"]
    assert groups["Federal Reserve Board of Governors"] != groups["BLS"]


def test_case_and_punctuation_do_not_create_a_separate_entity():
    groups = alias_groups(["U.S. Bureau of Labor Statistics",
                           "us bureau of labor statistics"])
    assert len(set(groups.values())) == 1


def test_run_flags_candidate_duplicate_source_naming(conn):
    from kxsurv.params import register
    P = {"version": "t", "c5_settlement": {"inventory_only": True}}
    register(conn, P)
    upsert_markets(conn, [market("KXCPI-26JUL-T0.1", "KXCPI-26JUL", 0.1),
                          market("KXU3-26JUL-T4.0", "KXU3-26JUL", 4.0)])
    build_inventory(conn, FakeApi(), ["KXCPI", "KXU3", "KXFED"])
    conn.execute("UPDATE settlement_sources SET source_name='BLS'"
                 " WHERE series_ticker='KXU3'")
    conn.commit()
    out = run(conn, P)
    aliases = [a for a in out
               if a.evidence.get("issue") == "candidate duplicate settlement-source naming"]
    assert len(aliases) == 1
    assert set(aliases[0].evidence["declared_names"]) == {"BLS", "Bureau of Labor Statistics"}
    assert aliases[0].evidence["source_domains"] == ["www.bls.gov"]
    assert "if provider identity is confirmed" in aliases[0].evidence["consequence"]


def test_no_alias_alert_when_names_are_consistent(conn):
    from kxsurv.params import register
    P = {"version": "t", "c5_settlement": {"inventory_only": True}}
    register(conn, P)
    upsert_markets(conn, [market("KXCPI-26JUL-T0.1", "KXCPI-26JUL", 0.1)])
    build_inventory(conn, FakeApi(), ["KXCPI", "KXU3", "KXFED"])
    assert [a for a in run(conn, P)
            if a.evidence.get("issue") ==
            "candidate duplicate settlement-source naming"] == []


# --- third review round (2026-09-07) ---------------------------------------

class MultiSourceApi:
    def series(self, t):
        return {"settlement_sources": [{"name": "Alpha Agency", "url": "a"},
                                       {"name": "Beta Bureau", "url": "b"}],
                "category": "X"}


def test_per_source_coverage_overlaps_and_is_not_a_partition(conn):
    """Per-source counts are coverage, not a partition: a market resolving
    against two declared sources appears under both. On the real corpus every
    series declares one source, so the counts happen to sum to the total and
    read like a partition. They are not one, and the framework says so."""
    upsert_markets(conn, [market(f"KXQ-26JUL-T{i}", "KXQ-26JUL", float(i))
                          for i in range(10)])
    build_inventory(conn, MultiSourceApi(), ["KXQ"])
    rows = concentration(conn)
    assert {r["source_name"] for r in rows} == {"Alpha Agency", "Beta Bureau"}
    assert all(r["market_count"] == 10 for r in rows), \
        "each source covers all 10 markets; the sets overlap"
    assert sum(r["market_count"] for r in rows) == 20, \
        "summing overlapping coverage is not meaningful and must not be presented as a total"


def test_normalised_concentration_unions_duplicate_alias_coverage(conn):
    class AliasApi:
        def series(self, _):
            return {"settlement_sources": [
                {"name": "Bureau of Labor Statistics", "url": "https://www.bls.gov/a"},
                {"name": "BLS", "url": "https://www.bls.gov/b"}], "category": "X"}
    upsert_markets(conn, [market("KXQ-26JUL-T1", "KXQ-26JUL", 1.0)])
    build_inventory(conn, AliasApi(), ["KXQ"])
    assert concentration(conn, normalise=True) == [{
        "source_name": "Bureau of Labor Statistics", "series_count": 1,
        "market_count": 1, "declared_as": ["BLS", "Bureau of Labor Statistics"]}]


def test_normalised_concentration_does_not_merge_an_acronym_collision(conn):
    conn.executemany(
        "INSERT INTO settlement_sources"
        " (series_ticker, source_name, source_url, category, market_count)"
        " VALUES (?, ?, ?, 'X', 0)",
        [("S1", "Alpha Bureau", "https://alpha.example/a"),
         ("S2", "AB", "https://unrelated.example/b")],
    )
    conn.commit()
    rows = concentration(conn, normalise=True)
    assert {row["source_name"] for row in rows} == {"Alpha Bureau", "AB"}


def test_market_counts_are_live_not_frozen_at_inventory_time(conn):
    """market_count was read at build_inventory time; markets ingested later
    left the figure stale. It is now computed by join at report time."""
    upsert_markets(conn, [market("KXQ-26JUL-T1", "KXQ-26JUL", 1.0)])
    build_inventory(conn, FakeApi(), ["KXCPI"])
    conn.execute("UPDATE settlement_sources SET series_ticker='KXQ'")
    conn.commit()
    upsert_markets(conn, [market("KXQ-26JUL-T2", "KXQ-26JUL", 2.0)])
    assert concentration(conn)[0]["market_count"] == 2


def test_ladder_result_consistency_is_checked(conn):
    """A 'greater' ladder cannot settle NO at a low strike and YES at a higher
    one. Nothing verified this; a contradiction would be a genuine
    settlement-integrity failure."""
    from kxsurv.params import register
    from kxsurv.controls.c5_settlement import run
    P = {"version": "t", "c5_settlement": {"inventory_only": True}}
    register(conn, P)
    upsert_markets(conn, [
        market("KXQ-26JUL-T0.1", "KXQ-26JUL", 0.1, result="no"),
        market("KXQ-26JUL-T0.2", "KXQ-26JUL", 0.2, result="yes"),  # impossible
    ])
    build_inventory(conn, FakeApi(), ["KXCPI"])
    out = [a for a in run(conn, P)
           if a.evidence.get("issue") == "ladder settled inconsistently"]
    assert len(out) == 1
    assert out[0].evidence["lower_strike"] == 0.1


def test_a_consistent_ladder_raises_no_such_alert(conn):
    from kxsurv.params import register
    from kxsurv.controls.c5_settlement import run
    P = {"version": "t", "c5_settlement": {"inventory_only": True}}
    register(conn, P)
    upsert_markets(conn, [
        market("KXQ-26JUL-T0.1", "KXQ-26JUL", 0.1, result="yes"),
        market("KXQ-26JUL-T0.2", "KXQ-26JUL", 0.2, result="no"),
    ])
    build_inventory(conn, FakeApi(), ["KXCPI"])
    assert [a for a in run(conn, P)
            if a.evidence.get("issue") == "ladder settled inconsistently"] == []


def test_ladder_consistency_does_not_compare_other_strike_types(conn):
    """A mixed event must not compare a non-`greater` contract to the ladder."""
    from kxsurv.params import register

    P = {"version": "mixed-ladder", "c5_settlement": {"inventory_only": True}}
    register(conn, P)
    upsert_markets(conn, [
        market("KXQ-26JUL-LESS", "KXQ-26JUL", 0.1, result="no", strike_type="less"),
        market("KXQ-26JUL-GREATER", "KXQ-26JUL", 0.2, result="yes", strike_type="greater"),
    ])
    assert [a for a in run(conn, P)
            if a.evidence.get("issue") == "ladder settled inconsistently"] == []


def test_inventory_replaces_sources_removed_by_a_later_api_snapshot(conn):
    """A refresh must not leave an old provider declaration in place forever."""
    class MutableApi:
        def __init__(self):
            self.sources = [{"name": "Bureau of Labor Statistics",
                             "url": "https://www.bls.gov/"}]

        def series(self, _):
            return {"settlement_sources": self.sources, "category": "Economics"}

    from kxsurv.params import register

    params = {"version": "c5-source-removal", "c5_settlement": {"inventory_only": True}}
    register(conn, params)
    upsert_markets(conn, [market("KXCPI-26JUL-T0.1", "KXCPI-26JUL", 0.1)])
    api = MutableApi()
    build_inventory(conn, api, ["KXCPI"])
    assert conn.execute("SELECT COUNT(*) FROM settlement_sources").fetchone()[0] == 1

    api.sources = []
    build_inventory(conn, api, ["KXCPI"])
    assert conn.execute("SELECT COUNT(*) FROM settlement_sources").fetchone()[0] == 0
    assert [a.target for a in run(conn, params)
            if a.evidence.get("issue") == "no declared settlement source"] == ["KXCPI"]
