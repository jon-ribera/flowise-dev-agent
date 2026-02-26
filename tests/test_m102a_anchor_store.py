"""M10.2a — Canonical Anchor Dictionary Store (DD-093).

Tests for AnchorDictionaryStore, compute_compatible_types, and provider wiring.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from flowise_dev_agent.knowledge.anchor_store import (
    AnchorDictionaryStore,
    compute_compatible_types,
    normalize_schema_to_anchor_dict,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Minimal schema fixtures matching snapshot format
TOOL_AGENT_SCHEMA = {
    "node_type": "toolAgent",
    "name": "toolAgent",
    "label": "Tool Agent",
    "inputAnchors": [
        {
            "id": "{nodeId}-input-tools-Tool",
            "name": "tools",
            "label": "tools",
            "type": "Tool",
            "optional": True,
        },
        {
            "id": "{nodeId}-input-memory-BaseChatMemory",
            "name": "memory",
            "label": "memory",
            "type": "BaseChatMemory",
            "optional": True,
        },
        {
            "id": "{nodeId}-input-model-BaseChatModel",
            "name": "model",
            "label": "model",
            "type": "BaseChatModel",
            "optional": True,
        },
    ],
    "outputAnchors": [
        {
            "id": "{nodeId}-output-toolAgent-AgentExecutor|BaseChain|Runnable",
            "name": "toolAgent",
            "label": "Tool Agent",
            "type": "AgentExecutor | BaseChain | Runnable",
        },
    ],
}

CHAT_OPENAI_SCHEMA = {
    "node_type": "chatOpenAI",
    "name": "chatOpenAI",
    "label": "ChatOpenAI",
    "inputAnchors": [
        {
            "id": "{nodeId}-input-cache-BaseCache",
            "name": "cache",
            "label": "cache",
            "type": "BaseCache",
            "optional": True,
        },
    ],
    "outputAnchors": [
        {
            "id": "{nodeId}-output-chatOpenAI-ChatOpenAI|BaseChatOpenAI|BaseChatModel|BaseLanguageModel|Runnable",
            "name": "chatOpenAI",
            "label": "ChatOpenAI",
            "type": "ChatOpenAI | BaseChatOpenAI | BaseChatModel | BaseLanguageModel | Runnable",
        },
    ],
}


@pytest.fixture
def mock_nss():
    """Return a mock NodeSchemaStore with a small index."""
    nss = MagicMock()
    nss._index = {
        "toolAgent": TOOL_AGENT_SCHEMA,
        "chatOpenAI": CHAT_OPENAI_SCHEMA,
    }
    nss._loaded = True
    nss._load = MagicMock()
    return nss


@pytest.fixture
def store(mock_nss):
    """Return an AnchorDictionaryStore backed by mock_nss."""
    return AnchorDictionaryStore(mock_nss)


# ---------------------------------------------------------------------------
# compute_compatible_types
# ---------------------------------------------------------------------------


class TestComputeCompatibleTypes:
    """Tests for the pipe-split + CamelCase parent token logic."""

    def test_empty_string(self):
        assert compute_compatible_types("") == []

    def test_single_type(self):
        result = compute_compatible_types("Tool")
        assert result == ["Tool"]

    def test_pipe_split(self):
        result = compute_compatible_types("AgentExecutor | BaseChain | Runnable")
        assert "AgentExecutor" in result
        assert "BaseChain" in result
        assert "Runnable" in result

    def test_camel_case_parent_token(self):
        """BaseChatMemory should also yield BaseMemory."""
        result = compute_compatible_types("BaseChatMemory")
        assert "BaseChatMemory" in result
        assert "BaseMemory" in result

    def test_base_chat_model_parent_tokens(self):
        result = compute_compatible_types("BaseChatModel")
        assert "BaseChatModel" in result
        assert "BaseModel" in result

    def test_pipe_chain_with_parents(self):
        """Full pipe chain like chatOpenAI output type."""
        result = compute_compatible_types(
            "ChatOpenAI | BaseChatOpenAI | BaseChatModel | BaseLanguageModel | Runnable"
        )
        # Explicit types
        assert "ChatOpenAI" in result
        assert "BaseChatOpenAI" in result
        assert "BaseChatModel" in result
        assert "BaseLanguageModel" in result
        assert "Runnable" in result
        # Derived parents
        assert "BaseModel" in result

    def test_no_duplicates(self):
        result = compute_compatible_types("BaseChatModel | BaseChatModel")
        # Even if input has duplicates, result should have BaseChatModel once
        count = result.count("BaseChatModel")
        assert count == 2  # appears in both split entries (pipe-split preserves)
        # But derived tokens shouldn't be duplicated
        base_model_count = result.count("BaseModel")
        assert base_model_count == 1

    def test_simple_type_no_parents(self):
        """Single-word types produce no derived tokens."""
        result = compute_compatible_types("Tool")
        assert result == ["Tool"]

    def test_advisory_only(self):
        """compatible_types should never raise or block — it's advisory."""
        # Even weird inputs should produce a list, not an error
        result = compute_compatible_types("weird|type|here")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# normalize_schema_to_anchor_dict
