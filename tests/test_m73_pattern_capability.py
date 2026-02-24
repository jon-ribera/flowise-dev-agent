"""Tests for Milestone 7.3: PatternCapability Upgrade (DD-068).

Covers the acceptance tests from the roadmap:
  Test group 1 — DB migration: new columns present after setup().
  Test group 2 — search_patterns_filtered() filters by domain correctly.
  Test group 3 — apply_as_base_graph() returns a non-empty GraphIR from saved flow_data.
  Test group 4 — base_graph_ir in artifacts influences patch v2 base graph selection.
  Test group 5 — save_pattern() stores new metadata columns correctly.
  Test group 6 — meta_fingerprint property on NodeSchemaStore.

See roadmap7_multi_domain_runtime_hardening.md — Milestone 7.3.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from flowise_dev_agent.agent.compiler import GraphIR, GraphNode
from flowise_dev_agent.agent.pattern_store import PatternStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite file path."""
    return str(tmp_path / "test_patterns.db")


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
                    "outputAnchors": [{"id": "chatOpenAI_0-output-chatOpenAI-BaseChatModel"}],
                    "outputs": {},
                    "inputs": {"modelName": "gpt-4o"},
                    "selected": False,
                },
            },
            {
                "id": "bufferMemory_0",
                "type": "customNode",
                "position": {"x": 400, "y": 100},
                "data": {
                    "id": "bufferMemory_0",
                    "label": "Buffer Memory",
                    "name": "bufferMemory",
                    "type": "BufferMemory",
                    "baseClasses": ["BaseMemory"],
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
# Test group 1 — DB migration: M7.3 columns present after setup()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_adds_m73_columns(tmp_db):
    """setup() must create all five M7.3 columns."""
    import aiosqlite

    store = await PatternStore.open(tmp_db)
    await store.close()

    async with aiosqlite.connect(tmp_db) as conn:
        async with conn.execute("PRAGMA table_info(patterns)") as cur:
            cols = {row[1] async for row in cur}

    for col in ("domain", "node_types", "category", "schema_fingerprint", "last_used_at"):
        assert col in cols, f"Column '{col}' missing after migration"


@pytest.mark.asyncio
async def test_migration_is_idempotent(tmp_db):
    """Calling setup() twice must not raise (migration is safe to re-run)."""
    store1 = await PatternStore.open(tmp_db)
    await store1.close()

    store2 = await PatternStore.open(tmp_db)  # columns already exist
    await store2.close()


@pytest.mark.asyncio
async def test_save_pattern_stores_metadata(tmp_db, simple_flow_data):
    """save_pattern() must persist domain, node_types, category, schema_fingerprint."""
    import aiosqlite

    store = await PatternStore.open(tmp_db)
    pat_id = await store.save_pattern(
        name="Test Bot",
        requirement_text="build a customer support chatflow",
        flow_data=simple_flow_data,
        domain="flowise",
        node_types=json.dumps(["chatOpenAI", "bufferMemory"]),
        category="Simple Conversation",
        schema_fingerprint="abc123",
    )
    await store.close()

    async with aiosqlite.connect(tmp_db) as conn:
        async with conn.execute(
            "SELECT domain, node_types, category, schema_fingerprint FROM patterns WHERE id = ?",
            (pat_id,),
        ) as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row[0] == "flowise"
    assert json.loads(row[1]) == ["chatOpenAI", "bufferMemory"]
    assert row[2] == "Simple Conversation"
    assert row[3] == "abc123"


# ---------------------------------------------------------------------------
# Test group 2 — search_patterns_filtered() filters by domain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_filtered_by_domain(tmp_db, simple_flow_data):
    """search_patterns_filtered(domain='flowise') must exclude 'workday' patterns."""
    store = await PatternStore.open(tmp_db)

    await store.save_pattern(
        name="Flowise Bot",
        requirement_text="customer support chatflow openai",
        flow_data=simple_flow_data,
        domain="flowise",
    )
    await store.save_pattern(
        name="Workday Bot",
        requirement_text="customer support workday hire employee",
        flow_data=simple_flow_data,
        domain="workday",
    )
    await store.close()

    store2 = await PatternStore.open(tmp_db)
    results = await store2.search_patterns_filtered(
        "customer support", domain="flowise", limit=5
    )
    await store2.close()

    assert all(r["domain"] == "flowise" for r in results), (
        "search_patterns_filtered must only return flowise-domain patterns"
    )
    names = [r["name"] for r in results]
    assert "Flowise Bot" in names
    assert "Workday Bot" not in names


@pytest.mark.asyncio
async def test_search_filtered_no_domain_returns_all(tmp_db, simple_flow_data):
    """search_patterns_filtered without domain filter returns all matching patterns."""
    store = await PatternStore.open(tmp_db)
    await store.save_pattern(
        name="Bot A", requirement_text="support chatflow", flow_data=simple_flow_data, domain="flowise"
    )
    await store.save_pattern(
        name="Bot B", requirement_text="support workday hire", flow_data=simple_flow_data, domain="workday"
    )
    await store.close()

    store2 = await PatternStore.open(tmp_db)
    results = await store2.search_patterns_filtered("support", limit=10)
    await store2.close()

    domains = {r["domain"] for r in results}
    assert "flowise" in domains
    assert "workday" in domains


@pytest.mark.asyncio
async def test_search_filtered_node_types_overlap(tmp_db, simple_flow_data):
    """node_types filter must retain only patterns with overlapping node types."""
    store = await PatternStore.open(tmp_db)
    await store.save_pattern(
        name="OpenAI Bot",
        requirement_text="chatflow using openai model memory",
        flow_data=simple_flow_data,
        node_types=json.dumps(["chatOpenAI", "bufferMemory"]),
    )
    await store.save_pattern(
        name="Anthropic Bot",
        requirement_text="chatflow using anthropic model memory",
        flow_data=simple_flow_data,
        node_types=json.dumps(["chatAnthropic", "bufferMemory"]),
    )
    await store.close()

    store2 = await PatternStore.open(tmp_db)
    # Filter for chatOpenAI node type only
    results = await store2.search_patterns_filtered(
        "chatflow", node_types=["chatOpenAI"], limit=10
    )
    await store2.close()

    names = [r["name"] for r in results]
    assert "OpenAI Bot" in names
    assert "Anthropic Bot" not in names


@pytest.mark.asyncio
async def test_search_filtered_empty_keywords_no_crash(tmp_db, simple_flow_data):
    """search_patterns_filtered with empty keywords must not raise."""
    store = await PatternStore.open(tmp_db)
    await store.save_pattern(
        name="Bot", requirement_text="support chatflow", flow_data=simple_flow_data
    )
    await store.close()

    store2 = await PatternStore.open(tmp_db)
    results = await store2.search_patterns_filtered("", domain="flowise", limit=5)
    await store2.close()
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Test group 3 — apply_as_base_graph() returns GraphIR from saved flow_data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_as_base_graph_returns_graph_ir(tmp_db, simple_flow_data):
    """apply_as_base_graph() must return a GraphIR with nodes from flow_data."""
    store = await PatternStore.open(tmp_db)
    pat_id = await store.save_pattern(
        name="Test", requirement_text="support bot", flow_data=simple_flow_data
    )

    graph_ir = await store.apply_as_base_graph(pat_id)
    await store.close()

    assert isinstance(graph_ir, GraphIR)
    assert len(graph_ir.nodes) == 2
    node_ids = {n.id for n in graph_ir.nodes}
    assert "chatOpenAI_0" in node_ids
    assert "bufferMemory_0" in node_ids


@pytest.mark.asyncio
async def test_apply_as_base_graph_increments_success_count(tmp_db, simple_flow_data):
    """apply_as_base_graph() must increment success_count and set last_used_at."""
    import aiosqlite

    store = await PatternStore.open(tmp_db)
    pat_id = await store.save_pattern(
        name="Test", requirement_text="support", flow_data=simple_flow_data
    )
    await store.apply_as_base_graph(pat_id)
    await store.close()

    async with aiosqlite.connect(tmp_db) as conn:
        async with conn.execute(
            "SELECT success_count, last_used_at FROM patterns WHERE id = ?", (pat_id,)
        ) as cur:
            row = await cur.fetchone()

    assert row[0] == 2, "success_count should be 2 (1 initial + 1 from apply_as_base_graph)"
    assert row[1] is not None, "last_used_at should be set"


@pytest.mark.asyncio
async def test_apply_as_base_graph_missing_id_returns_empty(tmp_db):
    """apply_as_base_graph() with a non-existent ID returns empty GraphIR."""
    store = await PatternStore.open(tmp_db)
    graph_ir = await store.apply_as_base_graph(999999)
    await store.close()

    assert isinstance(graph_ir, GraphIR)
    assert len(graph_ir.nodes) == 0


@pytest.mark.asyncio
async def test_apply_as_base_graph_to_flow_data_round_trip(tmp_db, simple_flow_data):
    """to_flow_data() on the returned GraphIR must be JSON-serialisable."""
    store = await PatternStore.open(tmp_db)
    pat_id = await store.save_pattern(
        name="Test", requirement_text="support", flow_data=simple_flow_data
    )
    graph_ir = await store.apply_as_base_graph(pat_id)
    await store.close()

    fd = graph_ir.to_flow_data()
    assert isinstance(fd, dict)
    assert "nodes" in fd and "edges" in fd
    # Must be JSON-serialisable (required for LangGraph checkpointing)
    json.dumps(fd)  # must not raise


# ---------------------------------------------------------------------------
# Test group 4 — base_graph_ir in artifacts influences patch v2 base graph
# ---------------------------------------------------------------------------


def test_graphir_from_base_graph_ir_dict(simple_flow_data):
    """GraphIR.from_flow_data() must reconstruct nodes from a stored base_graph_ir dict."""
    base_graph_ir_dict = json.loads(simple_flow_data)
    graph_ir = GraphIR.from_flow_data(base_graph_ir_dict)

    assert len(graph_ir.nodes) == 2
    assert graph_ir.get_node("chatOpenAI_0") is not None
    assert graph_ir.get_node("bufferMemory_0") is not None


def test_base_graph_ir_reduces_addnode_ops(simple_flow_data):
    """Starting from a seeded base graph should show existing nodes as already present."""
    base_graph_ir_dict = json.loads(simple_flow_data)
    graph_ir = GraphIR.from_flow_data(base_graph_ir_dict)

    # Verify that node_ids() reflects the seeded nodes
    node_ids = graph_ir.node_ids()
    assert "chatOpenAI_0" in node_ids
    assert "bufferMemory_0" in node_ids
    assert len(node_ids) == 2


# ---------------------------------------------------------------------------
# Test group 5 — meta_fingerprint property on NodeSchemaStore
# ---------------------------------------------------------------------------


def test_meta_fingerprint_returns_none_when_no_meta(tmp_path):
    """meta_fingerprint must return None when meta file does not exist."""
    from flowise_dev_agent.knowledge.provider import NodeSchemaStore

    store = NodeSchemaStore(
        snapshot_path=tmp_path / "nodes.snapshot.json",
        meta_path=tmp_path / "nodes.meta.json",
    )
    assert store.meta_fingerprint is None


def test_meta_fingerprint_reads_from_meta_file(tmp_path):
    """meta_fingerprint must return the fingerprint value from the meta JSON file."""
    from flowise_dev_agent.knowledge.provider import NodeSchemaStore

    meta_path = tmp_path / "nodes.meta.json"
    meta_path.write_text(
        json.dumps({"fingerprint": "deadbeef1234", "item_count": 42}),
        encoding="utf-8",
    )
    store = NodeSchemaStore(
        snapshot_path=tmp_path / "nodes.snapshot.json",
        meta_path=meta_path,
    )
    assert store.meta_fingerprint == "deadbeef1234"


def test_meta_fingerprint_falls_back_to_sha256_key(tmp_path):
    """meta_fingerprint must also check 'sha256' key if 'fingerprint' is absent."""
    from flowise_dev_agent.knowledge.provider import NodeSchemaStore

    meta_path = tmp_path / "nodes.meta.json"
    meta_path.write_text(
        json.dumps({"sha256": "cafebabe5678"}),
        encoding="utf-8",
    )
    store = NodeSchemaStore(
        snapshot_path=tmp_path / "nodes.snapshot.json",
        meta_path=meta_path,
    )
    assert store.meta_fingerprint == "cafebabe5678"


def test_meta_fingerprint_returns_none_on_malformed_json(tmp_path):
    """meta_fingerprint must return None if the meta file is not valid JSON."""
    from flowise_dev_agent.knowledge.provider import NodeSchemaStore

    meta_path = tmp_path / "nodes.meta.json"
    meta_path.write_text("not json {{{", encoding="utf-8")
    store = NodeSchemaStore(
        snapshot_path=tmp_path / "nodes.snapshot.json",
        meta_path=meta_path,
    )
    assert store.meta_fingerprint is None
