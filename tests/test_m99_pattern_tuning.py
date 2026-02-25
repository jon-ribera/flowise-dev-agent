"""Tests for Milestone 9.9: PatternCapability maturity tuning.

Covers the acceptance tests from the roadmap:
  Test group 1 — Pattern metadata completeness: saved patterns carry all M9.9 fields.
  Test group 2 — _is_pattern_schema_compatible: fingerprint matching logic.
  Test group 3 — UPDATE mode guard: pattern seeding is skipped when operation_mode=="update".
  Test group 4 — success_count field exists and is an integer.
  Test group 5 — _infer_category_from_node_types: category derivation heuristics.
  Test group 6 — search_patterns_filtered returns last_used_at as ISO string.

All tests are fully mocked — no live database or LLM required.

See flowise_dev_agent/agent/pattern_store.py (M9.9 additions).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite file path."""
    return str(tmp_path / "test_m99_patterns.db")


@pytest.fixture
def simple_flow_data() -> str:
    """Minimal valid Flowise flowData JSON with two nodes."""
    return json.dumps({
        "nodes": [
            {
                "id": "chatOpenAI_0",
                "type": "customNode",
                "position": {"x": 100, "y": 100},
                "data": {
                    "id": "chatOpenAI_0",
                    "label": "ChatOpenAI",
                    "name": "chatOpenAI",
                    "type": "ChatOpenAI",
                    "baseClasses": ["BaseChatModel"],
                    "inputAnchors": [],
                    "inputParams": [],
                    "outputAnchors": [],
                    "outputs": {},
                    "inputs": {},
                    "selected": False,
                },
            },
            {
                "id": "conversationChain_0",
                "type": "customNode",
                "position": {"x": 400, "y": 100},
                "data": {
                    "id": "conversationChain_0",
                    "label": "Conversation Chain",
                    "name": "conversationChain",
                    "type": "ConversationChain",
                    "baseClasses": ["BaseChain"],
                    "inputAnchors": [],
                    "inputParams": [],
                    "outputAnchors": [],
                    "outputs": {},
                    "inputs": {},
                    "selected": False,
                },
            },
        ],
        "edges": [],
    })


@pytest.fixture
def rag_flow_data() -> str:
    """Flowise flowData JSON containing a vectorStore node (RAG pattern)."""
    return json.dumps({
        "nodes": [
            {
                "id": "vectorStoreFaiss_0",
                "type": "customNode",
                "position": {"x": 100, "y": 100},
                "data": {
                    "id": "vectorStoreFaiss_0",
                    "label": "Faiss",
                    "name": "vectorStoreFaiss",
                    "type": "Faiss",
                    "baseClasses": ["VectorStore"],
                    "inputAnchors": [],
                    "inputParams": [],
                    "outputAnchors": [],
                    "outputs": {},
                    "inputs": {},
                    "selected": False,
                },
            },
        ],
        "edges": [],
    })


# ---------------------------------------------------------------------------
# Test group 1 — Pattern metadata completeness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pattern_metadata_fields_present(tmp_db, simple_flow_data):
    """Saved pattern must carry domain, node_types, schema_fingerprint, last_used_at fields.

    After save_pattern(), the row should have domain, node_types, category, and
    schema_fingerprint set correctly.  last_used_at is None until apply_as_base_graph()
    is called (side-effect updates it).
    """
    import aiosqlite

    from flowise_dev_agent.agent.pattern_store import PatternStore

    node_types_list = ["chatOpenAI", "conversationChain"]
    store = await PatternStore.open(tmp_db)
    pat_id = await store.save_pattern(
        name="Test Conversational Bot",
        requirement_text="build a customer support chatflow with openai",
        flow_data=simple_flow_data,
        domain="flowise",
        node_types=json.dumps(node_types_list),
        category="conversational",
        schema_fingerprint="fp-abc123",
    )
    await store.close()

    # Verify persistence at the SQL level
    async with aiosqlite.connect(tmp_db) as conn:
        async with conn.execute(
            "SELECT domain, node_types, category, schema_fingerprint, last_used_at, success_count "
            "FROM patterns WHERE id = ?",
            (pat_id,),
        ) as cur:
            row = await cur.fetchone()

    assert row is not None, "Pattern row must exist after save_pattern()"
    domain, node_types_raw, category, fp, last_used_at_raw, success_count = row

    assert domain == "flowise", "domain must be 'flowise'"
    assert json.loads(node_types_raw) == node_types_list, "node_types must be stored as JSON array"
    assert category == "conversational", "category must be stored correctly"
    assert fp == "fp-abc123", "schema_fingerprint must be stored correctly"
    assert last_used_at_raw is None, "last_used_at must be None until apply_as_base_graph() is called"
    assert isinstance(success_count, int), "success_count must be an integer"


