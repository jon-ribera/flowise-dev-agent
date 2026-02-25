# Design Decisions — Flowise Development Agent

This document records the key architectural and implementation decisions made
during the design and development of the Flowise Dev Agent.

Each decision explains what was decided, why, and what alternatives were rejected.

---

## DD-001 — LangGraph for Orchestration

**Decision**: Use LangGraph (not plain Python, FastAPI background tasks, or LangChain LCEL)
as the orchestration framework for the agent loop.

**Reason**: LangGraph's StateGraph provides:
- Native human-in-the-loop (HITL) interrupt/resume semantics
- Built-in checkpointing for session persistence across HTTP requests
- Explicit node/edge topology that mirrors the Discover → Plan → Patch → Test → Converge mental model
- Conditional routing without ad-hoc if/else branching

**Rejected alternatives**:
- Plain async Python: manual state management, no built-in HITL or persistence
- LangChain LCEL: streaming-first design conflicts with HITL checkpoint patterns
- Temporal/Prefect: heavyweight workflow engines with high operational overhead

---

## DD-002 — FastAPI as the HTTP Layer

**Decision**: Wrap the LangGraph graph in a FastAPI HTTP service, not a CLI or
direct Python library.

**Reason**:
- HTTP API decouples the agent from any specific client (CLI, web UI, CI pipeline)
- Enables async HITL: client can disconnect and reconnect between interrupt points
- OpenAPI docs generated automatically for the agent's interrupt/resume protocol
- Compatible with Docker and cloud deployment without client-side dependencies

**Rejected alternatives**:
- CLI-only: no way to surface HITL interrupts to a remote UI or CI pipeline
- Python library: callers must manage their own async event loops and persistence

---

## DD-003 — Provider-Agnostic ReasoningEngine ABC

**Decision**: Define a `ReasoningEngine` abstract base class with a single `complete()`
method. Ship `ClaudeEngine` and `OpenAIEngine` as the two implementations.

**Reason**: The choice of LLM provider should be swappable via environment variable
without touching the graph or tool code. This also makes the agent testable with
a mock engine.

**Interface**:
```python
class ReasoningEngine(ABC):
    async def complete(messages, system, tools, temperature) -> EngineResponse: ...
    def model_id(self) -> str: ...
```

---

## DD-004 — MemorySaver Checkpointer (In-Memory, Dev Default)

**Decision**: Default to LangGraph's `MemorySaver` for session checkpointing.
Production deployments should swap to `SqliteSaver` or `PostgresSaver`.

**Reason**: MemorySaver requires zero infrastructure for development and testing.
The `build_graph(checkpointer=...)` parameter makes it easy to inject a
persistent checkpointer in production without code changes.

**Production path**: `SqliteSaver("sessions.db")` is sufficient for single-instance
deployments. Multi-instance deployments need `PostgresSaver`.

---

## DD-005 — REASONING_ENGINE Environment Variable

**Decision**: Select the LLM provider via `REASONING_ENGINE=claude|openai`.
The model name can be overridden with `REASONING_MODEL`.

**Defaults**: `claude-sonnet-4-6` for Claude, `gpt-4o` for OpenAI.

**Reason**: Operator-level configuration without code changes. Matches the
twelve-factor app pattern.

---

## DD-006 — Temperature 0.2 Default

**Decision**: Default sampling temperature is 0.2, configurable via `REASONING_TEMPERATURE`.

**Reason**: Lower temperature produces more deterministic, rule-following outputs —
critical for Patch (must follow strict flowData rules) and Converge (must use exact
structured output format). Discovery and Plan can tolerate slightly higher values
but the global default keeps all phases predictable.

---

## DD-007 — AgentState as a TypedDict with Reducer-Annotated Messages

**Decision**: Represent all session state in a single `AgentState` TypedDict.
The `messages` field uses LangGraph's `Annotated[list[Message], _append_messages]`
reducer. All other fields use overwrite semantics.

**Reason**:
- TypedDict gives static type checking across all nodes
- Append semantics on `messages` prevents nodes from accidentally losing history
- Overwrite semantics on scalar fields (plan, test_results, etc.) means each node
  simply returns the new value without needing to know the previous value

---

## DD-008 — DomainTools Plugin Architecture

**Decision**: Introduce a `DomainTools` dataclass as the plugin interface for adding
new tool domains (Flowise, Workday, etc.) to the agent.

**Structure**:
```python
@dataclass
class DomainTools:
    name: str
    discover: list[ToolDef]
    patch: list[ToolDef]
    test: list[ToolDef]
    executor: dict[str, Callable]
    discover_context: str
    patch_context: str
    test_context: str
```

**Reason**: Adding a Workday domain (v2) requires only implementing a new
`DomainTools` subclass and passing it to `build_graph()`. No changes to the
graph nodes, routing, or system prompts are required.

---

## DD-009 — Compact Context Strategy (No Raw Tool Call History in State)

**Decision**: The `discover` node does NOT persist raw tool call messages to
`state["messages"]`. Only the distilled `discovery_summary` (text) is stored.
Downstream nodes build compact context from structured state fields.

**Reason**: Raw `list_nodes` and `list_marketplace_templates` responses are
100k–500k tokens. Accumulating these in state would blow the LLM context window
within 1–2 iterations, making every downstream call fail.

**Pattern**: Each node builds its own context:
```python
ctx = [
    Message(role="user", content=f"Requirement:\n{state['requirement']}\n\nDiscovery:\n{state['discovery_summary']}"),
    Message(role="assistant", content=state.get("plan") or ""),
]
```

---

## DD-010 — Two HITL Interrupt Points

**Decision**: Place human-in-the-loop interrupt nodes at exactly two points:
1. `human_plan_approval`: after plan is written, before any writes
2. `human_result_review`: after converge says DONE, before session ends

**Reason**: Two checkpoints give the developer maximum control at the two highest-risk
moments (approving the plan before writes, and accepting the result before ending)
without slowing down the automation loop with unnecessary friction.

**Not a checkpoint**: credential_check IS an interrupt (it blocks on missing credentials)
but is handled by `check_credentials` node with `interrupt()` directly.

---

## DD-011 — POST /sessions + POST /sessions/{id}/resume API Shape

**Decision**: The HTTP API has three endpoints:
- `POST /sessions` — start a new session, runs until first interrupt
- `POST /sessions/{id}/resume` — resume with developer response
- `GET /sessions/{id}` — inspect current state without advancing

**Reason**: This maps directly to LangGraph's `ainvoke()` / `Command(resume=...)` pattern.
The `thread_id` in every response is the key the client must store to resume later.

---

## DD-012 — SessionResponse Shape

**Decision**: All session endpoints return `SessionResponse` with:
- `status`: `"pending_interrupt"` | `"completed"` | `"error"`
- `interrupt`: present when status is `pending_interrupt`, typed as `InterruptPayload`
- `thread_id`: always present for resuming

**Reason**: A single response shape for all endpoints simplifies client logic.
The `interrupt.type` field (`"plan_approval"`, `"result_review"`, `"credential_check"`)
tells the client what UI to show.

---

## DD-013 — _get_node_processed: Pre-Split inputAnchors / inputParams

**Decision**: Wrap `client.get_node()` in `_get_node_processed()` which pre-splits
the flat `inputs` array into `inputAnchors` (class-name types) and `inputParams`
(primitive types), and synthesizes `outputAnchors` with `{nodeId}` placeholders.

**Reason**: Flowise's `buildChatflow` crashes with `TypeError: Cannot read properties
of undefined (reading 'find')` when node data is missing `inputAnchors`. Without this
pre-processing the agent frequently produces invalid flowData causing HTTP 500 on
every subsequent prediction call.

**Splitting rule**: `type` starts with uppercase → `inputAnchor`. `type` is lowercase → `inputParam`.

---

## DD-014 — Skill File System

**Decision**: Domain-specific knowledge is stored in editable markdown files
(`flowise_dev_agent/skills/<domain>.md`) rather than hardcoded Python strings.

**Reason**: Skill files can be updated by a developer without touching Python code,
restarting the server, or understanding the LangGraph internals. The file is parsed
into `## Section` blocks; three sections are injected into system prompts per phase.

**Fallback**: If a skill file is missing, `FloviseDomain` falls back to hardcoded
`_FLOWISE_*_CONTEXT` constants so the agent never fails to start.

---

## DD-015 — _list_nodes_slim / _list_marketplace_templates_slim

**Decision**: Trim the `list_nodes` response to `{name, category, label}` only,
and strip `flowData` from `list_marketplace_templates` results before returning them
to the LLM.

**Reason**:
- Full `/nodes` response: ~650KB, ~162k tokens — exceeds context limits
- Full `/marketplaces/templates` response: ~1.7MB, ~430k tokens — catastrophically large
- Slim versions: ~25KB and ~13KB respectively — give the LLM what it needs to choose
  which nodes/templates to inspect further with targeted `get_node()` calls

---

## DD-016 — ReasoningSettings Isolated from MCP Server

**Decision**: `ReasoningSettings` (the pydantic-settings class that reads
`REASONING_ENGINE`, `ANTHROPIC_API_KEY`, etc.) lives in `flowise_dev_agent.reasoning`,
not in the `cursorwise` package.

**Reason**: The `cursorwise` MCP server is a lightweight Flowise API client with no
LLM dependencies. Adding `pydantic-settings` and `anthropic` to its install would
bloat the server for users who only want the MCP tools. Keeping reasoning config in
this package maintains the clean dependency split.

---

## DD-017 — Credential HITL Checkpoint

**Decision**: Add a `check_credentials` node between `discover` and `plan`. If the
discover summary indicates missing credentials, issue a `credential_check` interrupt
before the plan is written.

**Reason**: Discovering missing credentials AFTER writing a chatflow means a failed
prediction test that requires an unrelated fix. Front-loading this check means the
developer can create the credentials in Flowise before any writes happen, making the
first patch cycle more likely to succeed.

**Trigger**: The `discover` node's skill file instructs the LLM to emit a structured
`CREDENTIALS_STATUS: MISSING\nMISSING_TYPES: openAIApi, anthropicApi` block at the
end of its summary. The `check_credentials` node parses this to decide whether to
interrupt.

---

## DD-018 — FlowData Pre-Flight Validator (Poka-Yoke Tool)

**Decision**: Add `validate_flow_data(flow_data_str)` as a tool available in the
Patch phase. Make it MANDATORY before any `create_chatflow` or `update_chatflow` call
(enforced via both the tool list ordering and the skill file Rule 8).

