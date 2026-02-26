"""Tests for LangSmith quality metrics: evaluators (DD-087) and metadata extraction (DD-085).

Merged from test_langsmith_evaluators.py and test_langsmith_metadata.py.
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
from flowise_dev_agent.util.langsmith.metadata import (
    extract_outcome_tags,
    extract_session_metadata,
)


# ===========================================================================
# Part 1 — Evaluators (from test_langsmith_evaluators.py)
# ===========================================================================


# ---------------------------------------------------------------------------
# compile_success
# ---------------------------------------------------------------------------


class TestCompileSuccess:
    @pytest.mark.parametrize(
        "state",
        [
            pytest.param(
                {"chatflow_id": "abc-123", "done": True, "converge_verdict": {"verdict": "DONE"}},
                id="full_success",
            ),
            pytest.param(
                {"chatflow_id": "abc", "done": True},
                id="missing_verdict_defaults_ok",
            ),
        ],
    )
    def test_success_cases(self, state):
        r = compile_success(state)
        assert r["key"] == "compile_success"
        assert r["score"] == 1.0

    @pytest.mark.parametrize(
        "state",
        [
            pytest.param(
                {"chatflow_id": None, "done": True, "converge_verdict": {"verdict": "DONE"}},
                id="no_chatflow_id",
            ),
            pytest.param(
                {"chatflow_id": "abc", "done": False, "converge_verdict": {"verdict": "DONE"}},
                id="not_done",
            ),
            pytest.param(
                {"chatflow_id": "abc", "done": True, "converge_verdict": {"verdict": "ITERATE"}},
                id="iterate_verdict",
            ),
            pytest.param(
                {},
                id="empty_state",
            ),
        ],
    )
    def test_failure_cases(self, state):
        assert compile_success(state)["score"] == 0.0


# ---------------------------------------------------------------------------
# intent_confidence
# ---------------------------------------------------------------------------


class TestIntentConfidence:
    @pytest.mark.parametrize(
        "state, kwargs, expected_score, comment_substring",
        [
            pytest.param(
                {"intent_confidence": 0.95}, {}, 0.95, None,
                id="high_confidence",
            ),
            pytest.param(
                {"intent_confidence": 0.3}, {}, 0.3, None,
                id="low_confidence",
            ),
            pytest.param(
                {}, {}, 0.0, None,
                id="missing",
            ),
            pytest.param(
                {"intent_confidence": 0.5}, {"threshold": 0.8}, 0.5, "threshold=0.8",
                id="custom_threshold",
            ),
        ],
    )
    def test_intent_confidence(self, state, kwargs, expected_score, comment_substring):
        r = intent_confidence(state, **kwargs)
        assert r["key"] == "intent_confidence"
        assert r["score"] == expected_score
        if comment_substring is not None:
            assert comment_substring in r["comment"]


# ---------------------------------------------------------------------------
# iteration_efficiency
# ---------------------------------------------------------------------------


class TestIterationEfficiency:
    @pytest.mark.parametrize(
        "state, kwargs",
        [
            pytest.param(
                {"done": True, "iteration": 1}, {},
                id="done_in_one",
            ),
            pytest.param(
                {"done": True, "iteration": 3}, {},
                id="done_in_three",
            ),
            pytest.param(
                {"done": True, "iteration": 5}, {"max_iterations": 5},
                id="custom_max",
            ),
        ],
    )
    def test_success_cases(self, state, kwargs):
        r = iteration_efficiency(state, **kwargs)
        assert r["score"] == 1.0

    @pytest.mark.parametrize(
        "state",
        [
            pytest.param(
                {"done": True, "iteration": 4},
                id="done_in_four_exceeds_default",
            ),
            pytest.param(
                {"done": False, "iteration": 1},
                id="not_done",
            ),
            pytest.param(
                {},
                id="empty_state",
            ),
        ],
    )
    def test_failure_cases(self, state):
        r = iteration_efficiency(state)
        assert r["score"] == 0.0


# ---------------------------------------------------------------------------
# token_budget  (kept as-is — each case has distinct state structure)
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
    @pytest.mark.parametrize(
        "plan, expected_score",
        [
            pytest.param(
                (
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
                ),
                1.0,
                id="complete_plan",
            ),
            pytest.param(
                (
                    "## GOAL\n## INPUTS\n## OUTPUTS\n## CONSTRAINTS\n"
                    "## SUCCESS CRITERIA\n## PATTERN\n## ACTION\n"
                ),
                pytest.approx(0.7, abs=0.01),
                id="sections_only",
            ),
        ],
    )
    def test_complete_plans(self, plan, expected_score):
        r = plan_quality({"plan": plan})
        assert r["score"] == expected_score

    @pytest.mark.parametrize(
        "state, check_score_zero, check_partial",
        [
            pytest.param({"plan": ""}, True, False, id="empty_plan"),
            pytest.param({}, True, False, id="no_plan"),
            pytest.param(
                {"plan": "## GOAL\nDo something\n## ACTION\nCREATE\n"},
                False, True,
                id="partial_plan",
            ),
        ],
    )
    def test_partial_or_missing_plans(self, state, check_score_zero, check_partial):
        r = plan_quality(state)
        if check_score_zero:
            assert r["score"] == 0.0
        if check_partial:
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


# ===========================================================================
# Part 2 — Metadata extraction (from test_langsmith_metadata.py)
# ===========================================================================


def _make_state(**overrides) -> dict:
    """Build a minimal AgentState-like dict with sensible defaults."""
    base = {
        "operation_mode": "create",
        "intent_confidence": 0.85,
        "iteration": 2,
        "pattern_used": True,
        "pattern_id": 7,
        "runtime_mode": "capability_first",
        "done": True,
        "total_input_tokens": 5000,
        "total_output_tokens": 1200,
        "facts": {
            "flowise": {
                "schema_fingerprint": "abc123",
                "prior_schema_fingerprint": "abc123",
            }
        },
        "debug": {
            "flowise": {
                "phase_metrics": [
                    {
                        "phase": "discover",
                        "duration_ms": 1500.0,
                        "input_tokens": 2000,
                        "output_tokens": 500,
                        "tool_call_count": 3,
                        "cache_hits": 10,
                        "repair_events": 1,
                    },
                    {
                        "phase": "patch",
                        "duration_ms": 3200.0,
                        "input_tokens": 3000,
                        "output_tokens": 700,
                        "tool_call_count": 5,
                        "cache_hits": 8,
                        "repair_events": 0,
                    },
                ],
                "pattern_metrics": {
                    "pattern_used": True,
                    "pattern_id": 7,
                    "ops_in_base": 4,
                },
            }
        },
        "converge_verdict": {
            "verdict": "DONE",
            "category": None,
            "reason": "All tests pass, DoD met.",
            "fixes": [],
        },
    }
    base.update(overrides)
    return base


class TestExtractSessionMetadata:
    def test_full_state(self):
        meta = extract_session_metadata(_make_state())

        assert meta["agent.operation_mode"] == "create"
        assert meta["agent.intent_confidence"] == 0.85
        assert meta["agent.iteration"] == 2
        assert meta["agent.pattern_used"] is True
        assert meta["agent.pattern_id"] == 7
        assert meta["agent.runtime_mode"] == "capability_first"
        assert meta["agent.done"] is True

    def test_token_totals(self):
        meta = extract_session_metadata(_make_state())
        assert meta["telemetry.total_input_tokens"] == 5000
        assert meta["telemetry.total_output_tokens"] == 1200

    def test_schema_no_drift(self):
        meta = extract_session_metadata(_make_state())
        assert meta["telemetry.schema_fingerprint"] == "abc123"
        assert meta["telemetry.drift_detected"] is False

    def test_schema_drift_detected(self):
        state = _make_state()
        state["facts"]["flowise"]["prior_schema_fingerprint"] = "old_fp"
        state["facts"]["flowise"]["schema_fingerprint"] = "new_fp"
        meta = extract_session_metadata(state)
        assert meta["telemetry.drift_detected"] is True

    def test_phase_metrics(self):
        meta = extract_session_metadata(_make_state())
        assert meta["telemetry.total_phases_timed"] == 2
        assert meta["telemetry.total_repair_events"] == 1
        assert meta["telemetry.phase_ms.discover"] == 1500.0
        assert meta["telemetry.phase_ms.patch"] == 3200.0

    def test_pattern_metrics(self):
        meta = extract_session_metadata(_make_state())
        assert meta["pattern.pattern_used"] is True
        assert meta["pattern.pattern_id"] == 7
        assert meta["pattern.ops_in_base"] == 4

    def test_converge_verdict(self):
        meta = extract_session_metadata(_make_state())
        assert meta["verdict.value"] == "DONE"
        assert meta["verdict.category"] == ""
        assert "All tests pass" in meta["verdict.reason"]

    def test_verdict_with_category(self):
        state = _make_state()
        state["converge_verdict"] = {
            "verdict": "ITERATE",
            "category": "STRUCTURE",
            "reason": "Missing terminal node",
            "fixes": ["Add conversationalAgent node"],
        }
        meta = extract_session_metadata(state)
        assert meta["verdict.value"] == "ITERATE"
        assert meta["verdict.category"] == "STRUCTURE"

    def test_empty_state(self):
        """Gracefully handles a completely empty state dict."""
        meta = extract_session_metadata({})
        assert meta["agent.operation_mode"] == "unknown"
        assert meta["agent.intent_confidence"] == 0.0
        assert meta["agent.iteration"] == 0
        assert meta["agent.done"] is False
        assert meta["telemetry.total_input_tokens"] == 0
        assert meta["telemetry.total_phases_timed"] == 0

    def test_missing_debug_and_facts(self):
        """Handles state with no debug or facts keys."""
        state = {"operation_mode": "update", "iteration": 1, "done": False}
        meta = extract_session_metadata(state)
        assert meta["agent.operation_mode"] == "update"
        assert meta["telemetry.total_phases_timed"] == 0
        assert "pattern.pattern_used" not in meta  # no pattern_metrics

    def test_verdict_reason_truncated(self):
        state = _make_state()
        state["converge_verdict"]["reason"] = "x" * 500
        meta = extract_session_metadata(state)
        assert len(meta["verdict.reason"]) == 200


class TestExtractOutcomeTags:
    def test_completed_create_with_pattern(self):
        tags = extract_outcome_tags(_make_state())
        assert "outcome:completed" in tags
        assert "mode:create" in tags
        assert "pattern:reused" in tags
        assert "iterations:2-3" in tags

    def test_incomplete(self):
        tags = extract_outcome_tags(_make_state(done=False))
        assert "outcome:incomplete" in tags
        assert "outcome:completed" not in tags

    def test_single_iteration(self):
        tags = extract_outcome_tags(_make_state(iteration=1))
        assert "iterations:1" in tags

    def test_many_iterations(self):
        tags = extract_outcome_tags(_make_state(iteration=5))
        assert "iterations:4+" in tags

    def test_update_mode(self):
        tags = extract_outcome_tags(_make_state(operation_mode="update"))
        assert "mode:update" in tags

    def test_no_pattern(self):
        tags = extract_outcome_tags(_make_state(pattern_used=False))
        assert "pattern:reused" not in tags
