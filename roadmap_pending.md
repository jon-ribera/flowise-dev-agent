# Roadmap: Pending

Items in this file have **no corresponding Design Decision (DD)** in
[DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) — the authoritative source of record.
**No DD = not yet implemented.**

When an item is shipped, add a DD entry to DESIGN_DECISIONS.md and move the
item to [roadmap_shipped.md](roadmap_shipped.md).

Next available DD number: **DD-082**

---

## roadmap3_architecture_optimization.md — Milestone 3 Remnants

> Original file: `roadmap3_architecture_optimization.md`
> Milestone 3 was partially superseded by Roadmap 7 M7.5 (DD-070).
> Items below were NOT covered by any shipped DD.

### M3-A: Live Workday MCP Tool Discovery (no DD)

Blueprint-driven discovery (DD-070) covers the static case. The dynamic case
remains open:

- **Live `tools/list` call** to the Workday MCP server at discover time (requires
  a real `WORKDAY_MCP_SERVER_URL` to be configured)
- Per-tenant action filtering based on which MCP tools the server exposes
- `WorkdayCapability.discover()` currently falls back to the
  `workday_default` blueprint regardless of what the live MCP server offers

**Prerequisite:** A real Workday MCP server endpoint (tenant-configured URL +
OAuth token) must be available in the deployment environment.

### M3-B: `workday_extend.md` Skill File (no DD)

A `/extend` or `/workday-extend` slash-command skill file was planned for
Milestone 3 to let users activate Workday MCP wiring interactively. Not yet
created.

**Files to create:**
- `flowise_dev_agent/skills/workday_extend.md` — skill definition for
  activating `WorkdayCapability` via a slash command

---

## roadmap4_workday_cross_domain.md — Multi-Domain Enhancements

> Original file: `roadmap4_workday_cross_domain.md`
> No DDs exist for any Milestone 4 item.

### M4.1 — Live Workday Async Callables (no DD)

The stub tools in `WorkdayDomainTools` (`get_worker`, `list_business_processes`)
return hardcoded placeholder data. Real async callables are not yet wired.

**Open items:**
- Replace `_stub_get_worker()` / `_stub_list_business_processes()` with real
  HTTP calls to the Workday REST API (or through the MCP server)
- Add `[LIVE]` / `[STUB]` markers to `ToolDef.description` to make stub status
  machine-readable
- `WorkdayApiStore` (currently raises `NotImplementedError` on all methods)
  needs a real snapshot + loader

**Files to modify:**
- `flowise_dev_agent/agent/domains/workday.py` — replace stub executors
- `flowise_dev_agent/knowledge/workday_provider.py` — implement `WorkdayApiStore`
- `schemas/workday_api.snapshot.json` — populate with Workday API endpoint catalog

### M4.2 — Cross-Domain Planner (no DD)

The plan node produces a single freeform markdown plan. A cross-domain planner
would route to multiple `DomainCapability` instances per session.

**Open items:**
- `active_domain` routing in the graph: after plan node identifies
  `domain_targets`, dispatch discover + patch phases per domain
- Per-domain patch node (not just Flowise-side): Workday patch operations run
  concurrently with Flowise patch operations
- Per-domain converge: each domain produces a verdict; overall session is DONE
  only when all domain verdicts are DONE
- Integration: `PlanContract.domain_targets` (DD-067) already parses the domains;
  the graph routing to act on them is the missing piece

**Files to modify:**
- `flowise_dev_agent/agent/graph.py` — conditional edge routing based on
  `domain_targets`; multi-domain patch + converge fan-out

### M4.3 — PatternCapability Full Domain Migration (no DD)

DD-068 (M7.3) added structured metadata columns and `apply_as_base_graph()` to
`PatternStore`. The remaining M4.3 items are:

- `PatternCapability` as a proper `DomainCapability` subclass (currently
  patterns are handled inline in graph.py, not via the capability interface)
- Pattern-seeded compile: when `base_graph_ir` is loaded from a pattern, the
  Patch IR diff should only emit delta ops rather than full AddNode/Connect
  sequences (reduces op count and LLM token usage)
- Cross-domain pattern support: a pattern can span Flowise + Workday nodes;
  `apply_as_base_graph()` returns a multi-domain `GraphIR`

**Files to modify:**
- `flowise_dev_agent/agent/graph.py` — extract pattern handling into a
  `PatternCapability` class
- `flowise_dev_agent/agent/pattern_store.py` — delta-diff between base IR
  and compiled IR

### G4 — Workday Extend Skill File (same as M3-B above)

Tracked under M3-B; listed here for cross-reference with `roadmap4_workday_cross_domain.md`.

---

