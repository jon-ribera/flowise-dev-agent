---
name: workday_extend
description: |
  Build Flowise chatflows that call Workday APIs via the customMCP tool node pattern.
  Use when the user wants to read Worker profiles, search employee data, query HR records,
  integrate Workday into a chatbot, or build any flow that connects to Workday — even if they
  don't say "Workday MCP" or "customMCP" directly. Triggers on: Workday chatbot, employee
  search flow, Worker profile agent, Workday HR assistant, MCP tool node.
version: 0.2.0
---

# Workday Integration Skill

**Domain**: workday
**Status**: Partial — customMCP wiring pattern active (M7.5); full Workday ops catalog TBD

---

## Overview

This skill teaches the co-pilot how to build Flowise chatflows that call Workday APIs.
Workday connectivity happens *inside Flowise chatflows* via the `customMCP` Tool node —
not inside the co-pilot itself.

```
Flowise Dev Agent
  → builds Flowise chatflows
     → those chatflows use customMCP Tool nodes that call Workday REST APIs
        → Workday data flows through the chatflow at user runtime
```

The co-pilot's job: discover the available Workday MCP actions from the blueprint catalog,
emit Patch IR ops to wire the customMCP Tool node correctly, and test the resulting flow
against sandbox data.

---

## Discover Context

Your goal: identify what Workday capability the user needs and which MCP actions from the
blueprint catalog satisfy it. Then produce a PlanContract.

### Step 1 — Classify the Workday operation

Determine which Workday domain is involved:
- **Workers**: `getMyInfo`, `getWorkers`, `searchForWorker`
- **Absences**: absence management operations (TBD — catalog under development)
- **Other HR objects**: check the MCP blueprint catalog

### Step 2 — Check the MCP blueprint catalog

Read `schemas/workday_mcp.snapshot.json`. Each entry has:
- `action`: the MCP action name (used in `mcpActions` array)
- `description`: what the action does
- `input_schema`: parameters the action accepts
- `output_schema`: what the action returns

Find actions that satisfy the user's requirement. A single chatflow can expose multiple actions.

### Step 3 — Verify Workday credential

Call `list_credentials`. Look for a credential with type `workdayOAuth`. The customMCP node
requires this credential — without it the Workday API calls will fail with 401 at runtime.

### Step 4 — Check for existing Workday chatflows

Call `list_chatflows`. If a Workday flow already exists, call `get_chatflow(id)` to inspect
its current `mcpActions` list — you may be adding to an existing flow (UPDATE mode) rather
than building from scratch (CREATE mode).

<output_format>
Return a plan summary (2–4 sentences) followed by a JSON PlanContract code block labeled "plan_v2".

```plan_v2
{
  "intent": "<one sentence — what Workday capability is being exposed>",
  "operation_mode": "create" | "update",
  "target_chatflow_id": "<chatflow ID for UPDATE, null for CREATE>",
  "pattern_id": null,
  "nodes": [
    {"type": "chatOpenAI", "role": "conversational model"},
    {"type": "customTool", "role": "Workday MCP bridge — actions: <list of mcpActions>"}
  ],
  "credentials": [
    {"name": "<workday credential name>", "type": "workdayOAuth", "status": "resolved" | "needed"}
  ],
  "success_criteria": [
    "<testable criterion — e.g., 'Flow returns Worker displayName for a valid worker ID'>",
    "<testable criterion 2>"
  ]
}
```

CREDENTIALS_STATUS: OK
(or CREDENTIALS_STATUS: MISSING / MISSING_TYPES: workdayOAuth)
</output_format>

---

## Patch Context

Workday chatflows use the `customMCP` Tool node inside a standard Flowise Tool node.
The wiring pattern is fixed and deterministic. Emit Patch IR ops to construct it.

<constraints>
Always:
- Use `selectedTool = "customMCP"` inside the Tool node — this is the Flowise MCP bridge.
- Set `mcpServerConfig` as a **stringified JSON string** (not a nested object) — Flowise parses
  it with JSON.parse at runtime; sending an object causes silent misconfig.
- Resolve `workdayOAuth` credential before emitting `BindCredential` — Workday API calls fail
  with 401 at runtime if the credential is not bound, not at compile time.
- Keep `chatflow_only: true` — Workday MCP tools are only supported in CHATFLOW type, not AGENTFLOW.

Never:
- Guess the `mcpActions` list — always read action names from `schemas/workday_mcp.snapshot.json`.
- Set `mcpServerConfig` as a nested JSON object — it must be a stringified JSON string.
</constraints>

### customMCP Tool node wiring pattern (DD-070)

The customMCP pattern requires these Patch IR ops:

```json
[
  {"op_type": "AddNode",   "node_name": "chatOpenAI",  "node_id": "chatOpenAI_0"},
  {"op_type": "AddNode",   "node_name": "bufferMemory", "node_id": "bufferMemory_0"},
  {"op_type": "AddNode",   "node_name": "toolAgent",   "node_id": "toolAgent_0"},
  {"op_type": "AddNode",   "node_name": "customTool",  "node_id": "customTool_0"},
  {"op_type": "SetParam",  "node_id": "chatOpenAI_0",  "param": "modelName", "value": "gpt-4o"},
  {"op_type": "SetParam",  "node_id": "customTool_0",  "param": "selectedTool", "value": "customMCP"},
  {"op_type": "SetParam",  "node_id": "customTool_0",  "param": "selectedToolConfig", "value": {
    "mcpServerConfig": "{\"url\":\"<workday-mcp-url>\",\"headers\":{\"Authorization\":\"$vars.beartoken\"}}",
    "mcpActions": ["getMyInfo", "searchForWorker", "getWorkers"]
  }},
  {"op_type": "SetParam",  "node_id": "customTool_0",  "param": "color", "value": "#4CAF50"},
  {"op_type": "Connect",   "source_id": "chatOpenAI_0",  "target_id": "toolAgent_0", "target_anchor": "model"},
  {"op_type": "Connect",   "source_id": "bufferMemory_0", "target_id": "toolAgent_0", "target_anchor": "memory"},
  {"op_type": "Connect",   "source_id": "customTool_0",  "target_id": "toolAgent_0", "target_anchor": "tools"},
  {"op_type": "BindCredential", "node_id": "chatOpenAI_0",  "credential_id": "<openai-cred-id>"},
  {"op_type": "BindCredential", "node_id": "customTool_0",  "credential_id": "<workday-oauth-cred-id>"}
]
```

