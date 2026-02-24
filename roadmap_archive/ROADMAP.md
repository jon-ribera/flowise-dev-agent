# Flowise Dev Agent — Product Roadmap

Prioritized enhancement backlog for the Flowise Development Agent.
Continue implementation in the `flowise-dev-agent` repo.

---

## Priority Matrix

| Enhancement | Pillar | Impact | Effort | Priority |
|---|---|---|---|---|
| SQLite persistence | Reliability | Critical | 1 day | **Do next** |
| Streaming SSE output | DX | High | 2 days | **Do next** |
| Chatflow snapshot/rollback | Reliability | High | 1 day | **Do next** |
| Upsert-before-query RAG skill | Patterns | High | 2 hours | **Do next** |
| CLI wrapper | DX | High | 2 days | High |
| LangSmith integration | Observability | High | 2 hours | High |
| Session browser API | DX | Medium | 1 day | Medium |
| API key auth | Security | High | 2 hours | Medium |
| OpenAI Assistant skill | Patterns | Medium | 4 hours | Medium |
| Custom tool creation skill | Patterns | Medium | 4 hours | Medium |
| Token budget in response | Observability | Low | 2 hours | Low |
| Pattern library | Self-improve | High | 3 days | Future |
| Multiple Flowise instances | Multi-tenant | Medium | 1 day | Future |

---

## Key Files

```
flowise_dev_agent/
├── api.py                    ← FastAPI server (sessions, resume, health)
├── reasoning.py              ← ReasoningEngine ABC + ClaudeEngine + OpenAIEngine
├── agent/
│   ├── graph.py              ← LangGraph 8-node state machine (main orchestration)
│   ├── state.py              ← AgentState TypedDict
│   ├── tools.py              ← DomainTools, FloviseDomain, validate_flow_data
│   └── skills.py             ← Skill file loader
└── skills/
    ├── flowise_builder.md    ← 10 rules for Flowise chatflow construction
    └── workday_extend.md     ← Placeholder for Workday v2
```

---

## DO NEXT — Detailed Implementation Plans

---

### 1. SQLite Persistence

**Goal**: Sessions survive server restarts. Required before any production use.

**Files to change**: `flowise_dev_agent/api.py`

**Current state** (`api.py` lifespan):
```python
graph, client = create_agent(settings, reasoning_settings)
```

**Implementation**:

In `flowise_dev_agent/agent/graph.py`, `build_graph()` already accepts a `checkpointer=` parameter and defaults to `MemorySaver`. No changes needed there.

In `flowise_dev_agent/api.py`, update the lifespan to use `SqliteSaver`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    from dotenv import load_dotenv
    load_dotenv()

    from flowise_dev_agent.agent import create_agent
    from flowise_dev_agent.agent.graph import build_graph, create_engine
    from flowise_dev_agent.agent.tools import FloviseDomain
    from cursorwise.client import FlowiseClient
    from cursorwise.config import Settings
    from flowise_dev_agent.reasoning import ReasoningSettings
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    settings = Settings.from_env()
    reasoning_settings = ReasoningSettings.from_env()

    db_path = os.getenv("SESSIONS_DB_PATH", "sessions.db")

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        engine = create_engine(reasoning_settings)
        client = FlowiseClient(settings)
        domains = [FloviseDomain(client)]
        graph = build_graph(engine, domains, checkpointer=checkpointer)

        app.state.graph = graph
        app.state.client = client

        yield

    await client.close()
```

Add `import os` at the top of `api.py`.

Add to `pyproject.toml` dependencies:
```toml
"langgraph-checkpoint-sqlite>=2.0",
```

Add to `.env.example`:
```bash
# Path to SQLite database for session persistence (default: sessions.db)
SESSIONS_DB_PATH=sessions.db
```

Add to `DESIGN_DECISIONS.md` as **DD-024**.

---

### 2. Streaming SSE Output

**Goal**: Surface live progress tokens during the 30–60s Discover and Patch phases.
Currently the client waits in silence until the full phase completes.

**Files to change**: `flowise_dev_agent/api.py`

**New endpoint** — add alongside existing routes:

```python
from fastapi.responses import StreamingResponse
import asyncio
import json as _json

