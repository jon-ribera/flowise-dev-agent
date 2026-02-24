# Flowise Dev Agent — Product Roadmap 2

Next-wave enhancement backlog following completion of ROADMAP.md (DD-024 – DD-032).
Continue implementation in the `flowise-dev-agent` repo on branch `feat/roadmap2`.

---

## Priority Matrix

| Enhancement | Pillar | Impact | Effort | Priority |
|---|---|---|---|---|
| Requirement clarification node | Quality | Critical | 1 day | **Do next** |
| Session export / audit trail | DX | High | 2 hours | **Do next** |
| Discover response caching | Cost | High | 4 hours | **Do next** |
| Rate limiting | Security | High | 2 hours | **Do next** |
| Webhook callbacks (HITL) | DX | High | 2 days | High |
| Error recovery playbook | Quality | High | 2 days | High |
| Chatflow version tags | Reliability | High | 2 days | High |
| Parallel test execution | Performance | Medium | 1 day | High |
| GitHub chatflow export | Integration | Medium | 2 days | Future |
| Slack / Teams notifications | DX | Medium | 1 day | Future |
| Per-key token quotas | Security | Medium | 1 day | Future |
| Session analytics endpoint | Observability | Medium | 1 day | Future |
| Requirement similarity dedup | Quality | Low | 1 day | Future |

---

## Key Files

```
flowise_dev_agent/
├── api.py                         ← FastAPI service (all HTTP changes land here)
├── instance_pool.py               ← FlowiseClientPool (DD-032)
├── agent/
│   ├── graph.py                   ← LangGraph state machine (node/edge topology)
│   ├── state.py                   ← AgentState TypedDict
│   ├── tools.py                   ← DomainTools, FloviseDomain, executor factory
│   ├── pattern_store.py           ← Pattern library (DD-031)
│   └── skills.py                  ← Skill file loader
└── skills/
    └── flowise_builder.md         ← 14 rules for chatflow construction
```

---

## DO NEXT — Detailed Implementation Plans

---

### 1. Requirement Clarification Node

**Goal**: Before Discover runs, ask the developer 2–3 targeted questions when the
requirement is ambiguous. Front-loading human input eliminates the most expensive
outcome: ITERATE loops caused by a misunderstood requirement.

**Files to change**: `flowise_dev_agent/agent/graph.py`, `flowise_dev_agent/agent/state.py`,
`flowise_dev_agent/.env.example`

**New graph topology**:
```
START → clarify → discover → check_credentials → plan → ...
```
The `clarify` node is a HITL interrupt that fires when the LLM scores ambiguity
above a threshold. It can be bypassed entirely with `SKIP_CLARIFICATION=true`.

**Add to `AgentState`** in `state.py`:
```python
# Clarifying answers provided by developer before discover (DD-033).
# None = no clarification needed or SKIP_CLARIFICATION=true.
clarification: str | None
```

**New node** in `graph.py`:
```python
_CLARIFY_SYSTEM = """
You are a requirements analyst. Read the developer's requirement and decide if it is
specific enough to build a correct Flowise chatflow without further information.

Score ambiguity 0–10 (0 = fully specified, 10 = completely unclear).
If score >= 5, output exactly 2–3 YES/NO or short-answer questions that would resolve
the ambiguity. Focus on: LLM provider, memory requirements, new vs modify, RAG needed.
If score < 5, output: CLEAR

Format:
SCORE: N
QUESTIONS:
1. ...
2. ...
"""

def _make_clarify_node(engine: ReasoningEngine):
    async def clarify(state: AgentState) -> dict:
        """Pre-discover: ask clarifying questions if requirement is ambiguous."""
        # Skip if env var set (for automated pipelines / tests)
        import os
        if os.getenv("SKIP_CLARIFICATION", "").lower() in ("true", "1", "yes"):
            return {"clarification": None}

        response = await engine.complete(
            messages=[Message(role="user", content=state["requirement"])],
            system=_CLARIFY_SYSTEM,
            tools=None,
        )
        text = (response.content or "").strip()

        if text.upper().startswith("SCORE"):
            # Parse score
            score_line = text.splitlines()[0]
            try:
                score = int(score_line.split(":")[1].strip())
            except (IndexError, ValueError):
                score = 0
        else:
            score = 0

        if score >= 5:
            developer_response: str = interrupt({
                "type": "clarification",
                "prompt": text,
                "requirement": state["requirement"],
                "iteration": 0,
            })
            return {
                "clarification": developer_response,
                "total_input_tokens": response.input_tokens,
                "total_output_tokens": response.output_tokens,
            }

        return {
            "clarification": None,
            "total_input_tokens": response.input_tokens,
            "total_output_tokens": response.output_tokens,
        }

    return clarify
```

