# Flowise Dev Agent Skills

Skills are markdown files that define domain-specific knowledge for the Flowise Builder co-pilot.
Each domain the agent works with has its own skill file. The agent loads skill files at startup
and injects the relevant sections into system prompts for each phase of the development loop.

---

## How Skills Work

Each skill file is parsed into named `## Sections`. The agent uses three sections per domain:

| Section | Injected into | Purpose |
|---|---|---|
| `## Discover Context` | Discover phase system prompt | What to look for, what to read, domain-specific rules |
| `## Patch Context` | Patch phase system prompt | Non-negotiable rules for making changes in this domain |
| `## Test Context` | Test phase system prompt | How to validate changes in this domain |

Additional sections (`## Overview`, `## Error Reference`, etc.) are documentation only —
not injected into prompts, but useful for developers maintaining the skill.

---

## File Format

```markdown
# [Domain] Builder Skill

**Domain**: <name>
**Version**: <semver>

## Overview
Brief description of what this skill covers.

## Discover Context
[Injected into Discover system prompt — what to gather, what to read]

## Patch Context
[Injected into Patch system prompt — non-negotiable rules for making changes]

## Test Context
[Injected into Test system prompt — how to validate]

## Error Reference
[Common errors and how to fix them — documentation only, not injected]
```

---

## Current Skills

| File | Domain | Status |
|---|---|---|
| `flowise_builder.md` | Flowise chatflow development | Active — loaded by `FloviseDomain` |
| `workday_extend.md`  | Workday Build (Extend + Orchestrate) | Placeholder — ready for v2 |

---

## Adding a New Skill (v2 and beyond)

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
   graph = build_graph(engine, domains=[FloviseDomain(flowise_client), WorkdayDomain(workday_client)])
   ```

No changes to the graph or node logic are needed. The agent merges tools and context from all
registered domains automatically.

---

## Relationship to the Orchestrator Guide

The `FLOWISE_BUILDER_ORCHESTRATOR_CHATFLOW_MCP.md` guide in the `cursorwise` repo is the
**Cursor IDE behavioral guide** — a comprehensive reference for a human developer using the
Cursorwise MCP directly in Cursor.

The `flowise_builder.md` skill file in this directory is the **agent's knowledge base** —
a structured, machine-injectable version of the same domain knowledge, organized by phase.

Both documents cover the same domain. The skills file is leaner and phase-structured.
The Cursor guide is comprehensive and human-focused. They are maintained independently.
