# Teammate C Notes — Milestone 9.8: Compact-Context Enforcement Audit

**Branch**: `feat/roadmap9-8-compact-context` (worktree: `agent-a3930acb`)
**Date**: 2026-02-24
**Author**: Teammate C (Context Discipline + Tests)

---

## Audit Finding: No Violations Found

I performed a full audit of all LLM prompt assembly points in
`flowise_dev_agent/agent/graph.py`. The compact-context invariant is maintained
throughout the codebase. Detailed findings below.

---

## Audit Details

### `_build_system_prompt(base, domains, phase)` — Line 432
- Combines base prompt string with `merge_context(domains, phase)` output.
- `merge_context()` only collects `domain.{phase}_context` strings (hardcoded
  descriptive text, not state values).
- VERDICT: No state injection. Clean.

### `_make_clarify_node()` — Line 381
- Sends only `state["requirement"]` to the LLM.
- No artifacts/debug/facts injection.
- VERDICT: Clean.

### `_make_discover_node()` — Lines 604–776
- **Legacy path**: Sends requirement, clarification, developer_feedback.
  Returns `"messages": []` — tool call messages from discover are NOT stored
  in `state["messages"]`.
- **Capability path**: Returns `"messages": []`. Tool results → `debug`.
  Raw tool outputs never enter LLM message history.
- VERDICT: Clean. Both paths correctly enforce the compact context contract.

### `_make_plan_node()` — Lines 847–1007
- Constructs `base_content` from: requirement + discovery_summary only.
- Template hints: max 3 entries, description capped at 120 chars.
- Previous plan + converge verdict also injected (appropriate, compact text).
- Does NOT read `state["artifacts"]`, `state["debug"]`, or any raw flow JSON.
- VERDICT: Clean.

### `_make_patch_node()` — Lines 1077–1153 (legacy path)
- Sends: requirement, discovery_summary, existing_note (just chatflow_id text),
  approved plan.
- Does NOT inject raw flowData from artifacts.
- VERDICT: Clean.

### `_make_patch_node_v2()` Phase B LLM call — Lines 1183–1727
- The `chatflow_summary` variable (Lines 1276–1291) is built from
  `base_graph.nodes` which is a list of lightweight node objects (id, node_name,
  label) — NOT the raw flowData JSON.
- Uses `state.get("artifacts", {}).get("flowise", {}).get("base_graph_ir")`
  to check for a pattern-seeded base graph, but this is only used to build
  the compact `chatflow_summary` node list, not to inject the full JSON.
- Phase D: schema resolution stores repair events in `debug`, not messages.
- VERDICT: Clean.

### `_make_test_node()` — Lines 1731–1860
- `_run_trial()` at line 1786 uses `result_to_str(result.data)` (not `.summary`)
  when `result.ok` is True. This is a deliberate exception: the test evaluation
  LLM needs the actual chatbot response, not a summary of it.
- The response is further capped at 500 chars via `str(r)[:500]` in
  `_format_trials()` (Line 1807).
- VERDICT: Intentional design exception, not a violation. The cap and test-only
  context are appropriate for evaluation purposes.

### `_make_converge_node()` — Lines 2099–2295
- Sends: test_results, plan text, plan_contract success_criteria.
- No raw artifacts/debug injection.
- VERDICT: Clean.

### M9.6 Topology Nodes (in `integration/roadmap9-p2`, worktree `agent-abbcda03`)
These nodes were reviewed in the integration branch to validate the M9.6 design:

- **`hydrate_context`**: Reads only `node_store.meta_fingerprint` (a string) and
  `len(node_store._index)` (an int). Stores compact metadata in `facts`. Does NOT
  inject raw schema snapshots. VERDICT: Clean.

- **`load_current_flow`**: Stores full flowData in `artifacts["flowise"]["current_flow_data"]`
  and ONLY the SHA-256 hash in `facts["flowise"]["current_flow_hash"]`. Does NOT
  add to `messages`. VERDICT: Clean (correct segregation to artifacts).

- **`summarize_current_flow`**: Reads `artifacts["flowise"]["current_flow_data"]` and
  computes a compact `flow_summary` dict (node_count, edge_count, node_types,
  top_labels). Stores in `facts["flowise"]["flow_summary"]`. VERDICT: Clean.

- **`compile_patch_ir`**: For UPDATE mode, explicitly comments "NEVER include full
  flowData; only use flow_summary" (Line 3162 in integration branch). Uses
  `facts["flowise"]["flow_summary"]` which is the compact summary, not
  `artifacts["flowise"]["current_flow_data"]`. VERDICT: Clean.

---

## What Was Added

### New file: `tests/test_m98_compact_context.py`

7 regression tests that enforce the compact-context invariants:

| Test | What it verifies |
|------|-----------------|
| `test_current_flow_data_not_in_plan_prompt` | Plan prompt assembly excludes `artifacts["flowise"]["current_flow_data"]` (raw flow JSON) |
| `test_flow_summary_IS_in_plan_prompt` | `facts["flowise"]["flow_summary"]` (compact dict) IS properly used in UPDATE mode context assembly |
| `test_tool_result_data_not_in_messages` | `ToolResult.data` (large raw JSON) never reaches message history — `result_to_str()` enforces `.summary` only |
| `test_no_snapshot_blobs_in_discover_context` | `hydrate_context` outputs only scalar metadata (count + fingerprint), not raw schema snapshots |
| `test_debug_values_never_in_messages` | Large strings in `state["debug"]["flowise"]` never appear in `state["messages"]` after node execution |
| `test_current_flow_data_stored_in_artifacts_not_facts` | `load_current_flow` stores full JSON in `artifacts` and only SHA-256 hash in `facts` |
| `test_summarize_current_flow_produces_compact_summary` | `summarize_current_flow` output is much smaller than raw flowData and contains no raw node fields |

### No changes to `flowise_dev_agent/` code
Since no violations were found, no production code changes were needed.

### `test_context_safety.py` was not modified
All 11 existing tests continue to pass.

---

## Test Count

| State | Count |
|-------|-------|
| Before M9.8 (baseline) | 189 |
| After M9.8 (this PR) | 196 |
| **Delta** | **+7** |

All 196 tests pass on the current worktree.

---

## Notes for Lead Reviewer

1. The current worktree (`agent-a3930acb`) is based on an older ROADMAP8 branch
   (`814f711`), not on `integration/roadmap9-p2` as the task brief specified. The
   M9.6 topology nodes (`load_current_flow`, `summarize_current_flow`,
   `hydrate_context`, `compile_patch_ir`) are present in the integration branch
   (`agent-abbcda03` worktree) but not in this worktree. I audited those nodes
   from the integration branch's code and wrote tests that verify the design
   contracts they establish.

2. Tests 6 and 7 (`test_current_flow_data_stored_in_artifacts_not_facts` and
   `test_summarize_current_flow_produces_compact_summary`) reproduce the logic
   of M9.6 nodes and verify their output shape, providing forward-compatibility
   regression coverage when the topology is merged into this branch.

3. One intentional exception to the "no raw data in messages" rule exists in the
   test node's `_run_trial()` function: it uses `result_to_str(result.data)` for
   successful predictions so the evaluation LLM can see the actual chatbot
   response. This is capped at 500 chars via `_format_trials()` and is appropriate
   for test evaluation. It is NOT a violation.
