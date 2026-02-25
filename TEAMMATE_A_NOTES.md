# Teammate A Notes — M9.6 Topology v2

Implementation of Milestone 9.6: Production-Grade LangGraph Topology v2 (CREATE + UPDATE modes).

---

## Files Modified

| File | Change |
|------|--------|
| `flowise_dev_agent/agent/state.py` | Added 3 new AgentState fields (operation_mode, target_chatflow_id, intent_confidence) |
| `flowise_dev_agent/agent/graph.py` | Added 18-node v2 topology, all node factories, routing functions, _summarize_flow_data, _repair_schema_for_ops |
| `flowise_dev_agent/api.py` | Added M9.6 fields to _initial_state(); added v2 node names to _NODE_PROGRESS |
| `tests/test_m96_topology_v2.py` | New test file with 12 tests covering all 7 required scenarios |

---

## New Node Names (for Teammate B to add metrics to)

Phase A:
- `classify_intent`
- `hydrate_context`

Phase B (UPDATE path only):
- `resolve_target`
- `hitl_select_target`

Phase C (UPDATE path only):
- `load_current_flow`
- `summarize_current_flow`

Phase D:
- `plan_v2`
- `hitl_plan_v2`
- `define_patch_scope`
- `compile_patch_ir`
- `compile_flow_data`

Phase E:
- `validate`
- `repair_schema`

Phase F:
- `preflight_validate_patch`
- `apply_patch`
- `test_v2`
- `evaluate`
- `hitl_review_v2`

---

## New Facts Keys Used (for Teammate B's session summary)

### facts["flowise"] (extended):
- `intent` — "create" | "update"
- `target_name` — str | None (chatflow name from classify_intent)
- `schema_fingerprint` — str (from local NodeSchemaStore, set by hydrate_context)
- `node_count` — int (from local snapshot, set by hydrate_context)
- `top_matches` — list[{id, name, updated_at}] (set by resolve_target)
- `operation_mode` — "create" | "update" (set by hitl_select_target)
- `target_chatflow_id` — str (set by hitl_select_target)
- `current_flow_hash` — str SHA-256 (set by load_current_flow)
- `flow_summary` — dict (compact summary, set by summarize_current_flow)
- `proposed_flow_hash` — str SHA-256 (set by compile_flow_data)
- `plan_contract` — dict (from existing _parse_plan_contract, set by plan_v2 node)
- `resolved_credentials` — dict (from existing credential resolution)

### facts["budgets"]:
- `max_patch_ops_per_iter` — int (20 for CREATE, 12 for UPDATE; overridden by define_patch_scope)
- `max_schema_repairs_per_iter` — int (default 2)
- `max_total_retries_per_iter` — int (default 1)
- `retries_used` — int (counter)

### facts["repair"]:
- `count` — int (number of repair_schema executions this iteration)
- `repaired_node_types` — list[str]
- `budget_exceeded` — bool

### facts["patch"]:
- `max_ops` — int (from define_patch_scope)
- `focus_area` — str | None
- `protected_nodes` — list[str]

### facts["validation"]:
- `ok` — bool
- `failure_type` — "schema_mismatch" | "structural" | "other" | None
- `missing_node_types` — list[str]

### facts["preflight"]:
- `ok` — bool
- `reason` — str | None

### facts["apply"]:
- `ok` — bool
- `chatflow_id` — str | None
- `pre_patch_flow_hash` — str (UPDATE mode rollback anchor)

### facts["verdict"]:
- `verdict` — "done" | "iterate"
- `reason` — str

---

## Artifacts Keys Used

### artifacts["flowise"]:
- `current_flow_data` — dict (FULL flowData JSON — set by load_current_flow, NEVER in prompts)
- `base_graph_ir` — dict (pattern-seeded base, set by plan node for CREATE)
- `proposed_flow_data` — dict (compiled output from compile_flow_data)
- `compile_errors` — list[str] (from compile_flow_data)
- `diff_summary` — str (human-readable change log from compile_flow_data)

