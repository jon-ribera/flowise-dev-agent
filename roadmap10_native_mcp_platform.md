# ROADMAP10 — Native MCP Platform

## Purpose

Roadmap 10 establishes `flowise-dev-agent` as a fully self-contained MCP-native platform by:

1. Removing the `cursorwise` pip dependency entirely — internalizing the Flowise HTTP client.
2. Defining a first-class native Flowise MCP tool surface (51 tools) that lives in this repo.
3. Re-wiring the LangGraph graph topology (built in M9.6) to invoke Flowise operations via the native MCP tool surface instead of direct `FlowiseClient` imports.
4. Optionally exposing the native MCP tool surface as an external MCP server for Cursor IDE, Claude Desktop, and future Flowise native integration.
5. Formalizing the new relationship between this repo and the `cursorwise` repo.

### What does NOT change in this roadmap

- The deterministic compiler (`compile_flow_data`) remains a pure Python data
  transformation pipeline — it is not an I/O operation and gains nothing from the
  MCP protocol. However, the compiler's **anchor resolution strategy** is simplified
  in M10.3a: the 5-pass fuzzy resolver is replaced with exact-match + deprecated
  fallback, enabled by the anchor dictionary tool (M10.2b) that gives the LLM
  exact anchor names before it emits Patch IR.
- The M9.6 LangGraph topology structure (18 nodes, CREATE/UPDATE routing, budgets,
  retries) is preserved. Roadmap 10 re-wires the I/O operations inside those nodes.
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

## M10.1 — Internalize FlowiseClient (remove cursorwise pip dependency) ✅

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

**DD-093**: FlowiseClient internalization — single source of truth for Flowise HTTP
communication lives in `flowise_dev_agent/client/`. cursorwise is no longer a
runtime dependency. The client interface is intentionally minimal (raw dict returns,
no business logic) to stay decoupled from the tool surface defined in M10.2.

---

## M10.2 — Native Flowise MCP tool surface (50 tools) ✅

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

**DD-094**: Native Flowise MCP tool surface — 50 tool functions defined as first-class
async methods in `flowise_dev_agent/mcp/tools.py`. These are the canonical
implementation for all Flowise API operations. The external MCP server (M10.4)
wraps them; the LangGraph executor calls them directly. Separation: tools.py owns
the I/O contract; client.py owns the HTTP mechanics; the compiler owns the
transformation logic. None of these three layers cross-owns the other.

---

## M10.2a — Canonical Schema Normalization Contract ✅

### Goal

Normalize node schemas from `NodeSchemaStore` into a canonical anchor dictionary
format. `AnchorDictionaryStore` is a **derived view** — it consumes
`NodeSchemaStore._index` (the authoritative schema registry), not the snapshot file
directly. Every node type maps to an unambiguous list of input/output anchors with
`name`, `type`, `id_template`, and `compatible_types[]`.

### Why now

The compiler's 5-pass fuzzy resolver (`_resolve_anchor_id()` in `compiler.py`) is
brittle: each new anchor mismatch requires a new resolver pass. Session `ebb04388`
revealed that `"BaseMemory"` couldn't match `"BaseChatMemory"` — DD-092 patched it
with Pass 5 (camelCase token matching), but this is unsustainable. A canonical anchor
dictionary eliminates the guessing by providing the LLM with exact anchor names
before it emits Patch IR.

This milestone creates the **data layer** that the anchor dictionary tool (M10.2b)
and the Patch IR contract update (M10.3a) depend on.

### Canonical anchor entry format

Each anchor is normalized into this shape:

```python
{
    "node_type": "toolAgent",
    "direction": "input",                                # "input" | "output"
    "name": "memory",                                    # canonical name (exact match key)
    "label": "Memory",                                   # human-readable label
    "type": "BaseChatMemory",                            # primary type
    "id_template": "{nodeId}-input-memory-BaseChatMemory",  # see sourcing rules below
    "compatible_types": ["BaseChatMemory", "BaseMemory"],   # advisory — see note below
    "optional": True
}
```

**`id_template` sourcing**:
- **Preferred**: When the raw/processed schema provides an `id` field on the anchor
  (e.g. `"{nodeId}-input-memory-BaseChatMemory"`), use it verbatim as `id_template`.
  This is the common path — virtually all anchors in `flowise_nodes.snapshot.json`
  already carry a well-formed `id` with the `{nodeId}` placeholder.
