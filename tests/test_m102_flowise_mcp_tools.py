"""M10.2 — Native Flowise MCP tool surface (DD-079).

Tests for FlowiseMCPTools (50 tools) and registry wiring.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from flowise_dev_agent.agent.tools import ToolResult
from flowise_dev_agent.mcp.tools import FlowiseMCPTools, _CRED_ALLOWLIST


# ---------------------------------------------------------------------------
# Fixture: mocked FlowiseClient + FlowiseMCPTools
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """Return a MagicMock with all FlowiseClient methods as AsyncMocks."""
    client = MagicMock()
    # Auto-create async methods on attribute access
    client.ping = AsyncMock(return_value={"status": "pong"})
    client.list_nodes = AsyncMock(return_value=[{"name": "chatOpenAI"}, {"name": "toolAgent"}])
    client.get_node = AsyncMock(return_value={"name": "chatOpenAI", "type": "ChatOpenAI"})
    client.list_chatflows = AsyncMock(return_value=[
        {"id": "cf-1", "name": "Flow A", "type": "CHATFLOW"},
        {"id": "cf-2", "name": "Flow B", "type": "CHATFLOW"},
    ])
    client.get_chatflow = AsyncMock(return_value={"id": "cf-1", "name": "Flow A", "flowData": "{}"})
    client.get_chatflow_by_apikey = AsyncMock(return_value={"id": "cf-1", "name": "Flow A"})
    client.create_chatflow = AsyncMock(return_value={"id": "cf-new", "name": "New Flow"})
    client.update_chatflow = AsyncMock(return_value={"id": "cf-1", "name": "Updated Flow"})
    client.delete_chatflow = AsyncMock(return_value={"success": True})
    client.create_prediction = AsyncMock(return_value={"text": "Hello! How can I help?"})
    client.list_assistants = AsyncMock(return_value=[])
    client.get_assistant = AsyncMock(return_value={"id": "a-1"})
    client.create_assistant = AsyncMock(return_value={"id": "a-new"})
    client.update_assistant = AsyncMock(return_value={"id": "a-1"})
    client.delete_assistant = AsyncMock(return_value={"success": True})
    client.list_tools = AsyncMock(return_value=[])
    client.get_tool = AsyncMock(return_value={"id": "t-1"})
    client.create_tool = AsyncMock(return_value={"id": "t-new"})
    client.update_tool = AsyncMock(return_value={"id": "t-1"})
    client.delete_tool = AsyncMock(return_value={"success": True})
    client.list_variables = AsyncMock(return_value=[])
    client.create_variable = AsyncMock(return_value={"id": "v-1"})
    client.update_variable = AsyncMock(return_value={"id": "v-1"})
    client.delete_variable = AsyncMock(return_value={"success": True})
    client.list_document_stores = AsyncMock(return_value=[])
    client.get_document_store = AsyncMock(return_value={"id": "ds-1"})
    client.create_document_store = AsyncMock(return_value={"id": "ds-new"})
    client.update_document_store = AsyncMock(return_value={"id": "ds-1"})
    client.delete_document_store = AsyncMock(return_value={"success": True})
    client.get_document_chunks = AsyncMock(return_value=[])
    client.update_document_chunk = AsyncMock(return_value={"success": True})
    client.delete_document_chunk = AsyncMock(return_value={"success": True})
    client.upsert_document = AsyncMock(return_value={"success": True})
    client.refresh_document_store = AsyncMock(return_value={"success": True})
    client.query_document_store = AsyncMock(return_value=[])
    client.delete_document_loader = AsyncMock(return_value={"success": True})
    client.delete_vectorstore_data = AsyncMock(return_value={"success": True})
    client.list_chat_messages = AsyncMock(return_value=[])
    client.delete_chat_messages = AsyncMock(return_value={"success": True})
    client.list_feedback = AsyncMock(return_value=[])
    client.create_feedback = AsyncMock(return_value={"id": "fb-1"})
    client.update_feedback = AsyncMock(return_value={"id": "fb-1"})
    client.list_leads = AsyncMock(return_value=[])
    client.create_lead = AsyncMock(return_value={"id": "ld-1"})
    client.upsert_vector = AsyncMock(return_value={"success": True})
    client.list_upsert_history = AsyncMock(return_value=[])
    client.delete_upsert_history = AsyncMock(return_value={"success": True})
    client.list_credentials = AsyncMock(return_value=[
        {"id": "cred-1", "name": "my-key", "credentialName": "openAIApi", "encryptedData": "SECRET", "apiKey": "sk-xxx"},
    ])
    client.create_credential = AsyncMock(return_value={"id": "cred-new"})
    client.list_marketplace_templates = AsyncMock(return_value=[{"name": "Template A"}])
    return client


@pytest.fixture
def tools(mock_client):
    return FlowiseMCPTools(mock_client)


# ---------------------------------------------------------------------------
# Tool count verification
# ---------------------------------------------------------------------------


class TestToolCount:
    """Verify exactly 51 tool methods exist (50 original + get_anchor_dictionary)."""

    def test_tool_count(self, tools):
        import inspect

        methods = [
            name for name, fn in inspect.getmembers(tools, predicate=inspect.ismethod)
            if not name.startswith("_")
        ]
        assert len(methods) == 51, f"Expected 51 tools, got {len(methods)}: {sorted(methods)}"


# ---------------------------------------------------------------------------
# Core graph-path tools
# ---------------------------------------------------------------------------


class TestCoreTools:
    """Test the primary graph-path tools."""

    @pytest.mark.asyncio
    async def test_list_chatflows(self, tools):
        result = await tools.list_chatflows()
        assert isinstance(result, ToolResult)
        assert result.ok is True
        assert "2 chatflows" in result.summary
        assert len(result.data) == 2

    @pytest.mark.asyncio
    async def test_get_chatflow(self, tools):
        result = await tools.get_chatflow("cf-1")
        assert result.ok is True
        assert "cf-1" in result.summary
        assert "Flow A" in result.summary
        assert result.data["flowData"] == "{}"

    @pytest.mark.asyncio
    async def test_create_chatflow(self, tools):
        result = await tools.create_chatflow("My Flow", description="A test")
        assert result.ok is True
        assert "cf-new" in result.summary
        assert "My Flow" in result.summary
        assert result.facts.get("chatflow_id") == "cf-new"

    @pytest.mark.asyncio
    async def test_update_chatflow(self, tools):
        result = await tools.update_chatflow("cf-1", name="Renamed")
        assert result.ok is True
        assert "cf-1" in result.summary

    @pytest.mark.asyncio
    async def test_delete_chatflow(self, tools):
        result = await tools.delete_chatflow("cf-1")
        assert result.ok is True
        assert "cf-1" in result.summary

    @pytest.mark.asyncio
    async def test_create_prediction(self, tools):
        result = await tools.create_prediction("cf-1", "Hello")
        assert result.ok is True
        assert "cf-1" in result.summary
        assert "streaming=False" in result.summary

    @pytest.mark.asyncio
    async def test_ping(self, tools):
        result = await tools.ping()
        assert result.ok is True
        assert "pong" in result.summary

    @pytest.mark.asyncio
    async def test_get_node(self, tools):
        result = await tools.get_node("chatOpenAI")
        assert result.ok is True
        assert "chatOpenAI" in result.summary

    @pytest.mark.asyncio
    async def test_list_nodes(self, tools):
        result = await tools.list_nodes()
        assert result.ok is True
        assert "2 node types" in result.summary


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """FlowiseClient error responses → ToolResult(ok=False)."""

    @pytest.mark.asyncio
    async def test_http_error_get(self, tools, mock_client):
        mock_client.get_chatflow = AsyncMock(return_value={"error": "HTTP 404", "detail": "Not Found"})
        result = await tools.get_chatflow("bad-id")
        assert result.ok is False
        assert "404" in result.summary
        assert result.error is not None
        assert result.error["type"] == "FlowiseAPIError"
        assert result.error["detail"] == "Not Found"

    @pytest.mark.asyncio
    async def test_http_error_post(self, tools, mock_client):
        mock_client.create_chatflow = AsyncMock(return_value={"error": "HTTP 500", "detail": "Internal Server Error"})
        result = await tools.create_chatflow("Test")
        assert result.ok is False
        assert "500" in result.summary

    @pytest.mark.asyncio
    async def test_http_error_list(self, tools, mock_client):
        mock_client.list_chatflows = AsyncMock(return_value={"error": "Connection refused"})
        result = await tools.list_chatflows()
        assert result.ok is False
        assert "Connection refused" in result.summary

    @pytest.mark.asyncio
    async def test_ping_error(self, tools, mock_client):
        mock_client.ping = AsyncMock(return_value={"error": "Connection timeout"})
        result = await tools.ping()
        assert result.ok is False


# ---------------------------------------------------------------------------
# Credential allowlist
# ---------------------------------------------------------------------------


class TestCredentialAllowlist:
    """list_credentials strips non-allowlisted keys."""

    @pytest.mark.asyncio
    async def test_strips_encrypted_data(self, tools):
        result = await tools.list_credentials()
        assert result.ok is True
        assert isinstance(result.data, list)
        assert len(result.data) == 1
        entry = result.data[0]
        # Allowlisted keys should be present
        assert "id" in entry
        assert "name" in entry
        assert "credentialName" in entry
        # Secret keys MUST be stripped
        assert "encryptedData" not in entry
        assert "apiKey" not in entry

    @pytest.mark.asyncio
    async def test_allowlist_with_error(self, tools, mock_client):
        mock_client.list_credentials = AsyncMock(return_value={"error": "HTTP 403", "detail": "Forbidden"})
        result = await tools.list_credentials()
        assert result.ok is False


# ---------------------------------------------------------------------------
# ToolResult structure
# ---------------------------------------------------------------------------


class TestToolResultStructure:
    """Every tool returns a proper ToolResult."""

    @pytest.mark.asyncio
    async def test_ok_result_fields(self, tools):
        result = await tools.list_chatflows()
        assert hasattr(result, "ok")
        assert hasattr(result, "summary")
        assert hasattr(result, "facts")
        assert hasattr(result, "data")
        assert hasattr(result, "error")
        assert hasattr(result, "artifacts")
        assert result.error is None
        assert isinstance(result.summary, str)
        assert len(result.summary) <= 300

    @pytest.mark.asyncio
    async def test_error_result_fields(self, tools, mock_client):
        mock_client.list_chatflows = AsyncMock(return_value={"error": "fail"})
        result = await tools.list_chatflows()
        assert result.ok is False
        assert result.error is not None
        assert "type" in result.error
        assert "message" in result.error
        assert "detail" in result.error


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestRegistry:
    """Registry registration and executor lookup."""

    def test_register_50_tools(self, mock_client):
        from flowise_dev_agent.agent.registry import ToolRegistry
        from flowise_dev_agent.mcp.registry import register_flowise_mcp_tools

        registry = ToolRegistry()
        tools = FlowiseMCPTools(mock_client)
        register_flowise_mcp_tools(registry, tools)

        # Get all tool defs for all phases
        all_tools = set()
        for phase in ("discover", "patch", "test"):
            for td in registry.tool_defs(phase):
                all_tools.add(td.name)

        # All should be namespaced as flowise__*
        flowise_tools = {t for t in all_tools if t.startswith("flowise__")}
        assert len(flowise_tools) == 51, f"Expected 51, got {len(flowise_tools)}: {sorted(flowise_tools)}"

    def test_executor_has_dual_keys(self, mock_client):
        from flowise_dev_agent.agent.registry import ToolRegistry
        from flowise_dev_agent.mcp.registry import register_flowise_mcp_tools

        registry = ToolRegistry()
        tools = FlowiseMCPTools(mock_client)
        register_flowise_mcp_tools(registry, tools)

        executor = registry.executor("discover")

        # Namespaced key
        assert "flowise__list_chatflows" in executor
        assert "flowise__get_chatflow" in executor
        assert "flowise__create_prediction" in executor
        assert "flowise__ping" in executor

        # Simple key (backwards compat)
        assert "list_chatflows" in executor
        assert "get_chatflow" in executor

    @pytest.mark.asyncio
    async def test_executor_callable_reaches_tool(self, mock_client):
        from flowise_dev_agent.agent.registry import ToolRegistry
        from flowise_dev_agent.mcp.registry import register_flowise_mcp_tools

        registry = ToolRegistry()
        tools = FlowiseMCPTools(mock_client)
        register_flowise_mcp_tools(registry, tools)

        executor = registry.executor("discover")
        fn = executor["flowise__list_chatflows"]
        result = await fn()
        assert isinstance(result, ToolResult)
        assert result.ok is True
        assert "2 chatflows" in result.summary

    @pytest.mark.asyncio
    async def test_executor_with_args(self, mock_client):
        from flowise_dev_agent.agent.registry import ToolRegistry
        from flowise_dev_agent.mcp.registry import register_flowise_mcp_tools

        registry = ToolRegistry()
        tools = FlowiseMCPTools(mock_client)
        register_flowise_mcp_tools(registry, tools)

        executor = registry.executor("discover")
        fn = executor["flowise__get_chatflow"]
        result = await fn(chatflow_id="cf-1")
        assert result.ok is True
        assert "cf-1" in result.summary


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


class TestImportSmoke:
    """Module imports work correctly."""

    def test_import_mcp_package(self):
        from flowise_dev_agent.mcp import FlowiseMCPTools  # noqa: F401

    def test_import_tools(self):
        from flowise_dev_agent.mcp.tools import FlowiseMCPTools  # noqa: F401

    def test_import_registry(self):
        from flowise_dev_agent.mcp.registry import register_flowise_mcp_tools  # noqa: F401