@app.post("/sessions/{thread_id}/stream", tags=["sessions"])
async def stream_session(thread_id: str, body: ResumeSessionRequest, request: Request):
    """Resume a session and stream progress as Server-Sent Events.

    Each SSE event has one of these types:
      data: {"type": "token", "content": "..."}       ← LLM output token
      data: {"type": "tool_call", "name": "..."}      ← tool being called
      data: {"type": "tool_result", "name": "...", "preview": "..."} ← result summary
      data: {"type": "interrupt", ...}                ← HITL interrupt reached
      data: {"type": "done", "thread_id": "..."}      ← session completed
      data: {"type": "error", "detail": "..."}        ← error occurred
    """
    from langgraph.types import Command

    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    async def event_stream():
        try:
            async for event in graph.astream_events(
                Command(resume=body.response), config=config, version="v2"
            ):
                kind = event.get("event")
                data = event.get("data", {})

                if kind == "on_chat_model_stream":
                    chunk = data.get("chunk", {})
                    content = getattr(chunk, "content", "") or ""
                    if content:
                        yield f"data: {_json.dumps({'type': 'tool_call', 'content': content})}\n\n"

                elif kind == "on_tool_start":
                    yield f"data: {_json.dumps({'type': 'tool_call', 'name': event.get('name', '')})}\n\n"

                elif kind == "on_tool_end":
                    output = str(data.get("output", ""))[:200]
                    yield f"data: {_json.dumps({'type': 'tool_result', 'name': event.get('name', ''), 'preview': output})}\n\n"

            # After stream ends, check for interrupt or completion
            response = _build_response(graph, config, thread_id)
            if response.status == "pending_interrupt":
                yield f"data: {_json.dumps({'type': 'interrupt', **response.interrupt.model_dump()})}\n\n"
            else:
                yield f"data: {_json.dumps({'type': 'done', 'thread_id': thread_id})}\n\n"

        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

Also add a streaming variant for `POST /sessions` (new session start):

```python
@app.post("/sessions/stream", tags=["sessions"])
async def stream_create_session(body: StartSessionRequest, request: Request):
    """Start a new session and stream progress as SSE."""
    graph = _get_graph(request)
    thread_id = body.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    async def event_stream():
        # ... same pattern as above but with _initial_state as input
        async for event in graph.astream_events(
            _initial_state(body.requirement, body.test_trials),
            config=config, version="v2"
        ):
            # ... same event routing
            pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

**Client usage example**:
```bash
curl -N -X POST http://localhost:8000/sessions/uuid-.../stream \
  -H "Content-Type: application/json" \
  -d '{"response": "approved"}'
```

Add to `DESIGN_DECISIONS.md` as **DD-025**.

---

### 3. Chatflow Snapshot / Rollback

**Goal**: Before every Patch, save the current chatflow flowData to a snapshot store.
If a patch breaks the flow, the developer can rollback to the last good state.

**Files to change**: `flowise_dev_agent/agent/tools.py`, `flowise_dev_agent/api.py`

**New tool** — add to `flowise_dev_agent/agent/tools.py`:

```python
# In-memory snapshot store (replace with SQLite in production)
_snapshots: dict[str, list[dict]] = {}

async def _snapshot_chatflow(client: FlowiseClient, chatflow_id: str, session_id: str) -> dict:
    """Save current chatflow state as a snapshot before patching."""
    chatflow = await client.get_chatflow(chatflow_id)
    if "error" in chatflow:
        return chatflow

    snap = {
        "chatflow_id": chatflow_id,
        "name": chatflow.get("name"),
        "flow_data": chatflow.get("flowData", ""),
        "timestamp": __import__("time").time(),
    }
    _snapshots.setdefault(session_id, []).append(snap)
    return {"snapshotted": True, "snapshot_count": len(_snapshots[session_id])}


async def _rollback_chatflow(client: FlowiseClient, chatflow_id: str, session_id: str) -> dict:
    """Restore last snapshot for a chatflow."""
    snaps = _snapshots.get(session_id, [])
    if not snaps:
        return {"error": "No snapshots found for this session"}

    snap = snaps[-1]
    return await client.update_chatflow(
        chatflow_id=chatflow_id,
        flow_data=snap["flow_data"],
    )
```

**Add to executor** in `_make_flowise_executor()`:
```python
"snapshot_chatflow": lambda chatflow_id, session_id: _snapshot_chatflow(client, chatflow_id, session_id),
"rollback_chatflow": lambda chatflow_id, session_id: _rollback_chatflow(client, chatflow_id, session_id),
```

**Add to `_FLOWISE_PATCH_TOOLS`**:
```python
_td(
    "snapshot_chatflow",
    "Save the current chatflow state as a snapshot before making changes. "
    "Call this before every update_chatflow so rollback is available if the patch breaks the flow.",
    {"chatflow_id": {"type": "string"}, "session_id": {"type": "string"}},
    ["chatflow_id", "session_id"],
),
```

**New API endpoint** in `api.py`:
```python
@app.post("/sessions/{thread_id}/rollback", tags=["sessions"])
async def rollback_session(thread_id: str, request: Request):
    """Rollback the chatflow to the last snapshot taken during this session."""
    # ... call rollback_chatflow tool with thread_id as session_id