- **Fallback (fabricated)**: Only when the schema does not provide an `id` field
  (e.g. a hand-crafted or incomplete node definition), derive `id_template` from
  convention: `{nodeId}-{direction}-{name}-{type}`. Mark it with a
  `"id_source": "fabricated"` flag in the entry so downstream consumers can
  distinguish schema-sourced from synthesized IDs.

**`compatible_types` computation**:
- Start with the pipe-separated `type` field from the raw schema
  (e.g. `"ChatOpenAI | BaseChatOpenAI | BaseChatModel | BaseLanguageModel | Runnable"`)
- Split on `|`, strip whitespace → `["ChatOpenAI", "BaseChatOpenAI", "BaseChatModel", "BaseLanguageModel", "Runnable"]`
- For input anchors, additionally extract CamelCase parent tokens from the primary type:
  `"BaseChatMemory"` → tokens `{"Base", "Chat", "Memory"}` → parent `"BaseMemory"` is
  a valid compatible type because `{"Base", "Memory"} ⊆ {"Base", "Chat", "Memory"}`
- Deduplicate and sort alphabetically

**`compatible_types` is advisory, not a hard gate.** This list is a best-effort hint
to guide the LLM when choosing connections. Final authority on whether a connection
is valid remains with `_validate_flow_data()` (structural validation) and the test
execution phase (runtime validation). The compiler and `validate_patch_ops()` should
**not** reject a connection solely because it is absent from `compatible_types` —
Flowise's own runtime may accept connections that the static type list does not cover.

### Deliverables

#### New files

**`flowise_dev_agent/knowledge/anchor_store.py`**
- `AnchorDictionaryStore` class — mirrors `CredentialStore` pattern (provider.py).
- Three indices for O(1) lookup:
  - `_by_node_type: dict[str, dict]` — node_type → `{input_anchors: [...], output_anchors: [...]}`
  - `_by_anchor_name: dict[str, list[dict]]` — lowercase anchor name → list of entries
  - `_by_type_token: dict[str, list[dict]]` — lowercase type name → list of compatible entries
- `get(node_type: str) -> dict | None` — returns full anchor dict for a node type.
- `get_or_repair(node_type, api_fetcher) -> dict | None` — async repair fallback
  (fetches via API `get_node(name)`, normalizes into the **same canonical format**
  as snapshot-derived schemas, persists, re-indexes). The repair path MUST produce
  identical anchor entry shapes — no raw schema dialect may leak into compilation paths.
- `is_compatible(source_type: str, target_anchor: dict) -> bool` — checks if a source
  output type appears in the target anchor's `compatible_types`.
- **Derived from `NodeSchemaStore`** — not a parallel pipeline. On first access,
  `AnchorDictionaryStore` reads `NodeSchemaStore._index` and builds its three indices.
  No separate snapshot file. If `NodeSchemaStore` is refreshed or repaired, the
  anchor dictionary is invalidated and rebuilt on next access.

#### Modified files

| File | Change |
|------|--------|
| `flowise_dev_agent/knowledge/provider.py` | Add `anchor_dictionary` property to `FlowiseKnowledgeProvider`; instantiate `AnchorDictionaryStore` from `NodeSchemaStore._index` |
| `flowise_dev_agent/knowledge/anchor_store.py` | New file — `AnchorDictionaryStore` |

#### New tests

**`tests/test_m102a_anchor_store.py`**
- All 303 node types produce valid anchor entries (no empty `name`, no missing `type`).
- `toolAgent` input anchor `name="memory"` has `compatible_types` containing
  `"BaseChatMemory"` AND `"BaseMemory"`.
- `chatOpenAI` output anchor `compatible_types` includes full chain:
  `["ChatOpenAI", "BaseChatOpenAI", "BaseChatModel", "BaseLanguageModel", "Runnable"]`.
- O(1) lookup by `node_type` returns correct anchor list.
- `is_compatible("ChatOpenAI", target_anchor_for_model)` returns True
  (because `ChatOpenAI` inherits `BaseChatModel`).
- Repair fallback: unknown node type triggers API fetch + re-index.

### Acceptance criteria

- Every node in snapshot produces a complete anchor dictionary entry.
- `compatible_types` correctly captures the pipe-separated type hierarchy.
- Lookup is sync O(1) from warm cache.
- `FlowiseKnowledgeProvider.anchor_dictionary` property is accessible.
- Repair fallback normalizes raw `get_node` schema into canonical anchor dictionary
  format; no raw schema dialect leaks into compilation paths.
- `id_template` is sourced from the schema's `id` field when available; fabricated
  IDs are flagged with `"id_source": "fabricated"`.
