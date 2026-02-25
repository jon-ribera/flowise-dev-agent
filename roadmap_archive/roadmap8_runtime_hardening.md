# Roadmap 8: Runtime Hardening

**Branch:** `ROADMAP8_RuntimeHardening`
**Status:** In progress — M8.0 complete, M8.1 next

---

## Context

Roadmap 7 (M7.1–M7.5) and schema hardening are complete. Live end-to-end testing
uncovered three compiler/knowledge bugs:

1. Multi-output nodes used wrong Flowise `outputAnchors` format (flat list instead
   of `type: "options"` wrapper with `outputs["output"]` selection field)
2. `_validate_flow_data` did not look inside `options[]` arrays for edge anchor IDs
3. `_normalize_api_schema` ignored the live API `outputs` field; snapshot names were
   synthesized from node type name instead of real anchor names (e.g., `"retriever"`
   vs. `"memoryVectorStore"`)

All three were fixed and committed before Roadmap 8 work began (M8.0).

Beyond the session fixes, a gap exists between the intended "knowledge-first"
architecture and actual runtime behavior:

- The discover prompt tells the LLM to call `get_node` for every node it considers,
  but does not explain that `get_node` is served from a local cache — the LLM
  sometimes skips calls and hallucinates anchor names.
- RAG chatflows silently produce HTTP 500 at Flowise runtime when `memoryVectorStore`
  has no document source; the agent has no guardrail for this constraint.
- `_compute_action` repair gating is implemented but has zero unit tests.
- AgentState has no counters for knowledge layer operations (local hits vs. API
  repairs, total `get_node` calls) — the knowledge-first contract cannot be measured.

This roadmap closes those gaps across four milestones.

---

## Scope: What Is Already Done (do not re-implement)

| Item | Location | Status |
|------|----------|--------|
| `_compute_action` version/hash repair gating | `knowledge/provider.py` L383-415 | Done |
| `_normalize_api_schema` handles `outputs` field | `knowledge/provider.py` L106-147 | Done |
| `_patch_output_anchors_from_api` in refresh.py | `knowledge/refresh.py` L265-321 | Done |
| Multi-output `options` format in compiler | `agent/compiler.py` `_build_node_data` | Done |
| Connect op sets `outputs["output"]` | `agent/compiler.py` connect handler | Done |
| `_validate_flow_data` checks inside `options[]` | `agent/tools.py` | Done |
| WriteGuard (validate-before-write + hash) | `agent/tools.py` L833-902 | Done |
| ToolResult summary caps (200-300 chars) | `agent/tools.py` | Done |
| PatternStore schema_fingerprint, last_used_at | `agent/pattern_store.py` | Done |
| PhaseMetrics with cache_hits, repair_events | `agent/metrics.py` | Done |

---

## M8.0: Commit Session Fixes (prerequisite) — COMPLETE

Committed all compiler/knowledge fixes discovered during the first live end-to-end
test, plus the `simulate_frontend.py` dev script.

| File | Change |
|------|--------|
| `flowise_dev_agent/agent/compiler.py` | Multi-output nodes -> options format; initial_outputs; Connect op sets outputs["output"] |
| `flowise_dev_agent/agent/tools.py` | `_validate_flow_data` looks inside `options[]` for anchor IDs |
| `flowise_dev_agent/knowledge/provider.py` | `_normalize_api_schema`: outputs > outputAnchors > synthesize |
| `flowise_dev_agent/knowledge/refresh.py` | `_patch_output_anchors_from_api`; called from `refresh_nodes()`; `load_dotenv()` |
| `tests/test_compiler_integration.py` | `source_anchor` for memoryVectorStore updated to `"retriever"` |
| `simulate_frontend.py` | New dev script — tracked in repo |

**Acceptance criteria (met):**
- `pytest tests/ -x -q` → 168 passed
- `python -m flowise_dev_agent.knowledge.refresh --nodes --validate` → PASS, 89 nodes patched

---

## M8.1: Discover-Prompt Alignment + RAG Guardrail (P0)

### Problem A — Prompt contradicts knowledge-first architecture

`_DISCOVER_BASE` in `graph.py` instructs the LLM to call `get_node` for every node
it plans to use, but does not clarify that all results are served from a local cache.
The LLM treats `get_node` as expensive and sometimes skips it, hallucinating anchor
names.

