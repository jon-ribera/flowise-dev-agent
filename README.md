<p align="center">
  <h1 align="center">⚡ Flowise Dev Agent</h1>
  <p align="center">
    <strong>LangGraph co-pilot for building Flowise chatflows</strong><br>
    Autonomous <strong>18-node graph</strong> with dual CREATE / UPDATE modes,
    human-in-the-loop review at every checkpoint, and a native <strong>51-tool MCP server</strong>
  </p>
  <p align="center">
    <a href="#-quick-start">Quick Start</a> •
    <a href="#-mcp-server">MCP Server</a> •
    <a href="#️-configuration">Configuration</a> •
    <a href="#-api-reference">API</a> •
    <a href="#-how-it-works">How It Works</a> •
    <a href="#-architecture">Architecture</a> •
    <a href="#-documentation">Docs</a>
  </p>
</p>

---

## ✨ Features

| | Feature | Description |
|---|---|---|
| 🔄 | **18-node LangGraph topology** | Dual CREATE / UPDATE modes with 6 phases (Intent → Resolve → Load → Plan → Validate → Apply & Test) and HITL at 4 checkpoints |
| 🧩 | **Patch IR compiler** | LLM emits structured ops (`AddNode / SetParam / Connect / BindCredential`); deterministic compiler resolves anchor IDs from canonical dictionaries — no hallucinated JSON |
| 🛡️ | **WriteGuard** | SHA-256 gate prevents any Flowise write unless the payload hash matches the validation-time hash |
| 🔌 | **51-tool native MCP server** | `python -m flowise_dev_agent.mcp` — connects Cursor IDE and Claude Desktop directly to Flowise with zero external dependencies |
| 📚 | **Pattern library** | SQLite-backed self-improvement — re-uses past successful chatflow blueprints as compile-time seeds with schema fingerprint matching |
| 🌐 | **Streaming web UI** | Real-time SSE token stream, one-click HITL approve/reject buttons, session sidebar — no build step |
| 🔭 | **LangSmith observability** | Automatic tracing, redaction, HITL feedback, pure-function evaluators, golden-set CI evaluation |
| 🗄️ | **Postgres persistence** | All sessions checkpointed to Postgres with async connection pooling and event logging |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Flowise running and accessible (default: `http://localhost:3000`)
- Postgres (for session persistence)
- A Flowise API key — generate one at **Flowise → top-right menu → API Keys → Add New Key**

### 1. Local Web UI (recommended)

```bash
# Start Postgres
docker compose -f docker-compose.postgres.yml up -d

cp .env.example .env
# Edit .env: set FLOWISE_API_KEY, FLOWISE_API_ENDPOINT, ANTHROPIC_API_KEY, POSTGRES_DSN

pip install -e ".[claude,dev]"
flowise-agent
# Open http://localhost:8000/ui
```

> 💡 **Windows:** if `flowise-agent` is not found after install, run `python -m flowise_dev_agent.api` or add the Python Scripts directory to your PATH.

### 2. Docker

```bash
cp .env.example .env
docker compose up
curl http://localhost:8000/health
```

### 3. CLI (headless / CI)

```bash
flowise-agent          # start the API server
flowise-agent-cli      # interactive terminal session (prompts for requirement)
```

---

## 🔌 MCP Server

This repo includes a native MCP server exposing 51 Flowise tools over stdio. Use it with Cursor IDE, Claude Code, or Claude Desktop — no external dependencies required.

```bash
python -m flowise_dev_agent.mcp
```

### Cursor IDE / Claude Code

Copy the example config and fill in your values:

```bash
cp .mcp.json.example .mcp.json
```

Edit `.mcp.json`:

```json
{
  "mcpServers": {
    "flowise": {
      "command": "python",
      "args": ["-m", "flowise_dev_agent.mcp"],
      "env": {
        "FLOWISE_API_KEY": "your-flowise-api-key",
        "FLOWISE_API_ENDPOINT": "http://localhost:3000"
      }
    }
  }
}
```

Enable auto-approval in `.claude/settings.local.json`:

```json
{
  "enableAllProjectMcpServers": true
}
```

Reload the window: `Ctrl+Shift+P` → **Developer: Reload Window**

