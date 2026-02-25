# Roadmap: Shipped

All items in this file have a corresponding Design Decision (DD) entry in
[DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) — the authoritative source of record.
**DD present = shipped and live.** Source-code inline docstrings reference the
original roadmap filenames below; those filenames are preserved as-is.

Next available DD number: **DD-082**

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

## roadmap8_runtime_hardening.md — Runtime Hardening

> Original file: `roadmap8_runtime_hardening.md`
> Design Decisions: **DD-071 – DD-074**
> **All four milestones complete as of 2026-02-24.**

### M8.0 — Session Fixes (DD-073)

- Multi-output Flowise node format: `outputAnchors` with `type: "options"` wrapper + `outputs["output"]` selection field (`compiler.py`)
- `_validate_flow_data` looks inside `options[]` arrays for edge anchor IDs (`tools.py`)
- `_normalize_api_schema`: priority order `outputs` (live API) > `outputAnchors` (legacy) > synthesized (`provider.py`)
- `_patch_output_anchors_from_api`: post-parse enrichment of 89 nodes with real output anchor names from live API (`refresh.py`)
- `scripts/simulate_frontend.py`: three-step frontend simulation script (plan → approve → accept)

### M8.1 — Discover-Prompt Alignment + RAG Guardrail (DD-071, DD-072)

- `_DISCOVER_BASE` (graph.py): informs LLM that all `get_node` results are served from a local cache — 303 nodes, zero network calls; explicit RAG document-source constraint added
- `_PATCH_IR_SYSTEM` (graph.py): rule 7 — anchor/param names must come from `get_node`, never invented
- `FLOWISE_NODE_REFERENCE.md`: RUNTIME CONSTRAINT block on `memoryVectorStore` entry
- `flowise_builder.md` Rule 7: RAG document-source constraint propagated to the skill file
- `test_rag_with_document_source`: full `plainText → memoryVectorStore → conversationalRetrievalQAChain` integration test
- `tests/test_schema_repair_gating.py`: 5 unit tests covering all `_compute_action` return values

### M8.2 — Knowledge-Layer Telemetry (DD-071)

- `NodeSchemaStore._call_count`: increments on every `get_or_repair` call (hits + misses)
- `graph.py` patch node: writes `get_node_calls_total` to `debug["flowise"]` after Phase D
- `SessionSummary` gains three new fields: `knowledge_repair_count`, `get_node_calls_total`, `phase_durations_ms`
- `list_sessions()` populates all three from debug state

### M8.3 — Context Safety Gate + E2E Integration Test (DD-074)

- `tests/test_context_safety.py`: 11 tests — `result_to_str` contract; no raw JSON >500 chars in transcript; `ToolResult.data` never reaches message content
- `tests/test_e2e_session.py`: 6 tests against live server; skips via `AGENT_E2E_SKIP=1`; `@pytest.mark.slow` registered in `pyproject.toml`
- `simulate_frontend.py` moved from repo root to `scripts/`

See DESIGN_DECISIONS.md §DD-071 through §DD-074.

---

## roadmap9_production_graph_runtime_hardening.md — Production Graph + Runtime Hardening

> Original file: `roadmap9_production_graph_runtime_hardening.md`
> Design Decisions: **DD-075 – DD-081**
> **P0 (M9.3, M9.4, M9.5), P1 (M9.1, M9.2), and P2 partial (M9.6, M9.9) complete.**
> M9.7 (telemetry polish) and M9.8 (compact-context audit) remain pending.

### M9.3 — Knowledge-First Runtime Contract Alignment (DD-075)

- `_DISCOVER_BASE` (graph.py): "NODE SCHEMA CONTRACT (M9.3)" block — schemas are pre-loaded; patch phase resolves automatically; do NOT call `get_node` during discover
- `_FLOWISE_DISCOVER_CONTEXT` (tools.py): removed per-node `get_node` instruction; added explicit "Do NOT call get_node during discover" guidance
- `get_node` tool description: split DISCOVER PHASE (do not call) / PATCH PHASE (call freely)
- `_MAX_SCHEMA_REPAIRS = 10` (graph.py): budget constant capping targeted API repair calls per patch iteration
- `_repair_schema_for_ops()` (graph.py): standalone async function extracted from Phase D; fast path (cache hit) = zero API calls; slow path (cache miss) = one targeted `get_node` call; budget enforced
- Phase D of `_make_patch_node_v2`: delegates to `_repair_schema_for_ops()`; M8.2 telemetry retained
- `tests/test_m93_knowledge_first.py`: 11 unit tests (prompt contract + repair function behaviour)

