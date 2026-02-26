"""Tests for flowise_dev_agent.util.langsmith.evaluators (DD-087).

All evaluators are pure functions — no mocking needed.
"""

from __future__ import annotations

import pytest

from flowise_dev_agent.util.langsmith.evaluators import (
    ALL_EVALUATORS,
    compile_success,
    intent_confidence,
    iteration_efficiency,
    plan_quality,
    token_budget,
)


# ---------------------------------------------------------------------------
# compile_success
# ---------------------------------------------------------------------------


class TestCompileSuccess:
    def test_full_success(self):
        state = {
            "chatflow_id": "abc-123",
            "done": True,
            "converge_verdict": {"verdict": "DONE"},
        }
        r = compile_success(state)
        assert r["key"] == "compile_success"
        assert r["score"] == 1.0

    def test_no_chatflow_id(self):
        state = {"chatflow_id": None, "done": True, "converge_verdict": {"verdict": "DONE"}}
        assert compile_success(state)["score"] == 0.0

    def test_not_done(self):
        state = {"chatflow_id": "abc", "done": False, "converge_verdict": {"verdict": "DONE"}}
        assert compile_success(state)["score"] == 0.0

    def test_iterate_verdict(self):
        state = {
            "chatflow_id": "abc",
            "done": True,
            "converge_verdict": {"verdict": "ITERATE"},
        }
        assert compile_success(state)["score"] == 0.0

    def test_missing_verdict(self):
        state = {"chatflow_id": "abc", "done": True}
        # No verdict dict — verdict_ok defaults to True (not ITERATE)
        assert compile_success(state)["score"] == 1.0

    def test_empty_state(self):
        assert compile_success({})["score"] == 0.0


# ---------------------------------------------------------------------------
# intent_confidence
# ---------------------------------------------------------------------------


class TestIntentConfidence:
    def test_high_confidence(self):
        r = intent_confidence({"intent_confidence": 0.95})
        assert r["score"] == 0.95
        assert r["key"] == "intent_confidence"

    def test_low_confidence(self):
        r = intent_confidence({"intent_confidence": 0.3})
        assert r["score"] == 0.3

    def test_missing(self):
        r = intent_confidence({})
        assert r["score"] == 0.0

    def test_custom_threshold_in_comment(self):
        r = intent_confidence({"intent_confidence": 0.5}, threshold=0.8)
        assert "threshold=0.8" in r["comment"]


# ---------------------------------------------------------------------------
# iteration_efficiency
# ---------------------------------------------------------------------------


class TestIterationEfficiency:
    def test_done_in_one(self):
        r = iteration_efficiency({"done": True, "iteration": 1})
        assert r["score"] == 1.0

    def test_done_in_three(self):
        r = iteration_efficiency({"done": True, "iteration": 3})
        assert r["score"] == 1.0

    def test_done_in_four(self):
        r = iteration_efficiency({"done": True, "iteration": 4})
        assert r["score"] == 0.0

    def test_not_done(self):
        r = iteration_efficiency({"done": False, "iteration": 1})
        assert r["score"] == 0.0

    def test_custom_max(self):
        r = iteration_efficiency({"done": True, "iteration": 5}, max_iterations=5)
        assert r["score"] == 1.0

    def test_empty_state(self):
        r = iteration_efficiency({})
        assert r["score"] == 0.0


# ---------------------------------------------------------------------------
# token_budget
# ---------------------------------------------------------------------------


class TestTokenBudget:
    def test_within_budget(self):
        state = {
            "debug": {
                "flowise": {
                    "phase_metrics": [
                        {"phase": "discover", "input_tokens": 5000, "output_tokens": 1000},
                        {"phase": "patch", "input_tokens": 8000, "output_tokens": 2000},
                    ]
                }
            }
        }
        r = token_budget(state)
        assert r["score"] == 1.0
        assert "all phases within budget" in r["comment"]

    def test_one_violation(self):
        state = {
            "debug": {
                "flowise": {
                    "phase_metrics": [
                        {"phase": "discover", "input_tokens": 14000, "output_tokens": 2000},  # 16k > 15k
                        {"phase": "patch", "input_tokens": 5000, "output_tokens": 1000},
                    ]
                }
            }
        }
        r = token_budget(state)
        assert r["score"] == 0.5  # 1 violation / 2 phases = 0.5

    def test_all_violations(self):
        state = {
            "debug": {
                "flowise": {
                    "phase_metrics": [
                        {"phase": "discover", "input_tokens": 20000, "output_tokens": 0},
                        {"phase": "plan", "input_tokens": 20000, "output_tokens": 0},
                    ]
                }
            }
        }
        r = token_budget(state)
        assert r["score"] == 0.0

    def test_empty_metrics(self):
        r = token_budget({})
        assert r["score"] == 1.0  # no phases = no violations

    def test_unknown_phase_uses_default_budget(self):
        state = {
            "debug": {
                "flowise": {
                    "phase_metrics": [
                        {"phase": "custom_step", "input_tokens": 24000, "output_tokens": 0},
                    ]
                }
            }
        }
        r = token_budget(state)
        assert r["score"] == 1.0  # 24k < 25k default


# ---------------------------------------------------------------------------
# plan_quality
# ---------------------------------------------------------------------------


class TestPlanQuality:
    def test_complete_plan(self):
        plan = (
            "## GOAL\nBuild a RAG chatflow.\n"
            "## INPUTS\nUser queries\n"
            "## OUTPUTS\nAssistant response\n"
            "## CONSTRAINTS\nMust use OpenAI\n"
            "## SUCCESS CRITERIA\nTests pass\n"
            "## PATTERN\nRAG template\n"
            "## ACTION\nCREATE\n"
            "## DOMAINS\nflowise\n"
            "## CREDENTIALS\nopenAIApi\n"
            "## DATA_CONTRACTS\nnone\n"
        )
        r = plan_quality({"plan": plan})
        assert r["score"] == 1.0

    def test_sections_only(self):
        plan = (
            "## GOAL\n## INPUTS\n## OUTPUTS\n## CONSTRAINTS\n"
            "## SUCCESS CRITERIA\n## PATTERN\n## ACTION\n"
        )
        r = plan_quality({"plan": plan})
        assert r["score"] == pytest.approx(0.7, abs=0.01)

    def test_empty_plan(self):
        r = plan_quality({"plan": ""})
        assert r["score"] == 0.0

    def test_no_plan(self):
        r = plan_quality({})
        assert r["score"] == 0.0

    def test_partial_plan(self):
        plan = "## GOAL\nDo something\n## ACTION\nCREATE\n"
        r = plan_quality({"plan": plan})
        assert 0.0 < r["score"] < 1.0
        assert "missing" in r["comment"]


# ---------------------------------------------------------------------------
# ALL_EVALUATORS
# ---------------------------------------------------------------------------


class TestAllEvaluators:
    def test_registry_has_five(self):
        assert len(ALL_EVALUATORS) == 5

    def test_all_return_valid_dicts(self):
        state = {"done": True, "chatflow_id": "x", "iteration": 1, "intent_confidence": 0.9}
        for eval_fn in ALL_EVALUATORS:
            result = eval_fn(state)
            assert "key" in result
            assert "score" in result
            assert "comment" in result
            assert isinstance(result["score"], (int, float))
