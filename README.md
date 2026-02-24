<p align="center">
  <h1 align="center">⚡ Flowise Dev Agent</h1>
  <p align="center">
    <strong>LangGraph co-pilot for building Flowise chatflows</strong><br>
    Autonomous <strong>Clarify → Discover → Plan → Patch → Test → Converge</strong> loop
    with human-in-the-loop review at every checkpoint
  </p>
  <p align="center">
    <a href="#-quick-start">Quick Start</a> •
    <a href="#-claude-code-mcp-setup">MCP Setup</a> •
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
| 🔄 | **Autonomous build loop** | Clarify → Discover → Plan → Patch → Test → Converge with HITL at 4 checkpoints |
| 🧩 | **Patch IR compiler** | LLM emits structured ops (`AddNode / SetParam / Connect / BindCredential`); deterministic compiler resolves handle IDs — no hallucinated JSON |
| 🛡️ | **WriteGuard** | SHA-256 gate prevents any Flowise write unless the payload hash matches the validation-time hash |
| 📚 | **Pattern library** | SQLite-backed self-improvement — re-uses past successful chatflow blueprints as compile-time seeds |
| 🔌 | **Domain plugins** | `DomainCapability` ABC; Flowise + Workday Custom MCP capabilities ship out of the box |
| 🌐 | **Streaming web UI** | Real-time SSE token stream, one-click HITL approve/reject buttons, session sidebar — no build step |

---

## 🚀 Quick Start

### 1. Local Web UI (recommended)

```bash
cp .env.example .env
# Edit .env: set FLOWISE_API_KEY, FLOWISE_API_ENDPOINT, ANTHROPIC_API_KEY

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

## 🔌 Claude Code MCP Setup

Connect [cursorwise](https://github.com/jon-ribera/cursorwise) to Claude Code so the AI can build and manage Flowise chatflows directly from the IDE.

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed (`uvx` available in PATH)
- Flowise running and accessible (default: `http://localhost:3000`)
- A Flowise API key — generate one at **Flowise → top-right menu → API Keys → Add New Key**

### 1. Configure the MCP server

Copy the example config and fill in your values:

```bash
cp .mcp.json.example .mcp.json
```

Edit `.mcp.json`:

```json
{
  "mcpServers": {
    "cursorwise": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/jon-ribera/cursorwise.git", "cursorwise"],
      "env": {
        "FLOWISE_API_KEY": "your-flowise-api-key",
        "FLOWISE_API_ENDPOINT": "http://localhost:3000",
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

> **Windows users:** If `uvx` is not found by the extension, replace `"command": "uvx"` with the full path to `uvx.exe`, e.g. `"C:/Users/<you>/AppData/Local/uv/uvx.exe"`. Find it with `where uvx` in a terminal.

### 2. Enable auto-approval in `.claude/settings.local.json`

```json
{
  "enableAllProjectMcpServers": true
}
```

### 3. Reload the window

`Ctrl+Shift+P` → **Developer: Reload Window**

Verify the connection with `/mcp` in the chat — `cursorwise` should show as connected.

### Configuration reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `FLOWISE_API_KEY` | Yes | — | Bearer token for Flowise API |
| `FLOWISE_API_ENDPOINT` | No | `http://localhost:3000` | Flowise instance URL |
| `FLOWISE_TIMEOUT` | No | `120` | HTTP timeout in seconds |
| `PYTHONUNBUFFERED` | No | `1` | Recommended — ensures MCP log output is not buffered |

> `.mcp.json` contains secrets — it is gitignored. Never commit it. Share `.mcp.json.example` instead.

---

## ⚙️ Configuration

Set via environment variables or a `.env` file. See [.env.example](.env.example) for the full template.

| Variable | Required | Default | Description |
|---|---|---|---|
| 🌐 `FLOWISE_API_ENDPOINT` | ✅ Yes | `http://localhost:3000` | Flowise server URL |
| 🔑 `FLOWISE_API_KEY` | ✅ Yes | — | Flowise API key |
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
| 🏃 `FLOWISE_COMPAT_LEGACY` | No | `false` | Set `true` to run the pre-refactor ReAct patch path |
| 📐 `FLOWISE_SCHEMA_DRIFT_POLICY` | No | `warn` | `warn` \| `fail` \| `refresh` on schema fingerprint mismatch |

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
  │CHECK CREDS  │  INTERRUPT if required credentials are missing from Flowise
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │    PLAN     │  Structured plan: Goal / Inputs / Outputs / Pattern / Success Criteria
  └──────┬──────┘
         │
  ⏸ INTERRUPT: plan_approval  ← Developer reviews and approves (or requests changes)
         │
  ┌──────▼──────┐
  │    PATCH    │  Snapshot → Patch IR ops → deterministic compiler → WriteGuard → write
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │    TEST     │  Happy-path + edge-case predictions with unique sessionIds
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │   CONVERGE  │  Structured verdict: DONE or ITERATE with Category / Reason / Fix
  └──────┬──────┘
         │ DONE
  ⏸ INTERRUPT: result_review  ← Developer accepts or requests another iteration
         │ accepted
        END
