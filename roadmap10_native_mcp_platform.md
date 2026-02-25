# ROADMAP10 — Native MCP Platform

## Purpose

Roadmap 10 establishes `flowise-dev-agent` as a fully self-contained MCP-native platform by:

1. Removing the `cursorwise` pip dependency entirely — internalizing the Flowise HTTP client.
2. Defining a first-class native Flowise MCP tool surface (50 tools) that lives in this repo.
3. Re-wiring the LangGraph graph topology (built in M9.6) to invoke Flowise operations via the native MCP tool surface instead of direct `FlowiseClient` imports.
4. Optionally exposing the native MCP tool surface as an external MCP server for Cursor IDE, Claude Desktop, and future Flowise native integration.
5. Formalizing the new relationship between this repo and the `cursorwise` repo.

### What does NOT change in this roadmap

- The deterministic compiler (`compile_flow_data`) stays. The compiler transforms Patch IR into valid Flowise flow JSON — this is a data transformation pipeline, not an I/O operation, and gains nothing from the MCP protocol.
- The M9.6 LangGraph topology structure (18 nodes, CREATE/UPDATE routing, budgets, retries) is preserved. Roadmap 10 re-wires the I/O operations inside those nodes.
- HITL interrupts (4 points) are unchanged.
- All existing tests continue to pass at every milestone boundary.

---

## Guiding principles

1. **MCP at the I/O boundary only.** MCP tools own all reads and writes to the Flowise REST API. Deterministic transformations (compiler, schema parsing, validation) remain as pure Python.
2. **In-process by default.** Tool functions are called directly as Python coroutines inside the LangGraph executor — no stdio/SSE protocol overhead for internal calls.
3. **External MCP server is a wrapper, not the source.** The FastMCP server in M10.4 wraps the same native tool functions; it does not own separate logic.
4. **One canonical Flowise client.** `flowise_dev_agent/client/` is the single source of truth for Flowise HTTP communication. Nothing else imports httpx for Flowise calls.
5. **Backwards compatibility at every step.** Each milestone produces a passing test suite. No milestone breaks the existing agent session flow.

---

## Architecture target

```
flowise-dev-agent (single process)
├── LangGraph agent (M9.6 topology)
│   ├── resolve_target node  ──────────────────┐
│   ├── load_current_flow node  ───────────────┤
│   ├── apply_patch node  ─────────────────────┤──→ execute_tool() → ToolRegistry
│   ├── test node  ─────────────────────────────┤                        │
│   └── compile_flow_data node (compiler)        │   flowise.list_chatflows
│                                                │   flowise.get_chatflow
├── flowise_dev_agent/mcp/                       │   flowise.create_chatflow
│   ├── tools.py  ← 50 native tool functions ←──┘   flowise.update_chatflow
│   ├── server.py ← FastMCP wrapper (external)       flowise.create_prediction
│   └── __main__.py ← entry point                    … (46 more)
│
└── flowise_dev_agent/client/
    ├── flowise_client.py  ← httpx wrapper (was cursorwise/client.py)
    └── config.py          ← Settings (was cursorwise/config.py)

External access (optional):
  Cursor IDE / Claude Desktop / Flowise native
    └──→ stdio or SSE ──→ flowise_dev_agent/mcp/server.py
                              └── same native tool functions
```

---

## M10.1 — Internalize FlowiseClient (remove cursorwise pip dependency)

### Goal

Remove `cursorwise @ git+https://github.com/jon-ribera/cursorwise.git` from `pyproject.toml`
and own the Flowise HTTP client natively inside this repo.

### Why now

Every subsequent milestone depends on a clean internal client. This is the foundation.
cursorwise imports are scattered across 5 files (24 total usages); removing them
unblocks the MCP tool surface definition and the graph re-wiring.

### Deliverables

#### New files

**`flowise_dev_agent/client/__init__.py`**
- Re-exports `FlowiseClient` and `Settings` so all imports become
  `from flowise_dev_agent.client import FlowiseClient, Settings`.