### artifacts["validation_report"]:
- str (full validation report text, set by validate node)

### artifacts["diff_summary"]:
- str (populated by evaluate node, shown in hitl_review_v2)

---

## Prompt Assembly Points (for Teammate C)

All LLM calls in the v2 topology. Prompt content:

1. **classify_intent** (`_CLASSIFY_INTENT_SYSTEM` prompt):
   - Input: state["requirement"]
   - System: _CLASSIFY_INTENT_SYSTEM (compact, no tools)
   - File: flowise_dev_agent/agent/graph.py, function `_make_classify_intent_node`

2. **plan_v2** (reuses existing `_make_plan_node`):
   - System: _PLAN_BASE (existing)
   - Input: requirement + discovery_summary + flow_summary (compact dict, NOT full flowData)
   - For UPDATE: includes flow_summary from facts["flowise"]["flow_summary"]

3. **define_patch_scope** (`_DEFINE_PATCH_SCOPE_SYSTEM` prompt):
   - Input: operation_mode + approved plan (first 2000 chars)
   - System: _DEFINE_PATCH_SCOPE_SYSTEM
   - File: flowise_dev_agent/agent/graph.py, function `_make_define_patch_scope_node`

4. **compile_patch_ir** (`_COMPILE_PATCH_IR_V2_SYSTEM` prompt):
   - Input: requirement + operation_mode + plan + flow_summary (for UPDATE, compact dict only)
   - System: _COMPILE_PATCH_IR_V2_SYSTEM
   - CRITICAL: full flowData NEVER in prompt — only flow_summary dict
   - File: flowise_dev_agent/agent/graph.py, function `_make_compile_patch_ir_node`

5. **evaluate** (`_EVALUATE_SYSTEM` prompt):
   - Input: plan (500 chars) + diff_summary + test_results (500 chars)
   - System: _EVALUATE_SYSTEM
   - File: flowise_dev_agent/agent/graph.py, function `_make_evaluate_node`

---

## build_graph() Signature Changes

```python
# Before (all existing callers still work — no change needed)
build_graph(engine, domains, checkpointer=None, client=None, pattern_store=None, capabilities=None)

# After (new optional param with default="v1" — backward compatible)
build_graph(engine, domains, checkpointer=None, client=None, pattern_store=None, capabilities=None,
            topology_version="v1")
```

To activate the v2 topology:
```python
graph = build_graph(engine, domains, topology_version="v2")
```

All existing callers that do not pass `topology_version` continue to use the v1 topology unchanged.

---

## Context Safety Guarantees

1. Full flowData JSON NEVER enters any LLM prompt (constraint from spec):
   - `load_current_flow` stores in `artifacts["flowise"]["current_flow_data"]`
   - `summarize_current_flow` produces compact `facts["flowise"]["flow_summary"]` (deterministic, no LLM)
   - `compile_patch_ir` receives `flow_summary` dict in context, not raw flowData

2. `compile_flow_data` node reads `artifacts["flowise"]["current_flow_data"]` directly for base graph
   construction — this data never goes through the LLM.

3. WriteGuard is used in `apply_patch` to enforce hash integrity on writes.

---

## Known Limitations and Follow-up Work

- The `repair_schema` node does synchronous index lookup via `_repair_schema_for_ops()` then
  async API fallback. For the async path it updates `node_store._index` in-memory. This is
  sufficient for single-session use but not thread-safe across concurrent sessions.

- The `evaluate` node uses a small LLM to assess the diff. This could be replaced with a
  deterministic diff comparison for Teammate B's metrics tracking.

- Pattern auto-save (converge node) is not yet wired into v2 topology (plan_v2 node inherits
  it via _make_plan_node but converge is not in v2). This is left for a future milestone.

- The `test_v2` node is identical to `test` (reuses `_make_test_node`). No behavioral changes.
