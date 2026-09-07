"""Entry point: ingest, register parameters, run all controls, print the funnel."""
from __future__ import annotations

import sys

from .api import KalshiPublic
from .controls import run_control
from .controls import (c1_prerelease, c2_prehalt, c3_oi_divergence,
                       c4_monotonicity, c5_settlement)
from .db import connect, init_schema
from .events import build_events
from .ingest import ingest_series
from .params import load_params, register
from .report import funnel_markdown

SERIES = ["KXCPI", "KXCPIYOY", "KXPAYROLLS", "KXU3", "KXFED"]
CONTROLS = [c4_monotonicity, c3_oi_divergence, c1_prerelease,
            c2_prehalt, c5_settlement]


def main(skip_ingest: bool = False) -> int:
    params = load_params("config/params.yaml")
    conn = connect("out/kxsurv.db")
    init_schema(conn)
    register(conn, params)

    api = KalshiPublic()
    if not skip_ingest:
        for s in SERIES:
            print(ingest_series(conn, api, s), flush=True)
    print("events:", build_events(conn))
    c5_settlement.build_inventory(conn, api, SERIES)

    for mod in CONTROLS:
        alerts = run_control(conn, mod, params)
        print("{}: {} alerts".format(mod.CONTROL_ID, len(alerts)), flush=True)

    print()
    print(funnel_markdown(conn))
    return 0


if __name__ == "__main__":
    sys.exit(main(skip_ingest="--skip-ingest" in sys.argv))