**`flowise_dev_agent/client/flowise_client.py`**
- Direct port of `cursorwise/client.py`.
- Thin async httpx wrapper covering the Flowise REST API surface used by this agent.
- Methods mapped from existing cursorwise usage (graph.py, tools.py, refresh.py):
  - `get_node_types()` → `GET /nodes`
  - `get_node(name)` → `GET /nodes/{name}`
  - `list_chatflows()` → `GET /chatflows`
  - `get_chatflow(id)` → `GET /chatflows/{id}`
  - `create_chatflow(name, flow_data, ...)` → `POST /chatflows`
  - `update_chatflow(id, ...)` → `PUT /chatflows/{id}`
  - `delete_chatflow(id)` → `DELETE /chatflows/{id}`
  - `create_prediction(id, question, ...)` → `POST /prediction/{id}`
  - `list_credentials()` → `GET /credentials`
  - `list_templates()` → `GET /marketplaces/templates`
- Typed return: raw `dict | list` (no ToolResult wrapping at this layer).
- Error model: returns `{"error": str, "detail": str}` on HTTP failure (same as cursorwise).
- No business logic. No schema parsing. No ToolResult.

**`flowise_dev_agent/client/config.py`**
- Direct port of `cursorwise/config.py`.
- `Settings` dataclass with `from_env()` classmethod.
- Env vars: `FLOWISE_API_KEY`, `FLOWISE_API_ENDPOINT` (default `http://localhost:3000`),
  `FLOWISE_TIMEOUT` (default `120`).

#### Modified files

| File | Change |
|------|--------|
| `flowise_dev_agent/agent/graph.py` | Replace 7 cursorwise imports with `from flowise_dev_agent.client import FlowiseClient, Settings` |
| `flowise_dev_agent/agent/tools.py` | Replace 14 cursorwise imports (same) |
| `flowise_dev_agent/api.py` | Replace 3 cursorwise imports (same) |
| `flowise_dev_agent/instance_pool.py` | Replace cursorwise imports |
| `flowise_dev_agent/cli.py` | Replace cursorwise imports |
| `flowise_dev_agent/knowledge/refresh.py` | Replace cursorwise imports |
| `pyproject.toml` | Remove `cursorwise @ git+...` dependency; add `httpx>=0.27` if not already present |

#### New tests

**`tests/test_m101_flowise_client.py`**
- `FlowiseClient` instantiates with `Settings.from_env()`.
- `Settings` reads env vars correctly with defaults.
- `FlowiseClient._get` / `_post` wrap httpx correctly (mock `httpx.AsyncClient`).
- HTTP error → returns `{"error": "HTTP 4xx", "detail": ...}` (not raises).
- All 5 import locations can be imported after cursorwise removal.

### Acceptance criteria

- `pytest tests/ -x -q` passes with `cursorwise` uninstalled from the environment.
- `grep -r "from cursorwise" flowise_dev_agent/` returns no results.
- `pyproject.toml` has no cursorwise dependency entry.

### Design decision

**DD-078**: FlowiseClient internalization — single source of truth for Flowise HTTP
communication lives in `flowise_dev_agent/client/`. cursorwise is no longer a
runtime dependency. The client interface is intentionally minimal (raw dict returns,
no business logic) to stay decoupled from the tool surface defined in M10.2.

---

## M10.2 — Native Flowise MCP tool surface (50 tools)

### Goal

Define all 50 Flowise operations as first-class async Python tool functions inside
this repo. These are the canonical implementation — the external MCP server in M10.4
is a thin wrapper around them.

### Tool surface inventory (ported from cursorwise/server.py, 386 lines, 50 tools)

Grouped by domain:

**Chatflow CRUD (6)**
- `list_chatflows()` — list all chatflows with id, name, deployed, type
- `get_chatflow(chatflow_id)` — full chatflow JSON including flowData
- `get_chatflow_by_apikey(apikey)` — resolve chatflow by API key
- `create_chatflow(name, flow_data, description, chatflow_type)` — create new
- `update_chatflow(chatflow_id, name, flow_data, description, deployed, is_public, chatbot_config, category)` — update existing
- `delete_chatflow(chatflow_id)` — delete

**Node schema (2)**
- `list_nodes()` — all available node types (used by refresh pipeline)
- `get_node(name)` — single node schema by name (used by repair path)

**Predictions (1)**
- `create_prediction(chatflow_id, question, override_config, history, streaming)` — run chatflow

**Assistants (5)**
- `list_assistants()`, `get_assistant(id)`, `create_assistant(...)`, `update_assistant(...)`, `delete_assistant(id)`

**Custom tools (5)**
- `list_tools()`, `get_tool(id)`, `create_tool(...)`, `update_tool(...)`, `delete_tool(id)`