Verify with `/mcp` in the chat — `flowise` should show as connected with 51 tools.

> See [`flowise_dev_agent/mcp/README.md`](flowise_dev_agent/mcp/README.md) for Claude Desktop configuration and the full environment variable reference.

### MCP configuration reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `FLOWISE_API_KEY` | Yes | — | Bearer token for Flowise API |
| `FLOWISE_API_ENDPOINT` | No | `http://localhost:3000` | Flowise instance URL |
| `FLOWISE_TIMEOUT` | No | `120` | HTTP timeout in seconds |
| `CURSORWISE_LOG_LEVEL` | No | `WARNING` | Python log level for MCP server |

> `.mcp.json` contains secrets — it is gitignored. Never commit it. Share `.mcp.json.example` instead.

---

## ⚙️ Configuration

Set via environment variables or a `.env` file. See [.env.example](.env.example) for the full template.

| Variable | Required | Default | Description |
|---|---|---|---|
| 🌐 `FLOWISE_API_ENDPOINT` | ✅ Yes | `http://localhost:3000` | Flowise server URL |
| 🔑 `FLOWISE_API_KEY` | ✅ Yes | — | Flowise API key |
| 🗄️ `POSTGRES_DSN` | ✅ Yes | — | Postgres connection string (e.g. `postgresql://postgres:postgres@localhost:5432/flowise_dev_agent`) |
| 🤖 `REASONING_ENGINE` | No | `claude` | LLM provider: `claude` or `openai` |
| 🧠 `REASONING_MODEL` | No | Provider default | Model name override |
| 🌡️ `REASONING_TEMPERATURE` | No | `0.2` | Sampling temperature (0.0–1.0) |
| 🔑 `ANTHROPIC_API_KEY` | If claude | — | Anthropic API key |
| 🔑 `OPENAI_API_KEY` | If openai | — | OpenAI API key |
| 🔒 `AGENT_API_KEY` | No | — | Bearer token for API auth (unset = open access) |
| 🚪 `AGENT_API_PORT` | No | `8000` | API server port |
| ⏱️ `FLOWISE_TIMEOUT` | No | `120` | HTTP timeout in seconds |
| 🚦 `RATE_LIMIT_SESSIONS_PER_MIN` | No | `10` | Max new sessions per IP per minute |
| 💬 `SKIP_CLARIFICATION` | No | `false` | Skip pre-discover clarification step |
| 📦 `DISCOVER_CACHE_TTL_SECS` | No | `300` | TTL for cached discover responses (seconds) |
| 📐 `FLOWISE_SCHEMA_DRIFT_POLICY` | No | `warn` | `warn` \| `fail` \| `refresh` on schema fingerprint mismatch |
| 🔭 `LANGCHAIN_API_KEY` | No | — | LangSmith API key (enables tracing) |
| 🔭 `LANGCHAIN_PROJECT` | No | `flowise-dev-agent` | LangSmith project name |

---

## 🔧 API Reference

| | Endpoint | Purpose |
|---|---|---|
| 💓 | `GET /health` | API + Flowise connectivity check |
| 🖥️ | `GET /ui` | Local developer web UI |
| ▶️ | `POST /sessions/stream` | Start a session and stream SSE events (preferred) |
| ↩️ | `POST /sessions/{id}/stream` | Resume a paused session and stream the continuation |
| 📋 | `GET /sessions` | List all sessions with status, iteration count, token totals |
| 🔍 | `GET /sessions/{id}` | Check session status + any pending interrupt payload |
| ▶️ | `POST /sessions` | Start a session (non-streaming) |
| ↩️ | `POST /sessions/{id}/resume` | Resume a paused session (non-streaming) |
| 📄 | `GET /sessions/{id}/summary` | Markdown audit trail for the full session |
| 🗑️ | `DELETE /sessions/{id}` | Delete a session and its checkpoint history |
| 📸 | `GET /sessions/{id}/versions` | List all chatflow snapshots taken during the session |
| ⏪ | `POST /sessions/{id}/rollback` | Roll back the chatflow to a prior snapshot |
| 🔎 | `GET /patterns` | Search reusable chatflow blueprints |
| 🌐 | `GET /instances` | List all configured Flowise instances |

