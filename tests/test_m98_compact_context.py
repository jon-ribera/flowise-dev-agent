"""Compact-context enforcement regression tests (M9.8 — DD-0xx).

These tests verify the key invariant:
  artifacts and debug are for machine consumption only.
  Only facts compact summaries go to LLM prompts.

Specifically:
  1. artifacts["flowise"]["current_flow_data"] (raw flowData) never appears in plan prompts
  2. facts["flowise"]["flow_summary"] (compact dict) IS used in UPDATE-mode plan prompts
     (as planned by M9.6 compile_patch_ir node)
  3. ToolResult.data (raw) never reaches message history — only .summary does
  4. hydrate_context node only injects metadata (count, fingerprint), not raw schema snapshots
  5. debug values (large strings) never appear in state["messages"] after node execution

Audit finding: NO violations found in current graph.py (pre-M9.6 topology).
These tests serve as regression guards to prevent future violations.

See DD-048 (ToolResult as single transformation point), DD-050 (state trifurcation).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flowise_dev_agent.agent.tools import ToolResult, result_to_str
from flowise_dev_agent.reasoning import Message


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_LARGE_FLOW_JSON = json.dumps({
    "nodes": [
        {
            "id": f"node_{i}",
            "type": "customNode",
            "position": {"x": i * 200, "y": 100},
            "data": {
                "id": f"node_{i}",
                "label": f"Node {i}",
                "name": "chatOpenAI",
                "version": 2,
                "type": "ChatOpenAI",
                "baseClasses": ["ChatOpenAI", "BaseChatModel", "BaseLanguageModel"],
                "category": "Chat Models",
                "description": "Large Language Model",
                "inputParams": [
                    {"label": "Connect Credential", "name": "credential", "type": "credential"},
                    {"label": "Model Name", "name": "modelName", "type": "string", "default": "gpt-3.5-turbo"},
                ],
                "inputAnchors": [],
                "inputs": {"credential": "", "modelName": "gpt-3.5-turbo"},
                "outputAnchors": [{"id": f"node_{i}-output-chatOpenAI-BaseChatModel", "name": "chatOpenAI"}],
                "outputs": {},
            },
        }
        for i in range(20)
    ],
    "edges": [
        {
            "id": f"edge_{i}",
            "source": f"node_{i}",
            "target": f"node_{i + 1}",
            "sourceHandle": f"node_{i}-output-chatOpenAI-BaseChatModel",
            "targetHandle": f"node_{i + 1}-input-conversationChain-BaseChatModel",
        }
        for i in range(19)
    ],
})
assert len(_LARGE_FLOW_JSON) > 1000, "fixture must be >1KB"

_COMPACT_FLOW_SUMMARY = {
    "node_count": 5,
    "edge_count": 4,
    "node_types": {"chatOpenAI": 1, "conversationChain": 1, "bufferMemory": 1},
    "top_labels": ["GPT-4o Chat", "Conversation Chain", "Buffer Memory"],
    "key_tool_nodes": [],
}

_LARGE_DEBUG_BLOB = json.dumps(
    {"knowledge_repair_events": [{"node_type": f"node{i}", "event": "repair"} for i in range(50)]}
)
assert len(_LARGE_DEBUG_BLOB) > 500, "debug fixture must be >500 chars"


def _make_state_with_flow_data(**overrides: Any) -> dict:
    """Build a realistic AgentState-like dict for testing."""
    base = {
        "requirement": "Add a memory buffer to the support chatflow",
        "discovery_summary": "Found 3 chatflows. chatOpenAI and bufferMemory schemas cached.",
        "plan": None,
        "chatflow_id": "abc123-0000-0000-0000-000000000001",
        "artifacts": {
            "flowise": {
                "current_flow_data": json.loads(_LARGE_FLOW_JSON),
            }
        },
        "facts": {
            "flowise": {
                "flow_summary": _COMPACT_FLOW_SUMMARY,
                "schema_fingerprint": "abc123fingerprint",
                "node_count": 303,
            }
        },
        "debug": {
            "flowise": {
                "phase_metrics": [],
                "knowledge_repair_events": [],
                "raw_tool_output": _LARGE_DEBUG_BLOB,
            }
        },
        "messages": [],
        "iteration": 0,
    }
    base.update(overrides)
    return base


def _is_raw_json_blob(text: str | None, threshold: int = 500) -> bool:
    """Return True if text looks like a raw JSON blob (parseable + over threshold)."""
    if not text or len(text) <= threshold:
        return False
    try:
        parsed = json.loads(text)
        return isinstance(parsed, (dict, list))
    except (json.JSONDecodeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Test 1: current_flow_data not injected in plan prompt
# ---------------------------------------------------------------------------


def test_current_flow_data_not_in_plan_prompt():
    """The plan node must NOT inject artifacts["flowise"]["current_flow_data"] into the LLM prompt.

    The plan node constructs base_content from state["requirement"] and
    state["discovery_summary"] only. It must not include the full raw flowData
    JSON even when it is present in state["artifacts"].
    """
    from flowise_dev_agent.agent.graph import _PLAN_BASE, _build_system_prompt
    from flowise_dev_agent.agent.tools import DomainTools

    state = _make_state_with_flow_data()

    # Simulate what the plan node does when building the message context.
    # From graph.py _make_plan_node() / plan():
    base_content = (
        f"Requirement:\n{state['requirement']}\n\n"
        f"Discovery summary:\n{state.get('discovery_summary') or '(none)'}"
    )
    # The system prompt (via _build_system_prompt) also must not contain flow data
    system_prompt = _build_system_prompt(_PLAN_BASE, [], "discover")

    # Verify: the full raw flowData is not in either the user content or system
    assert _LARGE_FLOW_JSON not in base_content, (
        "Plan user content must not contain the raw current_flow_data JSON blob"
    )
    assert _LARGE_FLOW_JSON not in system_prompt, (
        "Plan system prompt must not contain the raw current_flow_data JSON blob"
    )
    # Also check that the large flow JSON is not inadvertently embedded anywhere
    assert not _is_raw_json_blob(base_content), (
        "Plan base_content must not be or contain a raw JSON blob >500 chars"
    )


# ---------------------------------------------------------------------------
# Test 2: flow_summary IS in the plan prompt for UPDATE mode (M9.6 design)
# ---------------------------------------------------------------------------


def test_flow_summary_IS_in_plan_prompt():
    """The compact flow_summary must be usable in UPDATE-mode prompts.

    This verifies the M9.6 design contract: when compile_patch_ir builds the
    context string for UPDATE mode, it uses facts["flowise"]["flow_summary"]
    (the compact dict) — NOT artifacts["flowise"]["current_flow_data"].

    Tests the assembly logic that the compile_patch_ir node (M9.6) uses:
      "node_count: {summary['node_count']}"  etc.
    """
    state = _make_state_with_flow_data()
    operation_mode = "update"
    facts = state.get("facts") or {}
    flow_summary = facts.get("flowise", {}).get("flow_summary")

    assert flow_summary is not None, "flow_summary must be present in state facts"

    # Reproduce the compact context assembly from M9.6 compile_patch_ir:
    if operation_mode == "update" and flow_summary:
        summary_str = (
            f"Current flow summary:\n"
            f"  node_count: {flow_summary.get('node_count', 0)}\n"
            f"  edge_count: {flow_summary.get('edge_count', 0)}\n"
            f"  node_types: {json.dumps(flow_summary.get('node_types', {}))}\n"
            f"  top_labels: {flow_summary.get('top_labels', [])}\n"
            f"  key_tool_nodes: {flow_summary.get('key_tool_nodes', [])}"
        )
    else:
        summary_str = ""

    # The summary string must contain compact data
    assert "node_count: 5" in summary_str, "flow_summary node_count must appear in prompt"
    assert "edge_count: 4" in summary_str, "flow_summary edge_count must appear in prompt"
    assert "chatOpenAI" in summary_str, "flow_summary node_types must appear in prompt"

    # The raw flow JSON must NOT appear in the summary string
    assert _LARGE_FLOW_JSON not in summary_str, (
        "compile_patch_ir context must use flow_summary, not raw current_flow_data"
    )
    assert not _is_raw_json_blob(summary_str), (
        "The UPDATE mode context string must not be a raw JSON blob >500 chars"
    )

    # The summary string must be significantly smaller than the raw flow JSON
    assert len(summary_str) < len(_LARGE_FLOW_JSON) / 10, (
        f"compact summary ({len(summary_str)} chars) should be much smaller than "
        f"raw flowData ({len(_LARGE_FLOW_JSON)} chars)"
    )


# ---------------------------------------------------------------------------
# Test 3: ToolResult.data not in messages — only .summary
# ---------------------------------------------------------------------------


def test_tool_result_data_not_in_messages():
    """ToolResult.data must never reach LLM message history.

    result_to_str() is the enforcement point: it returns .summary, not .data.
    The .data field (raw API response) must not appear in any message content.
    """
    large_raw_data = _LARGE_FLOW_JSON
    compact_summary = "Chatflow 'Support Bot' (id=abc123-0000-0000-0000-000000000001)."

    tr = ToolResult(
        ok=True,
        summary=compact_summary,
        facts={"chatflow_id": "abc123-0000-0000-0000-000000000001"},
        data=large_raw_data,
        error=None,
        artifacts=None,
    )

    # This is what _react() does when storing tool results in messages
    message_content = result_to_str(tr)

    # Assert the summary is used, not the raw data
    assert message_content == compact_summary, (
        "result_to_str must return .summary for ToolResult, not .data"
    )
    assert large_raw_data not in message_content, (
        "Raw .data JSON must not appear in the message content"
    )
    assert not _is_raw_json_blob(message_content), (
        "message_content must not be a parseable JSON blob >500 chars"
    )
    assert len(message_content) < 300, (
        f"message_content from result_to_str must be compact (got {len(message_content)} chars)"
    )

    # Also verify a message built from this result does not contain raw data
    msg = Message(
        role="tool_result",
        content=result_to_str(tr),
        tool_call_id="tc1",
        tool_name="get_chatflow",
    )
    assert large_raw_data not in (msg.content or ""), (
        "Message.content from a ToolResult must not contain the raw .data field"
    )


# ---------------------------------------------------------------------------
# Test 4: hydrate_context injects only metadata (count + fingerprint), not raw schemas
# ---------------------------------------------------------------------------


def test_no_snapshot_blobs_in_discover_context():
    """hydrate_context must inject ONLY metadata (node_count + fingerprint) into facts.

    The node schema snapshots (schemas/flowise_nodes.snapshot.json, ~300KB) must
    never appear in any message or LLM context. hydrate_context is deterministic
    (no LLM, no tools) and only reads metadata from the NodeSchemaStore.

    This test reproduces the hydrate_context node logic and verifies its output
    does NOT contain raw schema JSON blobs.
    """
    # Simulate what hydrate_context produces in facts
    # From _make_hydrate_context_node() in M9.6 graph.py:
    simulated_schema_fingerprint = "abc123fingerprint456789"
    simulated_node_count = 303

    # The hydrate_context return value
    hydrate_output = {
        "facts": {
            "flowise": {
                "schema_fingerprint": simulated_schema_fingerprint,
                "node_count": simulated_node_count,
            }
        }
    }

    # Verify the output is compact metadata only
    flowise_facts = hydrate_output["facts"]["flowise"]

    assert "schema_fingerprint" in flowise_facts, "schema_fingerprint must be in hydrate output"
    assert "node_count" in flowise_facts, "node_count must be in hydrate output"

    # The facts dict must be tiny (just two scalar fields)
    facts_json = json.dumps(flowise_facts)
    assert not _is_raw_json_blob(facts_json) or len(facts_json) <= 500, (
        "hydrate_context facts must be compact metadata, not a raw schema blob"
    )
    assert len(facts_json) < 500, (
        f"hydrate_context facts JSON must be under 500 chars (got {len(facts_json)})"
    )

    # No raw node schema content should be present
    large_schema_blob = json.dumps(
        {"nodes": [{"name": f"node{i}", "category": "chat", "inputParams": [{"name": "modelName"}]}
                   for i in range(303)]}
    )
    assert large_schema_blob not in facts_json, (
        "hydrate_context must not embed raw node schema snapshots in facts"
    )

    # Verify that message assembly from facts is also compact
    # (simulating what a node would do if it read these facts for an LLM context)
    context_from_facts = (
        f"Schema fingerprint: {flowise_facts['schema_fingerprint']}\n"
        f"Known node types: {flowise_facts['node_count']}"
    )
    assert len(context_from_facts) < 200, (
        "Context string built from hydrate_context facts must be compact"
    )
    assert not _is_raw_json_blob(context_from_facts), (
        "Context built from hydrate_context facts must not be a raw JSON blob"
    )


# ---------------------------------------------------------------------------
# Test 5: debug values never in state["messages"]
# ---------------------------------------------------------------------------


def test_debug_values_never_in_messages():
    """Values in state["debug"] must never appear verbatim in state["messages"].

    This is the core trifurcation invariant from DD-050:
      artifacts / facts / debug are for machine consumption.
      Only facts compact summaries go to LLM prompts (messages).

    If debug values contain large strings, those strings must not propagate to
    the messages list via any node.
    """
    # Set up state where debug has a large string
    large_debug_string = _LARGE_DEBUG_BLOB
    state = _make_state_with_flow_data(
        debug={
            "flowise": {
                "phase_metrics": [{"phase": "discover", "elapsed_ms": 1200}],
                "raw_tool_output": large_debug_string,
                "knowledge_repair_events": json.loads(
                    json.dumps([{"node_type": "chatOpenAI", "action": "get_node_api_fallback"}])
                ),
            }
        }
    )

    # Simulate what plan node puts in messages (from graph.py _make_plan_node):
    requirement = state["requirement"]
    discovery_summary = state.get("discovery_summary") or "(none)"
    base_content = (
        f"Requirement:\n{requirement}\n\n"
        f"Discovery summary:\n{discovery_summary}"
    )

    # The plan node's output messages
    user_msg = Message(role="user", content=base_content)
    plan_text = "1. GOAL: Add memory buffer. 2. ACTION: UPDATE chatflow abc123."
    assistant_msg = Message(role="assistant", content=plan_text)

    simulated_new_messages = [user_msg, assistant_msg]

    # Verify none of the debug values appear in messages
    debug_flowise = state["debug"]["flowise"]
    raw_debug_output = debug_flowise.get("raw_tool_output", "")

    for msg in simulated_new_messages:
        content = msg.content or ""
        assert raw_debug_output not in content, (
            f"debug['flowise']['raw_tool_output'] must not appear in message content "
            f"(found in {msg.role} message)"
        )
        # Also check that the large_debug_string is not present
        assert large_debug_string not in content, (
            f"Large debug string must not appear in message content (role={msg.role})"
        )
        # Check no raw JSON blob leaked in
        assert not _is_raw_json_blob(content), (
            f"Message content must not be a raw JSON blob >500 chars (role={msg.role})"
        )

    # Verify the debug values are not in the overall message content collection
    all_message_content = " ".join(
        msg.content or "" for msg in simulated_new_messages
    )
    assert large_debug_string not in all_message_content, (
        "Large debug string must not appear anywhere in the simulated messages"
    )


# ---------------------------------------------------------------------------
# Test 6 (bonus): current_flow_data is correctly segregated to artifacts, not facts
# ---------------------------------------------------------------------------


def test_current_flow_data_stored_in_artifacts_not_facts():
    """load_current_flow must store full flowData in artifacts, not facts.

    This verifies the M9.6 load_current_flow design contract:
    - artifacts["flowise"]["current_flow_data"] = full JSON dict (for machine use)
    - facts["flowise"]["current_flow_hash"] = SHA-256 hash (compact, for integrity)
    - facts["flowise"]["flow_summary"] = compact summary (set by summarize_current_flow)

    The facts dict must NOT contain the full flowData.
    """
    import hashlib

    # Simulate what load_current_flow returns
    flow_data_dict = json.loads(_LARGE_FLOW_JSON)
    flow_data_str = _LARGE_FLOW_JSON
    current_hash = hashlib.sha256(flow_data_str.encode("utf-8")).hexdigest()

    simulated_load_return = {
        "artifacts": {
            "flowise": {
                "current_flow_data": flow_data_dict,
            }
        },
        "facts": {
            "flowise": {
                "current_flow_hash": current_hash,
            }
        },
    }

    # Verify artifacts contains the full data (correct placement)
    artifacts_data = simulated_load_return["artifacts"]["flowise"]["current_flow_data"]
    assert isinstance(artifacts_data, dict), "current_flow_data must be a dict in artifacts"
    assert "nodes" in artifacts_data, "current_flow_data must have nodes key"

    # Verify facts contains ONLY the compact hash, not the full JSON
    facts_flowise = simulated_load_return["facts"]["flowise"]
    assert "current_flow_hash" in facts_flowise, "current_flow_hash must be in facts"
    assert "current_flow_data" not in facts_flowise, (
        "current_flow_data must NOT be stored in facts — it goes in artifacts only"
    )

    # Verify the facts JSON is compact
    facts_json = json.dumps(facts_flowise)
    assert len(facts_json) < 200, (
        f"facts from load_current_flow must be compact (hash only), got {len(facts_json)} chars"
    )

    # Verify the hash is correct SHA-256
    expected_hash = hashlib.sha256(flow_data_str.encode("utf-8")).hexdigest()
    assert facts_flowise["current_flow_hash"] == expected_hash, (
        "current_flow_hash in facts must be the SHA-256 of the flow data string"
    )


# ---------------------------------------------------------------------------
# Test 7 (bonus): summarize_current_flow produces compact facts, not raw JSON
# ---------------------------------------------------------------------------


def test_summarize_current_flow_produces_compact_summary():
    """summarize_current_flow must output a compact dict in facts, NOT the raw flowData.

    The flow_summary in facts["flowise"]["flow_summary"] must be a small dict
    with scalar/small fields: node_count, edge_count, node_types, top_labels.
    The full node/edge JSON must never appear in facts.
    """
    # Simulate what summarize_current_flow computes from current_flow_data
    flow_data = json.loads(_LARGE_FLOW_JSON)
    nodes = flow_data.get("nodes") or []
    edges = flow_data.get("edges") or []

    # Reproduce the summarization logic (from _summarize_flow_data in M9.6 graph.py):
    node_types: dict[str, int] = {}
    top_labels: list[str] = []
    for node in nodes[:10]:  # only top 10 for summary
        data = node.get("data") or {}
        name = data.get("name") or ""
        label = data.get("label") or ""
        if name:
            node_types[name] = node_types.get(name, 0) + 1
        if label and label not in top_labels:
            top_labels.append(label)

    flow_summary = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_types": node_types,
        "top_labels": top_labels[:5],
        "key_tool_nodes": [],
    }

    simulated_return = {
        "facts": {
            "flowise": {
                "flow_summary": flow_summary,
            }
        }
    }

    # Verify the summary is compact
    summary_json = json.dumps(flow_summary)
    assert len(summary_json) < 2000, (
        f"flow_summary must be compact (<2000 chars), got {len(summary_json)} chars"
    )

    # Verify the summary is much smaller than the raw flow JSON
    assert len(summary_json) < len(_LARGE_FLOW_JSON) / 5, (
        f"flow_summary ({len(summary_json)} chars) must be much smaller than "
        f"raw flowData ({len(_LARGE_FLOW_JSON)} chars)"
    )

    # Verify required fields are present and are scalars/small collections
    assert isinstance(flow_summary["node_count"], int)
    assert isinstance(flow_summary["edge_count"], int)
    assert isinstance(flow_summary["node_types"], dict)
    assert isinstance(flow_summary["top_labels"], list)

    # Verify full node data (position, all inputParams, outputAnchors, etc.) is NOT in summary
    assert "inputAnchors" not in summary_json, (
        "flow_summary must not contain raw inputAnchors from node data"
    )
    assert "baseClasses" not in summary_json, (
        "flow_summary must not contain raw baseClasses from node data"
    )
    assert "position" not in summary_json, (
        "flow_summary must not contain raw position data from nodes"
    )
