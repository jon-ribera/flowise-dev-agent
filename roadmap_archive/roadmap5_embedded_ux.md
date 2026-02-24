# Roadmap 5: Embedded UX — Agent as a Flowise Node

**Status:** Planning
**Created:** 2026-02-23
**Branch:** TBD (independent of feat/strategic-architecture-optimization)
**Predecessor:** None — Roadmap 5 is independent of Roadmap 4. The DomainCapability ABC and
ToolRegistry shipped in M1/M2 are sufficient. R5 can begin before R4 is complete.

---

## Context

The Flowise Dev Agent is currently a standalone external (3P) service. Developers interact
with it via a separate web UI (`GET /ui`) or REST API. The goal of Roadmap 5 is to make the
agent accessible as a first-class node inside Flowise itself — so that a visual chatflow
builder can invoke the dev agent as part of a larger workflow.

### Integration architecture recap

```
Current (external):
  Developer → FloWise Dev Agent REST API → Flowise REST API
  (separate process, separate UI, separate session)

After R5 (embedded):
  Flowise Flow Canvas
    └── [FlowiseDevAgent Node] → calls agent API → Flowise REST API
         ├── Input: requirement (string)
         ├── Config: agent_endpoint, api_key, auto_approve
         └── Output: chatflow_id, chatflow_name, session_summary
```

### Three integration levels (progressive delivery)

| Level | Mechanism | Code changes | Effort |
|-------|-----------|--------------|--------|
| L1 | Flowise Custom Tool (JS inline) | New endpoint in Python agent | Low |
| L2 | Flowise Custom Node (TypeScript INode) | New `flowise_node/` package in this repo | Medium |
| L3 | Agent-as-Tool (deploy as AgentFlow) | L1 + deployment documentation | Low |

---

## Problem Statement

1. **No sync/blocking endpoint.** The current agent exposes only streaming (`/sessions/stream`)
   and polling (`/sessions`, `/sessions/{id}`) endpoints. Flowise Custom Tools need a callable
   that returns a result synchronously — a long-poll or blocking `/sessions/complete` endpoint
   is missing.

2. **HITL incompatibility in embedded context.** When embedded in a Flowise flow, HITL
   interrupts (plan approval, result review) cannot surface to the user via the current web UI.
   An embedded invocation needs either: auto-approval options, or a mechanism to surface
   interrupts as flow state that parent nodes can handle.

3. **No native Flowise node exists.** The agent has no TypeScript INode implementation and
   does not appear in the Flowise node palette.

---

## Goals

- **G1** — Add an embedded-compatible endpoint (`/sessions/complete`) that blocks until
  session completes or interrupts, suitable for Flowise Custom Tool JS functions.
- **G2** — Support configurable auto-approve mode: allow embedded callers to skip HITL
  interrupts (auto-approve plan, auto-accept result) via a session parameter.
- **G3** — Create a `flowise_node/` TypeScript package (INode implementation) that can be
  dropped into Flowise's `packages/components/nodes/` and appear in the node palette.
- **G4** — Provide a Custom Tool JS template and Agent-as-Tool deployment guide.

## Non-Goals

- Running the Python dev agent inside Flowise's process (it stays an external HTTP service).
- Modifying the Flowise repository itself (the TypeScript node is distributed separately).
- Streaming from inside the TypeScript node to the parent flow (out of scope for M5).
- Multi-domain cross-chatflow planning (Roadmap 4 concern).

---

## Phased Implementation Plan

### Milestone 5.1 — Embedded-Compatible API Layer ⬜ PENDING

**Scope (Python agent changes only):**

**New endpoint: `POST /sessions/complete`**
- Starts a new session and blocks until completion or interrupt
- Accepts same body as `POST /sessions` plus:
  - `auto_approve: bool = False` — if true, automatically responds "approved" to every
    `plan_approval` and `result_review` interrupt without human input
  - `max_wait_secs: int = 300` — long-poll timeout (HTTP 408 if exceeded)
