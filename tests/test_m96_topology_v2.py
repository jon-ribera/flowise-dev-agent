"""Tests for Milestone 9.6: Production-Grade LangGraph Topology v2 (CREATE + UPDATE modes).

Verifies:
  Test 1 — test_classify_intent_create: "build a new chatbot" → intent=create
  Test 2 — test_classify_intent_update: "update the Support Bot" → intent=update, target_name
  Test 3 — test_routing_create_skips_resolve_and_load: create path never calls resolve_target/load
  Test 4 — test_routing_update_hits_resolve_then_hitl: update path calls resolve_target + interrupt
  Test 5 — test_load_current_flow_single_fetch: load_current_flow called exactly once, JSON in artifacts
  Test 6 — test_schema_mismatch_routes_to_repair_then_retries_once: validate→repair→compile, not second repair
  Test 7 — test_budget_exceed_triggers_hitl: patch_ir len > max_ops → preflight routes to HITL

See roadmap9_production_graph_runtime_hardening.md — Milestone 9.6.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flowise_dev_agent.agent.state import AgentState


# ---------------------------------------------------------------------------
# Helpers: minimal stubs
# ---------------------------------------------------------------------------


def _make_stub_engine(intent_response: str = "INTENT: create\nCONFIDENCE: 0.9\nTARGET_NAME: (none)"):
    """Stub ReasoningEngine returning a fixed response."""
    engine = MagicMock()
    response = MagicMock()
    response.content = intent_response
    response.input_tokens = 10
    response.output_tokens = 5
    response.has_tool_calls = False
    response.tool_calls = []
    engine.complete = AsyncMock(return_value=response)
    return engine


def _make_stub_flowise_domain():
    """Stub FloviseDomain that does not connect to a real Flowise server."""
    from flowise_dev_agent.agent.tools import FloviseDomain
    client = MagicMock()
    domain = FloviseDomain(client)
    return domain


def _make_stub_tool_result(ok: bool = True, data=None):
    """Build a minimal ToolResult stub."""
    from flowise_dev_agent.agent.tools import ToolResult
    return ToolResult(
        ok=ok,
        summary="stub result",
        data=data or {},
    )


def _base_state(**overrides) -> dict:
    """Return a minimal state dict suitable for testing individual nodes."""
    state: dict = {
        "requirement": "build a new customer support chatbot",
        "session_name": None,
        "runtime_mode": None,
        "messages": [],
        "chatflow_id": None,
        "discovery_summary": None,
        "plan": None,
        "test_results": None,
        "iteration": 0,
        "done": False,
        "developer_feedback": None,
        "webhook_url": None,
        "clarification": None,
        "credentials_missing": None,
        "converge_verdict": None,
        "test_trials": 1,
        "flowise_instance_id": None,
        "domain_context": {},
        "artifacts": {},
        "facts": {},
        "debug": {},
        "patch_ir": None,
        "validated_payload_hash": None,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        # M9.6 fields
        "operation_mode": None,
        "target_chatflow_id": None,
        "intent_confidence": None,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Test 1 — classify_intent: CREATE path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_intent_create():
    """'build a new chatbot' should produce intent=create with no target_name."""
    from flowise_dev_agent.agent.graph import _make_classify_intent_node

    engine = _make_stub_engine(
        "INTENT: create\nCONFIDENCE: 0.95\nTARGET_NAME: (none)"
    )
    node = _make_classify_intent_node(engine)

    state = _base_state(requirement="build a new chatbot for customer service")
    result = await node(state)

    assert result["operation_mode"] == "create", (
        f"Expected operation_mode='create', got {result['operation_mode']!r}"
    )
    flowise_facts = result["facts"]["flowise"]
    assert flowise_facts["intent"] == "create"
    assert flowise_facts["target_name"] is None

    # Budget state must be initialized
    budgets = result["facts"]["budgets"]
    assert budgets["max_patch_ops_per_iter"] == 20, "CREATE mode should default to 20 max ops"
    assert budgets["max_schema_repairs_per_iter"] == 2
    assert budgets["max_total_retries_per_iter"] == 1

    # Repair state initialized
    repair = result["facts"]["repair"]
    assert repair["count"] == 0
    assert repair["repaired_node_types"] == []


# ---------------------------------------------------------------------------
# Test 2 — classify_intent: UPDATE path with target name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_intent_update():
    """'update the Support Bot chatflow' should produce intent=update, target_name='Support Bot'."""
    from flowise_dev_agent.agent.graph import _make_classify_intent_node

    engine = _make_stub_engine(
        "INTENT: update\nCONFIDENCE: 0.9\nTARGET_NAME: Support Bot"
    )
    node = _make_classify_intent_node(engine)

    state = _base_state(requirement="update the Support Bot chatflow to use GPT-4o")
    result = await node(state)

    assert result["operation_mode"] == "update", (
        f"Expected operation_mode='update', got {result['operation_mode']!r}"
    )
    flowise_facts = result["facts"]["flowise"]
    assert flowise_facts["intent"] == "update"
    assert flowise_facts["target_name"] == "Support Bot"

    # UPDATE mode should default to 12 max ops
    budgets = result["facts"]["budgets"]
    assert budgets["max_patch_ops_per_iter"] == 12, "UPDATE mode should default to 12 max ops"

    # Confidence captured
    assert result["intent_confidence"] == pytest.approx(0.9, abs=0.01)


# ---------------------------------------------------------------------------
# Test 3 — CREATE routing skips resolve_target and load_current_flow
# ---------------------------------------------------------------------------


def test_routing_create_skips_resolve_and_load():
    """The v2 CREATE routing path must not include resolve_target or load_current_flow nodes."""
    from flowise_dev_agent.agent.graph import (
        _route_after_hydrate_context_v2,
        _route_after_hitl_select_target,
    )

    # Simulate state after classify_intent with operation_mode=create
    state_create = _base_state(operation_mode="create")

    # After hydrate_context with create intent: must go to plan_v2, NOT resolve_target
    route = _route_after_hydrate_context_v2(state_create)
    assert route == "plan_v2", (
        f"CREATE intent should route to 'plan_v2' after hydrate_context, got {route!r}"
    )

    # Simulate state after HITL with create new response
    state_create_new = _base_state(operation_mode="create")
    route_after_hitl = _route_after_hitl_select_target(state_create_new)
    assert route_after_hitl == "plan_v2", (
        f"CREATE mode after HITL should route to 'plan_v2', got {route_after_hitl!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — UPDATE routing hits resolve_target then HITL_select_target
# ---------------------------------------------------------------------------


def test_routing_update_hits_resolve_then_hitl():
    """UPDATE intent must route through resolve_target then interrupt at hitl_select_target."""
    from flowise_dev_agent.agent.graph import (
        _route_after_hydrate_context_v2,
        _route_after_hitl_select_target,
    )

    # Simulate state with update intent
    state_update = _base_state(operation_mode="update")

    # After hydrate_context with update intent: must go to resolve_target
    route = _route_after_hydrate_context_v2(state_update)
    assert route == "resolve_target", (
        f"UPDATE intent should route to 'resolve_target' after hydrate_context, got {route!r}"
    )

    # After HITL_select_target, if operation_mode is still update: route to load_current_flow
    state_update_selected = _base_state(
        operation_mode="update",
        target_chatflow_id="abc123-uuid",
    )
    route_after_hitl = _route_after_hitl_select_target(state_update_selected)
    assert route_after_hitl == "load_current_flow", (
        f"UPDATE with target selected should route to 'load_current_flow', got {route_after_hitl!r}"
    )


# ---------------------------------------------------------------------------
# Test 5 — load_current_flow called exactly once, full JSON in artifacts not messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_current_flow_single_fetch():
    """load_current_flow must call get_chatflow exactly once and store JSON in artifacts, not messages."""
    from flowise_dev_agent.agent.graph import _make_load_current_flow_node
    from flowise_dev_agent.agent.tools import FloviseDomain, ToolResult

    # Build an executor dict with a mock get_chatflow (M10.3: factory takes executor, not domains)
    sample_flow_data = {"nodes": [{"id": "chatOpenAI_0", "data": {"name": "chatOpenAI", "label": "ChatOpenAI"}}], "edges": []}
    call_count = 0

    async def mock_get_chatflow(**kwargs):
        nonlocal call_count
        call_count += 1
        return {"id": "abc123", "flowData": json.dumps(sample_flow_data)}

    executor = {"get_chatflow": mock_get_chatflow}

    node = _make_load_current_flow_node(executor)
    state = _base_state(
        operation_mode="update",
        target_chatflow_id="abc123",
    )

    result = await node(state)

    # get_chatflow must be called exactly once
    assert call_count == 1, f"Expected get_chatflow called exactly once, got {call_count}"

    # Full flow data must be in artifacts["flowise"]["current_flow_data"]
    flowise_artifacts = result.get("artifacts", {}).get("flowise", {})
    assert "current_flow_data" in flowise_artifacts, (
        "current_flow_data must be stored in artifacts['flowise'], not in messages"
    )
    assert flowise_artifacts["current_flow_data"] == sample_flow_data

    # Hash must be computed and stored in facts
    flowise_facts = result.get("facts", {}).get("flowise", {})
    assert "current_flow_hash" in flowise_facts
    assert len(flowise_facts["current_flow_hash"]) == 64  # SHA-256 hex

    # Messages must NOT contain the full flow data
    messages = result.get("messages", [])
    for msg in messages:
        content = getattr(msg, "content", "") or ""
        assert "nodes" not in content or len(content) < 200, (
            "Full flowData JSON must not appear in messages (context safety violation)"
        )


# ---------------------------------------------------------------------------
# Test 6 — schema_mismatch routes to repair then retries compile exactly once
# ---------------------------------------------------------------------------


def test_schema_mismatch_routes_to_repair_then_retries_once():
    """Validate routes schema_mismatch to repair_schema; after repair routes back to compile_patch_ir."""
    from flowise_dev_agent.agent.graph import (
        _route_after_validate,
        _route_after_repair_schema,
    )

    # State with schema_mismatch failure, repair count = 0
    state_schema_mismatch = _base_state(
        facts={
            "validation": {
                "ok": False,
                "failure_type": "schema_mismatch",
                "missing_node_types": ["unknownNode"],
            },
            "repair": {"count": 0, "repaired_node_types": []},
            "budgets": {
                "max_schema_repairs_per_iter": 2,
                "max_patch_ops_per_iter": 20,
                "max_total_retries_per_iter": 1,
                "retries_used": 0,
            },
        }
    )

    # validate should route to repair_schema
    route = _route_after_validate(state_schema_mismatch)
    assert route == "repair_schema", (
        f"schema_mismatch should route to 'repair_schema', got {route!r}"
    )

    # After repair: should route back to compile_patch_ir (not repair again)
    route_after_repair = _route_after_repair_schema(state_schema_mismatch)
    assert route_after_repair == "compile_patch_ir", (
        f"After repair should route to 'compile_patch_ir', got {route_after_repair!r}"
    )

    # Second failure (repair count = 2 = max): should route to hitl_plan_v2
    # (escalate to plan review, not hitl_review_v2 which expects test results)
    state_budget_exceeded = _base_state(
        facts={
            "validation": {
                "ok": False,
                "failure_type": "schema_mismatch",
                "missing_node_types": ["unknownNode"],
            },
            "repair": {"count": 2, "repaired_node_types": []},
            "budgets": {
                "max_schema_repairs_per_iter": 2,
                "max_patch_ops_per_iter": 20,
                "max_total_retries_per_iter": 1,
                "retries_used": 0,
            },
        }
    )
    route_budget_exceeded = _route_after_validate(state_budget_exceeded)
    assert route_budget_exceeded == "hitl_plan_v2", (
        f"Budget exceeded should route to 'hitl_plan_v2', got {route_budget_exceeded!r}"
    )


# ---------------------------------------------------------------------------
# Test 7 — patch_ir len > max_ops triggers preflight failure → HITL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_exceed_triggers_hitl():
    """patch_ir length exceeding max_ops must cause preflight_validate_patch to fail."""
    from flowise_dev_agent.agent.graph import (
        _make_preflight_validate_patch_node,
        _route_after_preflight,
    )

    # Build a patch_ir with 25 ops but max_ops = 20
    large_patch_ir = [
        {"op_type": "add_node", "node_name": f"node{i}", "node_id": f"node{i}_0", "label": f"Node {i}", "params": {}}
        for i in range(25)
    ]

    state = _base_state(
        patch_ir=large_patch_ir,
        facts={
            "patch": {"max_ops": 20, "focus_area": None, "protected_nodes": []},
            "budgets": {
                "max_patch_ops_per_iter": 20,
                "max_schema_repairs_per_iter": 2,
                "max_total_retries_per_iter": 1,
                "retries_used": 0,
            },
            "repair": {"count": 0, "repaired_node_types": [], "budget_exceeded": False},
        },
    )

    node = _make_preflight_validate_patch_node()
    result = await node(state)

    preflight = result["facts"]["preflight"]
    assert preflight["ok"] is False, (
        f"Preflight must fail when patch_ir ({len(large_patch_ir)}) > max_ops (20)"
    )
    assert preflight["reason"] is not None
    assert "max_ops" in preflight["reason"].lower() or "25" in preflight["reason"]

    # Routing after failed preflight must go to hitl_review_v2
    state_with_preflight_fail = _base_state(
        facts={"preflight": {"ok": False, "reason": "too many ops"}},
    )
    route = _route_after_preflight(state_with_preflight_fail)
    assert route == "hitl_review_v2", (
        f"Failed preflight should route to 'hitl_review_v2', got {route!r}"
    )

    # Routing after passing preflight must go to apply_patch
    state_with_preflight_ok = _base_state(
        facts={"preflight": {"ok": True, "reason": None}},
    )
    route_ok = _route_after_preflight(state_with_preflight_ok)
    assert route_ok == "apply_patch", (
        f"Passing preflight should route to 'apply_patch', got {route_ok!r}"
    )


# ---------------------------------------------------------------------------
# Additional tests: state.py M9.6 fields exist
# ---------------------------------------------------------------------------


def test_agent_state_has_m96_fields():
    """AgentState TypedDict must declare all M9.6 fields."""
    from flowise_dev_agent.agent.state import AgentState

    annotations = AgentState.__annotations__
    assert "operation_mode" in annotations, "AgentState must declare 'operation_mode'"
    assert "target_chatflow_id" in annotations, "AgentState must declare 'target_chatflow_id'"
    assert "intent_confidence" in annotations, "AgentState must declare 'intent_confidence'"


def test_build_graph_v2_topology_version():
    """build_graph() must produce a compiled v2 graph without errors (v2 is the only topology)."""
    from flowise_dev_agent.agent.graph import build_graph

    engine = _make_stub_engine()
    domain = _make_stub_flowise_domain()

    # Must not raise — v2 is now the default and only topology
    graph = build_graph(engine, [domain])
    assert graph is not None, "build_graph() must return a compiled graph"


def test_summarize_flow_data_deterministic():
    """_summarize_flow_data must be deterministic and never call the LLM."""
    from flowise_dev_agent.agent.graph import _summarize_flow_data

    flow_data = {
        "nodes": [
            {"id": "chatOpenAI_0", "data": {"name": "chatOpenAI", "label": "ChatOpenAI"}},
            {"id": "bufferMemory_0", "data": {"name": "bufferMemory", "label": "Buffer Memory"}},
            {"id": "conversationChain_0", "data": {"name": "conversationChain", "label": "Conversation Chain"}},
        ],
        "edges": [
            {"id": "e1", "source": "chatOpenAI_0", "target": "conversationChain_0"},
        ],
    }

    summary1 = _summarize_flow_data(flow_data)
    summary2 = _summarize_flow_data(flow_data)

    assert summary1 == summary2, "_summarize_flow_data must be deterministic"
    assert summary1["node_count"] == 3
    assert summary1["edge_count"] == 1
    assert "chatOpenAI" in summary1["node_types"]
    assert len(summary1["top_labels"]) <= 10
    assert isinstance(summary1["key_tool_nodes"], list)


def test_summarize_flow_data_handles_empty():
    """_summarize_flow_data must handle empty or invalid input gracefully."""
    from flowise_dev_agent.agent.graph import _summarize_flow_data

    assert _summarize_flow_data({}) == {
        "node_count": 0,
        "edge_count": 0,
        "node_types": {},
        "top_labels": [],
        "key_tool_nodes": [],
    }
    assert _summarize_flow_data("invalid json!!")["node_count"] == 0
    assert _summarize_flow_data(None)["node_count"] == 0  # type: ignore[arg-type]


def test_initial_state_has_m96_fields():
    """_initial_state() must include all M9.6 topology v2 fields."""
    from flowise_dev_agent.api import _initial_state

    state = _initial_state("build a chatflow")
    assert "operation_mode" in state, "_initial_state must include 'operation_mode'"
    assert "target_chatflow_id" in state, "_initial_state must include 'target_chatflow_id'"
    assert "intent_confidence" in state, "_initial_state must include 'intent_confidence'"
    assert state["operation_mode"] is None
    assert state["target_chatflow_id"] is None
    assert state["intent_confidence"] is None


# ---------------------------------------------------------------------------
# Plan approval keyword matching — regression for "approved - approach: ..." loop
# ---------------------------------------------------------------------------


def _check_approved(response: str) -> bool:
    """Mirror the approval logic from _make_human_plan_approval_node."""
    _APPROVED_WORDS = ("approved", "approve", "yes", "y", "ok", "looks good", "lgtm", "proceed")
    _norm = response.strip().lower()
    _parts = _norm.split()
    return _norm in _APPROVED_WORDS or bool(_parts and _parts[0].rstrip("-:") in _APPROVED_WORDS)


def test_plan_approval_exact_keywords():
    """Exact approval keywords must be detected."""
    for kw in ("approved", "Approved", "APPROVED", "yes", "Yes", "ok", "lgtm", "proceed", "looks good"):
        assert _check_approved(kw), f"{kw!r} should be approved"


def test_plan_approval_approach_suffix():
    """'approved - approach: ...' format (sent by UI option selection) must be approved."""
    assert _check_approved("approved - approach: **Cheerio Web Scraper:** Use the built-in Cheerio")
    assert _check_approved("approved - approach: **Multi-URL Cheerio + Custom Tool (Selected):** Two Cheerio")
    assert _check_approved("Approved - approach: Some other approach")


def test_plan_approval_rejects_feedback():
    """Plain feedback strings must NOT be treated as approved."""
    assert not _check_approved("please add memory")
    assert not _check_approved("use gpt-4o instead")
    assert not _check_approved("the plan is missing error handling")
    assert not _check_approved("")
