# Flowise Development Agent

LangGraph co-pilot for building Flowise chatflows.
Autonomous **Clarify → Discover → Plan → Patch → Test → Converge** loop with human-in-the-loop review at key checkpoints.

---

## What It Does

The Flowise Dev Agent takes a natural-language requirement and autonomously builds a working Flowise chatflow:

```
POST /sessions/stream  {"requirement": "Build a customer support chatbot with GPT-4o and memory"}

  ┌─────────────┐
  │   CLARIFY   │  INTERRUPT (if ambiguous): asks 2–3 targeted questions before spending tokens
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │   DISCOVER  │  Read-only: search_patterns, list_chatflows, get_node, list_credentials
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │CHECK CREDS  │  INTERRUPT if required credentials are missing
  └──────┬──────┘   → Developer creates them in Flowise, resumes
         │
  ┌──────▼──────┐
  │    PLAN     │  Structured plan: Goal / Inputs / Outputs / Pattern / Success Criteria
  └──────┬──────┘
         │
  ⏸ INTERRUPT: plan_approval  ← Developer reviews and approves (or requests changes)
         │
  ┌──────▼──────┐
  │    PATCH    │  Minimal write: snapshot → get_chatflow → create/update_chatflow
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │    TEST     │  Happy-path + edge-case predictions with unique sessionIds
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │   CONVERGE  │  Structured verdict: DONE or ITERATE with Category/Reason/Fix
  └──────┬──────┘
         │ DONE
  ⏸ INTERRUPT: result_review  ← Developer accepts or requests another iteration
         │ accepted
        END
```

---

## Quick Start

### Local Web UI (recommended for development)

```bash
cp .env.example .env
# Edit .env: set FLOWISE_API_KEY, FLOWISE_API_ENDPOINT, ANTHROPIC_API_KEY

pip install -e ".[claude]"
flowise-agent
# Open http://localhost:8000/ui
```

The web UI streams token output in real-time, renders the structured plan in markdown,
and provides one-click Approve / Accept buttons at each HITL checkpoint.

### Docker

```bash
cp .env.example .env
docker compose up
curl http://localhost:8000/health
```

### CLI (headless)

```bash
flowise-agent          # start API server
flowise-agent-cli      # interactive terminal session (prompts for requirement)
```

---

## Configuration

All configuration is via environment variables (or a `.env` file).

| Variable | Required | Default | Description |
|---|---|---|---|
| `FLOWISE_API_ENDPOINT` | Yes | `http://localhost:3000` | Flowise server URL |
| `FLOWISE_API_KEY` | Yes | — | Flowise API key |
| `FLOWISE_TIMEOUT` | No | `120` | HTTP timeout in seconds |
| `REASONING_ENGINE` | No | `claude` | LLM provider: `claude` or `openai` |
| `REASONING_MODEL` | No | Provider default | Model name override |
| `REASONING_TEMPERATURE` | No | `0.2` | Sampling temperature (0.0–1.0) |
| `ANTHROPIC_API_KEY` | If claude | — | Anthropic API key |
| `OPENAI_API_KEY` | If openai | — | OpenAI API key |
| `AGENT_API_KEY` | No | — | Bearer token for API auth (unset = no auth) |
| `AGENT_API_PORT` | No | `8000` | API server port |
| `SKIP_CLARIFICATION` | No | `false` | Skip pre-discover clarification step |
| `DISCOVER_CACHE_TTL_SECS` | No | `300` | TTL for cached discover responses |
| `RATE_LIMIT_SESSIONS_PER_MIN` | No | `10` | Max new sessions per IP per minute |
| `CURSORWISE_LOG_LEVEL` | No | `INFO` | Log verbosity |

---

## API Reference

### `GET /health`
Verify the API and Flowise connection are both up.

```bash
curl http://localhost:8000/health
# {"api": "ok", "flowise": "ok"}
```

### `GET /ui`
Serve the local developer web UI (HTML, no build step required).

```
http://localhost:8000/ui
```

### `POST /sessions/stream`
Start a new session and stream events via SSE. Preferred over `POST /sessions` for interactive use.