- Returns on first stop: completed session OR pending interrupt payload
- Response schema (same as `POST /sessions` but with `auto_approve` honored):
  ```json
  {
    "thread_id": "uuid-...",
    "status": "completed" | "pending_interrupt" | "timeout",
    "chatflow_id": "uuid-... | null",
    "chatflow_name": "name | null",
    "summary": "markdown audit trail string",
    "interrupt": { ... } | null
  }
  ```

**`auto_approve` mode detail:**
- When `auto_approve=true`, the session runner catches each interrupt and immediately resumes
  with `"approved"` without waiting for human input
- Suitable for: CI pipelines, embedded flow invocations, automated testing
- HITL interrupt events are still recorded in the session audit trail (just auto-resolved)
- `auto_approve` is per-session — it does not affect other running sessions

**Files to modify:**
| File | Change |
|------|--------|
| `flowise_dev_agent/api.py` | Add `POST /sessions/complete` endpoint + `auto_approve` param |
| `flowise_dev_agent/agent/graph.py` | Auto-approve runner mode (optional interrupt bypass) |
| `README.md` | Document new endpoint |

**Checkpoints:**
- `POST /sessions/complete` with `auto_approve=true` runs full session without HITL pauses
- `POST /sessions/complete` with `auto_approve=false` returns `pending_interrupt` at first HITL
- Existing `POST /sessions` and `POST /sessions/stream` unaffected

---

### Milestone 5.2 — Custom Tool Template ⬜ PENDING

**Scope (no Python changes — artifact + documentation):**

Create `flowise_node/custom_tool_template.js` — a paste-ready Flowise Custom Tool function:

```javascript
// FlowiseDevAgent Custom Tool
// Paste into Flowise → Add Tool → Custom Tool → Function
// Required env vars: FLOWISE_DEV_AGENT_URL, FLOWISE_DEV_AGENT_KEY (optional)

const response = await fetch(`${process.env.FLOWISE_DEV_AGENT_URL}/sessions/complete`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    ...(process.env.FLOWISE_DEV_AGENT_KEY
      ? { Authorization: `Bearer ${process.env.FLOWISE_DEV_AGENT_KEY}` }
      : {}),
  },
  body: JSON.stringify({
    requirement: $requirement,
    auto_approve: true,
    max_wait_secs: 300,
  }),
});

const result = await response.json();
if (result.status === "completed" && result.chatflow_id) {
  return `Created chatflow "${result.chatflow_name}" (id: ${result.chatflow_id})`;
}
return result.summary || JSON.stringify(result);
```

**Input schema for the Custom Tool:**
```json
{
  "type": "object",
  "properties": {
    "requirement": {
      "type": "string",
      "description": "Natural language description of the chatflow to build"
    }
  },
  "required": ["requirement"]
}
```

**Files to create:**
- `flowise_node/custom_tool_template.js` — paste-ready tool function
- `flowise_node/README.md` — integration guide (Custom Tool + Agent-as-Tool + Custom Node)

---

### Milestone 5.3 — TypeScript Custom Node ⬜ PENDING

**Scope: Create `flowise_node/` TypeScript package.**

This package implements Flowise's `INode` interface and can be placed at:
`{flowise}/packages/components/nodes/agents/FlowiseDevAgent/`

**Node configuration (inputs):**
| Parameter | Type | Description |
|-----------|------|-------------|
| `requirement` | string (input anchor) | Chatflow requirement from upstream node |
| `agentEndpoint` | string (credential) | URL of the dev agent (`http://localhost:8000`) |
| `agentApiKey` | password (credential) | Bearer token (optional) |
| `autoApprove` | boolean | Skip HITL interrupts (default: true for embedded) |
| `maxWaitSecs` | number | Timeout in seconds (default: 300) |

**Node outputs:**
| Output | Type | Description |
|--------|------|-------------|
| `chatflowId` | string | Created/updated chatflow UUID |
| `chatflowName` | string | Chatflow display name |
| `summary` | string | Markdown audit trail |

**File structure:**
```
flowise_node/
├── package.json
├── tsconfig.json
├── src/
│   └── FlowiseDevAgent.ts      # INode implementation
├── custom_tool_template.js     # L1 template (M5.2)
└── README.md                   # Integration guide
```

