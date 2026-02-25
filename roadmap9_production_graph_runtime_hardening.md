# ROADMAP9_Production Graph + Runtime Hardening

Purpose: consolidate the remaining "production-worthy" work into a single, sequenced roadmap that reconciles:
- the original 6 pending items (knowledge-first contract alignment, refresh reproducibility, schema repair gating correctness, telemetry/drift polish, compact-context enforcement, PatternCapability maturity), and
- the new platform upgrades we just agreed on (Postgres, node-level streaming, environment scoping, production-grade LangGraph topology).

This roadmap explicitly avoids overengineering and focuses on fast iteration, token efficiency, and hardening through deterministic control surfaces (graph routing, budgets, and local-first knowledge).

---

## 0) Guiding principles

1) **Knowledge-first**: local snapshots are the default truth; APIs are repair-only.
2) **Deterministic-first patching**: Patch IR + compiler is the primary edit path; ReAct loops are bounded fallback.
3) **Fast feedback**: stream node lifecycle events; keep payloads small.
4) **Auditable operations**: persist checkpoints + event logs in Postgres.
5) **Environment-scoped truth**: snapshots and caches are scoped by Flowise base URL / env label.

---

## 1) Milestone 9.1: Postgres persistence (checkpoints + event log)

### Goal
Move from SQLite to Postgres locally (Docker now, managed DSN later), enabling:
- resumable sessions under multi-worker future,
- durable audit trails (event replay),
- cleaner rollback diagnostics.

### Deliverables
- Local Docker Postgres compose file.
- `POSTGRES_DSN` and `CHECKPOINTER=postgres|sqlite` config switch.
- Postgres-backed LangGraph checkpointer enabled when DSN set.
- A minimal `session_events` table with:
  - session_id
  - seq (monotonic int) or timestamp
  - node_name
  - phase
  - status (started/completed/failed/interrupted)
  - duration_ms
  - summary (optional short string)
  - payload_json (optional, bounded)

### Acceptance criteria
- Fresh checkout + `docker compose up` yields working sessions with Postgres checkpointer.
- Events are persisted and can be replayed chronologically per session.
- Switching to managed Postgres is a DSN-only change.

---

## 2) Milestone 9.2: Node-level streaming (SSE) backed by Postgres

### Goal
Provide Cursor/Claude-style "what's happening" visibility without token burn.

### Deliverables
- `GET /sessions/{id}/stream` SSE endpoint that emits node lifecycle events.
- Emission policy:
  - node_start, node_end, node_error, interrupt
  - tool_call_start/tool_call_end (optional, name + duration only)
- Event payloads are small and reference artifacts/facts keys instead of including blobs.
- All events also written to Postgres event log (Milestone 9.1).

### Acceptance criteria
- A client can connect to SSE and see progress in near-real-time.
- No raw tool payloads are streamed.
- Stream remains functional across resume/HITL interrupts (session can reconnect).

---

## 3) Milestone 9.3: Knowledge-first runtime contract alignment (kill "always get_node")

### Goal
Ensure the LLM contract and graph routing match Roadmap 6's intent:
- use local schema snapshot first,
- call Flowise API only on repair conditions.

### Deliverables
- Update discover/planning prompts and/or tool descriptions to:
  - assume schema exists locally,
  - request repair only when missing or validation fails due to schema mismatch.
- Enforce in graph logic:
  - route schema misses to a targeted `repair_schema` node (one node type at a time),
  - cap repairs per iteration.

### Acceptance criteria
- Typical runs do not call `get_node` for known nodes.
- Repair events are logged when they occur, and are rare.

---

## 4) Milestone 9.4: Refresh reproducibility (canonical node reference + CI dry-run)

### Goal
Make snapshots deterministic and reproducible across machines.

### Deliverables
- Establish a canonical markdown source file name in repo root:
  - `FLOWISE_NODE_REFERENCE.md` (recommended) or rename refresh to match actual file.
