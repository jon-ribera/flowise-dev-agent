"""Tests for Milestone 9.7: Telemetry and Drift Polish.

Covers the acceptance tests from the M9.7 deliverables:
  1. SessionSummary.schema_fingerprint populated from facts["flowise"]["schema_fingerprint"].
  2. SessionSummary.drift_detected = True when current fingerprint != prior fingerprint.
  3. SessionSummary.drift_detected = False when fingerprints match.
  4. SessionSummary.drift_detected = False when prior_schema_fingerprint is absent.
  5. SessionSummary.pattern_metrics populated from debug["flowise"]["pattern_metrics"].
  6. SessionSummary.phase_durations_ms dict contains phase names from phase_metrics.

These tests are pure unit tests — no live server, Postgres, or Flowise API needed.
The SessionSummary extraction logic is tested by constructing the same state dicts
that list_sessions() receives from the LangGraph snapshot and invoking the same
extraction expressions used in api.py.
"""

from __future__ import annotations

import json

import pytest

from flowise_dev_agent.api import SessionSummary


# ---------------------------------------------------------------------------
# Helpers: simulate the extraction logic from list_sessions()
# ---------------------------------------------------------------------------


def _build_summary(state: dict) -> SessionSummary:
    """Replicate the SessionSummary construction logic from list_sessions().

    This mirrors the extraction logic in api.py::list_sessions() so that the
    tests exercise the same field mapping without requiring a live HTTP server.
    """
    _flowise_debug: dict = (state.get("debug") or {}).get("flowise", {}) or {}
    _phase_metrics: list = _flowise_debug.get("phase_metrics") or []
    _repair_events = sum(
        m.get("repair_events", 0)
        for m in _phase_metrics
        if isinstance(m, dict)
    )
    _kr_events: list = _flowise_debug.get("knowledge_repair_events") or []
    _knowledge_repair_count = len(_kr_events)
    _get_node_calls: int = _flowise_debug.get("get_node_calls_total", 0) or 0
    # M8.2: phase_durations_ms (confirmed correct — phase name → last duration)
    _phase_durations: dict[str, float] = {
        m["phase"]: m.get("duration_ms", 0.0)
        for m in _phase_metrics
        if isinstance(m, dict) and "phase" in m
    }
    # M9.7: schema_fingerprint + drift_detected
    _flowise_facts: dict = (state.get("facts") or {}).get("flowise", {}) or {}
    _schema_fp: str | None = _flowise_facts.get("schema_fingerprint")
    _prior_fp: str | None = _flowise_facts.get("prior_schema_fingerprint")
    _drift_detected: bool = bool(
        _schema_fp and _prior_fp and _schema_fp != _prior_fp
    )
    # M9.7: pattern_metrics from debug["flowise"]["pattern_metrics"]
    _pattern_metrics: dict | None = _flowise_debug.get("pattern_metrics") or None

    return SessionSummary(
        thread_id=state.get("thread_id", "test-thread"),
        status=state.get("status", "completed"),
        iteration=state.get("iteration", 0),
        chatflow_id=state.get("chatflow_id"),
        total_input_tokens=state.get("total_input_tokens", 0) or 0,
        total_output_tokens=state.get("total_output_tokens", 0) or 0,
        session_name=state.get("session_name"),
        runtime_mode=state.get("runtime_mode"),
        total_repair_events=_repair_events,
        total_phases_timed=len(_phase_metrics),
        knowledge_repair_count=_knowledge_repair_count,
        get_node_calls_total=_get_node_calls,
        phase_durations_ms=_phase_durations,
        schema_fingerprint=_schema_fp,
        drift_detected=_drift_detected,
        pattern_metrics=_pattern_metrics,
    )


# ---------------------------------------------------------------------------
# Test 1 — schema_fingerprint populated from facts["flowise"]["schema_fingerprint"]
# ---------------------------------------------------------------------------