## roadmap5_embedded_ux.md — Embedded UX Enhancements

> Original file: `roadmap5_embedded_ux.md`
> No DDs exist for any Milestone 5 item.

### M5.1 — Blocking `/sessions/complete` Endpoint + `auto_approve` Flag (no DD)

The current API only exposes polling (`GET /sessions/{id}`) to wait for a
session to finish. A blocking endpoint and auto-approve flag are not yet
implemented.

**Open items:**
- `POST /sessions/{id}/complete` — blocks (long-poll or SSE) until the session
  reaches a terminal state (`DONE`, `FAILED`, `AWAITING_HITL`)
- `auto_approve: bool` request field — automatically approves all HITL interrupt
  points (plan approval, result review) without human input; useful for CI/CD
  pipelines and embedded UX flows

**Files to modify:**
- `flowise_dev_agent/api.py` — add `/sessions/{id}/complete` route; add
  `auto_approve` to the session creation request model

### M5.2 — Custom Tool JS Template Generation (no DD)

The agent can design Flowise chatflows but cannot yet generate the JavaScript
code for a custom Flowise Tool node.

**Open items:**
- Given a tool description in the plan, emit a JS function template
  compatible with Flowise's `CustomTool` node format
- Template includes input schema, output schema, and a TODO body
- Surfaced via a new `artifacts["flowise"]["custom_tool_js"]` key

**Files to modify / create:**
- `flowise_dev_agent/agent/graph.py` — plan node or patch node emits
  `custom_tool_js` to artifacts
- `flowise_dev_agent/templates/custom_tool.js.jinja` — template file

### M5.3 — TypeScript INode Implementation (no DD)

For teams building their own Flowise node plugins, the agent was planned to
generate a TypeScript `INode` class scaffold.

**Open items:**
- TypeScript class scaffold matching the Flowise `INode` interface
- Includes `inputs`, `outputs`, `credential`, and `run()` body stubs
- Emitted to `artifacts["flowise"]["inode_typescript"]`

**Files to create:**
- `flowise_dev_agent/templates/inode.ts.jinja` — INode template
- `flowise_dev_agent/agent/codegen.py` — template renderer

### M5.4 — Deployment Guide (no DD)

A production deployment guide covering Docker, Nginx, and systemd was planned
but not yet written.

**Open items:**
- `docs/deployment.md` — step-by-step guide for:
  - Docker Compose setup (API + SQLite volume)
  - Nginx reverse-proxy config with TLS termination
  - systemd service unit for auto-restart
  - Environment variable reference (`FLOWISE_API_URL`, `FLOWISE_API_KEY`,
    `FLOWISE_COMPAT_LEGACY`, `FLOWISE_SCHEMA_DRIFT_POLICY`, etc.)
  - Backup and restore for `sessions.db` + `schemas/` snapshots

**Files to create:**
- `docs/deployment.md`
- `docker-compose.yml` (or update if it already exists)

---

## Summary Table

| Item | Source Roadmap | Prerequisite / Blocker |
|------|---------------|----------------------|
| M3-A: Live MCP tool discovery | `roadmap3_architecture_optimization.md` | Real Workday MCP server URL |
| M3-B: `workday_extend.md` skill | `roadmap3_architecture_optimization.md` | None |
| M4.1: Live Workday async callables | `roadmap4_workday_cross_domain.md` | Real Workday API credentials |
| M4.2: Cross-domain planner routing | `roadmap4_workday_cross_domain.md` | M4.1 callables + DD-067 plan contract |
| M4.3: PatternCapability domain migration | `roadmap4_workday_cross_domain.md` | DD-068 (shipped); delta-diff work open |
| G4: Workday extend skill | `roadmap4_workday_cross_domain.md` | Same as M3-B |
| M5.1: Blocking endpoint + auto_approve | `roadmap5_embedded_ux.md` | None |
| M5.2: Custom Tool JS template | `roadmap5_embedded_ux.md` | None |
| M5.3: TypeScript INode scaffold | `roadmap5_embedded_ux.md` | None |
| M5.4: Deployment guide | `roadmap5_embedded_ux.md` | None |

---

## Completion Checklist

When implementing any item above:

1. Implement the feature.
2. Write tests (regression: `pytest tests/ -q` must stay green).
3. Add a DD entry in [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) using the
   next available DD number (currently **DD-076**).
4. Move the item from this file to [roadmap_shipped.md](roadmap_shipped.md)
   under the appropriate original roadmap section.
5. Update the DD index table in `roadmap_shipped.md`.
6. Update [MEMORY.md](../.claude/projects/c--Users-jon-ribera-Desktop-FloWiseDevAgent/memory/MEMORY.md)
   with the new milestone completion note.