Key fields in `selectedToolConfig`:
- `mcpServerConfig`: **string** — stringified JSON with `url` and `headers`.
  Use `$vars.beartoken` as the Authorization value placeholder.
- `mcpActions`: array of action name strings from the MCP blueprint catalog.
  Use exact names from `schemas/workday_mcp.snapshot.json`.

Tool agents require a function-calling model (ChatOpenAI, ChatAnthropic, ChatMistral).

> **TBD**: Full ops catalog for Workday-specific flows (absence management, business processes,
> etc.) will be added as those patterns are validated. See `schemas/workday_mcp.snapshot.json`
> for the current blueprint catalog.

---

## Test Context

> **STATUS**: Partial — happy path + sandbox rules defined. Edge case patterns TBD.

The graph dispatches predictions before you receive this context. **Your role is evaluation only —
do not call any tools.**

### Evaluation criteria for Workday flows

1. Did the response address the input without error strings (`401`, `403`, `JSON.parse error`, etc.)?
2. For Worker queries: does the response include a recognizable Workday data shape (displayName, WID, etc.)?
3. Does the response satisfy the SUCCESS_CRITERIA from the PlanContract?

### Workday-specific failure patterns

- Empty response or `"I couldn't find that"` → likely `mcpActions` list doesn't include the
  right action for the query. Check that action names match the blueprint catalog exactly.
- `401 Unauthorized` → `workdayOAuth` credential not bound or expired. BindCredential op needed.
- `JSON.parse error` on `mcpServerConfig` → `selectedToolConfig.mcpServerConfig` was sent as an
  object instead of a stringified string.
- Response returns sandbox data that looks like test employee names → expected; confirm sandbox
  tenant is configured in `mcpServerConfig.url`.

<output_format>
Trial 1 (happy-path):
  Input: "<the question>"
  Response: "<full response or first 300 chars>"
  Status: PASS | FAIL
  Notes: "<optional>"

Trial 2 (edge-case):
  Input: "<the question>"
  Response: "<full response or first 300 chars>"
  Status: PASS | FAIL
  Notes: "<optional>"

RESULT: HAPPY PATH [PASS/FAIL] | EDGE CASE [PASS/FAIL]
VERDICT: DONE | ITERATE
DIAGNOSIS: <if ITERATE — one sentence on most likely root cause>
</output_format>

> **TBD**: Add Workday sandbox tenant confirmation check and synthetic employee data patterns
> once the first Workday-connected chatflow is validated end-to-end.

---

## Error Reference

| Error | Root Cause | Fix in Patch IR terms |
|---|---|---|
| `401 Unauthorized` | workdayOAuth credential not bound | Add `BindCredential(customTool_0, <workday-cred-id>)` |
| `JSON.parse error` on mcpServerConfig | `mcpServerConfig` sent as object | SetParam value must be a stringified JSON string, not a nested object |
| `customTool missing color` | color field not set | Add `SetParam(customTool_0, color, "#4CAF50")` |
| Empty response / "I couldn't find that" | mcpActions doesn't include right action | Check action names against `schemas/workday_mcp.snapshot.json` |
| `Tool not found: customMCP` | `selectedTool` not set to `"customMCP"` | Add `SetParam(customTool_0, selectedTool, "customMCP")` |
| TBD | TBD | TBD — fill in as Workday errors are encountered |

---

## v2 Activation Checklist

When ready to build full Workday-connected chatflow patterns:

- [ ] Confirm Workday OAuth 2.0 credentials are saved in Flowise (`list_credentials` → type `workdayOAuth`)
- [ ] Validate `schemas/workday_mcp.snapshot.json` has the correct action catalog
- [ ] Build and test the first customMCP tool flow (Worker search)
- [ ] Fill in TBD sections in Discover/Patch/Test with validated patterns
- [ ] Add Workday-specific errors to the Error Reference as encountered
- [ ] Run `python -m flowise_dev_agent.knowledge.refresh --workday-mcp` when the catalog is updated

---

## Changelog

### 0.2.0 (2026-02-24)
- Added YAML frontmatter with triggering description
- Added customMCP tool node wiring pattern (DD-070) to Patch Context
- Added `selectedToolConfig` schema with mcpServerConfig (stringified JSON) + mcpActions
- Added Workday credential type (`workdayOAuth`) to Discover and Test contexts
- Added PlanContract `<output_format>` spec to Discover Context
- Added `<constraints>` block with mcpServerConfig string-vs-object rule
- Added Error Reference entries for customMCP failures
- Applied WHY-based rewrites; removed TBD-only placeholder sections

### 0.1.0 (initial)
- Skeleton placeholder — architecture overview only
- All phase sections TBD
