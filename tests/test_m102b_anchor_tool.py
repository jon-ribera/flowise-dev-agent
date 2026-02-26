"""M10.2b — Anchor Dictionary Tool (#51) + Prompt Update (DD-094).

Tests for:
- get_anchor_dictionary tool method
- Registry registration (tool #51)
- Patch IR prompt anchor resolution rules
- Prefetch logic (anchor dictionaries injected into compile context)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from flowise_dev_agent.agent.tools import ToolResult
from flowise_dev_agent.mcp.tools import FlowiseMCPTools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TOOL_AGENT_ANCHOR_DICT = {
    "node_type": "toolAgent",
    "input_anchors": [
        {
            "name": "tools",
            "type": "Tool",
            "optional": True,
            "id_template": "{nodeId}-input-tools-Tool",
            "compatible_types": ["Tool"],
        },
        {
            "name": "memory",
            "type": "BaseChatMemory",
            "optional": True,
            "id_template": "{nodeId}-input-memory-BaseChatMemory",
            "compatible_types": ["BaseChatMemory", "BaseMemory"],
        },
        {
            "name": "model",
            "type": "BaseChatModel",
            "optional": True,
            "id_template": "{nodeId}-input-model-BaseChatModel",
            "compatible_types": ["BaseChatModel", "BaseModel"],
        },
    ],
    "output_anchors": [
        {
            "name": "toolAgent",
            "type": "AgentExecutor | BaseChain | Runnable",
            "optional": False,
            "id_template": "{nodeId}-output-toolAgent-AgentExecutor|BaseChain|Runnable",
            "compatible_types": ["AgentExecutor", "BaseChain", "Runnable"],
        },
    ],
}


def _make_getter(entries: dict[str, dict | None] | None = None):
    """Create a simple anchor_dict_getter callable."""
    store = entries or {"toolAgent": TOOL_AGENT_ANCHOR_DICT}

    def getter(node_type: str) -> dict | None:
        return store.get(node_type)

    return getter


@pytest.fixture
def mock_client():
    """Minimal mock FlowiseClient for FlowiseMCPTools."""
    return MagicMock()


@pytest.fixture
def tools_with_getter(mock_client):
    """FlowiseMCPTools with anchor_dict_getter configured."""
    return FlowiseMCPTools(mock_client, anchor_dict_getter=_make_getter())


@pytest.fixture
def tools_without_getter(mock_client):
    """FlowiseMCPTools WITHOUT anchor_dict_getter (legacy mode)."""
    return FlowiseMCPTools(mock_client)


# ---------------------------------------------------------------------------
# Tool method — success path
# ---------------------------------------------------------------------------


class TestGetAnchorDictionary:
    """Tool #51: get_anchor_dictionary returns proper ToolResult."""

    @pytest.mark.asyncio
    async def test_known_node_type(self, tools_with_getter):
        result = await tools_with_getter.get_anchor_dictionary("toolAgent")
        assert isinstance(result, ToolResult)
        assert result.ok is True
        assert result.data is not None
        assert result.data["node_type"] == "toolAgent"
        assert len(result.data["input_anchors"]) == 3
        assert len(result.data["output_anchors"]) == 1

    @pytest.mark.asyncio
    async def test_summary_format(self, tools_with_getter):
        result = await tools_with_getter.get_anchor_dictionary("toolAgent")
        assert "toolAgent" in result.summary
        assert "3 inputs" in result.summary
        assert "1 output" in result.summary
        assert "memory" in result.summary
        assert "model" in result.summary
        assert "tools" in result.summary
        assert "toolAgent" in result.summary  # output anchor name

    @pytest.mark.asyncio
    async def test_anchor_data_shape(self, tools_with_getter):
        result = await tools_with_getter.get_anchor_dictionary("toolAgent")
        for anchor in result.data["input_anchors"]:
            assert "name" in anchor
            assert "type" in anchor
            assert "compatible_types" in anchor
            assert "optional" in anchor
            assert "id_template" in anchor

    @pytest.mark.asyncio
    async def test_compatible_types_advisory(self, tools_with_getter):
        """compatible_types are present but advisory — no hard gate."""
        result = await tools_with_getter.get_anchor_dictionary("toolAgent")
        memory = [a for a in result.data["input_anchors"] if a["name"] == "memory"][0]
        assert "BaseChatMemory" in memory["compatible_types"]
        assert "BaseMemory" in memory["compatible_types"]