```

Add to `DESIGN_DECISIONS.md` as **DD-026**.

---

### 4. Upsert-Before-Query RAG Skill

**Goal**: Add Rule 11 to `flowise_builder.md` covering the upsert-before-query pattern
for RAG chatflows. This is a 2-hour skill file update, no Python changes.

**File to change**: `flowise_dev_agent/skills/flowise_builder.md`

**Add after Rule 10**:

````markdown
### Rule 11: RAG — Upsert Before Query

For any RAG flow with a VectorStore, always upsert documents BEFORE testing predictions.
A new VectorStore is empty — queries return empty results until data is loaded.

**Upsert pattern**:
1. After creating the chatflow, call `upsert_vector(chatflow_id)` to load documents
2. Verify upsert succeeded (check response for document count)
3. Then run `create_prediction` to test retrieval

**When to upsert**:
- After creating a new RAG chatflow
- After changing the DocumentLoader source URL/file
- After changing chunk size or embeddings model
- Any time you suspect the vector store is stale

**Tool**: `upsert_vector(chatflow_id)` — already in the FlowiseClient.
Add it to the patch executor and test tools as needed.

**Error pattern**:
- `"No vector node found"` → the chatflow has no VectorStore node (wrong flow type)
- Empty prediction response after upsert → check embeddings model credential binding
````

Also add `upsert_vector` to `_FLOWISE_TEST_TOOLS` in `tools.py`:

```python
_td(
    "upsert_vector",
    "Load documents into the vector store for RAG chatflows. "
    "REQUIRED before testing any RAG flow — the vector store is empty until upserted.",
    {"chatflow_id": {"type": "string"}},
    ["chatflow_id"],
),
```

And to the executor:
```python
"upsert_vector": client.upsert_vector,
```

---

## HIGH PRIORITY

---

### 5. CLI Wrapper

**Goal**: `flowise-agent build "requirement"` runs the full loop interactively in the terminal.
No HTTP client or curl needed for solo developer use.

**New file**: `flowise_dev_agent/cli.py`

```python
"""Interactive CLI wrapper for the Flowise Dev Agent.

Usage:
    flowise-agent build "Build a customer support chatbot with GPT-4o"
    flowise-agent build "requirement" --trials 2
    flowise-agent resume <thread_id>
    flowise-agent status <thread_id>
"""

import asyncio
import sys
import argparse
from uuid import uuid4

async def _run_session(requirement: str, trials: int = 1):
    """Run an interactive build session in the terminal."""
    from dotenv import load_dotenv
    load_dotenv()

    from flowise_dev_agent.agent import create_agent
    from flowise_dev_agent.agent.graph import build_graph, create_engine
    from flowise_dev_agent.agent.tools import FloviseDomain
    from cursorwise.client import FlowiseClient
    from cursorwise.config import Settings
    from flowise_dev_agent.reasoning import ReasoningSettings
    from flowise_dev_agent.api import _initial_state
    from langgraph.types import Command

    settings = Settings.from_env()
    reasoning_settings = ReasoningSettings.from_env()
    graph, client = create_agent(settings, reasoning_settings)

    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print(f"\nSession: {thread_id}")
    print(f"Building: {requirement}\n")

    try:
        # Start the session
        await graph.ainvoke(_initial_state(requirement, trials), config=config)

        while True:
            snapshot = graph.get_state(config)
            interrupts = [
                intr.value
                for task in snapshot.tasks
                for intr in getattr(task, "interrupts", [])
            ]

            if not interrupts:
                print("\nSession complete.")
                break

            raw = interrupts[0]
            interrupt_type = raw.get("type", "unknown")

            print(f"\n{'='*60}")
            print(f"CHECKPOINT: {interrupt_type.upper()}")
            print('='*60)

            if interrupt_type == "plan_approval":
                print("\nPLAN:\n")
                print(raw.get("plan", ""))
                print(f"\n{raw.get('prompt', '')}")
                response = input("\nYour response: ").strip()

            elif interrupt_type == "result_review":
                print("\nTEST RESULTS:\n")
                print(raw.get("test_results", ""))
                print(f"\n{raw.get('prompt', '')}")
                response = input("\nYour response: ").strip()

            elif interrupt_type == "credential_check":
                print(f"\n{raw.get('prompt', '')}")
                response = input("\nYour response: ").strip()

            else:
                print(f"Unknown interrupt: {raw}")
                response = input("Response: ").strip()

            await graph.ainvoke(Command(resume=response), config=config)

    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(prog="flowise-agent")
    sub = parser.add_subparsers(dest="command")

    build_p = sub.add_parser("build", help="Build a new chatflow")
    build_p.add_argument("requirement", help="What to build")
    build_p.add_argument("--trials", type=int, default=1, help="Test reliability trials (pass^k)")

    args = parser.parse_args()

    if args.command == "build":
        asyncio.run(_run_session(args.requirement, args.trials))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

