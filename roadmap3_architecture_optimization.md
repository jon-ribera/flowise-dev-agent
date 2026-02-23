# Roadmap 3: Architecture Optimization — Multi-Domain Abstraction Layer

**Status:** Milestone 1 in progress
**Created:** 2026-02-23
**Branch:** feat/strategic-architecture-optimization

---

## Problem Statement

The codebase has three friction points that compound as new domains (Workday) are added:

1. **Raw tool results bleed into LLM context.** `result_to_str()` serializes full API responses as JSON (potentially 162k tokens for `list_nodes`) directly into the message history. The compact context policy exists in documentation but is not enforced in code.

2. **Tool names are not canonical.** Bare names like `get_node` work today because there is one domain. With two domains, `flowise.get_node` and `workday.get_node` are distinct operations. There is no registry that enforces namespacing or phase permissions.

3. **DomainTools is data-only.** Adding Workday requires duplicating graph orchestration logic (the ReAct loop, result routing, state updates) rather than implementing a typed contract. The orchestrator and domain implementations are not cleanly separated.

---

## Goals

- **G1** — Enforce compact LLM context: tool results injected into prompts must be summaries, not raw API blobs.
- **G2** — Enable unambiguous multi-domain tool execution via namespaced identifiers and a canonical registry.
- **G3** — Define a DomainCapability contract so adding a new domain (Workday, ServiceNow, etc.) requires implementing one ABC, not touching the orchestrator.
- **G4** — Separate state into: transcript (messages), canonical artifacts (domain-keyed), facts (structured), debug (raw, never LLM context).
- **G5** — Keep the agent external for now. No embedded UX.
- **G6** — Patch IR shift is deferred. Patching remains LLM-driven in this milestone.

## Non-Goals

- Implementing Patch IR schema (Milestone 2).
- Building a deterministic compiler or guard rails (Milestone 2).
- Real Workday API integration (Milestone 3).
- Cross-domain planning (Milestone 3).
- Embedded agent UX in Flowise (Milestone 3+).
- Changing any FastAPI endpoint routes or Pydantic response models.
- Removing HITL interrupts.

---

## Target Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI (unchanged routes)                   │
│  POST /sessions  ·  POST /sessions/{id}/resume  ·  GET /health  │
└─────────────────────────────┬───────────────────────────────────┘
                               │
┌─────────────────────────────▼───────────────────────────────────┐
│                   LangGraph Orchestrator (graph.py)              │
│                                                                   │
│  clarify → discover → check_creds → plan → [HITL] →             │
│  patch → test → converge → [HITL] → END                         │
│                                                                   │
│  Nodes use DomainCapability.discover() for structured results    │
│  All phases use ToolRegistry (namespaced) for tool execution     │
│  _react() injects ToolResult.summary (not raw data)              │
└───────┬──────────────────────┬──────────────────────────────────┘
        │                      │
┌───────▼──────────┐  ┌────────▼────────────────────────────────┐
│  FlowiseCapability│  │  WorkdayCapability (stub → real later)  │
│  (wraps           │  │  discover-only, placeholder tools        │
│  FloviseDomain)   │  │  "workday.get_worker" (stub)             │
│                   │  └────────────────────────────────────────┘
│  ToolRegistry:    │
│  flowise.get_node │  [Milestone 3: real Workday MCP tools]
│  flowise.list_*   │
│  flowise.create_* │
│  ...              │
└───────────────────┘

AgentState (state.py):
  messages:   list[Message]          transcript (tool summaries, not raw)
  artifacts:  dict[domain → {ids}]   persistent refs (chatflow IDs, snapshot labels)
  facts:      dict[domain → {...}]   structured deltas per domain
  debug:      dict[domain → {iter: {tool: content}}]   raw — NOT LLM context
```

### Milestone Path

```
Now:   Flowise (external agent) → scaffolding + ToolResult + Registry + DomainCapability
Next:  Workday (discover-only stub) → real tools when MCP available
Later: Patch IR + deterministic compiler → predictable patch operations
Far:   Embedded UX + cross-domain planner
```

---

## Key Abstractions

### ToolResult Envelope

```python
@dataclass
class ToolResult:
    ok: bool
    summary: str        # COMPACT — injected into LLM context (msg.content)
    facts: dict         # structured deltas → state['facts'][domain]
    data: Any           # RAW output → state['debug'][domain] — NEVER LLM context
    error: dict | None  # {type, message, detail} when ok=False
    artifacts: dict | None  # {ids, hashes, refs} → state['artifacts'][domain]
```

**Invariant:** Only `summary` ever enters LLM context. `data` is never injected.

### ToolRegistry v2

```python
class ToolRegistry:
    def register(namespace, tool_def, phases, fn): ...
    def register_domain(domain: DomainTools): ...        # convenience
    def tool_defs(phase) -> list[ToolDef]: ...           # namespaced names to LLM
    def executor(phase) -> dict[str, Callable]: ...      # dual-keyed: "ns.name" AND "name"
    def context(phase) -> str: ...                       # merged domain system prompts
    async def call(tool_name, arguments) -> ToolResult: ...