**Fix — `flowise_dev_agent/agent/graph.py`:**
- Prepend to `_DISCOVER_BASE`: inform the LLM that all `get_node` calls are served
  from a local schema cache with zero network calls for any of the 303 known nodes.
- Add to `_PATCH_IR_SYSTEM`: never invent anchor names or param keys — always use
  `get_node`.

### Problem B — RAG chatflows silently fail without a document source

`memoryVectorStore` requires a document loader node wired to its `document` input
anchor to initialize. Without it, Flowise returns "Expected a Runnable" (HTTP 500).

**Fix:**
- Add constraint note to `_DISCOVER_BASE` covering all vector stores.
- Add same constraint to `FLOWISE_NODE_REFERENCE.md` memoryVectorStore entry.
- Add `test_rag_with_document_source` to `tests/test_compiler_integration.py`:
  `plainText → memoryVectorStore.document`, `openAIEmbeddings → memoryVectorStore.embeddings`,
  `memoryVectorStore.retriever → conversationalRetrievalQAChain.vectorStoreRetriever`.

### Problem C — NodeSchemaStore repair gating has no unit tests

`_compute_action` logic is implemented but untested.

**New file: `tests/test_schema_repair_gating.py`**

| Case | local_ver | api_ver | Expected action |
|------|-----------|---------|-----------------|
| Same version | "2" | "2" | skip_same_version |
| Different version | "1" | "2" | update_changed_version_or_hash |
| No version, same hash | "" | "" | skip_same_version |
| No version, different hash | "" | "" | update_no_version_info |

**Acceptance criteria:**
- `pytest tests/ -x -q` → 173+ passed
- `simulate_frontend.py` plan for a RAG requirement includes a document loader node
- No hallucinated anchor names in end-to-end session logs

---

## M8.2: Tool-Call Telemetry + Session Observability (P1)

### Problem

AgentState has `total_input_tokens` / `total_output_tokens` but no counters for the
knowledge layer. Without `get_node_calls_total`, local cache hits vs. API repairs
cannot be measured — the knowledge-first contract is unverifiable at runtime.

### Work items

**1. `get_node_calls_total` counter** in `NodeSchemaStore.get_or_repair()`
(`knowledge/provider.py`):
- Increment a per-instance counter on each call.
- Store in `debug["flowise"]["get_node_calls_total"]` at end of patch phase.

**2. SessionSummary telemetry** in `api.py` response model:
- `knowledge_repair_count: int` — from `debug["flowise"]["knowledge_repair_events"]` length
- `get_node_calls_total: int` — from `debug["flowise"]["get_node_calls_total"]`
- `phase_durations_ms: dict[str, float]` — from `debug["flowise"]["phase_metrics"]`

**3. New test `test_session_summary_includes_telemetry`** in `tests/test_m74_telemetry.py`.

**Key files:** `knowledge/provider.py`, `agent/graph.py`, `api.py`, `tests/test_m74_telemetry.py`

**Acceptance criteria:**
- Session response body includes `knowledge_repair_count` and `get_node_calls_total`
- Normal session on known nodes shows `knowledge_repair_count == 0`
- `pytest tests/test_m74_telemetry.py` → all pass (existing + new)

---

## M8.3: Context Safety Gate + End-to-End Integration Test (P1)

### Problem

No regression test prevents a raw snapshot blob from leaking into LLM message
transcript. The live end-to-end flow has no CI coverage.

### Work items

**1. `tests/test_context_safety.py` (new):**
- Mock a full discover + plan session.
- Assert no message in `state["messages"]` contains raw JSON >500 chars.
- Assert `state["debug"]` values never appear in messages.

**2. `tests/test_e2e_session.py` (new):**
- `httpx.AsyncClient` against live agent (skip if `AGENT_E2E_SKIP=1`).
- Simple `conversationChain` requirement (no Flowise dependency if using mock).
- Verify: `plan_approval` interrupt, valid plan text, resume reaches `result_review`.

**3. Move `simulate_frontend.py` → `scripts/simulate_frontend.py`** (tracked in repo).

**Acceptance criteria:**
- `pytest tests/test_context_safety.py -v` passes
- `pytest tests/test_e2e_session.py -v -m "not slow"` passes with mock Flowise
- `scripts/simulate_frontend.py --no-resume` completes cleanly against live server

---

