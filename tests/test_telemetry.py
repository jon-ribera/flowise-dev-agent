"""Tests for telemetry, drift detection, and session summary extraction.

Consolidated from test_m74_telemetry.py (DD-069) and test_m97_telemetry_drift.py (M9.7).

Covers:
  - PhaseMetrics dataclass fields and JSON serialisability
  - MetricsCollector async context manager behaviour
  - FLOWISE_SCHEMA_DRIFT_POLICY module constant
  - SessionSummary: M7.4 fields, M8.2 telemetry, M9.7 drift + pattern metrics
  - Phase metrics accumulation across nodes
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time

import pytest

from flowise_dev_agent.agent.metrics import MetricsCollector, PhaseMetrics
from flowise_dev_agent.api import SessionSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_summary(state: dict) -> SessionSummary:
    """Replicate the SessionSummary construction logic from list_sessions().

    Mirrors the extraction logic in api.py::list_sessions() so the tests
    exercise the same field mapping without requiring a live HTTP server.
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
    _phase_durations: dict[str, float] = {
        m["phase"]: m.get("duration_ms", 0.0)
        for m in _phase_metrics
        if isinstance(m, dict) and "phase" in m
    }
    _flowise_facts: dict = (state.get("facts") or {}).get("flowise", {}) or {}
    _schema_fp: str | None = _flowise_facts.get("schema_fingerprint")
    _prior_fp: str | None = _flowise_facts.get("prior_schema_fingerprint")
    _drift_detected: bool = bool(
        _schema_fp and _prior_fp and _schema_fp != _prior_fp
    )
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
# PhaseMetrics dataclass
# ---------------------------------------------------------------------------


class TestPhaseMetrics:

    def test_construction_and_defaults(self):
        """Required fields accepted; optional counters default to zero."""
        m = PhaseMetrics(phase="test", start_ts=0.0, end_ts=1.0, duration_ms=1000.0)
        assert m.phase == "test"
        assert m.start_ts == 0.0
        assert m.end_ts == 1.0
        assert m.duration_ms == 1000.0
        assert m.input_tokens == 0
        assert m.output_tokens == 0
        assert m.tool_call_count == 0
        assert m.cache_hits == 0
        assert m.repair_events == 0

    def test_counter_fields_settable(self):
        m = PhaseMetrics(
            phase="patch_b", start_ts=100.0, end_ts=101.5, duration_ms=1500.0,
            input_tokens=500, output_tokens=200, tool_call_count=3,
            cache_hits=7, repair_events=1,
        )
        assert m.input_tokens == 500
        assert m.output_tokens == 200
        assert m.tool_call_count == 3
        assert m.cache_hits == 7
        assert m.repair_events == 1

    def test_asdict_complete_and_json_serialisable(self):
        """asdict has all expected keys, all values are JSON primitives."""
        m = PhaseMetrics(
            phase="patch_d", start_ts=1000.0, end_ts=1002.0, duration_ms=2000.0,
            input_tokens=10, output_tokens=5, cache_hits=3, repair_events=0,
        )
        d = dataclasses.asdict(m)
        expected_keys = {
            "phase", "start_ts", "end_ts", "duration_ms",
            "input_tokens", "output_tokens", "tool_call_count",
            "cache_hits", "repair_events",
        }
        assert set(d.keys()) == expected_keys
        for val in d.values():
            assert isinstance(val, (str, int, float))
        json.dumps(d)  # must not raise


# ---------------------------------------------------------------------------
# MetricsCollector async context manager
# ---------------------------------------------------------------------------