```

### Patch IR + Deterministic Compiler

The `patch` node runs a 5-step pipeline:

1. **Snapshot** — save the existing chatflow before any changes
2. **LLM emits ops only** — `AddNode / SetParam / Connect / BindCredential` in JSON; no handle IDs, no edge IDs
3. **IR validation** — `validate_patch_ops()` catches dangling refs and duplicate node IDs before compilation
4. **Deterministic compiler** — `compile_patch_ops()` reads the existing chatflow as a `GraphIR`, resolves anchor handle IDs from node schemas, and produces `flowData + payload_hash + diff_summary`
5. **WriteGuard** — `create_chatflow / update_chatflow` are blocked unless the payload hash matches the hash recorded at validation time

### Evaluator-Optimizer Feedback Loop

The `converge` node classifies failures and injects targeted fix instructions into
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
pattern library. On subsequent sessions with similar requirements, `discover` finds the
matching pattern and seeds the compiler with it — reducing AddNode op count and token
usage. Set `test_trials: 2+` for pass^k reliability testing across multiple runs.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────┐
│  flowise-dev-agent  (this repo)                      │
│                                                      │
│  FastAPI  (14 endpoints + SSE streaming)             │
│       │                                              │
│  LangGraph StateGraph  (9 nodes)                     │
│  ├── clarify · discover · check_credentials          │
│  ├── plan · human_plan_approval                      │
│  ├── patch · test · converge · human_result_review   │
│       │                                              │
│  DomainCapability layer                              │
│  ├── FlowiseCapability  — discover + compile_ops     │
│  └── WorkdayCapability  — Custom MCP blueprint wiring│
│                                                      │
│  Patch IR + compiler                                 │
│  ├── patch_ir.py   — AddNode / SetParam /            │
│  │                   Connect / BindCredential        │
│  └── compiler.py   — GraphIR + compile_patch_ops()  │
│                                                      │
│  Platform Knowledge Layer                            │
│  ├── NodeSchemaStore   — flowise_nodes.snapshot.json │
│  ├── CredentialStore   — flowise_credentials.snapshot│
│  └── WorkdayMcpStore   — workday_mcp.snapshot.json   │
│                                                      │
│  SQLite                                              │
│  ├── sessions.db   — LangGraph checkpoint store      │
│  └── patterns.db   — chatflow pattern library        │
└────────────────────────┬─────────────────────────────┘
                         │  pip dependency
┌────────────────────────▼─────────────────────────────┐
│  cursorwise  (separate repo)                         │
│  FlowiseClient — 52 async methods                    │
│  MCP Server   — 50 tools for Cursor IDE              │
└────────────────────────┬─────────────────────────────┘
                         │  HTTP REST API
┌────────────────────────▼─────────────────────────────┐
│  Flowise Server  (localhost:3000 or remote)          │
└──────────────────────────────────────────────────────┘
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
| 📐 [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) | 70 architectural decisions — the authoritative rationale log (DD-001 – DD-070) |
| ✅ [roadmap_shipped.md](roadmap_shipped.md) | All shipped milestones with DD cross-references and original roadmap traceability |
| 🗂️ [roadmap_pending.md](roadmap_pending.md) | Open backlog items — each traceable to its source roadmap and next DD number |
| 📊 [PERFORMANCE.md](PERFORMANCE.md) | Token cost analysis, root cause of quadratic context growth, and optimization strategies |
| 📄 [.env.example](.env.example) | Full environment variable template with inline documentation |
| 🗄️ [roadmap_archive/](roadmap_archive/) | Historical roadmap files (source-code docstrings reference these filenames) |

**Key design decisions at a glance:**

| DD | Decision |
|---|---|
| DD-019 | Structured converge verdicts — evaluator-optimizer feedback loop |
| DD-048 | `ToolResult` envelope — compact context enforcement at `execute_tool` boundary |
| DD-051 | Patch IR schema — LLM emits ops, compiler derives handle IDs deterministically |
| DD-052 | WriteGuard — SHA-256 hash gate before every Flowise write |
| DD-066 | Capability-first default + `FLOWISE_COMPAT_LEGACY` escape hatch |

---

## 🗂️ Project Structure

```
flowise_dev_agent/
├── api.py                        # FastAPI endpoints + SSE streaming
├── agent/
│   ├── graph.py                  # LangGraph StateGraph (9 nodes)
│   ├── domain.py                 # DomainCapability ABC + result models
│   ├── patch_ir.py               # AddNode / SetParam / Connect / BindCredential
│   ├── compiler.py               # GraphIR + compile_patch_ops()
│   ├── plan_schema.py            # PlanContract dataclass
│   ├── metrics.py                # PhaseMetrics + MetricsCollector
│   ├── pattern_store.py          # SQLite pattern library
│   ├── registry.py               # ToolRegistry v2 (namespaced + dual-key)
│   ├── state.py                  # AgentState TypedDict
│   ├── tools.py                  # DomainTools + ToolResult + execute_tool
│   └── domains/
│       └── workday.py            # WorkdayCapability (Custom MCP blueprint wiring)
├── knowledge/
│   ├── provider.py               # NodeSchemaStore + CredentialStore
│   ├── workday_provider.py       # WorkdayMcpStore + WorkdayApiStore
│   └── refresh.py                # CLI: python -m flowise_dev_agent.knowledge.refresh
├── skills/
│   └── flowise_builder.md        # Active skill: chatflow construction rules
├── static/
│   └── index.html                # Single-file web UI (no build step)
└── cli.py                        # flowise-agent-cli entry point
schemas/                          # Local-first snapshots (refresh with CLI above)
├── flowise_nodes.snapshot.json
├── flowise_credentials.snapshot.json
└── workday_mcp.snapshot.json
tests/                            # pytest suite (159 tests)
roadmap_archive/                  # Historical roadmap files
```

---

## 🔗 Related

- [cursorwise](https://github.com/jon-ribera/cursorwise) — Flowise MCP server for Cursor IDE (pip dependency)
- [Flowise](https://github.com/FlowiseAI/Flowise) — the chatflow platform this agent builds on

---

## 📄 License

MIT — [Jon Ribera](mailto:riberajon@gmail.com)
