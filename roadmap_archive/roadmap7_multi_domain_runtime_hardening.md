# Roadmap 7: Multi-Domain Runtime Hardening

**Status:** Planning
**Created:** 2026-02-24
**Branch:** TBD (new branch off main)
**Predecessor:** ROADMAP6_Platform Knowledge (complete)

---

## Context

ROADMAP6 delivered the local-first platform knowledge layer (node schemas, template metadata, credential snapshots, Workday knowledge stubs). This roadmap addresses the five remaining gaps needed to reach a production-grade multi-domain co-developer agent.

### Current-state gaps

1. **Capability-first is not the default** — `build_graph(capabilities=None)` routes sessions through the legacy ReAct patch loop unless the caller explicitly opts in. There is no env var to set the default — control is entirely at graph construction time (`api.py → _get_graph()`).

2. **No cross-domain data contracts** — `plan` is freeform markdown (`str | None`). There is no `PlanContract` model, no domain targets, no credential requirements in structured form. `TestSuite` exists as a minimal dataclass but has no domain-scoped runner or integration tests. Verdicts are grounded in LLM confidence, not structured test outcomes.

3. **PatternStore is not a compiler asset** — patterns live in SQLite with keyword-only LIKE search and no structured metadata (no domain filter, no node_type list, no schema fingerprint). Patterns are never used to seed `GraphIR` — they are "read at discover time, ignored at compile time."

4. **No latency telemetry or drift management** — only cumulative `total_input_tokens` / `total_output_tokens` exist in state. No per-phase timing, no cache hit/miss rates, no schema fingerprint recording, no drift detection policy.

5. **WorkdayCapability is all stubs** — `discover()` returns hardcoded mock data, `compile_ops()` returns `DomainPatchResult(stub=True)`. The real direction (Workday MCP nodes inside Flowise chatflows, not direct Workday API calls from the co-pilot) is not yet implemented.

---

## Goals

- Make **capability-first** the default execution path, with legacy as an explicit compat flag.
- Add a **cross-domain contract layer** — structured `PlanContract`, domain-scoped `TestSuite`, verdict grounded in structured success criteria.
- Upgrade `PatternStore` into a **compiler-influencing asset** — structured metadata, filtered search, pattern-as-base-`GraphIR`.
- Add **drift detection + per-phase telemetry** so the runtime is observable and production-safe.
- Enable **Workday MCP-in-Flowise** as the correct integration model — agent generates Flowise chatflows that include Workday MCP nodes.

## Non-goals (this roadmap)

- Embedding the agent into the Flowise UI (deferred).
- Full semantic validation for every Flowise node type (incremental in later milestones).
- Vector database dependency for pattern or knowledge retrieval.

---

## Milestone 7.1 — Capability-First Default Runtime

### Problem
Sessions default to the legacy ReAct patch loop. There is no way to configure capability-first as default without changing Python code.

### Key files
- `flowise_dev_agent/api.py` — `_get_graph()`, `_initial_state()`, `SessionSummary`
- `flowise_dev_agent/agent/state.py` — add `runtime_mode` field

### Changes

**A. Env var + compat flag** (`api.py`)

Add module-level constant:
```python
_COMPAT_LEGACY = os.environ.get("FLOWISE_COMPAT_LEGACY", "").lower() in ("1", "true", "yes")
```

Update `_get_graph()` to pass `capabilities=[FlowiseCapability(...)]` when `_COMPAT_LEGACY=False` (the new default), or `capabilities=None` when `True`.

**B. `runtime_mode` state field** (`state.py`, after `session_name`)
```python
runtime_mode: str | None  # "capability_first" | "compat_legacy" — set once at creation
```

Set in `_initial_state()` based on `_COMPAT_LEGACY`.

**C. Expose in `SessionSummary`** (`api.py`)
```python
runtime_mode: str | None = Field(None)
```
Extracted from `sv.get("runtime_mode")` in `list_sessions()`.

**D. Hard constraint** — no new logic is added inside the legacy path nodes. `build_graph()` signature is unchanged.

### Acceptance criteria
- Sessions without env var run `discover_capability` + `_make_patch_node_v2`
- `FLOWISE_COMPAT_LEGACY=true` reproduces pre-refactor behavior exactly
- `GET /sessions` returns `runtime_mode` per session
- 28/28 tests pass; new test: `test_capability_first_default`

---

## Milestone 7.2 — Cross-Domain PlanContract + TestSuite

### Problem
Plans are freeform text. Multi-domain sessions have no machine-readable record of which domains are involved, what credentials are needed, or what success looks like. Verdicts rely on LLM confidence rather than structured pass/fail criteria.

