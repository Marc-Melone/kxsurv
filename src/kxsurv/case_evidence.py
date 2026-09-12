"""Re-fetch a C1 case's public tape and compare it with its published summary.

This is a new retrieval, not recovery of the unavailable historical database.
The generated supplement says which published metrics it does and does not match.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .api import KalshiPublic
from .controls import percentile_of
from .controls.c1_prerelease import (_iso, _parse, _trades_between,
                                    aggressor_direction, informed_flow_score)
from .db import connect, init_schema, upsert_trades
from .params import load_params, params_hash
from .validation import timestamp_us


def render_supplement(artifact: dict, alert_id: int, params: dict, api) -> str:
    if artifact["run"]["params_hash"] != params_hash(params):
        raise ValueError("parameters do not match the published artifact")
    alert = next((a for a in artifact["alerts"] if a["alert_id"] == alert_id), None)
    if alert is None or alert["control_id"] != "C1":
        raise ValueError("select a published C1 alert")
    if alert["evidence"].get("surprise_price") != "per-trade execution price":
        raise ValueError("the published case uses a different C1 scoring method")
    p = params["c1_prerelease"]
    start, end = _parse(alert["window_start"]), _parse(alert["window_end"])
    length = timedelta(minutes=p["window_minutes"])
    if end - start != length:
        raise ValueError("case window does not match the registered length")
    rows = api.trades(ticker=alert["target"],
                      min_ts=timestamp_us(start - length * p["null_windows"]) // 1_000_000,
                      max_ts=timestamp_us(end) // 1_000_000)
    conn = connect(":memory:")
    try:
        init_schema(conn)
        upsert_trades(conn, [dict(row, ticker=alert["target"]) for row in rows])
        settled_yes = alert["evidence"]["settled"] == "yes"
        window = _trades_between(conn, alert["target"], start, end)
        detail = conn.execute(
            "SELECT created_time, count_fp, yes_price, taker_outcome_side FROM trades"
            " WHERE ticker = ? AND created_time_us >= ? AND created_time_us < ?"
            " ORDER BY created_time_us, trade_id",
            (alert["target"], timestamp_us(start), timestamp_us(end))).fetchall()
        comparisons = []
        for i in range(1, p["null_windows"] + 1):
            stop = end - length * i
            w = _trades_between(conn, alert["target"], stop - length, stop)
            comparisons.append((stop - length, stop, w,
                                informed_flow_score(w, None, settled_yes) if w else None))
    finally:
        conn.close()
    null = [row[3] for row in comparisons if row[3] is not None]
    score = informed_flow_score(window, None, settled_yes)
    volume = sum(row[1] for row in detail)
    observed = {"Trade count": len(window), "Window volume": volume,
                "C1 score": score, "Non-empty comparison windows": len(null),
                "Percentile": percentile_of(score, null)}
    expected = {"Trade count": alert["evidence"]["trade_count"],
                "Window volume": alert["evidence"]["window_volume"],
                "C1 score": alert["score"],
                "Non-empty comparison windows": alert["evidence"]["null_samples"],
                "Percentile": alert["percentile"]}
    lines = ["# Public-tape supplement — {}".format(alert["target"]), "",
             "Retrieved: {}".format(datetime.now(timezone.utc).isoformat()), "",
             "Published reference: run {}, alert {}, source commit `{}`.".format(
                 artifact["run"]["run_id"], alert_id, artifact["run"]["source_commit"]), "",
             "This is a fresh retrieval from the public API. Agreement with the summary "
             "does not establish identity with every row of the original snapshot. "
             "The published artifact and its disposition remain unchanged.", "",
             "## Timeline", "",
             "- Scored interval: `[{}, {})` (UTC).".format(_iso(start), _iso(end)),
             "- Halt-to-release gap in the published record: {} minute(s).".format(
                 alert["evidence"]["halt_to_release_minutes"]), "",
             "## Reconciliation", "",
             "| Metric | Published | Re-fetched | Matches |",
             "|---|---:|---:|---|"]
    for key, value in observed.items():
        matches = math.isclose(value, expected[key], rel_tol=1e-10, abs_tol=1e-9)
        lines.append("| {} | {:.10g} | {:.10g} | {} |".format(
            key, expected[key], value, "yes" if matches else "NO — investigate difference"))
    lines += ["", "## Trades in the scored window", "",
              "Contribution is contracts × direction × surprise / total window volume. "
              "Direction is +1 for buying the eventual outcome and −1 otherwise.", "",
              "| Timestamp | Contracts | YES price | Aggressor bought | Surprise | Score contribution |",
              "|---|---:|---:|---|---:|---:|"]
    for ts, size, price, side in detail:
        surprise = 1 - price if settled_yes else price
        contribution = size * aggressor_direction(side, settled_yes) * surprise / volume
        lines.append("| {} | {:.2f} | {:.4f} | {} | {:.4f} | {:.8f} |".format(
            ts, size, price, side, surprise, contribution))
    if not detail:
        lines.append("| No trades returned | — | — | — | — | — |")
    lines += ["", "## Comparison windows", "",
              "Empty windows are shown explicitly and excluded from the percentile population.", "",
              "| Start UTC (inclusive) | End UTC (exclusive) | Trades | Contracts | C1 score |",
              "|---|---|---:|---:|---:|"]
    for begin, stop, trades, value in comparisons:
        lines.append("| {} | {} | {} | {:.2f} | {} |".format(
            _iso(begin), _iso(stop), len(trades), sum(t["count_fp"] for t in trades),
            "excluded: empty" if value is None else "{:.8f}".format(value)))
    lines += ["", "## Interpretation", "",
              "A high relative rank is a screening result. These comparison windows "
              "are sparse, dependent observations and do not calibrate a false-positive "
              "rate. Public-information processing remains an alternative explanation; "
              "account identity and access to non-public information are unavailable.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", default="site/data/run-8.json")
    parser.add_argument("--alert", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    text = render_supplement(json.loads(Path(args.artifact).read_text()), args.alert,
                             load_params("config/params.yaml"), KalshiPublic())
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print("Wrote {}".format(path))


if __name__ == "__main__":
    main()