```bash
curl -X POST http://localhost:8000/sessions/stream \
  -H "Content-Type: application/json" \
  -d '{"requirement": "Build a customer support chatbot with GPT-4o and memory"}'
```

SSE event stream (`data: {...}\n\n`):
```
data: {"type": "token", "content": "Discovering node types..."}
data: {"type": "tool_call", "tool": "get_node", "args": {"name": "chatOpenAI"}}
data: {"type": "tool_result", "tool": "get_node", "result": "..."}
data: {"type": "plan_approval", "plan": "# STRUCTURED PLAN\n...", "prompt": "..."}
data: {"type": "done", "thread_id": "uuid-...", "status": "pending_interrupt"}
```

### `POST /sessions/{thread_id}/stream`
Resume a paused session and stream the continuation.

```bash
curl -X POST http://localhost:8000/sessions/uuid-.../stream \
  -H "Content-Type: application/json" \
  -d '{"response": "approved"}'
```

### `POST /sessions`
Start a new session (non-streaming). Returns after Discover + Plan when an interrupt is pending.

```bash
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "requirement": "Build a customer support chatbot with GPT-4o and memory",
    "test_trials": 1,
    "webhook_url": "https://your-server.com/webhook"
  }'
```

Response:
```json
{
  "thread_id": "uuid-...",
  "status": "pending_interrupt",
  "iteration": 0,
  "interrupt": {
    "type": "plan_approval",
    "plan": "1. GOAL\n...",
    "prompt": "Review the plan above. Reply 'approved' to proceed..."
  }
}
```

### `POST /sessions/{thread_id}/resume`
Resume a paused session with the developer's response (non-streaming).

```bash
# Approve the plan
curl -X POST http://localhost:8000/sessions/uuid-.../resume \
  -H "Content-Type: application/json" \
  -d '{"response": "approved"}'

# Request changes
curl -X POST http://localhost:8000/sessions/uuid-.../resume \
  -H "Content-Type: application/json" \
  -d '{"response": "Use claude-sonnet-4-6 instead of GPT-4o"}'
```

### `GET /sessions`
List all sessions with current status, iteration count, and token totals.

```bash
curl http://localhost:8000/sessions
```

### `GET /sessions/{thread_id}`
Check session status (including any pending interrupt payload).

```bash
curl http://localhost:8000/sessions/uuid-...
```

### `GET /sessions/{thread_id}/summary`
Return a human-readable markdown audit trail of the session.

```bash
curl http://localhost:8000/sessions/uuid-.../summary
# {"thread_id": "...", "summary": "# Session uuid-...\n\n**Requirement**: ..."}
```

### `DELETE /sessions/{thread_id}`
Delete a session and its checkpoint history.

```bash
curl -X DELETE http://localhost:8000/sessions/uuid-...
```

### `GET /sessions/{thread_id}/versions`
List all chatflow snapshots taken during the session.

```bash
curl http://localhost:8000/sessions/uuid-.../versions
```

### `POST /sessions/{thread_id}/rollback`
Roll back the chatflow to a specific snapshot (or latest if version omitted).

```bash
curl -X POST http://localhost:8000/sessions/uuid-.../rollback \
  -H "Content-Type: application/json" \
  -d '{"version": "v1.0"}'
```

### `GET /patterns`
Search the pattern library for reusable chatflow blueprints.

```bash
curl "http://localhost:8000/patterns?q=customer+support"
```

### `GET /instances`
List all configured Flowise instances (from `FLOWISE_API_ENDPOINT_*` env vars).

```bash
curl http://localhost:8000/instances
```

---

## How It Works

### 9-Node LangGraph Graph