- `compatible_types` is advisory — no compilation or validation path rejects a
  connection solely because a type is absent from this list.

### Design decision

**DD-095**: Canonical Schema Normalization Contract — `AnchorDictionaryStore` is a
**derived view** of `NodeSchemaStore`, not a parallel pipeline. It normalizes raw node
schemas into a canonical anchor format with exact `name` fields, schema-sourced
`id_template` values, and computed `compatible_types` arrays (advisory, not enforcement).
This is the data foundation for the anchor dictionary tool (M10.2b) and the Patch IR
contract simplification (M10.3a). The store reads `NodeSchemaStore._index` on first
access and rebuilds when the schema store is refreshed or repaired — no separate
snapshot file. It follows the same O(1)-local-first, repair-on-miss pattern as
`CredentialStore`. The repair path produces identical canonical entries regardless of
whether the source is a snapshot or a live API response.

---

## M10.2b — Anchor Dictionary Tool ✅

### Goal

Add a new MCP tool `flowise.get_anchor_dictionary(node_type)` that the LLM calls
during plan/patch phases to get the exact anchor specification for any node type.
This eliminates the need for the LLM to guess anchor names or types.

### Why now

The LLM currently receives anchor guidance only through prompt instructions (which
conflict: skills doc says "match by name", compile prompt says "use type"). The LLM
has no runtime tool to look up the exact anchor names, so it guesses — and the compiler
compensates with 5 fuzzy passes. By providing a tool, the LLM can query exact anchor
specs on demand, achieving 100% exact-match resolution.

### Tool specification

