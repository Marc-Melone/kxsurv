import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from kxsurv import cli, evaluate
from kxsurv.api import BASE
from tests.test_cli import _seed_snapshot


def manifest():
    return {"schema": 1, "frozen_at": "2026-01-01T00:00:00Z",
            "start": "2026-01-02T00:00:00Z", "end": "2026-01-03T00:00:00Z",
            "series": ["KXCPI"], "source_commit": "test", "api_base": BASE,
            **evaluate.identity()}


def write_manifest(tmp_path, doc):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(doc))
    return str(path)


def test_cannot_freeze_an_already_observed_period(tmp_path):
    with pytest.raises(ValueError, match="future interval"):
        evaluate.freeze(str(tmp_path / "m.json"), "2020-01-01T00:00:00Z",
                        "2020-02-01T00:00:00Z", ["KXCPI"])
    assert not (tmp_path / "m.json").exists()


def test_freeze_is_create_only_and_records_the_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "_source_commit", lambda: ("abc123", False))
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    path = str(tmp_path / "m.json")
    doc = evaluate.freeze(path, start.isoformat(), (start + timedelta(days=7)).isoformat(), ["kxcpi"])
    assert doc["series"] == ["KXCPI"]
    assert doc["environment"]["python"]
    assert doc["environment"]["packages"]["requests"]
    with pytest.raises(FileExistsError):
        evaluate.freeze(path, start.isoformat(), (start + timedelta(days=7)).isoformat(), ["KXCPI"])


@pytest.mark.parametrize("failure", ["unfinished", "drift", "late_freeze"])
def test_bad_evaluation_manifest_never_starts_acquisition(tmp_path, monkeypatch, failure):
    doc = manifest()
    if failure == "unfinished":
        doc["end"] = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    elif failure == "drift":
        doc["code_hash"] = "changed"
    else:
        doc["frozen_at"] = doc["start"]
    monkeypatch.setattr(cli, "main", lambda **_: pytest.fail("must fail before any acquisition"))
    with pytest.raises(ValueError):
        evaluate.acquire(write_manifest(tmp_path, doc), str(tmp_path / "data.db"),
                         str(tmp_path / "run.json"))
    assert not (tmp_path / "data.db").exists()


def test_evaluation_runs_fixed_interval_and_leaves_review_to_an_analyst(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "KalshiPublic", lambda: SimpleNamespace(_base=BASE))
    monkeypatch.setattr(cli, "KalshiPublic", lambda: object())
    bounds = []

    def ingest(conn, api, series, **kwargs):
        bounds.append(kwargs)
        _seed_snapshot(conn, series)
        return {"markets": 1, "candles": 1}

    monkeypatch.setattr(cli, "ingest_series", ingest)
    monkeypatch.setattr(cli.c5_settlement, "build_inventory", lambda *_: 1)
    result = evaluate.acquire(write_manifest(tmp_path, manifest()),
                              str(tmp_path / "data.db"), str(tmp_path / "run.json"))
    assert bounds == [{"start_ts": 1767312000, "end_ts": 1767398400}]
    assert result["run"]["status"] == "complete"
    assert result["run"]["controls_complete"] == 5
    assert result["funnel"]["triaged"] == 0
    assert (tmp_path / "data.db").exists()
    assert json.loads((tmp_path / "run.json").read_text()) == result


def test_cli_rejects_partial_or_unaligned_fixed_bounds():
    with pytest.raises(ValueError, match="together"):
        cli.main(start_time="2026-01-01T00:00:00Z")
    with pytest.raises(ValueError, match="whole UTC hours"):
        cli.main(start_time="2026-01-01T00:00:00.001Z", end_time="2026-01-02T00:00:00Z")