**Variables (4)**
- `list_variables()`, `create_variable(...)`, `update_variable(...)`, `delete_variable(id)`

**Document stores (5 management + 5 operations = 10)**
- `list_document_stores()`, `get_document_store(id)`, `create_document_store(...)`,
  `update_document_store(...)`, `delete_document_store(id)`
- `get_document_chunks(store_id, loader_id, page_no)`
- `update_document_chunk(store_id, loader_id, chunk_id, ...)`
- `delete_document_chunk(store_id, loader_id, chunk_id)`
- `delete_document_loader(store_id, loader_id)`
- `delete_vectorstore_data(store_id)`

**Document operations (3)**
- `upsert_document(store_id, loader, splitter, embedding, vector_store, ...)` — ingest
- `refresh_document_store(store_id, items)` — re-sync
- `query_document_store(store_id, query)` — semantic search

**Chat messages (2)**
- `list_chat_messages(chatflow_id, chat_type, order, chat_id, session_id, start_date, end_date)`
- `delete_chat_messages(chatflow_id, chat_id, chat_type, session_id, hard_delete)`

**Feedback (3)**
- `list_feedback(chatflow_id, ...)`, `create_feedback(...)`, `update_feedback(...)`

**Leads (2)**
- `list_leads(chatflow_id)`, `create_lead(...)`

**Vector operations (3)**
- `upsert_vector(chatflow_id, stop_node_id, override_config)` — trigger vector upsert
- `list_upsert_history(chatflow_id, order, start_date, end_date)`
- `delete_upsert_history(chatflow_id, ids)`

**Credentials (2)**
- `list_credentials()` — returns id, name, credentialName, created_at, updated_at (allowlisted only)
- `create_credential(name, credential_name, encrypted_data)` — create

**Marketplace (1)**
- `list_marketplace_templates()` — all template metadata

**Utility (1)**
- `ping()` — connectivity check

### Deliverables

**`flowise_dev_agent/mcp/__init__.py`**
- Package init; re-exports `FlowiseMCPTools`.

**`flowise_dev_agent/mcp/tools.py`**
- `FlowiseMCPTools` class initialized with a `FlowiseClient` instance.
- All 50 tool functions as `async def` methods.
- Each method returns a `ToolResult` (using the existing typed envelope).
  - `.ok` — True if HTTP call succeeded
  - `.summary` — ≤300 char human-readable description (for LLM context)
  - `.data` — raw response dict/list (for debug/artifacts)
  - `.error` — error string if failed
- No business logic beyond what is needed to call the API and format the result.
- `_CREDENTIAL_ALLOWLIST` applied in `list_credentials()` (same as `CredentialStore`).

**`flowise_dev_agent/mcp/registry.py`**
- `register_flowise_mcp_tools(registry: ToolRegistry, tools: FlowiseMCPTools)` —
  registers all 50 tools under `flowise.*` namespace.
- Example registrations:
  - `flowise.list_chatflows`
  - `flowise.get_chatflow`
  - `flowise.create_chatflow`
  - `flowise.update_chatflow`
  - `flowise.create_prediction`
  - … (all 50)

#### New tests

**`tests/test_m102_flowise_mcp_tools.py`**
- Each of the 4 primary graph-path tools tested with mocked `FlowiseClient`:
  - `list_chatflows` → returns `ToolResult(ok=True, summary=..., data=[...])`
  - `get_chatflow` → returns full flow JSON in `.data`
  - `create_chatflow` → returns created id in `.data`
  - `update_chatflow` → returns updated chatflow in `.data`
- HTTP error path → `ToolResult(ok=False, error=...)`
- `list_credentials` respects allowlist (no `encryptedData` in output)
- `ping` returns ok=True with connected Flowise endpoint

### Acceptance criteria

- All 50 tools instantiate and call through without import errors.
- Primary graph-path tools (list, get, create, update chatflow + create_prediction)
  are unit tested with mock client.
- `ToolResult` is returned by all tools (no raw dict leakage).

### Design decision

**DD-079**: Native Flowise MCP tool surface — 50 tool functions defined as first-class
async methods in `flowise_dev_agent/mcp/tools.py`. These are the canonical
implementation for all Flowise API operations. The external MCP server (M10.4)
wraps them; the LangGraph executor calls them directly. Separation: tools.py owns
the I/O contract; client.py owns the HTTP mechanics; the compiler owns the
transformation logic. None of these three layers cross-owns the other.