@pytest.mark.asyncio
async def test_pattern_last_used_at_updated_after_apply(tmp_db, simple_flow_data):
    """apply_as_base_graph() must set last_used_at to a recent Unix timestamp."""
    import aiosqlite

    from flowise_dev_agent.agent.pattern_store import PatternStore

    store = await PatternStore.open(tmp_db)
    pat_id = await store.save_pattern(
        name="Bot",
        requirement_text="some requirement",
        flow_data=simple_flow_data,
        schema_fingerprint="fp-xyz",
    )
    before_ts = time.time()
    await store.apply_as_base_graph(pat_id)
    after_ts = time.time()
    await store.close()

    async with aiosqlite.connect(tmp_db) as conn:
        async with conn.execute(
            "SELECT last_used_at FROM patterns WHERE id = ?", (pat_id,)
        ) as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row[0] is not None, "last_used_at must be set after apply_as_base_graph()"
    assert before_ts <= float(row[0]) <= after_ts, (
        "last_used_at must be within the before/after window"
    )


# ---------------------------------------------------------------------------
# Test group 2 — _is_pattern_schema_compatible
# ---------------------------------------------------------------------------


def test_schema_compatible_matching_fingerprint():
    """_is_pattern_schema_compatible returns True when fingerprints match."""
    from flowise_dev_agent.agent.pattern_store import _is_pattern_schema_compatible

    pattern = {"schema_fingerprint": "fp-abc123"}
    assert _is_pattern_schema_compatible(pattern, "fp-abc123") is True


def test_schema_incompatible_mismatched_fingerprint():
    """_is_pattern_schema_compatible returns False when fingerprints differ."""
    from flowise_dev_agent.agent.pattern_store import _is_pattern_schema_compatible

    pattern = {"schema_fingerprint": "fp-old"}
    assert _is_pattern_schema_compatible(pattern, "fp-new") is False


def test_schema_compatible_no_stored_fingerprint():
    """_is_pattern_schema_compatible returns True when stored fingerprint is None."""
    from flowise_dev_agent.agent.pattern_store import _is_pattern_schema_compatible

    # Empty string stored fingerprint treated the same as None
    pattern_none = {"schema_fingerprint": None}
    pattern_empty = {"schema_fingerprint": ""}
    pattern_missing = {}

    assert _is_pattern_schema_compatible(pattern_none, "fp-current") is True
    assert _is_pattern_schema_compatible(pattern_empty, "fp-current") is True
    assert _is_pattern_schema_compatible(pattern_missing, "fp-current") is True


def test_schema_compatible_no_current_fingerprint():
    """_is_pattern_schema_compatible returns True when current_fingerprint is None/empty."""
    from flowise_dev_agent.agent.pattern_store import _is_pattern_schema_compatible

    pattern = {"schema_fingerprint": "fp-stored"}

    # Cannot compare, so assume compatible
    assert _is_pattern_schema_compatible(pattern, None) is True
    assert _is_pattern_schema_compatible(pattern, "") is True


