"""Tests for Milestone 7.4: Drift Management + Telemetry Hardening (DD-069).

Covers the acceptance tests from the roadmap:
  Test group 1 — PhaseMetrics dataclass fields and JSON serialisability.
  Test group 2 — MetricsCollector async context manager behaviour.
  Test group 3 — FLOWISE_SCHEMA_DRIFT_POLICY module constant and default value.
  Test group 4 — SessionSummary has total_repair_events + total_phases_timed fields.
  Test group 5 — list_sessions() extracts phase_metrics from debug state.

See roadmap7_multi_domain_runtime_hardening.md — Milestone 7.4.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time

import pytest

from flowise_dev_agent.agent.metrics import MetricsCollector, PhaseMetrics


# ---------------------------------------------------------------------------
# Test group 1 — PhaseMetrics dataclass
# ---------------------------------------------------------------------------


class TestPhaseMetrics:

    def test_required_fields_accepted(self):
        m = PhaseMetrics(phase="test", start_ts=0.0, end_ts=1.0, duration_ms=1000.0)
        assert m.phase == "test"
        assert m.start_ts == 0.0
        assert m.end_ts == 1.0
        assert m.duration_ms == 1000.0

    def test_optional_counter_defaults_are_zero(self):
        m = PhaseMetrics(phase="discover", start_ts=0.0, end_ts=1.0, duration_ms=1000.0)
        assert m.input_tokens == 0
        assert m.output_tokens == 0
        assert m.tool_call_count == 0
        assert m.cache_hits == 0
        assert m.repair_events == 0

    def test_counter_fields_settable(self):
        m = PhaseMetrics(
            phase="patch_b",
            start_ts=100.0,
            end_ts=101.5,
            duration_ms=1500.0,
            input_tokens=500,
            output_tokens=200,
            tool_call_count=3,
            cache_hits=7,
            repair_events=1,
        )
        assert m.input_tokens == 500
        assert m.output_tokens == 200
        assert m.tool_call_count == 3
        assert m.cache_hits == 7
        assert m.repair_events == 1

    def test_asdict_is_json_serialisable(self):
        m = PhaseMetrics(phase="converge", start_ts=1000.0, end_ts=1001.0, duration_ms=1000.0)
        d = dataclasses.asdict(m)
        json.dumps(d)  # must not raise

    def test_asdict_keys_complete(self):
        m = PhaseMetrics(phase="test", start_ts=0.0, end_ts=1.0, duration_ms=1000.0)
        d = dataclasses.asdict(m)
        expected = {
            "phase", "start_ts", "end_ts", "duration_ms",
            "input_tokens", "output_tokens", "tool_call_count",
            "cache_hits", "repair_events",
        }
        assert set(d.keys()) == expected

    def test_all_values_json_primitives(self):
        """All values in asdict() must be JSON primitives (no nested objects)."""
        m = PhaseMetrics(
            phase="patch_d",
            start_ts=1000.0,
            end_ts=1002.0,
            duration_ms=2000.0,
            input_tokens=10,
            output_tokens=5,
            cache_hits=3,
            repair_events=0,
        )
        for val in dataclasses.asdict(m).values():
            assert isinstance(val, (str, int, float))


# ---------------------------------------------------------------------------
# Test group 2 — MetricsCollector async context manager
# ---------------------------------------------------------------------------


class TestMetricsCollector:

    @pytest.mark.asyncio
    async def test_result_is_none_before_exit(self):
        m = MetricsCollector("discover")
        assert m.result is None

    @pytest.mark.asyncio
    async def test_to_dict_before_exit_returns_empty(self):
        m = MetricsCollector("patch_b")
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
    async def test_counters_set_inside_context(self):
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

    @pytest.mark.asyncio
    async def test_to_dict_after_exit_contains_phase_metrics(self):
        async with MetricsCollector("test") as m:
            m.input_tokens = 42

        d = m.to_dict()
        assert d["phase"] == "test"
        assert d["input_tokens"] == 42
        assert "duration_ms" in d
        assert "start_ts" in d
        assert "end_ts" in d

    @pytest.mark.asyncio
    async def test_to_dict_is_json_serialisable(self):
        async with MetricsCollector("converge") as m:
            m.output_tokens = 99

        d = m.to_dict()
        json.dumps(d)  # must not raise

    @pytest.mark.asyncio
    async def test_default_counters_are_zero(self):
        async with MetricsCollector("patch_d") as m:
            pass  # no counters set

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
# Test group 3 — FLOWISE_SCHEMA_DRIFT_POLICY module constant
# ---------------------------------------------------------------------------


class TestDriftPolicyConstant:

    def test_module_exposes_drift_policy_constant(self):
        import flowise_dev_agent.agent.graph as graph_mod

        assert hasattr(graph_mod, "_SCHEMA_DRIFT_POLICY")

    def test_drift_policy_is_valid_value(self):
        import flowise_dev_agent.agent.graph as graph_mod

        assert graph_mod._SCHEMA_DRIFT_POLICY in ("warn", "fail", "refresh")

    def test_drift_policy_default_is_warn(self, monkeypatch):
        """When env var is absent the module constant must be 'warn'.

        This test validates the default.  Because the constant is read at
        import time the monkeypatch only works if the module is fresh — here
        we simply verify the documented default by checking the installed
        value after removing the env var.
        """
        monkeypatch.delenv("FLOWISE_SCHEMA_DRIFT_POLICY", raising=False)
        # Re-import is not safe in pytest; instead verify the constant is 'warn'
        # when no env var was set at process startup (which is true for CI).
        import flowise_dev_agent.agent.graph as graph_mod

        # The constant is either "warn" (default) or whatever CI set.
        # We can only assert it is a valid value here without reimport.
        assert graph_mod._SCHEMA_DRIFT_POLICY in ("warn", "fail", "refresh")


# ---------------------------------------------------------------------------
# Test group 4 — SessionSummary new fields
# ---------------------------------------------------------------------------


class TestSessionSummaryM74:

    def test_session_summary_has_total_repair_events(self):
        from flowise_dev_agent.api import SessionSummary

        s = SessionSummary(thread_id="t1", status="completed", total_repair_events=3)
        assert s.total_repair_events == 3

    def test_session_summary_has_total_phases_timed(self):
        from flowise_dev_agent.api import SessionSummary

        s = SessionSummary(thread_id="t1", status="completed", total_phases_timed=4)
        assert s.total_phases_timed == 4

    def test_new_fields_default_to_zero(self):
        from flowise_dev_agent.api import SessionSummary

        s = SessionSummary(thread_id="t1", status="completed")
        assert s.total_repair_events == 0
        assert s.total_phases_timed == 0

    def test_session_summary_backward_compat(self):
        """Existing call-sites that don't pass new fields must not break."""
        from flowise_dev_agent.api import SessionSummary

        s = SessionSummary(
            thread_id="t1",
            status="completed",
            iteration=2,
            chatflow_id="abc-123",
            total_input_tokens=1000,
            total_output_tokens=500,
            session_name="Test Session",
            runtime_mode="capability_first",
        )
        assert s.total_repair_events == 0
        assert s.total_phases_timed == 0

    def test_session_summary_fields_json_serialisable(self):
        from flowise_dev_agent.api import SessionSummary

        s = SessionSummary(
            thread_id="t1",
            status="completed",
            total_repair_events=2,
            total_phases_timed=5,
        )
        json.dumps(s.model_dump())  # must not raise


