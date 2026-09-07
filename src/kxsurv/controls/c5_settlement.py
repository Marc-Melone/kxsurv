"""C5 - settlement-source integrity. CFTC DCM Core Principle 4.

Core Principle 4 covers disruption of the settlement process, and Kalshi
markets resolve against external reference data. GET /series/{ticker} exposes
settlement_sources as [{name, url}] -- e.g. KXCPI resolves against the Bureau
of Labor Statistics.

Part 1 is an inventory: which series resolve against which provider, and how
concentrated that is. An outage or methodology change at one provider is a
CORRELATED settlement event across every market it resolves.

Part 2 is divergence monitoring where an independent corroborating source
exists. Alerts here are operational settlement-risk events, not participant-
conduct alerts, and route to a separate disposition track.
"""
from __future__ import annotations

import re

from . import Alert

# Words that carry no identifying weight when forming an acronym.
_STOPWORDS = {"of", "the", "and", "for", "us", "united", "states"}

CONTROL_ID = "C5"


def _words(name: str) -> list[str]:
    # Drop periods first so "U.S." collapses to "us" rather than splitting into
    # two single-letter tokens and producing a different acronym.
    cleaned = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace(".", ""))
    return [w for w in cleaned.split() if w and w not in _STOPWORDS]


def acronym(name: str) -> str:
    """Initials of the significant words: 'Bureau of Labor Statistics' -> 'BLS'."""
    return "".join(w[0] for w in _words(name)).upper()


def alias_groups(names) -> dict[str, str]:
    """Map each declared source name to a canonical key for its entity.

    Settlement metadata is free text. The same provider appears as both
    "Bureau of Labor Statistics" and "BLS", which splits any concentration
    measure computed from the raw field. A short name matching another name's
    acronym is treated as the same entity.
    """
    unique = list(dict.fromkeys(names))
    full = {}          # acronym -> canonical (longest spelling wins)
    for n in unique:
        w = _words(n)
        if len(w) > 1:
            key = acronym(n)
            if key not in full or len(n) > len(full[key]):
                full[key] = n

    out: dict[str, str] = {}
    for n in unique:
        w = _words(n)
        if len(w) == 1:                      # e.g. "BLS"
            out[n] = full.get(w[0].upper(), n)
        else:
            out[n] = full.get(acronym(n), n)
    return out


def build_inventory(conn, api, series_tickers: list[str]) -> int:
    n = 0
    for st in series_tickers:
        s = api.series(st)
        category = s.get("category")
        count = conn.execute(
            "SELECT COUNT(*) FROM markets WHERE series_ticker = ?", (st,)
        ).fetchone()[0]
        for src in (s.get("settlement_sources") or []):
            conn.execute(
                "INSERT OR REPLACE INTO settlement_sources (series_ticker,"
                " source_name, source_url, category, market_count)"
                " VALUES (?,?,?,?,?)",
                (st, src.get("name", "unknown"), src.get("url"), category, count))
            n += 1
    conn.commit()
    return n


def concentration(conn, normalise: bool = False) -> list[dict]:
    """Series and market counts per settlement source, most concentrated first.

    With `normalise=True`, names that alias to the same provider are merged --
    which is the only figure that reflects true correlated exposure.
    """
    # Count DISTINCT markets via a join. Summing the stored per-row
    # market_count double-counts any series that declares more than one source,
    # which would inflate the concentration figures.
    cur = conn.execute(
        "SELECT ss.source_name,"
        "       COUNT(DISTINCT ss.series_ticker) AS series_count,"
        "       COUNT(DISTINCT m.ticker)         AS market_count"
        " FROM settlement_sources ss"
        " LEFT JOIN markets m ON m.series_ticker = ss.series_ticker"
        " GROUP BY ss.source_name")
    rows = [{"source_name": r[0], "series_count": r[1], "market_count": r[2]}
            for r in cur.fetchall()]
    if normalise:
        groups = alias_groups([r["source_name"] for r in rows])
        merged: dict[str, dict] = {}
        for r in rows:
            canon = groups[r["source_name"]]
            m = merged.setdefault(canon, {"source_name": canon, "series_count": 0,
                                          "market_count": 0, "declared_as": []})
            m["series_count"] += r["series_count"]
            m["market_count"] += r["market_count"]
            m["declared_as"].append(r["source_name"])
        rows = list(merged.values())
        for r in rows:
            r["declared_as"] = sorted(r["declared_as"])
    rows.sort(key=lambda r: (-r["series_count"], -r["market_count"]))
    return rows


