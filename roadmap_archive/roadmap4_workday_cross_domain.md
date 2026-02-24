# Roadmap 4: Workday Integration + Cross-Domain Planner

**Status:** Planning — implementation begins after M1/M2 backend + UI validation
**Created:** 2026-02-23
**Branch:** feat/strategic-architecture-optimization (or new branch per milestone)
**Predecessor:** roadmap3_architecture_optimization.md (M1 + M2 complete)

---

## Relationship to Roadmap 5 (Embedded UX)

Roadmap 5 (agent running as a Flowise AgentFlow node) has **no dependency on Roadmap 4**.
The DomainCapability ABC and ToolRegistry are already in place. Roadmap 5 can be planned
and executed independently, even while Roadmap 4 is blocked on Workday MCP availability.

```
R4 (Workday + cross-domain)  ─── independent ───  R5 (Embedded UX / Flowise node)
         │                                                    │
         ▼                                                    ▼
Requires Workday MCP tools                     Requires Flowise AgentFlow API +
to be configured in Flowise                    packaging as a custom node
```

---

## Problem Statement

Three remaining friction points after M1/M2:

1. **WorkdayCapability is a stub.** Some Workday MCP endpoints are partially accessible but
   `WorkdayDomainTools` holds only placeholder callables. `discover()` returns synthetic data.
   The agent cannot discover real Workday objects or suggest Workday-connected chatflow patterns.

2. **The planner is single-domain.** `_make_plan_node()` injects Flowise discovery context and
   produces a Flowise-only plan. When a requirement touches both Flowise chatflow construction
   and Workday data, the plan node has no structured way to emit domain-qualified intents or
   route the patch phase to the right domain.

3. **PatternDomain is not a DomainCapability.** Pattern matching is domain logic but is
   implemented as a legacy `DomainTools` data descriptor. It cannot participate in the
   capability path and cannot benefit from compile_ops/validate/generate_tests.

---

## Goals

- **G1** — Wire accessible Workday MCP endpoints into `WorkdayCapability` so `discover()`
  returns real data. Mark endpoints not yet accessible as `[STUB — not yet available]` with
  structured warnings (never silent fake data).
- **G2** — Cross-domain planner: `plan` node synthesizes across all registered domain contexts
  and emits domain-qualified plan sections. `patch` node routes to the correct domain's
  `compile_ops` via `active_domain` state.
- **G3** — `PatternCapability`: migrate `PatternDomain` → `DomainCapability` so the pattern
  library participates in the capability path.
- **G4** — Complete `workday_extend.md` Discover / Patch / Test rules from real experience
  with the first working Workday-connected chatflow.

## Non-Goals

- Workday Patch IR (`compile_ops` for Workday) — deferred until all required MCP endpoints
  are confirmed and stable.
- Cross-domain Patch IR (single op touching both Flowise and Workday simultaneously).
- Embedded UX / agent-as-Flowise-node (Roadmap 5 — no dependency on R4).
- New FastAPI route changes.
- Removing the `capabilities=None` legacy path.

---

## Current State (what exists)

| Component | Status |
|-----------|--------|
| `WorkdayCapability.discover()` | Stub — synthetic data, no real API calls |
| `WorkdayDomainTools` tools | `get_worker`, `list_business_processes` — both stubs |
| `workday_extend.md` | Skeleton — Discover/Patch/Test all marked TBD |
| Plan node (`_make_plan_node`) | Single-domain — only injects `domain_context["flowise"]` |
| Patch node routing | Only routes to `FlowiseCapability` — no Workday path |
| `PatternDomain` | Legacy `DomainTools` descriptor — not a `DomainCapability` |

---

## Target Architecture Delta

What changes from the current (post-M2) state:

```
Current:
  discover → [FlowiseCapability.discover(), WorkdayCapability.discover() (stub)]
  plan     → single Flowise plan
  patch    → FlowiseCapability.compile_ops() only
  test     → Flowise tests only
  converge → Flowise verdict only

After R4:
  discover → [FlowiseCapability.discover(), WorkdayCapability.discover() (real)]
              [PatternCapability.discover() → artifacts["patterns"]]
  plan     → multi-domain plan:
               ## Flowise Plan: ...
               ## Workday Plan: ...  ← new (only if Workday in requirement)
  patch    → routes by active_domain:
               FlowiseCapability.compile_ops() or WorkdayCapability.compile_ops()
  test     → per-domain TestSuites, run in parallel
  converge → per-domain verdicts, combined into overall DONE/ITERATE
```