**Registration**: `flowise.get_anchor_dictionary` (tool #51 in the MCP tool surface)

**Signature**:
```python
async def get_anchor_dictionary(self, node_type: str) -> ToolResult:
    """Return the canonical anchor dictionary for a node type.

    The system ensures anchor dictionaries are available for all node types
    involved in Connect ops — via prefetch (in-process) or on-demand tool
    call. Use the 'name' field from input_anchors/output_anchors as the
    exact value for target_anchor/source_anchor in Connect operations.
    """
```

**Return shape** (in `ToolResult.data`):
```json
{
    "node_type": "toolAgent",
    "input_anchors": [
        {
            "name": "memory",
            "type": "BaseChatMemory",
            "compatible_types": ["BaseChatMemory", "BaseMemory"],
            "optional": true
        },
        {
            "name": "model",
            "type": "BaseChatModel",
            "compatible_types": ["BaseChatModel", "BaseLanguageModel"],
            "optional": false
        }
    ],
    "output_anchors": [
        {
            "name": "toolAgent",
            "type": "AgentExecutor | BaseChain | Runnable",
            "compatible_types": ["AgentExecutor", "BaseChain", "Runnable"]
        }
    ]
}
```

**`ToolResult.summary`**: `"toolAgent: 2 inputs (memory, model), 1 output (toolAgent)"`

**Error case**: Unknown node type → `ToolResult(ok=False, error="Unknown node type 'foo'. Use list_nodes() to discover available types.")`

### LLM prompt update

**`_COMPILE_PATCH_IR_V2_SYSTEM`** (graph.py) updated to include:

```
ANCHOR RESOLUTION RULES:

1. The system pre-fetches anchor dictionaries for all node types listed in your
   plan. If you need anchors for a node type not yet fetched, call
   get_anchor_dictionary(node_type) on demand.

2. All Connect ops MUST use canonical anchor 'name' fields:
     - source_anchor = output anchor 'name' from source node's dictionary
     - target_anchor = input anchor 'name' from target node's dictionary

3. Use 'compatible_types' as an advisory guide when choosing connections.
   If uncertain about compatibility, prefer types listed in compatible_types,
   but note that final validation is performed by validate_flow_data and
   the test execution phase — not by compatible_types alone.

4. DO NOT guess anchor names. DO NOT use type names (e.g. "BaseChatModel")
   as anchor names. Always use the canonical 'name' field (e.g. "model",
   "memory", "chatOpenAI").
```

**Prefetch strategy**: The `compile_patch_ir` node prefetches anchor dictionaries
in-process for **all node types involved in Connect ops for the current iteration**:
- In **CREATE mode**: all node types from `AddNode` ops in the plan.
- In **UPDATE mode**: all `AddNode` node types **plus** the node types of existing
  nodes in the loaded flow that may be re-wired (i.e., any node referenced as a
  source or target in a `Connect` op whose ID is not in the `AddNode` set — these
  are existing nodes from the base graph).

This means the LLM typically has all anchors available in context without making
explicit tool calls. The LLM should call `get_anchor_dictionary` on-demand only for
node types not covered by prefetch (rare) or when a compilation attempt fails due to
unresolved anchors.

### Deliverables

#### Modified files

| File | Change |
|------|--------|
| `flowise_dev_agent/mcp/tools.py` | Add `get_anchor_dictionary()` method to `FlowiseMCPTools` |
| `flowise_dev_agent/mcp/registry.py` | Register as `flowise.get_anchor_dictionary` (tool count: 50 → 51) |
| `flowise_dev_agent/agent/graph.py` | Update `_COMPILE_PATCH_IR_V2_SYSTEM` prompt with anchor resolution rules + prefetch strategy |
| `flowise_dev_agent/agent/tools.py` | Add `get_anchor_dictionary` to `DomainTools` and executor |
| `flowise_dev_agent/skills/flowise_builder.md` | Update Patch IR docs: `target_anchor` = canonical name, not type |

#### New tests

**`tests/test_m102b_anchor_tool.py`**
- `get_anchor_dictionary("toolAgent")` returns correct input/output anchor lists.
- `get_anchor_dictionary("nonExistentNode")` returns `ToolResult(ok=False, error=...)`.
- Tool is registered and callable via `execute_tool("flowise.get_anchor_dictionary", {"node_type": "toolAgent"})`.
- Updated prompt includes mandatory `get_anchor_dictionary` instruction.

### Acceptance criteria

- LLM can call `get_anchor_dictionary` for any of the 303+ node types.
- Response includes exact `name` fields that match what the compiler expects.
- `compatible_types` is included as an advisory guide; it does not gate compilation.
- The compile prompt explicitly forbids guessing anchor names.
- Anchor dictionaries are prefetched in-process for all node types involved in
  Connect ops (AddNode types + UPDATE-mode existing nodes being re-wired); the LLM
  calls the tool on-demand only for node types not covered by prefetch.

### Design decision

**DD-096**: Anchor Dictionary Tool — `flowise.get_anchor_dictionary(node_type)` is the
51st MCP tool in the native surface. It returns canonical anchor names, types, and
advisory compatibility lists from the `AnchorDictionaryStore` (M10.2a). Anchor
dictionaries are prefetched in-process for all node types involved in Connect ops
(AddNode types + UPDATE-mode existing nodes being re-wired), so the LLM rarely
needs to make explicit tool calls — it calls on-demand only for node types not
covered by prefetch or after a compilation failure. Connect ops must use canonical `name` fields, not
type names. The tool is sync-fast (O(1) cache lookup) with an async repair fallback
for unknown node types.

---

## M10.3 — LangGraph graph topology re-wiring (native MCP tools → executor) ✅

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

**DD-097**: LangGraph graph nodes use the MCP tool executor for all Flowise API
operations. This aligns the agent's internal architecture with the MCP-native
design principle: all external I/O flows through the tool registry and can be
observed, mocked, rate-limited, or replaced at a single point. The compiler
remains a direct Python call — it does not cross an I/O boundary.

---

## M10.3a — Patch IR Anchor Contract Update ✅

### Goal

Update the Patch IR `Connect` dataclass so `source_anchor` and `target_anchor` use
canonical anchor **names** from the anchor dictionary (not type names). Simplify the
5-pass fuzzy resolver in `_resolve_anchor_id()` to a 1-pass exact-match with a
deprecated backwards-compatible fallback.

### Why now

With the anchor dictionary tool (M10.2b) available, the LLM no longer needs to guess
anchor names. The compiler can enforce exact-match semantics, reducing `_resolve_anchor_id()`
from 75 lines (5 fuzzy passes) to ~30 lines (1 exact pass + deprecated fallback wrapper).
The fallback preserves backwards compatibility for legacy sessions that were created
before the anchor dictionary existed.

### Connect dataclass contract change

**Before** (current — `patch_ir.py`):
```python
@dataclass
class Connect:
    """Connect two nodes by their anchor names.
    source_anchor:   Name of the output anchor (e.g. "chatOpenAI").
    target_anchor:   Name of the input anchor type (e.g. "BaseChatModel", "BaseMemory").
                     This is the baseClass type expected at the target input slot.
    """
```

**After** (M10.3a):
```python
@dataclass
class Connect:
    """Connect two nodes by their canonical anchor names.
    source_anchor: Canonical name from output anchor dictionary (e.g. "chatOpenAI").
    target_anchor: Canonical name from input anchor dictionary (e.g. "memory", "model").

    The LLM MUST call get_anchor_dictionary(node_type) to obtain the exact
    anchor name before emitting Connect ops. Type names (e.g. "BaseChatModel")
    are DEPRECATED and will trigger a fallback resolution with a warning.
    """
```

### Compiler simplification

**`_resolve_anchor_id()` restructured** (compiler.py:253–328):

```python
def _resolve_anchor_id(schema, node_id, anchor_name, direction):
    """Resolve the full anchor ID for a given anchor name.

    Resolution order:
      1. Exact name match (canonical path — covers all anchor dictionary usage)
      2. Deprecated fuzzy fallback (5-pass legacy resolution with warning)
    """
    anchors = schema.get("outputAnchors" if direction == "output" else "inputAnchors") or []

    # Pass 1: exact name match (canonical — should always succeed with dictionary)
    for anchor in anchors:
        if anchor.get("name", "") == anchor_name:
            return anchor.get("id", "").replace("{nodeId}", node_id)

    # Deprecated fallback: fuzzy matching for legacy sessions
    resolved = _resolve_anchor_id_fuzzy_deprecated(schema, node_id, anchor_name, direction)
    if resolved:
        logger.warning(
            "Fuzzy anchor resolution used for '%s' on '%s' — "
            "this is DEPRECATED. Use get_anchor_dictionary() for exact names.",
            anchor_name, node_id,
        )
    return resolved
```

The existing 5-pass logic moves into `_resolve_anchor_id_fuzzy_deprecated()` — identical
logic, but wrapped as a deprecated fallback that emits compiler warnings.

### Anchor resolution metrics

Tracked in `debug["flowise"]["anchor_resolution"]`:

```python
{
    "total_connections": 5,
    "exact_name_matches": 4,
    "fuzzy_fallbacks": 1,
    "exact_match_rate": 0.80,
    "fuzzy_details": [
        {
            "node": "toolAgent_0",
            "anchor": "BaseMemory",
            "resolved_to": "memory",
            "pass": 3
        }
    ]
}
```

Target: `exact_match_rate` = 1.0 for all new sessions using the anchor dictionary prompt.

### Validation enhancement

`validate_patch_ops()` in `patch_ir.py` gains optional anchor validation:

```python
def validate_patch_ops(ops, anchor_store=None, node_type_map=None):
    # ... existing validation ...
    # NEW: if anchor_store provided, verify Connect anchor names exist.
    # node_type_map: dict[str, str] maps node_id → node_type,
    # built from base graph nodes (UPDATE) + AddNode ops (all modes).
    for op in ops:
        if isinstance(op, Connect) and anchor_store and node_type_map:
            src_node_type = node_type_map.get(op.source_node_id)
            tgt_node_type = node_type_map.get(op.target_node_id)
            if not src_node_type or not tgt_node_type:
                warnings.append(f"Unknown node_id — cannot validate anchors for Connect({op.source_node_id} → {op.target_node_id})")
                continue
            src_dict = anchor_store.get(src_node_type)
            if src_dict:
                output_names = [a["name"] for a in src_dict.get("output_anchors", [])]
                if op.source_anchor not in output_names:
                    warnings.append(
                        f"Unknown source_anchor '{op.source_anchor}' on {op.source_node_id}; "
                        f"valid options: {output_names}"
                    )
            tgt_dict = anchor_store.get(tgt_node_type)
            if tgt_dict:
                input_names = [a["name"] for a in tgt_dict.get("input_anchors", [])]
                if op.target_anchor not in input_names:
                    warnings.append(
                        f"Unknown target_anchor '{op.target_anchor}' on {op.target_node_id}; "
                        f"valid options: {input_names}"
                    )
```

This catches invalid anchor **names** before compilation, providing actionable error
messages that include the list of valid options. Note: this validation checks whether
the anchor name exists on the node, not whether `compatible_types` match — type
compatibility is advisory (see M10.2a) and validated definitively by
`_validate_flow_data()` and the test execution phase.

**`node_id → node_type` mapping**: The code above references `src_node_type` and
`tgt_node_type`, which `validate_patch_ops` must derive from node IDs. The caller
passes a `node_type_map: dict[str, str]` (node_id → node_type) built from two sources:
1. **Base graph nodes** — for UPDATE mode, the loaded flow's existing `nodes[]` array
   provides `{node.data.id: node.data.name}` for every node already in the chatflow.
2. **`AddNode` ops in the current patch** — each `AddNode` op contributes
   `{op.node_id: op.node_type}`.

The union of these two sources covers every node ID that can appear in a `Connect` op.
If a `Connect` references a node ID absent from both sources, `validate_patch_ops`
emits a warning (`"Unknown node_id '{id}' — cannot resolve node_type for anchor
validation"`) and skips anchor validation for that edge.

### Deliverables

#### Modified files

| File | Change |
|------|--------|
| `flowise_dev_agent/agent/patch_ir.py` | Update `Connect` docstring semantics; add anchor validation to `validate_patch_ops()` |
| `flowise_dev_agent/agent/compiler.py` | Restructure `_resolve_anchor_id()` to exact-match + `_resolve_anchor_id_fuzzy_deprecated()`; add metrics tracking |
| `flowise_dev_agent/agent/graph.py` | Pass `anchor_store` to `compile_patch_ops()`; log `anchor_resolution` metrics to `debug["flowise"]` |

#### New tests

**`tests/test_m103a_anchor_contract.py`**
- Connect with canonical name `"memory"` resolves in Pass 1 (exact match).
- Connect with old-style type name `"BaseChatMemory"` still resolves via deprecated fallback.
- `anchor_resolution` metrics correctly count exact vs fuzzy matches.
- `validate_patch_ops()` with `anchor_store` flags unknown anchor names and includes
  valid options in the warning message.
- `exact_match_rate` = 1.0 when all Connect ops use dictionary names.
- All existing compiler integration tests continue to pass unchanged.

### Acceptance criteria

- Existing tests pass unchanged (backwards compatible via deprecated fallback).
- New sessions using the anchor dictionary prompt target 100% exact-match rate;
  any fuzzy fallback is a warning condition surfaced in `debug["flowise"]` and
  tracked in LangSmith metadata.
- Compiler warnings surface in `debug["flowise"]` for any fuzzy fallback usage.
- `_resolve_anchor_id()` primary path reduced to ~30 lines (1 exact pass + fallback call).
- `validate_patch_ops()` provides actionable error messages with valid anchor options.

### Design decision

**DD-098**: Patch IR Anchor Contract Update — the `Connect` dataclass contract changes
from "type name" to "canonical anchor name" semantics. The compiler's `_resolve_anchor_id()`
is restructured as exact-match-first with a deprecated fuzzy fallback. Resolution metrics
(`exact_match_rate`, `fuzzy_fallbacks`) are tracked in `debug["flowise"]["anchor_resolution"]`
and surfaced in LangSmith metadata. `validate_patch_ops()` gains optional pre-compilation
anchor validation with actionable error messages. The deprecated fallback preserves
backwards compatibility for sessions created before the anchor dictionary was available.

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
- FastMCP server lists all 51 tools when `mcp.list_tools()` is called in-process.
- Tool names match `flowise.*` registry namespace.
- Server starts and stops cleanly (no leaked subprocesses).

### Acceptance criteria

- `python -m flowise_dev_agent.mcp` starts without error.
- All 51 tools are discoverable via MCP tool listing (50 original + `get_anchor_dictionary`).
- Cursor IDE can connect (manual verification, not automated).

### Design decision

**DD-099**: External MCP server as a thin wrapper. The FastMCP server in
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
- DD-100: Repository decoupling strategy.
- DD-101: Future Flowise native MCP integration path (transport swap only).

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

## Cross-cutting: LangSmith Observability Alignment

All new sub-milestones (M10.2a, M10.2b, M10.3a) must integrate with the existing
LangSmith observability layer (`flowise_dev_agent/util/langsmith/`):

### Tracing

- `get_anchor_dictionary` tool calls appear in LangSmith traces via `@dev_tracer`
  decorator (same pattern as existing tool functions).
- `AnchorDictionaryStore.get_or_repair()` repair path traced as a child span
  when tracing is enabled.

### Metadata extraction

`extract_session_metadata()` (metadata.py) gains new telemetry keys:

| Key | Source | Type |
|-----|--------|------|
| `telemetry.anchor_exact_match_rate` | `debug["flowise"]["anchor_resolution"]["exact_match_rate"]` | float (0.0–1.0) |
| `telemetry.anchor_fuzzy_fallbacks` | `debug["flowise"]["anchor_resolution"]["fuzzy_fallbacks"]` | int |
| `telemetry.anchor_dictionary_calls` | Count of `get_anchor_dictionary` tool invocations | int |

These keys are filterable in the LangSmith dashboard for monitoring the transition
from fuzzy to exact-match resolution.

### Redaction

Anchor data contains no secrets. Standard `hide_metadata()` is applied uniformly
but requires no anchor-specific redaction patterns.

### Evaluator update

`compile_success` evaluator (evaluators.py) gains an optional quality signal:
- Bonus: if `anchor_exact_match_rate >= 1.0`, the evaluator notes "perfect anchor resolution"
  in the evaluation comment (informational, does not affect the binary score).

### Automation rules

Existing LangSmith automation rules (DD-088) apply unchanged:
- Failed sessions (including anchor resolution failures) → annotation queue.
- Successful sessions → golden dataset sampling.
- New rule suggestion (manual setup): flag sessions where `anchor_fuzzy_fallbacks > 0`
  for annotation review during the M10.3a transition period.

---

## Cross-cutting: UX (SSE Streaming + HITL Checkpoints)

### SSE streaming

- **`get_anchor_dictionary` tool calls** emit `tool_call`/`tool_result` SSE events
  automatically — the existing `_sse_from_event()` handler in `api.py` already
  transforms `execute_tool()` calls into SSE data lines. No new SSE event types needed.
- **No new graph nodes** are added by M10.2a–M10.3a, so `_NODE_PROGRESS` and
  `_NODE_PHASES` mappings require no changes. Anchor dictionary lookups happen
  inside the existing `compile_patch_ir` node.
- **Progress visibility**: Anchor dictionary lookups appear in the streaming UI as
  tool calls during the patch phase (e.g. `{"type": "tool_call", "name": "get_anchor_dictionary"}`).

### HITL checkpoints

All 4 existing HITL interrupt points are **unchanged**:

1. **hitl_plan_v2** — plan approval (including structural retry guard from DD-092)
2. **hitl_review_v2** — result review
3. **hitl_select_target** — UPDATE mode target selection
4. **credential clarification** — missing credential prompt

No new interrupt points are introduced. The anchor dictionary eliminates one class
of structural errors that previously triggered re-approval loops (session ebb04388).

### Node lifecycle events

`wrap_node()` in `hooks.py` continues to emit `node_start`/`node_end`/`node_error`
events for all 18 graph nodes. The `compile_patch_ir` node's `_node_summary()` output
can optionally include anchor resolution stats (e.g. "5 connections, 100% exact match").

---

## Sequencing

```
M10.1  Internalize FlowiseClient              ✅
  │
  ├──→ M10.2   Native MCP tool surface        ✅
  │      │
  │      └──→ M10.2a  Schema Normalization    ✅
  │             │
  │             └──→ M10.2b  Anchor Dict Tool  ✅
  │                    │
  │                    └──→ M10.3   Graph re-wiring  ✅
  │                           │
  │                           └──→ M10.3a  Patch IR Update  ✅
  │                                  │
  │                                  └──→ M10.4  External MCP server  ← NEXT
  │                                         │
  │                                         └──→ M10.5  Repo decoupling + future path
  │
  └──→ (Roadmap 9 complete ✅)
```

### Dependency on M9.6

M10.3 (graph re-wiring) requires M9.6 (topology structure) to be complete first,
because M10.3 re-wires the new node functions built in M9.6. M10.1, M10.2, M10.2a,
and M10.2b can proceed independently of M9.6 and in parallel with remaining Roadmap 9
milestones.

### Dependency chain for anchor dictionary

```
M10.2a depends on M10.2  (tool surface defines where anchor tool lives)
M10.2b depends on M10.2a (anchor tool needs the normalized data)
M10.3a depends on M10.3  (compiler changes need graph re-wiring done first)
M10.3a depends on M10.2b (compiler exact-match requires the anchor dictionary tool)
```

### Recommended order across both roadmaps

```
Roadmap 9 (complete):   9.1 → 9.2 → 9.6 → 9.7 → 9.8 → 9.9  ✅
Roadmap 10:             10.1 ✅ → 10.2 ✅ → 10.2a ✅ → 10.2b ✅
                        10.3 ✅ → 10.3a ✅
                        10.4 → 10.5                    (remaining)
```

---

## Key files summary

| File | Milestone | Status |
|------|-----------|--------|
| `flowise_dev_agent/client/__init__.py` | M10.1 | ✅ Shipped |
| `flowise_dev_agent/client/flowise_client.py` | M10.1 | ✅ Shipped (ported from cursorwise) |
| `flowise_dev_agent/client/config.py` | M10.1 | ✅ Shipped (ported from cursorwise) |
| `flowise_dev_agent/mcp/__init__.py` | M10.2 | ✅ Shipped |
| `flowise_dev_agent/mcp/tools.py` | M10.2, M10.2b | ✅ Shipped (50+1 tool functions) |
| `flowise_dev_agent/mcp/registry.py` | M10.2, M10.2b | ✅ Shipped |
| `flowise_dev_agent/knowledge/anchor_store.py` | M10.2a | ✅ Shipped (AnchorDictionaryStore) |
| `flowise_dev_agent/knowledge/provider.py` | M10.2a | ✅ Shipped (anchor_dictionary property) |
| `flowise_dev_agent/agent/graph.py` | M10.2b, M10.3, M10.3a | ✅ Shipped (prompt update, node re-wiring, anchor metrics) |
| `flowise_dev_agent/agent/tools.py` | M10.2b, M10.3 | ✅ Shipped (anchor tool executor, remove direct client) |
| `flowise_dev_agent/agent/compiler.py` | M10.3a | ✅ Shipped (exact-match + deprecated fallback) |
| `flowise_dev_agent/agent/patch_ir.py` | M10.3a | ✅ Shipped (Connect contract, validate_patch_ops) |
| `flowise_dev_agent/skills/flowise_builder.md` | M10.2b | ✅ Shipped (anchor name docs) |
| `flowise_dev_agent/util/langsmith/metadata.py` | M10.3a | ✅ Shipped (anchor resolution metrics) |
| `flowise_dev_agent/mcp/server.py` | M10.4 | Pending |
| `flowise_dev_agent/mcp/__main__.py` | M10.4 | Pending |
| `pyproject.toml` | M10.1, M10.5 | ✅ M10.1 shipped; M10.5 pending |
| `tests/test_m101_flowise_client.py` | M10.1 | ✅ Shipped |
| `tests/test_m102_flowise_mcp_tools.py` | M10.2 | ✅ Shipped |
| `tests/test_m102a_anchor_store.py` | M10.2a | ✅ Shipped |
| `tests/test_m102b_anchor_tool.py` | M10.2b | ✅ Shipped |
| `tests/test_m103_graph_mcp_wiring.py` | M10.3 | ✅ Shipped |
| `tests/test_m103a_anchor_contract.py` | M10.3a | ✅ Shipped |
| `tests/test_m104_mcp_server.py` | M10.4 | Pending |

---

## Design decisions summary

| DD | Milestone | Title |
|----|-----------|-------|
| DD-093 | M10.1 | FlowiseClient internalization |
| DD-094 | M10.2 | Native Flowise MCP tool surface (50 tools) |
| DD-095 | M10.2a | Canonical Schema Normalization Contract |
| DD-096 | M10.2b | Anchor Dictionary Tool |
| DD-097 | M10.3 | LangGraph MCP tool executor wiring |
| DD-098 | M10.3a | Patch IR Anchor Contract Update |
| DD-099 | M10.4 | External MCP server (thin wrapper) |
| DD-100 | M10.5 | Repository decoupling strategy |
| DD-101 | M10.5 | Future Flowise native MCP path |

---

## Definition of Done for ROADMAP10

ROADMAP10 is complete when:

- `flowise_dev_agent` has no `cursorwise` import anywhere in source or tests.
- `cursorwise` is not listed as a dependency in `pyproject.toml`.
- All 51 Flowise operations are callable as `execute_tool("flowise.xxx", ...)`.
- The M9.6 graph topology nodes reach Flowise exclusively through the tool executor.
- `flowise.get_anchor_dictionary` returns correct anchor data for all 303+ node types.
- Anchor dictionaries are prefetched in-process for all node types involved in
  Connect ops (AddNode types + UPDATE-mode existing nodes); the LLM prompt requires
  canonical anchor names in Connect ops (prefetch or on-demand tool call).
- New sessions target 100% exact-match anchor resolution; any fuzzy fallback is a
  warning condition monitored via telemetry (`anchor_resolution` metrics in LangSmith).
- Legacy sessions (without anchor dictionary) still work via deprecated fuzzy fallback.
- Anchor resolution metrics (`exact_match_rate`, `fuzzy_fallbacks`) visible in LangSmith metadata.
- The compiler's `_resolve_anchor_id()` primary path is exact-match only.
- `validate_patch_ops()` provides actionable error messages with valid anchor options.
- `python -m flowise_dev_agent.mcp` starts and lists 51 tools via MCP.
- Cursor IDE can be configured to use `flowise_dev_agent.mcp` as a drop-in
  replacement for `cursorwise`.
- `pytest tests/ -q` passes in full.
- DESIGN_DECISIONS.md records DD-093 through DD-101.
- README setup instructions require no cursorwise installation.
