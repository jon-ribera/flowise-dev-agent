# Roadmap: Shipped

All items in this file have a corresponding Design Decision (DD) entry in
[DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) — the authoritative source of record.
**DD present = shipped and live.** Source-code inline docstrings reference the
original roadmap filenames below; those filenames are preserved as-is.

Next available DD number: **DD-071**

---

## ROADMAP.md — Core MVP + Production Hardening

> Original file: `ROADMAP.md`
> Design Decisions: **DD-001 – DD-032**

All core MVP functionality and production hardening items from the original
roadmap are shipped. Key decision groups:

| DD Range | Topic |
|----------|-------|
| DD-001 – DD-010 | Initial agent graph, LangGraph wiring, FastAPI skeleton |
| DD-011 – DD-020 | AsyncSqlite session store, HITL interrupt points, Flowise HTTP client |
| DD-021 – DD-028 | Compiler (GraphIR), schema validation, error repair loop |
| DD-029 – DD-032 | Production hardening: logging, exception boundaries, state serialization |

See DESIGN_DECISIONS.md §DD-001 through §DD-032 for full rationale.

---

## ROADMAP2.md — Next-Wave Enhancements

> Original file: `ROADMAP2.md`
> Design Decisions: **DD-033 – DD-040**

All eight next-wave enhancements are shipped.

| DD | Feature |
|----|---------|
| DD-033 | Multi-session isolation (per-session SQLite row, no shared mutable state) |
| DD-034 | Rate limiting via `slowapi` (removed `__future__` annotations for FastAPI compat) |
| DD-035 | Input validation — Pydantic models on all API endpoints |
| DD-036 | Four HITL interrupt points: `clarify`, `credentials`, `plan_approval`, `result_review` |
| DD-037 | Pattern store (SQLite) — save/load successful chatflow patterns |
| DD-038 | Template hints — injected into plan node system prompt |
| DD-039 | Schema repair loop — `flowise_nodes.snapshot.json` fallback when live API fails |
| DD-040 | `GraphIR` compiler — structured intermediate representation for patch operations |

See DESIGN_DECISIONS.md §DD-033 through §DD-040.

> **Note:** DD-041 – DD-045 are absent from DESIGN_DECISIONS.md (reserved range, unused).

---

## roadmap3_architecture_optimization.md — Architecture Optimization

> Original file: `roadmap3_architecture_optimization.md`
> Source-code inline refs: `"See roadmap3_architecture_optimization.md — Milestone X."`
> **Do not rename this file** — inline docstrings in 17+ Python files reference it.

### Milestone 1 — v2 Abstractions (DD-046 – DD-050)

| DD | Item |
|----|------|
| DD-046 | `DomainCapability` ABC as primary domain abstraction |
| DD-047 | `WorkdayCapability` stub-first (real implementation in M7.5) |
| DD-048 | `ToolResult` single transformation point (`_wrap_result` in `tools.py`) |
| DD-049 | Dual-key executor (`"flowise.get_node"` + `"get_node"`) for backwards compat |
| DD-050 | State trifurcation: `artifacts` / `facts` / `debug` with `_merge_domain_dict` reducer |

### Milestone 2 — Patch IR Compiler (DD-051 – DD-052)

| DD | Item |
|----|------|
| DD-051 | `PatchIR` schema (`AddNode`, `SetParam`, `Connect`, `BindCredential` dataclasses) |
| DD-052 | `compile_ops()` real implementation replacing stubs; `validate_patch_ops()` guard |

> **Note:** DD-053 – DD-058 are absent from DESIGN_DECISIONS.md (reserved range, unused).

### Milestone 3 — Status
Milestone 3 (live Workday MCP discover, cross-domain plan node) was partially
superseded by Roadmap 7 M7.5 (DD-070). Outstanding M3 items that were NOT
superseded are tracked in [roadmap_pending.md](roadmap_pending.md).

---

## roadmap6_ui_iteration_fixes.md — UI Iteration Fixes

> Original file: `roadmap6_ui_iteration_fixes.md`
> Design Decisions: **DD-059 – DD-061**
> **Status: ALL items shipped** (file header still shows "pending" — this table is authoritative)

| DD | Change |
|----|--------|
| DD-059 | C1: Static UI overhaul (dark theme, collapsible panels); C2: session list live-reload; C3: debug panel toggle |
| DD-060 | C4: Chatflow context card (active chatflow name + ID displayed in UI) |
| DD-061 | C5: HITL interrupt rendering (inline approval/rejection buttons in chat) |

See DESIGN_DECISIONS.md §DD-059 through §DD-061.

---

## ROADMAP6_Platform Knowledge.md — Platform Knowledge Layer

