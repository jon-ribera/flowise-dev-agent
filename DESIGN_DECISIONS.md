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