### Quick examples

```bash
# Start a session (streaming)
curl -X POST http://localhost:8000/sessions/stream \
  -H "Content-Type: application/json" \
  -d '{"requirement": "Build a customer support chatbot with GPT-4o and memory"}'

# Approve the plan interrupt
curl -X POST http://localhost:8000/sessions/<thread_id>/resume \
  -H "Content-Type: application/json" \
  -d '{"response": "approved"}'

# Request a change before patching
curl -X POST http://localhost:8000/sessions/<thread_id>/resume \
  -H "Content-Type: application/json" \
  -d '{"response": "Use claude-sonnet-4-6 instead of GPT-4o"}'
```

---

## 🔁 How It Works

The agent runs an 18-node LangGraph topology with two operation modes:

- **CREATE** — build a new chatflow from a natural-language requirement (Phases A, D–F)
- **UPDATE** — modify an existing chatflow by ID (all phases B–F)

```
POST /sessions/stream  {"requirement": "Build a customer support chatbot with GPT-4o and memory"}

  Phase A — Intent
  ┌─────────────────┐
  │ classify_intent  │  Determine CREATE vs UPDATE, extract confidence
  │ hydrate_context  │  Load node schemas, templates, credentials, patterns
  └────────┬────────┘
           │
  Phase B — Resolve (UPDATE only)
  ┌────────▼────────┐
  │ resolve_target   │  Find the chatflow to modify
  │ hitl_select      │  INTERRUPT if multiple matches
  └────────┬────────┘
           │
  Phase C — Load (UPDATE only)
  ┌────────▼────────┐
  │ load_current     │  Fetch existing flowData
  │ summarize_flow   │  Compact summary for LLM context
  └────────┬────────┘
           │
  Phase D — Plan + Compile
  ┌────────▼────────┐
  │ plan_v2          │  Structured plan: Goal / Inputs / Outputs / Pattern
  │ hitl_plan_v2     │  ⏸ INTERRUPT: plan_approval
  │ define_scope     │  Extract patch scope from approved plan
  │ compile_ir       │  LLM emits Patch IR ops (AddNode / SetParam / Connect / BindCredential)
  │ compile_flow     │  Deterministic compiler → flowData + payload_hash
  └────────┬────────┘
           │
  Phase E — Validate
  ┌────────▼────────┐
  │ validate         │  Schema validation + anchor contract checks
  │ repair_schema    │  Auto-repair if local schema is stale
  └────────┬────────┘
           │
  Phase F — Apply & Test
  ┌────────▼────────┐
  │ preflight        │  Final payload hash check (WriteGuard)
  │ apply_patch      │  Write to Flowise (create or update)
  │ test_v2          │  Run predictions with unique sessionIds
  │ evaluate         │  Structured verdict: DONE or ITERATE
  │ hitl_review_v2   │  ⏸ INTERRUPT: result_review
  └─────────────────┘
```

### Patch IR + Deterministic Compiler

The compile phase runs a 5-step pipeline:

1. **Snapshot** — save the existing chatflow before any changes
2. **LLM emits ops only** — `AddNode / SetParam / Connect / BindCredential` in JSON; no handle IDs, no edge IDs
3. **IR validation** — `validate_patch_ops()` catches dangling refs and duplicate node IDs before compilation
4. **Deterministic compiler** — `compile_patch_ops()` reads the existing chatflow as a `GraphIR`, resolves anchor handle IDs from the canonical anchor dictionary, and produces `flowData + payload_hash + diff_summary`
5. **WriteGuard** — `create_chatflow / update_chatflow` are blocked unless the payload hash matches the hash recorded at validation time

### Evaluator-Optimizer Feedback Loop

The `evaluate` node classifies failures and injects targeted fix instructions into
the next iteration's planning context:

```
ITERATE
Category: CREDENTIAL
Reason:   OpenAI API key not bound at data.credential
Fix:      Set data.credential = "<credential_id>" in addition to data.inputs.credential
```

Each failure category maps to a specific repair strategy — the next iteration applies
a known fix rather than reasoning from scratch.

### Pattern Library (Self-Improvement)

