"""Freeze a future evaluation interval, then acquire it after it has finished."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from . import cli
from .api import KalshiPublic
from .db import connect, init_schema
from .export import _source_commit, write_export
from .params import load_params, params_hash
from .runs import code_hash
from .validation import timestamp_us


def environment() -> dict:
    return {"python": platform.python_version(), "packages": dict(sorted(
        (d.metadata["Name"].lower(), d.version) for d in importlib.metadata.distributions()))}


def identity() -> dict:
    return {"code_hash": code_hash(),
            "params_hash": params_hash(load_params("config/params.yaml")),
            "requirements_hash": hashlib.sha256(Path("requirements.txt").read_bytes()).hexdigest(),
            "environment": environment()}


def freeze(path: str, start: str, end: str, series: list[str]) -> dict:
    now = datetime.now(timezone.utc)
    start_us, end_us = timestamp_us(start), timestamp_us(end)
    if start_us <= timestamp_us(now) or start_us >= end_us:
        raise ValueError("freeze a non-empty future interval before its data exist")
    if start_us % 3_600_000_000 or end_us % 3_600_000_000:
        raise ValueError("evaluation bounds must align to UTC hours")
    commit, dirty = _source_commit()
    if not commit or dirty:
        raise ValueError("commit the source changes before freezing an evaluation")
    api = KalshiPublic()
    manifest = {"schema": 1, "frozen_at": now.isoformat(), "start": start, "end": end,
                "series": cli._selected_series(series), "source_commit": commit,
                "api_base": api._base, **identity()}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # A second freeze must be a new file, not a rewrite of an earlier promise.
    with target.open("x") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return manifest


def acquire(path: str, db_path: str, output: str) -> dict:
    manifest = json.loads(Path(path).read_text())
    if manifest.get("schema") != 1:
        raise ValueError("unsupported evaluation manifest")
    frozen, start, end = (timestamp_us(manifest[k]) for k in ("frozen_at", "start", "end"))
    if not frozen < start < end:
        raise ValueError("manifest was not frozen before its observation interval")
    if end > timestamp_us(datetime.now(timezone.utc)):
        raise ValueError("wait until the frozen evaluation interval has finished")
    for key, value in identity().items():
        if manifest[key] != value:
            raise ValueError("{} changed after the evaluation was frozen".format(key))
    if KalshiPublic()._base != manifest["api_base"]:
        raise ValueError("API endpoint changed after the evaluation was frozen")
    if Path(db_path).exists() or Path(output).exists():
        raise ValueError("use a new database and output; retain earlier attempts")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    cli.main(register_params=True, db_path=db_path, series=manifest["series"])
    cli.main(db_path=db_path, series=manifest["series"],
             start_time=manifest["start"], end_time=manifest["end"])
    conn = connect(db_path)
    try:
        init_schema(conn)
        result = write_export(conn, output)
    finally:
        conn.close()
    # No automatic dispositions: an unreviewed candidate is not a benign result.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("freeze")
    plan.add_argument("--manifest", required=True)
    plan.add_argument("--start", required=True)
    plan.add_argument("--end", required=True)
    plan.add_argument("--series", nargs="+", default=cli.SERIES)
    collect = commands.add_parser("acquire")
    collect.add_argument("--manifest", required=True)
    collect.add_argument("--db", required=True)
    collect.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.manifest, args.start, args.end, args.series)
        print("Frozen {}. Retain this manifest before the observation interval.".format(args.manifest))
    else:
        result = acquire(args.manifest, args.db, args.output)
        print("Run {}: {} candidates; {} await analyst review.".format(
            result["run"]["run_id"], result["funnel"]["generated"], result["funnel"]["untriaged"]))


if __name__ == "__main__":
    main()
