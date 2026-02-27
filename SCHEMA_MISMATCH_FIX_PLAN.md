# Fix: Schema Mismatch Repair Loop — Wrong Node Names Never Self-Correct

## Context

Session `0e7353a3` showed the LLM using `ConversationSummaryBufferMemory` (PascalCase) instead of the correct `conversationSummaryBufferMemory` (camelCase). The graph entered a repair loop: `validate → repair_schema → compile_patch_ir → compile_flow_data → validate` cycling 3 times until repair budget was exhausted, then falling through to `hitl_plan_v2` with no actionable guidance visible to the user.

The `validate` node correctly generates a "Did you mean: 'conversationSummaryBufferMemory'?" message in `developer_feedback`. But the feedback never reaches any LLM because:

1. `_route_after_validate` sends `schema_mismatch` to `repair_schema` (designed for genuinely missing schemas)
2. `repair_schema` fetches/finds the schema but can't fix wrong names in the plan
3. `_route_after_repair_schema` always returns `"compile_patch_ir"`
4. `compile_patch_ir` **does NOT read `developer_feedback`** — it re-runs the LLM with the same plan containing the wrong name
5. The LLM generates the same wrong AddNode op → same compile error → back to validate

Meanwhile, for `structural` and `type_mismatch` failures, `_route_after_validate` correctly routes to `plan_v2`, which **does** read `developer_feedback` and injects it as LLM context. The fix needs to give `schema_mismatch` from naming errors the same treatment.

## Root Cause Analysis

There are **two distinct failure modes** conflated under `schema_mismatch`:

| Mode | Example | repair_schema can fix? | Correct route |
|------|---------|----------------------|---------------|
| **Genuinely missing schema** | Node type `customNewPlugin` doesn't exist in snapshot | Yes — fetch from API | `repair_schema` → `compile_patch_ir` |
| **Wrong node name (naming error)** | `ConversationSummaryBufferMemory` instead of `conversationSummaryBufferMemory` | No — schema exists under correct name | `plan_v2` (re-plan with "did you mean?" feedback) |

The validate node already distinguishes these via `_schema_mismatch_feedback()` which uses `difflib.get_close_matches()` — when close matches exist, it's a naming error.

Additionally, `compile_flow_data` (line 2406) uses `node_store._index.get(node_name)` (exact match), NOT the case-insensitive `node_store.get()`. So even after `repair_schema` finds the schema via case-insensitive lookup, the next compilation fails again because the IR still has the wrong-cased name.

## The Broken Cycle (Step by Step)

```
[1] plan_v2: LLM creates plan with "ConversationSummaryBufferMemory" (wrong case)
[2] hitl_plan_v2: Developer approves plan
[3] define_patch_scope → compile_patch_ir: LLM reads plan, emits AddNode(node_name="ConversationSummaryBufferMemory")
[4] compile_flow_data: Looks up schema via _index.get("ConversationSummaryBufferMemory") → NOT FOUND
    → Sets compile_errors = ["no schema for 'ConversationSummaryBufferMemory'"]
[5] validate: Detects schema_mismatch, generates "Did you mean: 'conversationSummaryBufferMemory'?"
    → Sets developer_feedback ✓ ... but routing sends to repair_schema, not plan_v2
[6] repair_schema: Finds schema via case-insensitive lookup (repair "succeeds")
[7] _route_after_repair_schema → compile_patch_ir: LLM gets SAME plan, generates SAME wrong ops
[8] compile_flow_data: FAILS AGAIN — _index.get() is exact-match, IR still has wrong name
[9] Loop repeats until repair budget exhausted → hitl_plan_v2 (no feedback visible to user)
```

## Approach: Route Naming Errors to plan_v2, Not repair_schema

The fix is surgical — classify the sub-type at the source (validate) and route accordingly.

### File: `flowise_dev_agent/agent/graph.py`

#### Change 1: `_schema_mismatch_feedback()` returns a signal (line ~2565)

Change return type from `str` to `tuple[str, bool]`. The bool indicates whether close matches were found (naming error vs genuinely missing). This is the natural place — the function already computes this information internally.

```python
# Before:
def _schema_mismatch_feedback(...) -> str:
    ...
    return "\n".join(lines)

# After:
def _schema_mismatch_feedback(...) -> tuple[str, bool]:
    ...
    has_close_matches = False
    for mt in missing_types:
        matches = difflib.get_close_matches(...)
        if suggestions:
            has_close_matches = True
            ...
    return "\n".join(lines), has_close_matches
```

