# Flowise Native MCP Server

Standalone MCP server exposing 51 Flowise tools over stdio.
No cursorwise dependency — connects directly via `FlowiseClient`.

## Quick Start

```bash
python -m flowise_dev_agent.mcp
```

## Cursor IDE

Add to `.mcp.json` (repo root or `~/.cursor/.mcp.json`):

```json
{
  "mcpServers": {
    "flowise": {
      "command": "python",
      "args": ["-m", "flowise_dev_agent.mcp"],
      "env": {
        "FLOWISE_API_KEY": "<your-key>",
        "FLOWISE_API_ENDPOINT": "http://localhost:3000"
      }
    }
  }
}
```

## Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "flowise": {
      "command": "python",
      "args": ["-m", "flowise_dev_agent.mcp"],
      "env": {
        "FLOWISE_API_KEY": "<your-key>",
        "FLOWISE_API_ENDPOINT": "http://localhost:3000"
      }
    }
  }
}
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FLOWISE_API_KEY` | *(empty)* | Flowise API key |
| `FLOWISE_API_ENDPOINT` | `http://localhost:3000` | Flowise base URL |
| `FLOWISE_TIMEOUT` | `120` | Request timeout (seconds) |
| `CURSORWISE_LOG_LEVEL` | `WARNING` | Python log level |
| `MCP_TRANSPORT` | `stdio` | Transport (`stdio` only — `sse` not yet implemented) |