def test_schema_compatible_both_none():
    """_is_pattern_schema_compatible returns True when both fingerprints are absent."""
    from flowise_dev_agent.agent.pattern_store import _is_pattern_schema_compatible

    pattern = {}
    assert _is_pattern_schema_compatible(pattern, None) is True


# ---------------------------------------------------------------------------
# Test group 3 — UPDATE mode guard: pattern seeding skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pattern_not_applied_for_update_mode(tmp_db, simple_flow_data):
    """When operation_mode=='update', pattern seeding must be skipped.

    Verifies the UPDATE guard (M9.9 constraint) by calling the plan node's
    pattern seeding logic indirectly:  we set up a PatternStore with a matching
    pattern, then run the plan node with operation_mode='update' and confirm that
    debug['flowise']['pattern_metrics']['pattern_used'] is False.

    The plan node is invoked with a fully-mocked LLM engine so no real LLM call
    is made.
    """
    from flowise_dev_agent.agent.pattern_store import PatternStore
    from flowise_dev_agent.agent.graph import _make_plan_node

    # Seed the pattern store with one matching pattern
    store = await PatternStore.open(tmp_db)
    await store.save_pattern(
        name="Customer Support Bot",
        requirement_text="build customer support chatflow",
        flow_data=simple_flow_data,
        domain="flowise",
        node_types=json.dumps(["chatOpenAI", "conversationChain"]),
        category="conversational",
        schema_fingerprint="fp-abc",
    )
    await store.close()

    # Reopen for use in plan node
    store = await PatternStore.open(tmp_db)

    # Build a fake LLM engine that returns a canned plan
    fake_response = MagicMock()
    fake_response.content = "## PLAN\n1. GOAL\nBuild a chatflow.\n"
    fake_response.input_tokens = 10
    fake_response.output_tokens = 20
    fake_engine = AsyncMock()
    fake_engine.complete = AsyncMock(return_value=fake_response)

    plan_node = _make_plan_node(
        engine=fake_engine,
        domains=[],
        pattern_store=store,
        template_store=None,
    )

    state = {
        "requirement": "build customer support chatflow",
        "iteration": 0,
        "chatflow_id": None,
        "operation_mode": "update",  # <-- this must suppress pattern seeding
        "developer_feedback": None,
        "plan": None,
        "facts": {},
        "artifacts": {},
        "debug": {},
        "messages": [],
        "discovery_summary": "Found existing chatflow.",
        "converge_verdict": None,
    }

    result = await plan_node(state)

    await store.close()

    # The pattern_metrics key must be present and pattern_used must be False
    debug_flowise = result.get("debug", {}).get("flowise", {})
    pattern_metrics = debug_flowise.get("pattern_metrics", {})
    assert "pattern_metrics" in debug_flowise, (
        "debug['flowise']['pattern_metrics'] must be present even when pattern is skipped"
    )
    assert pattern_metrics.get("pattern_used") is False, (
        "pattern_used must be False when operation_mode == 'update'"
    )
    assert pattern_metrics.get("pattern_id") is None, (
        "pattern_id must be None when pattern seeding is skipped"
    )


