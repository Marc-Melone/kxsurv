"""Entry point: explicitly register, ingest, or locally re-run controls."""
from __future__ import annotations

import argparse
import sys

from .api import KalshiPublic
from .controls import run_control
from .controls import (c1_prerelease, c2_prehalt, c3_oi_divergence,
                       c4_monotonicity, c5_settlement)
from .db import connect, init_schema
from .events import build_events
from .ingest import ingest_series
from .params import load_params, register, verify
from .runs import (begin_run, begin_snapshot_refresh, fail_run,
                   fail_snapshot_refresh, finish_run, finish_snapshot_refresh,
                   verify_snapshot_ready)
from .controls.c1_prerelease import coverage as c1_coverage
from .controls.c3_oi_divergence import coverage as c3_coverage
from .report import funnel_markdown

SERIES = ["KXCPI", "KXCPIYOY", "KXPAYROLLS", "KXU3", "KXFED"]
CONTROLS = [c4_monotonicity, c3_oi_divergence, c1_prerelease,
            c2_prehalt, c5_settlement]
# Trades can legitimately be absent beyond the public tape horizon, and an
# empty settlement-source inventory is itself a C5 condition.  Do not mistake
# either condition for an incomplete snapshot.
REQUIRED_SNAPSHOT_TABLES = ("markets", "events", "candles", "ingest_log")


def main(skip_ingest: bool = False, register_params: bool = False) -> int:
    params = load_params("config/params.yaml")
    conn = connect("out/kxsurv.db")
    init_schema(conn)
    if register_params:
        register(conn, params)
        print("registered parameter version {}".format(params["version"]))
        return 0
    # Fail before an API call or raw-data mutation when the parameters were not
    # explicitly registered in advance.
    verify(conn, params)

    if not skip_ingest:
        begin_snapshot_refresh(conn)
        try:
            api = KalshiPublic()
            for s in SERIES:
                print(ingest_series(conn, api, s), flush=True)
            print("events:", build_events(conn))
            c5_settlement.build_inventory(conn, api, SERIES)
        except Exception as exc:
            fail_snapshot_refresh(conn, exc)
            raise
        else:
            finish_snapshot_refresh(conn)
    else:
        verify_snapshot_ready(conn)
        missing = [table for table in REQUIRED_SNAPSHOT_TABLES
                   if conn.execute("SELECT COUNT(*) FROM {}".format(table)).fetchone()[0] == 0]
        unlogged = conn.execute(
            "SELECT COUNT(*) FROM markets m LEFT JOIN ingest_log i USING(ticker)"
            " WHERE i.ticker IS NULL"
        ).fetchone()[0]
        if missing:
            raise RuntimeError("--skip-ingest requires an existing local snapshot; missing {}"
                               .format(", ".join(missing)))
        if unlogged:
            raise RuntimeError("--skip-ingest requires a completeness record for every market; "
                               "{} market(s) are missing one".format(unlogged))

    run_id = begin_run(conn, params)
    try:
        for mod in CONTROLS:
            alerts = run_control(conn, mod, params, run_id)
            print("{}: {} alerts".format(mod.CONTROL_ID, len(alerts)), flush=True)
    except Exception as exc:
        # Preserve a failed run record for audit; it is excluded from the
        # default funnel because it is not complete.
        fail_run(conn, run_id, exc)
        raise
    else:
        finish_run(conn, run_id)

    print()
    print("C1 coverage:", c1_coverage(conn, params))
    print("C3 population:", c3_coverage(conn, params))
    print()
    print(funnel_markdown(conn, run_id))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run kxsurv against a registered parameter set and data snapshot.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--skip-ingest", action="store_true",
                       help="run locally against an existing snapshot; make no API calls")
    group.add_argument("--register-params", action="store_true",
                       help="explicitly register the current new parameter version, then exit")
    args = parser.parse_args()
    sys.exit(main(skip_ingest=args.skip_ingest, register_params=args.register_params))