**Register in `pyproject.toml`**:
```toml
[project.scripts]
flowise-agent     = "flowise_dev_agent.api:serve"
flowise-agent-cli = "flowise_dev_agent.cli:main"
```

Or replace the HTTP entry point with a unified CLI that has both `build` and `serve` subcommands.

---

### 6. LangSmith Integration

**Goal**: Add distributed tracing so you can see every LLM call, tool call, and token
count for each session. 2-hour change — purely additive.

**Files to change**: `flowise_dev_agent/api.py`, `.env.example`

**Implementation** — add to lifespan in `api.py`:

```python
# In lifespan, before creating graph:
langsmith_key = os.getenv("LANGCHAIN_API_KEY")
if langsmith_key:
    import os
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "flowise-dev-agent")
    logger.info("LangSmith tracing enabled: project=%s", os.environ["LANGCHAIN_PROJECT"])
```

**Add to `.env.example`**:
```bash
# -----------------------------------------------------------------------------
# LangSmith Observability (optional — https://smith.langchain.com)
# -----------------------------------------------------------------------------
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=flowise-dev-agent
```

**Add to `pyproject.toml`** optional extras:
```toml
[project.optional-dependencies]
langsmith = ["langsmith>=0.1"]
```

No other code changes needed — LangGraph auto-instruments when `LANGCHAIN_TRACING_V2=true`.

Add to `DESIGN_DECISIONS.md` as **DD-027**.

---

## MEDIUM PRIORITY

---

### 7. Session Browser API

**Goal**: List all sessions, filter by status, get session history.

**New endpoints** in `api.py`:

```python
@app.get("/sessions", tags=["sessions"])
async def list_sessions(request: Request, status: str | None = None) -> list[dict]:
    """List all sessions. Requires SQLite persistence (DD-024)."""
    graph = _get_graph(request)
    # Use graph.get_state_history() or query SQLite directly
    # Returns: [{"thread_id": "...", "status": "...", "iteration": N, "chatflow_id": "..."}]
    ...

@app.delete("/sessions/{thread_id}", tags=["sessions"])
async def delete_session(thread_id: str, request: Request):
    """Delete a session and its checkpointed state."""
    ...
```

Requires SQLite persistence (item 1) to be implemented first.

---

### 8. API Key Authentication

**Goal**: Protect the API with a Bearer token so it can be exposed outside localhost.

**Files to change**: `flowise_dev_agent/api.py`

**Implementation** — add FastAPI dependency:

```python
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)

def _verify_api_key(credentials: HTTPAuthorizationCredentials | None = Security(security)):
    """Verify Bearer token matches AGENT_API_KEY env var."""
    api_key = os.getenv("AGENT_API_KEY")
    if not api_key:
        return  # No key configured = open access (dev mode)
    if not credentials or credentials.credentials != api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
```

Add `dependencies=[Depends(_verify_api_key)]` to each route decorator.

**Add to `.env.example`**:
```bash
# API key for authenticating requests (leave empty for open access in dev)
AGENT_API_KEY=
```

Add to `DESIGN_DECISIONS.md` as **DD-028**.

---

### 9. OpenAI Assistant Skill (Rule 12)

**Goal**: Add Rule 12 to `flowise_builder.md` for the OpenAI Assistant node pattern.
This is a skill file update — no Python changes.

**Add to `flowise_dev_agent/skills/flowise_builder.md`** after Rule 11:

````markdown
### Rule 12: OpenAI Assistant Node

The `openAIAssistant` node wraps the OpenAI Assistants API. It requires:
- `details` field MUST be a JSON string, not a nested object:
  ```json
  {"details": "{\"assistantId\": \"asst_...\"}"}
  ```
  Sending `details` as a dict causes `"[object Object]" is not valid JSON`.
