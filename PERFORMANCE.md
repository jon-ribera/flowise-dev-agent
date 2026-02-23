# Flowise Dev Agent — Performance & Cost Analysis

## Observed Token Costs (from `sessions.db`, February 2026)

| Session | Description | Input tokens | Output tokens | Iterations | Est. cost |
|---|---|---|---|---|---|
| `bc7d31bd` | Disneyland planner (1st run) | 548,996 | 165,517 | 2 | **$4.13** |
| `6bacdb1f` | Disneyland planner (2nd run) | 215,404 | 64,609 | 1 | **$1.62** |

Pricing basis: Claude Sonnet at $3/MTok input + $15/MTok output.

Both sessions failed to produce a working chatflow (chatflow_id was None) due to
a separate bug (now fixed in `graph.py`). The cost data reflects accurate LLM usage
regardless of session outcome.

---

## Root Cause: Quadratic Context Accumulation

The `_react` loop in `flowise_dev_agent/agent/graph.py` sends `messages + new_msgs`
to the API on every round:

```python
for round_num in range(max_rounds):
    response = await engine.complete(
        messages=messages + new_msgs,   # grows by ~2 messages per round
        ...
    )
```

`new_msgs` accumulates every assistant turn and every tool result. After N rounds,
round N sends the full history of all prior tool results. This produces:

**Total tokens = O(N² × avg_tool_result_size)**

| Variable | Discover phase | Patch phase |
|---|---|---|
| max_rounds | 20 | 15 |
| Typical tool calls | 10–15 | 5–8 |
| Total rounds (inc. final text) | 11–16 | 6–9 |

With avg_tool_result_size = 5,000 chars and 14 rounds:
- Round 1: ~200 tokens
- Round 14: ~200 + 26 × ~1,500 = ~39,000 tokens
- **Total across all rounds: ~280,000 input tokens for discover alone**

---

## Primary Cost Drivers (Ordered by Impact)

### 1. `list_marketplace_templates` — 50,000–100,000 chars per call

The raw marketplace response contains every Flowise template in full detail.
`_list_marketplace_templates_slim` trims this to the most relevant fields, but
even the slim version is large. Once this result lands in `new_msgs`, it
accumulates in every subsequent round's context window.

**Location**: `flowise_dev_agent/agent/tools.py` → `_list_marketplace_templates_slim`
**Fix**: Cap `result_to_str` at 4,000 chars (see below)

### 2. `get_chatflow` responses — 10,000–50,000 chars per call

The discover phase instructs the LLM to call `get_chatflow` for any candidate
existing chatflow. A complex chatflow's `flowData` JSON (all nodes, edges, params)
can be 10–50k chars. Like the marketplace response, it accumulates in context.

**Location**: `flowise_dev_agent/agent/tools.py` → `result_to_str`
**Fix**: Cap `result_to_str` at 4,000 chars (see below)

### 3. `_get_node_processed` `**schema` spread — ~2,000 extra chars per node

`_get_node_processed` returns `{**schema, inputAnchors, inputParams, outputAnchors, outputs}`.
The `**schema` spread includes fields that are **not needed for flowData construction**:
- `inputs` — the raw inputs array, already replaced by `inputAnchors`/`inputParams`
- `description` — long free-text description of the node
- `category`, `icon`, `tags`, `badge`, `author`, `deprecated` — UI metadata

With 8–14 `get_node` calls per discover, this adds ~20,000–40,000 extra chars
to the accumulating context window.

**Location**: `flowise_dev_agent/agent/tools.py` → `_get_node_processed` (line ~540)
**Fix**: Remove `**schema` spread, explicitly select only needed fields

---

## Proposed Fixes

### Fix 1: `result_to_str` Truncation

**File**: `flowise_dev_agent/agent/tools.py`
**Change**: Add 4,000-char cap to `result_to_str`

```python
_MAX_TOOL_RESULT_CHARS = 4_000

def result_to_str(result: Any) -> str:
    if isinstance(result, str):
        s = result
    else:
        try:
            s = json.dumps(result, default=str)
        except Exception:
            s = str(result)
    if len(s) > _MAX_TOOL_RESULT_CHARS:
        omitted = len(s) - _MAX_TOOL_RESULT_CHARS
        s = s[:_MAX_TOOL_RESULT_CHARS] + f"\n...[{omitted} chars truncated]"
    return s
```

**Expected impact**: `list_marketplace_templates` (50–100k chars → 4k), `get_chatflow`
(10–50k chars → 4k). This breaks the quadratic growth since per-round context
delta stays bounded.

### Fix 2: `_get_node_processed` Field Pruning

**File**: `flowise_dev_agent/agent/tools.py`
**Change**: Replace `{**schema, ...}` with explicit field selection

```python
_KEEP_PARAM_FIELDS = {"name", "type", "label", "id", "optional", "default", "list", "acceptVariable"}

def _slim_param(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k in _KEEP_PARAM_FIELDS}

# In _get_node_processed return (replaces **schema spread):
return {
    "name": node_name,
    "label": schema.get("label", node_name),
    "version": schema.get("version"),
    "baseClasses": base_classes,
    "inputAnchors": [_slim_param(e) for e in input_anchors],
    "inputParams": [_slim_param(e) for e in input_params],
    "outputAnchors": output_anchors,
    "outputs": {},
    "_flowdata_note": ...,
}
```

**Removed fields**: `inputs` (raw, replaced by inputAnchors/inputParams), `description`,
`category`, `icon`, `tags`, `badge`, `author`, `deprecated`. None of these are
referenced in flowData construction logic.

**Expected impact**: Each `get_node` response shrinks from ~3–5k to ~1–2k chars.
With 8–14 calls per discover, saves ~14–56k chars from the accumulated context.

---

## Expected Savings After Both Fixes

| Metric | Current | After fixes | Reduction |
|---|---|---|---|
| `list_marketplace_templates` response | ~60k chars | ~4k chars | 93% |
| `get_chatflow` response (discover) | ~30k chars | ~4k chars | 87% |
| `get_node` response | ~4k chars | ~2k chars | 50% |
| Input tokens / session (estimate) | 215k–549k | 60k–150k | ~70% |
| Cost / session (estimate) | $1.62–$4.13 | $0.50–$1.20 | ~70% |

---

## Additional Opportunities (Lower Priority)

### 3. Periodic Context Summarization in `_react`

After every 5 rounds, summarize `new_msgs` into a compact summary message and
replace the accumulated messages with the summary. Reduces quadratic growth to
linear but requires a summarization LLM call per checkpoint.

**Complexity**: Medium. Requires careful summary prompt and validation that
important tool results (chatflow IDs, credential IDs) are preserved.

### 4. Trim `discovery_summary` Before Patch Context

The discover summary (5–10k tokens) is passed verbatim to patch as context.
Truncating to ~2k chars at the start of the patch node would save ~50–100k
tokens across all patch rounds. Low risk since the approved plan already
captures the key constraints.

**Location**: `flowise_dev_agent/agent/graph.py` → `_make_patch_node`, `ctx` construction

### 5. Caching Already in ROADMAP2 (DD-035)

`list_marketplace_templates` and `list_nodes` are called fresh on every session.
A TTL cache (already designed in ROADMAP2 as DD-035) would eliminate these calls
entirely for repeat sessions within the cache window.

---

## Next Design Decision Number

The next available DD number after the fixes above: **DD-041**

Suggested: `DD-041 — Tool Result Truncation and Node Schema Pruning`
