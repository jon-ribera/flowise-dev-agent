# Teammate D — M9.9 Implementation Notes

Milestone 9.9: PatternCapability Maturity Tuning

## Files Modified

### flowise_dev_agent/agent/pattern_store.py
- Added `import datetime` at module level.
- Added `_is_pattern_schema_compatible(pattern, current_fingerprint) -> bool` helper function (Part B):
  - Returns `True` when stored fingerprint is None/empty (old pattern, assume compatible).
  - Returns `True` when current_fingerprint is None/empty (cannot check, assume compatible).
  - Returns `stored == current_fingerprint` otherwise.
- Added `_infer_category_from_node_types(node_types: list[str]) -> str` helper function (Part A):
  - "rag" — any node whose name contains "vectorStore" or "retriev" (checked first).
  - "tool_agent" — any node whose name contains "toolAgent".
  - "conversational" — both a chat model node (chatOpenAI/chatAnthropic/chatOllamaLocal) AND a
    conversationChain node are present.
  - "custom" — catch-all for all other combinations.
- Updated `search_patterns_filtered()` SQL query to SELECT `last_used_at` column (row index 10).
- Updated result construction to convert the stored Unix float to an ISO-8601 UTC string:
  `datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()`.
  `None` is returned when `last_used_at` has never been set (pattern never applied as base).

### flowise_dev_agent/agent/graph.py
- Modified the pattern seeding block in `_make_plan_node()` (around the prior line 916):
  - Added `state.get("operation_mode") != "update"` guard so patterns are NEVER applied
    over existing flows (M9.6 constraint).
  - Initialised `_pat_matches: list = []` and `_pat: dict = {}` before the guard block so
    these variables are always defined in the outer scope (needed by the metrics dict below).
  - After the seeding block, always builds `_debug_update_flowise["pattern_metrics"]` dict:
    ```python
    "pattern_metrics": {
        "pattern_used": _pattern_base_ir is not None,
        "pattern_id": _pat.get("id") if _pat_matches else None,
        "ops_in_base": len(_pattern_base_ir.get("nodes", [])) if _pattern_base_ir is not None else 0,
    }
    ```
  - Added `"debug": {"flowise": _debug_update_flowise}` to the plan node return dict so
    `pattern_metrics` is always emitted (even when no pattern store or no match found).

### flowise_dev_agent/agent/state.py
- Added two new fields at the end of the `AgentState` TypedDict (Part E):
  - `pattern_used: bool` — True when a pattern was used as the base GraphIR for the current
    plan iteration.
  - `pattern_id: int | None` — Integer ID of the PatternStore row applied as the base graph,
    or None when no pattern was seeded this iteration.

## New Files

### tests/test_m99_pattern_tuning.py
18 tests across 6 groups:
1. **Pattern metadata completeness** — `save_pattern()` stores all M9.9 fields; `apply_as_base_graph()` sets `last_used_at`.
2. **Schema compatibility** — `_is_pattern_schema_compatible()` returns correct True/False for all fingerprint combinations.
3. **UPDATE mode guard** — plan node with `operation_mode=="update"` emits `pattern_used=False`; plan node with `operation_mode=None` emits `pattern_used=True` when a matching pattern exists.
4. **success_count** — defaults to `int(1)` on insert; increments to 2 via `apply_as_base_graph()`; increments via explicit `increment_success()`.
5. **_infer_category_from_node_types** — validates rag, tool_agent, conversational, custom, and rag-over-conversational priority.
6. **last_used_at as ISO string** — `search_patterns_filtered()` returns `None` before first apply; returns a valid ISO-8601 string with timezone after apply.

## New debug["flowise"]["pattern_metrics"] Structure

Always emitted by the plan node (M9.9):

```json
{
  "pattern_used": true,
  "pattern_id": 42,
  "ops_in_base": 3
}
```

| Field         | Type          | Description                                                    |
|---------------|---------------|----------------------------------------------------------------|
| `pattern_used`| `bool`        | `True` if a pattern GraphIR was seeded this iteration          |
| `pattern_id`  | `int \| null` | PatternStore row ID of the applied pattern, `null` if none     |
| `ops_in_base` | `int`         | Node count from the seeded pattern flow_data (0 if none used)  |

When `pattern_store` is `None` or no matching pattern was found, all three fields reflect the
"no pattern" state: `{pattern_used: false, pattern_id: null, ops_in_base: 0}`.

## New State Fields Added

```python
pattern_used: bool          # True when a pattern was used as base GraphIR
pattern_id: int | None      # ID of the pattern used (PatternStore row id)
```

Both fields are in `flowise_dev_agent/agent/state.py` under the "Pattern library (M9.9)" section.

## Key Constraint: Patterns Must NOT Apply for UPDATE Mode

When `state.get("operation_mode") == "update"`, the seeding block is entirely skipped.  This
enforces the M9.6 design decision that patterns are only valid as base graphs for CREATE flows —
applying them over an existing chatflow would corrupt the existing structure.

The guard condition in `_make_plan_node()`:
```python
if (
    pattern_store is not None
    and iteration == 0
    and not state.get("chatflow_id")
    and state.get("operation_mode") != "update"   # M9.9 guard
):
```
