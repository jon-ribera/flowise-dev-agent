"""Tests for flowise_dev_agent.util.langsmith.metadata (DD-085).

Verifies extraction of session telemetry into flat LangSmith metadata dicts.
"""

from __future__ import annotations

import pytest

from flowise_dev_agent.util.langsmith.metadata import (
    extract_outcome_tags,
    extract_session_metadata,
)


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
