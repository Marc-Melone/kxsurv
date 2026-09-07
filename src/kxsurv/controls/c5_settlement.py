"""C5 - settlement-source integrity. CFTC DCM Core Principle 4.

Core Principle 4 covers disruption of the settlement process, and Kalshi
markets resolve against external reference data. GET /series/{ticker} exposes
settlement_sources as [{name, url}] -- e.g. KXCPI resolves against the Bureau
of Labor Statistics.

Part 1 is an inventory: which series resolve against which provider, and how
concentrated that is. An outage or methodology change at one provider is a
CORRELATED settlement event across every market it resolves.

No independent corroborating feed is ingested, so this control is deliberately
limited to source-inventory metadata and resolved-ladder consistency. Alerts
are operational settlement-risk events, not participant-conduct findings.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

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
    try:
        for st in series_tickers:
            s = api.series(st)
            if "settlement_sources" not in s:
                raise ValueError("series {} response omitted settlement_sources".format(st))
            category = s.get("category")
            sources = s["settlement_sources"] or []
            # A refresh is an authoritative replacement for this series.  Retaining
            # a source removed by the API would make C5's inventory look complete
            # and could suppress a genuine no-source alert.
            conn.execute("DELETE FROM settlement_sources WHERE series_ticker = ?", (st,))
            count = conn.execute(
                "SELECT COUNT(*) FROM markets WHERE series_ticker = ?", (st,)
            ).fetchone()[0]
            for src in sources:
                conn.execute(
                    "INSERT OR REPLACE INTO settlement_sources (series_ticker,"
                    " source_name, source_url, category, market_count)"
                    " VALUES (?,?,?,?,?)",
                    (st, src.get("name") or "unknown", src.get("url"), category, count))
                n += 1
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return n


def concentration(conn, normalise: bool = False) -> list[dict]:
    """Series and market counts per settlement source, most concentrated first.

    With `normalise=True`, names that alias to the same provider are merged --
    which is the only figure that reflects true correlated exposure.
    """
    # Build set unions, rather than summing pre-aggregated counts. A series can
    # declare an alias and a long form (or two distinct sources), in which case
    # summing would double-count its markets after normalisation.
    raw = conn.execute(
        "SELECT ss.source_name, ss.series_ticker, m.ticker"
        " FROM settlement_sources ss"
        " LEFT JOIN markets m ON m.series_ticker = ss.series_ticker").fetchall()
    groups = alias_groups([r[0] for r in raw]) if normalise else {}
    merged: dict[str, dict] = {}
    for name, series, ticker in raw:
        canon = groups.get(name, name)
        item = merged.setdefault(canon, {"source_name": canon, "series": set(),
                                         "markets": set(), "declared_as": set()})
        item["series"].add(series)
        if ticker is not None:
            item["markets"].add(ticker)
        item["declared_as"].add(name)
    rows = []
    for item in merged.values():
        row = {"source_name": item["source_name"], "series_count": len(item["series"]),
               "market_count": len(item["markets"])}
        if normalise:
            row["declared_as"] = sorted(item["declared_as"])
        rows.append(row)
    rows.sort(key=lambda r: (-r["series_count"], -r["market_count"]))
    return rows


def _source_domains(conn, names: list[str]) -> list[str]:
    if not names:
        return []
    rows = conn.execute(
        "SELECT source_url FROM settlement_sources WHERE source_name IN ({})".format(
            ",".join("?" * len(names))), names).fetchall()
    return sorted({parsed.hostname.lower() for (url,) in rows if url
                   for parsed in [urlparse(str(url))] if parsed.hostname})


def run(conn, params: dict) -> list[Alert]:
    """Flag source-inventory and resolved-ladder consistency problems.

    An independent-feed divergence control is not implemented.  A market with
    no declared resolution source is nevertheless an inventory-risk item on
    its face.
    """
    if not params["c5_settlement"].get("inventory_only", True):
        raise ValueError("C5 divergence monitoring requires an independent source feed")
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
        domains = _source_domains(conn, names)
        # An acronym collision is not evidence that providers are identical.
        # Require the declared metadata to corroborate the name match.
        if len(domains) != 1:
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
                      "source_domains": domains,
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
            "   AND strike_type = 'greater' AND result IN ('yes','no')"
            " ORDER BY floor_strike ASC",
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