### Key files
- `flowise_dev_agent/agent/plan_schema.py` (**new**) — `PlanContract` dataclass + `_parse_plan_contract()`
- `flowise_dev_agent/agent/graph.py` — plan node writes contract to facts; converge node reads it
- `flowise_dev_agent/agent/domain.py` — extend `TestSuite` with `domain_scopes` + `integration_tests`

### Changes

**A. `PlanContract` dataclass** (`plan_schema.py`)
```python
@dataclass
class PlanContract:
    goal: str
    domain_targets: list[str]          # ["flowise"] or ["flowise", "workday"]
    credential_requirements: list[str] # ["openAIApi", "workdayOAuth"]
    data_fields: list[str]             # named fields flowing across domains
    pii_fields: list[str]              # fields flagged as PII
    success_criteria: list[str]        # testable conditions from ## SUCCESS CRITERIA
    action: str                        # "CREATE" | "UPDATE"
    raw_plan: str                      # original plan text, preserved verbatim
```

**B. New plan prompt sections** (`graph.py`, `_PLAN_BASE`)

Add three required sections to the LLM instructions:
```
## DOMAINS
flowise | flowise,workday  (comma-separated)

## CREDENTIALS
<type1>, <type2>  (use exact Flowise credentialName values)

## DATA_CONTRACTS
<field>: <source_domain> → <target_domain> [PII]
```

**C. Parser** (`plan_schema.py`)

`_parse_plan_contract(plan_text, chatflow_id) -> PlanContract` — extracts each section with regex, tolerant of absent sections (defaults to empty lists).

**D. Plan node writes contract to facts** (`graph.py`, `_make_plan_node`)

After LLM call:
```python
contract = _parse_plan_contract(plan_text, state.get("chatflow_id"))
facts_update = {"flowise": {**existing_facts, "plan_contract": asdict(contract)}}
return {"plan": plan_text, "facts": facts_update, ...}
```

**E. Extend `TestSuite`** (`domain.py`)
```python
domain_scopes: list[str] = field(default_factory=list)       # domains to run tests for
integration_tests: list[str] = field(default_factory=list)   # cross-domain scenario strings
```

**F. Verdict grounding** (`graph.py`, `_make_converge_node`)

If `facts["flowise"]["plan_contract"]` is present, inject extracted `success_criteria` into the converge prompt:
```
REQUIRED SUCCESS CRITERIA (from plan contract):
- <criterion 1>
- <criterion 2>
Verdict MUST reference which criteria passed/failed.
```

### Acceptance criteria
- Plan node always writes a parseable `PlanContract` to `facts["flowise"]["plan_contract"]`
- Multi-domain requirement produces `domain_targets: ["flowise", "workday"]`
- Converge verdict references plan contract success criteria by name
- 28/28 tests pass; new test: `test_plan_contract_parsing`

---

## Milestone 7.3 — PatternCapability Upgrade

### Problem
Patterns are saved with keyword-only metadata. They cannot be filtered by domain or node type. They never seed the `GraphIR` — the compiler always starts from scratch, even when a perfect structural template exists.

### Key files
- `flowise_dev_agent/agent/pattern_store.py` — schema migration + structured metadata + `apply_as_base_graph()`
- `flowise_dev_agent/agent/graph.py` — plan node writes pattern hit to `artifacts`; patch v2 Phase A reads it

### Changes

**A. Schema migration** (`pattern_store.py`)

Add columns via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`:
```sql
domain           TEXT DEFAULT 'flowise',
node_types       TEXT DEFAULT '',     -- JSON array: ["chatOpenAI", "bufferMemory"]
category         TEXT DEFAULT '',     -- "OpenAI chatflow", "HTTP API", "MCP bridge"
schema_fingerprint TEXT DEFAULT '',   -- flowise_nodes.snapshot fingerprint at save time
last_used_at     REAL DEFAULT NULL
```

**B. Structured search** (`pattern_store.py`)

New method: `async search_patterns_filtered(keywords, domain=None, category=None, node_types=None, limit=3)`
- SQL WHERE on `domain` + `category` + keyword LIKE
- `node_types` overlap: Python-side JSON check after fetch

**C. `apply_as_base_graph()` method** (`pattern_store.py`)
```python
async def apply_as_base_graph(self, pattern_id: int) -> GraphIR:
    """Return a GraphIR seeded from a saved pattern's flow_data."""
    # increments success_count and sets last_used_at
