# Flowise Dev Agent Skills

Skills are markdown files that provide domain-specific knowledge for the Flowise Builder co-pilot.
Each domain has its own skill file. The agent loads skill files at startup and injects the relevant
sections into system prompts for each phase of the development loop.

---

## How Skills Work

Each skill file is parsed into named `## sections`. The agent uses three injection-point sections:

| Section | Injected into | Purpose |
|---|---|---|
| `## Discover Context` | `plan_v2` node system prompt | Intent classification, schema lookup, credential resolution, PlanContract output |
| `## Patch Context` | `compile_patch_ir` node system prompt | Patch IR op emission (AddNode/SetParam/Connect/BindCredential) |
| `## Test Context` | `evaluate` node system prompt | Evaluation criteria; DONE vs ITERATE verdict rules |

Additional sections (`## Overview`, `## Error Reference`, `## Changelog`, etc.) are documentation
only — not injected into prompts.

> **Note on YAML frontmatter**: The parser (`skills.py`) starts reading at the first `## ` heading.
> YAML frontmatter (`---` block) before the first heading is silently ignored. Adding frontmatter
> to skill files is safe and encouraged for documentation purposes.

---

## File Format

```markdown
---
name: domain-name
description: |
  One paragraph. Lead with what it does. Include trigger phrases. Be slightly pushy.
version: 2.0.0
---

# Domain Builder Skill

## Overview
Brief description (documentation only — not injected).

## Discover Context
[Injected into plan_v2 system prompt — intent classification, schema lookup, PlanContract format]

## Patch Context
[Injected into compile_patch_ir system prompt — Patch IR ops to emit, ordering constraints]

## Test Context
[Injected into evaluate system prompt — DONE vs ITERATE evaluation criteria]

## Error Reference
[Common errors and fixes — documentation only, not injected]

## Changelog
[Version history — documentation only]
```

---

## Current Skills

| File | Domain | Version | Status |
|---|---|---|---|
| `flowise_builder.md` | Flowise chatflow development | 2.0.0 | Active — loaded by `FloviseDomain` |
| `workday_extend.md` | Workday-connected chatflow development | 0.2.0 | Partial — customMCP wiring pattern active; full Workday ops TBD |

---

## How the Patch Phase Works (v2 graph)

The LLM no longer writes raw `flowData` JSON. The v2 graph uses a deterministic compiler:

```
plan_v2 node        → LLM emits PlanContract (intent, nodes, credentials, success_criteria)
compile_patch_ir    → LLM emits Patch IR ops (AddNode / SetParam / Connect / BindCredential)
compiler            → deterministically builds flowData from the ops
create/update call  → sends compiled flowData to Flowise REST API
```

Skill Patch Context sections must reflect this: the LLM emits ops, not JSON.

---

## Adding a New Skill

1. Create `flowise_dev_agent/skills/<domain_name>.md` following the format above.
2. Implement a `DomainTools` subclass in `flowise_dev_agent/agent/tools.py`:
   ```python
   class WorkdayDomain(DomainTools):
       def __init__(self, workday_client) -> None:
           from flowise_dev_agent.agent.skills import load_skill
           skill = load_skill("workday_extend")
           super().__init__(
               name="workday",
               discover=[...],
               patch=[...],
               test=[...],
               executor={...},
               discover_context=skill.discover_context if skill else "",
               patch_context=skill.patch_context if skill else "",
               test_context=skill.test_context if skill else "",
           )
   ```
3. Register the domain when building the graph:
   ```python
   graph = build_graph(capabilities=[FloviseDomain(flowise_client), WorkdayCapability(workday_client)])
   ```

No changes to the graph or node logic are needed — the agent merges tools and context from all
registered domains automatically.

---

## Relationship to the Orchestrator Guide

The `Flowise_MCP_Builder_Guide.md` in the repo root is the **Cursor IDE behavioral
guide** — comprehensive reference for a human developer using the Flowise MCP
tools directly in Cursor or Claude Desktop.

The `flowise_builder.md` skill file is the **agent's knowledge base** — structured,
machine-injectable domain knowledge organized by phase.

Both cover the same Flowise domain. The skill file is leaner and phase-structured.
The Cursor guide is comprehensive and human-focused. They are maintained independently.