- The assistant must already exist in your OpenAI account.
  Use `get_node("openAIAssistant")` to see the exact `inputs` schema.
- Credential: `openAIApi` — bind at BOTH `data.credential` AND `data.inputs.credential`.

**When to use**: The requirement explicitly asks for OpenAI Assistants (file search,
code interpreter, or pre-configured assistant personality). For general conversation,
use `conversationChain` + `chatOpenAI` instead (simpler, cheaper).
````

---

### 10. Custom Tool Creation Skill (Rule 13)

**Goal**: Add Rule 13 to `flowise_builder.md` for the Custom Tool node pattern.

**Add to `flowise_dev_agent/skills/flowise_builder.md`** after Rule 12:

````markdown
### Rule 13: Custom Tool Node

Custom tools let agents call external APIs. Required fields:
- `color`: MUST be a hex color string (e.g. `"#4CAF50"`).
  Missing color causes `NOT NULL constraint failed: tool.color` (HTTP 500).
- `schema`: JSON Schema string describing the tool's input parameters.
- `func`: JavaScript function body that calls the external API.

**Example node data**:
```json
{
  "name": "getWeather",
  "description": "Get current weather for a city",
  "color": "#4CAF50",
  "schema": "{\"type\":\"object\",\"properties\":{\"city\":{\"type\":\"string\"}},\"required\":[\"city\"]}",
  "func": "const resp = await fetch(`https://api.weather.com/v1/${city}`); return resp.json();"
}
```

Call `get_node("customTool")` to verify exact schema before building.
````

---

### 11. Token Budget in Response

**Goal**: Return token counts in `SessionResponse` so callers can track cost/usage.

**Files to change**: `flowise_dev_agent/api.py`, `flowise_dev_agent/reasoning.py`

**Add to `EngineResponse`** in `reasoning.py`:
```python
@dataclass
class EngineResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    input_tokens: int = 0    # ← add
    output_tokens: int = 0   # ← add
```

**Populate in `ClaudeEngine.complete()`**:
```python
return EngineResponse(
    content=content_text,
    tool_calls=tool_calls,
    stop_reason=response.stop_reason or "end_turn",
    input_tokens=response.usage.input_tokens,
    output_tokens=response.usage.output_tokens,
)
```

**Add to `AgentState`** in `state.py`:
```python
total_input_tokens: int    # accumulated across all LLM calls
total_output_tokens: int
```

**Add to `SessionResponse`** in `api.py`:
```python
total_input_tokens: int = Field(0, description="Total input tokens consumed by this session.")
total_output_tokens: int = Field(0, description="Total output tokens generated by this session.")
```

---

## FUTURE

---

### 12. Pattern Library (Self-Improvement)

**Goal**: The agent learns from successful sessions. After each `DONE` verdict,
extract the flowData pattern and store it in a searchable pattern library.
Future Discover phases can query the library before calling Flowise APIs.

**Architecture**:
- SQLite table: `patterns (id, name, requirement_keywords, flow_data, created_at, success_count)`
- New tool: `search_patterns(keywords)` — returns top-3 matching patterns
- New tool: `save_pattern(name, flow_data)` — called by converge node after DONE
- Skill update: add pattern search to Discover phase rules

**Scope**: 3 days. Requires SQLite persistence (item 1) first.

---

### 13. Multiple Flowise Instances

**Goal**: Route different sessions to different Flowise instances (dev/staging/prod,
or different customer tenants).

**Architecture**:
- Add `flowise_instance_id` to `StartSessionRequest`
- Maintain a `FlowiseClient` pool keyed by instance ID
- Read instance configs from `FLOWISE_INSTANCES` env var (JSON array) or a config file

**Scope**: 1 day. Requires SQLite persistence (item 1) and API key auth (item 8) first.

---

## Implementation Order (Recommended)

```
Week 1:  SQLite persistence (1) + Upsert RAG skill (4) + LangSmith (6)
Week 2:  Streaming SSE (2) + CLI wrapper (5)
Week 3:  Snapshot/rollback (3) + API key auth (8) + OpenAI/Custom tool skills (9, 10)
Week 4:  Session browser API (7) + Token budget (11)
Future:  Pattern library (12) + Multi-tenant (13)
```

---

## Adding a New Design Decision

When implementing any item above, add a `DD-0XX` entry to `DESIGN_DECISIONS.md`
following the existing format:

```markdown
### DD-0XX — <Title>
**Date**: YYYY-MM-DD
**Decision**: ...
**Reason**: ...
**Rejected alternatives**: ...
```

Next available DD number: **DD-024**
