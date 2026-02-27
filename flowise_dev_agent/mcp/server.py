"""External MCP server — exposes FlowiseMCPTools via MCP protocol (M10.4, DD-099).

Uses the low-level ``mcp.server.Server`` with a single ``call_tool`` dispatcher
driven by ``TOOL_CATALOG``.  Zero per-tool wrappers, zero schema duplication.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp import types
from mcp.server import Server

from flowise_dev_agent.agent.tools import ToolResult
from flowise_dev_agent.mcp.registry import TOOL_CATALOG
from flowise_dev_agent.mcp.tools import FlowiseMCPTools

logger = logging.getLogger(__name__)

# Pre-compute name → method_name for O(1) dispatch.
_DISPATCH: dict[str, str] = {td.name: method_name for method_name, td in TOOL_CATALOG}


def create_server(tools: FlowiseMCPTools) -> Server:
    """Create an MCP Server wired to the given *tools* instance.

    The server exposes every entry in ``TOOL_CATALOG`` — adding a tool there
    automatically makes it available here.
    """
    server = Server("flowise")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=td.name,
                description=td.description or "",
                inputSchema=td.parameters,
            )
            for _method_name, td in TOOL_CATALOG
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> list[types.TextContent]:
        method_name = _DISPATCH.get(name)
        if method_name is None:
            payload = json.dumps({"ok": False, "error": f"Unknown tool: {name}"})
            return [types.TextContent(type="text", text=payload)]

        method = getattr(tools, method_name)
        result: ToolResult = await method(**(arguments or {}))
        return [types.TextContent(type="text", text=_serialize(result))]

    return server


def _serialize(r: ToolResult) -> str:
    """Serialize a ToolResult to JSON for MCP transport."""
    return json.dumps(
        {"ok": r.ok, "summary": r.summary, "data": r.data, "error": r.error},
        default=str,
    )