| Node | Phase | Description |
|---|---|---|
| `clarify` | Pre-discover | HITL interrupt when requirement is ambiguous — asks 2–3 targeted questions |
| `discover` | Read-only | Searches pattern library, calls list_chatflows, get_node, list_credentials |
| `check_credentials` | Validation | HITL interrupt if required credentials are missing from Flowise |
| `plan` | Planning | Creates structured plan (Goal/Inputs/Outputs/Constraints/Success Criteria) |
| `human_plan_approval` | HITL | Developer reviews and approves plan before any writes |
| `patch` | Write | Snapshots existing chatflow, validates flowData, creates/updates chatflow |
| `test` | Validation | Runs happy-path and edge-case predictions with unique sessionIds |
| `converge` | Evaluation | Structured verdict: DONE or ITERATE with Category/Reason/Fix |
| `human_result_review` | HITL | Developer accepts result or requests another iteration |

### Evaluator-Optimizer Feedback Loop

The `converge` node classifies failures and injects targeted fix instructions into
the next planning context:

```
ITERATE
Category: CREDENTIAL
Reason: OpenAI API key not bound at data.credential
Fix: Set data.credential = "<credential_id>" in addition to data.inputs.credential
```

The error recovery playbook maps each category to a specific repair strategy,
reducing the next iteration from "reason from scratch" to "apply known fix X".

### pass^k Reliability Testing

Set `test_trials: 2` (or higher) to require all `k` trials to pass:
- `test_trials: 1` — pass@1 (default — tests capability)
- `test_trials: 2` — pass^2 (requires consistent results across 2 runs)
- `test_trials: 3+` — pass^k (higher confidence for production readiness)

### Pattern Library (Self-Improvement)

After each successful session, the agent saves the chatflow blueprint to a local
SQLite pattern library. On subsequent sessions with similar requirements, `discover`
finds the matching pattern and reuses its flowData directly — skipping most of the
discovery and planning phases.

### HITL Webhooks

Pass `webhook_url` when starting a session to receive interrupt payloads via HTTP POST.
The agent fires the webhook before each HITL pause, enabling CI pipelines, Slack bots,
or custom UIs to respond without polling.

---

## Web UI

The local web UI at `GET /ui` provides:
- **Real-time token stream** — watch the LLM think as it discovers nodes and builds the plan
- **Tool call badges** — each `get_node`, `create_chatflow`, etc. call appears as a badge in the stream
- **Markdown plan rendering** — structured plan is rendered with full formatting at `plan_approval`
- **One-click HITL responses** — Approve, Accept, and feedback buttons at each checkpoint
- **Session sidebar** — browse all sessions with live status indicators
- **Audit trail** — click any completed session to read the full summary

No build step, no Node.js, no dependencies. Single HTML file served by FastAPI.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│          flowise-dev-agent                  │  This repo
│                                             │
│  FastAPI (15+ endpoints + SSE streaming)    │
│       │                                     │
│  LangGraph StateGraph (9 nodes)             │
│  ├── clarify node (DD-033)                  │
│  ├── discover node                          │
│  ├── check_credentials node (DD-017)        │
│  ├── plan node                              │
│  ├── human_plan_approval (HITL)             │
│  ├── patch node                             │
│  ├── test node (parallel, DD-040)           │
│  ├── converge node (DD-019)                 │
│  └── human_result_review (HITL)             │
│       │                                     │
│  DomainCapability layer (DD-046)            │
│  ├── FlowiseCapability  ← ToolRegistry      │
│  │                        (namespaced,      │
│  │                         DD-049)          │
│  └── WorkdayCapability (stub, DD-047)       │
│                                             │
│  ToolResult envelope (DD-048)               │
│  └── execute_tool() → compact summary only  │
│                                             │
│  ReasoningEngine (Claude / OpenAI)          │
│       │                                     │
│  SQLite (AsyncSqliteSaver, DD-024)          │
│  ├── sessions.db  — checkpoint store        │
│  └── patterns.db  — pattern library (DD-031)│
│                                             │
│  flowise_dev_agent/skills/                  │
│  └── flowise_builder.md                     │
└────────────────┬────────────────────────────┘
                 │  pip dependency
┌────────────────▼────────────────────────────┐
│              cursorwise                     │  Separate repo
│                                             │
│  FlowiseClient (52 async methods)           │
│  FlowiseClientPool (multi-instance, DD-032) │
│  Settings (Flowise connection)              │
│  MCP Server (50 tools for Cursor)           │
└─────────────────────────────────────────────┘
                 │  HTTP REST API