class TestSessionSummarySchemaFingerprint:

    def test_session_summary_has_schema_fingerprint(self):
        """SessionSummary.schema_fingerprint reads from facts["flowise"]["schema_fingerprint"]."""
        state = {
            "facts": {
                "flowise": {
                    "schema_fingerprint": "abc123fingerprint",
                }
            }
        }
        summary = _build_summary(state)
        assert summary.schema_fingerprint == "abc123fingerprint"

    def test_session_summary_schema_fingerprint_none_when_absent(self):
        """When facts["flowise"]["schema_fingerprint"] is absent, field is None."""
        state = {"facts": {"flowise": {}}}
        summary = _build_summary(state)
        assert summary.schema_fingerprint is None

    def test_session_summary_schema_fingerprint_none_when_no_facts(self):
        """When facts is empty/absent, schema_fingerprint is None."""
        state = {}
        summary = _build_summary(state)
        assert summary.schema_fingerprint is None

    def test_session_summary_schema_fingerprint_field_exists_on_model(self):
        """SessionSummary model must declare the schema_fingerprint field."""
        s = SessionSummary(thread_id="t1", status="completed")
        assert hasattr(s, "schema_fingerprint")
        assert s.schema_fingerprint is None  # default

    def test_session_summary_schema_fingerprint_json_serialisable(self):
        """SessionSummary with schema_fingerprint must be JSON-serialisable."""
        s = SessionSummary(
            thread_id="t1",
            status="completed",
            schema_fingerprint="deadbeef1234",
        )
        json.dumps(s.model_dump())  # must not raise


# ---------------------------------------------------------------------------
# Test 2 — drift_detected = True when fingerprints differ
# ---------------------------------------------------------------------------


class TestDriftDetectedWhenFingerprintsDiffer:

    def test_session_summary_drift_detected_when_fingerprints_differ(self):
        """drift_detected is True when current != prior schema fingerprint."""
        state = {
            "facts": {
                "flowise": {
                    "schema_fingerprint": "new-fp-xyz",
                    "prior_schema_fingerprint": "old-fp-abc",
                }
            }
        }
        summary = _build_summary(state)
        assert summary.drift_detected is True

    def test_drift_detected_true_sets_schema_fingerprint_correctly(self):
        """When drift detected, schema_fingerprint reflects the current value."""
        state = {
            "facts": {
                "flowise": {
                    "schema_fingerprint": "fp-v2",
                    "prior_schema_fingerprint": "fp-v1",
                }
            }
        }
        summary = _build_summary(state)
        assert summary.schema_fingerprint == "fp-v2"
        assert summary.drift_detected is True


# ---------------------------------------------------------------------------
# Test 3 — drift_detected = False when fingerprints match
# ---------------------------------------------------------------------------


class TestDriftNotDetectedWhenFingerprintsSame:

    def test_session_summary_drift_not_detected_when_same(self):
        """drift_detected is False when current fingerprint == prior fingerprint."""
        fp = "stable-fingerprint-0001"
        state = {
            "facts": {
                "flowise": {
                    "schema_fingerprint": fp,
                    "prior_schema_fingerprint": fp,
                }
            }
        }
        summary = _build_summary(state)
        assert summary.drift_detected is False

    def test_drift_not_detected_schema_fingerprint_still_populated(self):
        """schema_fingerprint is present even when no drift detected."""
        fp = "same-fp"
        state = {
            "facts": {
                "flowise": {
                    "schema_fingerprint": fp,
                    "prior_schema_fingerprint": fp,
                }
            }
        }
        summary = _build_summary(state)
        assert summary.schema_fingerprint == fp
        assert summary.drift_detected is False


# ---------------------------------------------------------------------------
# Test 4 — drift_detected = False when prior_schema_fingerprint is absent
# ---------------------------------------------------------------------------


class TestDriftFalseWhenNoPrior:

    def test_session_summary_drift_false_when_no_prior(self):
        """drift_detected is False when prior_schema_fingerprint is not present."""
        state = {
            "facts": {
                "flowise": {
                    "schema_fingerprint": "current-fp",
                    # prior_schema_fingerprint intentionally absent
                }
            }
        }
        summary = _build_summary(state)
        assert summary.drift_detected is False

    def test_drift_false_when_prior_is_none(self):
        """drift_detected is False when prior_schema_fingerprint is explicitly None."""
        state = {
            "facts": {
                "flowise": {
                    "schema_fingerprint": "current-fp",
                    "prior_schema_fingerprint": None,
                }
            }
        }
        summary = _build_summary(state)
        assert summary.drift_detected is False

    def test_drift_false_when_no_facts_at_all(self):
        """drift_detected defaults to False when state has no facts."""
        summary = _build_summary({})
        assert summary.drift_detected is False

    def test_drift_detected_field_exists_on_model(self):
        """SessionSummary model must declare the drift_detected field."""
        s = SessionSummary(thread_id="t1", status="completed")
        assert hasattr(s, "drift_detected")
        assert s.drift_detected is False  # default


