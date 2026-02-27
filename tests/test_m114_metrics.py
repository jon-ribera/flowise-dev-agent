"""M11.4 — Drift metrics and observability tests (DD-110, DD-111).

Tests:
- DriftMetrics counters update correctly for cache hits/misses
- DriftMetrics serialization (to_dict, telemetry_dict)
- CompileResult.schema_gap_metrics field exists and propagates
- Telemetry keys match LangSmith convention
"""

from __future__ import annotations

import pytest

from flowise_dev_agent.agent.compiler import CompileResult
from flowise_dev_agent.knowledge.drift import DriftMetrics


# ---------------------------------------------------------------------------
# DriftMetrics counter tests
# ---------------------------------------------------------------------------


class TestDriftMetricsCounters:
    def test_initial_state_all_zero(self):
        """All counters start at zero."""
        m = DriftMetrics()
        assert m.cache_hits_memory == 0
        assert m.cache_hits_postgres == 0
        assert m.cache_misses == 0
        assert m.mcp_fetches == 0
        assert m.drift_detected_count == 0
        assert m.repair_attempts_count == 0
        assert m.compile_retry_count == 0
        assert m.repaired_node_types == []

    def test_increment_cache_hits(self):
        """Cache hit counters increment correctly."""
        m = DriftMetrics()
        m.cache_hits_memory += 5
        m.cache_hits_postgres += 3
        assert m.cache_hits_memory == 5
        assert m.cache_hits_postgres == 3

    def test_increment_misses_and_fetches(self):
        """Miss and fetch counters track correctly."""
        m = DriftMetrics()
        m.cache_misses += 2
        m.mcp_fetches += 2
        assert m.cache_misses == 2
        assert m.mcp_fetches == 2

    def test_repair_tracking(self):
        """Repair counters and list track correctly."""
        m = DriftMetrics()
        m.repair_attempts_count += 1
        m.repaired_node_types.append("chatOpenAI")
        m.repair_attempts_count += 1
        m.repaired_node_types.append("bufferMemory")
        m.compile_retry_count = 1

        assert m.repair_attempts_count == 2
        assert m.repaired_node_types == ["chatOpenAI", "bufferMemory"]
        assert m.compile_retry_count == 1


# ---------------------------------------------------------------------------
# DriftMetrics serialization
# ---------------------------------------------------------------------------


class TestDriftMetricsSerialization:
    def test_to_dict_all_fields(self):
        """to_dict contains all expected fields."""
        m = DriftMetrics(
            cache_hits_memory=10,
            cache_hits_postgres=5,
            cache_misses=2,
            mcp_fetches=3,
            drift_detected_count=1,
            repair_attempts_count=1,
            repaired_node_types=["chatOpenAI"],
            compile_retry_count=1,
        )
        d = m.to_dict()
        assert d == {
            "cache_hits_memory": 10,
            "cache_hits_postgres": 5,
            "cache_misses": 2,
            "mcp_fetches": 3,
            "drift_detected_count": 1,
            "repair_attempts_count": 1,
            "repaired_node_types": ["chatOpenAI"],
            "compile_retry_count": 1,
        }

    def test_to_dict_is_json_safe(self):
        """to_dict output can be JSON serialized."""
        import json

        m = DriftMetrics(
            cache_hits_memory=1,
            repaired_node_types=["chatOpenAI"],
        )
        json_str = json.dumps(m.to_dict())
        assert "cache_hits_memory" in json_str
        assert "chatOpenAI" in json_str


# ---------------------------------------------------------------------------
# Telemetry dict (LangSmith metadata)
# ---------------------------------------------------------------------------


class TestTelemetryDict:
    def test_telemetry_keys_match_convention(self):
        """Telemetry keys follow 'telemetry.*' naming."""
        m = DriftMetrics()
        t = m.telemetry_dict()
        for key in t:
            assert key.startswith("telemetry."), f"Key '{key}' doesn't follow convention"

    def test_telemetry_expected_keys(self):
        """All expected telemetry keys are present."""
        m = DriftMetrics()
        t = m.telemetry_dict()
        expected = {
            "telemetry.cache_hit_rate",
            "telemetry.mcp_fetches",
            "telemetry.schema_repairs",
            "telemetry.drift_detected",
        }
        assert set(t.keys()) == expected

    def test_hit_rate_100_percent(self):
        """All hits → 1.0 rate."""
        m = DriftMetrics(cache_hits_memory=10, cache_misses=0)
        assert m.telemetry_dict()["telemetry.cache_hit_rate"] == 1.0

    def test_hit_rate_50_percent(self):
        """Half hits → 0.5 rate."""
        m = DriftMetrics(cache_hits_memory=5, cache_misses=5)
        assert m.telemetry_dict()["telemetry.cache_hit_rate"] == 0.5

    def test_hit_rate_mixed_tiers(self):
        """Memory + Postgres hits counted together."""
        m = DriftMetrics(
            cache_hits_memory=3,
            cache_hits_postgres=7,
            cache_misses=0,
        )
        assert m.telemetry_dict()["telemetry.cache_hit_rate"] == 1.0

    def test_hit_rate_zero_lookups(self):
        """No lookups → 1.0 (vacuously true)."""
        m = DriftMetrics()
        assert m.telemetry_dict()["telemetry.cache_hit_rate"] == 1.0

    def test_hit_rate_rounding(self):
        """Hit rate is rounded to 4 decimal places."""
        m = DriftMetrics(
            cache_hits_memory=1,
            cache_misses=2,
        )
        rate = m.telemetry_dict()["telemetry.cache_hit_rate"]
        assert rate == round(1 / 3, 4)


# ---------------------------------------------------------------------------
# CompileResult.schema_gap_metrics
# ---------------------------------------------------------------------------


class TestCompileResultSchemaGapMetrics:
    def test_schema_gap_metrics_default_empty(self):
        """CompileResult defaults to empty schema_gap_metrics."""
        cr = CompileResult(
            flow_data={},
            flow_data_str="{}",
            payload_hash="abc",
            diff_summary="",
        )
        assert cr.schema_gap_metrics == {}

    def test_schema_gap_metrics_populated(self):
        """CompileResult can carry drift metrics."""
        m = DriftMetrics(
            cache_hits_memory=5,
            drift_detected_count=1,
            repaired_node_types=["chatOpenAI"],
            compile_retry_count=1,
        )
        cr = CompileResult(
            flow_data={},
            flow_data_str="{}",
            payload_hash="abc",
            diff_summary="",
            schema_gap_metrics=m.to_dict(),
        )
        assert cr.schema_gap_metrics["cache_hits_memory"] == 5
        assert cr.schema_gap_metrics["drift_detected_count"] == 1
        assert cr.schema_gap_metrics["repaired_node_types"] == ["chatOpenAI"]
        assert cr.schema_gap_metrics["compile_retry_count"] == 1

    def test_compile_result_ok_unaffected_by_gap_metrics(self):
        """schema_gap_metrics don't affect CompileResult.ok."""
        cr = CompileResult(
            flow_data={},
            flow_data_str="{}",
            payload_hash="abc",
            diff_summary="",
            schema_gap_metrics={"drift_detected_count": 5},
        )
        assert cr.ok  # ok depends on errors list, not gap metrics