```

**D. Plan node uses pattern as base** (`graph.py`, `_make_plan_node`)

After template hint injection, search for a matching pattern:
```python
if pattern_store:
    matches = await pattern_store.search_patterns_filtered(keywords, domain="flowise", limit=1)
    if matches:
        base_ir = await pattern_store.apply_as_base_graph(matches[0]["id"])
        artifacts_update = {"flowise": {**existing_artifacts, "base_graph_ir": base_ir.to_flow_data()}}
```

**E. Patch v2 Phase A reads `base_graph_ir`** (`graph.py`, `_make_patch_node_v2`)

If no `chatflow_id` and `artifacts["flowise"]["base_graph_ir"]` present, use it as `base_graph` instead of empty `GraphIR()`. Note this in the Phase B user context so the LLM knows not to re-add existing nodes.

**F. Converge node enriches pattern metadata on save**

When saving pattern after DONE verdict, also pass:
- `domain="flowise"`, `node_types=json.dumps([...])`, `category` (from PATTERN section)
- `schema_fingerprint` from `knowledge_provider.node_schemas.meta_fingerprint`

### Acceptance criteria
- Pattern records saved with new metadata fields populated
- Sessions with a matching pattern show `base_graph_ir` in `artifacts["flowise"]`
- Patch IR ops on a pattern-seeded build contain fewer `AddNode` ops vs an empty start
- 28/28 tests pass; new test: `test_pattern_as_base_graph`

---

## Milestone 7.4 — Drift Management + Telemetry Hardening

### Problem
No per-phase timing or cache metrics exist. Schema drift (snapshot updated between sessions) is undetected and can silently produce incorrect ops or anchor mismatches.

### Key files
- `flowise_dev_agent/agent/metrics.py` (**new**) — `PhaseMetrics` + `MetricsCollector`
- `flowise_dev_agent/agent/graph.py` — instrument discover, patch, test, converge phases
- `flowise_dev_agent/knowledge/provider.py` — add `meta_fingerprint` property to `NodeSchemaStore`
- `flowise_dev_agent/api.py` — surface metrics in `SessionSummary`

### Changes

**A. `PhaseMetrics` + `MetricsCollector`** (`metrics.py`)
```python
@dataclass
class PhaseMetrics:
    phase: str            # "discover" | "plan" | "patch_b" | "patch_d" | "test" | "converge"
    start_ts: float
    end_ts: float
    duration_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    tool_call_count: int = 0
    cache_hits: int = 0   # schema/credential lookups served from snapshot
    repair_events: int = 0
```

`MetricsCollector` is an async context manager. On `__aexit__`, appends the completed `PhaseMetrics` to a list accumulated in the calling node's return dict under `debug["flowise"]["phase_metrics"]`.

**B. Instrument phases** (`graph.py`)

Wrap with `MetricsCollector`:
- `discover_capability` — tool_call_count, tokens
- Patch v2 Phase B (LLM call) — input/output tokens
- Patch v2 Phase D (schema resolution) — cache_hits, repair_events
- Test node — tokens

**C. Drift detection policy** (env var `FLOWISE_SCHEMA_DRIFT_POLICY`)

Values: `warn` (default) | `fail` | `refresh`

In Patch v2 Phase D, after schema resolution:
1. Read `facts["flowise"]["schema_fingerprint"]` from prior iteration (if any)
2. Compare to current `knowledge_provider.node_schemas.meta_fingerprint`
3. If mismatch: apply policy
4. Write current fingerprint to `facts["flowise"]["schema_fingerprint"]`

**D. `meta_fingerprint` property** (`provider.py`, `NodeSchemaStore`)
```python
@property
def meta_fingerprint(self) -> str | None:
    if self._meta_path.exists():
        return json.loads(self._meta_path.read_text()).get("fingerprint")
    return None
```

**E. Surface metrics in `SessionSummary`** (`api.py`)
```python
total_repair_events: int = Field(0)
total_phases_timed: int = Field(0)
```
Extracted from `debug["flowise"].get("phase_metrics", [])`.

### Acceptance criteria
- `debug["flowise"]["phase_metrics"]` populated for discover, patch, test phases
- Normal sessions show `repair_events=0` (all lookups served from snapshot)
- `FLOWISE_SCHEMA_DRIFT_POLICY=fail` returns an error state when fingerprint changes between iterations
- 28/28 tests pass; new test: `test_phase_metrics_recorded`

---

## Milestone 7.5 — Workday M3: MCP-in-Flowise

### Problem
`WorkdayCapability` is fully stubbed. The correct integration model is to generate Flowise **chatflows** that include Workday integration via Flowise's existing **Custom MCP** tool configuration — not a dedicated Workday node, and not a direct Workday API call from the co-pilot process.

Flowise currently represents MCP tooling by embedding a `customMCP` tool config inside a Tool node. The agent must learn to emit Patch IR ops that produce exactly this config shape. No live MCP discovery or catalog ingestion is required for this milestone.

### How Flowise wires Custom MCP

The persisted structure the agent must produce is:

```
selectedTool = "customMCP"

