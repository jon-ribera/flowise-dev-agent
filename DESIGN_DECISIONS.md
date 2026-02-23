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