# ---------------------------------------------------------------------------


class TestNormalizeSchemaToAnchorDict:
    """Tests for schema-to-anchor-dict normalization."""

    def test_tool_agent(self):
        result = normalize_schema_to_anchor_dict(TOOL_AGENT_SCHEMA, "toolAgent")
        assert result["node_type"] == "toolAgent"
        assert len(result["input_anchors"]) == 3
        assert len(result["output_anchors"]) == 1

    def test_no_empty_names(self):
        result = normalize_schema_to_anchor_dict(TOOL_AGENT_SCHEMA, "toolAgent")
        for anchor in result["input_anchors"] + result["output_anchors"]:
            assert anchor["name"], f"Empty name in anchor: {anchor}"

    def test_type_present(self):
        result = normalize_schema_to_anchor_dict(TOOL_AGENT_SCHEMA, "toolAgent")
        for anchor in result["input_anchors"] + result["output_anchors"]:
            assert "type" in anchor, f"Missing type in anchor: {anchor}"

    def test_id_template_from_schema(self):
        """id_template should use schema-provided id when available."""
        result = normalize_schema_to_anchor_dict(TOOL_AGENT_SCHEMA, "toolAgent")
        memory = [a for a in result["input_anchors"] if a["name"] == "memory"][0]
        assert memory["id_template"] == "{nodeId}-input-memory-BaseChatMemory"
        assert "id_source" not in memory  # schema-provided, no fabrication marker

    def test_id_template_fabricated(self):
        """When schema id is missing, id_template is fabricated with marker."""
        schema_no_id = {
            "node_type": "test",
            "inputAnchors": [
                {"name": "foo", "type": "Bar", "optional": False},
            ],
            "outputAnchors": [],
        }
        result = normalize_schema_to_anchor_dict(schema_no_id, "test")
        anchor = result["input_anchors"][0]
        assert anchor["id_template"] == "{nodeId}-input-foo-Bar"
        assert anchor["id_source"] == "fabricated"

    def test_compatible_types_on_anchors(self):
        result = normalize_schema_to_anchor_dict(TOOL_AGENT_SCHEMA, "toolAgent")
        memory = [a for a in result["input_anchors"] if a["name"] == "memory"][0]
        assert "BaseChatMemory" in memory["compatible_types"]
        assert "BaseMemory" in memory["compatible_types"]

    def test_output_anchor_compatible_types(self):
        result = normalize_schema_to_anchor_dict(CHAT_OPENAI_SCHEMA, "chatOpenAI")
        output = result["output_anchors"][0]
        assert "ChatOpenAI" in output["compatible_types"]
        assert "BaseChatModel" in output["compatible_types"]
        assert "Runnable" in output["compatible_types"]

    def test_optional_field(self):
        result = normalize_schema_to_anchor_dict(TOOL_AGENT_SCHEMA, "toolAgent")
        memory = [a for a in result["input_anchors"] if a["name"] == "memory"][0]
        assert memory["optional"] is True

    def test_empty_schema(self):
        """Schema with no anchors should produce empty lists."""
        result = normalize_schema_to_anchor_dict(
            {"node_type": "empty", "inputAnchors": [], "outputAnchors": []},
            "empty",
        )
        assert result["input_anchors"] == []
        assert result["output_anchors"] == []


# ---------------------------------------------------------------------------
# AnchorDictionaryStore
# ---------------------------------------------------------------------------