After each successful session, the agent saves the chatflow blueprint to a local SQLite
pattern library. On subsequent sessions with similar requirements, `hydrate_context` finds
the matching pattern and seeds the compiler with it — reducing AddNode op count and token
usage. Patterns are fingerprinted against the current node schema version and only applied
when compatible.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│  flowise-dev-agent  (this repo — fully self-contained)   │
│                                                          │
│  FastAPI  (14 endpoints + SSE streaming)                 │
│       │                                                  │
│  LangGraph StateGraph  (18 nodes, v2 topology)           │
│  ├── Phase A: classify_intent · hydrate_context          │
│  ├── Phase B: resolve_target · hitl_select_target        │
│  ├── Phase C: load_current_flow · summarize_current_flow │
│  ├── Phase D: plan_v2 · hitl_plan · define_scope ·       │
│  │            compile_ir · compile_flow                  │
│  ├── Phase E: validate · repair_schema                   │
│  └── Phase F: preflight · apply_patch · test ·           │
│               evaluate · hitl_review                     │
│       │                                                  │
│  Native MCP Layer  (51 tools, TOOL_CATALOG SSoT)         │
│  ├── FlowiseMCPTools    — 51 async methods → ToolResult  │
│  ├── TOOL_CATALOG       — single source of truth         │
│  ├── ToolRegistry       — namespaced dual-key executor   │
│  └── MCP Server         — python -m flowise_dev_agent.mcp│
│       │                                                  │
│  Patch IR + Compiler                                     │
│  ├── patch_ir.py   — AddNode / SetParam /                │
│  │                   Connect / BindCredential            │
│  └── compiler.py   — GraphIR + compile_patch_ops()       │
│       │                                                  │
│  Knowledge Layer                                         │
│  ├── NodeSchemaStore      — 303 node schemas (local-first)│
│  ├── AnchorDictionaryStore— canonical anchor names/types │
│  ├── CredentialStore      — O(1) resolve by id/name/type │
│  └── TemplateStore        — marketplace template search  │
│       │                                                  │
│  Persistence (Postgres)                                  │
│  ├── AsyncCheckpointSaver — LangGraph session state      │
│  ├── EventLog             — node lifecycle events        │
│  └── PatternStore (SQLite)— chatflow pattern library     │
│       │                                                  │
│  Observability (LangSmith)                               │
│  ├── Redaction            — secret scrubbing on all traces│
│  ├── Evaluators           — 5 pure-function quality checks│
│  └── CI Eval              — golden-set regression testing │
│                                                          │
│  FlowiseClient  (internalized httpx REST wrapper)        │
└────────────────────────┬─────────────────────────────────┘
                         │  HTTP REST API
┌────────────────────────▼─────────────────────────────────┐
│  Flowise Server  (localhost:3000 or remote)               │
└──────────────────────────────────────────────────────────┘
```

---

## 🧩 Skills — Extending Agent Knowledge

Agent domain knowledge lives in editable markdown files — no Python changes or server
restart required:

```
flowise_dev_agent/skills/
├── flowise_builder.md   ← Active — 14 rules for Flowise chatflow construction
└── README.md            ← Skill authoring guide
```

Each skill file injects three sections into system prompts:

| Section | Purpose |
|---|---|
| `## Discover Context` | What to look for, which APIs to call |
| `## Patch Context` | Non-negotiable rules for writing `flowData` |
| `## Test Context` | How to validate the result |

To update agent behavior for a new Flowise pattern, edit `flowise_builder.md` directly.

---

## 📚 Documentation

| Document | Description |
|---|---|
| 📐 [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) | 101 architectural decisions — the authoritative rationale log (DD-001 – DD-101) |
| ✅ [roadmap_shipped.md](roadmap_shipped.md) | All shipped milestones with DD cross-references and original roadmap traceability |
| 🗂️ [roadmap_pending.md](roadmap_pending.md) | Open backlog items — each traceable to its source roadmap and next DD number |
| 📊 [PERFORMANCE.md](PERFORMANCE.md) | Token cost analysis, root cause of quadratic context growth, and optimization strategies |
| 📄 [.env.example](.env.example) | Full environment variable template with inline documentation |
| 🗄️ [roadmap_archive/](roadmap_archive/) | Historical roadmap files (source-code docstrings reference these filenames) |