- Refresh CLI must fail with actionable message if canonical reference is missing.
- Add a lightweight CI/local check:
  - `python -m flowise_dev_agent.knowledge.refresh --nodes --dry-run` succeeds.

### Acceptance criteria
- Clean checkout can regenerate node snapshots deterministically from the canonical source.
- Repo includes the canonical source or refresh code matches the canonical filename.

---

## 5) Milestone 9.5: NodeSchemaStore repair gating correctness (version/hash logic)

### Goal
Make schema repair decisioning correct and test-backed.

### Deliverables
- Fix action selection logic to correctly compare:
  - local_version vs api_version (skip only if equal)
  - local_hash vs api_hash (skip only if equal when versions absent)
- Add unit tests:
  - same version -> skip
  - different version -> update
  - no version, same hash -> skip
  - no version, different hash -> update
- Record gating decision into debug/repair event payload.

### Acceptance criteria
- Tests pass and demonstrate correct gating behavior.
- Repair only overwrites when justified by version/hash.

---

## 6) Milestone 9.6 (REPLACEMENT): Production-grade LangGraph Topology v2 (Create + Update, Full-Flow Baseline, Budgets + Bounded Retries)

### Why this milestone is being replaced
The previous Milestone 9.6 topology was optimized for “create new chatflow” and assumed a single base flow context. In practice, production usage requires **two operational modes**:

- **CREATE**: build a new chatflow from scratch (optionally from a pattern).
- **UPDATE**: modify an existing chatflow, often referenced by **name** rather than ID, requiring target resolution and full-flow baseline loading.

This replacement milestone introduces a topology that:
- supports CREATE + UPDATE with minimal branching complexity,
- always fetches the full flow on UPDATE (for correctness),
- keeps prompts small via summaries + targeted excerpts (for speed and token control),
- enforces reliability through graph-level budgets and bounded retries (not just prompt instructions),
- integrates naturally with Postgres persistence + node-level streaming milestones.

---

### Primary goals
1) **Support both CREATE and UPDATE** in one canonical graph.
2) **Resolve update targets by name or recency** with a bounded candidate list and HITL selection to avoid wrong-target edits.
3) **Always load the full existing flow for UPDATE exactly once** and use it as the deterministic baseline for Patch IR compilation and diffing.
4) **Keep the LLM context compact** by default (summary + targeted excerpts only), to minimize token cost and latency.
5) **Enforce bounded retries + budgets at the graph level**, including schema repair routing, to prevent runaway loops.
6) Provide **node-level streaming events** for a “co-developer” experience (ties into 9.2), without streaming tokens.

---

### Non-goals (explicit)
- Do not implement background indexing or scheduled chatflow catalogs (future).
- Do not implement embeddings/vector DB for schemas in this milestone (future).
- Do not introduce a tool-gating subsystem; rely on graph structure + budgets.
- Do not implement automatic rollback; only capture rollback anchors and diffs.

---

## 6.1) Updated node set (Topology v2)

### Phase A: Intent + context hydration
1) **classify_intent** (LLM-lite, no tools)
   - Purpose: determine CREATE vs UPDATE, extract candidate chatflow name if provided
   - Outputs:
     - `facts.flowise.intent = "create" | "update"`
     - `facts.flowise.target_name` (optional)
     - `facts.flowise.intent_confidence` (optional)

2) **hydrate_context** (deterministic, local-only)
   - Purpose: load platform knowledge (node schemas, templates, credentials snapshots) without network calls
   - Outputs:
     - `facts.flowise.schema_fingerprint`
     - any cached snapshot metadata needed for planning/compile

### Phase B: Update target resolution (UPDATE only)
3) **resolve_target** (tool call permitted, bounded)
   - Purpose: list available chatflows, rank by recency, filter by fuzzy name match if provided
   - Behavior:
     - If `facts.flowise.target_name` exists:
       - return top matches by fuzzy match score, then recency
     - Else:
       - return most recently updated chatflows
   - Outputs:
     - `facts.flowise.top_matches` (limit 10 recommended)
       - include: id, name, updated_at (or best available proxy), optional tags