@pytest.mark.asyncio
async def test_pattern_applied_for_create_mode(tmp_db, simple_flow_data):
    """When operation_mode is not 'update', pattern seeding proceeds as normal.

    Verifies that a saved pattern IS used when operation_mode is absent (CREATE mode).
    """
    from flowise_dev_agent.agent.pattern_store import PatternStore
    from flowise_dev_agent.agent.graph import _make_plan_node

    store = await PatternStore.open(tmp_db)
    await store.save_pattern(
        name="Support Bot",
        requirement_text="build customer support chatflow",
        flow_data=simple_flow_data,
        domain="flowise",
        node_types=json.dumps(["chatOpenAI", "conversationChain"]),
        category="conversational",
        schema_fingerprint="fp-abc",
    )
    await store.close()

    store = await PatternStore.open(tmp_db)

    fake_response = MagicMock()
    fake_response.content = "## PLAN\n1. GOAL\nBuild a chatflow.\n"
    fake_response.input_tokens = 10
    fake_response.output_tokens = 20
    fake_engine = AsyncMock()
    fake_engine.complete = AsyncMock(return_value=fake_response)

    plan_node = _make_plan_node(
        engine=fake_engine,
        domains=[],
        pattern_store=store,
        template_store=None,
    )

    state = {
        "requirement": "build customer support chatflow",
        "iteration": 0,
        "chatflow_id": None,
        "operation_mode": None,  # <-- CREATE mode (absent or None)
        "developer_feedback": None,
        "plan": None,
        "facts": {},
        "artifacts": {},
        "debug": {},
        "messages": [],
        "discovery_summary": "No existing chatflow found.",
        "converge_verdict": None,
    }

    result = await plan_node(state)
    await store.close()

    debug_flowise = result.get("debug", {}).get("flowise", {})
    pattern_metrics = debug_flowise.get("pattern_metrics", {})
    # Pattern should have been used (nodes exist in flow_data)
    assert pattern_metrics.get("pattern_used") is True, (
        "pattern_used must be True when a matching pattern exists and operation_mode is not 'update'"
    )
    assert pattern_metrics.get("pattern_id") is not None, (
        "pattern_id must be set when a pattern was applied"
    )
    assert pattern_metrics.get("ops_in_base", 0) > 0, (
        "ops_in_base must reflect the node count from the seeded pattern"
    )


# ---------------------------------------------------------------------------
# Test group 4 — success_count is an integer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_count_increments(tmp_db, simple_flow_data):
    """success_count must default to 1 on insert and increment on each apply_as_base_graph call."""
    import aiosqlite

    from flowise_dev_agent.agent.pattern_store import PatternStore

    store = await PatternStore.open(tmp_db)
    pat_id = await store.save_pattern(
        name="RAG Bot",
        requirement_text="build rag chatflow",
        flow_data=simple_flow_data,
    )

    # Read initial value
    async with aiosqlite.connect(tmp_db) as conn:
        async with conn.execute(
            "SELECT success_count FROM patterns WHERE id = ?", (pat_id,)
        ) as cur:
            row = await cur.fetchone()

    assert isinstance(row[0], int), "success_count must be an integer"
    assert row[0] == 1, "success_count must start at 1"

    # apply_as_base_graph increments it
    await store.apply_as_base_graph(pat_id)

    async with aiosqlite.connect(tmp_db) as conn:
        async with conn.execute(
            "SELECT success_count FROM patterns WHERE id = ?", (pat_id,)
        ) as cur:
            row2 = await cur.fetchone()

    assert isinstance(row2[0], int), "success_count must remain an integer after increment"
    assert row2[0] == 2, "success_count must be 2 after one apply_as_base_graph call"

    await store.close()


@pytest.mark.asyncio
async def test_increment_success_explicit(tmp_db, simple_flow_data):
    """increment_success() must bump success_count by 1."""
    import aiosqlite

    from flowise_dev_agent.agent.pattern_store import PatternStore

    store = await PatternStore.open(tmp_db)
    pat_id = await store.save_pattern(
        name="Bot",
        requirement_text="test requirement",
        flow_data=simple_flow_data,
    )
    await store.increment_success(pat_id)
    await store.increment_success(pat_id)
    await store.close()

    async with aiosqlite.connect(tmp_db) as conn:
        async with conn.execute(
            "SELECT success_count FROM patterns WHERE id = ?", (pat_id,)
        ) as cur:
            row = await cur.fetchone()

    assert isinstance(row[0], int)
    assert row[0] == 3, "success_count must be 3 (1 initial + 2 increments)"