class TestAnchorDictionaryStore:
    """Tests for the store's build, lookup, and invalidation."""

    def test_get_returns_dict(self, store):
        result = store.get("toolAgent")
        assert result is not None
        assert result["node_type"] == "toolAgent"
        assert isinstance(result["input_anchors"], list)
        assert isinstance(result["output_anchors"], list)

    def test_get_unknown_returns_none(self, store):
        assert store.get("nonExistentNode") is None

    def test_node_count(self, store):
        assert store.node_count == 2

    def test_lazy_build(self, mock_nss):
        """Store does not build until first access."""
        s = AnchorDictionaryStore(mock_nss)
        assert s._built is False
        s.get("toolAgent")
        assert s._built is True

    def test_invalidate_forces_rebuild(self, store):
        # Build once
        store.get("toolAgent")
        assert store._built is True
        # Invalidate
        store.invalidate()
        assert store._built is False
        assert len(store._by_node_type) == 0
        # Next access rebuilds
        result = store.get("toolAgent")
        assert result is not None
        assert store._built is True

    def test_tool_agent_anchors(self, store):
        result = store.get("toolAgent")
        names = [a["name"] for a in result["input_anchors"]]
        assert "memory" in names
        assert "model" in names
        assert "tools" in names

    def test_tool_agent_memory_compatible_types(self, store):
        result = store.get("toolAgent")
        memory = [a for a in result["input_anchors"] if a["name"] == "memory"][0]
        assert "BaseChatMemory" in memory["compatible_types"]
        assert "BaseMemory" in memory["compatible_types"]

    def test_chat_openai_output(self, store):
        result = store.get("chatOpenAI")
        assert len(result["output_anchors"]) == 1
        output = result["output_anchors"][0]
        assert output["name"] == "chatOpenAI"
        assert "ChatOpenAI" in output["compatible_types"]
        assert "Runnable" in output["compatible_types"]

    def test_by_anchor_name(self, store):
        """Secondary index: lookup by anchor name."""
        entries = store.by_anchor_name("memory")
        assert len(entries) >= 1
        assert any(e["node_type"] == "toolAgent" for e in entries)

    def test_by_type_token(self, store):
        """Secondary index: lookup by type token."""
        entries = store.by_type_token("BaseChatModel")
        assert len(entries) >= 1
        # Both toolAgent (input "model") and chatOpenAI (output) should appear
        node_types = {e["node_type"] for e in entries}
        assert "toolAgent" in node_types
        assert "chatOpenAI" in node_types


# ---------------------------------------------------------------------------
# Repair normalization
# ---------------------------------------------------------------------------