┌────────────────▼────────────────────────────┐
│          Flowise Server                     │
│  localhost:3000 (or remote)                 │
└─────────────────────────────────────────────┘
```

---

## Skills — Extending Agent Knowledge

The agent's domain knowledge lives in editable markdown files:

```
flowise_dev_agent/skills/
├── flowise_builder.md   ← Active (14 rules for Flowise chatflow construction)
├── workday_extend.md    ← Placeholder for Workday v2
└── README.md            ← Skill authoring guide
```

Each skill file has three sections injected into system prompts:
- `## Discover Context` — what to look for, what APIs to call
- `## Patch Context` — non-negotiable rules for writing flowData
- `## Test Context` — how to validate the result

To update agent behavior for a new Flowise pattern, edit `flowise_builder.md` directly.
No Python changes or server restart required.

---

## Design Decisions

See [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) for the full architectural rationale,
covering 52 decisions from LangGraph topology to the deterministic patch compiler.

Key decisions:

| DD | Title |
|---|---|
| DD-009 | Compact context strategy — no raw tool call blobs in state |
| DD-013 | `_get_node_processed` — pre-splits inputAnchors/inputParams to prevent HTTP 500 |
| DD-017 | Credential HITL checkpoint — front-load credential discovery |
| DD-018 | FlowData pre-flight validator — poka-yoke design against invalid writes |
| DD-019 | Structured converge verdicts — evaluator-optimizer feedback loop |
| DD-021 | pass^k reliability testing — capability vs reliability distinction |
| DD-024 | SQLite session persistence via AsyncSqliteSaver |
| DD-025 | SSE streaming endpoints |
| DD-026 | Chatflow snapshot / rollback |
| DD-028 | API key authentication (optional bearer token) |
| DD-029 | Token budget tracking |
| DD-031 | Pattern library (self-improvement loop) |
| DD-032 | Multiple Flowise instances |
| DD-033 | Requirement clarification node — front-load human input |
| DD-034 | Session export / audit trail |
| DD-035 | Discover response caching |
| DD-036 | Rate limiting |
| DD-037 | Webhook callbacks for HITL interrupts |
| DD-038 | Error recovery playbook |
| DD-039 | Chatflow version tags (full rollback history) |
| DD-040 | Parallel test execution |
| DD-046 | DomainCapability ABC — behavioral contract for domain plugins |
| DD-047 | WorkdayCapability stub — interface-complete before API is connected |
| DD-048 | ToolResult envelope — compact context enforcement at execute_tool boundary |
| DD-049 | ToolRegistry v2 — namespaced, phase-gated, dual-key executor |
| DD-050 | AgentState trifurcation — artifacts/facts/debug separated from transcript |
| DD-051 | Patch IR schema — LLM emits ops, compiler derives handle IDs deterministically |
| DD-052 | WriteGuard — same-iteration SHA-256 hash enforcement before any Flowise write |

---

## Performance

See [PERFORMANCE.md](PERFORMANCE.md) for observed token costs and the root cause
analysis of quadratic context accumulation.

**Compact context (shipped — DD-048):** `execute_tool()` now returns a `ToolResult`;
`result_to_str(ToolResult)` injects only the compact `.summary` into LLM context.
Raw API responses (previously up to 162k tokens for `list_nodes`) are stored in
`state['debug']` only and never reach the prompt. This eliminates the primary source
of context bloat at the tool execution boundary.

---

## Related

- [cursorwise](https://github.com/jon-ribera/cursorwise) — Flowise MCP server for Cursor IDE (dependency)
- [Flowise](https://github.com/FlowiseAI/Flowise) — the chatflow platform this agent builds on
- [ROADMAP2.md](ROADMAP2.md) — next-wave enhancement backlog
- [roadmap3_architecture_optimization.md](roadmap3_architecture_optimization.md) — Architecture blueprint: M1 ToolResult + ToolRegistry + DomainCapability (complete), M2 Patch IR (next), M3 Workday + cross-domain (future)