**Update discover node** to inject clarification into the user message:
```python
user_content = f"My requirement:\n{state['requirement']}"
if state.get("clarification"):
    user_content += f"\n\nClarifications provided:\n{state['clarification']}"
```

**Register in `build_graph()`**:
```python
builder.add_node("clarify", _make_clarify_node(engine))
builder.add_edge(START, "clarify")
builder.add_edge("clarify", "discover")
# Remove: builder.add_edge(START, "discover")
```

**Add to `.env.example`**:
```bash
# Set to true to skip the pre-discover clarification step (useful for automated pipelines)
SKIP_CLARIFICATION=false
```

Add to `DESIGN_DECISIONS.md` as **DD-033**.

---

### 2. Session Export / Audit Trail

**Goal**: `GET /sessions/{thread_id}/summary` returns a human-readable markdown
summary of a completed or in-progress session. Zero new state — purely formats
existing `AgentState` fields. Essential for team handoffs, compliance, and debugging.

**Files to change**: `flowise_dev_agent/api.py`

**New endpoint**:
```python
@app.get("/sessions/{thread_id}/summary", tags=["sessions"],
         dependencies=[Depends(_verify_api_key)])
async def get_session_summary(thread_id: str, request: Request) -> dict:
    """Return a human-readable markdown summary of a session."""
    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        snapshot = graph.get_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found.")

    s = snapshot.values
    lines = [
        f"# Session `{thread_id}`",
        f"",
        f"**Requirement**: {s.get('requirement', '—')}",
        f"**Chatflow**: `{s.get('chatflow_id') or '(not yet created)'}`",
        f"**Status**: {'completed' if s.get('done') else 'in progress'}",
        f"**Iterations**: {s.get('iteration', 0)}",
        f"**Tokens**: {s.get('total_input_tokens', 0):,} in / {s.get('total_output_tokens', 0):,} out",
        f"",
    ]
    if s.get("plan"):
        lines += ["## Approved Plan", "", s["plan"], ""]
    if s.get("discovery_summary"):
        lines += ["## Discovery Summary", "", s["discovery_summary"], ""]
    if s.get("test_results"):
        lines += ["## Test Results", "", s["test_results"], ""]

    return {"thread_id": thread_id, "summary": "\n".join(lines)}
```

Add to `DESIGN_DECISIONS.md` as **DD-034**.

---

### 3. Discover Response Caching

**Goal**: `list_nodes` (~162k tokens, never changes) and `list_marketplace_templates`
(~430k tokens raw, trimmed to ~13k) are called fresh on every Discover phase.
A 5-minute TTL cache keyed by `(instance_id, tool_name)` eliminates 20–30% of
per-session token cost with zero change to agent behaviour.

**Files to change**: `flowise_dev_agent/agent/tools.py`, `.env.example`

**Implementation** — add to `tools.py`:
```python
import time as _time

_tool_cache: dict[str, tuple[Any, float]] = {}  # key → (result, expires_at)


def _cached(key: str, ttl: float, fn):
    """Wrap an async callable with a TTL cache. Returns the cached value if fresh."""
    async def wrapper(*args, **kwargs):
        now = _time.monotonic()
        if key in _tool_cache:
            value, expires_at = _tool_cache[key]
            if now < expires_at:
                logger.debug("Cache hit: %s", key)
                return value
        result = await fn(*args, **kwargs)
        _tool_cache[key] = (result, now + ttl)
        return result
    return wrapper
```

**Update `_make_flowise_executor()`**:
```python
import os as _os
_cache_ttl = float(_os.getenv("DISCOVER_CACHE_TTL_SECS", "300"))

return {
    ...
    "list_nodes": _cached(
        f"list_nodes:{id(client)}", _cache_ttl,
        lambda: _list_nodes_slim(client)
    ),
    "list_marketplace_templates": _cached(
        f"list_marketplace_templates:{id(client)}", _cache_ttl,
        lambda: _list_marketplace_templates_slim(client)
    ),
    ...
}
```

**Add to `.env.example`**:
```bash
# TTL in seconds for cached discover tool responses (list_nodes, list_marketplace_templates).
# Set to 0 to disable caching. Default: 300 (5 minutes).
DISCOVER_CACHE_TTL_SECS=300
```