4) **HITL_select_target** (interrupt)
   - Purpose: user selects correct chatflow or decides to create new
   - Outputs:
     - `facts.flowise.operation_mode = "update" | "create"`
     - `facts.flowise.target_chatflow_id` if update

### Phase C: Full-flow baseline load (UPDATE only)
5) **load_current_flow** (tool call permitted, exactly once)
   - Purpose: fetch full flowData for selected target
   - Outputs:
     - `artifacts.flowise.current_flow_data` (full JSON)
     - `facts.flowise.current_flow_hash` (hash/fingerprint)
   - Note: This full blob is NOT injected into LLM prompts by default.

6) **summarize_current_flow** (deterministic; LLM optional but discouraged)
   - Purpose: produce compact structured summary for the LLM
   - Summary structure (stored in facts):
     - node_count, edge_count
     - node_types histogram
     - top node labels (limit N)
     - key “tool nodes” present (custom tools, MCP/customMCP tool, HTTP nodes, etc.)
     - optional entry/output markers if detectable
   - Outputs:
     - `facts.flowise.flow_summary`

### Phase D: Planning + patch generation (CREATE and UPDATE)
7) **plan** (LLM, no tools)
   - Purpose: produce a plan that references:
     - operation_mode (create/update)
     - target flow summary (update)
     - expected tool nodes (Flowise MCP wiring, Workday customMCP wiring, etc.)
   - Outputs:
     - `artifacts.plan`

8) **HITL_plan** (interrupt)
   - Purpose: approve plan and target selection, confirm constraints

9) **define_patch_scope** (LLM-lite, no tools)
   - Purpose: enforce incremental changes and bound complexity
   - Outputs:
     - `facts.patch.max_ops` (default lower in UPDATE)
     - `facts.patch.focus_area` (optional)
     - `facts.patch.protected_nodes` (optional)

10) **compile_patch_ir** (LLM, no tools)
   - Purpose: emit Patch IR ops ONLY, as JSON
   - Inputs:
     - CREATE: pattern skeleton summary OR empty baseline summary
     - UPDATE: `facts.flowise.flow_summary` + targeted excerpts only when necessary
   - Outputs:
     - `artifacts.patch_ir`

11) **compile_flow_data** (deterministic compiler)
   - Purpose: apply Patch IR deterministically to a base:
     - CREATE base: empty GraphIR or selected Pattern skeleton
     - UPDATE base: normalized GraphIR from `artifacts.flowise.current_flow_data`
   - Outputs:
     - `artifacts.proposed_flow_data`
     - `facts.flowise.proposed_flow_hash`

12) **validate** (deterministic)
   - Purpose: validate structural correctness (schema, required inputs, anchors, etc.)
   - Outputs:
     - `artifacts.validation_report`
     - `facts.validation.ok = true|false`
     - `facts.validation.failure_type` (schema_mismatch | structural | other)
     - `facts.validation.missing_node_types` (if schema-related)

### Phase E: Repair + bounded retries (conditional)
13) **repair_schema** (deterministic, targeted)
   - Trigger: only when validate indicates schema mismatch or missing schema for specific node type(s)
   - Behavior:
     - repair only the missing node types (one at a time or small batch)
     - update snapshot store accordingly
   - Outputs:
     - `facts.repair.repaired_node_types`
     - `facts.repair.count += n`

### Phase F: Write, test, evaluate
14) **preflight_validate_patch** (deterministic)
   - Purpose: enforce budgets + safety checks before write
   - Checks:
     - patch ops count <= `facts.patch.max_ops`
     - repair count <= budget
     - retries <= budget
   - Outputs:
     - `facts.preflight.ok`

15) **apply_patch** (single write, guarded)
   - Purpose: one write to Flowise with write guard + payload hash
   - Outputs:
     - `facts.apply.ok`
     - `facts.apply.chatflow_id` (created or updated)
     - store rollback anchor refs:
       - UPDATE: pre_patch_flow_hash
       - CREATE: created id + initial hash