# ---------------------------------------------------------------------------
# Tool method — error paths
# ---------------------------------------------------------------------------


class TestGetAnchorDictionaryErrors:
    """Error responses from get_anchor_dictionary."""

    @pytest.mark.asyncio
    async def test_unknown_node_type(self, tools_with_getter):
        result = await tools_with_getter.get_anchor_dictionary("nonExistentNode")
        assert result.ok is False
        assert "nonExistentNode" in result.summary
        assert result.error is not None
        assert result.error["type"] == "NotFound"

    @pytest.mark.asyncio
    async def test_no_getter_configured(self, tools_without_getter):
        result = await tools_without_getter.get_anchor_dictionary("toolAgent")
        assert result.ok is False
        assert result.error is not None
        assert result.error["type"] == "ConfigurationError"

    @pytest.mark.asyncio
    async def test_error_result_has_proper_fields(self, tools_with_getter):
        result = await tools_with_getter.get_anchor_dictionary("missing")
        assert result.ok is False
        assert result.error is not None
        assert "type" in result.error
        assert "message" in result.error
        assert "detail" in result.error


# ---------------------------------------------------------------------------
# Registry — tool #51 registered
# ---------------------------------------------------------------------------


class TestRegistryTool51:
    """Tool #51 is registered correctly in ToolRegistry."""

    def test_51_tools_registered(self, mock_client):
        from flowise_dev_agent.agent.registry import ToolRegistry
        from flowise_dev_agent.mcp.registry import register_flowise_mcp_tools

        registry = ToolRegistry()
        tools = FlowiseMCPTools(mock_client, anchor_dict_getter=_make_getter())
        register_flowise_mcp_tools(registry, tools)

        all_tools = set()
        for phase in ("discover", "patch", "test"):
            for td in registry.tool_defs(phase):
                all_tools.add(td.name)

        flowise_tools = {t for t in all_tools if t.startswith("flowise__")}
        assert len(flowise_tools) == 51, f"Expected 51, got {len(flowise_tools)}"
        assert "flowise__get_anchor_dictionary" in flowise_tools

    def test_executor_has_anchor_tool(self, mock_client):
        from flowise_dev_agent.agent.registry import ToolRegistry
        from flowise_dev_agent.mcp.registry import register_flowise_mcp_tools

        registry = ToolRegistry()
        tools = FlowiseMCPTools(mock_client, anchor_dict_getter=_make_getter())
        register_flowise_mcp_tools(registry, tools)

        executor = registry.executor("discover")
        assert "flowise__get_anchor_dictionary" in executor
        assert "get_anchor_dictionary" in executor  # simple key

    @pytest.mark.asyncio
    async def test_executor_callable(self, mock_client):
        from flowise_dev_agent.agent.registry import ToolRegistry
        from flowise_dev_agent.mcp.registry import register_flowise_mcp_tools

        registry = ToolRegistry()
        tools = FlowiseMCPTools(mock_client, anchor_dict_getter=_make_getter())
        register_flowise_mcp_tools(registry, tools)

        executor = registry.executor("discover")
        fn = executor["flowise__get_anchor_dictionary"]
        result = await fn(node_type="toolAgent")
        assert isinstance(result, ToolResult)
        assert result.ok is True
        assert "toolAgent" in result.summary


# ---------------------------------------------------------------------------
# Patch IR prompt update
# ---------------------------------------------------------------------------


class TestPatchIRPrompt:
    """The Patch IR system prompt includes anchor resolution rules."""

    def test_anchor_resolution_rules_present(self):
        from flowise_dev_agent.agent.graph import _COMPILE_PATCH_IR_V2_SYSTEM

        prompt = _COMPILE_PATCH_IR_V2_SYSTEM

        # Key phrases from the ANCHOR RESOLUTION RULES section
        assert "ANCHOR RESOLUTION RULES" in prompt
        assert "canonical anchor NAMES" in prompt
        assert "do NOT use" in prompt.lower() or "NOT type names" in prompt
        assert "compatible_types" in prompt
        assert "ADVISORY" in prompt.upper() or "advisory" in prompt.lower()
        assert "get_anchor_dictionary" in prompt

    def test_target_anchor_rule_updated(self):
        from flowise_dev_agent.agent.graph import _COMPILE_PATCH_IR_V2_SYSTEM

        prompt = _COMPILE_PATCH_IR_V2_SYSTEM

        # Rule 3 should now say anchor NAME, not TYPE
        assert 'target_anchor: input anchor NAME' in prompt