# ---------------------------------------------------------------------------
# Test group 5 — _infer_category_from_node_types heuristics
# ---------------------------------------------------------------------------


def test_infer_category_rag():
    """Node types containing vectorStore → 'rag' category."""
    from flowise_dev_agent.agent.pattern_store import _infer_category_from_node_types

    assert _infer_category_from_node_types(["chatOpenAI", "vectorStoreFaiss"]) == "rag"
    assert _infer_category_from_node_types(["vectorStoreChroma", "openAIEmbeddings"]) == "rag"


def test_infer_category_tool_agent():
    """Node types containing toolAgent → 'tool_agent' category."""
    from flowise_dev_agent.agent.pattern_store import _infer_category_from_node_types

    assert _infer_category_from_node_types(["toolAgent", "chatOpenAI", "calculator"]) == "tool_agent"


def test_infer_category_conversational():
    """chatOpenAI + conversationChain → 'conversational' category."""
    from flowise_dev_agent.agent.pattern_store import _infer_category_from_node_types

    assert _infer_category_from_node_types(["chatOpenAI", "conversationChain"]) == "conversational"
    assert _infer_category_from_node_types(["chatAnthropic", "conversationChain"]) == "conversational"


def test_infer_category_custom_fallback():
    """Unrecognised node combination → 'custom' category."""
    from flowise_dev_agent.agent.pattern_store import _infer_category_from_node_types

    assert _infer_category_from_node_types(["someNode", "anotherNode"]) == "custom"
    assert _infer_category_from_node_types([]) == "custom"


def test_infer_category_rag_takes_priority_over_conversational():
    """RAG detection must take priority over conversational detection."""
    from flowise_dev_agent.agent.pattern_store import _infer_category_from_node_types

    # Both vectorStore and conversationChain present → rag wins
    result = _infer_category_from_node_types(
        ["chatOpenAI", "vectorStoreFaiss", "conversationChain"]
    )
    assert result == "rag", "rag must take priority over conversational"


# ---------------------------------------------------------------------------
# Test group 6 — search_patterns_filtered returns last_used_at as ISO string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_used_at_none_before_apply(tmp_db, simple_flow_data):
    """search_patterns_filtered must return last_used_at=None when pattern has never been used."""
    from flowise_dev_agent.agent.pattern_store import PatternStore

    store = await PatternStore.open(tmp_db)
    await store.save_pattern(
        name="Fresh Bot",
        requirement_text="build fresh chatflow",
        flow_data=simple_flow_data,
        domain="flowise",
    )
    results = await store.search_patterns_filtered("fresh chatflow", domain="flowise", limit=1)
    await store.close()

    assert results, "Expected at least one search result"
    assert results[0]["last_used_at"] is None, (
        "last_used_at must be None for a pattern that has never been applied"
    )


@pytest.mark.asyncio
async def test_last_used_at_iso_string_after_apply(tmp_db, simple_flow_data):
    """search_patterns_filtered must return last_used_at as an ISO-8601 string after apply."""
    from flowise_dev_agent.agent.pattern_store import PatternStore

    store = await PatternStore.open(tmp_db)
    pat_id = await store.save_pattern(
        name="Used Bot",
        requirement_text="build used chatflow",
        flow_data=simple_flow_data,
        domain="flowise",
    )
    await store.apply_as_base_graph(pat_id)
    results = await store.search_patterns_filtered("used chatflow", domain="flowise", limit=1)
    await store.close()

    assert results, "Expected at least one search result"
    last_used_at = results[0]["last_used_at"]
    assert last_used_at is not None, "last_used_at must not be None after apply_as_base_graph()"
    assert isinstance(last_used_at, str), "last_used_at must be a string (ISO-8601)"

    # Must parse as a valid datetime
    parsed = datetime.datetime.fromisoformat(last_used_at)
    assert parsed.tzinfo is not None, "last_used_at ISO string must include timezone info"
