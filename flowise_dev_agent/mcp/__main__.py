"""Entry point: ``python -m flowise_dev_agent.mcp``

Starts the native Flowise MCP server over stdio (default) so Cursor IDE
and Claude Desktop can discover all 51 tools without the cursorwise dependency.

Environment variables
---------------------
FLOWISE_API_KEY          Flowise API key (required for authenticated calls).
FLOWISE_API_ENDPOINT     Flowise base URL (default ``http://localhost:3000``).
FLOWISE_TIMEOUT          Request timeout in seconds (default ``120``).
CURSORWISE_LOG_LEVEL     Python log level (default ``WARNING``).
MCP_TRANSPORT            ``stdio`` (default) or ``sse`` (not yet implemented).
"""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.environ.get("CURSORWISE_LOG_LEVEL", "WARNING").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

from flowise_dev_agent.client import FlowiseClient, Settings  # noqa: E402
from flowise_dev_agent.mcp.server import create_server  # noqa: E402
from flowise_dev_agent.mcp.tools import FlowiseMCPTools  # noqa: E402


async def main() -> None:
    settings = Settings.from_env()
    client = FlowiseClient(settings)
    try:
        tools = FlowiseMCPTools(client, anchor_dict_getter=None)
        server = create_server(tools)

        transport = os.environ.get("MCP_TRANSPORT", "stdio")
        if transport == "sse":
            raise NotImplementedError("SSE transport not yet wired — use stdio")

        from mcp.server.stdio import stdio_server  # noqa: E402

        async with stdio_server() as (read_stream, write_stream):
            init_options = server.create_initialization_options()
            await server.run(read_stream, write_stream, init_options)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