# ---------------------------------------------------------------------------
# Test 5 — pattern_metrics populated from debug["flowise"]["pattern_metrics"]
# ---------------------------------------------------------------------------


class TestPatternMetricsIncluded:

    def test_session_summary_pattern_metrics_included(self):
        """pattern_metrics is populated from debug["flowise"]["pattern_metrics"]."""
        pm = {"pattern_used": True, "pattern_id": 7, "ops_in_base": 4}
        state = {
            "debug": {
                "flowise": {
                    "pattern_metrics": pm,
                }
            }
        }
        summary = _build_summary(state)
        assert summary.pattern_metrics == pm

    def test_pattern_metrics_none_when_absent(self):
        """pattern_metrics is None when debug["flowise"]["pattern_metrics"] is absent."""
        state = {"debug": {"flowise": {}}}
        summary = _build_summary(state)
        assert summary.pattern_metrics is None

    def test_pattern_metrics_none_when_no_debug(self):
        """pattern_metrics is None when debug state is absent."""
        summary = _build_summary({})
        assert summary.pattern_metrics is None

    def test_pattern_metrics_field_exists_on_model(self):
        """SessionSummary model must declare the pattern_metrics field."""
        s = SessionSummary(thread_id="t1", status="completed")
        assert hasattr(s, "pattern_metrics")
        assert s.pattern_metrics is None  # default

    def test_pattern_metrics_json_serialisable(self):
        """SessionSummary with pattern_metrics dict must be JSON-serialisable."""
        s = SessionSummary(
            thread_id="t1",
            status="completed",
            pattern_metrics={"pattern_used": False, "pattern_id": None, "ops_in_base": 0},
        )
        json.dumps(s.model_dump())  # must not raise


# ---------------------------------------------------------------------------
# Test 6 — phase_durations_ms populated from debug["flowise"]["phase_metrics"]
# ---------------------------------------------------------------------------


class TestPhaseDurationsPopulatedFromPhaseMetrics:

    def test_phase_durations_populated_from_phase_metrics(self):
        """phase_durations_ms dict contains phase names from debug["flowise"]["phase_metrics"]."""
        state = {
            "debug": {
                "flowise": {
                    "phase_metrics": [
                        {"phase": "discover", "duration_ms": 1200.5,
                         "start_ts": 0.0, "end_ts": 1.2},
                        {"phase": "patch_b", "duration_ms": 800.0,
                         "start_ts": 1.2, "end_ts": 2.0},
                        {"phase": "patch_d", "duration_ms": 350.25,
                         "start_ts": 2.0, "end_ts": 2.35},
                    ]
                }
            }
        }
        summary = _build_summary(state)
        assert "discover" in summary.phase_durations_ms
        assert "patch_b" in summary.phase_durations_ms
        assert "patch_d" in summary.phase_durations_ms
        assert summary.phase_durations_ms["discover"] == 1200.5
        assert summary.phase_durations_ms["patch_b"] == 800.0
        assert summary.phase_durations_ms["patch_d"] == 350.25

    def test_phase_durations_empty_when_no_phase_metrics(self):
        """phase_durations_ms is empty dict when phase_metrics is absent."""
        summary = _build_summary({})
        assert summary.phase_durations_ms == {}

    def test_phase_durations_uses_last_value_for_duplicate_phase(self):
        """When the same phase appears twice, the later entry's duration wins."""
        state = {
            "debug": {
                "flowise": {
                    "phase_metrics": [
                        {"phase": "patch_d", "duration_ms": 300.0,
                         "start_ts": 0.0, "end_ts": 0.3},
                        {"phase": "patch_d", "duration_ms": 450.0,
                         "start_ts": 1.0, "end_ts": 1.45},
                    ]
                }
            }
        }
        summary = _build_summary(state)
        # Dict comprehension in list_sessions() uses the last value for duplicate keys
        assert summary.phase_durations_ms["patch_d"] == 450.0

    def test_total_phases_timed_matches_phase_metrics_length(self):
        """total_phases_timed equals the number of entries in phase_metrics."""
        state = {
            "debug": {
                "flowise": {
                    "phase_metrics": [
                        {"phase": "discover", "duration_ms": 100.0,
                         "start_ts": 0.0, "end_ts": 0.1},
                        {"phase": "patch_b", "duration_ms": 200.0,
                         "start_ts": 0.1, "end_ts": 0.3},
                    ]
                }
            }
        }
        summary = _build_summary(state)
        assert summary.total_phases_timed == 2
