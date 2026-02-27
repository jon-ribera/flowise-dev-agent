# Flowise Dev Agent — Performance & Cost Analysis

> Last updated: February 2026 (post-Roadmap 9)

## Architecture Overview

The agent runs on an **18-node LangGraph topology** (M9.6, DD-080) with per-phase
token tracking, compact context enforcement, and LangSmith observability. The old
monolithic `_react` loop and its quadratic context accumulation problem were fully
eliminated in Roadmap 9.

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `ToolResult.summary` | `tools.py` (DD-048) | Only `.summary` reaches LLM context; `.data` goes to debug only |
| `_summarize_flow_data()` | `graph.py` (M9.6) | Deterministic compact summary — full flowData never in prompts |
| `PhaseMetrics` | `metrics.py` (DD-069) | Per-phase input/output token + timing capture |
| `SessionSummary` | `api.py` | Cumulative token counts exposed via REST API |
| Token budget evaluator | `langsmith/evaluators.py` (DD-087) | Per-phase budget enforcement via LangSmith |
| State trifurcation | `state.py` (DD-050) | `messages` / `artifacts` / `debug` — clean separation |

---

## Context Management

### ToolResult Envelope (DD-048)

Every tool call returns a `ToolResult` with five fields. Only `.summary` is injected
into the LLM message history via `result_to_str()`:

```
ToolResult(
    ok=True,
    summary="Chatflow 'My RAG Bot' (id=abc-123).",   # → LLM context
    facts={"chatflow_id": "abc-123", ...},            # → state["facts"]
    data={<full API response>},                       # → state["debug"] only
    error=None,
)
```

The `_wrap_result()` function (single transformation point) applies 7 priority rules
to normalize all tool outputs into compact summaries (200–300 char generation limits).

### Flow Data Summarization (M9.6)

`_summarize_flow_data()` produces a compact dict from raw flowData JSON:

```python
{
    "node_count": 8,
    "edge_count": 7,
    "node_types": {"chatOpenAI": 1, "pdfFile": 1, ...},
    "top_labels": ["ChatOpenAI_0", "PDF File_0", ...],
    "key_tool_nodes": ["toolAgent_0"],
}
```

This is used in UPDATE-mode prompts. The raw flowData (10–50k chars) is stored in
`artifacts["flowise"]["current_flow_data"]` and never injected into LLM context.
A SHA-256 hash (`facts["flowise"]["current_flow_hash"]`) provides identity checks.

### State Trifurcation (DD-050)

| Bucket | Content | LLM-visible? |
|--------|---------|---------------|
| `messages` | Conversation turns + tool summaries | Yes |
| `artifacts` | Raw flowData, full API responses | No |
| `facts` | Scalar metadata (IDs, hashes, counts) | Selectively (via prompts) |
| `debug` | Phase metrics, pattern metrics, raw data | No |

### Compact-Context Invariants (M9.8, DD-083)

Seven regression tests enforce these rules:

1. Raw `current_flow_data` never appears in plan/patch prompts
2. `flow_summary` (compact dict) is used instead — verified <10% of raw size
3. `ToolResult.data` never reaches message history
4. `hydrate_context` injects only scalar metadata, not raw schemas
5. Debug values never appear in `state["messages"]`
6. `current_flow_data` stored in artifacts, not facts
7. `summarize_current_flow` output always <2000 chars

---

## Token Tracking

### Per-Phase Metrics (DD-069)

Each graph phase captures token usage via `MetricsCollector`:

```python
async with MetricsCollector("discover") as m:
    response = await engine.complete(...)
    m.input_tokens = response.input_tokens
    m.output_tokens = response.output_tokens
```

Results accumulate in `state["debug"]["flowise"]["phase_metrics"]` as a list of dicts,
each containing: `phase`, `start_ts`, `end_ts`, `duration_ms`, `input_tokens`,
`output_tokens`, `tool_call_count`, `cache_hits`, `repair_events`.

### Per-Phase Token Budgets

The LangSmith `token_budget` evaluator enforces these per-phase limits:

| Phase | Budget (tokens) |
|-------|-----------------|
| `discover` | 15,000 |
| `plan` | 8,000 |
| `patch` | 20,000 |
| `test` | 10,000 |
| `evaluate` | 5,000 |
| `converge` | 5,000 |
| Unknown phase | 25,000 (default) |

Score = `1.0 - (violations / total_phases)`, clipped to [0.0, 1.0].

### Session-Level Tracking