### M9.5 — NodeSchemaStore Repair Gating Correctness (DD-076)

- `_compute_action()` in `knowledge/provider.py`: skip_same_version / update_changed_version_or_hash / update_no_version_info / skip_same_hash — four-case gating matrix
- Repair only overwrites when justified by version change or hash mismatch
- `tests/test_m95_repair_gating.py`: 5 unit tests covering all action branches

### M9.4 — Refresh Reproducibility (DD-077)

- `_patch_output_anchors_from_api()` in `knowledge/refresh.py`: post-parse enrichment of output anchor names from live Flowise API (called from `refresh_nodes()`)
- `load_dotenv()` called at top of `refresh.py` so `FLOWISE_API_KEY` resolves from `.env`
- `tests/test_m94_refresh_reproducibility.py`: refresh round-trip tests

### M9.1 — Postgres-Only Persistence (DD-078)

- `flowise_dev_agent/persistence/__init__.py`: exports `CheckpointerAdapter`, `make_checkpointer`, `EventLog`, `wrap_node`
- `flowise_dev_agent/persistence/checkpointer.py`: `CheckpointerAdapter` + `make_checkpointer` (Postgres-only, no fallback)
- `flowise_dev_agent/persistence/event_log.py`: `EventLog` (`session_events` table, fire-and-forget inserts)
- `docker-compose.postgres.yml`: Postgres 16 local service
- `pyproject.toml`: added `langgraph-checkpoint-postgres>=2.0`, `psycopg[binary]>=3.1`
- `api.py`: `POSTGRES_DSN` env var; lifespan uses `make_checkpointer` + `EventLog`
- `tests/test_m91_postgres_persistence.py`: 17 tests

### M9.2 — Node-Level SSE Streaming (DD-079)

- `flowise_dev_agent/persistence/hooks.py`: `wrap_node`, `_node_summary`, `_NODE_PHASES`, `_INTERRUPT_CLASS_NAMES`
- `flowise_dev_agent/agent/graph.py`: `build_graph` gains `emit_event=None` + `_w()` helper wrapping all nodes
- `flowise_dev_agent/api.py`: `GET /sessions/{id}/stream` SSE endpoint; `_format_event_as_sse`; `_session_is_done`
- SSE event types: `node_start`, `node_end`, `node_error`, `interrupt`, `done`
- `tests/test_m92_sse_streaming.py`: 27 tests

### M9.6 — Production-Grade LangGraph Topology v2 (DD-080)

- 18-node v2 topology replacing 9-node v1; v1 code fully removed
- CREATE mode: Phases A + D–F; UPDATE mode: all 6 phases
- `_build_graph_v2()` private function with `_w2()` wrapper for SSE integration
- `_summarize_flow_data()`: deterministic compact summary (no LLM, no blob leakage)
- `_repair_schema_local_sync()`: sync local-only schema repair for v2 repair_schema node
- `facts["budgets"]`: graph-level budget enforcement at `preflight_validate_patch`
- Schema-repair bounded retry: one retry then HITL (no runaway loops)
- New state fields: `operation_mode`, `target_chatflow_id`, `intent_confidence`
- `_NODE_PHASES` and `_node_summary` in `hooks.py` fully rewritten for 18 v2 node names
- `api.py`: `_NODE_PROGRESS` updated to v2 nodes only; `_initial_state` includes M9.6 fields
- `tests/test_m96_topology_v2.py`: 13 tests

### M9.9 — PatternCapability Maturity (DD-081)

- `_is_pattern_schema_compatible(pattern, fingerprint)`: schema-compat guard in `pattern_store.py`
- `_infer_category_from_node_types(node_types)`: rag/tool_agent/conversational/custom inference
- `last_used_at` ISO-8601 timestamps returned from `search_patterns_filtered()`
- UPDATE mode guard in plan node: patterns NOT seeded when `operation_mode == "update"`
- `debug["flowise"]["pattern_metrics"]`: `{pattern_used, pattern_id, ops_in_base}` per session
- New state fields: `pattern_used: bool`, `pattern_id: int | None`
- `api.py`: `_initial_state` includes `pattern_used: False`, `pattern_id: None`
- `tests/test_m99_pattern_tuning.py`: 5 tests

See DESIGN_DECISIONS.md §DD-075 through §DD-081.

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
| DD-071 – DD-074 | `roadmap8_runtime_hardening.md` |
| DD-075 – DD-081 | `roadmap9_production_graph_runtime_hardening.md` |
