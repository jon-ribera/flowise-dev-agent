"""M10.4 — External MCP server (DD-099).

Tests for the registry-driven MCP server, single dispatch, and serialization.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from flowise_dev_agent.agent.tools import ToolResult
from flowise_dev_agent.mcp.registry import TOOL_CATALOG
from flowise_dev_agent.mcp.server import _serialize, create_server
from flowise_dev_agent.mcp.tools import FlowiseMCPTools


# ---------------------------------------------------------------------------
# Catalog integrity
# ---------------------------------------------------------------------------


def test_catalog_has_51_tools():
    assert len(TOOL_CATALOG) == 51


def test_catalog_method_names_match_tools_class():
    for method_name, _td in TOOL_CATALOG:
        assert hasattr(FlowiseMCPTools, method_name), (
            f"TOOL_CATALOG references '{method_name}' but FlowiseMCPTools has no such method"
        )


def test_catalog_entries_have_required_fields():
    for method_name, td in TOOL_CATALOG:
        assert td.name, f"{method_name}: ToolDef.name is empty"
        assert td.description, f"{method_name}: ToolDef.description is empty"
        assert isinstance(td.parameters, dict), f"{method_name}: ToolDef.parameters is not a dict"


# ---------------------------------------------------------------------------
# list_tools handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_returns_mcp_types():
    from mcp import types

    tools = MagicMock(spec=FlowiseMCPTools)
    server = create_server(tools)

    handler = server.request_handlers[types.ListToolsRequest]
    server_result = await handler(types.ListToolsRequest(method="tools/list"))
    tool_list = server_result.root.tools

    assert len(tool_list) == 51
    assert all(isinstance(t, types.Tool) for t in tool_list)
    assert tool_list[0].name == "ping"
    assert tool_list[0].inputSchema is not None


# ---------------------------------------------------------------------------
# call_tool handler — dispatch
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tools():
    tools = MagicMock(spec=FlowiseMCPTools)
    tools.ping = AsyncMock(return_value=ToolResult(
        ok=True, summary="pong", facts={}, data={"status": "pong"}, error=None, artifacts=None,
    ))
    return tools


@pytest.mark.asyncio
async def test_call_tool_dispatches_by_name(mock_tools):
    from mcp import types

    server = create_server(mock_tools)
    handler = server.request_handlers[types.CallToolRequest]

    server_result = await handler(types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name="ping", arguments={}),
    ))

    mock_tools.ping.assert_awaited_once_with()
    content = server_result.root.content
    assert len(content) == 1
    parsed = json.loads(content[0].text)
    assert parsed["ok"] is True
    assert parsed["summary"] == "pong"


@pytest.mark.asyncio
async def test_call_tool_unknown_name(mock_tools):
    from mcp import types

    server = create_server(mock_tools)
    handler = server.request_handlers[types.CallToolRequest]

    server_result = await handler(types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name="nonexistent_tool", arguments={}),
    ))

    content = server_result.root.content
    assert len(content) == 1
    parsed = json.loads(content[0].text)
    assert parsed["ok"] is False
    assert "Unknown tool" in parsed["error"]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_serialize_ok_result():
    r = ToolResult(ok=True, summary="Listed 5 chatflows", facts={}, data=[1, 2, 3], error=None, artifacts=None)
    text = _serialize(r)
    parsed = json.loads(text)
    assert parsed["ok"] is True
    assert parsed["summary"] == "Listed 5 chatflows"
    assert parsed["data"] == [1, 2, 3]
    assert parsed["error"] is None


def test_serialize_error_result():
    r = ToolResult(ok=False, summary="Failed", facts={}, data=None, error={"type": "NotFound", "detail": "gone"}, artifacts=None)
    text = _serialize(r)
    parsed = json.loads(text)
    assert parsed["ok"] is False
    assert parsed["error"]["type"] == "NotFound"


# ---------------------------------------------------------------------------
# Entry point importable
# ---------------------------------------------------------------------------


def test_entrypoint_importable():
    import flowise_dev_agent.mcp.__main__  # noqa: F401