`SessionSummary` (REST API) exposes cumulative per-session data:

| Field | Description |
|-------|-------------|
| `total_input_tokens` | Cumulative LLM prompt tokens |
| `total_output_tokens` | Cumulative LLM completion tokens |
| `total_repair_events` | Schema/credential repair API fallbacks |
| `total_phases_timed` | Number of phases with captured timing |
| `phase_durations_ms` | Per-phase wall-clock durations |
| `schema_fingerprint` | Current NodeSchemaStore snapshot fingerprint |
| `drift_detected` | True when schema fingerprint changed vs prior iteration |
| `pattern_metrics` | Pattern usage metrics from last patch iteration |

---

## Knowledge Layer Cost Savings

### Local-First Lookups (Roadmap 6, DD-062–DD-064)

| Store | Lookup Cost | API Fallback |
|-------|-------------|--------------|
| `NodeSchemaStore` | O(1) from snapshot | Repair-only (single node fetch) |
| `TemplateStore` | Keyword search across local snapshot | Only when stale (TTL-gated) |
| `CredentialStore` | O(1) by id/name/type | `resolve_or_repair()` async fallback |

These replaced the old pattern of calling `list_nodes`, `list_marketplace_templates`,
and `list_credentials` from the LLM via tool calls, which generated 50–100k char
responses per call.

### Anchor Dictionary (Roadmap 10, DD-095–DD-096)

`AnchorDictionaryStore` provides a derived view of `NodeSchemaStore` for the Patch IR
compiler. Anchor resolution uses exact-match (Pass 1) with deprecated fuzzy fallback
(Pass 2), tracked via `CompileResult.anchor_metrics`.

---

## LangSmith Observability (DD-084–DD-088)

| Evaluator | Score Basis |
|-----------|-------------|
| `compile_success` | 1.0 if chatflow_id present, else 0.0 |
| `intent_confidence` | Raw confidence float from discover phase |
| `iteration_efficiency` | 1.0 if converged in 1 iteration, penalty per extra |
| `token_budget` | Fraction of phases within their token budget |
| `plan_quality` | Heuristic from plan structure and specificity |

All session runs are auto-routed to the `agent-review-queue` annotation queue.
Redaction (DD-084) strips API keys, DSN strings, and credential values from traces.

---

## Historical Comparison

### Pre-Roadmap 7 (Early February 2026)

The original architecture used a monolithic `_react` loop that accumulated tool
results in `new_msgs` across rounds, producing **O(N^2 x avg_tool_result_size)**
token growth:

| Session | Input Tokens | Output Tokens | Cost |
|---------|-------------|---------------|------|
| `bc7d31bd` (Disneyland planner, 1st) | 548,996 | 165,517 | $4.13 |
| `6bacdb1f` (Disneyland planner, 2nd) | 215,404 | 64,609 | $1.62 |

Pricing: Claude Sonnet at $3/MTok input + $15/MTok output.

### Root Causes (All Resolved)

| Problem | Tokens Wasted | Fix | DD |
|---------|---------------|-----|-----|
| Quadratic `_react` loop | 200k–400k/session | 18-node LangGraph topology | DD-080 |
| `list_marketplace_templates` raw (50–100k chars) | 50k+/call | `ToolResult.summary` + `TemplateStore` | DD-048, DD-063 |
| `get_chatflow` raw JSON in context | 10–50k/call | `_summarize_flow_data()` compact dict | DD-080 |
| `_get_node_processed` `**schema` spread | 20–40k/session | `NodeSchemaStore` field selection | DD-062 |
| No token tracking | N/A | `PhaseMetrics` + LangSmith evaluators | DD-069, DD-087 |

---

## Remaining Opportunities

### 1. Live Session Benchmarks

The historical data predates all fixes. We need fresh benchmarks from the current
18-node topology to establish a new baseline. Key metrics to capture:

- Per-phase token usage (from `PhaseMetrics`)
- Total session cost for CREATE vs UPDATE flows
- Token budget violation rate across sessions

### 2. Prompt Compression

Individual phase prompts (system + user) could be audited for redundancy. The
compact-context invariants (M9.8) ensure no raw data leaks, but the prompt text
itself may contain verbose instructions that could be tightened.

### 3. LLM Call Caching

Identical schema lookups across sessions could leverage LLM-level prompt caching
(Anthropic prompt caching / OpenAI cached completions) for repeated system prompts.
The `schema_fingerprint` + `drift_detected` fields (M9.7) provide the staleness
signal needed to invalidate caches safely.
