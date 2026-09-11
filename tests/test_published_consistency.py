"""The published documents must agree with the published artifact.

Every defect this project has had in its published record was a number in a
document that no longer matched, or never matched, the run it described. Prose
and artifact drift apart silently; a test is the only thing that notices. These
run against the committed export, so a stale README fails CI rather than
reaching a reader.
"""
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "site" / "data" / "run-8.json"

pytestmark = pytest.mark.skipif(
    not ARTIFACT.exists(), reason="no published artifact in this checkout")


@pytest.fixture(scope="module")
def published():
    return json.loads(ARTIFACT.read_text())


@pytest.fixture(scope="module")
def docs():
    return {name: (ROOT / name).read_text()
            for name in ("README.md", "SURVEILLANCE_FRAMEWORK.md")}


def _row(control, counts):
    return "| {} | {} | {} | {} | {} |".format(control, *counts)


@pytest.mark.parametrize("control", ["C1", "C3", "C4", "C5"])
def test_every_document_states_the_exported_per_control_result(published, docs, control):
    r = published["funnel"]["by_control"][control]
    row = _row(control, (r["generated"], r["no_action"], r["monitor"], r["escalated"]))
    for name, text in docs.items():
        assert row in text, "{} does not state {}'s exported result: {}".format(
            name, control, row)


def test_every_document_states_the_exported_total(published, docs):
    f = published["funnel"]
    row = "| **Total** | **{}** | **{}** | **{}** | **{}** |".format(
        f["generated"], f["no_action"], f["monitor"], f["escalated"])
    for name, text in docs.items():
        assert row in text, "{} does not state the exported total: {}".format(name, row)


def test_published_run_is_complete(published):
    run = published["run"]
    assert run["status"] == "complete"
    assert run["controls_complete"] == run["controls_expected"]


def test_published_run_was_not_exported_from_a_drifted_tree(published):
    """A result published under a code fingerprint the tree does not match
    misdescribes what produced it."""
    assert published["run"]["code_drift"] is False
    assert published["run"]["source_commit"]


def test_every_published_alert_carries_a_written_rationale(published):
    """An alert without reasoning is a number, not a surveillance record."""
    for a in published["alerts"]:
        assert a["disposition"], "alert {} is published untriaged".format(a["alert_id"])
        assert a["disposition"]["rationale"].strip(), \
            "alert {} has an empty rationale".format(a["alert_id"])


def test_funnel_arithmetic_closes(published):
    f = published["funnel"]
    assert f["no_action"] + f["monitor"] + f["escalated"] == f["triaged"]
    assert f["triaged"] + f["untriaged"] == f["generated"]
    assert sum(c["generated"] for c in f["by_control"].values()) == f["generated"]


def test_artifact_carries_no_raw_market_data(published):
    """Derived results are published; Kalshi's raw tape is not."""
    blob = json.dumps(published)
    for field in ("trade_id", "yes_bid_close", "open_interest_fp", "count_fp"):
        assert field not in blob


def test_coverage_figures_appear_in_the_readme(published):
    readme = (ROOT / "README.md").read_text()
    assert "{} of 408".format(published["coverage"]["C1"]["scored"]) in readme
    assert "{:,} scoreable".format(published["coverage"]["C3"]["scoreable"]) in readme


def test_viewer_reads_the_key_set_the_exporter_writes(published):
    """The page and the artifact share one contract; keep them in one place."""
    app = (ROOT / "site" / "app.js").read_text()
    for key in ("funnel", "coverage", "executions", "alerts", "disclaimer", "corpus"):
        assert 'doc.' + key in app or '"' + key + '"' in app
        assert key in published