---

## M10.3 — LangGraph graph topology re-wiring (native MCP tools → executor)

### Goal

Re-wire the M9.6 LangGraph graph topology so that all Flowise API operations
flow through `execute_tool()` → `ToolRegistry` → `FlowiseMCPTools` instead of
direct `FlowiseClient` method calls embedded in graph node functions.

This is the milestone that delivers "MCP at the LangGraph layer."

### What changes vs M9.6

M9.6 built the correct topology structure (18 nodes, CREATE/UPDATE routing,
budgets, retries). M10.3 changes only the implementation inside nodes that call
Flowise — the node structure, routing, and budget logic are unchanged.

| M9.6 node | Current implementation | M10.3 implementation |
|-----------|----------------------|---------------------|
| `resolve_target` | `client.list_chatflows()` direct | `execute_tool("flowise.list_chatflows", ...)` |
| `load_current_flow` | `client.get_chatflow(id)` direct | `execute_tool("flowise.get_chatflow", ...)` |
| `apply_patch` | `client.create_chatflow(...)` / `update_chatflow(...)` direct | `execute_tool("flowise.create_chatflow", ...)` / `execute_tool("flowise.update_chatflow", ...)` |
| `test` | `client.create_prediction(...)` direct | `execute_tool("flowise.create_prediction", ...)` |
| `repair_schema` | `client.get_node(name)` via NodeSchemaStore repair path | `execute_tool("flowise.get_node", ...)` |
| `compile_flow_data` | Deterministic compiler — **unchanged** | **unchanged** |

### Deliverables

#### Graph initialization change

`build_graph()` receives a `FlowiseMCPTools` instance (or None for legacy path).
If provided, `register_flowise_mcp_tools(registry, tools)` is called at startup,
replacing the current pattern where `FlowiseClient` is instantiated per node.

```python
# Before (M9.6)
async def _resolve_target_node(state):
    client = FlowiseClient(settings)
    raw = await client.list_chatflows()
    ...

# After (M10.3)
async def _resolve_target_node(state):
    result = await execute_tool("flowise.list_chatflows", {}, executor)
    ...
```

#### State contract additions

No new state fields required — M9.6 state schema covers everything. Tool results
flow into the same `facts/artifacts/debug` trifurcation already in place.

#### FlowiseCapability update

`FlowiseCapability.__init__` initializes `FlowiseMCPTools(client)` and registers
via `register_flowise_mcp_tools`. Direct `FlowiseClient` usage inside capability
methods is replaced with `execute_tool` calls.

#### Legacy path preserved

`capabilities=None` (legacy mode) continues to work. `FlowiseClient` is still
available for direct use via `flowise_dev_agent.client`. The legacy path remains
a clean fallback for the duration of any transition.

#### Modified files

| File | Change |
|------|--------|
| `flowise_dev_agent/agent/graph.py` | All `client.xxx()` calls in node functions → `execute_tool("flowise.xxx", ...)` |
| `flowise_dev_agent/agent/tools.py` | Remove `FlowiseClient` direct usage; route through registry |
| `flowise_dev_agent/agent/graph.py` | `build_graph()` accepts and wires `FlowiseMCPTools` |

#### New tests

**`tests/test_m103_graph_mcp_wiring.py`**
- `resolve_target` calls `execute_tool("flowise.list_chatflows")` not `FlowiseClient` directly.
- `load_current_flow` calls `execute_tool("flowise.get_chatflow")`.
- `apply_patch` in CREATE mode calls `execute_tool("flowise.create_chatflow")`.
- `apply_patch` in UPDATE mode calls `execute_tool("flowise.update_chatflow")`.
- Legacy path (`capabilities=None`) still reaches Flowise without `FlowiseMCPTools`.
- All 9 compiler integration tests continue to pass.

### Acceptance criteria

- `grep -r "FlowiseClient" flowise_dev_agent/agent/` returns only the legacy
  compatibility path and imports — no direct method calls inside node functions.
- `pytest tests/ -x -q` passes in full.
- A trace of a CREATE session shows tool calls named `flowise.create_chatflow`
  (not raw `client.create_chatflow`) in `debug["flowise"]["phase_metrics"]`.

### Design decision