---

## Phased Implementation Plan

### Milestone 4.1 — Workday MCP Wiring ⬜ PENDING

**Prerequisite:** Inventory which Workday MCP endpoints are currently accessible in Flowise.
**Blocked on:** Partial Workday MCP endpoint access confirmed — needs inventory.

**Scope:**
- Replace stub callables in `WorkdayDomainTools` with real async functions for available endpoints
- Each tool tagged `[LIVE]` or `[STUB — not yet available]` in its description string
- `[STUB]` tools return `{"status": "stub", "warning": "endpoint not yet available", ...}` —
  never fake data that could mislead the planner
- `WorkdayCapability.__init__` gains `engine` parameter (passed from `build_graph`)
- `WorkdayCapability.discover()` body replaced with a real `_react()` loop call:
  ```python
  summary, new_msgs, in_tok, out_tok = await _react(
      self._engine, [user_msg], system, tool_defs, executor, max_rounds=20
  )
  return DomainDiscoveryResult(summary=summary, facts=facts, debug=debug, ...)
  ```
- Fill in `workday_extend.md` Discover Context based on real tool schemas and first test run
- `build_graph()` / `create_agent()` updated to pass `engine` to `WorkdayCapability`

**Files to modify:**
| File | Change |
|------|--------|
| `flowise_dev_agent/agent/domains/workday.py` | Real tool callables + engine param + real discover() |
| `flowise_dev_agent/skills/workday_extend.md` | Fill Discover Context from real schemas |
| `flowise_dev_agent/agent/graph.py` | Pass engine to WorkdayCapability in build_graph/create_agent |

**Checkpoints:**
- `WorkdayCapability(engine).discover({})` returns `DomainDiscoveryResult` with real (non-stub) summary
- `[STUB]` tools return structured warning dict — verified in unit test
- All 28 existing tests pass

**Out of scope:** `compile_ops`, `validate`, Patch IR for Workday.

---

### Milestone 4.2 — Cross-Domain Planner ⬜ PENDING

**Prerequisite:** M4.1 complete (at least one real Workday discover result to test with).

**Scope:**
- `_make_plan_node()` system prompt updated: instructs LLM to acknowledge all domains in
  `state["domain_context"]` and emit domain-qualified sections only for active domains
- Plan output format (when multiple domains discovered):
  ```
  ## Flowise Plan
  ...Flowise chatflow construction steps...

  ## Workday Plan
  ...Workday data operations...
  ```
- `AgentState` gains `active_domain: str | None` field — set by plan node, read by patch node
- `_make_patch_node_v2()` updated:
  - Reads `state["active_domain"]`
  - Selects matching `DomainCapability` from capabilities list by name
  - Falls back to FlowiseCapability if `active_domain` is None or not matched
- `_make_converge_node()` updated:
  - Collects per-domain test suites if multiple domains active
  - Emits combined `converge_verdict` (DONE only if all active domains pass)
- `_initial_state()` in `api.py` gains `"active_domain": None` default

**Files to modify:**
| File | Change |
|------|--------|
| `flowise_dev_agent/agent/graph.py` | Plan node prompt, patch routing, converge multi-domain |
| `flowise_dev_agent/agent/state.py` | `active_domain: str | None` field |
| `flowise_dev_agent/api.py` | `_initial_state()` default |

**Invariant:** `capabilities=None` path is completely untouched.

**Checkpoints:**
- Flowise-only requirement → plan has only `## Flowise Plan` — no Workday section
- Flowise + Workday requirement → plan has both sections; `active_domain` set in state
- Patch phase routes to the domain matching `active_domain`
- All 28 existing tests pass

---

### Milestone 4.3 — PatternCapability ⬜ PENDING

**Prerequisite:** None — can be implemented independently of M4.1/M4.2.

**Scope:**
- Create `flowise_dev_agent/agent/domains/flowise_patterns.py`
- `PatternCapability(DomainCapability)`:
  - `name` = `"patterns"`
  - `discover(context)`: calls `self._pattern_store.search(requirement)`, wraps each
    matched pattern as a compact summary; raw flowData goes to `debug["patterns"]`;
    returns `DomainDiscoveryResult(artifacts={"patterns": [...]}, ...)`
  - `compile_ops()`, `validate()`: stubs — PatternDomain can't author new patterns via IR
  - `generate_tests()`: extracts test questions from matched pattern metadata
  - `evaluate()`: delegates to FlowiseCapability.evaluate() (same chatflow verdict logic)