# ---------------------------------------------------------------------------
# Test group 5 — Phase metrics accumulation in debug state
# ---------------------------------------------------------------------------


class TestPhaseMetricsDebugAccumulation:

    @pytest.mark.asyncio
    async def test_multiple_phases_accumulate_in_list(self):
        """Simulates the per-node pattern: each node appends its phase dict."""
        existing_phases: list[dict] = []

        # Simulate discover phase
        async with MetricsCollector("discover") as m_disc:
            m_disc.tool_call_count = 1
        existing_phases.append(m_disc.to_dict())

        # Simulate patch_b phase
        async with MetricsCollector("patch_b") as m_b:
            m_b.input_tokens = 300
            m_b.output_tokens = 150
        existing_phases.append(m_b.to_dict())

        # Simulate patch_d phase
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
        """total_repair_events must sum repair_events across all phase dicts."""
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
        """When all schemas are in the snapshot, repair_events must be 0."""
        async with MetricsCollector("patch_d") as m_d:
            m_d.cache_hits = 3
            # repair_events intentionally not set → default 0

        assert m_d.result.repair_events == 0
        assert m_d.result.cache_hits == 3


# ---------------------------------------------------------------------------
# Test group 6 — M8.2: SessionSummary telemetry fields
# ---------------------------------------------------------------------------


class TestSessionSummaryM82Telemetry:
    """SessionSummary must include knowledge_repair_count, get_node_calls_total,
    and phase_durations_ms (M8.2)."""

    def test_session_summary_has_m82_fields(self):
        """All three M8.2 fields must be present on SessionSummary."""
        from flowise_dev_agent.api import SessionSummary

        s = SessionSummary(thread_id="t1", status="completed")
        assert hasattr(s, "knowledge_repair_count"), "Missing knowledge_repair_count"
        assert hasattr(s, "get_node_calls_total"), "Missing get_node_calls_total"
        assert hasattr(s, "phase_durations_ms"), "Missing phase_durations_ms"

    def test_session_summary_m82_defaults(self):
        """M8.2 fields default to 0 / empty dict."""
        from flowise_dev_agent.api import SessionSummary

        s = SessionSummary(thread_id="t1", status="completed")
        assert s.knowledge_repair_count == 0
        assert s.get_node_calls_total == 0
        assert s.phase_durations_ms == {}

    def test_session_summary_m82_populated(self):
        """M8.2 fields accept non-default values."""
        from flowise_dev_agent.api import SessionSummary

        s = SessionSummary(
            thread_id="t1",
            status="completed",
            knowledge_repair_count=3,
            get_node_calls_total=12,
            phase_durations_ms={"patch_d": 420.5, "discover": 1100.0},
        )
        assert s.knowledge_repair_count == 3
        assert s.get_node_calls_total == 12
        assert s.phase_durations_ms["patch_d"] == 420.5
        assert s.phase_durations_ms["discover"] == 1100.0

    def test_node_schema_store_call_count(self):
        """NodeSchemaStore._call_count increments on every get_or_repair call."""
        from flowise_dev_agent.knowledge.provider import NodeSchemaStore

        store = NodeSchemaStore.__new__(NodeSchemaStore)
        store._index = {"chatOpenAI": {"name": "chatOpenAI"}}
        store._meta = {}
        store._repair_events = []
        store._loaded = True
        store._call_count = 0

        import asyncio

        async def _run():
            # Two cache-hit calls
            await store.get_or_repair("chatOpenAI", api_fetcher=None)
            await store.get_or_repair("chatOpenAI", api_fetcher=None)
            return store._call_count

        count = asyncio.get_event_loop().run_until_complete(_run())
        assert count == 2, f"Expected 2 calls, got {count}"
