# Flowise Development Agent

LangGraph co-pilot for building Flowise chatflows.
Autonomous **Discover → Plan → Patch → Test → Converge** loop with human-in-the-loop review at key checkpoints.

---

## What It Does

The Flowise Dev Agent takes a natural-language requirement and autonomously builds a working Flowise chatflow:

```
POST /sessions  {"requirement": "Build a customer support chatbot with GPT-4o and memory"}

  ┌─────────────┐
  │   DISCOVER  │  Read-only: list_chatflows, get_node, list_credentials, list_marketplace_templates
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
  │    PATCH    │  Minimal write: get_chatflow → validate → create/update_chatflow
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

### Docker (recommended)

```bash
cp .env.example .env
# Edit .env: set FLOWISE_API_KEY, FLOWISE_API_ENDPOINT, ANTHROPIC_API_KEY

docker compose up
curl http://localhost:8000/health
```

### Local Python

```bash
pip install -e ".[claude]"
cp .env.example .env
# Edit .env

flowise-agent
# Server starts at http://localhost:8000
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
| `CURSORWISE_LOG_LEVEL` | No | `INFO` | Log verbosity |
| `AGENT_API_PORT` | No | `8000` | API server port |

---

## API Reference

### `GET /health`
Verify the API and Flowise connection are both up.

```bash
curl http://localhost:8000/health
# {"api": "ok", "flowise": "ok", "flowise_detail": {...}}
```

### `POST /sessions`
Start a new co-development session. Runs Discover + Plan, then pauses for plan approval.

```bash
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "requirement": "Build a customer support chatbot with GPT-4o and memory",
    "test_trials": 1
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
Resume a paused session with the developer's response.

```bash
# Approve the plan
curl -X POST http://localhost:8000/sessions/uuid-.../resume \
  -H "Content-Type: application/json" \
  -d '{"response": "approved"}'

# Or request changes
curl -X POST http://localhost:8000/sessions/uuid-.../resume \
  -H "Content-Type: application/json" \
  -d '{"response": "Use claude-sonnet-4-6 instead of GPT-4o"}'
```

### `GET /sessions/{thread_id}`
Check session status without advancing it.

```bash
curl http://localhost:8000/sessions/uuid-...
```

---

## How It Works

### 8-Node LangGraph Graph

| Node | Phase | Description |
|---|---|---|
| `discover` | Read-only | Calls list_chatflows, get_node, list_credentials, list_marketplace_templates |
| `check_credentials` | Validation | HITL interrupt if required credentials are missing from Flowise |
| `plan` | Planning | Creates structured plan (Goal/Inputs/Outputs/Constraints/Success Criteria) |
| `human_plan_approval` | HITL | Developer reviews and approves plan before any writes |
| `patch` | Write | Validates flowData, creates/updates chatflow with minimal changes |
| `test` | Validation | Runs happy-path and edge-case predictions with unique sessionIds |
| `converge` | Evaluation | Structured verdict: DONE or ITERATE with Category/Reason/Fix |
| `human_result_review` | HITL | Developer accepts result or requests another iteration |

### Evaluator-Optimizer Feedback Loop

The `converge` node acts as the **evaluator** and `plan` as the **optimizer**. When tests fail,
converge emits a structured verdict:
```
ITERATE
Category: CREDENTIAL
Reason: OpenAI API key not bound at data.credential
Fix: Set data.credential = "<credential_id>" in addition to data.inputs.credential
```

This verdict is injected directly into the next plan context, giving the planner
specific repair instructions rather than vague failure messages.

### pass^k Reliability Testing

Set `test_trials: 2` (or higher) to require all `k` trials to pass:
- `test_trials: 1` — pass@1 (default, fastest — tests capability)
- `test_trials: 2` — pass^2 (requires consistent results across 2 runs)
- `test_trials: 3+` — pass^k (higher confidence for production readiness)

---

## Architecture

```
┌─────────────────────────────────────┐
│        flowise-dev-agent            │  This repo
│                                     │
│  FastAPI (/sessions, /health)       │
│       │                             │
│  LangGraph StateGraph               │
│  ├── discover node                  │
│  ├── check_credentials node         │
│  ├── plan node                      │
│  ├── human_plan_approval (HITL)     │
│  ├── patch node                     │
│  ├── test node                      │
│  ├── converge node                  │
│  └── human_result_review (HITL)     │
│       │                             │
│  ReasoningEngine (Claude / OpenAI)  │
│       │                             │
│  flowise_dev_agent/skills/          │
│  └── flowise_builder.md             │
└────────────────┬────────────────────┘
                 │  pip dependency
┌────────────────▼────────────────────┐
│           cursorwise                │  Separate repo
│                                     │
│  FlowiseClient (52 async methods)   │
│  Settings (Flowise connection)      │
│  MCP Server (50 tools for Cursor)   │
└─────────────────────────────────────┘
                 │  HTTP REST API
┌────────────────▼────────────────────┐
│        Flowise Server               │
│  localhost:3000 (or remote)         │
└─────────────────────────────────────┘
```

---

## Skills — Extending Agent Knowledge

The agent's domain knowledge lives in editable markdown files:

```
flowise_dev_agent/skills/
├── flowise_builder.md   ← Active (10 rules for Flowise chatflow construction)
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
covering 23 decisions from LangGraph topology to the evaluator-optimizer feedback loop.

Key decisions:
- **DD-009**: Compact context strategy — no raw tool call blobs in state
- **DD-013**: `_get_node_processed` pre-splits inputAnchors/inputParams to prevent HTTP 500
- **DD-017**: Credential HITL before plan — front-load credential discovery
- **DD-018**: FlowData pre-flight validator — poka-yoke design against invalid writes
- **DD-019**: Structured converge verdicts — evaluator-optimizer feedback loop
- **DD-021**: pass^k reliability testing — capability vs reliability distinction
- **DD-023**: Repository separation — cursorwise (MCP server) + flowise-dev-agent (agent)

---

## Related

- [cursorwise](https://github.com/jon-ribera/cursorwise) — Flowise MCP server for Cursor IDE (dependency)
- [Flowise](https://github.com/FlowiseAI/Flowise) — the chatflow platform this agent builds on