Add to `DESIGN_DECISIONS.md` as **DD-035**.

---

### 4. Rate Limiting

**Goal**: Protect the `/sessions` POST endpoints from runaway callers exhausting
the LLM quota. A single misconfigured client can otherwise burn thousands of tokens
and block all other sessions.

**Files to change**: `flowise_dev_agent/api.py`, `pyproject.toml`, `.env.example`

**Add to `pyproject.toml`**:
```toml
"slowapi>=0.1",
"limits>=3.0",
```

**Implementation** in `api.py`:
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

_rate_limit = os.getenv("RATE_LIMIT_SESSIONS_PER_MIN", "10")
limiter = Limiter(key_func=get_remote_address, default_limits=[f"{_rate_limit}/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

**Apply decorator** to session-start endpoints:
```python
@app.post("/sessions", ...)
@limiter.limit(f"{os.getenv('RATE_LIMIT_SESSIONS_PER_MIN', '10')}/minute")
async def create_session(request: Request, body: StartSessionRequest) -> SessionResponse:
    ...
```

**Add to `.env.example`**:
```bash
# Max new session starts per minute per IP (default: 10). Set to 0 to disable.
RATE_LIMIT_SESSIONS_PER_MIN=10
```

Add to `DESIGN_DECISIONS.md` as **DD-036**.

---

## HIGH PRIORITY

---

### 5. Webhook Callbacks for HITL Interrupts

**Goal**: Notify an external URL when the graph pauses at a HITL interrupt.
Developers don't need to poll — their CI pipeline, Slack bot, or custom UI
receives the interrupt payload immediately via HTTP POST.

**Files to change**: `flowise_dev_agent/agent/state.py`, `flowise_dev_agent/agent/graph.py`,
`flowise_dev_agent/api.py`

**Add to `AgentState`** in `state.py`:
```python
# Optional URL to POST interrupt payloads to (DD-037).
# None = no webhook. Set via StartSessionRequest.webhook_url.
webhook_url: str | None
```

**Add to `StartSessionRequest`** in `api.py`:
```python
webhook_url: str | None = Field(
    None,
    description=(
        "Optional HTTPS URL to POST interrupt payloads to. "
        "Called when plan_approval, result_review, or credential_check interrupts fire."
    ),
)
```

**Webhook dispatch helper** in `graph.py`:
```python
async def _fire_webhook(url: str, payload: dict) -> None:
    """POST interrupt payload to webhook_url. Non-blocking; failures are logged."""
    import httpx
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
            return
        except Exception as e:
            wait = 2 ** attempt
            logger.warning("Webhook attempt %d failed (%s); retrying in %ds", attempt+1, e, wait)
            await asyncio.sleep(wait)
    logger.error("Webhook delivery failed after 3 attempts: %s", url)
```

**Update each HITL node** to call `_fire_webhook` before `interrupt()`:
```python
if state.get("webhook_url"):
    asyncio.create_task(_fire_webhook(state["webhook_url"], interrupt_payload))
developer_response: str = interrupt(interrupt_payload)
```

**Add `webhook_url`** to `_initial_state()` and pass-through from `StartSessionRequest`.

Add `httpx` to `pyproject.toml` dependencies.

Add to `DESIGN_DECISIONS.md` as **DD-037**.

---

### 6. Error Recovery Playbook

**Goal**: The converge node already classifies failures into categories
(`CREDENTIAL`, `STRUCTURE`, `LOGIC`, `INCOMPLETE`). A static lookup table of
category → targeted fix instructions reduces the next iteration's planning burden
from "reason about the failure from scratch" to "apply known fix X".

**Files to change**: `flowise_dev_agent/agent/graph.py`

**Playbook** — add to `graph.py`:
```python
_ERROR_PLAYBOOK: dict[str, str] = {
    "CREDENTIAL": (
        "RECOVERY: The failure is a missing or mis-bound credential. "
        "In the next Patch: verify the credential ID is set at BOTH data.credential "
        "AND data.inputs.credential for every node that requires an API key. "
        "Re-check list_credentials before patching."
    ),
    "STRUCTURE": (
        "RECOVERY: The failure is a structural flowData issue. "
        "In the next Patch: call validate_flow_data and fix ALL reported errors before "
        "calling update_chatflow. Ensure every node has inputAnchors, inputParams, "
        "outputAnchors, and outputs. Ensure minimum flow_data is {'nodes':[],'edges':[]}."
    ),
    "LOGIC": (
        "RECOVERY: The failure is a logic error (wrong prompt, wrong model config, "
        "incorrect chain/agent type). Review the test failure message carefully "
        "and change only the specific node/param that caused it."
    ),
    "INCOMPLETE": (
        "RECOVERY: The chatflow is incomplete or untestable. "
        "Verify the chatflow was deployed (deployed:true) and the correct chatflow_id "
        "was used in predictions. Re-run list_chatflows if unsure."
    ),
}
```

**Inject into plan node context** when an ITERATE verdict has a known category:
```python
# In _make_plan_node, after reading converge_verdict:
cv = state.get("converge_verdict")
if cv and cv.get("verdict") == "ITERATE":
    category = cv.get("category", "INCOMPLETE")
    playbook_hint = _ERROR_PLAYBOOK.get(category, "")
    if playbook_hint:
        ctx.append(Message(role="user", content=playbook_hint))
```

Add to `DESIGN_DECISIONS.md` as **DD-038**.

---

### 7. Chatflow Version Tags (Full Rollback History)

**Goal**: Replace the "last snapshot only" rollback with named version tags,
so developers can roll back to *any* prior good state, not just the most recent.

**Files to change**: `flowise_dev_agent/agent/tools.py`, `flowise_dev_agent/api.py`

**Update `_snapshots` data structure**:
```python
# Before: _snapshots: dict[str, list[dict]] = {}
# After: each entry includes an explicit version_label

async def _snapshot_chatflow(client, chatflow_id, session_id,
                              version_label: str | None = None) -> dict:
    chatflow = await client.get_chatflow(chatflow_id)
    if "error" in chatflow:
        return chatflow
    existing = _snapshots.get(session_id, [])
    label = version_label or f"v{len(existing) + 1}.0"
    snap = {
        "chatflow_id": chatflow_id,
        "name": chatflow.get("name"),
        "flow_data": chatflow.get("flowData", ""),
        "version_label": label,
        "timestamp": time.time(),
    }
    _snapshots.setdefault(session_id, []).append(snap)
    return {"snapshotted": True, "version_label": label,
            "snapshot_count": len(_snapshots[session_id])}
```

**Update `snapshot_chatflow` tool definition** to add optional `version_label` param.

**Update `_rollback_chatflow`** to accept optional `version_label` param;
if None rolls back to the latest, otherwise finds the matching label.

**New API endpoints**:
```python
@app.get("/sessions/{thread_id}/versions", tags=["sessions"])
async def list_versions(thread_id: str, ...) -> list[dict]:
    """List all chatflow snapshots taken during this session."""
    ...

@app.post("/sessions/{thread_id}/rollback", ...)
async def rollback_session(thread_id: str, version: str | None = None, ...):
    """Rollback to a specific version label (default: latest)."""
    ...
```

Add to `DESIGN_DECISIONS.md` as **DD-039**.

---

### 8. Parallel Test Execution

**Goal**: The test node currently runs happy-path then edge-case predictions
sequentially, even though they are independent. Running them concurrently halves
test phase latency. With `test_trials=3`, the improvement is 3×.

**Files to change**: `flowise_dev_agent/agent/graph.py`,
`flowise_dev_agent/skills/flowise_builder.md`

**Current state**: test node calls `_react()` which runs a single ReAct loop.
The LLM issues `create_prediction` calls one at a time.

**Implementation** — update test node system prompt to instruct the LLM to issue
both test tool calls in a single response (which the ReAct loop processes together),
or add a dedicated async test runner that fires both predictions via `asyncio.gather`:

```python
# In _make_test_node, after getting chatflow_id:
async def _run_prediction(session_suffix: str, input_text: str) -> dict:
    return await client.create_prediction(
        chatflow_id=chatflow_id,
        question=input_text,
        override_config={"sessionId": f"test-{chatflow_id}-{session_suffix}"},
    )

happy_path_task = asyncio.create_task(
    _run_prediction("happy", state["requirement"][:100])
)
edge_case_task = asyncio.create_task(
    _run_prediction("edge", "")  # empty input edge case
)
happy_result, edge_result = await asyncio.gather(happy_path_task, edge_case_task)
```

This bypasses the LLM for the test execution itself and uses the LLM only to
evaluate results — separating execution from evaluation.

**Skill update**: Add Rule 15 to `flowise_builder.md` documenting the new
parallel test behaviour and what the LLM should focus on (evaluation, not invocation).

Add to `DESIGN_DECISIONS.md` as **DD-040**.

---

## FUTURE

---

### 9. GitHub Chatflow Export

**Goal**: After every DONE verdict, commit the final chatflow JSON to a configured
GitHub repository. Enables version control, PR-based review, and audit history for
regulated environments.

**Files to change**: `flowise_dev_agent/agent/graph.py`, `pyproject.toml`, `.env.example`

**Implementation sketch**:
- Add optional `GITHUB_TOKEN`, `GITHUB_REPO`, `GITHUB_BRANCH` env vars
- In converge node after DONE (alongside pattern save): push `chatflows/{chatflow_id}.json`
  to the repo using `PyGitHub` (`pip install PyGitHub`)
- File content: `{"chatflow_id": ..., "name": ..., "flowData": ..., "exported_at": ...}`

Add to `DESIGN_DECISIONS.md` as **DD-041**.

---

### 10. Slack / Teams Notifications

**Goal**: POST the interrupt payload to a Slack or Teams incoming webhook URL when
a HITL pause fires. Developers get a notification in their work chat without polling.

**Relation to item 5**: This is a specialised variant of Webhook Callbacks (item 5).
Implement item 5 first; Slack/Teams support can be added as a helper that formats
the generic payload as a Slack Block Kit / Teams Adaptive Card message.

Add to `DESIGN_DECISIONS.md` as **DD-042**.

---

### 11. Per-Key Token Quotas

**Goal**: Cap the number of LLM tokens a given API key can consume, enabling
cost control in multi-tenant deployments without a billing system.

**Files to change**: `flowise_dev_agent/api.py`, `flowise_dev_agent/agent/state.py`

**Implementation sketch**:
- SQLite table `quotas(api_key TEXT PK, token_limit INT, tokens_used INT, reset_at REAL)`
- Check in `_verify_api_key`: if `tokens_used >= token_limit` → HTTP 429
- Increment `tokens_used` on session completion using `total_input_tokens + total_output_tokens`
- `POST /quotas` (admin) to set limits per key

Add to `DESIGN_DECISIONS.md` as **DD-043**.

---

### 12. Session Analytics Endpoint

**Goal**: Aggregate metrics across all sessions to support capacity planning and
identify systemic failure patterns (e.g., "CREDENTIAL errors account for 40% of
all ITERATE loops").

**New endpoint**: `GET /analytics`

**Returns**:
```json
{
  "total_sessions": 42,
  "completed": 35,
  "avg_iterations_to_done": 1.8,
  "avg_tokens_per_session": 14200,
  "failure_categories": {"CREDENTIAL": 12, "STRUCTURE": 7, "LOGIC": 3},
  "pattern_reuse_rate": 0.28
}
```

Computed by querying the sessions SQLite DB + pattern store.

Add to `DESIGN_DECISIONS.md` as **DD-044**.

---

### 13. Requirement Similarity Deduplication

**Goal**: Before starting a new session, warn the developer if the pattern library
contains a high-similarity match for their requirement — they may not need to build
at all.

**Implementation sketch**:
- Generate embeddings for requirements using a small local model (`sentence-transformers`)
  or the same LLM already in use
- On session start, compute cosine similarity against all stored pattern requirements
- If similarity ≥ 0.90 → return a warning interrupt with the matching pattern
- Developer can proceed anyway or reuse the existing chatflow

**Dependencies**: `sentence-transformers` or embedding API call. Adds ~200ms latency
at session start.

Add to `DESIGN_DECISIONS.md` as **DD-045**.

---

## Implementation Order (Recommended)

```
Sprint 1:  Requirement clarification (1) + Session export (2) + Discover cache (3) + Rate limiting (4)
Sprint 2:  Webhook callbacks (5) + Error recovery playbook (6)
Sprint 3:  Version tags (7) + Parallel tests (8)
Future:    GitHub export (9) + Slack/Teams (10) + Quotas (11) + Analytics (12) + Dedup (13)
```

---

## Adding a New Design Decision

When implementing any item above, add a `DD-0XX` entry to `DESIGN_DECISIONS.md`
following the existing format:

```markdown
## DD-0XX — <Title>

**Date**: YYYY-MM-DD
**Decision**: ...
**Reason**: ...
**Implementation**: ...
**Rejected alternatives**: ...
```

Next available DD number: **DD-033**