#### Change 2: Validate node stores the signal in facts (both code paths, lines ~2691 and ~2783)

Unpack the tuple and store `has_close_matches` in `facts["validation"]`:

```python
feedback_text, has_close = _schema_mismatch_feedback(missing_types, _known_names, report)
result["developer_feedback"] = feedback_text
result["facts"]["validation"]["has_close_matches"] = has_close
```

#### Change 3: `_route_after_validate()` — naming errors go to plan_v2 (line ~3255)

When `schema_mismatch` AND `has_close_matches`, route to `plan_v2` instead of `repair_schema`. The `developer_feedback` is already set with "did you mean?" suggestions, and `plan_v2` reads and consumes it.

```python
# Before:
if failure_type == "schema_mismatch" and repair_count < max_repairs:
    return "repair_schema"

# After:
if failure_type == "schema_mismatch":
    has_close = validation.get("has_close_matches", False)
    if has_close:
        # Naming error — LLM used wrong case/spelling. Re-plan with suggestions.
        return "plan_v2"
    if repair_count < max_repairs:
        # Genuinely missing schema — try fetching from API.
        return "repair_schema"
```

#### Change 4: `_route_after_repair_schema()` — check if repair actually resolved the issue (line ~3296)

Currently always returns `"compile_patch_ir"`. After repair, if types are still unresolved (repair found nothing), route to `plan_v2` instead of blindly retrying compilation with the same broken IR.

```python
# Before:
def _route_after_repair_schema(state: AgentState) -> str:
    """After repair_schema: always retry compile_patch_ir exactly once."""
    return "compile_patch_ir"

# After:
def _route_after_repair_schema(state: AgentState) -> str:
    """After repair_schema: retry if repair found schemas, else re-plan."""
    facts = state.get("facts") or {}
    repair = facts.get("repair") or {}
    validation = facts.get("validation") or {}
    missing = validation.get("missing_node_types") or []
    repaired = repair.get("repaired_node_types") or []

    # If none of the missing types were repaired, re-plan instead of retrying
    if missing and not any(mt in repaired for mt in missing):
        return "plan_v2"
    return "compile_patch_ir"
```

#### Change 5: Update graph edge map (line ~3628)

Add `"plan_v2"` as a valid target for `_route_after_repair_schema`:

```python
# Before:
builder.add_conditional_edges(
    "repair_schema",
    _route_after_repair_schema,
    {"compile_patch_ir": "compile_patch_ir"},
)

# After:
builder.add_conditional_edges(
    "repair_schema",
    _route_after_repair_schema,
    {"compile_patch_ir": "compile_patch_ir", "plan_v2": "plan_v2"},
)
```

### File: `tests/test_m96_topology_v2.py`

Update `test_schema_mismatch_routes_to_repair_then_retries_once` — this test currently asserts that schema_mismatch always routes to `repair_schema`. After the fix, it should assert:
- `schema_mismatch` with `has_close_matches=True` → `plan_v2`
- `schema_mismatch` with `has_close_matches=False` → `repair_schema`
- After repair with unresolved types → `plan_v2`
- After repair with resolved types → `compile_patch_ir`
- Budget exceeded → `hitl_plan_v2` (unchanged)

### File: `tests/test_m107_node_name_normalization.py`

Add a test verifying that `_schema_mismatch_feedback` returns `(str, True)` when close matches exist and `(str, False)` when none exist.

## What This Does NOT Change

- `_schema_mismatch_feedback` text format — identical output, just also returns a bool
- `repair_schema` node logic — still repairs genuinely missing schemas the same way
- `compile_patch_ir` node — no changes needed; naming errors now go to `plan_v2` before reaching it
- `plan_v2` node — already reads `developer_feedback` correctly
- No new state fields — `has_close_matches` lives in `facts["validation"]`, not top-level state

## Verification

1. **Unit tests**: Run `pytest tests/test_m96_topology_v2.py tests/test_m107_node_name_normalization.py -v`
2. **Full suite**: Run `pytest tests/ -x --ignore=tests/e2e` to verify no regressions
3. **Manual E2E**: Start a session requesting a chatflow with a node the LLM typically PascalCases. Verify:
   - The "did you mean?" feedback reaches plan_v2 (check logs for `[PLAN]` with developer feedback)
   - The LLM re-plans with correct camelCase names
   - No 3x repair loop in the phase timeline