- `PatternDomain` in `tools.py` is **not removed** — legacy path (`capabilities=None`)
  continues using it unchanged
- `build_graph()` auto-injects `PatternCapability` when BOTH `pattern_store` AND
  `capabilities` are provided (mirrors current `PatternDomain` auto-injection logic)

**Files to create / modify:**
| File | Change |
|------|--------|
| `flowise_dev_agent/agent/domains/flowise_patterns.py` | New — PatternCapability |
| `flowise_dev_agent/agent/graph.py` | Auto-inject PatternCapability in build_graph |
| `flowise_dev_agent/agent/__init__.py` | Export PatternCapability |

**Checkpoints:**
- `PatternCapability(pattern_store).discover({"requirement": "..."})` returns matched patterns
  in `artifacts["patterns"]`
- Legacy path (`capabilities=None`) still uses `PatternDomain` — no regression
- Pattern artifacts appear as compact summaries in SSE `tool_result` events (not raw flowData)

---

## Design Decisions to Add

| DD | Title |
|----|-------|
| DD-053 | WorkdayCapability LIVE/STUB tool marking — `[LIVE]` / `[STUB — not yet available]` in tool description strings; stubs return structured warning dicts, never synthetic data |
| DD-054 | Cross-domain plan sections + `active_domain` state routing — LLM emits `## {Domain} Plan` markers; patch node reads `active_domain` set by plan node, never guesses |
| DD-055 | PatternCapability — pattern library as first-class DomainCapability; `PatternDomain` preserved for legacy path; auto-injected in capability path when `pattern_store` present |

---

## Invariants (additions to roadmap3 list)

9.  **Workday partial availability**: `[STUB — not yet available]` tools return a structured
    dict with `status: "stub"` and `warning` message. They never return fake worker data or
    empty success responses that could mislead the planner.
10. **Domain routing via state**: `active_domain` in `AgentState` is set only by the plan node.
    The patch node reads it and selects the matching capability. It never guesses based on
    requirement text.
11. **PatternDomain preserved**: `PatternDomain` in `tools.py` is not removed or modified.
    `PatternCapability` adds a capability-path wrapper on top. Both coexist.

---

## Acceptance Criteria

| # | Criterion | Milestone |
|---|-----------|-----------|
| AC-1 | `WorkdayCapability(engine).discover({})` returns real (non-stub) discovery summary | M4.1 |
| AC-2 | `[STUB]` tools return structured warning dict, not synthetic success data | M4.1 |
| AC-3 | Session with Workday requirement produces a plan with `## Workday Plan` section | M4.2 |
| AC-4 | Patch node routes to correct capability when `active_domain` is set | M4.2 |
| AC-5 | Flowise-only session (no Workday mention) is fully unaffected by M4.2 changes | M4.2 |
| AC-6 | `PatternCapability.discover()` returns matched patterns in `artifacts["patterns"]` | M4.3 |
| AC-7 | Legacy path (`capabilities=None`) still uses `PatternDomain` — no regression | M4.3 |
| AC-8 | All 28 existing tests in `tests/test_patch_ir.py` pass after each milestone | All |

---

## In-Scope vs Deferred (Quick Reference)

| Item | M4.1 | M4.2 | M4.3 | Roadmap 5 |
|------|:----:|:----:|:----:|:---------:|
| WorkdayCapability real discover | ✅ | | | |
| `[LIVE]`/`[STUB]` tool marking | ✅ | | | |
| `workday_extend.md` Discover rules | ✅ | | | |
| Cross-domain plan node | | ✅ | | |
| `active_domain` patch routing | | ✅ | | |
| Per-domain converge verdicts | | ✅ | | |
| `workday_extend.md` Patch/Test rules | | ✅ | | |
| PatternCapability | | | ✅ | |
| Workday Patch IR / `compile_ops` | | | | TBD |
| Cross-domain Patch IR | | | | — |
| Embedded UX (AgentFlow node) | | | | ✅ |

---

## Related

- [roadmap3_architecture_optimization.md](roadmap3_architecture_optimization.md) — M1 + M2 complete
- [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) — DD-046 through DD-055
- [flowise_dev_agent/agent/domains/workday.py](flowise_dev_agent/agent/domains/workday.py) — activation checklist
- [flowise_dev_agent/skills/workday_extend.md](flowise_dev_agent/skills/workday_extend.md) — domain skill file