def run(conn, params: dict) -> list[Alert]:
    """Flag series that declare no settlement source at all.

    A market with no declared resolution source is a settlement-risk item on
    its face, and it is the one divergence check available without an
    independent corroborating feed.
    """
    alerts: list[Alert] = []

    # (a) A provider declared under more than one name. Any concentration
    # measure taken from the raw field is wrong until these are reconciled.
    declared = [r[0] for r in conn.execute(
        "SELECT DISTINCT source_name FROM settlement_sources").fetchall()]
    groups = alias_groups(declared)
    by_entity: dict[str, list[str]] = {}
    for name, canon in groups.items():
        by_entity.setdefault(canon, []).append(name)
    for canon, names in by_entity.items():
        if len(names) < 2:
            continue
        markets = conn.execute(
            "SELECT COUNT(DISTINCT m.ticker) FROM settlement_sources ss"
            " JOIN markets m ON m.series_ticker = ss.series_ticker"
            " WHERE ss.source_name IN ({})".format(",".join("?" * len(names))),
            names).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0] or 1
        alerts.append(Alert(
            control_id=CONTROL_ID, target="source:{}".format(canon),
            window_start=None, window_end=None,
            score=float(markets), percentile=None, threshold=None,
            evidence={"issue": "provider declared under multiple names",
                      "declared_names": sorted(names),
                      "markets_affected": markets,
                      "share_of_corpus": round(markets / total, 4),
                      "consequence": "declared concentration understates the "
                                     "correlated settlement exposure to this provider",
                      "track": "operational settlement risk, not participant conduct"}))

    # (b) Ladder settlement consistency. A `greater` ladder cannot settle NO at
    # a low strike and YES at a higher one: P(X > k) is non-increasing in k, and
    # the realised value either exceeds a strike or does not. A contradiction
    # means the event resolved against inconsistent reference data, which is a
    # settlement failure rather than a pricing observation.
    for (ev,) in conn.execute(
            "SELECT DISTINCT event_ticker FROM markets"
            " WHERE event_ticker IS NOT NULL AND strike_type = 'greater'"):
        rows = conn.execute(
            "SELECT floor_strike, result, ticker FROM markets"
            " WHERE event_ticker = ? AND floor_strike IS NOT NULL"
            "   AND result IN ('yes','no') ORDER BY floor_strike ASC",
            (ev,)).fetchall()
        last_no = None
        for strike, result, ticker in rows:
            if result == "no":
                last_no = (strike, ticker)
            elif last_no is not None:
                alerts.append(Alert(
                    control_id=CONTROL_ID, target="{}:{}".format(ev, ticker),
                    window_start=None, window_end=None,
                    score=float(strike - last_no[0]), percentile=None,
                    threshold=None,
                    evidence={"issue": "ladder settled inconsistently",
                              "lower_strike": last_no[0],
                              "lower_ticker": last_no[1],
                              "higher_strike": strike,
                              "higher_ticker": ticker,
                              "consequence": "a monotone ladder cannot settle NO "
                                             "below a strike that settled YES; the "
                                             "event resolved against inconsistent "
                                             "reference data",
                              "track": "operational settlement risk, not participant conduct"}))
                break

    # (c) Series declaring no settlement source at all.
    rows = conn.execute(
        "SELECT DISTINCT m.series_ticker FROM markets m"
        " WHERE m.series_ticker IS NOT NULL AND m.series_ticker NOT IN"
        " (SELECT series_ticker FROM settlement_sources)").fetchall()
    for (st,) in rows:
        count = conn.execute(
            "SELECT COUNT(*) FROM markets WHERE series_ticker = ?", (st,)
        ).fetchone()[0]
        alerts.append(Alert(
            control_id=CONTROL_ID, target=st,
            window_start=None, window_end=None,
            score=float(count), percentile=None, threshold=None,
            evidence={"issue": "no declared settlement source",
                      "affected_markets": count,
                      "track": "operational settlement risk, not participant conduct"}))
    return alerts