> Original file: `ROADMAP6_Platform Knowledge.md`
> Design Decisions: **DD-062 – DD-065**

| DD | Item |
|----|------|
| DD-062 | `NodeSchemaStore` — local-first snapshot of Flowise node schemas (`flowise_nodes.snapshot.json`) |
| DD-063 | `CredentialStore` — local-first snapshot of credential types (`flowise_credentials.snapshot.json`) |
| DD-064 | `PatternStore` keyword-enhanced search (LIKE queries over `keywords` column) |
| DD-065 | `WorkdayKnowledgeProvider` scaffold + `WorkdayMcpStore` (real implementation delivered in M7.5 / DD-070) |

See DESIGN_DECISIONS.md §DD-062 through §DD-065.

---

## roadmap7_multi_domain_runtime_hardening.md — Multi-Domain Runtime Hardening

> Original file: `roadmap7_multi_domain_runtime_hardening.md`
> Design Decisions: **DD-066 – DD-070**
> **All five milestones complete as of 2026-02-23.**

### M7.1 — Capability-First Default Runtime (DD-066)

- `FLOWISE_COMPAT_LEGACY` env var controls legacy vs. capability-first routing
- `runtime_mode` field added to `AgentState` and exposed in `SessionSummary`
- Default (no env var): capability-first path via `_make_patch_node_v2`

### M7.2 — Cross-Domain PlanContract + TestSuite (DD-067)

- `PlanContract` dataclass (`plan_schema.py`): `goal`, `domain_targets`, `credential_requirements`, `data_fields`, `pii_fields`, `success_criteria`, `action`, `raw_plan`
- Plan node parses structured sections (`## DOMAINS`, `## CREDENTIALS`, `## DATA_CONTRACTS`) from LLM output
- `TestSuite` extended with `domain_scopes` and `integration_tests`
- Converge node verdict grounded in `success_criteria` from plan contract

### M7.3 — PatternCapability Upgrade (DD-068)

- SQLite `patterns` table migration: added `domain`, `node_types`, `category`, `schema_fingerprint`, `last_used_at` columns
- `search_patterns_filtered()` — SQL-level domain + category filtering
- `apply_as_base_graph()` — seeds `GraphIR` from a saved pattern (pattern → compile-time asset)
- Patch v2 Phase A reads `artifacts["flowise"]["base_graph_ir"]` when no live chatflow exists

### M7.4 — Drift Management + Telemetry Hardening (DD-069)

- `PhaseMetrics` dataclass + `MetricsCollector` async context manager (`metrics.py`)
- Per-phase timing, token counts, tool call counts, cache hits, repair events
- `FLOWISE_SCHEMA_DRIFT_POLICY` env var: `warn` | `fail` | `refresh`
- `NodeSchemaStore.meta_fingerprint` property; fingerprint recorded in `facts["flowise"]`
- `SessionSummary` exposes `total_repair_events` + `total_phases_timed`

### M7.5 — Workday MCP-in-Flowise (DD-070)

- `WorkdayMcpStore` real implementation: lazy `_load()`, O(1) `get(blueprint_id)`, keyword-scored `find(tags)`, `is_stale()`, `item_count`
- `schemas/workday_mcp.snapshot.json` populated with `workday_default` blueprint
- `WorkdayCapability.discover()`: blueprint-driven (no live MCP calls); falls back to module defaults if snapshot empty
- `WorkdayCapability.compile_ops()`: deterministic Patch IR — `AddNode` (Tool node, `selectedTool="customMCP"`, `mcpServerConfig` as STRINGIFIED JSON) + `BindCredential` (`credential_type="workdayOAuth"`, placeholder resolved at patch time)
- `refresh_workday_mcp()` writes default blueprint + meta with fingerprint
- 46 smoke tests in `tests/test_workday_mcp_integration.py`

See DESIGN_DECISIONS.md §DD-066 through §DD-070.

---

## Quick Reference: DD ↔ Roadmap Index

| DD Range | Roadmap File |
|----------|-------------|
| DD-001 – DD-032 | `ROADMAP.md` |
| DD-033 – DD-040 | `ROADMAP2.md` |
| DD-041 – DD-045 | *(reserved/unused)* |
| DD-046 – DD-052 | `roadmap3_architecture_optimization.md` |
| DD-053 – DD-058 | *(reserved/unused)* |
| DD-059 – DD-061 | `roadmap6_ui_iteration_fixes.md` |
| DD-062 – DD-065 | `ROADMAP6_Platform Knowledge.md` |
| DD-066 – DD-070 | `roadmap7_multi_domain_runtime_hardening.md` |