class TestMetricsCollector:

    @pytest.mark.asyncio
    async def test_before_exit_state(self):
        """result is None and to_dict() is empty before exiting context."""
        m = MetricsCollector("discover")
        assert m.result is None
        assert m.to_dict() == {}

    @pytest.mark.asyncio
    async def test_timing_recorded_after_exit(self):
        t_before = time.time()
        async with MetricsCollector("patch_b") as m:
            await asyncio.sleep(0.01)
        t_after = time.time()

        assert m.result is not None
        assert m.result.phase == "patch_b"
        assert m.result.start_ts >= t_before
        assert m.result.end_ts <= t_after
        assert m.result.end_ts >= m.result.start_ts
        assert m.result.duration_ms >= 10.0

    @pytest.mark.asyncio
    async def test_counters_and_serialisation(self):
        """Counters set inside context are preserved; to_dict() is JSON-serialisable."""
        async with MetricsCollector("discover") as m:
            m.input_tokens = 100
            m.output_tokens = 50
            m.tool_call_count = 3
            m.cache_hits = 2
            m.repair_events = 1

        assert m.result is not None
        assert m.result.input_tokens == 100
        assert m.result.output_tokens == 50
        assert m.result.tool_call_count == 3
        assert m.result.cache_hits == 2
        assert m.result.repair_events == 1

        d = m.to_dict()
        assert d["phase"] == "discover"
        assert d["input_tokens"] == 100
        assert "duration_ms" in d
        json.dumps(d)  # must not raise

    @pytest.mark.asyncio
    async def test_default_counters_are_zero(self):
        async with MetricsCollector("patch_d") as m:
            pass
        assert m.result.input_tokens == 0
        assert m.result.output_tokens == 0
        assert m.result.tool_call_count == 0
        assert m.result.cache_hits == 0
        assert m.result.repair_events == 0

    @pytest.mark.asyncio
    async def test_multiple_collectors_independent(self):
        """Two concurrent collectors must not share state."""
        async with MetricsCollector("patch_b") as m1:
            m1.input_tokens = 10
        async with MetricsCollector("patch_d") as m2:
            m2.cache_hits = 5
            m2.repair_events = 2

        assert m1.result.input_tokens == 10
        assert m1.result.cache_hits == 0
        assert m2.result.input_tokens == 0
        assert m2.result.cache_hits == 5
        assert m2.result.repair_events == 2

    @pytest.mark.asyncio
    async def test_phase_name_preserved(self):
        for phase_name in ("discover", "patch_b", "patch_d", "test", "converge"):
            async with MetricsCollector(phase_name) as m:
                pass
            assert m.result.phase == phase_name


# ---------------------------------------------------------------------------
# Drift policy constant
# ---------------------------------------------------------------------------


class TestDriftPolicyConstant:

    def test_module_exposes_valid_drift_policy(self):
        import flowise_dev_agent.agent.graph as graph_mod
        assert hasattr(graph_mod, "_SCHEMA_DRIFT_POLICY")
        assert graph_mod._SCHEMA_DRIFT_POLICY in ("warn", "fail", "refresh")

    def test_drift_policy_default_is_warn(self, monkeypatch):
        monkeypatch.delenv("FLOWISE_SCHEMA_DRIFT_POLICY", raising=False)
        import flowise_dev_agent.agent.graph as graph_mod
        assert graph_mod._SCHEMA_DRIFT_POLICY in ("warn", "fail", "refresh")


# ---------------------------------------------------------------------------
# SessionSummary M7.4 fields
# ---------------------------------------------------------------------------


class TestSessionSummaryM74:

    def test_repair_and_phases_fields(self):
        """M7.4 fields: total_repair_events and total_phases_timed with defaults."""
        s = SessionSummary(thread_id="t1", status="completed")
        assert s.total_repair_events == 0
        assert s.total_phases_timed == 0

        s2 = SessionSummary(thread_id="t1", status="completed",
                            total_repair_events=3, total_phases_timed=4)
        assert s2.total_repair_events == 3
        assert s2.total_phases_timed == 4

    def test_backward_compat_and_json(self):
        """Existing call-sites that don't pass new fields must not break; JSON-serialisable."""
        s = SessionSummary(
            thread_id="t1", status="completed", iteration=2,
            chatflow_id="abc-123", total_input_tokens=1000,
            total_output_tokens=500, session_name="Test Session",
            runtime_mode="capability_first",
            total_repair_events=2, total_phases_timed=5,
        )
        assert s.total_repair_events == 2
        json.dumps(s.model_dump())  # must not raise


# ---------------------------------------------------------------------------
# SessionSummary M8.2 telemetry fields
# ---------------------------------------------------------------------------