16) **test** (bounded)
   - Purpose: run minimal smoke tests (Flowise predict, node wiring sanity)
   - Outputs:
     - `artifacts.test_report`

17) **evaluate** (deterministic diff + rubric; optional small LLM)
   - Purpose:
     - produce a concise diff summary:
       - nodes added/removed
       - params changed
       - edges changed
     - produce verdict: done vs iterate
   - Outputs:
     - `artifacts.diff_summary`
     - `facts.verdict = done|iterate`
     - `facts.next_action` (optional)

18) **HITL_review** (interrupt)
   - Purpose: user sees what changed and confirms next iteration or completion

---

## 6.2) Graph routing rules (Create vs Update and repairs)

### CREATE branch
- classify_intent → hydrate_context → plan → HITL_plan → define_patch_scope → compile_patch_ir → compile_flow_data → validate → preflight_validate_patch → apply_patch → test → evaluate → HITL_review

### UPDATE branch (Option A behavior)
- classify_intent → hydrate_context → resolve_target → HITL_select_target
  - if user selects target: load_current_flow → summarize_current_flow → plan → …
  - if user chooses “create new”: route to CREATE flow at plan

### Schema mismatch repair routing
- validate (schema_mismatch) → repair_schema → compile_patch_ir (retry once) → compile_flow_data → validate
- validate failures not related to schema mismatch:
  - route to HITL with concise error explanation (avoid tool thrash)

---

## 6.3) Budgets and bounded retries (graph-level enforcement)

### Budget counters stored in state/facts
- `facts.budgets.max_patch_ops_per_iter`
- `facts.budgets.max_schema_repairs_per_iter`
- `facts.budgets.max_total_retries_per_iter`
- `facts.budgets.max_tool_calls_soft` (optional tracking; not gating framework)

### Default budget policy (speed-oriented)
- CREATE:
  - max_patch_ops_per_iter: 12–20
  - max_schema_repairs_per_iter: 2
  - retries: 1
- UPDATE:
  - max_patch_ops_per_iter: 6–12
  - max_schema_repairs_per_iter: 2
  - retries: 1

### Enforcement points
- preflight_validate_patch blocks write when budgets exceeded and routes to HITL
- repair_schema increments repair count and blocks additional repairs beyond budget
- compile_patch_ir retries capped at 1 additional attempt after repair

---

## 6.4) Context strategy (critical for speed)

### Full flow handling (UPDATE)
- Full flow JSON is always fetched and stored in artifacts.
- LLM context receives:
  - `facts.flowise.flow_summary` by default
  - targeted excerpts only when necessary:
    - a node’s param block
    - immediate edges
  - never full `flowData` by default

### Snapshot knowledge handling
- node schemas/templates/credentials are used locally first (hydrate_context)
- repair_schema is the only path that triggers API-based schema repair

---

## 6.5) Tooling implications (MCP and additional tools placement)

### Required tool abilities for this milestone
- list chatflows (for resolve_target)
- get chatflow by id (for load_current_flow)
- apply/create chatflow (existing apply_patch path)
- optional: predict/test endpoint (test node)

### Workday MCP and custom tools
- No change required to 7.5 in this milestone.
- However, the updated topology must ensure:
  - summarize_current_flow identifies whether a chatflow already includes Workday customMCP wiring
  - compile_patch_ir can choose to add/modify customMCP tool config nodes when requested

---

## 6.6) Deliverables

1) Updated graph implementation:
   - new nodes and conditional routing
   - create vs update mode support
2) Updated state schema fields:
   - operation_mode, target_chatflow_id, current_flow_hash, flow_summary, budgets, retry counters
3) Deterministic summarize_current_flow utility
4) validate + repair_schema routing
5) preflight budget enforcement
6) Diff summary generation for HITL_review

---

## 6.7) Acceptance criteria

### Functional
- UPDATE by name:
  - shows top matches (limit 10), sorted by best match then most recently updated
  - user selects target via HITL
  - agent fetches full flow exactly once
  - produces a minimal delta patch, not a full rewrite
