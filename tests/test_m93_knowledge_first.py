"""M9.3 — Knowledge-first runtime contract alignment tests.

Verifies:

  Prompt contract:
    1. _DISCOVER_BASE does NOT instruct "call get_node for EVERY node"
    2. _DISCOVER_BASE explicitly states schemas are pre-loaded / local
    3. _FLOWISE_DISCOVER_CONTEXT does NOT instruct calling get_node per node type
    4. _FLOWISE_DISCOVER_CONTEXT states do-not-call-get_node during discover
    5. get_node tool description carries a DISCOVER-phase warning

  _repair_schema_for_ops behaviour:
    6. Known nodes (cache hit) → no API call, schema returned from local store
    7. Unknown nodes (cache miss) → exactly one API call per missing type
    8. Repair budget enforced — nodes beyond max_repairs are skipped
    9. Empty node_names → empty result, no API call
   10. Legacy path (node_store=None) → always calls API (unchanged behaviour)

See roadmap9_production_graph_runtime_hardening.md — Milestone 9.3.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flowise_dev_agent.agent.graph import (
    _DISCOVER_BASE,
    _MAX_SCHEMA_REPAIRS,
    _repair_schema_for_ops,
)
from flowise_dev_agent.agent.tools import (
    _FLOWISE_DISCOVER_CONTEXT,
    _FLOWISE_DISCOVER_TOOLS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_desc(name: str) -> str:
    """Return the description of a named tool from _FLOWISE_DISCOVER_TOOLS."""
    for td in _FLOWISE_DISCOVER_TOOLS:
        if td.name == name:
            return td.description
    return ""


def _make_mock_store(known: set[str]) -> MagicMock:
    """Build a mock NodeSchemaStore where only ``known`` node types are cached.

    Cache HIT  → returns a minimal schema dict and appends NO repair event.
    Cache MISS → calls the api_fetcher and appends a repair event dict.
    """
    store = MagicMock()
    store._call_count = 0

    async def _get_or_repair(node_type: str, api_fetcher, repair_events_out=None):
        store._call_count += 1
        if node_type in known:
            # Fast path — return minimal schema, no repair event
            return {"name": node_type, "inputAnchors": [], "inputParams": [], "outputAnchors": []}
        # Slow path — call API fetcher and record repair event
        result = await api_fetcher(node_type)
        if repair_events_out is not None:
            repair_events_out.append({"node_type": node_type, "action": "repair"})
        return result if result else None

    store.get_or_repair = AsyncMock(side_effect=_get_or_repair)
    return store


def _make_dummy_executor(return_schema: dict | None = None) -> dict:
    """Return an executor dict whose 'get_node' handler returns return_schema."""
    from flowise_dev_agent.agent.tools import ToolResult

    async def _get_node(**kwargs):
        if return_schema is not None:
            return ToolResult(ok=True, summary="ok", facts={}, data=return_schema, error=None, artifacts=None)
        return ToolResult(ok=False, summary="not found", facts={}, data=None, error="404", artifacts=None)

    return {"get_node": _get_node}


# ---------------------------------------------------------------------------
# 1. _DISCOVER_BASE does NOT say "call get_node for EVERY node"
# ---------------------------------------------------------------------------


def test_discover_base_no_get_node_for_every_node():
    """The discover prompt must not instruct the LLM to call get_node for every node."""
    lower = _DISCOVER_BASE.lower()
    assert "get_node for every" not in lower, (
        "_DISCOVER_BASE still contains 'get_node for every' — this instruction "
        "causes the LLM to burn tokens on redundant schema fetches during discover."
    )
    # Also check the old RULE wording is gone
    assert "call get_node for every node you intend" not in lower


# ---------------------------------------------------------------------------
# 2. _DISCOVER_BASE mentions local / pre-loaded schemas
# ---------------------------------------------------------------------------


def test_discover_base_mentions_local_pre_loaded_schemas():
    """The discover prompt must tell the LLM that schemas are pre-loaded locally."""
    lower = _DISCOVER_BASE.lower()
    # Should contain at least one of these phrases
    phrases = ["pre-load", "local snapshot", "pre-loaded", "locally"]
    assert any(p in lower for p in phrases), (
        f"_DISCOVER_BASE does not mention local/pre-loaded schemas. "
        f"Checked phrases: {phrases}"
    )


# ---------------------------------------------------------------------------
# 3. _FLOWISE_DISCOVER_CONTEXT does NOT instruct per-node get_node calls
# ---------------------------------------------------------------------------


def test_discover_context_no_per_node_get_node_instruction():
    """_FLOWISE_DISCOVER_CONTEXT must not say 'call get_node' for each planned node."""
    lower = _FLOWISE_DISCOVER_CONTEXT.lower()
    bad_phrases = [
        "for each node type you plan to use, call get_node",
        "call get_node to verify its exact input schema",
    ]
    for phrase in bad_phrases:
        assert phrase not in lower, (
            f"_FLOWISE_DISCOVER_CONTEXT still contains '{phrase}' — "
            "this is the old instruction that causes per-node get_node calls during discover."
        )


# ---------------------------------------------------------------------------
# 4. _FLOWISE_DISCOVER_CONTEXT explicitly discourages get_node in discover
# ---------------------------------------------------------------------------


def test_discover_context_discourages_get_node():
    """_FLOWISE_DISCOVER_CONTEXT must actively discourage calling get_node during discover."""
    lower = _FLOWISE_DISCOVER_CONTEXT.lower()
    assert "do not call get_node" in lower or "not call get_node" in lower, (
        "_FLOWISE_DISCOVER_CONTEXT does not discourage calling get_node during discover."
    )


# ---------------------------------------------------------------------------
# 5. get_node tool description carries a DISCOVER-phase warning
# ---------------------------------------------------------------------------


def test_get_node_tool_discover_phase_warning():
    """The get_node tool description must warn against calling it during discover."""
    desc = _tool_desc("get_node").upper()
    assert "DISCOVER" in desc, (
        "get_node tool description has no DISCOVER PHASE warning. "
        "The LLM needs this signal to avoid redundant calls."
    )
    assert "DO NOT" in desc or "NOT CALL" in desc or "DO NOT CALL" in desc or "DO NOT" in desc.replace(" ", ""), (
        "get_node tool description does not say 'do not call' in the discover phase context."
    )


# ---------------------------------------------------------------------------
# 6. Known nodes (cache hit) → zero API calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_schema_skips_api_for_known_nodes():
    """When all node types are in the local snapshot, no API call is made."""
    known = {"chatOpenAI", "conversationChain"}
    store = _make_mock_store(known)
    api_called: list[str] = []

    async def _api_fetcher(node_type: str) -> dict:
        api_called.append(node_type)
        return {"name": node_type}

    # Patch execute_tool so the executor never actually gets called
    from flowise_dev_agent.agent import graph as _graph

    with patch.object(_graph, "execute_tool", new=AsyncMock(return_value=MagicMock(ok=False, data=None))):
        schema_cache, repair_events, debug_update = await _repair_schema_for_ops(
            node_names=known,
            node_store=store,
            executor={},
            prior_flowise_debug={},
        )

    assert len(repair_events) == 0, (
        f"Expected 0 repair events for known nodes, got {len(repair_events)}: {repair_events}"
    )
    assert set(schema_cache.keys()) == known, (
        f"schema_cache should contain all known nodes. Got: {set(schema_cache.keys())}"
    )
    assert debug_update == {}, "No debug update expected when all nodes are cache hits"


# ---------------------------------------------------------------------------
# 7. Unknown nodes (cache miss) → exactly one API call per missing type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_schema_calls_api_for_unknown_nodes():
    """Unknown node types trigger exactly one targeted API call each."""
    known: set[str] = set()  # empty snapshot — nothing cached
    store = _make_mock_store(known)
    missing_types = {"brandNewNode", "anotherMissing"}

    # Executor returns a minimal schema dict for any get_node call
    dummy_schema = {"name": "stub", "inputAnchors": [], "inputParams": [], "outputAnchors": []}
    executor = _make_dummy_executor(return_schema=dummy_schema)

    from flowise_dev_agent.agent import graph as _graph

    schema_cache, repair_events, debug_update = await _repair_schema_for_ops(
        node_names=missing_types,
        node_store=store,
        executor=executor,
        prior_flowise_debug={},
    )

    assert len(repair_events) == len(missing_types), (
        f"Expected {len(missing_types)} repair events, got {len(repair_events)}"
    )
    # get_or_repair was called once per missing type
    assert store.get_or_repair.call_count == len(missing_types)
    # debug_update should contain the repair events
    assert "flowise" in debug_update
    assert "knowledge_repair_events" in debug_update["flowise"]
    assert len(debug_update["flowise"]["knowledge_repair_events"]) == len(missing_types)


# ---------------------------------------------------------------------------
# 8. Repair budget enforced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_schema_budget_enforced():
    """Nodes beyond max_repairs are skipped with a warning — budget is hard."""
    # 5 unknown nodes but budget of 2
    unknown = {f"node_{i}" for i in range(5)}
    known: set[str] = set()
    store = _make_mock_store(known)

    dummy_schema = {"name": "stub", "inputAnchors": [], "inputParams": [], "outputAnchors": []}
    executor = _make_dummy_executor(return_schema=dummy_schema)

    schema_cache, repair_events, debug_update = await _repair_schema_for_ops(
        node_names=unknown,
        node_store=store,
        executor=executor,
        prior_flowise_debug={},
        max_repairs=2,
    )

    # At most 2 repair events (budget limit)
    assert len(repair_events) <= 2, (
        f"Budget was 2 but {len(repair_events)} repair events occurred"
    )
    # get_or_repair should have been called only up to budget times
    assert store.get_or_repair.call_count <= 2


# ---------------------------------------------------------------------------
# 9. Empty node_names → empty result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_schema_empty_ops():
    """No AddNode ops → empty schema_cache, zero API calls, empty debug."""
    store = _make_mock_store(known={"chatOpenAI"})

    schema_cache, repair_events, debug_update = await _repair_schema_for_ops(
        node_names=set(),
        node_store=store,
        executor={},
        prior_flowise_debug={},
    )

    assert schema_cache == {}
    assert repair_events == []
    assert debug_update == {}
    store.get_or_repair.assert_not_called()


# ---------------------------------------------------------------------------
# 10. Legacy path (node_store=None) always calls API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_schema_legacy_path_calls_api():
    """When node_store is None (legacy mode), API is always called per node type."""
    node_names = {"chatOpenAI", "bufferMemory"}
    dummy_schema = {"name": "stub", "inputAnchors": [], "inputParams": [], "outputAnchors": []}
    executor = _make_dummy_executor(return_schema=dummy_schema)
    api_call_log: list[str] = []

    from flowise_dev_agent.agent import graph as _graph
    from flowise_dev_agent.agent.tools import ToolResult

    original_execute_tool = _graph.execute_tool

    async def _patched_execute_tool(name, args, executor_):
        if name == "get_node":
            api_call_log.append(args.get("name", ""))
            return ToolResult(ok=True, summary="ok", facts={}, data=dummy_schema, error=None, artifacts=None)
        return await original_execute_tool(name, args, executor_)

    with patch.object(_graph, "execute_tool", side_effect=_patched_execute_tool):
        schema_cache, repair_events, debug_update = await _repair_schema_for_ops(
            node_names=node_names,
            node_store=None,   # legacy path
            executor=executor,
            prior_flowise_debug={},
        )

    # Both nodes should have triggered an API call
    assert set(api_call_log) == node_names, (
        f"Legacy path should call API for all nodes. Called: {api_call_log}"
    )
    assert set(schema_cache.keys()) == node_names
    # No repair events in legacy path (they come from node_store.get_or_repair)
    assert repair_events == []


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_max_schema_repairs_constant():
    """_MAX_SCHEMA_REPAIRS must be a positive integer."""
    assert isinstance(_MAX_SCHEMA_REPAIRS, int)
    assert _MAX_SCHEMA_REPAIRS > 0