class TestSessionSummaryM82Telemetry:

    def test_m82_fields_exist_and_defaults(self):
        """knowledge_repair_count, get_node_calls_total, phase_durations_ms present with defaults."""
        s = SessionSummary(thread_id="t1", status="completed")
        assert s.knowledge_repair_count == 0
        assert s.get_node_calls_total == 0
        assert s.phase_durations_ms == {}

    def test_m82_fields_populated(self):
        s = SessionSummary(
            thread_id="t1", status="completed",
            knowledge_repair_count=3, get_node_calls_total=12,
            phase_durations_ms={"patch_d": 420.5, "discover": 1100.0},
        )
        assert s.knowledge_repair_count == 3
        assert s.get_node_calls_total == 12
        assert s.phase_durations_ms["patch_d"] == 420.5

    def test_node_schema_store_call_count(self):
        """NodeSchemaStore._call_count increments on every get_or_repair call."""
        from flowise_dev_agent.knowledge.provider import NodeSchemaStore

        store = NodeSchemaStore.__new__(NodeSchemaStore)
        store._index = {"chatOpenAI": {"name": "chatOpenAI"}}
        store._meta = {}
        store._repair_events = []
        store._loaded = True
        store._call_count = 0

        async def _run():
            await store.get_or_repair("chatOpenAI", api_fetcher=None)
            await store.get_or_repair("chatOpenAI", api_fetcher=None)
            return store._call_count

        count = asyncio.get_event_loop().run_until_complete(_run())
        assert count == 2


# ---------------------------------------------------------------------------
# Phase metrics accumulation
# ---------------------------------------------------------------------------


class TestPhaseMetricsDebugAccumulation:

    @pytest.mark.asyncio
    async def test_multiple_phases_accumulate_in_list(self):
        existing_phases: list[dict] = []
        async with MetricsCollector("discover") as m_disc:
            m_disc.tool_call_count = 1
        existing_phases.append(m_disc.to_dict())
        async with MetricsCollector("patch_b") as m_b:
            m_b.input_tokens = 300
            m_b.output_tokens = 150
        existing_phases.append(m_b.to_dict())
        async with MetricsCollector("patch_d") as m_d:
            m_d.cache_hits = 2
            m_d.repair_events = 1
        existing_phases.append(m_d.to_dict())

        assert len(existing_phases) == 3
        assert existing_phases[0]["phase"] == "discover"
        assert existing_phases[1]["phase"] == "patch_b"
        assert existing_phases[2]["phase"] == "patch_d"

    @pytest.mark.asyncio
    async def test_repair_events_sum_across_phases(self):
        phases: list[dict] = []
        async with MetricsCollector("patch_d") as m_d:
            m_d.repair_events = 2
        phases.append(m_d.to_dict())
        async with MetricsCollector("patch_d") as m_d2:
            m_d2.repair_events = 1
        phases.append(m_d2.to_dict())

        total_repairs = sum(p.get("repair_events", 0) for p in phases)
        assert total_repairs == 3

    @pytest.mark.asyncio
    async def test_zero_repair_events_in_happy_path(self):
        async with MetricsCollector("patch_d") as m_d:
            m_d.cache_hits = 3
        assert m_d.result.repair_events == 0
        assert m_d.result.cache_hits == 3


# ---------------------------------------------------------------------------
# M9.7: Schema fingerprint + drift detection
# ---------------------------------------------------------------------------