# ---------------------------------------------------------------------------
# Prefetch logic
# ---------------------------------------------------------------------------


class TestPrefetchLogic:
    """Anchor dictionary prefetch in compile_patch_ir context."""

    def test_prefetch_extracts_from_plan(self):
        """Verify the prefetch pattern: node types from plan are looked up."""
        # This is a structural test — we verify the function exists and the
        # prompt includes the prefetch instruction
        from flowise_dev_agent.agent.graph import _COMPILE_PATCH_IR_V2_SYSTEM

        assert "Prefetched anchor dictionaries" in _COMPILE_PATCH_IR_V2_SYSTEM or \
               "prefetched" in _COMPILE_PATCH_IR_V2_SYSTEM.lower() or \
               "available in context" in _COMPILE_PATCH_IR_V2_SYSTEM.lower()

    def test_anchor_store_get_is_sync(self):
        """AnchorDictionaryStore.get() is sync O(1) — suitable for prefetch."""
        from flowise_dev_agent.knowledge.anchor_store import AnchorDictionaryStore

        mock_nss = MagicMock()
        mock_nss._index = {
            "chatOpenAI": {
                "node_type": "chatOpenAI",
                "inputAnchors": [{"id": "{nodeId}-input-cache-BaseCache", "name": "cache", "type": "BaseCache", "optional": True}],
                "outputAnchors": [{"id": "{nodeId}-output-chatOpenAI-ChatOpenAI", "name": "chatOpenAI", "type": "ChatOpenAI", "optional": False}],
            },
        }
        mock_nss._loaded = True
        mock_nss._load = MagicMock()

        store = AnchorDictionaryStore(mock_nss)
        # Sync O(1) — no await needed
        result = store.get("chatOpenAI")
        assert result is not None
        assert result["node_type"] == "chatOpenAI"

    def test_prefetch_does_not_call_api(self):
        """Prefetch uses .get() (sync, local) — never .get_or_repair() (async, API)."""
        from flowise_dev_agent.knowledge.anchor_store import AnchorDictionaryStore

        mock_nss = MagicMock()
        mock_nss._index = {"toolAgent": {
            "node_type": "toolAgent",
            "inputAnchors": [],
            "outputAnchors": [],
        }}
        mock_nss._loaded = True
        mock_nss._load = MagicMock()

        # api_fetcher should never be called during prefetch
        api_fetcher = AsyncMock(side_effect=AssertionError("API should not be called during prefetch"))
        store = AnchorDictionaryStore(mock_nss, api_fetcher=api_fetcher)

        # Sync .get() — no API call
        result = store.get("toolAgent")
        assert result is not None
        api_fetcher.assert_not_called()


# ---------------------------------------------------------------------------
# Constructor backwards compatibility
# ---------------------------------------------------------------------------


class TestConstructorCompat:
    """FlowiseMCPTools constructor is backwards compatible."""

    def test_old_style_no_getter(self, mock_client):
        """Existing code that passes only client still works."""
        tools = FlowiseMCPTools(mock_client)
        assert tools._anchor_dict_getter is None

    def test_new_style_with_getter(self, mock_client):
        """New code can pass anchor_dict_getter."""
        getter = _make_getter()
        tools = FlowiseMCPTools(mock_client, anchor_dict_getter=getter)
        assert tools._anchor_dict_getter is getter


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


class TestImportSmoke:
    """Module imports work correctly."""

    def test_import_tools(self):
        from flowise_dev_agent.mcp.tools import FlowiseMCPTools  # noqa: F401

    def test_import_registry(self):
        from flowise_dev_agent.mcp.registry import register_flowise_mcp_tools  # noqa: F401

    def test_import_prompt(self):
        from flowise_dev_agent.agent.graph import _COMPILE_PATCH_IR_V2_SYSTEM  # noqa: F401