**DD-080**: LangGraph graph nodes use the MCP tool executor for all Flowise API
operations. This aligns the agent's internal architecture with the MCP-native
design principle: all external I/O flows through the tool registry and can be
observed, mocked, rate-limited, or replaced at a single point. The compiler
remains a direct Python call — it does not cross an I/O boundary.

---

## M10.4 — External MCP server (Cursor IDE + future Flowise native integration)

### Goal

Expose the native Flowise MCP tool surface as an optionally runnable MCP server
so that external clients (Cursor IDE, Claude Desktop, future Flowise integration)
can connect without depending on the cursorwise repo.

This milestone has no impact on the agent's internal operation — it is purely
additive.

### Deliverables

**`flowise_dev_agent/mcp/server.py`**
- FastMCP server that wraps `FlowiseMCPTools`.
- All 50 tools registered as `@mcp.tool()` using the same function bodies as
  `tools.py` (not duplicated — imported and wrapped).
- Lifespan: initializes `FlowiseClient` + `FlowiseMCPTools` from env on startup.
- Transport: configurable via `MCP_TRANSPORT=stdio|sse` env var.
  - `stdio` (default) — for Cursor IDE / Claude Desktop local use.
  - `sse` — for remote/container deployments.
- SSE port: `MCP_PORT` (default `8001`).

**`flowise_dev_agent/mcp/__main__.py`**
- Entry point: `python -m flowise_dev_agent.mcp`
- Loads `.env`, reads `MCP_TRANSPORT`, starts the FastMCP server.

**`flowise_dev_agent/mcp/README.md`** (exception to no-docs rule: MCP config is
non-obvious and required for external consumers)
- How to add to Cursor IDE `mcp.json`.
- How to add to Claude Desktop `claude_desktop_config.json`.
- Required env vars.

#### Cursor IDE config (after M10.4)

```json
{
  "mcpServers": {
    "flowise": {
      "command": "python",
      "args": ["-m", "flowise_dev_agent.mcp"],
      "env": {
        "FLOWISE_API_KEY": "${FLOWISE_API_KEY}",
        "FLOWISE_API_ENDPOINT": "http://localhost:3000"
      }
    }
  }
}
```

#### New tests

**`tests/test_m104_mcp_server.py`**
- `python -m flowise_dev_agent.mcp --help` exits 0 (smoke test entry point).
- FastMCP server lists all 50 tools when `mcp.list_tools()` is called in-process.
- Tool names match `flowise.*` registry namespace.
- Server starts and stops cleanly (no leaked subprocesses).

### Acceptance criteria

- `python -m flowise_dev_agent.mcp` starts without error.
- All 50 tools are discoverable via MCP tool listing.
- Cursor IDE can connect (manual verification, not automated).

### Design decision

**DD-081**: External MCP server as a thin wrapper. The FastMCP server in
`flowise_dev_agent/mcp/server.py` wraps the same tool functions as `tools.py`
without duplicating logic. The server is optional — the agent runs without it.
This design allows the tool surface to be consumed both internally (direct Python
call, zero overhead) and externally (MCP protocol, full interoperability).

---

## M10.5 — Repository decoupling + future Flowise native MCP path

### Goal

Formalize the new relationship between `flowise-dev-agent` and `cursorwise`, and
lay the architectural groundwork for Flowise natively shipping an MCP server.

### Current relationship (before Roadmap 10)

```
flowise-dev-agent  ──imports──→  cursorwise  ──httpx──→  Flowise
```

### New relationship (after M10.1–M10.4)

```
flowise-dev-agent  ──httpx──→  Flowise     (native, no cursorwise dep)
cursorwise (optional)  can now import from flowise-dev-agent MCP server
  OR remain standalone
Cursor IDE  ──MCP──→  flowise_dev_agent.mcp.server  ──httpx──→  Flowise
```

### Future Flowise native MCP path

When Flowise ships a native MCP server endpoint:

```
flowise-dev-agent
  └── MCP_FLOWISE_ENDPOINT=http://flowise:3000/mcp
        └── FlowiseMCPTools points at Flowise directly (no intermediary)
              └── Flowise MCP server handles its own tools natively
```

The `flowise_dev_agent/client/flowise_client.py` would be replaced by an
MCP client (`mcp.ClientSession`) at that point. The tool surface in `tools.py`
and the tool registry wiring in M10.3 remain unchanged — only the transport
underneath `FlowiseMCPTools` changes. This is the correct abstraction boundary.

### Deliverables