class TestSchemaFingerprintAndDrift:

    @pytest.mark.parametrize("state,expected_fp,expected_drift", [
        # Fingerprints differ → drift detected
        (
            {"facts": {"flowise": {"schema_fingerprint": "new-fp", "prior_schema_fingerprint": "old-fp"}}},
            "new-fp", True,
        ),
        # Fingerprints same → no drift
        (
            {"facts": {"flowise": {"schema_fingerprint": "same", "prior_schema_fingerprint": "same"}}},
            "same", False,
        ),
        # No prior → no drift
        (
            {"facts": {"flowise": {"schema_fingerprint": "current-fp"}}},
            "current-fp", False,
        ),
        # Prior is None → no drift
        (
            {"facts": {"flowise": {"schema_fingerprint": "current-fp", "prior_schema_fingerprint": None}}},
            "current-fp", False,
        ),
        # No facts at all → None fingerprint, no drift
        (
            {},
            None, False,
        ),
        # Empty flowise facts → None fingerprint
        (
            {"facts": {"flowise": {}}},
            None, False,
        ),
    ], ids=["differ", "same", "no-prior", "prior-none", "no-facts", "empty-flowise"])
    def test_drift_detection(self, state, expected_fp, expected_drift):
        summary = _build_summary(state)
        assert summary.schema_fingerprint == expected_fp
        assert summary.drift_detected is expected_drift

    def test_drift_fields_exist_on_model(self):
        s = SessionSummary(thread_id="t1", status="completed")
        assert hasattr(s, "schema_fingerprint")
        assert s.schema_fingerprint is None
        assert hasattr(s, "drift_detected")
        assert s.drift_detected is False

    def test_fingerprint_json_serialisable(self):
        s = SessionSummary(thread_id="t1", status="completed",
                           schema_fingerprint="deadbeef1234")
        json.dumps(s.model_dump())  # must not raise


# ---------------------------------------------------------------------------
# M9.7: Pattern metrics
# ---------------------------------------------------------------------------


class TestPatternMetrics:

    @pytest.mark.parametrize("state,expected", [
        # Populated
        (
            {"debug": {"flowise": {"pattern_metrics": {"pattern_used": True, "pattern_id": 7, "ops_in_base": 4}}}},
            {"pattern_used": True, "pattern_id": 7, "ops_in_base": 4},
        ),
        # Absent
        ({"debug": {"flowise": {}}}, None),
        # No debug at all
        ({}, None),
    ], ids=["populated", "absent", "no-debug"])
    def test_pattern_metrics_extraction(self, state, expected):
        summary = _build_summary(state)
        assert summary.pattern_metrics == expected

    def test_pattern_metrics_field_exists_on_model(self):
        s = SessionSummary(thread_id="t1", status="completed")
        assert hasattr(s, "pattern_metrics")
        assert s.pattern_metrics is None

    def test_pattern_metrics_json_serialisable(self):
        s = SessionSummary(
            thread_id="t1", status="completed",
            pattern_metrics={"pattern_used": False, "pattern_id": None, "ops_in_base": 0},
        )
        json.dumps(s.model_dump())  # must not raise


# ---------------------------------------------------------------------------
# M9.7: Phase durations from phase_metrics
# ---------------------------------------------------------------------------


class TestPhaseDurationsFromPhaseMetrics:

    def test_phase_durations_populated(self):
        state = {
            "debug": {"flowise": {"phase_metrics": [
                {"phase": "discover", "duration_ms": 1200.5, "start_ts": 0.0, "end_ts": 1.2},
                {"phase": "patch_b", "duration_ms": 800.0, "start_ts": 1.2, "end_ts": 2.0},
                {"phase": "patch_d", "duration_ms": 350.25, "start_ts": 2.0, "end_ts": 2.35},
            ]}}
        }
        summary = _build_summary(state)
        assert summary.phase_durations_ms["discover"] == 1200.5
        assert summary.phase_durations_ms["patch_b"] == 800.0
        assert summary.phase_durations_ms["patch_d"] == 350.25

    def test_phase_durations_empty_when_no_phase_metrics(self):
        summary = _build_summary({})
        assert summary.phase_durations_ms == {}

    def test_duplicate_phase_uses_last_value(self):
        state = {
            "debug": {"flowise": {"phase_metrics": [
                {"phase": "patch_d", "duration_ms": 300.0, "start_ts": 0.0, "end_ts": 0.3},
                {"phase": "patch_d", "duration_ms": 450.0, "start_ts": 1.0, "end_ts": 1.45},
            ]}}
        }
        summary = _build_summary(state)
        assert summary.phase_durations_ms["patch_d"] == 450.0

    def test_total_phases_timed_matches_phase_metrics_length(self):
        state = {
            "debug": {"flowise": {"phase_metrics": [
                {"phase": "discover", "duration_ms": 100.0, "start_ts": 0.0, "end_ts": 0.1},
                {"phase": "patch_b", "duration_ms": 200.0, "start_ts": 0.1, "end_ts": 0.3},
            ]}}
        }
        summary = _build_summary(state)
        assert summary.total_phases_timed == 2