**Key design decisions at a glance:**

| DD | Decision |
|---|---|
| DD-051 | Patch IR schema — LLM emits ops, compiler derives handle IDs deterministically |
| DD-052 | WriteGuard — SHA-256 hash gate before every Flowise write |
| DD-078 | Postgres-only persistence with async connection pooling |
| DD-080 | 18-node topology v2 — dual CREATE / UPDATE modes |
| DD-093 | FlowiseClient internalization — zero external dependencies |
| DD-094 | Native MCP tool surface — 51 tools with `ToolResult` envelope |
| DD-099 | External MCP server — single-dispatch from `TOOL_CATALOG` (no wrapper functions) |
| DD-100 | Repository decoupling — self-contained, cursorwise is optional standalone alternative |

---

## 🗂️ Project Structure

```
flowise_dev_agent/
├── api.py                        # FastAPI endpoints + SSE streaming
├── cli.py                        # flowise-agent-cli entry point
├── reasoning.py                  # LLM abstraction (Claude / OpenAI)
├── instance_pool.py              # Multi-tenant Flowise instance routing
├── agent/
│   ├── graph.py                  # LangGraph StateGraph (18 nodes, v2 topology)
│   ├── state.py                  # AgentState TypedDict + reducers
│   ├── domain.py                 # DomainCapability ABC + result models
│   ├── tools.py                  # DomainTools + ToolResult + execute_tool
│   ├── registry.py               # ToolRegistry v2 (namespaced + dual-key)
│   ├── patch_ir.py               # AddNode / SetParam / Connect / BindCredential
│   ├── compiler.py               # GraphIR + compile_patch_ops()
│   ├── plan_schema.py            # PlanContract dataclass
│   ├── pattern_store.py          # SQLite pattern library
│   ├── metrics.py                # PhaseMetrics + MetricsCollector
│   └── domains/
│       └── workday.py            # WorkdayCapability (Custom MCP blueprint wiring)
├── client/
│   ├── flowise_client.py         # Async httpx REST client (internalized)
│   └── config.py                 # Settings from environment
├── mcp/
│   ├── __main__.py               # Entry point: python -m flowise_dev_agent.mcp
│   ├── server.py                 # MCP server (single-dispatch from TOOL_CATALOG)
│   ├── tools.py                  # FlowiseMCPTools (51 async methods → ToolResult)
│   └── registry.py               # TOOL_CATALOG + register_flowise_mcp_tools()
├── knowledge/
│   ├── provider.py               # NodeSchemaStore + CredentialStore + TemplateStore
│   ├── anchor_store.py           # AnchorDictionaryStore (canonical anchor names)
│   ├── workday_provider.py       # WorkdayMcpStore + WorkdayApiStore
│   └── refresh.py                # CLI: python -m flowise_dev_agent.knowledge.refresh
├── persistence/
│   ├── checkpointer.py           # Postgres AsyncCheckpointSaver
│   ├── event_log.py              # EventLog table + emit_event()
│   └── hooks.py                  # wrap_node() for lifecycle events
├── util/
│   └── langsmith/                # Observability: tracing, redaction, evaluators, CI eval
├── skills/
│   └── flowise_builder.md        # Active skill: chatflow construction rules
└── static/
    └── index.html                # Single-file web UI (no build step)
schemas/                          # Local-first snapshots (refresh with CLI)
├── flowise_nodes.snapshot.json   # 303 Flowise node schemas
├── flowise_credentials.snapshot.json  # Machine-specific (gitignored)
└── workday_mcp.snapshot.json     # Workday MCP tool definitions
tests/                            # pytest suite (556 tests)
roadmap_archive/                  # Historical roadmap files
```

---

## 🔗 Related

- [cursorwise](https://github.com/jon-ribera/cursorwise) — Standalone Flowise MCP server for Cursor IDE (lightweight alternative without the full agent platform)
- [Flowise](https://github.com/FlowiseAI/Flowise) — the chatflow platform this agent builds on

---

## 📄 License

MIT — [Jon Ribera](mailto:riberajon@gmail.com)