## M8.4: Pattern Maturity + Deferred DD Follow-ups (P2)

Lower priority — defer if M8.1–M8.3 take longer than expected.

### Work items (priority order)

**1. Pattern usage metrics** (highest value):
- Add `pattern_used: bool`, `pattern_id: int | None` to AgentState.
- Record whether the plan node was seeded from a pattern.
- Expose in session response; add `tests/test_pattern_metrics.py`.

**2. Snapshot rollback persistence** (DD-026 follow-up):
- Add `chatflow_snapshots` table to `sessions.db`.
- `_snapshot_chatflow()` / `_rollback_chatflow()` in `tools.py` use SQLite.
- Prune after session complete (keep last 3 per thread).

**3. Drift policy "refresh" mode** (DD-069 follow-up):
- When `FLOWISE_SCHEMA_DRIFT_POLICY=refresh` and drift detected, trigger
  `refresh_nodes()` in a background thread (once per session max).
- Record in `debug["flowise"]["schema_refresh_triggered"]`.

**Acceptance criteria:**
- `state["pattern_used"]` present in all converge-phase states
- Server restart does not lose chatflow snapshots
- `FLOWISE_SCHEMA_DRIFT_POLICY=refresh` triggers background refresh on drift

---

## Design Decisions

| DD | Summary | Milestone |
|----|---------|-----------|
| DD-071 | Knowledge-first prompt contract: `get_node` is local-first; LLM is informed explicitly | M8.1 |
| DD-072 | RAG document-source guardrail: vector stores require document anchor or runtime fails | M8.1 |
| DD-073 | Multi-output Flowise format: `options` wrapper + `outputs["output"]` selection field | M8.0 |
| DD-074 | Context safety gate: raw JSON >500 chars blocked from message transcript | M8.3 |

---

## Key Files

| File | Milestones | Action |
|------|------------|--------|
| `flowise_dev_agent/agent/graph.py` | M8.1, M8.2 | Update prompts; surface telemetry |
| `flowise_dev_agent/agent/compiler.py` | M8.0 | Committed — multi-output + Connect fixes |
| `flowise_dev_agent/agent/tools.py` | M8.0, M8.4 | Committed options[] fix; snapshot persistence |
| `flowise_dev_agent/knowledge/provider.py` | M8.0, M8.2 | Committed outputs priority; add call counter |
| `flowise_dev_agent/knowledge/refresh.py` | M8.0 | Committed `_patch_output_anchors_from_api` |
| `flowise_dev_agent/api.py` | M8.2 | Add SessionSummary telemetry fields |
| `FLOWISE_NODE_REFERENCE.md` | M8.1 | Add memoryVectorStore document-source constraint |
| `tests/test_compiler_integration.py` | M8.0, M8.1 | Committed anchor fix; add RAG+doc test |
| `tests/test_schema_repair_gating.py` | M8.1 | New — 4 repair gating cases |
| `tests/test_context_safety.py` | M8.3 | New — no snapshot blobs in transcript |
| `tests/test_e2e_session.py` | M8.3 | New — end-to-end session integration |
| `tests/test_pattern_metrics.py` | M8.4 | New — pattern_used field |
| `scripts/simulate_frontend.py` | M8.3 | Moved from root; tracked in repo |

---

## Execution Order

```
M8.0  ->  commit session fixes (prerequisite — DONE)
M8.1  ->  prompt alignment + RAG guardrail + repair gating tests       [P0]
M8.2  ->  telemetry counters + SessionSummary enrichment               [P1]
M8.3  ->  context safety test + e2e integration test                   [P1]
M8.4  ->  pattern metrics + snapshot persistence + drift refresh        [P2]
```

---

## Verification Commands

```bash
# After M8.0 (complete)
pytest tests/ -x -q                                               # 168 passed
python -m flowise_dev_agent.knowledge.refresh --nodes --validate  # PASS, 89 patched

# After M8.1
pytest tests/test_schema_repair_gating.py -v                      # 4 passed
pytest tests/test_compiler_integration.py -v                      # 10+ passed
python scripts/simulate_frontend.py --no-resume                   # plan has document loader

# After M8.2
pytest tests/test_m74_telemetry.py -v                             # all pass

# After M8.3
pytest tests/test_context_safety.py tests/test_e2e_session.py -v

# Full suite
pytest tests/ -q                                                  # 180+ passed
```