**`pyproject.toml`**
- cursorwise removed (completed in M10.1; formally documented here).
- Optional dev dependency entry if cursorwise is still useful for local testing.

**`DESIGN_DECISIONS.md`**
- DD-082: Repository decoupling strategy.
- DD-083: Future Flowise native MCP integration path (transport swap only).

**`README.md` updates**
- Remove cursorwise installation step from setup instructions.
- Add `flowise_dev_agent.mcp` server as the replacement for Cursor IDE integration.
- Document MCP_TRANSPORT config option.

**`roadmap_pending.md`** (when roadmap housekeeping is done)
- Note: Flowise native MCP integration is tracked as a future product item,
  not an implementation item for this repo.

### Acceptance criteria

- A fresh `git clone` + `pip install -e .` succeeds without cursorwise.
- README setup instructions are accurate.
- `python -m flowise_dev_agent.mcp` works as Cursor IDE replacement for cursorwise.

---

## Sequencing

```
M10.1  Internalize FlowiseClient          ← unblocks everything; do first
  │
  ├──→ M10.2  Native MCP tool surface     ← defines the 50 tools
  │      │
  │      └──→ M10.3  Graph re-wiring      ← MCP at the LangGraph layer (requires M9.6 done)
  │             │
  │             └──→ M10.4  External MCP server  ← optional, purely additive
  │                    │
  │                    └──→ M10.5  Repo decoupling + future path
  │
  └──→ (Roadmap 9 milestones continue in parallel — M10.1 does not block M9.x work)
```

### Dependency on M9.6

M10.3 (graph re-wiring) requires M9.6 (topology structure) to be complete first,
because M10.3 re-wires the new node functions built in M9.6. M10.1 and M10.2 can
proceed independently of M9.6 and in parallel with remaining Roadmap 9 milestones.

### Recommended order across both roadmaps

```
Roadmap 9 (remaining):  9.1 → 9.2 → 9.6 → 9.7 → 9.8 → 9.9
Roadmap 10:             10.1 → 10.2  (alongside 9.1/9.2)
                        10.3          (after 9.6)
                        10.4 → 10.5   (after 10.3)
```

---

## Key files summary

| File | Milestone | Status |
|------|-----------|--------|
| `flowise_dev_agent/client/__init__.py` | M10.1 | New |
| `flowise_dev_agent/client/flowise_client.py` | M10.1 | New (ported from cursorwise) |
| `flowise_dev_agent/client/config.py` | M10.1 | New (ported from cursorwise) |
| `flowise_dev_agent/mcp/__init__.py` | M10.2 | New |
| `flowise_dev_agent/mcp/tools.py` | M10.2 | New (50 tool functions) |
| `flowise_dev_agent/mcp/registry.py` | M10.2 | New |
| `flowise_dev_agent/agent/graph.py` | M10.3 | Modified (node re-wiring) |
| `flowise_dev_agent/agent/tools.py` | M10.3 | Modified (remove direct client calls) |
| `flowise_dev_agent/mcp/server.py` | M10.4 | New (FastMCP wrapper) |
| `flowise_dev_agent/mcp/__main__.py` | M10.4 | New |
| `pyproject.toml` | M10.1, M10.5 | Modified |
| `tests/test_m101_flowise_client.py` | M10.1 | New |
| `tests/test_m102_flowise_mcp_tools.py` | M10.2 | New |
| `tests/test_m103_graph_mcp_wiring.py` | M10.3 | New |
| `tests/test_m104_mcp_server.py` | M10.4 | New |

---

## Definition of Done for ROADMAP10

ROADMAP10 is complete when:

- `flowise_dev_agent` has no `cursorwise` import anywhere in source or tests.
- `cursorwise` is not listed as a dependency in `pyproject.toml`.
- All 50 Flowise operations are callable as `execute_tool("flowise.xxx", ...)`.
- The M9.6 graph topology nodes reach Flowise exclusively through the tool executor.
- The deterministic compiler (`compile_flow_data`) is unchanged.
- `python -m flowise_dev_agent.mcp` starts and lists 50 tools via MCP.
- Cursor IDE can be configured to use `flowise_dev_agent.mcp` as a drop-in
  replacement for `cursorwise`.
- `pytest tests/ -q` passes in full.
- DESIGN_DECISIONS.md records DD-078 through DD-083.
- README setup instructions require no cursorwise installation.