```

**Invariant:** `executor()` returns both `"flowise.get_node"` and `"get_node"` as keys. The LLM uses the namespaced name; legacy code using bare names still works.

### DomainCapability ABC

```python
class DomainCapability(ABC):
    @property def name(self) -> str: ...           # "flowise" | "workday"
    @property def tools(self) -> ToolRegistry: ... # domain's registry
    @property def domain_tools(self) -> DomainTools: ... # wrapped DomainTools

    async def discover(self, context) -> DomainDiscoveryResult: ...
    async def compile_ops(self, plan) -> DomainPatchResult: ...   # STUB M1
    async def validate(self, artifacts) -> ValidationReport: ...  # STUB M1
    async def generate_tests(self, plan) -> TestSuite: ...
    async def evaluate(self, results) -> Verdict: ...
```

### Result Models

| Model | Fields | Used By |
|-------|--------|---------|
| `DomainDiscoveryResult` | summary, facts, artifacts, debug, tool_results | discover node → state |
| `DomainPatchResult` | stub=True *(M1 only)* | compile_ops stub |
| `ValidationReport` | stub=True *(M1 only)* | validate stub |
| `TestSuite` | happy_question, edge_question, domain_name | test node |
| `Verdict` | done, verdict, category, reason, fixes | converge node; .to_dict()/.from_dict() ↔ legacy |

### State Separation (AgentState additions)

```
messages   = transcript: user/assistant/tool_result(summary) — LLM context
artifacts  = domain-keyed persistent refs: {"flowise": {"chatflow_ids": [...]}}
facts      = domain-keyed structured deltas: {"flowise": {"chatflow_id": "abc", ...}}
debug      = domain-keyed raw: {"flowise": {0: {"list_chatflows": [...raw...]}}}
```

---

## Contracts / Data Models (Full Field Semantics)

### ToolResult.summary — Generation Rules

Priority order in `_wrap_result(tool_name, raw)`:

1. `raw` is `dict` with `"error"` key → `ok=False`, `summary=f"{tool_name} failed: {msg}"`
2. `raw` is `dict` with `"valid"` key (validate_flow_data) → structured pass/fail summary
3. `raw` is `dict` with `"id"` key (chatflow) → `"Chatflow '{name}' (id={id})."` + artifact
4. `raw` is `dict` with `"snapshotted"` key → `"Snapshot saved as {label} (total: N)."`
5. `raw` is `list` → `"{tool_name} returned {N} item(s)."`
6. `raw` is other `dict` → first 200 chars of JSON
7. `raw` is scalar/string → first 300 chars

### Verdict ↔ Legacy converge_verdict

```python
# Verdict is the typed form; converge_verdict is the existing untyped dict
verdict.to_dict()  →  {"verdict": "DONE", "category": None, "reason": "...", "fixes": [...]}
Verdict.from_dict(d)  →  Verdict(done=d["verdict"]=="DONE", ...)
```

The `converge_verdict` state field continues to receive `.to_dict()` output for full backwards compatibility with existing plan node logic.

---

## Invariants

1. **Compact context**: Only `ToolResult.summary` enters `msg.content`. Never `ToolResult.data`.
2. **Namespace isolation**: Tool names in the registry are `"namespace.tool_name"`. No two domains can claim the same namespace.
3. **Phase gating**: `registry.tool_defs("patch")` never returns discover-only tools. Phase permissions are set at registration time.
4. **Dual-key executor**: `executor(phase)` always includes both the namespaced key and the simple key. Old code using bare names never breaks.
5. **State separation**: `artifacts`, `facts`, `debug` use `_merge_domain_dict` — domain keys are merged, never globally overwritten.
6. **Capability opt-in**: `build_graph(capabilities=None)` → all behavior is identical to pre-refactor. The capability path is additive.
7. **No Patch IR**: `compile_ops()` and `validate()` return stubs in Milestone 1. They exist in the interface to make it clear they will be implemented in Milestone 2.
8. **HITL unchanged**: All four interrupt points (clarify, credential_check, plan_approval, result_review) are untouched.

---

## Phased Implementation Plan

### Milestone 1 — Scaffolding (This Prompt) ✅ IN PROGRESS

**Scope:**
- `ToolResult` envelope in `tools.py`
- `_wrap_result()` function (single transformation point)
- `execute_tool()` returns `ToolResult` (not `Any`)
- `result_to_str(ToolResult)` returns `.summary` (compact context enforcement)
- `ToolRegistry` class in new `registry.py`
- `DomainCapability` ABC + result models in new `domain.py`
- `FlowiseCapability` concrete impl in `graph.py`
- `WorkdayCapability` stub in new `agent/domains/workday.py`
- `AgentState` gains `artifacts`, `facts`, `debug` fields
- `_make_discover_node()` updated with optional `capabilities` path
- `build_graph()` gains `capabilities` parameter

**Checkpoints:**
- [ ] `python -c "from flowise_dev_agent.agent import ToolResult, ToolRegistry, DomainCapability"` — no ImportError
- [ ] `from flowise_dev_agent.agent.domains.workday import WorkdayCapability` — no ImportError
- [ ] `_wrap_result("test", {"id": "abc", "name": "Bot"})` → `ToolResult(ok=True, summary="Chatflow 'Bot' (id=abc).", artifacts={"chatflow_ids": ["abc"]})`
- [ ] `ToolRegistry.executor("discover")` includes both `"flowise.get_node"` and `"get_node"` keys
- [ ] Existing session flow unchanged when `capabilities=None` (default)

**Out of scope:** Patch IR, compiler, real Workday API, route changes.

---

### Milestone 2 — Patch IR + Compiler (Next Prompt)

**Scope:**
- `PatchIR` schema: typed representation of a chatflow delta (node add/remove/update, edge add/remove)
- `DomainCapability.compile_ops(plan: str) -> DomainPatchResult` — replaces stubs
- `DomainPatchResult` carries a list of `PatchIR` operations
- `FlowiseCapability.compile_ops()` — LLM produces PatchIR from plan (structured output)
- Guard rails: validate PatchIR before applying (no invalid edges, no orphaned nodes)
- `patch` node updated to execute `compile_ops()` then apply validated PatchIR
- `DomainCapability.validate()` — replaces stubs with real structural checks

**Checkpoints:**
- `compile_ops()` returns typed PatchIR for a simple single-node addition
- Applying invalid PatchIR raises `PatchValidationError` (never reaches Flowise)
- LLM-driven patch fallback still available as escape hatch

---

### Milestone 3 — Real Workday + Cross-Domain (Future)

**Scope:**
- Replace `WorkdayCapability` stub with real Workday MCP tool integration
- Complete `workday_extend.md` activation checklist
- Cross-domain planner: `plan` node can target multiple domains simultaneously
- Embedded UX path: agent running inside Flowise as an AgentFlow node
- `PatternDomain` → `PatternCapability` migration

---

## Acceptance Criteria (Milestone 1)

| # | Criterion | Test |
|---|-----------|------|
| AC-1 | `ToolResult` is importable from `flowise_dev_agent.agent` | Import test |
| AC-2 | `ToolRegistry` namespaces tools; dual-key executor | Unit assertion |
| AC-3 | `DomainCapability` is an ABC that cannot be instantiated directly | `pytest.raises(TypeError)` |
| AC-4 | `FlowiseCapability.discover()` returns `DomainDiscoveryResult` | Async test |
| AC-5 | `WorkdayCapability.discover()` returns stub result without API calls | Async test |
| AC-6 | `result_to_str(ToolResult)` returns `.summary` not raw JSON | Unit assertion |
| AC-7 | `AgentState` has `artifacts`, `facts`, `debug` with merge semantics | State test |
| AC-8 | Existing sessions (no capabilities) behave identically | Regression test |
| AC-9 | `_extract_chatflow_id` handles both JSON (legacy) and summary (ToolResult) | Unit test |

---

## In-Scope vs Deferred (Quick Reference)

| Item | Milestone 1 | Milestone 2 | Milestone 3 |
|------|:-----------:|:-----------:|:-----------:|
| ToolResult envelope | ✅ | | |
| ToolRegistry v2 (namespaced) | ✅ | | |
| DomainCapability ABC | ✅ | | |
| FlowiseCapability (discover) | ✅ | | |
| WorkdayCapability (stub) | ✅ | | |
| State: artifacts/facts/debug | ✅ | | |
| Compact context enforcement | ✅ | | |
| Patch IR schema | | ✅ | |
| Deterministic compiler | | ✅ | |
| Compiler guard rails | | ✅ | |
| DomainCapability.validate() | | ✅ | |
| DomainCapability.compile_ops() | | ✅ | |
| Real Workday MCP | | | ✅ |
| Cross-domain planner | | | ✅ |
| Embedded UX | | | ✅ |

---

## How to Add a New Domain (Post-Milestone 1)

See [How to Add a New Domain](#how-to-add-a-new-domain) in the implementation output.

Quick reference:
1. Create `agent/domains/yourname.py`
2. Define `YourNameDomainTools(DomainTools)` — tool defs + executor
3. Define `YourNameCapability(DomainCapability)` — implement all abstract methods
4. Register your ToolRegistry in `__init__` using `registry.register_domain(self._domain_tools)`
5. Pass capability to `build_graph(capabilities=[..., YourNameCapability()])`
6. No changes to graph.py, api.py, or any existing code required

---

## Design Decisions Added in This Milestone

- **DD-046** — `DomainCapability` as primary abstraction boundary (wraps DomainTools, adds behavioral contract)
- **DD-047** — `WorkdayCapability` stub-first approach (interface complete before API is connected)
- **DD-048** — `ToolResult` as single transformation point (`_wrap_result()` in tools.py, enforced via `result_to_str()`)
- **DD-049** — Dual-key executor (namespaced + simple) for zero-regression backwards compatibility
- **DD-050** — State trifurcation: transcript / canonical artifacts / debug
