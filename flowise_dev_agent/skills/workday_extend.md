# Workday Integration Skill

**Domain**: workday
**Version**: 0.1.0 (placeholder — not yet active)
**Status**: SKELETON — fill in when Workday MCP tools are configured in Flowise

---

## Overview

This skill teaches the Flowise Builder co-pilot how to work with Workday-connected
chatflows — specifically, Flowise flows that use Workday MCP tools to read and write
Workday data.

### Integration architecture (how this actually works)

The Flowise Dev Agent is a **Flowise development co-pilot**. It stays external (3P) and builds
chatflows inside Flowise. Workday connectivity happens *inside those chatflows* — not
inside the co-pilot itself.

```
Flowise Dev Agent
  → builds Flowise chatflows
     → those chatflows call Workday APIs via MCP tools configured in Flowise
        → Workday data flows through the chatflow at runtime
```

The co-pilot's job when Workday is involved:
1. Know how to discover and use the Workday MCP tools already configured in Flowise
2. Know the rules for building chatflows that call Workday APIs correctly
3. Know how to test those chatflows against sandbox data

This skill file is the place to record that knowledge as it is developed.

### Workday Build platform (for context)
- **Flowise** (recently acquired by Workday) — AI agent and chatflow development
- **Workday Extend** — Custom UX and business logic applications
- **Workday Orchestrate** — Graphical integration development
- **Workday Pipeline** — Data pipeline development

### Agent classification
- **1P**: Built by Workday product team (native Workday AI agents)
- **2P**: Built natively on Workday platform (Extend, Orchestrate)
- **3P**: Built externally — this agent is currently 3P

---

## Discover Context

> **STATUS**: TBD — fill in when Workday MCP tools are configured in Flowise.

WORKDAY-CONNECTED CHATFLOW DISCOVERY RULES:

<!-- TODO: Fill in when you have Workday MCP tools available in Flowise. -->

What to gather when the requirement involves Workday data:
1. Call `list_nodes` and identify which Workday MCP tool nodes are available
2. For each relevant Workday tool node, call `get_node` to check its exact input schema
3. Identify what Workday objects are involved (Workers, Absences, Business Processes, etc.)
4. Verify Workday credentials exist in Flowise (`list_credentials` — look for OAuth 2.0 type)
5. Check if a marketplace template already exists for this Workday integration pattern

Key Workday data concepts to be aware of:
- **WIDs** (Workday IDs) — primary keys for all Workday objects; capture and reuse them
- **Tenant** — every Workday API call is scoped to a tenant; confirm the target tenant
- **API versioning** — Workday APIs are versioned (e.g., v3); pin the version in every call

---

## Patch Context

> **STATUS**: TBD — fill in when Workday MCP tools are configured in Flowise.

WORKDAY-CONNECTED CHATFLOW PATCH RULES:

<!-- TODO: Add non-negotiable rules for building chatflows that call Workday APIs. -->

Key areas to define:
- OAuth 2.0 credential binding for Workday API nodes (likely same dual-binding rule as OpenAI)
- WID handling patterns (how to pass WIDs between nodes)
- Workday API error response patterns and how to surface them to the user
- Sandbox vs production chatflow configuration

---

## Test Context

> **STATUS**: TBD — fill in when Workday MCP tools are configured in Flowise.

WORKDAY-CONNECTED CHATFLOW TEST RULES:

<!-- TODO: Add testing patterns once the first Workday-connected chatflow is built. -->

Key areas to define:
- Always test against Workday sandbox (not production) — confirm correct tenant in sessionId
- Workday API rate limits and retry behaviour in test scenarios
- PII/sensitive data handling in test inputs (use synthetic employee data)
- Expected response shapes for common Workday operations

---

## Error Reference

> **STATUS**: TBD — fill in with Workday-specific errors as they are encountered.

| Error | Root Cause | Fix |
|---|---|---|
| TBD | TBD | TBD |

---

## Workday API Patterns (reference)

For when you are building or debugging Workday-connected Flowise nodes:

1. **Authentication**: OAuth 2.0 with client credentials grant — credential must be bound at
   both `data.credential` AND `data.inputs.credential` (same rule as OpenAI)
2. **Object model**: All Workday objects have WIDs as primary keys — capture WIDs from
   initial lookups and pass them downstream rather than re-looking up by name
3. **API versioning**: Target a specific version in every call (e.g., `/absenceManagement/v3/`)
   — do not call versionless endpoints
4. **Workday REST vs WWS**: Prefer REST API over SOAP/WWS for new chatflow integrations

---

## v2 Activation Checklist

When the team is ready to build Workday-connected chatflows:

- [ ] Configure Workday MCP tools in Flowise (Workday Agent Gateway or direct REST)
- [ ] Verify Workday OAuth 2.0 credentials are saved in Flowise (`list_credentials`)
- [ ] Build a simple test chatflow that reads one Workday object (e.g., Worker profile)
- [ ] Fill in the Discover/Patch/Test context sections above based on what you learn
- [ ] Add Workday-specific errors to the Error Reference as they are encountered
- [ ] Update `flowise_dev_agent/skills/flowise_builder.md` if any Workday MCP node patterns
      need to be added to the main Flowise builder rules