**INode implementation sketch:**
```typescript
import { INode, INodeData, INodeParams } from "flowise-components";
import fetch from "node-fetch";

class FlowiseDevAgentNode implements INode {
  label = "Flowise Dev Agent";
  name = "flowiseDevAgent";
  version = 1.0;
  type = "FlowiseDevAgent";
  category = "Agents";
  baseClasses = ["FlowiseDevAgent"];
  description = "Build a Flowise chatflow from a natural language requirement.";
  inputs: INodeParams[] = [ /* ... */ ];

  async init(nodeData: INodeData): Promise<string> {
    const endpoint = nodeData.inputs?.agentEndpoint as string;
    const requirement = nodeData.inputs?.requirement as string;
    const autoApprove = (nodeData.inputs?.autoApprove as boolean) ?? true;

    const response = await fetch(`${endpoint}/sessions/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requirement, auto_approve: autoApprove }),
    });
    const result = await response.json();
    return result.chatflow_id ?? result.summary;
  }
}

module.exports = { nodeClass: FlowiseDevAgentNode };
```

**Checkpoints:**
- Node compiles with `tsc` without errors
- Node appears in Flowise node palette when dropped into `packages/components/nodes/`
- Node successfully calls local dev agent and returns `chatflow_id`
- Node displayed name, category, and description match Flowise UI conventions

---

## Design Decisions to Add

| DD | Title |
|----|-------|
| DD-056 | `/sessions/complete` endpoint — blocking long-poll for embedded callers; `auto_approve` per-session HITL bypass |
| DD-057 | `auto_approve` mode — interrupt events recorded in audit trail but not paused on; enables CI and embedded flow use |
| DD-058 | TypeScript Custom Node in `flowise_node/` — distributed as a separate package, not merged into Flowise repository |

---

## Invariants

1. **`auto_approve` is per-session, not global.** It never affects other sessions or the default behavior of the web UI or REST API.
2. **HITL audit trail preserved.** Even when `auto_approve=true`, every interrupt event is recorded in the session summary with a note `[auto-approved]`.
3. **External process model.** The Python dev agent stays a separate HTTP service. The TypeScript node is an HTTP client wrapper, not a native extension of Flowise's Python/JS internals.
4. **Existing endpoints unchanged.** `/sessions`, `/sessions/stream`, `/sessions/{id}/resume` are not modified.

---

## Acceptance Criteria

| # | Criterion | Milestone |
|---|-----------|-----------|
| AC-1 | `POST /sessions/complete` with `auto_approve=true` returns `status: "completed"` with `chatflow_id` | M5.1 |
| AC-2 | `auto_approve=false` returns `status: "pending_interrupt"` at first HITL | M5.1 |
| AC-3 | Audit trail for `auto_approve` session contains `[auto-approved]` notes on interrupt events | M5.1 |
| AC-4 | Custom tool JS template calls the agent and returns a chatflow result string | M5.2 |
| AC-5 | TypeScript node compiles without errors | M5.3 |
| AC-6 | TypeScript node appears in Flowise palette and successfully invokes agent | M5.3 |
| AC-7 | All existing tests in `tests/test_patch_ir.py` still pass after M5.1 | M5.1 |

---

## In-Scope vs Deferred

| Item | M5.1 | M5.2 | M5.3 | Future |
|------|:----:|:----:|:----:|:------:|
| `/sessions/complete` endpoint | ✅ | | | |
| `auto_approve` HITL bypass | ✅ | | | |
| Custom Tool JS template | | ✅ | | |
| TypeScript Custom Node | | | ✅ | |
| Streaming from inside node | | | | Future |
| Native Flowise process integration | | | | — |
| Cross-domain R4 features via node | | | | Depends on R4 |

---

## Related

- [roadmap4_workday_cross_domain.md](roadmap4_workday_cross_domain.md) — Independent; R5 does not require R4
- [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) — DD-056 through DD-058 (reserved)
- [flowise_dev_agent/api.py](flowise_dev_agent/api.py) — `/sessions/complete` added in M5.1
- Flowise Custom Node docs: https://docs.flowiseai.com/contributing/building-node
- Flowise Custom Tool docs: https://docs.flowiseai.com/integrations/langchain/tools/custom-tool