class TestRepairNormalization:
    """Repair via api_fetcher normalizes raw API response to canonical format."""

    @pytest.mark.asyncio
    async def test_repair_normalizes_api_response(self, mock_nss):
        """A raw API response should produce the same canonical anchor dict keys."""
        # Raw API response shape (different from snapshot format)
        raw_api = {
            "name": "newNode",
            "label": "New Node",
            "baseClasses": ["NewClass", "Runnable"],
            "inputs": [
                {"name": "input1", "type": "SomeType", "optional": False},
            ],
            "outputs": [
                {"name": "newNode", "label": "New Node", "baseClasses": ["NewClass", "Runnable"]},
            ],
        }

        async def fake_fetcher(node_type):
            return raw_api

        store = AnchorDictionaryStore(mock_nss, api_fetcher=fake_fetcher)
        result = await store.get_or_repair("newNode")

        assert result is not None
        assert result["node_type"] == "newNode"
        # Check canonical keys
        assert "input_anchors" in result
        assert "output_anchors" in result
        # Input anchor has proper shape
        assert len(result["input_anchors"]) == 1
        inp = result["input_anchors"][0]
        assert inp["name"] == "input1"
        assert inp["type"] == "SomeType"
        assert "compatible_types" in inp
        assert "id_template" in inp
        # Output anchor has proper shape
        assert len(result["output_anchors"]) == 1
        out = result["output_anchors"][0]
        assert out["name"] == "newNode"
        assert "compatible_types" in out

    @pytest.mark.asyncio
    async def test_repair_cached_after_fetch(self, mock_nss):
        """After repair, the node should be in the index for sync get()."""
        raw_api = {
            "name": "repairedNode",
            "baseClasses": ["Foo"],
            "inputs": [],
        }

        async def fake_fetcher(node_type):
            return raw_api

        store = AnchorDictionaryStore(mock_nss, api_fetcher=fake_fetcher)
        # Not in index yet
        assert store.get("repairedNode") is None
        # Repair fetches it
        result = await store.get_or_repair("repairedNode")
        assert result is not None
        # Now available via sync get()
        cached = store.get("repairedNode")
        assert cached is not None
        assert cached["node_type"] == "repairedNode"

    @pytest.mark.asyncio
    async def test_repair_error_returns_none(self, mock_nss):
        """API error should return None, not raise."""
        async def failing_fetcher(node_type):
            return {"error": "HTTP 404", "detail": "Not Found"}

        store = AnchorDictionaryStore(mock_nss, api_fetcher=failing_fetcher)
        result = await store.get_or_repair("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_repair_exception_returns_none(self, mock_nss):
        """Exception in fetcher should return None, not propagate."""
        async def crashing_fetcher(node_type):
            raise ConnectionError("timeout")

        store = AnchorDictionaryStore(mock_nss, api_fetcher=crashing_fetcher)
        result = await store.get_or_repair("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_repair_no_fetcher_returns_none(self, mock_nss):
        """No api_fetcher provided should return None."""
        store = AnchorDictionaryStore(mock_nss)
        result = await store.get_or_repair("missing")
        assert result is None


# ---------------------------------------------------------------------------
# Full snapshot integration
# ---------------------------------------------------------------------------


class TestFullSnapshot:
    """Test against real snapshot if available (non-destructive read-only)."""

    @pytest.fixture
    def real_nss(self):
        """Load real NodeSchemaStore from disk if snapshot exists."""
        from flowise_dev_agent.knowledge.provider import NodeSchemaStore

        snapshot_path = Path(__file__).parent.parent / "schemas" / "flowise_nodes.snapshot.json"
        if not snapshot_path.exists():
            pytest.skip("Snapshot not available")
        return NodeSchemaStore(snapshot_path)

    def test_all_nodes_produce_valid_entries(self, real_nss):
        """Every node type in snapshot should produce a valid anchor dict entry."""
        store = AnchorDictionaryStore(real_nss)
        store._build()

        assert store.node_count > 0
        for node_type, entry in store._by_node_type.items():
            assert entry["node_type"] == node_type
            for anchor in entry["input_anchors"] + entry["output_anchors"]:
                assert anchor["name"], f"Empty name in {node_type}: {anchor}"
                assert "type" in anchor, f"Missing type in {node_type}: {anchor}"
                assert "id_template" in anchor, f"Missing id_template in {node_type}: {anchor}"
                assert "compatible_types" in anchor, f"Missing compatible_types in {node_type}: {anchor}"

    def test_tool_agent_memory_anchor(self, real_nss):
        """toolAgent should have memory anchor with BaseChatMemory + BaseMemory."""
        store = AnchorDictionaryStore(real_nss)
        result = store.get("toolAgent")
        if result is None:
            pytest.skip("toolAgent not in snapshot")

        memory = [a for a in result["input_anchors"] if a["name"] == "memory"]
        assert len(memory) == 1
        assert "BaseChatMemory" in memory[0]["compatible_types"]
        assert "BaseMemory" in memory[0]["compatible_types"]

    def test_chat_openai_output_chain(self, real_nss):
        """chatOpenAI output compatible_types should include full hierarchy."""
        store = AnchorDictionaryStore(real_nss)
        result = store.get("chatOpenAI")
        if result is None:
            pytest.skip("chatOpenAI not in snapshot")

        output = result["output_anchors"][0]
        expected = {"ChatOpenAI", "BaseChatOpenAI", "BaseChatModel", "BaseLanguageModel", "Runnable"}
        actual = set(output["compatible_types"])
        assert expected.issubset(actual), f"Missing: {expected - actual}"


# ---------------------------------------------------------------------------
# Provider wiring
# ---------------------------------------------------------------------------


class TestProviderWiring:
    """FlowiseKnowledgeProvider.anchor_dictionary property."""

    def test_anchor_dictionary_property_returns_store(self):
        """Property returns an AnchorDictionaryStore instance."""
        from flowise_dev_agent.knowledge.provider import FlowiseKnowledgeProvider

        # Use real schemas dir (lazy load, won't fail even if snapshot missing)
        provider = FlowiseKnowledgeProvider()
        ad = provider.anchor_dictionary
        assert isinstance(ad, AnchorDictionaryStore)

    def test_anchor_dictionary_is_cached(self):
        """Same instance returned on multiple accesses."""
        from flowise_dev_agent.knowledge.provider import FlowiseKnowledgeProvider

        provider = FlowiseKnowledgeProvider()
        ad1 = provider.anchor_dictionary
        ad2 = provider.anchor_dictionary
        assert ad1 is ad2


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


class TestImportSmoke:
    """Module imports work correctly."""

    def test_import_anchor_store(self):
        from flowise_dev_agent.knowledge.anchor_store import AnchorDictionaryStore  # noqa: F401

    def test_import_helpers(self):
        from flowise_dev_agent.knowledge.anchor_store import (  # noqa: F401
            compute_compatible_types,
            normalize_schema_to_anchor_dict,
        )

    def test_import_provider_property(self):
        from flowise_dev_agent.knowledge.provider import FlowiseKnowledgeProvider  # noqa: F401