**Reason**: Poka-yoke tool design (from Anthropic's agent design guide) — prevent
mistakes structurally rather than relying on prompt instructions alone. Invalid
flowData causes silent HTTP 500 errors from Flowise that are hard to diagnose.
A pre-flight check that lists every specific error (missing `inputAnchors`, dangling
edge references, etc.) lets the LLM fix problems before they reach the API.

**Checks performed**:
1. Valid JSON with `nodes` and `edges` arrays
2. Every node has `data.inputAnchors`, `data.inputParams`, `data.outputAnchors`, `data.outputs`
3. Every edge's `source`/`target` references an existing node ID
4. Every edge's `sourceHandle`/`targetHandle` references an existing anchor ID

---

## DD-019 — Structured Converge Verdicts (Evaluator-Optimizer Pattern)

**Decision**: Require the converge node to emit a structured verdict:
```
ITERATE
Category: CREDENTIAL | STRUCTURE | LOGIC | INCOMPLETE
Reason: <one line>
Fix: <specific action>
```
Parse this with `_parse_converge_verdict()` and inject it into the next plan context.

**Reason**: Implements the evaluator-optimizer pattern from Anthropic's agent design
guide. Without structured verdicts, the converge node emits freetext ITERATE reasons
that the plan node receives as vague context. With structured verdicts, the plan node
gets a specific, categorized repair instruction — dramatically reducing the number of
iterations required to fix common failure patterns.

**State field**: `converge_verdict: dict | None` — cleared when verdict is DONE,
kept across iterations when ITERATE.

---

## DD-020 — Multi-Output Node Support in _get_node_processed

**Decision**: In `_get_node_processed`, check `schema.get("outputAnchors")` first.
If the raw schema has outputAnchors (multi-output nodes like `ifElseFunction`),
use them with `{nodeId}` normalization. Otherwise synthesize from `baseClasses`.

**Reason**: Some Flowise nodes (conditional branching, switch nodes) have multiple
named output anchors with different types. The previous single-anchor synthesis from
`baseClasses` produced incorrect output IDs for these nodes, causing invalid edge
references in the generated flowData.

---

## DD-021 — pass^k Reliability Testing

**Decision**: Add `test_trials: int` to `AgentState` and `StartSessionRequest`.
When `test_trials > 1`, the test node runs each test case `k` times with different
`sessionId` values and requires ALL trials to pass.

**Reason**: Distinguishes between pass@1 (capability — can the flow produce a correct
answer?) and pass^k (reliability — does it produce correct answers consistently?).
Inspired by Anthropic's evaluation guide: "pass^k is a better measure of whether you
can trust the agent in production."

**Default**: 1 (pass@1, fastest). Set to 2–3 for pre-release validation.

---

## DD-022 — Skill File as Primary Agent Knowledge Base

**Decision**: The `flowise_builder.md` skill file is the single authoritative source
for Flowise-specific agent knowledge. Hardcoded context strings in `tools.py` are
fallbacks only.

**Reason**: Skill files can be iterated on without touching Python code. When the
team discovers a new failure pattern (new error type, new node behavior, new rule),
they update the skill file rather than modifying `tools.py` and redeploying. This
makes the knowledge base maintainable by anyone, not just Python developers.

---

## DD-023 — Repository Separation (cursorwise + flowise-dev-agent)

**Decision**: Extract the LangGraph agent into its own repository (`flowise-dev-agent`)
separate from the `cursorwise` MCP server. The agent imports `cursorwise` as a pip
dependency for `FlowiseClient` and `Settings`.

**Dependency hierarchy**:
```
flowise-dev-agent (this repo)
  └── depends on: cursorwise >= 1.0.0
       └── FlowiseClient (52 async Flowise API methods)
       └── Settings (Flowise connection config)
```

**Reason**:
- `cursorwise` is a lightweight MCP server with no LLM dependencies. Keeping it
  separate allows it to remain installable by anyone using Cursor + MCP without
  pulling in `langgraph`, `fastapi`, `anthropic`, etc.
- `flowise-dev-agent` is a full co-development platform. It can evolve independently,
  have its own versioning, and be deployed separately from the MCP server.
- The split creates a clean product boundary: one tool for Cursor IDE users, one tool
  for developers who want an autonomous agent.

**What stays in `cursorwise`**: `FlowiseClient`, `Settings`, 50 MCP tools, the
`FLOWISE_NODE_REFERENCE.md` and `FLOWISE_BUILDER_ORCHESTRATOR_CHATFLOW_MCP.md` guides.

**What lives here**: LangGraph graph, FastAPI API, ReasoningEngine, skill files,
HITL interrupt nodes, converge evaluator.

---

## DD-024 — SQLite Session Persistence via AsyncSqliteSaver

**Date**: 2026-02-22
**Decision**: Replace the development-only `MemorySaver` checkpointer with
`AsyncSqliteSaver` as the default production checkpointer. The database path
is configured via `SESSIONS_DB_PATH` (default: `sessions.db`).

**Reason**: Sessions must survive server restarts for any production use.
`MemorySaver` loses all session state on process exit, making it impossible
to resume a session after a deployment or crash. `AsyncSqliteSaver` requires
no external infrastructure (no Redis, no Postgres) and is sufficient for
single-instance deployments.

**Implementation**: `api.py` lifespan now opens an `AsyncSqliteSaver` context
manager and injects the checkpointer into `build_graph()`. The `build_graph()`
signature was already designed to accept a `checkpointer=` argument (DD-004).

**Rejected alternatives**:
- `PostgresSaver`: correct for multi-instance/HA deployments but adds infra overhead
  not needed for v1. Can be swapped in by changing `SESSIONS_DB_PATH` to a Postgres
  connection string and updating the import when needed.
- Keeping `MemorySaver` with a warning: not acceptable for production — any restart
  orphans all in-flight sessions with no recovery path.

---

## DD-027 — LangSmith Tracing (Optional, Zero-Code-Change)

**Date**: 2026-02-22
**Decision**: Activate LangSmith distributed tracing by setting `LANGCHAIN_API_KEY`
in the environment. When the key is present, the lifespan sets
`LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_PROJECT` before the graph is created.
No other code changes are needed.

**Reason**: LangGraph auto-instruments all LLM calls, tool calls, and token counts
when `LANGCHAIN_TRACING_V2` is set. This gives full per-session observability
(latency, token cost, node-by-node traces) at zero implementation cost. The feature
is opt-in — omitting the API key leaves the agent unchanged.

**Rejected alternatives**:
- Always-on tracing: forces a LangSmith account on every developer, adds network
  overhead even in local dev.
- Custom span instrumentation: significant effort for the same data LangGraph already
  emits automatically.

---

## DD-025 — Streaming SSE Endpoints

**Date**: 2026-02-22
**Decision**: Add `POST /sessions/stream` and `POST /sessions/{thread_id}/stream`
as streaming variants of the existing create and resume endpoints. Both return
`text/event-stream` responses using LangGraph's `astream_events(version="v2")`.

**Event types**:
- `token` — LLM output token (from `on_chat_model_stream`)
- `tool_call` — tool being invoked (from `on_tool_start`)
- `tool_result` — tool result preview (from `on_tool_end`)
- `interrupt` — HITL pause reached (emitted as the final event)
- `done` — session complete (emitted as the final event)
- `error` — unhandled exception

**Reason**: The discover and patch phases take 30–60 seconds. Without streaming,
clients wait in silence. Streaming tokens and tool call events give live feedback
that a long-running phase is progressing normally, dramatically improving DX.

**Design choices**:
- `aget_state()` (async) is used at the end of the stream instead of `get_state()`
  since the stream runs in an async context and the SQLite checkpointer is async.
- Anthropic content blocks (list of dicts) are flattened to text in `_sse_from_event`.
- The blocking `/sessions` and `/sessions/{id}/resume` endpoints are preserved
  unchanged — streaming is opt-in for clients that support SSE.

**Rejected alternatives**:
- WebSockets: more complex client setup, stateful connection required. SSE is
  simpler for one-way server-to-client streaming and works with `curl -N`.
- Long-polling: requires the client to repeatedly re-connect; adds server overhead.

---

## DD-026 — Chatflow Snapshot / Rollback

**Date**: 2026-02-22
**Decision**: Before every `update_chatflow`, the agent calls `snapshot_chatflow`
to save the current `flowData` to an in-memory store keyed by `session_id`.
A new `POST /sessions/{thread_id}/rollback` endpoint restores the last snapshot
by calling `update_chatflow` with the saved `flowData`.

**Reason**: Patches are irreversible in Flowise — once `update_chatflow` is called
there is no undo. A snapshot taken before every write gives the developer a
one-click rollback path if a patch breaks the flow or produces wrong behavior.

**Implementation**: `_snapshots: dict[str, list[dict]]` in `tools.py` holds snapshots
in-process. The session `thread_id` is used as `session_id` to scope snapshots.

**Limitations / future work**:
- In-memory store: snapshots are lost on server restart. A future version should
  persist snapshots to the SQLite sessions database (same file as DD-024).
- Only the last snapshot per session is used by rollback (simple stack pop).

**Rejected alternatives**:
- No-op (relying on developers to manually re-read and re-apply): too error-prone
  when patches break flows mid-iteration.
- Flowise version history API: Flowise doesn't expose one.

---

## DD-028 — API Key Authentication (Optional Bearer Token)

**Date**: 2026-02-22
**Decision**: Add an optional `_verify_api_key` FastAPI dependency injected into
every route via `dependencies=[Depends(_verify_api_key)]`. When `AGENT_API_KEY`
is set, all requests must include `Authorization: Bearer <key>`. When the env var
is absent, the API is open (dev mode).

**Reason**: The agent API can trigger writes to Flowise (create/update chatflows).
Without auth, any process with network access to the server can trigger these writes.
A simple Bearer token is the minimum viable protection for non-localhost deployments.

**Rejected alternatives**:
- Always-required auth: breaks zero-config local development. The opt-in pattern
  matches twelve-factor app conventions and requires no change to dev workflows.
- OAuth/JWT: significant complexity for an internal developer tool. Simple Bearer
  token is appropriate for single-tenant use.

---

## DD-029 — Token Budget Tracking

**Date**: 2026-02-22
**Decision**: Track cumulative LLM token usage (prompt + completion) across the
full session lifecycle. Each node that calls the LLM returns `total_input_tokens`
and `total_output_tokens` deltas. A `_sum_int` reducer on `AgentState` accumulates
these across all nodes. Totals are surfaced in every `SessionResponse`.

**Reason**: Long Discover + multi-iteration loops can consume large token budgets.
Operators need visibility into per-session cost. Surfacing totals in the API response
enables cost dashboards, budget alerts, and capacity planning without any external
instrumentation.

**Implementation**:
- `EngineResponse.input_tokens` / `.output_tokens` populated by both `ClaudeEngine`
  and `OpenAIEngine` from their respective usage objects.
- `AgentState.total_input_tokens` / `.total_output_tokens` with `Annotated[int, _sum_int]`
  reducer — each node contributes its delta; LangGraph accumulates automatically.
- `_react()` returns a 4-tuple `(text, messages, in_tok, out_tok)`; plan and converge
  nodes read from `response.input_tokens` / `.output_tokens` directly.
- `SessionResponse` exposes both totals at the API level.

**Rejected alternatives**:
- External observability only (LangSmith): requires a separate service and doesn't
  surface token counts directly in the API response.
- Counting tokens client-side: inaccurate (depends on tokenizer) and not available
  before the API call returns.

---

## DD-030 — Session Browser API

**Date**: 2026-02-22
**Decision**: Add `GET /sessions` (list all sessions) and `DELETE /sessions/{thread_id}`
(permanently remove a session) to the FastAPI service.

**Reason**: Operators need to enumerate active/completed sessions and clean up stale
ones without direct database access. The listing endpoint also enables building a
simple management UI on top of the API.

**Implementation**:
- `GET /sessions`: queries `SELECT DISTINCT thread_id FROM checkpoints` via the
  `AsyncSqliteSaver.conn` (aiosqlite connection), then calls `graph.aget_state()` per
  thread to build a lightweight `SessionSummary` (status, iteration, chatflow_id,
  token totals). Status is inferred: `pending_interrupt` if any task has interrupts,
  `completed` if `state.done` or no `snapshot.next`, otherwise `in_progress`.
- `DELETE /sessions/{thread_id}`: verifies thread existence, then calls
  `checkpointer.adelete_thread(thread_id)` which removes rows from both the
  `checkpoints` and `writes` tables.

**Rejected alternatives**:
- `alist(None)` instead of raw SQL: iterates every checkpoint row (not just distinct
  thread_ids), requiring deduplication in Python — less efficient.
- Separate admin service: unnecessary complexity for an internal developer tool.

---

## DD-031 — Pattern Library (Self-Improvement)

**Date**: 2026-02-22
**Decision**: After every DONE verdict the agent automatically saves the requirement text
and chatflow flowData to a `patterns` SQLite table. A new `search_patterns(keywords)`
Discover tool lets the LLM query the library before doing full API discovery. A matching
pattern can be reused directly, skipping most of the list_nodes/get_node/validate cycle.

**Implementation**:
- `flowise_dev_agent/agent/pattern_store.py` — `PatternStore` async class with `setup()`,
  `save_pattern()`, `search_patterns()`, `increment_success()`, and `list_patterns()`.
  Uses `aiosqlite` (transitive dep from langgraph-checkpoint-sqlite).
- `PatternDomain` in `tools.py` — wraps `PatternStore` as a `DomainTools` plugin;
  exposes `search_patterns` and `use_pattern` in the Discover phase.
- `_make_converge_node()` accepts optional `client` and `pattern_store`; when the
  verdict is DONE it fetches the final `flowData` via `client.get_chatflow()` and
  calls `pattern_store.save_pattern()`. Failure is logged but non-fatal.
- `build_graph()` accepts `pattern_store=` and auto-appends `PatternDomain` to
  `domains` when provided. The same `pattern_store` object is threaded to converge.
- `GET /patterns` endpoint exposes the library for inspection and search.
- `PATTERN_DB_PATH` env var (default: same SQLite file as sessions).
- Rule 14 added to `flowise_builder.md`: always call `search_patterns` first in Discover.

**Keyword search**: splits query on whitespace, runs `LIKE %word%` per word with a
CASE WHEN match-score counter. Results ranked by match_score then success_count.

**Rejected alternatives**:
- Full-text search (FTS5): adds complexity without meaningful benefit for short
  requirement descriptions. LIKE search is sufficient at this scale.
- Store patterns as a tool-result in the discover context: too verbose; the LLM
  would see full flowData for every pattern in every Discover call.

---

## DD-032 — Multiple Flowise Instances

**Date**: 2026-02-22
**Decision**: Support routing different sessions to different Flowise deployments
(dev/staging/prod, or separate customer tenants) via a `FlowiseClientPool`.
The session request carries an optional `flowise_instance_id` which is stored in
`AgentState` and used to resolve the correct client for rollback.

**Implementation**:
- `flowise_dev_agent/instance_pool.py` — `FlowiseClientPool` class. Reads
  `FLOWISE_INSTANCES` env var (JSON array of `{id, endpoint, api_key}` objects).
  Falls back to a single default instance from `FLOWISE_*` env vars when unset.
- `StartSessionRequest.flowise_instance_id` (optional) — passed to `_initial_state()`.
- `AgentState.flowise_instance_id` — persisted in checkpoint so rollback uses the
  correct client even after server restart.
- `_get_client(request, instance_id)` helper in `api.py` — resolves client from pool.
- `GET /instances` endpoint — returns available instance IDs for introspection.
- Rollback endpoint reads `instance_id` from state and resolves the client via pool.

**Limitations**:
- The graph is compiled with the default instance's domain tools. Routing per-session
  to a different instance's graph (with different node schemas) is not yet supported.
- Future work: compile separate graphs per instance, or reload domains dynamically.

**Rejected alternatives**:
- Per-session graph compilation: very high latency; not practical for interactive sessions.
- Single shared client with instance routing: would require passing instance_id through
  every tool call, coupling the tool layer to the routing layer.

---

## DD-033 — Requirement Clarification Node

**Date**: 2026-02-22
**Decision**: Insert a new `clarify` HITL node between `START` and `discover` in the
graph topology. The node calls the LLM with a requirements-analyst prompt, scores
ambiguity 0–10, and issues a HITL interrupt with 2–3 targeted questions when the
score is ≥ 5. If the score is < 5, or if `SKIP_CLARIFICATION=true`, the node passes
through immediately with `clarification: None`.

**New graph topology**:
```
START → clarify → discover → check_credentials → plan → ...
```

**Reason**: The most expensive failure mode in the agent loop is an ITERATE cycle
caused by a misunderstood requirement — the agent builds the wrong thing, tests it,
fails, and has to rebuild. Front-loading 2–3 targeted questions about LLM provider,
memory, RAG, and new-vs-modify decisions eliminates the most common sources of
ambiguity before any expensive API calls are made.

**Implementation**:
- `AgentState.clarification: str | None` — stores the developer's answers; `None`
  when clarification was not needed or was skipped.
- `_CLARIFY_SYSTEM` prompt in `graph.py` — instructs the LLM on the 0–10 scoring
  rubric and question format.
- `_make_clarify_node(engine)` — async node factory; reads `SKIP_CLARIFICATION` env
  var and issues `interrupt({"type": "clarification", ...})` when score ≥ 5.
- `discover` node updated to prepend clarification answers to `user_content` when
  `state["clarification"]` is set.
- `SKIP_CLARIFICATION=false` added to `.env.example`.
- `"clarification": None` added to `_initial_state()` in `api.py`.
- `InterruptPayload.type` description updated to include `"clarification"`.

**Bypass**: Set `SKIP_CLARIFICATION=true` to disable for automated pipelines and tests.

**Rejected alternatives**:
- Always ask questions: adds latency to every session, even for clear requirements.
- Static keyword matching to detect ambiguity: too brittle; LLM scoring generalises better.
- Ask questions in the plan node: too late — by then the discover phase has already
  run without the developer's input.

---

## DD-034 — Session Export / Audit Trail

**Date**: 2026-02-22
**Decision**: Add `GET /sessions/{thread_id}/summary` which returns a human-readable
markdown document summarising the session. The response includes requirement, chatflow
ID, status, iteration count, token totals, clarifications, approved plan, discovery
summary, and test results — all read from existing `AgentState` fields.

**Reason**: Teams need to hand off sessions between developers, produce compliance
artefacts, and debug failures without direct database access. A structured markdown
summary captures the full lifecycle of a session in a shareable format that works
in GitHub comments, Slack, Confluence, and plain terminals.

**Implementation**:
- New endpoint in `api.py`: `GET /sessions/{thread_id}/summary` → `{"thread_id": ..., "summary": "..."}`.
- Uses the synchronous `graph.get_state(config)` (same as `_build_response`); no new
  state fields are read or written.
- Sections are only included when the corresponding state field is non-empty, so
  early-stage sessions produce a short summary and completed sessions produce a full one.
- Clarification section added so auditors can see the questions and answers that
  shaped the requirement.

**Rejected alternatives**:
- Return structured JSON instead of markdown: markdown is immediately readable without
  tooling; structured JSON can be derived later if needed.
- Store the summary in state: pure formatting over existing data; no persistence needed.

---

## DD-035 — Discover Response Caching

**Date**: 2026-02-22
**Decision**: Wrap `list_nodes` and `list_marketplace_templates` in a monotonic-clock
TTL cache keyed by `f"{tool_name}:{id(client)}"`. The default TTL is 5 minutes,
configurable via `DISCOVER_CACHE_TTL_SECS`. Setting the TTL to 0 disables caching.

**Reason**: `list_nodes` returns ~162k tokens of node schema data. `list_marketplace_templates`
(trimmed) returns ~3k tokens but requires a network round-trip every call. Both responses
are stable across sessions — the Flowise node registry doesn't change between requests.
A 5-minute TTL eliminates 20–30% of per-session token cost and reduces Flowise API load
with zero change to agent behaviour.

**Implementation**:
- `_tool_cache: dict[str, tuple[Any, float]]` module-level dict in `tools.py`.
- `_cached(key, ttl, fn)` — returns an async wrapper that checks the cache before
  calling `fn`, stores the result on a miss, and respects `ttl=0` as a disable flag.
- `_make_flowise_executor()` reads `DISCOVER_CACHE_TTL_SECS` via `os.getenv` and
  wraps the two tools at executor construction time.
- Cache key uses `id(client)` to scope per-instance (supports multi-instance pools).
- `DISCOVER_CACHE_TTL_SECS=300` added to `.env.example`.

**Trade-offs**:
- In-process cache: lost on server restart (acceptable — TTL is short).
- `id(client)` reuse: safe because the client is held for the process lifetime.
- Node schemas never change mid-session; 5-minute staleness window is acceptable.

**Rejected alternatives**:
- Redis/external cache: adds infrastructure for a minor optimisation.
- Caching `get_node` results: node schemas are fetched selectively per type and vary
  by name; the per-call cost is low and safe to skip.
- Cache invalidation on deploy: Flowise doesn't emit events; polling is equivalent to TTL.

---

## DD-036 — Rate Limiting

**Date**: 2026-02-22
**Decision**: Add `slowapi` rate limiting to `POST /sessions` and `POST /sessions/stream`.
The per-IP limit defaults to 10 new sessions per minute and is configurable via
`RATE_LIMIT_SESSIONS_PER_MIN`. Exceeding the limit returns HTTP 429.

**Reason**: Each session start triggers a full Discover phase (LLM calls, Flowise API
calls, up to 162k tokens of node data). A single misconfigured or malicious caller
can exhaust the LLM quota and block all other sessions. A per-IP rate limit at the
session-start endpoints is the minimum viable protection with negligible implementation cost.

**Implementation**:
- `slowapi>=0.1` and `limits>=3.0` added to `pyproject.toml` dependencies.
- `Limiter(key_func=get_remote_address)` created at module level in `api.py`.
- `app.state.limiter = limiter` and `app.add_exception_handler(RateLimitExceeded, ...)`
  wired immediately after `app = FastAPI(...)`.
- `@limiter.limit(f"{RATE_LIMIT_SESSIONS_PER_MIN}/minute")` applied to `create_session`
  and `stream_create_session`. Resume endpoints are not rate-limited — resuming a session
  is cheap compared to starting one.
- `RATE_LIMIT_SESSIONS_PER_MIN=10` added to `.env.example`.

**Rejected alternatives**:
- Rate limiting all endpoints: resume, get, and list endpoints are cheap; no need to
  restrict legitimate polling or status checks.
- API-gateway-level limiting (nginx, Caddy): correct for production but adds
  infrastructure; slowapi provides the same protection with zero operational overhead
  for single-instance deployments.
- Token-bucket per API key: more precise but requires tracking state per key; IP-based
  limiting is sufficient for the single-tenant use case.

---

## DD-037 — Webhook Callbacks for HITL Interrupts

**Date**: 2026-02-22
**Decision**: When a developer provides a `webhook_url` at session start, the agent
POSTs the interrupt payload to that URL immediately before calling `interrupt()` at
every HITL pause point (`clarification`, `credential_check`, `plan_approval`,
`result_review`). The POST is fire-and-forget — it is scheduled as an
`asyncio.create_task()` and retried up to 3 times with exponential back-off (1s, 2s, 4s).
Delivery failures are logged but never propagate to the graph.

**New state field**: `AgentState.webhook_url: str | None` — stored in the checkpoint
so the value is available at every node, including after server restarts.

**Reason**: Without webhooks, developers must poll `/sessions/{id}` to detect
interrupts. This wastes resources and adds latency. A webhook turns the HITL flow
into a push notification: CI pipelines, Slack bots, and custom UIs can react
immediately without polling.

**Implementation**:
- `_fire_webhook(url, payload)` coroutine in `graph.py` — `httpx.AsyncClient` POST
  with 10-second timeout; 3-attempt retry loop with `asyncio.sleep(2^attempt)`.
- `asyncio.create_task(_fire_webhook(...))` called before every `interrupt()` when
  `state.get("webhook_url")` is set. The task runs independently; graph execution
  is not blocked.
- All four HITL nodes (`clarify`, `check_credentials`, `human_plan_approval`,
  `human_result_review`) converted to `async def` to support `create_task()` and
  unified with the existing async node pattern.
- `webhook_url: str | None` added to `StartSessionRequest` and `_initial_state()`.
- `httpx>=0.27` added to `pyproject.toml` dependencies.

**Security note**: The URL is caller-supplied and not validated beyond being a
non-empty string. Operators running in untrusted multi-tenant environments should
add URL allowlist validation in `_fire_webhook` before deploying.

**Rejected alternatives**:
- Blocking `await _fire_webhook(...)`: would add up to 7 seconds of latency before
  the interrupt fires when the webhook endpoint is slow.
- WebSocket push: stateful, requires a long-lived connection, not composable with
  the existing HTTP interrupt/resume flow.
- Polling endpoint on the agent side: inverts the notification model; callers can
  still poll `/sessions/{id}` as a fallback.

---

## DD-038 — Error Recovery Playbook

**Date**: 2026-02-22
**Decision**: Add a static `_ERROR_PLAYBOOK: dict[str, str]` lookup table in
`graph.py` that maps each converge failure category (`CREDENTIAL`, `STRUCTURE`,
`LOGIC`, `INCOMPLETE`) to a targeted, pre-validated repair instruction. When the
plan node enters an ITERATE cycle with a known category, the matching playbook
entry is appended to the plan context as an additional `user` message.

**Reason**: The converge node already classifies failures into four categories
(DD-019). Without the playbook, the plan node receives only the structured verdict
(`CONVERGE VERDICT [CREDENTIAL]: ...`) and must reason about the fix from first
principles on every iteration. This wastes tokens and increases iteration count.
The playbook converts each category into a concrete, step-by-step repair procedure
that the plan node can apply directly, dramatically reducing the probability of
repeating the same mistake.

**Implementation**:
- `_ERROR_PLAYBOOK` constant defined above `_make_plan_node` in `graph.py`.
- Inside `_make_plan_node`, after appending the CONVERGE VERDICT message, the
  category is looked up in `_ERROR_PLAYBOOK`. If a hint exists, it is appended
  as a second `Message(role="user", ...)` so the LLM receives both the verdict
  and the targeted fix guidance before generating the revised plan.
- No new state fields — the playbook is stateless and consulted on every ITERATE cycle.

**Playbook entries**:
- `CREDENTIAL` — verifies dual-binding at `data.credential` and `data.inputs.credential`.
- `STRUCTURE` — mandates `validate_flow_data` before every write, enforces minimum
  `{"nodes":[],"edges":[]}` shape, and checks required data keys.
- `LOGIC` — scopes the change to the specific failing node/param from the test output.
- `INCOMPLETE` — verifies `deployed:true` and correct `chatflow_id` via `list_chatflows`.

**Rejected alternatives**:
- Dynamic playbook from a database: the four failure categories are stable and
  well-understood; a static dict is sufficient and zero-latency.
- Injecting hints in the converge system prompt: converge evaluates, plan repairs;
  keeping the playbook in the plan node respects the evaluator-optimizer separation.
- Per-failure-message prompting (not categorised): the existing category classification
  already provides the right granularity; the playbook just adds the action to take.

---

## DD-039 — Chatflow Version Tags (Full Rollback History)

**Date**: 2026-02-22
**Decision**: Extend the in-memory snapshot store (`_snapshots` in `tools.py`) to
record a `version_label` (e.g. `"v1.0"`, `"v2.0"`) with every snapshot. Labels
are auto-generated as `f"v{len(existing)+1}.0"` when not supplied by the caller.
Rollback accepts an optional `version_label` to restore a specific version instead
of always using the latest snapshot. Two new public API surfaces are added:
`GET /sessions/{id}/versions` and an updated `POST /sessions/{id}/rollback?version=<label>`.

**Reason**: The original rollback always restored the most recent snapshot, making
it impossible to recover to a known-good state from two or more iterations ago without
manually capturing version numbers. By tagging snapshots with version labels the
developer can audit the full edit history via the API and roll back to any prior state,
not just the last one.

**Implementation**:
- `_snapshot_chatflow()` in `tools.py`: adds `version_label: str | None = None` param.
  Auto-generates `f"v{len(existing)+1}.0"` when not supplied. Stores `version_label`
  in the snap dict. Returns `{"snapshotted": True, "version_label": label, "snapshot_count": N}`.
- `_rollback_chatflow()` in `tools.py`: adds `version_label: str | None = None`. When
  supplied, filters snaps by label (error if not found, returns available labels in error
  message). When omitted, falls back to `snaps[-1]` (existing behaviour). Adds
  `"rolled_back_to": label` to the Flowise API result.
- Executor lambdas in `_make_flowise_executor()` updated to forward `version_label=None`.
- `snapshot_chatflow` tool definition: `version_label` added as optional parameter.
- `rollback_session_chatflow()` public wrapper updated to accept and forward `version_label`.
- `list_session_snapshots(session_id)` new public function: returns snapshot metadata
  (chatflow_id, name, version_label, timestamp) without the bulky `flow_data` field.
- `GET /sessions/{thread_id}/versions` endpoint in `api.py`: calls `list_session_snapshots`.
- `POST /sessions/{thread_id}/rollback` in `api.py`: accepts optional `version: str | None`
  query parameter; passes it through to `rollback_session_chatflow`.

**Rejected alternatives**:
- Persisting snapshots to SQLite: the in-memory store is already sufficient for the
  session lifetime; adding DB persistence would complicate the schema and the lifespan
  for minimal gain — snapshots are advisory, not authoritative.
- Incrementing version numbers as integers: semantic labels (`v1.0`) are more legible
  in the API response and give room for minor-version semantics in a future extension.

---

## DD-040 — Parallel Test Execution

**Date**: 2026-02-22
**Decision**: Refactor `_make_test_node()` in `graph.py` to dispatch all
`create_prediction` calls concurrently via `asyncio.gather()` instead of delegating
to the `_react()` ReAct loop. The LLM is called exactly once at the end — with
`tools=None` — to evaluate the raw API responses. All (happy × `test_trials`) +
(edge × `test_trials`) tasks are gathered in a single batch for maximum parallelism.

**Reason**: The previous test node ran a full ReAct loop where the LLM would make
sequential `create_prediction` tool calls. This had two problems: (1) latency —
happy and edge predictions ran serially, doubling the wall-clock time when both are
independent; (2) non-determinism — the LLM chose the sessionId format and test inputs,
which occasionally deviated from the expected pattern. By dispatching predictions
directly from Python we guarantee consistent sessionId format (`test-<id>-happy-t<N>`),
remove the extra ReAct round-trips, and cut test-phase latency roughly in half.

**Implementation**:
- `_make_test_node()` now calls `_, executor = merge_tools(domains, "test")` (drops
  `tool_defs` since `_react()` is no longer used).
- Inner `_run_trial(label, question, trial_num)` coroutine calls `execute_tool(
  "create_prediction", {..., "override_config": json.dumps({"sessionId": ...})}, executor)`.
- `asyncio.gather(*happy_tasks, *edge_tasks, return_exceptions=True)` fires all trials.
- Results are formatted into a `raw_results` string, then passed to a single LLM
  `engine.complete(tools=None)` call for evaluation.
- `flowise_builder.md` **Rule 15** added to the Test Context explaining that the LLM's
  role is evaluation-only and that `create_prediction` must not be called.
- `_react()` helper remains in `graph.py` — still used by discover, patch, and future phases.

**Rejected alternatives**:
- Keeping `_react()` and instructing the LLM to run predictions in parallel: LangGraph
  LLMs cannot natively fan out tool calls across coroutines; the instruction would be
  ignored and predictions would still run sequentially.
- Running happy and edge tests as separate graph nodes: would complicate the graph
  topology for a problem that is cleanly solved at the Python level with gather.

---

## DD-046 — DomainCapability ABC (Behavioral Domain Plugin Contract)

**Date**: 2026-02-23
**Decision**: Introduce `DomainCapability` as the primary abstraction boundary for
domain plugins. It wraps a `DomainTools` data descriptor and adds a typed behavioral
lifecycle: `discover()`, `compile_ops()`, `validate()`, `generate_tests()`, `evaluate()`.
Concrete implementations: `FlowiseCapability` (in `graph.py`, co-located with `_react`)
and `WorkdayCapability` (in `agent/domains/workday.py`).

**Reason**: `DomainTools` is a data descriptor (list of ToolDef + executor dict). Adding
Workday with only `DomainTools` would require duplicating the ReAct loop, result routing,
and state update logic inside the graph. `DomainCapability` defines a contract that any
domain must implement; the orchestrator calls `cap.discover(context)` and receives a typed
`DomainDiscoveryResult` without knowing anything about how the domain works internally.

**Key design choices**:
- `DomainCapability` wraps `DomainTools`; it does not replace it. `domain_tools` property
  preserves backwards compatibility for graph nodes that still call `merge_tools(domains)`.
- `FlowiseCapability` lives in `graph.py` to avoid circular imports (`_react()` and
  `_parse_converge_verdict()` must stay in `graph.py`; moving `FlowiseCapability` to
  `domains/flowise.py` would require importing from `graph.py` which imports from `domain.py`).
- `compile_ops()` and `validate()` are abstract stubs in Milestone 1 (must return
  `DomainPatchResult(stub=True)` / `ValidationReport(stub=True)`). This keeps the interface
  complete and testable while deferring Patch IR to Milestone 2.
- `build_graph(capabilities=None)` → all behaviour identical to pre-refactor. The
  capability path is fully opt-in.

**Files added**: `flowise_dev_agent/agent/domain.py`, `flowise_dev_agent/agent/domains/__init__.py`

**Rejected alternatives**:
- Subclassing `DomainTools` for behaviour: mixes data and behaviour into one class,
  makes testing harder (cannot mock the executor independently of the lifecycle).
- Protocol instead of ABC: ABCs give clearer instantiation errors and allow `super()` calls.
  Protocol would require structural subtyping which is harder to enforce statically.

---

## DD-047 — WorkdayCapability Stub-First Approach

**Date**: 2026-02-23
**Decision**: Implement `WorkdayCapability` in `agent/domains/workday.py` as a full
`DomainCapability` subclass with all five lifecycle methods returning typed stubs.
Tool definitions exist (`get_worker`, `list_business_processes`) but the executor
returns synthetic placeholder data without any real Workday API calls.

**Reason**: The stub establishes the full domain interface before any Workday API is
available. This serves two purposes: (1) it proves the `DomainCapability` contract
is implementable end-to-end without needing live infrastructure; (2) it gives a
concrete target for the Milestone 3 activation checklist — every change required to
go from stub to real is documented in the module docstring.

**Activation checklist** (in `workday.py` docstring):
1. Replace `_WORKDAY_DISCOVER_TOOLS` with real Workday MCP `ToolDef`s.
2. Replace `_stub_get_worker` / `_stub_list_business_processes` with real async callables.
3. Replace `WorkdayCapability.discover()` body with a `_react()` loop call.
4. Update `workday_extend.md` with real discovery rules.
5. Pass `WorkdayCapability()` to `build_graph(capabilities=[..., WorkdayCapability()])`.

**No other files need to change when the stub is activated.**

**Rejected alternatives**:
- Skip stub, implement only when Workday API is available: loses the architectural
  proof-of-concept and delays identifying any interface gaps until Milestone 3.
- Inline stub in `graph.py`: violates the domain isolation principle; Workday code
  belongs in `agent/domains/`, not in the Flowise orchestrator.

---

## DD-048 — ToolResult Envelope (Compact Context Enforcement)

**Date**: 2026-02-23
**Decision**: Add a `ToolResult` dataclass as the single return type of `execute_tool()`.
All executor callables still return raw `Any`; `_wrap_result(tool_name, raw)` wraps the
raw output at the `execute_tool()` boundary. `result_to_str(ToolResult)` returns only
`result.summary` — this is the sole enforcement point for the compact context policy.

**ToolResult fields**:
- `ok: bool` — success/failure flag
- `summary: str` — compact, prompt-safe; injected into `msg.content` / LLM context
- `facts: dict` — structured deltas destined for `state['facts']`
- `data: Any` — raw output destined for `state['debug']`; **never** injected into LLM context
- `error: dict | None` — `{type, message, detail}` when `ok=False`
- `artifacts: dict | None` — persistent refs (`chatflow_ids`, snapshot labels) for `state['artifacts']`

**`_wrap_result` priority rules** (applied in order):
1. `{"error": ...}` dict → `ok=False`, summary = error message
2. `{"valid": ...}` dict (validate_flow_data) → pass/fail with error count
3. `{"id": ...}` dict (chatflow) → `"Chatflow '{name}' (id={id})."` + `artifacts`
4. `{"snapshotted": True}` dict → snapshot summary with version label
5. `list` → `"{tool_name} returned {N} item(s)."`
6. other `dict` → first 200 chars of JSON
7. scalar/string → first 300 chars

**Test node special case**: `_run_trial` uses `result.data` (not `result.summary`) when
passing prediction responses to the evaluator LLM. The evaluator needs the full chatbot
response to judge PASS/FAIL; the compact summary is too lossy for evaluation purposes.
Error paths still use `result.summary`.

**Invariant**: `result_to_str(ToolResult)` → `result.summary` always. Raw data never
enters LLM context through any code path in graph.py or tools.py.

**Backwards compatibility**: All 21 existing executor callables are unchanged. Wrapping
happens entirely inside `execute_tool()`. Callers that checked `isinstance(result, dict)`
now check `isinstance(result, ToolResult)`.

**Rejected alternatives**:
- Truncating raw JSON at 500 chars: truncation is lossy and still allows large blobs for
  most responses. Summary generation requires understanding the tool's semantics.
- Per-tool result formatting inside each executor: duplicates formatting logic, hard to
  enforce consistently as new tools are added.
- Enforcing compact context in the system prompt only: instruction-following is unreliable
  for size constraints; code enforcement is the only reliable guarantee.

---

## DD-049 — ToolRegistry v2 (Namespaced, Phase-Gated, Dual-Key)

**Date**: 2026-02-23
**Decision**: Add `ToolRegistry` in `agent/registry.py`. Tools are registered with a
`namespace` (e.g. `"flowise"`), a `ToolDef`, a `phases` set (`{"discover"}`, `{"patch"}`,
etc.), and an async callable. The registry's `executor(phase)` returns a **dual-keyed**
dict: both `"flowise.get_node"` and `"get_node"` map to the same callable.

**Reason**: Without namespacing, adding Workday creates an immediate collision:
`get_node` (Flowise) vs. `get_worker` (Workday) are unambiguous today, but future
tools may share names. Namespacing to `flowise.get_node` / `workday.get_worker` makes
the identity canonical. Phase gating prevents discover-only tools from appearing in the
patch executor (reducing the LLM's tool surface at each phase).

**Dual-key executor** invariant: `executor()` always includes BOTH the namespaced key
(`"flowise.get_node"`) AND the simple key (`"get_node"`). This means:
- The LLM, which receives namespaced `ToolDef` names, calls the right tool.
- Existing Python code that looks up `executor["get_node"]` still works without changes.
- Zero regression risk on the legacy code path.

**`register_domain(domain: DomainTools)` convenience method**: registers all of
`domain.discover`, `domain.patch`, and `domain.test` tools in one call, inferring the
phase set from which list each tool appears in. Tools in multiple lists get merged phases.

**Files added**: `flowise_dev_agent/agent/registry.py`

**Rejected alternatives**:
- Flat global tool registry: doesn't support multi-domain or phase gating; adding any
  domain risks name collisions.
- Namespace prefix only in `tool_defs()`, not in `executor()`: breaks the LLM's ability
  to call `flowise.get_node` — the name in the tool definition must match the executor key.
- Separate executor dicts per namespace: callers would need to know the namespace of
  every tool call, coupling all call sites to the namespace scheme.

---

## DD-050 — AgentState Trifurcation (Transcript / Artifacts / Debug)

**Date**: 2026-02-23
**Decision**: Add three new domain-keyed fields to `AgentState`, all using a new
`_merge_domain_dict` reducer (last-writer-wins per domain key):

- `artifacts: dict[str, Any]` — persistent references produced during a phase
  (chatflow IDs, snapshot labels). Written by discover/patch nodes; read by test/converge.
- `facts: dict[str, Any]` — structured deltas extracted from tool results
  (chatflow_id, node names, credential types). Written per tool call; read by plan.
- `debug: dict[str, Any]` — raw tool output, keyed by iteration and tool name.
  **Never injected into LLM context.** Exists solely for introspection and unit testing.

**Reason**: The `messages` list serves two incompatible purposes: LLM context (messages
must be compact) and audit trail (raw data is useful for debugging). Separating these
into distinct state fields with explicit semantics removes the temptation to inject
`debug` content into LLM prompts, and makes it trivial to find structured data (look in
`facts`) vs. raw API output (look in `debug`) without scanning the full message history.

**`_merge_domain_dict` reducer semantics**:
```python
_merge_domain_dict({"flowise": {...}}, {"workday": {...}})
→ {"flowise": {...}, "workday": {...}}   # domain keys are merged
```
Each domain owns its key. One domain's discover phase cannot overwrite another domain's
facts or artifacts. LangGraph calls the reducer on every state update.

**State separation invariant**:
- `messages` — transcript: tool *summaries* (compact), plan text, user messages
- `artifacts` — canonical refs: chatflow IDs, snapshot labels; survives iteration boundary
- `facts` — structured deltas: tool-specific typed data; updated each discover cycle
- `debug` — raw: full API responses; NOT LLM context; reset or accumulated per session

**`_initial_state()` in api.py** was updated to include `"artifacts": {}, "facts": {}, "debug": {}`
so existing sessions started without these fields don't fail with `KeyError`.

**Rejected alternatives**:
- Single `domain_context: dict` field for everything: mixes compact summaries with raw data,
  making it impossible to enforce the "no raw blobs in LLM context" invariant.
- Append-list reducer (same as `messages`): domain data is replaced each iteration, not
  appended; a merge reducer matches the actual write pattern.
- Separate top-level TypedDict per domain: requires changing `AgentState` every time a
  new domain is added; the domain-keyed dict is open to extension without schema changes.

---

## DD-051 — Patch IR Schema (AddNode / SetParam / Connect / BindCredential)

**Date**: 2026-02-23
**Decision**: Replace "LLM writes full flowData JSON" with a typed Intermediate Representation
(IR) where the LLM produces a list of atomic operation objects and a deterministic compiler
translates them to the final Flowise API payload.

**Four op types:**
| Op | Purpose |
|----|---------|
| `AddNode` | Add a new Flowise node (type name + unique ID + optional params) |
| `SetParam` | Set a single `data.inputs` parameter on an existing node |
| `Connect` | Connect two nodes by anchor *names* (not raw handle strings) |
| `BindCredential` | Bind a credential ID at both `data.credential` levels |

**JSON discriminator:** each op carries `"op_type"` so deserialisation is unambiguous.

**Implementation** (`flowise_dev_agent/agent/patch_ir.py`):
- All four ops are `@dataclass` objects (consistent with existing codebase style)
- `validate_patch_ops(ops, base_node_ids)` catches: empty required fields,
  duplicate node IDs in AddNode ops, refs to non-existent nodes in Connect/SetParam/BindCredential
- `ops_from_json(s)` strips `\`\`\`json...\`\`\`` fences from LLM output before parsing
- `PatchIRValidationError` for programmatic error handling

**Compiler** (`flowise_dev_agent/agent/compiler.py`):
- `GraphIR` — canonical in-memory graph (nodes + edges)
- `GraphIR.from_flow_data(raw)` — parse existing Flowise flowData into GraphIR
- `compile_patch_ops(base_graph, ops, schema_cache)` — applies ops, returns `CompileResult`
- `CompileResult` carries: `flow_data`, `flow_data_str`, `payload_hash`, `diff_summary`, `errors`
- Anchor IDs derived deterministically from `_get_node_processed()` schemas (substitutes
  `{nodeId}` placeholder with actual node ID)
- Edge IDs: `"{src_node_id}-{src_anchor}-{tgt_node_id}-{tgt_anchor}"` — stable, no randomness
- Auto-layout: places new nodes in a 300px × 200px grid right of existing nodes

**Reason**: LLM-generated raw flowData JSON caused three recurring failure categories:
1. Wrong handle string format (LLM guesses anchor IDs that don't match schema)
2. Missing `data.credential` at both required levels (LLM sets only one)
3. Invalid JSON structure (`{}` instead of `{"nodes":[],"edges":[]}`)
By shrinking the LLM's output to anchor *names* (not handles) and credential *IDs* (not
both locations), each category is eliminated at compile time, not discovered at Flowise-write time.

**Key invariant**: The LLM NEVER writes handle IDs or edge IDs. The compiler derives them from
`_get_node_processed()` schemas. This eliminates the most common source of Flowise HTTP 500s.

**Backwards compatibility**: `build_graph(capabilities=None)` still uses the original
LLM-driven `_make_patch_node()`. The IR path is only active when capabilities are provided.

**Rejected alternatives**:
- Strict typed output (Pydantic structured output): adds a Pydantic round-trip and LLM-side
  schema compliance pressure; `ops_from_json` with fence stripping is simpler and equally safe.
- Keep full flowData LLM-generated but post-process: you'd need a second LLM call to "fix"
  bad handle strings, losing the determinism benefit entirely.

---

## DD-052 — WriteGuard: Same-Iteration Hash Enforcement

**Date**: 2026-02-23
**Decision**: Any Flowise write (`create_chatflow` / `update_chatflow`) is blocked by code
unless the exact payload that was written also passed `validate_flow_data` in the same iteration.

**Mechanism** (`flowise_dev_agent/agent/tools.py — WriteGuard`):
1. `guard.authorize(flow_data_str)` — called after `_validate_flow_data()` succeeds.
   Computes SHA-256 of `flow_data_str` and stores it as the authorized hash.
2. `guard.check(flow_data_str)` — called inside guarded `create_chatflow` / `update_chatflow`
   wrappers before the Flowise API call. Raises `PermissionError` if:
   - `authorize()` was never called → `"ValidationRequired"` error
   - payload differs from the authorized one → `"HashMismatch"` error
3. `guard.revoke()` — called after a successful write. One-shot: re-authorization required
   before any subsequent write.

**`_make_flowise_executor(client, guard=None)`** — updated to accept an optional `WriteGuard`.
When `guard is not None`, the three tools `validate_flow_data`, `create_chatflow`,
`update_chatflow` are replaced with guarded wrappers. When `guard=None` (default), behaviour
is identical to pre-M2 (no guard, full backwards compat).

**State field** `validated_payload_hash: str | None` in `AgentState` — the patch node
stores the authorized hash after a successful write for audit trail purposes.

**In the v2 patch node** (`_make_patch_node_v2`), the guard is built locally per iteration:
the compiler produces `CompileResult.payload_hash`, `guard.authorize(flow_data_str)` is called
explicitly, and write tools are wrapped with the guard. This means even if a future refactor
accidentally modifies the payload between validation and write, the guard raises at call time.

**Reason**: The primary risk in a code-driven patch system is "drift" between the flowData
that the structural validator checked and the flowData that is actually written. A hash-match
gate makes this physically impossible: the compiler's output is the validator's input is the
write's input, all the same bytes.

**Error types returned by the guard** (both as `PermissionError`):
- `"ValidationRequired"` — write called before validation; tells caller to call `validate_flow_data` first
- `"HashMismatch"` — payload was modified after validation; caller must re-validate

**Rejected alternatives**:
- Re-running validation inside the write wrapper: expensive; validation already happened at
  the compile step. A hash check is O(n) on payload size — trivially fast.
- Requiring an explicit `authorized_hash` parameter on `create_chatflow` / `update_chatflow`:
  changes tool signatures; requires LLM to pass the hash it doesn't know. The guard closure
  is transparent to callers.

---

## DD-059 — v1 Patch Node: Chatflow Context Injection

**Decision**: In `_make_patch_node()` (v1 LLM-driven path), inject `chatflow_id` and
`developer_feedback` into the LLM user context message before invoking the model.

**Reason**: The v1 patch node previously built its context from `requirement` +
`discovery_summary` only. On the first iteration, the LLM correctly called `create_chatflow`.
On subsequent iterations, the LLM re-read the original plan (which said "CREATE…") and called
`create_chatflow` again, producing a duplicate chatflow. By injecting an explicit
`IMPORTANT: Chatflow '{id}' already exists — use update_chatflow` note, the LLM is correctly
oriented on every iteration without modifying any tool signatures or graph topology.

`developer_feedback` (which may carry a selected approach label from the plan_approval
interrupt) is also appended so the patch node acts on the developer's choice.

**v2 patch node**: Unaffected — it uses programmatic CREATE vs UPDATE logic (not LLM) and
already reads `chatflow_id` directly from state at line 1186.

**Rejected alternatives**:
- Modifying the system prompt to always mention chatflow_id: system prompts are static strings;
  the chatflow_id is only known at runtime.
- Adding a graph edge to re-run discover before patch: adds latency; discover already ran.

---

## DD-060 — Structured Plan `## APPROACHES` Section

**Decision**: Instruct the plan node to emit an optional `## APPROACHES` section in the plan
when two or more meaningfully different implementation strategies exist. The section lists
numbered approaches with a short label and one-sentence description. A `_parse_plan_options()`
helper extracts the labels via regex and adds them to `InterruptPayload.options`. The UI
renders each option as a clickable card; selecting one and clicking "Approve Selected Approach"
resumes the graph with `"approved - approach: <label>"`, which the v1 patch node reads from
`developer_feedback` to execute the chosen strategy.

**Reason**: During testing, the plan node produced plans with two alternatives (e.g. "UPDATE
OR CREATE new chatflow") and the Approve button sent only the opaque string `"approved"` with
no way for the developer to specify which path to take. The LLM then guessed. A structured
approach list makes the choice explicit and machine-readable end-to-end.

**Format contract**:
```
## APPROACHES
1. Update existing: Locate the existing chatflow and apply targeted edits.
2. Create fresh: Delete the old chatflow and build a new one from scratch.
```
Section omitted entirely when there is only one clear path.

**Rejected alternatives**:
- Separate clarification interrupt before plan: adds a full round-trip; approach selection
  belongs at plan review time, not before the plan exists.
- Freeform text parsing in the patch node: brittle; `## APPROACHES` + numbered list is a
  well-defined, easily regex-parseable contract.

---

## DD-061 — Session Naming and UI Iteration Fixes (Roadmap 6)

**Decision**: Bucket the following UI and agent quality-of-life improvements under a single DD
to avoid proliferating low-signal entries:

1. **Session names** (`session_name` in `AgentState`): At session creation, a single LLM
   `complete()` call generates a 4–6 word display title. Stored in checkpointed state; editable
   via `PATCH /sessions/{id}/name` (persists across refreshes using `aupdate_state()`). The
   sidebar shows the name as the primary row title; thread UUID demoted to the secondary
   `.s-meta` line. Pencil icon on hover opens an inline `<input>` that saves on Enter/blur and
   cancels on Escape.

2. **Session delete** (UI only): `DELETE /sessions/{id}` already existed. A trash icon button
   added to each sidebar row (visible on hover) calls it with a confirmation dialog, removes
   the session from `state.sessions`, and navigates to idle if the deleted session was active.

3. **Rollback button on result_review**: The `human_result_review` node now recognises
   `"rollback"` / `"revert"` as terminal responses (sets `done=True` with a rollback note).
   A red "↩ Rollback" button alongside "✓ Accept" in the result_review interrupt card calls
   `quickReply('rollback')` — no new API endpoint needed; `POST /sessions/{id}/rollback`
   already exists.

4. **Approach selection for plan_approval** (UI counterpart to DD-060): When
   `InterruptPayload.options` is present, the UI renders selectable approach cards instead of
   the plain "Approve Plan" button. Selecting a card enables "Approve Selected Approach"; the
   resume payload becomes `"approved - approach: <label>"`.

**Why one DD**: All four changes are UI/UX polish items that improve developer ergonomics
without altering the core orchestration loop, state machine, or tool contracts. Bucketing them
avoids fragmentation while preserving a traceable record of what was changed and why.

---

## DD-062 — Local-First Node Schema Snapshot (Roadmap 6, Milestone 1)

**Decision**: Introduce a `FlowiseKnowledgeProvider` that loads `schemas/flowise_nodes.snapshot.json`
at startup and provides O(1) node schema lookups. The `_make_patch_node_v2` Phase D loop, which
previously called `execute_tool("get_node", ...)` for every new node type on every patch iteration,
now reads from the local snapshot first. A targeted API call is made **only** when the requested
`node_type` is absent from the snapshot (repair-only, not discovery-every-run).

**Problem it solves**: Building a chatflow with three node types caused three sequential `get_node`
API calls on every patch iteration. Node schemas are stable between Flowise releases — fetching
them every run is wasteful by design.

**Implementation**:

- `flowise_dev_agent/knowledge/provider.py` — `NodeSchemaStore` loads the snapshot, validates its
  SHA-256 fingerprint, and builds an in-memory `{node_type → schema}` index. On cache miss,
  `get_or_repair()` calls the provided `api_fetcher` coroutine for that one node type only,
  normalises the result to match the exact output shape of `_get_node_processed()` in tools.py,
  patches the index, and persists to disk with a refreshed fingerprint.

- `flowise_dev_agent/knowledge/refresh.py` — CLI job that parses `FLOWISE_NODE_REFERENCE.md`
  (303 nodes, 24 categories) into the snapshot JSON. The markdown is **never loaded at runtime**.
  Run: `python -m flowise_dev_agent.knowledge.refresh --nodes [--dry-run]`

- `schemas/flowise_nodes.snapshot.json` — 303 node schema objects. Each entry: `node_type`,
  `label`, `category`, `version`, `baseClasses`, `credential_required` (when present),
  `inputAnchors`, `inputParams`, `outputAnchors`, `outputs`. Format exactly matches
  `_get_node_processed()` output so `schema_cache` entries are structurally identical to
  live API-fetched entries.

- `schemas/flowise_nodes.meta.json` — SHA-256 fingerprint, `generated_at`, `source`, `node_count`.

**Narrow integration points** (only two files edited):
1. `FlowiseCapability.__init__` — instantiates `FlowiseKnowledgeProvider()` as `self._knowledge`,
   exposed via a `knowledge` property.
2. `_make_patch_node_v2` Phase D — replaces the `asyncio.gather(get_node...)` fan-out with a
   per-name `node_store.get_or_repair()` call. Repair events written to
   `debug["flowise"]["knowledge_repair_events"]`.

**Version/schema-hash gating on repair**: `skip_same_version` (no overwrite), `update_changed_version_or_hash`,
`update_no_version_info`, `update_new_node`. Prevents redundant disk writes when API and local agree.

**`capabilities=None` legacy path**: `node_store` is `None` → falls back to the original
`execute_tool("get_node", ...)` call. Pre-refactor behaviour preserved exactly.

**Prompt hygiene**: Snapshot data is never injected into LLM prompts. `schema_cache` goes only
to `compile_patch_ops()` (deterministic compiler), not to any message-building function.

**Rejected alternatives**:
- In-process TTL cache inside `_get_node_processed`: not durable across restarts, not inspectable.
- System-prompt injection of all node schemas: violates the no-full-snapshot-injection constraint.
- `list_nodes` at startup: returns slim objects only — full `inputs`/`outputAnchors` still needed.

---

## DD-063 — Marketplace Template Metadata Snapshot (Roadmap 6, Milestone 2)

**Decision**: Extend `FlowiseKnowledgeProvider` with a `TemplateStore` that holds a
metadata-only snapshot of the Flowise marketplace templates (no `flowData`).
The plan node uses `TemplateStore.find()` to inject a brief hint (≤3 entries,
description ≤120 chars) when templates are relevant to the requirement.

**Problem it solves**: The plan phase previously had no awareness of existing templates,
causing the agent to build chatflows from scratch that could have been imported as a
template starting point.  The existing `list_marketplace_templates` tool call is avoided
for agents that already have a local snapshot, preventing the ~1.7 MB API response on
every planning cycle.

**Implementation**:

- `flowise_dev_agent/knowledge/provider.py` — `TemplateStore` class added after `NodeSchemaStore`.
  Loads `schemas/flowise_templates.snapshot.json` lazily.  `is_stale(ttl_seconds)` reads
  `generated_at` from `flowise_templates.meta.json`; default TTL 86400 s (overridable via
  `TEMPLATE_SNAPSHOT_TTL_SECONDS` env var).  `find(tags, limit=3)` does case-insensitive
  substring matching across `templateName`, `categories`, `usecases`, `description` and
  returns ranked slim dicts.  `FlowiseKnowledgeProvider` gains a `template_store` property.

- `flowise_dev_agent/knowledge/refresh.py` — `--templates` flag added.  `refresh_templates()`
  calls `FlowiseClient.list_marketplace_templates()` via `asyncio.run()`, strips all fields
  except `_TEMPLATE_SLIM_FIELDS` (`templateName`, `type`, `categories`, `usecases`,
  `description`), writes snapshot + meta.  `--nodes` and `--templates` can be combined.

- `schemas/flowise_templates.snapshot.json` — placeholder `[]` until first `--templates` run.
- `schemas/flowise_templates.meta.json` — placeholder meta with `"status": "empty"`.

**Narrow integration point** (one file edited):
- `_make_plan_node()` — accepts optional `template_store: TemplateStore | None`.  Extracts
  4+ char non-stop-word tokens from `state["requirement"]` (cap 15), calls `find()`, and
  appends a one-paragraph hint to the plan context when matches exist.  Zero overhead when
  snapshot is empty or `capabilities=None` (template_store is `None`).
- `build_graph()` — extracts `template_store` from any capability that exposes
  `cap.knowledge.template_store`; passes it to `_make_plan_node`.

**Prompt-hygiene guardrail**: `find()` returns at most 3 slim entries; the full catalog is
never injected.  Stale snapshots still serve cached results (debug log only — no errors).

**`capabilities=None` legacy path**: `_template_store` remains `None` → `_make_plan_node`
receives `None` → no hint injected.  Pre-refactor behaviour preserved exactly.

**Refresh command**:
```
python -m flowise_dev_agent.knowledge.refresh --templates
```
Requires `FLOWISE_API_ENDPOINT` (defaults to `http://localhost:3000`) in environment.

**Rejected alternatives**:
- Per-request `list_marketplace_templates` API call in the plan node: requires network,
  adds latency, returns 1.7 MB that must be stripped before injection.
- Injecting all template names into the system prompt: violates no-full-snapshot-injection
  constraint; templates change rarely — no value in per-request injection.

---

## DD-064 — Credential Metadata Snapshot (Roadmap 6, Milestone 3)

**Decision**: Extend `FlowiseKnowledgeProvider` with a `CredentialStore` that holds an
allowlisted snapshot of Flowise credential metadata.  `_make_patch_node_v2` uses
`CredentialStore.resolve_or_repair()` in a new Phase C.2 to auto-fill empty
`credential_id` fields on `BindCredential` ops before IR validation runs.

**Problem it solves**: The `BindCredential` op requires the developer or LLM to provide
the credential UUID.  The LLM reliably knows the *type* (e.g. `"openAIApi"`) but frequently
omits the UUID (which requires a `list_credentials` call to discover).  With local-first
resolution, the UUID is available in O(1) from the snapshot — no API call needed when the
credential was previously fetched.

**Security contract** (hard, non-negotiable):
The snapshot allowlist — `credential_id`, `name`, `type`, `tags`, `created_at`, `updated_at`
— is enforced at three layers:
1. **Refresh job** (`_normalize_credential_api`): strips all non-allowlisted keys before
   writing.  The job then re-validates and aborts if any banned key survived.
2. **CredentialStore._load()**: validates allowlist on every load; strips defensively and
   logs an error if violations are found (so a tampered snapshot is not silently used).
3. **CredentialStore._persist()**: final strip before every disk write (repair path).

The snapshot **MUST NOT be committed to git** — it contains live instance credential IDs
and names that are machine-specific.  See `.gitignore`.

**`--validate` CI lint step**:
```
python -m flowise_dev_agent.knowledge.refresh --credentials --validate
```
Reads the existing snapshot, checks for banned keys, exits 1 on any violation.
Zero API calls — safe to run in CI.

**Implementation**:

- `flowise_dev_agent/knowledge/provider.py` — `_CRED_ALLOWLIST` frozenset (6 keys);
  `_normalize_credential()` handles both API shape and snapshot shape; `_validate_allowlist()`
  returns violation messages; `CredentialStore` class with:
  - `_by_id`, `_by_name`, `_by_type` indices (built lazily at load time).
  - `resolve(name_or_type_or_id)`: sync, O(1), tries id → name → type.
  - `resolve_or_repair(q, api_fetcher)`: async, falls back to `list_credentials` API on miss,
    normalises + persists, retries.
  - `is_stale(ttl_seconds)`: reads `generated_at` from meta; default TTL 3600 s
    (`CREDENTIAL_SNAPSHOT_TTL_SECONDS` env var).
  - `FlowiseKnowledgeProvider` gains `credential_store` property.

- `flowise_dev_agent/knowledge/refresh.py` — `--credentials` flag:
  `_normalize_credential_api()` maps Flowise API fields to snapshot fields;
  `validate_credential_snapshot()` is the CI lint function;
  `refresh_credentials(dry_run, validate_only)` fetches + normalises + diff + writes.
  `--validate` flag runs lint only (no API call, no write).

- `schemas/flowise_credentials.snapshot.json` — placeholder `[]` (gitignored).
- `schemas/flowise_credentials.meta.json` — placeholder meta (gitignored).

**Narrow integration point** (one existing function restructured):
- `_make_patch_node_v2` Phase C restructured into C.1 (parse) → C.2 (credential resolution)
  → C.3 (IR validation).  C.2 iterates `BindCredential` ops with empty `credential_id`,
  calls `resolve_or_repair()`, and mutates `op.credential_id` in-place so that C.3
  (which checks `if not op.credential_id`) sees the filled-in value.
- Resolved credentials written to `facts["flowise"]["resolved_credentials"]` map.
- Credential repair events written to `debug["flowise"]["credential_repair_events"]`.
- `BindCredential` imported into `graph.py` (previously only referenced in string prompts).

**`capabilities=None` legacy path**: `_cred_store` is `None` → Phase C.2 is a no-op →
all behaviour identical to pre-refactor.

**Repair fallback**: calls `execute_tool("list_credentials", {}, discover_executor)` — the
same executor used by Phase D for node schemas.  Result is normalised to allowlist before
any index update or disk write.  Exactly one API call per miss.

**Refresh command**:
```
python -m flowise_dev_agent.knowledge.refresh --credentials [--dry-run]
python -m flowise_dev_agent.knowledge.refresh --credentials --validate  # CI lint
```
Requires `FLOWISE_API_ENDPOINT` (defaults to `http://localhost:3000`) in environment.

**Rejected alternatives**:
- Storing full encrypted credential data: violates security contract; Flowise already
  handles encryption — the agent only needs the ID for binding, not the secret.
- Per-patch `list_credentials` call: adds network latency every iteration; credentials
  change infrequently (user-action required) so caching is appropriate.

---

## DD-065 — Workday Knowledge Provider Stubs (Roadmap 6, Milestone 4)

**Decision**: Introduce `WorkdayKnowledgeProvider`, `WorkdayMcpStore`, and `WorkdayApiStore`
in `flowise_dev_agent/knowledge/workday_provider.py` as explicit stubs.  All public lookup
methods raise `NotImplementedError`.  Four stub snapshot files (`workday_mcp.snapshot.json`,
`workday_mcp.meta.json`, `workday_api.snapshot.json`, `workday_api.meta.json`) are committed
with `status: stub`.  The refresh CLI gains `--workday-mcp` and `--workday-api` as no-op
flags that exit 0 and print an informative message.

**Why stubs, not nothing**:
- Committing the scaffold avoids a "big-bang" Milestone 5 PR that mixes new
  architecture with a provider implementation — reviewers can evaluate each layer
  independently.
- The `NotImplementedError` contract is an explicit promise: callers that
  accidentally wire `WorkdayCapability` into `build_graph` will get an immediate,
  descriptive error rather than silent fallback to empty data.
- Stub meta files (`status: stub`) let tooling (CI, health checks) detect that
  Workday knowledge is intentionally unpopulated without treating it as a missing file.
- No-op CLI flags let the refresh job be invoked with `--workday-mcp --workday-api`
  in scripts that will work correctly once real implementations land in Milestone 5+.

**Structure**:
- `WorkdayMcpStore` — future: Workday MCP endpoint metadata (loaded from
  `schemas/workday_mcp.snapshot.json`).
- `WorkdayApiStore` — future: Workday REST/SOAP API endpoint metadata (loaded from
  `schemas/workday_api.snapshot.json`).
- `WorkdayKnowledgeProvider` — mirrors `FlowiseKnowledgeProvider` pattern; holds both
  sub-stores; safe to instantiate (no network I/O, no errors on construction).
- `_stub_meta()` helper on each store: non-raising; reads the on-disk meta for
  informational use (e.g. health check endpoints).

**Integration points (deferred to Milestone 5+)**:
- `WorkdayCapability` in `agent/domains/workday.py` will accept a
  `WorkdayKnowledgeProvider` instance once real data is available.
- `build_graph(capabilities=[..., WorkdayCapability()])` — no graph.py changes needed.

**Rejected alternatives**:
- Implementing real Workday data in M4: Workday API schema is complex and
  environment-specific; stub-first keeps M4 small and reviewable.
- Leaving workday_provider.py absent until M5: makes the M5 PR harder to review
  and removes the `NotImplementedError` guardrail that prevents accidental use.

---

## DD-066 — Capability-First Default Runtime (Roadmap 7, Milestone 7.1)

**Decision**: Make the DomainCapability path (`capabilities=[FlowiseCapability(...)]`) the
default at graph construction time. The legacy DomainTools merge path is retained but
opt-in only via the `FLOWISE_COMPAT_LEGACY` env var. A `runtime_mode` field is added to
`AgentState` and surfaced in `GET /sessions` so operators can confirm which path a session used.

**Why change the default now**:
- The capability path has been production-ready since Milestone 1 (Roadmap 3), but
  `build_graph(capabilities=None)` remained the default because callers explicitly opted in.
  Roadmap 7 makes cross-domain work (Workday MCP, PlanContract) depend on the capability
  path, so "opt-in" is no longer the right posture.
- Keeping the legacy path available via env var gives operators a zero-risk escape hatch
  during rollout without requiring code changes.

**Implementation**:
- `_COMPAT_LEGACY: bool` — module-level constant in `api.py`, reads `FLOWISE_COMPAT_LEGACY`
  env var at import time.  `"1"`, `"true"`, `"yes"` (case-insensitive) activate legacy mode.
- `make_default_capabilities(engine, domains)` — new public factory in `graph.py`.
  Encapsulates `_build_system_prompt(_DISCOVER_BASE, ...)` so `api.py` does not import
  private graph helpers.
- `AgentState.runtime_mode: str | None` — set once at session creation from `app.state.runtime_mode`.
  Values: `"capability_first"` | `"compat_legacy"`.  Never mutated after creation.
- `SessionSummary.runtime_mode` — exposed in `GET /sessions` for observability.

**Guard: no new logic in legacy path**:
The `build_graph()` signature is unchanged.  No new branches are added inside the legacy
`discover_legacy` / `_make_patch_node` nodes.  `capabilities=None` produces byte-identical
behaviour to all pre-Roadmap-7 sessions.

**Rejected alternatives**:
- Hard-removing the legacy path: too risky before cross-domain features are validated in
  production; legacy path may be needed for regression testing.
- Runtime toggle via API request body: env var is the right boundary — the routing mode
  is an operator/deployment concern, not a per-session developer input.

---

## DD-067 — Cross-Domain PlanContract + TestSuite (Roadmap 7, Milestone 7.2)

**Decision**: Extend the plan node to parse a structured `PlanContract` dataclass from the
LLM plan output and store it as `facts["flowise"]["plan_contract"]`.  Extend `TestSuite`
with `domain_scopes` and `integration_tests` fields.  Extend the converge node to inject
`success_criteria` from the contract into the verdict prompt so the LLM references concrete,
developer-approved conditions rather than re-deriving them.

**PlanContract fields**:
- `goal` — one-sentence chatflow description (from `1. GOAL`).
- `domain_targets` — domains involved (e.g. `["flowise"]` or `["flowise","workday"]`).
- `credential_requirements` — exact Flowise credentialName values required.
- `data_fields` / `pii_fields` — fields crossing domain boundaries; PII subset flagged.
- `success_criteria` — testable conditions from `5. SUCCESS CRITERIA` bullet items.
- `action` — `"CREATE"` (chatflow_id absent) or `"UPDATE"` (chatflow_id present).
- `raw_plan` — verbatim plan text for audit.

**Machine-readable sections added to `_PLAN_BASE`**:
Three sections appended after the optional `## APPROACHES` block:
`## DOMAINS`, `## CREDENTIALS`, `## DATA_CONTRACTS`.  The LLM is instructed
to emit them verbatim at the end of every plan.  The parser is tolerant: absent
or `(none)` sections default to empty lists and never raise.

**Why store in `facts["flowise"]` rather than a new top-level field**:
- `facts` already uses `_merge_domain_dict` — writing `{"flowise": {...}}` preserves
  other domain entries (e.g. `"workday"`) without coordination between nodes.
- Avoids adding a new top-level field to `AgentState` for every new structured output.
- Consistent with DD-050 (state trifurcation): `facts` is the right layer for
  structured, machine-readable data (not `debug`, not `messages`).

**Why inject success_criteria in converge context rather than system prompt**:
The `_CONVERGE_BASE` system prompt is static and shared.  Injecting criteria as a
`role="user"` message keeps the system prompt clean and allows per-session criteria
without recompiling the graph.  The criteria text is clearly labelled as coming from
the developer-approved plan contract to distinguish it from the LLM's own reasoning.

**TestSuite extensions**:
- `domain_scopes: list[str]` — which DomainCapabilities' tests run for this suite.
  Empty list = only the owning domain.  Enables future cross-domain test orchestration.
- `integration_tests: list[str]` — freeform cross-domain scenario strings.
  Both fields have `field(default_factory=list)` so all existing call-sites are unaffected.

**Rejected alternatives**:
- Storing `PlanContract` as a separate top-level `AgentState` field: adds schema
  surface area for every new structured output; `facts` is already the right place.
- Parsing success criteria from the system prompt at converge time: brittle — the
  system prompt is static and doesn't reflect the per-session developer-approved plan.
- Making `domain_scopes` required in `TestSuite`: would break every existing
  `generate_tests()` call site; default-to-empty is the correct migration strategy.

---

## DD-068 — PatternCapability Upgrade (Roadmap 7, Milestone 7.3)

**Decision**: Extend the pattern library with structured metadata columns (domain, node_types,
category, schema_fingerprint, last_used_at), a filtered search method, and an
`apply_as_base_graph()` method that seeds patch v2 with a prior pattern's GraphIR.
The plan node searches the library before LLM planning; patch v2 reads the result
from `artifacts["flowise"]["base_graph_ir"]` to reduce unnecessary AddNode ops.

**Schema migration strategy**:
`PatternStore.setup()` calls `_migrate_schema()` which reads `PRAGMA table_info(patterns)`,
detects absent columns, and issues `ALTER TABLE patterns ADD COLUMN` for each missing one.
This is safe to re-run on any existing DB (idempotent) and future-proof (new columns added
to `_M73_COLUMNS` list will be picked up automatically). Fresh DBs receive all columns via
the updated `_CREATE_TABLE` DDL.  No data is lost during migration.

**New columns**:
- `domain TEXT DEFAULT 'flowise'` — which DomainCapability produced the pattern.
- `node_types TEXT DEFAULT ''` — JSON array string of node type names in the chatflow.
- `category TEXT DEFAULT ''` — chatflow category from `6. PATTERN` section of the plan.
- `schema_fingerprint TEXT DEFAULT ''` — `NodeSchemaStore.meta_fingerprint` at save time.
- `last_used_at REAL DEFAULT NULL` — Unix timestamp set by `apply_as_base_graph()`.

**`search_patterns_filtered()` design**:
- SQL WHERE on `domain` and `category` (exact match).
- Keyword scoring (same CASE/LIKE technique as `search_patterns()`) for ranking.
- `node_types` filter is Python-side after fetch (JSON array overlap check) because
  SQLite JSON functions are not guaranteed across all deployment environments.
- When no keywords are provided it falls back to success_count ordering (no crash).

**`apply_as_base_graph()` design**:
- Fetches `flow_data` then calls `GraphIR.from_flow_data()` — same parser used by
  the legacy `get_chatflow` path, ensuring identical node representation.
- Increments `success_count` and sets `last_used_at` on every call.
- Returns empty `GraphIR()` on missing ID or empty flow_data (never raises).
- Local import `from flowise_dev_agent.agent.compiler import GraphIR` avoids
  a module-level circular dependency: `pattern_store → compiler → patch_ir`.

**Plan node integration**:
- Keywords are extracted before the template-hint block (not inside it) so the same
  keyword list is reused for both template matching and pattern search.
- Pattern search only runs on iteration 0 of CREATE flows (`chatflow_id` absent)
  to avoid incorrectly seeding an UPDATE iteration with stale base nodes.
- Failure of the pattern search is non-fatal (logged as warning, no interrupt).
- Result stored as `artifacts["flowise"]["base_graph_ir"]` using the existing
  `_merge_domain_dict` reducer — preserves other artifact keys.

**Patch v2 Phase A integration**:
- Pattern-seeded base graph is used only when `chatflow_id` is absent (the `else`
  branch of the existing `if chatflow_id` check — no existing logic changed).
- When seed is applied, Phase B context includes an explicit note telling the LLM
  NOT to re-add the seeded nodes, only to emit ops for missing nodes/params.

**Converge enrichment**:
- `_make_converge_node` now accepts `capabilities` (default `None`) — backward compat.
- `node_types` derived from `flow_data` nodes' `data.name` fields.
- `category` parsed from `6. PATTERN` section of the approved plan text.
- `schema_fingerprint` read from `FlowiseCapability.knowledge.node_schemas.meta_fingerprint`
  (the new `NodeSchemaStore.meta_fingerprint` property added in this milestone).

**`NodeSchemaStore.meta_fingerprint` property**:
Added to `provider.py`.  Reads `fingerprint` (or falls back to `sha256`) from the
`.meta.json` file without triggering a full snapshot `_load()`.  Returns `None` when
the file is absent or malformed.  Used exclusively for pattern enrichment metadata.

**Rejected alternatives**:
- SQLite `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`: only available in SQLite 3.37.0+
  (2021-11-27); PRAGMA table_info approach works on all SQLite versions ≥ 3.0.
- Python-side JSON overlap for `node_types` in SQL (JSON_EACH): would require
  enabling the JSON1 extension, which is not guaranteed on all deployment targets.
- Storing `base_graph_ir` as a new top-level `AgentState` field: `artifacts["flowise"]`
  is already the right layer for domain-scoped produced references (DD-050).

---

## DD-069 — Drift Management + Telemetry Hardening (Roadmap 7, M7.4)

**Context**: No per-phase timing or drift management existed.  Only cumulative
`total_input_tokens`/`total_output_tokens` were tracked.  Schema snapshots could be
refreshed between iterations with no detection or guard.

**`PhaseMetrics` dataclass** (`agent/metrics.py`):
Immutable snapshot of one graph-node phase.  Fields:
- `phase` — name: "discover" | "patch_b" | "patch_d" | "test" | "converge"
- `start_ts` / `end_ts` / `duration_ms` — wall-clock timing
- `input_tokens` / `output_tokens` — LLM token counts for phases with an LLM call
- `tool_call_count` — number of domain tool dispatches (discover phase)
- `cache_hits` — schema/credential lookups served from snapshot (Phase D)
- `repair_events` — API fallback count (Phase D: cache miss → targeted repair call)

All fields are `int` or `float` primitives — JSON-serialisable via `dataclasses.asdict()`.

**`MetricsCollector`** (`agent/metrics.py`):
Async context manager.  Caller sets counter attributes inside the `async with` block;
`__aexit__` finalizes into a `PhaseMetrics`.  Accessor: `m.to_dict()` returns the dict
for state merging.  The collector is *stateless with respect to LangGraph* — nodes
collect dicts and append them to `debug["flowise"]["phase_metrics"]` in their return.

**Instrumented nodes / sub-phases**:

| Phase | Counters recorded |
|-------|-------------------|
| `discover_capability` | `tool_call_count` (successful cap calls) |
| `patch_b` (LLM ops generation) | `input_tokens`, `output_tokens` |
| `patch_d` (schema resolution) | `cache_hits`, `repair_events` |
| `test` (LLM evaluation) | `input_tokens`, `output_tokens` |
| `converge` (LLM verdict) | `input_tokens`, `output_tokens` |

**State storage**: `debug["flowise"]["phase_metrics"]` — a list of `PhaseMetrics`
dicts, appended per-node using the existing `_merge_domain_dict` reducer.

**`FLOWISE_SCHEMA_DRIFT_POLICY`** env var:
Read once at module import time into `_SCHEMA_DRIFT_POLICY` (graph.py).  Values:
- `"warn"` (default) — logs a warning, continues normally.
- `"fail"` — appends a `tool_result` error message and returns early from Phase D;
  the LLM sees the error and ITERATE is forced on the next converge.
- `"refresh"` — logs and continues (refresh scheduling is future work).

Drift is detected in Phase D by comparing the current `NodeSchemaStore.meta_fingerprint`
against `facts["flowise"]["schema_fingerprint"]` (written by the prior iteration).
No drift check occurs on the first iteration (prior fingerprint is absent).

**Fingerprint persistence**: After each Phase D, the current `meta_fingerprint` is
written to `facts["flowise"]["schema_fingerprint"]`.  This uses the existing
`_phase_c_facts` dict that already carries `resolved_credentials`; merging is done
with a dict spread so no existing fact keys are overwritten.

**`SessionSummary` additions** (`api.py`):
- `total_repair_events: int` — sum of `repair_events` across all phase_metrics dicts.
- `total_phases_timed: int` — count of phase_metrics entries.
Both are extracted in `list_sessions()` from `debug["flowise"]["phase_metrics"]`.

**Rejected alternatives**:
- Writing phase_metrics directly to a top-level `AgentState` field: would require a
  new reducer and a new field in the TypedDict — unnecessary complexity when
  `debug["flowise"]` is already the right layer for domain-scoped telemetry (DD-050).
- Auto-flushing from `MetricsCollector.__aexit__` into state: requires passing
  mutable state into the context manager, which conflicts with LangGraph's
  immutable-state-update pattern (nodes return dicts, not mutate state in place).
- Calculating `cache_hits` as `len(schema_cache)`: schema_cache only contains
  hits, so the formula `len(new_node_names) - len(_phase_d_repair_events)` is used
  instead, which correctly counts snapshot-served hits vs. API-repaired ones.

---

## DD-070 — Workday Custom MCP Blueprint Approach (Roadmap 7, Milestone 7.5)

**Decision**: Workday integration uses Flowise's built-in `customMCP` selected_tool
configuration inside a standard Tool node, driven by a local blueprint snapshot.
No live Workday MCP endpoint discovery (`tools/list`) is performed at compile time.

**Key wiring parameters**:
- `selectedTool = "customMCP"` — Flowise's generic MCP adapter
- `selectedToolConfig.mcpServerConfig` = **STRINGIFIED JSON** with `url` and
  `headers.Authorization` — must be a string, not a nested object
- `selectedToolConfig.mcpActions` = `["getMyInfo", "searchForWorker", "getWorkers"]`
- `credential_type = "workdayOAuth"` — resolved to real UUID by Phase C at patch time
- `chatflow_only = true` — agentflow wiring is not supported

**Blueprint snapshot**: `schemas/workday_mcp.snapshot.json` — a JSON array of
blueprint dicts keyed by `blueprint_id`.  Refreshed via:
`python -m flowise_dev_agent.knowledge.refresh --workday-mcp`

**`compile_ops()` produces deterministic Patch IR** (no LLM call):
1. `AddNode(node_name="tool", node_id="workdayMcpTool_0", params={...})`
2. `BindCredential(node_id="workdayMcpTool_0", credential_id="workday-oauth-auto", ...)`

The `credential_id` placeholder is overwritten by Phase C of `_make_patch_node_v2`
when the real Workday OAuth credential is resolved from `CredentialStore`.

**`discover()` is blueprint-driven** (no live MCP calls):
- Loads `workday_default` blueprint from `WorkdayMcpStore`
- Returns structured facts: `mcp_mode`, `mcp_actions`, `mcp_server_url`, `auth_var`,
  `credential_type`, `oauth_credential_id`
- Falls back to module-level constants when the snapshot is empty

**Rejected alternatives**:
- Live `tools/list` MCP discovery: requires a running Workday MCP server at compile
  time, adding a hard runtime dependency with no obvious benefit given the fixed
  action set.
- Dedicated `workdayMCP` Flowise node: does not exist in the node registry; using
  `customMCP` inside the standard Tool node is the correct Flowise pattern.
- Agentflow wiring: the Workday MCP actions are read-only lookup operations that
  fit naturally into a chatflow Tool node, not an agentic workflow.

**Files**:
- `schemas/workday_mcp.snapshot.json` — blueprint data
- `flowise_dev_agent/knowledge/workday_provider.py` — `WorkdayMcpStore` (real)
- `flowise_dev_agent/agent/domains/workday.py` — `WorkdayCapability.discover()` + `.compile_ops()`
- `flowise_dev_agent/knowledge/refresh.py` — `refresh_workday_mcp()` (real)
- `tests/test_workday_mcp_integration.py` — 46 smoke tests

---

## DD-071 — Knowledge-First Prompt Contract + Knowledge-Layer Telemetry (Roadmap 8, M8.1 + M8.2)

**Decision**: The discover prompt and tool descriptions explicitly state that all 303
node schemas are pre-loaded locally and that `get_node` calls during the discover phase
are unnecessary. Per-session telemetry counters (`get_node_calls_total`,
`knowledge_repair_count`, `phase_durations_ms`) are surfaced in `SessionSummary`.

**Problem solved**: Prior wording ("Call `get_node` for EVERY node you intend to
include") was technically correct (the tool is served from a local cache) but
misleading — the LLM treated it as an expensive obligation and sometimes skipped it,
or called it redundantly during discover for nodes it had no plan to use.

**Changes**:
- `_DISCOVER_BASE` (graph.py): replaced "RULE: Call get_node for EVERY node" with a
  "NODE SCHEMA CONTRACT" block clarifying local-first resolution.
- `_FLOWISE_DISCOVER_CONTEXT` (tools.py): removed per-node `get_node` instruction;
  added explicit "do not call get_node during discover" guidance.
- `get_node` tool description: split into DISCOVER PHASE (discourage) / PATCH PHASE
  (call freely) sections.
- `_PATCH_IR_SYSTEM` rule 7: anchor/param names must come from `get_node`; all 303
  schemas available locally at zero cost.
- `NodeSchemaStore._call_count` (provider.py): increments on every `get_or_repair`
  call (hits + misses).
- `graph.py` patch node: writes `get_node_calls_total` to `debug["flowise"]` after
  Phase D.
- `SessionSummary` (api.py): adds `knowledge_repair_count`, `get_node_calls_total`,
  `phase_durations_ms` fields; `list_sessions()` populates them from debug state.

**Rejected alternatives**:
- Removing `get_node` from discover tool list entirely: would break the legacy
  path (capabilities=None) where discover is the only schema-fetch opportunity.
- Silent behaviour: without explicit contract language, LLM models trained on
  tool-use patterns default to calling every tool "defensively".

**Files**:
- `flowise_dev_agent/agent/graph.py` — `_DISCOVER_BASE`, `_PATCH_IR_SYSTEM`, Phase D
- `flowise_dev_agent/agent/tools.py` — `_FLOWISE_DISCOVER_CONTEXT`, `get_node` tool def
- `flowise_dev_agent/knowledge/provider.py` — `_call_count`
- `flowise_dev_agent/api.py` — `SessionSummary` telemetry fields
- `tests/test_m74_telemetry.py` — M8.2 telemetry tests (4 new cases)

---

## DD-072 — RAG Document-Source Guardrail (Roadmap 8, M8.1)

**Decision**: Vector store nodes (`memoryVectorStore`, `pinecone`, `faiss`, etc.)
require a document loader wired to their `document` input anchor. This constraint is
enforced at three layers: the discover system prompt, the skill file (`flowise_builder.md`),
and the node reference doc (`FLOWISE_NODE_REFERENCE.md`).

**Problem solved**: RAG chatflows built without a document loader node silently
produce HTTP 500 ("Expected a Runnable") at Flowise runtime. The agent had no
guardrail and would generate structurally valid but non-functional RAG flows.

**Changes**:
- `_DISCOVER_BASE` (graph.py): added "RAG CONSTRAINT" block.
- `FLOWISE_NODE_REFERENCE.md`: added "RUNTIME CONSTRAINT" callout on the
  `memoryVectorStore` entry.
- `flowise_dev_agent/skills/flowise_builder.md`: Rule 7 updated with RAG constraint.
- `tests/test_compiler_integration.py`: added `test_rag_with_document_source` (10th
  integration test) — `plainText → memoryVectorStore → conversationalRetrievalQAChain`.

**Files**:
- `flowise_dev_agent/agent/graph.py` — `_DISCOVER_BASE`
- `FLOWISE_NODE_REFERENCE.md` — `memoryVectorStore` entry
- `flowise_dev_agent/skills/flowise_builder.md` — Rule 7
- `tests/test_compiler_integration.py` — `test_rag_with_document_source`

---

## DD-073 — Multi-Output Flowise Node Format (Roadmap 8, M8.0)

**Decision**: Flowise nodes with multiple output anchors use an `outputAnchors` entry
with `type: "options"` containing an `options[]` array; the active output is selected
via an `outputs["output"]` field on the node data. The compiler, validator, and schema
normaliser were updated to produce and recognise this format.

**Problem solved**: Three independent bugs converged on the same root cause — the
agent generated and validated output anchors using the pre-options format, causing
invalid flowData when used with nodes like `memoryVectorStore` that expose multiple
outputs (`retriever`, `vectorStore`).

**Changes**:
- `compiler.py`: multi-output AddNode ops emit `options[]` wrapper; Connect op sets
  `outputs["output"]` on the source node.
- `tools.py` (`_validate_flow_data`): anchor ID lookup now descends into `options[]`
  arrays.
- `knowledge/provider.py` (`_normalize_api_schema`): priority order
  `outputs` (live API) > `outputAnchors` (legacy) > synthesized.
- `knowledge/refresh.py` (`_patch_output_anchors_from_api`): post-parse enrichment
  of 89 nodes with real output anchor names from live API; called from
  `refresh_nodes()`.
- `scripts/simulate_frontend.py`: three-step frontend simulation (plan → approve →
  accept); moved from repo root to `scripts/` in M8.3.

**Files**:
- `flowise_dev_agent/agent/compiler.py`
- `flowise_dev_agent/agent/tools.py`
- `flowise_dev_agent/knowledge/provider.py`
- `flowise_dev_agent/knowledge/refresh.py`
- `scripts/simulate_frontend.py`
- `tests/test_compiler_integration.py` — `source_anchor` updated to `"retriever"`

---

## DD-074 — Context Safety Gate + E2E Integration Test (Roadmap 8, M8.3)

**Decision**: A regression test suite (`test_context_safety.py`) asserts that raw
snapshot blobs and large JSON tool payloads never enter the LLM message transcript.
An end-to-end session test (`test_e2e_session.py`) covers the full API lifecycle
against a live server, skipped automatically in CI via `AGENT_E2E_SKIP=1`.

**Problem solved**: No automated gate prevented a future refactor from inadvertently
injecting full snapshot blobs into `state["messages"]`, which would blow the context
window and degrade LLM quality silently.

**Changes**:
- `tests/test_context_safety.py` (11 tests): `result_to_str` contract; no raw JSON
  >500 chars in transcript; `ToolResult.data` never reaches message content.
- `tests/test_e2e_session.py` (6 tests): full session lifecycle — POST /sessions →
  `plan_approval` interrupt → resume → `result_review`; `@pytest.mark.slow`.
- `pyproject.toml`: `[tool.pytest.ini_options]` with `asyncio_mode = "strict"` and
  `slow` marker registration.
- `scripts/simulate_frontend.py`: moved from repo root (tracked in `scripts/`).

**Rejected alternatives**:
- Runtime context-size assertion inside the graph: would add overhead to every
  message and make the test behaviour implicit.
- Blanket truncation of all tool results: loses information that belongs in debug;
  the `result_to_str` / `ToolResult.summary` split is the correct boundary.

**Files**:
- `tests/test_context_safety.py`
- `tests/test_e2e_session.py`
- `pyproject.toml`
- `scripts/simulate_frontend.py`

---

## DD-075 — Knowledge-First Runtime Contract Alignment (Roadmap 9, M9.3)

**Decision**: The discover prompt, discover context, and `get_node` tool description
are rewritten to reflect the local-first schema contract. `get_node` calls during the
discover phase are explicitly discouraged. The Phase D repair loop is extracted into a
standalone `_repair_schema_for_ops()` function with a hard repair budget
(`_MAX_SCHEMA_REPAIRS = 10`).

**Problem solved**: M8.1 improved the prompt language but still retained the
instruction "Call get_node for EVERY node you intend to include." This contradicts
the knowledge-first architecture: Phase D of `_make_patch_node_v2` already resolves
all schemas automatically via `NodeSchemaStore.get_or_repair()` — the LLM does not
need to fetch them during discover. The instruction caused token waste and inconsistent
LLM behaviour (sometimes calling get_node redundantly, sometimes skipping it when
the budget felt high).

**Changes**:
- `_DISCOVER_BASE` (graph.py): "RULE: Call get_node for EVERY node" replaced with
  "NODE SCHEMA CONTRACT (M9.3)": schemas are pre-loaded; patch phase resolves them;
  do NOT call get_node during discover except for unusual parameter verification.
- `_FLOWISE_DISCOVER_CONTEXT` (tools.py): removed "For each node type you plan to
  use, call get_node"; added explicit "Do NOT call get_node during discover" with
  rationale.
- `get_node` tool description in `_FLOWISE_DISCOVER_TOOLS`: split into
  "DISCOVER PHASE: Do NOT call this" / "PATCH PHASE: Call freely" sections.
- `_MAX_SCHEMA_REPAIRS: int = 10` (graph.py): module-level budget constant capping
  targeted API repair calls per patch iteration.
- `_repair_schema_for_ops()` (graph.py): extracted from Phase D of
  `_make_patch_node_v2`; standalone async function; fast path (cache hit = zero API
  calls); slow path (cache miss = one targeted `get_node` call); budget enforced.
- Phase D of `_make_patch_node_v2` now delegates to `_repair_schema_for_ops()`;
  M8.2 `get_node_calls_total` telemetry retained.

**Contract**:
- Local snapshot HIT  → zero API calls (fast path)
- Local snapshot MISS → one targeted `get_node` API call per type (slow/repair path)
- Budget exceeded     → node type skipped with WARNING; AddNode op fails at compile

**Scope note**: A dedicated `repair_schema` LangGraph graph node with routing edges
is deferred to M9.6 (production-grade graph topology). `_repair_schema_for_ops()`
is the canonical repair function that M9.6 will wire as a proper node.

**Rejected alternatives**:
- Removing `get_node` from `_FLOWISE_DISCOVER_TOOLS` entirely: would break the
  legacy path (capabilities=None) where the discover ReAct loop is the only place
  schemas can be fetched before plan writing.
- Adding a new graph node for M9.3: the graph topology redesign is scoped to M9.6;
  adding a node without proper routing edges now would be incomplete.

**Files**:
- `flowise_dev_agent/agent/graph.py` — `_DISCOVER_BASE`, `_MAX_SCHEMA_REPAIRS`,
  `_repair_schema_for_ops()`, Phase D refactor
- `flowise_dev_agent/agent/tools.py` — `_FLOWISE_DISCOVER_CONTEXT`, `get_node` tool def
- `tests/test_m93_knowledge_first.py` — 11 unit tests

---

## DD-076 — NodeSchemaStore Repair Gating Correctness (Roadmap 9, M9.5)

**Decision**: `_compute_action` is refactored into `_compute_action_detail` which
returns both the action string and a structured gating context dict
(`comparison_method`, `decision_reason`, `local_version`, `api_version`, and when
hash comparison is used: `local_hash`, `api_hash`). `_compute_action` becomes a
thin backwards-compatible wrapper. The gating detail is written into every repair
event via `_record_event`, making the decisioning fully observable in
`debug["flowise"]["knowledge_repair_events"]`.

**Decision tree (unchanged from M8.1, now documented and tested more thoroughly)**:
1. Node absent from local index → `update_new_node`
2. Both sides have a non-empty version string:
   - versions equal → `skip_same_version`
   - versions differ → `update_changed_version_or_hash`
3. No complete version pair → hash comparison:
   - hashes equal → `skip_same_version`
   - hashes differ, no version on either side → `update_no_version_info`
   - hashes differ, partial version → `update_changed_version_or_hash`

**Edge cases covered**:
- Integer version (e.g. `2`) normalised to string `"2"` before comparison
- Zero version (`0`) treated as absent (falls to hash path)
- Whitespace-only version treated as absent
- Partial version presence (only one side has version) falls to hash path

**Why detail dict (not just action string)**:
The action alone is not sufficient for post-hoc debugging when a node is
unexpectedly updated or skipped. Including `comparison_method` and
`decision_reason` lets operators scan `knowledge_repair_events` in the session
debug to understand exactly why each schema was or was not refreshed.

**Backwards compatibility**: `_compute_action(node_type, api_raw) -> str` signature
is preserved unchanged. All 5 existing tests in `test_schema_repair_gating.py`
pass without modification.

**Files**:
- `flowise_dev_agent/knowledge/provider.py` — `_compute_action_detail()` (new),
  `_compute_action()` (now delegates), `get_or_repair()` (uses detail)
- `tests/test_m95_repair_gating.py` — 17 tests across three classes:
  `TestActionCorrectness` (5 spec cases + wrapper), `TestGatingDetail` (7 detail
  checks), `TestEdgeCases` (4 normalisation edge cases)

---

## DD-077 — Refresh Reproducibility (Roadmap 9, M9.4)

**Decision**: `FLOWISE_NODE_REFERENCE.md` at the repository root is the single
canonical source for all 303 Flowise node schemas. The refresh CLI is hardened to
fail fast with an actionable error (including a `git checkout` recovery hint) when
this file is absent. The filename is extracted to a named constant
`_CANONICAL_REFERENCE_NAME` so tests can assert the resolved path without
duplicating string literals.

**What already existed before M9.4**:
- `FLOWISE_NODE_REFERENCE.md` at repo root (7 975 lines, 303 nodes)
- `_REFERENCE_MD` path constant pointing at it
- `--dry-run` flag: parses + diffs without writing any files
- Missing-file guard in `refresh_nodes()` returning exit 1

**What M9.4 adds**:
- `_CANONICAL_REFERENCE_NAME = "FLOWISE_NODE_REFERENCE.md"` — explicit named
  constant; `_REFERENCE_MD` is now derived from it so the canonical name can
  never drift from the resolved path.
- Improved missing-file error — includes expected path, reason, and
  `git checkout HEAD -- FLOWISE_NODE_REFERENCE.md` recovery command.
- `tests/test_m94_refresh_reproducibility.py` (13 tests):
  - Constant is a non-empty `.md` string
  - `_REFERENCE_MD` resolves to `_REPO_ROOT / _CANONICAL_REFERENCE_NAME`
  - File exists and is non-empty in a clean checkout
  - Subprocess `--nodes --dry-run` exits 0 and reports node counts
  - Missing file → exit 1 (mock-patched `_REFERENCE_MD`)
  - Missing-file error contains canonical name and a recovery hint
  - `refresh_nodes(dry_run=True)` exits 0 when file is present
  - Dry-run does not create or modify `flowise_nodes.snapshot.json`

**How to run (local / CI gate)**:
```
python -m flowise_dev_agent.knowledge.refresh --nodes --dry-run
```
Exits 0 and prints the diff without writing. Add `--validate` for structural
checks (still no writes).

**Files**:
- `flowise_dev_agent/knowledge/refresh.py` — `_CANONICAL_REFERENCE_NAME`,
  `_REFERENCE_MD` derivation, improved missing-file error
- `tests/test_m94_refresh_reproducibility.py` — 13 tests

---

## DD-078 — Postgres-Only Persistence (Checkpointer + Event Log)

**Roadmap**: ROADMAP9 — Milestone 9.1

**Decision**: Replace the SQLite `AsyncSqliteSaver` checkpointer with a
Postgres-backed `AsyncPostgresSaver` as the single, required persistence backend.
SQLite is no longer a fallback option. The agent fails to start with a clear
error message if `POSTGRES_DSN` is not set.

**Reason**:
- SQLite is a single-file, single-process backend unsuitable for multi-worker
  deployments. Postgres enables resumable sessions under horizontal scaling.
- A Postgres-only path eliminates dual-backend complexity (no toggle, no
  fallback code paths, no conditional SQL dialects).
- Durable audit trails (event replay, session history) require a proper
  relational backend.
- The `session_events` table (node lifecycle events) is the foundation for
  M9.2 SSE streaming observability.
- Local development is straightforward: `docker compose -f docker-compose.postgres.yml up -d`.

**What was replaced**:
- `from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver` in api.py
- Direct `checkpointer.conn.execute(...)` SQLite-specific queries in
  `list_sessions` and `delete_session` endpoints.
- `SESSIONS_DB_PATH` env var (replaced by `POSTGRES_DSN`).

**New components**:

`flowise_dev_agent/persistence/checkpointer.py`:
- `make_checkpointer(dsn)` — async context manager that wraps `AsyncPostgresSaver`
  and calls `.setup()` to create LangGraph checkpoint tables on first use.
- `CheckpointerAdapter` — wraps `AsyncPostgresSaver` with two helper methods:
  - `list_thread_ids() -> list[str]` — replaces raw SQLite `.conn.execute()`
  - `thread_exists(thread_id) -> bool` — replaces raw SQLite `.conn.execute()`
  - All LangGraph methods delegated transparently via `__getattr__`.

`flowise_dev_agent/persistence/event_log.py`:
- `EventLog(dsn)` — owns a separate `psycopg.AsyncConnection`.
- `setup()` creates `session_events` table if absent (DDL is idempotent).
- `insert_event(session_id, node_name, phase, status, ...)` — fire-and-forget
  insert; errors are logged and never raised.
- `get_events(session_id, after_seq, limit)` — used by M9.2 SSE endpoint.
- `seq` uses `time.time_ns()` — monotonically increasing BIGINT without a
  DB round-trip for sequence generation.

`docker-compose.postgres.yml`:
- Postgres 16, `postgres/postgres`, database `flowise_dev_agent`, port 5432.
- Health check via `pg_isready`.

**Env vars**:
- `POSTGRES_DSN` — required; e.g. `postgresql://postgres:postgres@localhost:5432/flowise_dev_agent`

**Rejected alternatives**:
- SQLite + Postgres toggle with env var: adds two code paths for every
  query and makes tests environment-dependent. Not worth the complexity.
- Async SQLAlchemy ORM: heavyweight for an event-log table; raw psycopg is
  faster and simpler.
- Using the LangGraph checkpointer connection for the event log: the
  checkpointer's connection lifecycle is managed by LangGraph internals;
  sharing it is fragile. A dedicated EventLog connection is safer.

**Files**:
- `docker-compose.postgres.yml` — Postgres 16 local service
- `flowise_dev_agent/persistence/__init__.py` — package exports
- `flowise_dev_agent/persistence/checkpointer.py` — factory + adapter
- `flowise_dev_agent/persistence/event_log.py` — session_events helper
- `flowise_dev_agent/api.py` — lifespan updated; SQLite-specific queries replaced
- `pyproject.toml` — added `langgraph-checkpoint-postgres>=2.0`, `psycopg[binary]>=3.1`
- `tests/test_m91_postgres_persistence.py` — 13 tests (all mocked; no live DB required)


---

## DD-079 — Node-Level SSE Streaming (Event Log → GET /sessions/{id}/stream)

**Roadmap**: ROADMAP9 — Milestone 9.2

**Decision**: Add a `GET /sessions/{session_id}/stream` SSE endpoint that replays
persisted `session_events` rows and then tails for new ones via polling.  Node
lifecycle events (started / completed / failed / interrupted) are emitted by
wrapping every LangGraph node in `build_graph` with a thin `wrap_node` decorator
from `flowise_dev_agent/persistence/hooks.py`.

**Why this approach**:
- **Replay-first**: because events are persisted before being streamed, a client
  that reconnects receives all prior events from `after_seq=0` without any
  server-side fan-out or in-memory buffer.
- **No token streaming**: the endpoint only emits node lifecycle events, never
  LLM tokens or raw tool payloads.  This keeps event payloads small and
  independent of the existing `POST /sessions/stream` token-streaming endpoint.
- **Decoupled from graph execution**: nodes emit events via `EventLog.insert_event`
  (fire-and-forget); the SSE endpoint polls independently.  A slow SSE client
  never blocks graph execution.
- **wrap_node as a decorator**: wrapping at `build_graph` call-site means no
  node internals are modified.  `emit_event=None` (default) is a zero-cost no-op
  pass-through — all existing graph tests continue to use unwrapped nodes.

**What was added**:

`flowise_dev_agent/persistence/hooks.py` (new):
- `_NODE_PHASES` — maps node name → logical phase label (e.g. `"plan"`, `"patch"`).
- `_node_summary(node_name, result)` — extracts a compact (≤200 char) summary from
  a node result dict without including raw blobs.
- `wrap_node(node_name, fn, emit_event)` — wraps an async LangGraph node:
  - accepts `(state, config: Optional[RunnableConfig] = None)` so LangGraph passes
    the thread_id via config, giving us `session_id` without touching node internals.
  - emits `started` before calling fn.
  - emits `completed` / `failed` / `interrupted` after fn returns or raises.
  - always re-raises exceptions so graph routing is unaffected.
  - uses exception class name matching (`GraphInterrupt`, `NodeInterrupt`) to
    distinguish HITL interrupts from real failures without a hard import on
    LangGraph internals.

`flowise_dev_agent/agent/graph.py`:
- `build_graph` gains `emit_event=None` parameter.
- A `_w(name, fn)` helper in `build_graph` wraps each node via `wrap_node` only
  when `emit_event` is not None.  Zero overhead when omitted.

`flowise_dev_agent/api.py`:
- `_format_event_as_sse(event, session_id)` — formats a `session_events` row as
  RFC 8725 SSE: `event: <type>\ndata: <json>\n\n`.  `payload_json` column is
  intentionally excluded (no blob leakage).
- `_session_is_done(graph, session_id)` — checks `snapshot.values["done"]`.
- `GET /sessions/{session_id}/stream` — replay + poll SSE endpoint:
  - validates session exists before opening stream.
  - polls every `SSE_POLL_INTERVAL` seconds (default 2s, configurable via env var).
  - emits keepalive comments every `SSE_KEEPALIVE_AFTER` empty polls (default 15).
  - checks `done` flag every 5 polls (avoids Postgres round-trip on every tick).
  - emits `event: done` and closes when session completes.
  - respects `request.is_disconnected()` for early client exit.
  - supports `?after_seq=N` query param for resumable streaming.
- `build_graph` call in lifespan wired with `emit_event=event_log.insert_event`.

**SSE event types**:

| event:        | status emitted | when                          |
|---------------|----------------|-------------------------------|
| `node_start`  | `started`      | node function begins          |
| `node_end`    | `completed`    | node function returns         |
| `node_error`  | `failed`       | node function raises (non-interrupt) |
| `interrupt`   | `interrupted`  | node raises GraphInterrupt    |
| `done`        | —              | session `done=True`           |

**Rejected alternatives**:
- Postgres LISTEN/NOTIFY for push-based delivery: correct long-term approach but
  adds connection management complexity.  Polling at 2s is sufficient for M9.2
  and can be replaced later without changing the SSE contract.
- WebSockets: more capable but higher client complexity; SSE is sufficient for
  one-way server→client event streaming.
- In-memory fan-out queue: breaks replay on reconnect; not resumable.

**Files**:
- `flowise_dev_agent/persistence/hooks.py` — new: wrap_node + _node_summary
- `flowise_dev_agent/persistence/__init__.py` — wrap_node export added
- `flowise_dev_agent/agent/graph.py` — emit_event param + _w() wrapper helper
- `flowise_dev_agent/api.py` — SSE endpoint + helpers + lifespan wiring
- `tests/test_m92_sse_streaming.py` — 27 tests


---

## DD-080 — Production-Grade LangGraph Topology v2 (CREATE + UPDATE, Budgets, Bounded Retries)

**Roadmap**: ROADMAP9 — Milestone 9.6

**Decision**: Replace the original 9-node topology with an 18-node v2 topology that
supports both CREATE and UPDATE modes, enforces graph-level budgets and bounded
schema-repair retries, keeps full flow JSON out of LLM prompts (compact context
via summaries), and integrates with the M9.2 SSE streaming layer.

**Why this approach**:
- **CREATE vs UPDATE split**: production usage requires modifying existing chatflows
  by name rather than always building from scratch. A single canonical graph handles
  both modes with Phase B and Phase C skipped entirely for CREATE.
- **Full-flow isolation**: `load_current_flow` stores `artifacts["flowise"]["current_flow_data"]`
  (full JSON) and `summarize_current_flow` produces `facts["flowise"]["flow_summary"]`
  (compact dict). Only the summary ever reaches LLM prompts — no blob leakage.
- **Graph-level budgets via `facts["budgets"]`**: `max_patch_ops_per_iter`,
  `max_schema_repairs_per_iter`, `max_total_retries_per_iter`. Enforced by
  `preflight_validate_patch` — budget overage routes to HITL rather than silently failing.
- **Bounded schema-repair loop**: schema mismatch → `repair_schema` → retry
  `compile_patch_ir` exactly once. A second mismatch routes to HITL immediately.
- **v1 code fully removed**: `_make_clarify_node`, `_make_discover_node`,
  `_make_check_credentials_node`, `_make_patch_node`, `_make_patch_node_v2`,
  `_make_converge_node` and related routing functions removed.  `build_graph()`
  calls `_build_graph_v2()` directly — no `topology_version` parameter.
- **SSE integration**: `_w2()` helper inside `_build_graph_v2()` wraps all 18 nodes
  with `wrap_node` when `emit_event` is provided, matching the M9.2 pattern.

**18 node set (v2)**:

| Phase | Nodes |
|-------|-------|
| A: Intent + context | `classify_intent`, `hydrate_context` |
| B: Target resolution (UPDATE only) | `resolve_target`, `hitl_select_target` |
| C: Flow baseline load (UPDATE only) | `load_current_flow`, `summarize_current_flow` |
| D: Plan + patch generation | `plan_v2`, `hitl_plan_v2`, `define_patch_scope`, `compile_patch_ir`, `compile_flow_data` |
| E: Validation + repair | `validate`, `repair_schema` |
| F: Apply + test + review | `preflight_validate_patch`, `apply_patch`, `test_v2`, `evaluate`, `hitl_review_v2` |

**New state fields** (added to `AgentState`):
- `operation_mode: str | None` — `"create"` | `"update"` | `None` (set by `classify_intent`)
- `target_chatflow_id: str | None` — chosen chatflow for UPDATE (set by `hitl_select_target`)
- `intent_confidence: float | None` — informational only; not used for routing

**Rejected alternatives**:
- Keeping a `topology_version` toggle: adds dead code, complicates tests, and
  confuses contributors. v2 is the only topology; the toggle was removed.
- Streaming full flow JSON to the LLM for UPDATE mode: prohibitive token cost
  (typical chatflows 5–50 KB) and unnecessary given that the plan only needs
  a structural summary for most edits.
- Automatic schema repair without HITL: unbounded repair loops previously caused
  runaway LLM calls; the single-retry + HITL fallback gives correctness guarantees.

**Files**:
- `flowise_dev_agent/agent/graph.py` — 18 node factory functions, `_build_graph_v2()`,
  `_summarize_flow_data()`, `_repair_schema_local_sync()`, `_w2()` wrapper helper
- `flowise_dev_agent/agent/state.py` — `operation_mode`, `target_chatflow_id`, `intent_confidence`
- `flowise_dev_agent/api.py` — `_initial_state()` includes M9.6 fields; `_NODE_PROGRESS`
  updated to v2 node names only
- `flowise_dev_agent/persistence/hooks.py` — `_NODE_PHASES` and `_node_summary` rewritten
  for all 18 v2 node names
- `tests/test_m96_topology_v2.py` — 13 tests


---

## DD-081 — PatternCapability Maturity (Schema Compat + Category Inference + Metrics)

**Roadmap**: ROADMAP9 — Milestone 9.9

**Decision**: Harden the pattern library with schema-compatibility gating, automatic
category inference from node types, `last_used_at` tracking, and per-session
pattern usage metrics — without introducing a separate `PatternCapability` class
(inline plan node handling is sufficient at this scale).

**Why this approach**:
- **Schema-compatibility guard (`_is_pattern_schema_compatible`)**: patterns saved
  under a different node schema snapshot are silently skipped rather than applied
  and later failing during compile. Fingerprint match = compatible; no fingerprint
  = treat as compatible (backwards compat with older patterns).
- **Category inference (`_infer_category_from_node_types`)**: automatically assigns
  `"rag"` / `"tool_agent"` / `"conversational"` / `"custom"` from the node type
  list rather than relying on the LLM to supply the correct category string.
  Priority order (first match wins): vectorStore/retriev → toolAgent → chatOpenAI
  + conversationChain → custom.
- **UPDATE mode guard**: patterns are NOT applied as base graph when
  `operation_mode == "update"`. Applying a pre-built pattern as the baseline for
  an UPDATE would overwrite the existing flow. The guard ensures pattern seeding
  only accelerates CREATE sessions.
- **`last_used_at` tracking**: `search_patterns_filtered()` returns ISO-8601
  timestamps for `last_used_at`, enabling future least-recently-used eviction
  and usage analytics.
- **`pattern_metrics` in debug**: every plan node execution emits
  `debug["flowise"]["pattern_metrics"]` = `{pattern_used, pattern_id, ops_in_base}`.
  Visible in session debug output without adding API surface area.

**New state fields** (added to `AgentState`):
- `pattern_used: bool` — `True` when a pattern was used as base GraphIR for the
  current plan iteration; `False` otherwise.
- `pattern_id: int | None` — `PatternStore` row ID of the applied pattern, or
  `None` if no pattern was seeded.

**Rejected alternatives**:
- A separate `PatternCapability(DomainCapability)` class: the pattern logic is
  tightly coupled to the plan node (it seeds the base GraphIR that compile_patch_ir
  uses). Extracting it would require passing the GraphIR through the domain
  capability interface, adding complexity without benefit at current scale.
- Hard-fail on schema mismatch: skipping incompatible patterns is safer — the plan
  node falls back to an empty baseline and the LLM generates ops from scratch.

**Files**:
- `flowise_dev_agent/agent/pattern_store.py` — `_is_pattern_schema_compatible()`,
  `_infer_category_from_node_types()`, `last_used_at` in `search_patterns_filtered()`
  result dicts
- `flowise_dev_agent/agent/graph.py` — UPDATE mode guard in plan node;
  `pattern_metrics` emitted to `debug["flowise"]`; `pattern_used` + `pattern_id`
  written to state
- `flowise_dev_agent/agent/state.py` — `pattern_used`, `pattern_id` fields
- `flowise_dev_agent/api.py` — `_initial_state()` includes `pattern_used: False`,
  `pattern_id: None`
- `tests/test_m99_pattern_tuning.py` — 5 tests