selectedToolConfig:
  mcpServerConfig   = STRINGIFIED JSON:
                      {
                        "url": "<MCP_SERVER_URL>",
                        "headers": {
                          "Authorization": "<Flowise variable expression>"
                        }
                      }
  mcpActions        = ["getMyInfo", "searchForWorker", "getWorkers"]
```

Important constraints:
- `mcpServerConfig` is stored as a **string**, not a nested object.
- The `Authorization` value uses a Flowise variable expression (e.g. `$vars.beartoken`) and is **never hard-coded** by the agent.
- `mcpActions` is the list of MCP tool names Flowise exposes to the agent/tool layer.
- The output must be a **chatflow scaffold** — not an agentflow.

### Default action list

When no narrower action set is requested, the following three actions are used:

```
getMyInfo
searchForWorker
getWorkers
```

Additional actions may be selected based on the plan, but these three form the baseline.

### Key files
- `flowise_dev_agent/agent/domains/workday.py` — implement `discover()` + `compile_ops()`
- `flowise_dev_agent/knowledge/workday_provider.py` — implement `WorkdayMcpStore`
- `flowise_dev_agent/knowledge/refresh.py` — implement `refresh_workday_mcp()`
- `schemas/workday_mcp.snapshot.json` — replace `[]` with MCP wiring blueprint entries
- `tests/test_workday_mcp_integration.py` (**new**) — mocked smoke tests

### Changes

**A. MCP wiring blueprint** (`schemas/workday_mcp.snapshot.json`)

Replace the empty stub array with a small catalog of blueprint entries. Each entry describes one MCP action set that the agent can wire. Example entry shape:

```json
{
  "blueprint_id": "workday_default",
  "description": "Default Workday MCP actions for worker lookup and self-service",
  "selected_tool": "customMCP",
  "mcp_server_url_placeholder": "<WORKDAY_MCP_SERVER_URL>",
  "auth_var": "$vars.beartoken",
  "mcp_actions": ["getMyInfo", "searchForWorker", "getWorkers"],
  "credential_type": "workdayOAuth",
  "chatflow_only": true
}
```

`chatflow_only: true` signals that this blueprint is valid only in a chatflow context and must not be applied to agentflows.

**B. Implement `WorkdayMcpStore`** (`workday_provider.py`)

Replace `NotImplementedError` stubs following the `NodeSchemaStore` pattern:
- Lazy `_load()` from `schemas/workday_mcp.snapshot.json`
- `get(blueprint_id) -> dict | None` — O(1) index lookup by `blueprint_id`
- `find(tags, limit=3) -> list[dict]` — keyword search across `description` and `mcp_actions`
- `is_stale(ttl_seconds) -> bool` — TTL from `WORKDAY_MCP_SNAPSHOT_TTL_SECONDS` env var
- `item_count -> int`

**C. Implement `refresh_workday_mcp()`** (`refresh.py`)

Replace the no-op stub:
- Reads `WORKDAY_MCP_CATALOG_PATH` env var (path to a local JSON catalog)
- Normalizes entries to blueprint format
- Writes `schemas/workday_mcp.snapshot.json` + `workday_mcp.meta.json`
- Diff reporting (added/changed/removed entries)
- Falls back to writing the built-in default blueprint if `WORKDAY_MCP_CATALOG_PATH` is not set

**D. Implement `WorkdayCapability.discover()`** (`domains/workday.py`)

Replace hardcoded mock with real blueprint-driven discovery:

1. Query `workday_knowledge_provider.mcp_store.find(keywords from context)` for relevant blueprints
2. Check `credential_store.all_by_type("workdayOAuth")` for available OAuth credentials
3. Select the best-matching action list (defaults to `["getMyInfo", "searchForWorker", "getWorkers"]` when no narrower match)
4. Return `DomainDiscoveryResult` with:
   - `summary`: `"Found N Workday MCP blueprint(s). OAuth credential: present/missing. Actions selected: [...]"`
   - `facts`: `{"selected_blueprint_id": "...", "mcp_actions": [...], "oauth_credential_id": "..."}`
   - `artifacts`: `{"selected_tool": "customMCP", "mcp_actions": [...]}`

**E. Implement `WorkdayCapability.compile_ops()`** (`domains/workday.py`)

Given the plan text and the `facts`/`artifacts` produced by `discover()`, emit Patch IR ops that produce the Custom MCP tool config shape:

1. Emit `AddNode` for the Tool node that will hold the Custom MCP config, with params:
   - `selectedTool` = `"customMCP"`
   - `selectedToolConfig.mcpServerConfig` = stringified JSON `{"url": "<MCP_SERVER_URL>", "headers": {"Authorization": "$vars.beartoken"}}` (URL placeholder, auth via Flowise variable)
   - `selectedToolConfig.mcpActions` = the selected action list from `facts`
2. Emit `BindCredential` for `credential_type="workdayOAuth"` on the Tool node
3. Return `DomainPatchResult(ops=ops, stub=False)`

The MCP server URL placeholder is intentional — the developer supplies the real URL when they apply the chatflow to their Workday tenant.

**F. Integration smoke tests** (`tests/test_workday_mcp_integration.py`)

Mocked tests (no live Workday API or MCP server) that verify:

- `WorkdayCapability.discover()` returns non-stub data from `WorkdayMcpStore` when the snapshot has entries
- `compile_ops()` produces at least one `AddNode` op with:
  - `selectedTool` param = `"customMCP"`
  - `selectedToolConfig.mcpServerConfig` param containing a stringified JSON with `url` and `Authorization` keys
  - `selectedToolConfig.mcpActions` param containing at least the three default actions
- `compile_ops()` produces at least one `BindCredential` op with `credential_type="workdayOAuth"`
- The full ops list passes `validate_patch_ops()`
- No agentflow-specific keys appear in the produced op params

### Non-goals (this milestone)
- Full MCP catalog ingestion from a live Workday MCP server (no `tools/list` call)
- Live action discovery — the default action list is embedded in the blueprint
- Workday REST custom tools (placeholder only; full implementation is a future milestone)
- Agentflow support for the Workday MCP wiring

### Acceptance criteria
- `WorkdayMcpStore` loads the blueprint snapshot and returns entries without raising
- `WorkdayCapability.discover()` returns `stub=False` data when the snapshot is populated
- `compile_ops()` produces ops that set `selectedTool="customMCP"`, `mcpServerConfig` (stringified), and `mcpActions` (default list or subset)
- Output is clearly a chatflow scaffold — no agentflow-only keys present
- All integration smoke tests pass (mocked, no live dependencies)
- Full regression: all prior tests + new Workday tests pass

---

## Milestone Sequencing

```
7.1  Capability-first default        (1–2 days)
7.2  PlanContract + TestSuite        (2–3 days, depends on 7.1)
7.3  PatternCapability upgrade       (2–3 days, independent of 7.2)
7.4  Drift + telemetry               (1–2 days, depends on 7.1)
7.5  Workday MCP-in-Flowise          (3–5 days, depends on 7.2)
```

7.1 and 7.3 can be implemented in parallel. 7.4 can be worked alongside 7.2.

---

## Files Modified Summary

| File | Milestones |
|------|-----------|
| `flowise_dev_agent/api.py` | 7.1, 7.2, 7.4 |
| `flowise_dev_agent/agent/state.py` | 7.1 |
| `flowise_dev_agent/agent/graph.py` | 7.1, 7.2, 7.3, 7.4 |
| `flowise_dev_agent/agent/domain.py` | 7.2 |
| `flowise_dev_agent/agent/pattern_store.py` | 7.3 |
| `flowise_dev_agent/knowledge/provider.py` | 7.4 |
| `flowise_dev_agent/knowledge/refresh.py` | 7.5 |
| `flowise_dev_agent/knowledge/workday_provider.py` | 7.5 |
| `flowise_dev_agent/agent/domains/workday.py` | 7.5 |
| `schemas/workday_mcp.snapshot.json` | 7.5 |

**New files:**

| File | Milestone |
|------|----------|
| `flowise_dev_agent/agent/plan_schema.py` | 7.2 |
| `flowise_dev_agent/agent/metrics.py` | 7.4 |
| `tests/test_workday_mcp_integration.py` | 7.5 |

---

## Definition of Done (for this roadmap)

The stack is "production-grade multi-domain co-developer" when:

- [ ] Capability-first is the default and stable — legacy is an explicit opt-in
- [ ] Plans encode domains, credentials, data contracts, and success criteria in machine-readable form
- [ ] Verdict is grounded in structured test outcomes, not LLM confidence
- [ ] Patterns materially reduce ops/tool calls and are version-aware with schema fingerprints
- [ ] Drift is detectable (warn), blockable (fail), and surfaced in session summaries
- [ ] Per-phase telemetry is captured: tokens, latency, cache hits, repair events
- [ ] Workday MCP flows can be built and verified end-to-end inside Flowise
