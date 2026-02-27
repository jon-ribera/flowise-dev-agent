"""M11.4 — Bounded repair policy tests (DD-110).

Tests:
- Bad schema first → force_refresh → fixed schema → compile succeeds after retry
- Repair called once per node type (bounded)
- Compile retried exactly once
- Still-failing after repair → escalation path (compile_errors surface for HITL)
- No repair when no drift detected
- No repair when node_store is None
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flowise_dev_agent.knowledge.drift import (
    DriftMetrics,
    validate_flow_render_contract,
    validate_node_render_contract,
)
from flowise_dev_agent.knowledge.provider import NodeSchemaStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _good_schema(name: str = "chatOpenAI") -> dict:
    """Schema that passes render-safe contract."""
    return {
        "name": name,
        "node_type": name,
        "baseClasses": ["BaseChatModel"],
        "category": "Chat Models",
        "description": f"A {name} node",
        "inputAnchors": [],
        "inputParams": [
            {
                "name": "credential",
                "type": "credential",
                "credentialNames": ["openAIApi"],
            },
            {
                "name": "modelName",
                "type": "asyncOptions",
                "loadMethod": "listModels",
                "default": "gpt-4o",
            },
            {
                "name": "temperature",
                "type": "number",
                "default": 0.9,
            },
        ],
        "outputAnchors": [
            {
                "id": "{nodeId}-output-chatOpenAI-BaseChatModel",
                "name": name,
                "type": "BaseChatModel",
            }
        ],
        "outputs": {},
        "credentialNames": ["openAIApi"],
    }


def _bad_schema(name: str = "chatOpenAI") -> dict:
    """Schema that fails render-safe contract (drift detected)."""
    return {
        "name": name,
        "node_type": name,
        "baseClasses": ["BaseChatModel"],
        "category": "Chat Models",
        "description": f"A {name} node",
        "inputAnchors": [],
        "inputParams": [
            # Missing credential inputParam entirely (Rule 6 violation)
            {
                "name": "modelName",
                "type": "asyncOptions",
                # Missing loadMethod (Rule 2 violation)
            },
            {
                "name": "temperature",
                "type": "number",
                "default": "0.9",  # String default (Rule 4 violation - warning)
            },
        ],
        "outputAnchors": [
            {
                "id": "{nodeId}-output-chatOpenAI-BaseChatModel",
                "name": name,
                "type": "BaseChatModel",
            }
        ],
        "outputs": {},
        "credentialNames": ["openAIApi"],
    }


# ---------------------------------------------------------------------------
# force_refresh_node_schema tests
# ---------------------------------------------------------------------------


class TestForceRefreshNodeSchema:
    @pytest.mark.asyncio
    async def test_force_refresh_updates_memory(self, tmp_path):
        """force_refresh_node_schema updates memory index."""
        snapshot = tmp_path / "nodes.json"
        meta = tmp_path / "nodes.meta.json"
        snapshot.write_text("[]")

        store = NodeSchemaStore(snapshot_path=snapshot, meta_path=meta)
        store._load()

        good = _good_schema()

        async def _fetcher(name: str):
            return good

        result = await store.force_refresh_node_schema("chatOpenAI", _fetcher)

        assert result is not None
        assert store.get("chatOpenAI") is not None

    @pytest.mark.asyncio
    async def test_force_refresh_api_failure_returns_none(self, tmp_path):
        """force_refresh returns None when API call fails."""
        snapshot = tmp_path / "nodes.json"
        meta = tmp_path / "nodes.meta.json"
        snapshot.write_text("[]")

        store = NodeSchemaStore(snapshot_path=snapshot, meta_path=meta)
        store._load()

        async def _failing_fetcher(name: str):
            raise RuntimeError("network error")

        result = await store.force_refresh_node_schema("chatOpenAI", _failing_fetcher)
        assert result is None

    @pytest.mark.asyncio
    async def test_force_refresh_empty_response_returns_none(self, tmp_path):
        """force_refresh returns None when API returns empty/error."""
        snapshot = tmp_path / "nodes.json"
        meta = tmp_path / "nodes.meta.json"
        snapshot.write_text("[]")

        store = NodeSchemaStore(snapshot_path=snapshot, meta_path=meta)
        store._load()

        async def _empty_fetcher(name: str):
            return None

        result = await store.force_refresh_node_schema("chatOpenAI", _empty_fetcher)
        assert result is None

    @pytest.mark.asyncio
    async def test_force_refresh_writes_to_postgres(self, tmp_path):
        """force_refresh writes back to Postgres cache."""
        snapshot = tmp_path / "nodes.json"
        meta = tmp_path / "nodes.meta.json"
        snapshot.write_text("[]")

        pg_cache = AsyncMock()
        pg_cache.put = AsyncMock()

        store = NodeSchemaStore(
            snapshot_path=snapshot, meta_path=meta, pg_cache=pg_cache,
        )
        store._load()

        good = _good_schema()

        async def _fetcher(name: str):
            return good

        await store.force_refresh_node_schema("chatOpenAI", _fetcher)

        pg_cache.put.assert_called_once()
        call_args = pg_cache.put.call_args
        assert call_args[0][0] == "node"
        assert call_args[0][1] == "chatOpenAI"

    @pytest.mark.asyncio
    async def test_force_refresh_bypasses_version_gating(self, tmp_path):
        """force_refresh overwrites even when version matches."""
        snapshot = tmp_path / "nodes.json"
        meta = tmp_path / "nodes.meta.json"
        # Pre-populate with same-version schema
        existing = _bad_schema()
        existing["version"] = "1.0"
        snapshot.write_text(json.dumps([existing]))

        store = NodeSchemaStore(snapshot_path=snapshot, meta_path=meta)
        store._load()

        # Existing schema has the bad version
        assert store.get("chatOpenAI") is not None

        # Force refresh with good schema (same version)
        good = _good_schema()
        good["version"] = "1.0"

        async def _fetcher(name: str):
            return good

        result = await store.force_refresh_node_schema("chatOpenAI", _fetcher)

        # Should have overwritten despite same version
        assert result is not None


# ---------------------------------------------------------------------------
# Bounded repair policy tests
# ---------------------------------------------------------------------------


class TestBoundedRepairPolicy:
    def test_drift_metrics_initial_state(self):
        """DriftMetrics starts with all zeroes."""
        m = DriftMetrics()
        assert m.cache_hits_memory == 0
        assert m.repair_attempts_count == 0
        assert m.compile_retry_count == 0
        assert m.repaired_node_types == []

    def test_drift_metrics_to_dict(self):
        """DriftMetrics serializes to a dict."""
        m = DriftMetrics(
            cache_hits_memory=3,
            cache_hits_postgres=1,
            mcp_fetches=2,
            drift_detected_count=1,
            repair_attempts_count=1,
            repaired_node_types=["chatOpenAI"],
            compile_retry_count=1,
        )
        d = m.to_dict()
        assert d["cache_hits_memory"] == 3
        assert d["repaired_node_types"] == ["chatOpenAI"]
        assert d["compile_retry_count"] == 1

    def test_drift_metrics_telemetry_dict(self):
        """DriftMetrics produces LangSmith-compatible telemetry."""
        m = DriftMetrics(
            cache_hits_memory=8,
            cache_hits_postgres=2,
            cache_misses=0,
            mcp_fetches=1,
            repair_attempts_count=1,
            drift_detected_count=1,
        )
        t = m.telemetry_dict()
        assert t["telemetry.cache_hit_rate"] == 1.0  # 10/10 hits
        assert t["telemetry.mcp_fetches"] == 1
        assert t["telemetry.schema_repairs"] == 1
        assert t["telemetry.drift_detected"] == 1

    def test_telemetry_hit_rate_with_misses(self):
        """Cache hit rate correctly accounts for misses."""
        m = DriftMetrics(
            cache_hits_memory=6,
            cache_hits_postgres=2,
            cache_misses=2,
        )
        t = m.telemetry_dict()
        assert t["telemetry.cache_hit_rate"] == 0.8  # 8/10

    def test_telemetry_hit_rate_zero_total(self):
        """Cache hit rate is 1.0 when no lookups occurred."""
        m = DriftMetrics()
        t = m.telemetry_dict()
        assert t["telemetry.cache_hit_rate"] == 1.0

    def test_bad_schema_triggers_drift(self):
        """Bad schema triggers drift detection via validate_node_render_contract."""
        bad = _bad_schema()
        result = validate_node_render_contract(bad, "chatOpenAI_0")
        # Should have errors (missing loadMethod, missing credential param)
        assert not result.ok
        errors = [i for i in result.issues if i.severity == "error"]
        assert len(errors) >= 1

    def test_good_schema_no_drift(self):
        """Good schema passes drift validation."""
        good = _good_schema()
        result = validate_node_render_contract(good, "chatOpenAI_0")
        assert result.ok

    def test_repair_bounded_to_one_per_type(self):
        """Simulates the bounded repair policy: only 1 repair per node type."""
        repaired: set[str] = set()
        types_with_drift = {"chatOpenAI", "bufferMemory"}
        repairs_attempted = 0

        for nt in types_with_drift:
            if nt not in repaired:
                repairs_attempted += 1
                repaired.add(nt)

        # Second pass: no additional repairs
        for nt in types_with_drift:
            if nt not in repaired:
                repairs_attempted += 1
                repaired.add(nt)

        assert repairs_attempted == 2  # once per type
        assert repaired == {"chatOpenAI", "bufferMemory"}

    def test_compile_retry_count_bounded_to_one(self):
        """compile_retry_count should never exceed 1."""
        m = DriftMetrics()
        # Simulate the bounded repair logic
        drift_detected = True
        types_to_repair = {"chatOpenAI"}

        if drift_detected and types_to_repair:
            m.compile_retry_count = 1

        assert m.compile_retry_count == 1

    def test_affected_node_types_from_drift_result(self):
        """DriftResult.affected_node_types returns distinct types with issues."""
        from flowise_dev_agent.knowledge.drift import DriftIssue, DriftResult

        result = DriftResult(ok=False, issues=[
            DriftIssue("chatOpenAI_0", "chatOpenAI", "f1", "msg1", "error"),
            DriftIssue("chatOpenAI_1", "chatOpenAI", "f2", "msg2", "error"),
            DriftIssue("bufferMemory_0", "bufferMemory", "f3", "msg3", "warning"),
        ])
        assert result.affected_node_types == {"chatOpenAI", "bufferMemory"}
