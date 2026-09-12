import copy

from kxsurv.case_evidence import render_supplement
from kxsurv.params import params_hash
from tests.fixtures import trade

P = {"version": "case-test", "c1_prerelease": {"window_minutes": 120, "null_windows": 3}}


class PublicTape:
    def trades(self, **kwargs):
        assert kwargs["ticker"] == "K1"
        return [trade("current", "K1", "2026-08-12T12:00:00.500Z", 100, .2),
                trade("n1", "K1", "2026-08-12T11:00:00Z", 100, .9),
                trade("n2", "K1", "2026-08-12T09:00:00Z", 100, .9),
                trade("n3", "K1", "2026-08-12T07:00:00Z", 100, .9)]


def artifact(score=.8):
    return {"run": {"run_id": 1, "source_commit": "abc", "params_hash": params_hash(P)},
            "alerts": [{"alert_id": 1, "control_id": "C1", "target": "K1",
                        "window_start": "2026-08-12T12:00:00Z",
                        "window_end": "2026-08-12T14:00:00Z", "score": score, "percentile": 100,
                        "evidence": {"surprise_price": "per-trade execution price",
                                     "settled": "yes", "trade_count": 1, "window_volume": 100,
                                     "null_samples": 3, "halt_to_release_minutes": 1}}]}


def test_retrieved_trade_contributions_reconcile_with_published_summary():
    report = render_supplement(artifact(), 1, P, PublicTape())
    assert "| C1 score | 0.8 | 0.8 | yes |" in report
    assert "| Non-empty comparison windows | 3 | 3 | yes |" in report
    assert "2026-08-12T12:00:00.500Z | 100.00 | 0.2000 | yes | 0.8000 | 0.80000000" in report


def test_retrieval_difference_is_explicit_and_never_rewrites_the_original():
    original = artifact(score=.9)
    before = copy.deepcopy(original)
    report = render_supplement(original, 1, P, PublicTape())
    assert "| C1 score | 0.9 | 0.8 | NO — investigate difference |" in report
    assert original == before