- UPDATE by recency:
  - user provides no name and can select from “most recently updated” list
- CREATE:
  - continues to work exactly as before

### Reliability + speed
- Typical UPDATE flow requires:
  - 1 list call + 1 get call + 1 write call (plus optional test call)
- No uncontrolled loops:
  - bounded retries and patch budgets are enforced
- LLM prompt size remains stable:
  - full flow JSON not injected by default
  - summaries + targeted excerpts only

### Transparency
- HITL_review includes a concise diff summary of changes.

---

---

## 7) Milestone 9.7: Telemetry and drift polish (session-level summaries)

### Goal
Make performance and reliability auditable at-a-glance.

### Deliverables
- Per-node timings captured into:
  - debug["flowise"]["phase_metrics"]
- Session summary includes:
  - total tool calls by tool name
  - total repair events
  - total time per phase
  - current schema fingerprint
- Drift policy remains configurable:
  - warn/fail/refresh (refresh can be "request refresh" if not implemented)

### Acceptance criteria
- You can identify why a session was slow without digging into raw logs.
- Drift is detectable and consistent across runs.

---

## 8) Milestone 9.8: Compact-context enforcement audit (no schema/blob leakage)

### Goal
Prevent regressions where snapshots/tool payloads enter the LLM transcript.

### Deliverables
- Audit all prompt assembly points.
- Enforce:
  - only "top-k schema excerpts" are ever injected,
  - raw snapshots remain in artifacts/debug only,
  - tool results summarized into bounded structures.
- Add a regression test that fails if prompt contains large JSON snapshot patterns.

### Acceptance criteria
- Prompts never include entire snapshots.
- Token usage remains stable over multi-iteration sessions.

---

## 9) Milestone 9.9: PatternCapability maturity tuning (reduce ops + calls)

### Goal
Make patterns a default accelerator (when confidence is high), not a nice-to-have.

### Deliverables
- Ensure pattern metadata always stored:
  - domain, node_types, category, schema_fingerprint, last_used_at
- Default behavior:
  - apply pattern as base Graph IR for eligible sessions,
  - reduce Patch IR ops by starting from a known skeleton.
- Add metrics:
  - % sessions using a pattern
  - avg Patch IR ops count with/without patterns
  - avg tool calls with/without patterns

### Acceptance criteria
- Pattern-start sessions measurably reduce ops and tool calls.
- Patterns remain safe under drift via fingerprint checks.

---

## 10) Sequencing and recommended implementation order

P0 (unblocks performance and correctness):
1) ~~9.3 Knowledge-first contract alignment~~ **COMPLETE (DD-075)**
2) ~~9.5 Repair gating correctness + tests~~ **COMPLETE (DD-076)**
3) ~~9.4 Refresh reproducibility~~ **COMPLETE (DD-077)**

P1 (production experience):
4) ~~9.1 Postgres persistence~~ **COMPLETE (DD-078)**
5) ~~9.2 Node-level streaming (SSE) backed by event log~~ **COMPLETE (DD-079)**

P2 (hardening and scale):
6) ~~9.6 Production-grade graph topology (budgets + retries)~~ **COMPLETE (DD-080)**
7) 9.7 Telemetry/drift polish — **PENDING**
8) 9.8 Compact-context audit — **PENDING**
9) ~~9.9 PatternCapability tuning~~ **COMPLETE (DD-081)**

---

## 11) Definition of Done for ROADMAP9

ROADMAP9 is complete when:
- Sessions are resumable with Postgres checkpointer,
- Node-level events stream in real time and are persisted,
- Schema usage is local-first with repair-only API calls,
- Refresh is reproducible from a canonical reference,
- Repair gating is correct and test-backed,
- Graph enforces budgets and bounded retries,
- Telemetry and drift are summarized per session,
- Prompts never include large snapshots,
- Patterns reduce Patch IR ops and tool calls in practice.
