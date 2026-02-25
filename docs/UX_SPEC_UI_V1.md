# UX Spec — Flowise Dev Agent UI v1

**Branch:** `feat/ux-worldclass-ui-v1`
**Author:** Lead / UX Architect
**Status:** Draft — Milestone UX-1
**Last updated:** 2026-02-24

---

## 1. Purpose and scope

Build a production-quality developer co-pilot UI that gives full visibility into the Flowise Dev Agent's 18-node graph, supports both CREATE and UPDATE flows with explicit HITL checkpoints, and enables fast iteration on chatflow builds.

The UI replaces the existing single-file `flowise_dev_agent/static/index.html` with a Next.js app (App Router, TypeScript, Tailwind CSS, shadcn/ui). During development the Next.js dev server runs on `:3001` and proxies API calls to FastAPI on `:8000`. (Flowise itself already occupies `:3000`.) In production the built static output is served directly by FastAPI.

---

## 2. Information architecture

```
/ (Session List — dashboard)
└── /sessions/[id] (Session Detail)
    ├── Phase Timeline          (left panel, always visible)
    ├── Active Panel            (center, context-switches on state)
    │   ├── Streaming           (while graph is running)
    │   ├── HITL: Clarification
    │   ├── HITL: Credential Check
    │   ├── HITL: Plan Approval
    │   ├── HITL: Select Target  ← UPDATE flow
    │   ├── HITL: Result Review
    │   └── Completed           (done state)
    └── Artifacts Panel         (right, collapsible)
        ├── Plan (latest)
        ├── Test results
        ├── Version history
        └── Telemetry
```

---

## 3. Screens

### S1 — Session List (Dashboard)

**Route:** `/`

**Purpose:** Entry point. Shows all sessions. New session CTA.

**Layout:**
- Top bar: app name, API key field (password input, persisted to localStorage)
- Session table (sorted newest-first by default):
  - Status badge (color-coded)
  - Session name (editable inline)
  - Operation mode pill (`CREATE` / `UPDATE`)
  - Chatflow ID (monospace, copyable)
  - Iteration count
  - Token total (in + out)
  - Last activity time (relative: "2m ago")
  - Actions: open, rename, delete
- Empty state: "No sessions yet. Start your first co-development session." + primary CTA
- Footer: total sessions count, token budget summary

**Actions:**
- `+ New Session` (primary button, top-right) → opens New Session modal (S2)
- Click any row → navigate to `/sessions/[id]`
- Refresh button → re-fetch GET /sessions
- Auto-refresh: poll GET /sessions every 5s while any session is `in_progress`

**Data source:** `GET /sessions` → `list[SessionSummary]`

---

### S2 — New Session Modal

**Trigger:** "+ New Session" button on S1 or S3 (sidebar).

**Fields:**
- Requirement textarea (required, `min-height: 120px`)
  - Placeholder: `Describe what you want to build or change in Flowise...`
  - Hint: Ctrl+Enter to start
- Test trials (number input, 1–5, default 1)
  - Helper: "Higher values = pass^k reliability. Each trial repeats all tests."
- Advanced section (collapsed by default):
  - Flowise instance (select from GET /instances, optional)
  - Webhook URL (text input, optional)

**Submit:** `Start Session →` → `POST /sessions/stream`

**On submit:**
1. Generate a `thread_id = crypto.randomUUID()`
2. Navigate to `/sessions/[thread_id]`
3. Start SSE stream immediately

---

### S3 — Session Detail

**Route:** `/sessions/[id]`

**Layout:** Three-panel with responsive collapse:

```
┌──────────────────────────────────────────────────────────────────┐
│ Header: session name | status badge | operation mode | tokens    │
├──────────────────┬───────────────────────────┬───────────────────┤
│  Phase Timeline  │   Active Panel             │  Artifacts Panel  │
│  (240px, fixed) │   (flex: 1)                │  (320px, toggle)  │
│                  │                            │                    │
│  [classify]  ✓  │   <context-specific>       │  Plan / Tests /   │
│  [hydrate]   ✓  │                            │  Versions /       │
│  [resolve]   ⏸  │                            │  Telemetry        │
│  [plan]      …  │                            │                    │
│  [patch]        │                            │                    │
│  [apply]        │                            │                    │
│  [test]         │                            │                    │
│  [evaluate]     │                            │                    │
└──────────────────┴───────────────────────────┴───────────────────┘
```

---

### S3a — Phase Timeline

**Data source:** `GET /sessions/{id}/stream?after_seq=0` (M9.2 node SSE)

**Phases and nodes** (in order):

| Phase | Nodes | CREATE? | UPDATE? |
|-------|-------|---------|---------|
| Classify | classify_intent | ✓ | ✓ |
| Hydrate | hydrate_context | ✓ | ✓ |
| Resolve | resolve_target, hitl_select_target | — | ✓ |
| Load | load_current_flow, summarize_current_flow | — | ✓ |
| Plan | plan_v2, hitl_plan_v2 | ✓ | ✓ |
| Patch | define_patch_scope, compile_patch_ir, compile_flow_data, validate, repair_schema, preflight_validate_patch | ✓ | ✓ |
| Apply | apply_patch, test_v2, evaluate, hitl_review_v2 | ✓ | ✓ |

**Node states:**

| State | Visual |
|-------|--------|
| `pending` | Gray circle outline |
| `running` | Blue spinner (animated) |
| `completed` | Green filled circle + checkmark |
| `interrupted` | Amber pause icon (HITL waiting) |
| `failed` | Red X |
| `skipped` | Gray dashed circle (e.g. resolve/load in CREATE mode) |

**Behavior:**
- Phases are expandable (click to show individual nodes within)
- `duration_ms` shown on completed nodes (e.g. "412ms")
- `summary` text shown as tooltip or inline sub-label
- HITL nodes: amber pulsing border + "Waiting for you" label
- Scroll-lock: timeline auto-scrolls to current running node
- Replay on page load: fetch all events from `after_seq=0`, reconstruct timeline state
- Reconnect: if SSE disconnects, reconnect with `after_seq=<last_seq>` (exponential backoff, 3 attempts)

---

### S3b — Active Panel: Streaming

**When:** Graph is actively running (no interrupt pending).

**Content:**
- Phase progress label (matches current running phase from timeline)
- Tool call feed: each tool call as a row with name, calling/done state, preview on done
- Raw output stream (collapsible, defaulted open): shows `token` events as they arrive (monospace, auto-scroll)

**SSE source:** `POST /sessions/stream` or `POST /sessions/{id}/stream`

**Events consumed:**
- `token` → append to raw output stream
- `tool_call` → add tool row with calling state
- `tool_result` → update tool row to done + preview
- `interrupt` → transition to HITL panel (see S3c–S3g)
- `done` → transition to Completed (S3h)
- `error` → transition to error state

---

### S3c — HITL Panel: Clarification

**Interrupt type:** `clarification`

**Content:**
- Label: "? Clarification Needed" (blue)
- Body: `pl.prompt` as plain text (questions to answer)
- Textarea: "Answer the questions above"
- Submit: "Send Answers →"

**Response handling:** Free text → `POST /sessions/{id}/stream { response: <text> }`

---

### S3d — HITL Panel: Credential Check

**Interrupt type:** `credential_check`

**Content:**
- Label: "⚠ Credential Check" (red)
- Missing credentials: `pl.missing_credentials` as badge chips
- Instructions: "Create these in Flowise → Settings → Credentials → Add New, then paste the credential IDs below. Or reply `skip` to continue without them."
- Input: credential ID(s) textarea
- Submit: "Submit Credentials →"

**Response handling:** Credential IDs or "skip" → resume stream

---

### S3e — HITL Panel: Plan Approval

**Interrupt type:** `plan_approval`

**Content:**
- Label: "✎ Plan Ready for Review" (green)
- Thread metadata: chatflow ID (if known), iteration badge
- Plan body: `pl.plan` rendered as Markdown (syntax highlighted, scrollable, max-height 60vh)
- If `pl.options` present: approach selector cards (one per option, radio-style selection, required before approve)
- Textarea for feedback (placeholder: `"approved"`)
- Actions:
  - `✓ Approve Plan` (primary green) → quick-reply "approved"
  - If options: `✓ Approve Selected Approach` (disabled until approach chosen) → "approved - approach: <label>"
  - `Send Changes →` (secondary) → sends textarea content as feedback
- Pattern badge: if `pattern_used: true`, show "Based on pattern: <pattern_id>" pill

**Response handling:**
- "approved" or "approved - approach: <label>" → agent continues
- Any other text → plan node re-runs with feedback

---

### S3f — HITL Panel: Select Target (UPDATE flow)

**Interrupt type:** `select_target`

**Content:**
- Label: "⟳ Select Chatflow to Update" (amber)
- Prompt text: `pl.prompt`
- Candidate list from `pl.top_matches`:
  - Each row: chatflow name (bold), chatflow ID (monospace, truncated), last-updated (relative time)
  - Select button per row
  - Selected row: highlighted with accent border + checkmark
- Footer actions:
  - `Update Selected Chatflow →` (primary, disabled until selection made)
  - `Create New Instead` (secondary) → sends "create new"

**Response handling:**
- Selected chatflow ID → `POST /sessions/{id}/stream { response: "<chatflow_id>" }`
- "Create new" → `POST /sessions/{id}/stream { response: "create new" }`

**Notes:**
- `top_matches` comes directly in the interrupt payload — no additional API call needed
- If `top_matches` is empty, show "No matching chatflows found" + "Create New" as primary

---

### S3g — HITL Panel: Result Review

**Interrupt type:** `result_review`

**Content:**
- Label: "✓ Tests Complete — Review Results" (blue)
- Test result badges: HAPPY PATH [PASS/FAIL] + EDGE CASE [PASS/FAIL] (extracted from test_results text)
- Test results body: collapsible raw text (collapsed by default, "Show details" toggle)
- Chatflow ID pill + link to Flowise instance (if FLOWISE_BASE_URL env known)
- Iteration counter badge
- Actions:
  - `✓ Accept & Done` (primary green) → quick-reply "accepted"
  - `↩ Rollback` (secondary red) → quick-reply "rollback"
  - `Request Changes →` (secondary) → sends textarea feedback
- Textarea: "Describe what to change in the next iteration"

**Response handling:**
- "accepted" → sets `done=true`, graph ends → S3h
- "rollback" → triggers chatflow rollback, graph ends
- Any other text → plan node re-runs with feedback

---

### S3h — Active Panel: Completed

**When:** `done` SSE event received OR `data.status === "completed"` on load.

**Content:**
- "✓ Built Successfully" header (green)
- Session stats: iterations, total tokens (in + out), duration
- Chatflow ID (monospace, copy button)
- `+ New Session` (primary button)
- `View Audit Trail` toggle → fetch `GET /sessions/{id}/summary` and render markdown inline

---

### S3i — Artifacts Panel (right panel, toggleable)

**Tabs:**
1. **Plan** — latest `pl.plan` markdown (from plan_approval interrupt, updated each iteration)
2. **Tests** — latest test results text, parsed PASS/FAIL badges
3. **Versions** — fetch `GET /sessions/{id}/versions`:
   - List of snapshots (label, timestamp, chatflow ID)
   - Rollback button per snapshot → `POST /sessions/{id}/rollback?version=<label>`
4. **Telemetry** — from `SessionSummary` fields:
   - `phase_durations_ms` as a mini bar chart or table
   - `schema_fingerprint` (truncated) + `drift_detected` warning badge
   - `pattern_metrics` (pattern used, ops count)
   - `knowledge_repair_count`, `get_node_calls_total`
5. **Patterns** — `GET /patterns` — list of saved patterns (name, tags, use-case description)

---

## 4. User journeys

### J1 — CREATE (happy path)

```
/ → click "+ New Session" → S2 (modal)
  → fill requirement → "Start Session →"
  → /sessions/[id] → streaming panel
  → classify_intent ✓ → hydrate_context ✓ → plan_v2 running…
  → hitl_plan_v2 INTERRUPT → S3e (Plan Approval panel)
  → user clicks "✓ Approve Plan"
  → streaming resumes → patch phases → apply_patch ✓ → test_v2 ✓
  → hitl_review_v2 INTERRUPT → S3g (Result Review panel)
  → user clicks "✓ Accept & Done"
  → S3h (Completed)
```

### J2 — UPDATE (select target)

```
/ → "+ New Session" → requirement: "Update the RAG chatbot to add memory"
  → /sessions/[id] → streaming
  → classify_intent → operation_mode: "update"
  → resolve_target → hitl_select_target INTERRUPT → S3f (Select Target panel)
  → top_matches shows 3 candidate chatflows
  → user selects one → "Update Selected Chatflow →"
  → streaming resumes → load_current_flow → summarize_current_flow
  → plan_v2 → hitl_plan_v2 INTERRUPT → S3e
  → ... (same as CREATE from plan approval forward)
```

### J3 — Iteration (plan rejected)

```
S3e (Plan Approval) → user types "Use Claude instead of GPT-4"
  → streaming → plan_v2 re-runs with feedback
  → hitl_plan_v2 INTERRUPT again → S3e (Plan Approval, iteration 1)
  → user approves → continue
```

### J4 — Open existing interrupted session

```
/ → click session row (status: pending_interrupt)
  → /sessions/[id] → GET /sessions/{id}
  → has interrupt payload → render correct HITL panel immediately
  → Phase timeline: replay from GET /sessions/{id}/stream?after_seq=0
  → completed phases show as ✓
```

### J5 — Reconnect after SSE disconnect

```
Session is streaming → network drop
  → GET SSE disconnects
  → UI shows reconnect indicator
  → exponential backoff: 1s → 2s → 4s (max 3 attempts)
  → on reconnect: GET /sessions/{id}/stream?after_seq=<last_seq>
  → missed events replayed from Postgres
  → POST SSE: re-subscribe to stream via POST /sessions/{id}/stream { response: "" }
  → (note: if the session completed during disconnect, load final state from GET /sessions/{id})
```

---

## 5. State machine

```
idle
  │ start session
  ▼
streaming ──→ error
  │ interrupt event
  ▼
interrupted
  │ submit response → streaming
  │ (accepted / rollback) → completed
  ▼
completed
  │ + New Session
  ▼
idle
```

Session-level status mapping:
| Backend status | UI label | Badge color |
|----------------|----------|-------------|
| `pending_interrupt` | "Waiting for you" | Amber |
| `in_progress` | "Running" | Blue |
| `completed` | "Done" | Green |
| `error` | "Error" | Red |

---

## 6. Event → UI mapping

### POST SSE events (active stream)

| SSE `type` | Fields | UI action |
|-----------|--------|-----------|
| `token` | `content: str` | Append to raw output stream (auto-scroll) |
| `tool_call` | `name: str` | Add tool row with "calling…" badge |
| `tool_result` | `name: str`, `preview: str` | Update tool row to ✓ + show preview |
| `interrupt` | type, prompt, plan, options, top_matches, test_results, missing_credentials, chatflow_id, iteration | Switch to matching HITL panel |
| `done` | `thread_id: str` | Switch to Completed panel |
| `error` | `detail: str` | Switch to error state + toast |

### GET SSE events (M9.2 node lifecycle — phase timeline)

| SSE `type` | Fields | UI action |
|-----------|--------|-----------|
| `node_start` | node_name, phase, status, seq | Mark phase node as "running" (spinner) |
| `node_end` | node_name, phase, status, duration_ms, summary, seq | Mark node "completed" (✓), show duration |
| `node_error` | node_name, phase, status, duration_ms, summary, seq | Mark node "failed" (✗), show error summary |
| `interrupt` | node_name, phase, status, seq | Mark node "interrupted" (⏸), pulse amber |
| `done` | session_id | Mark all remaining nodes as "skipped" or "done" |

---

## 7. Component list

| Component | File | Description |
|-----------|------|-------------|
| `SessionList` | `components/session/SessionList.tsx` | Table of all sessions |
| `SessionCard` | `components/session/SessionCard.tsx` | Single session row |
| `NewSessionModal` | `components/session/NewSessionModal.tsx` | Requirement form + submit |
| `PhaseTimeline` | `components/timeline/PhaseTimeline.tsx` | 7-phase vertical timeline |
| `PhaseRow` | `components/timeline/PhaseRow.tsx` | Single phase group (expandable) |
| `NodeRow` | `components/timeline/NodeRow.tsx` | Individual node within a phase |
| `StreamingPanel` | `components/hitl/StreamingPanel.tsx` | Active run view (tokens + tools) |
| `ToolCallFeed` | `components/hitl/ToolCallFeed.tsx` | Scrolling list of tool calls |
| `PlanApproval` | `components/hitl/PlanApproval.tsx` | Plan markdown + approach chips |
| `SelectTarget` | `components/hitl/SelectTarget.tsx` | top_matches list + selection |
| `ResultReview` | `components/hitl/ResultReview.tsx` | Test result badges + actions |
| `CredentialCheck` | `components/hitl/CredentialCheck.tsx` | Missing cred badges + input |
| `Clarification` | `components/hitl/Clarification.tsx` | Questions + answer textarea |
| `ArtifactsPanel` | `components/artifacts/ArtifactsPanel.tsx` | Tabbed: plan/tests/versions/telemetry |
| `VersionHistory` | `components/artifacts/VersionHistory.tsx` | Snapshot list + rollback |
| `TelemetryView` | `components/artifacts/TelemetryView.tsx` | Phase durations + drift badge |
| `PatternsBrowser` | `components/artifacts/PatternsBrowser.tsx` | Pattern cards from GET /patterns |

---

## 8. Acceptance criteria

### AC-1: Session List
- [ ] Lists all sessions from `GET /sessions`, sorted newest-first
- [ ] Shows status badge, session name, operation mode, chatflow ID, iteration, tokens
- [ ] "New Session" opens modal
- [ ] Auto-refreshes every 5s while any session is `in_progress`
- [ ] Inline rename (click pencil icon → input field → Enter/blur to save)
- [ ] Delete with confirmation dialog

### AC-2: CREATE flow (happy path)
- [ ] Requirement form submits and navigates to session detail
- [ ] Phase timeline shows nodes progressing in real time
- [ ] Plan Approval panel renders plan markdown correctly
- [ ] Approach chips appear when `options` is non-empty; Approve is disabled until one is selected
- [ ] Approving plan continues stream
- [ ] Result Review shows PASS/FAIL badges
- [ ] Accepting transitions to Completed panel

### AC-3: UPDATE flow
- [ ] Requirement that implies update triggers `select_target` interrupt
- [ ] Select Target panel renders `top_matches` with name, ID, last-updated
- [ ] "Update Selected" button is disabled until a row is selected
- [ ] "Create New Instead" sends "create new" response
- [ ] After selection, stream continues with load/summarize phases visible in timeline

### AC-4: Phase timeline
- [ ] Timeline renders all 7 phase groups
- [ ] Nodes within phases show correct state (pending/running/completed/interrupted/failed/skipped)
- [ ] Duration shown on completed nodes
- [ ] HITL nodes pulse amber while waiting
- [ ] Page load replays full history from `GET /sessions/{id}/stream?after_seq=0`
- [ ] CREATE mode: resolve/load phases shown as `skipped`
- [ ] UPDATE mode: all phases shown

### AC-5: SSE reconnect
- [ ] Disconnected GET SSE reconnects with `after_seq=<last_seq>` (exponential backoff)
- [ ] Max 3 reconnect attempts, then shows "Connection lost" indicator with retry button
- [ ] On reconnect, missed events replay correctly (no duplicate phases)
- [ ] `in_progress` session loaded from sidebar immediately reconnects to node SSE

### AC-6: Artifacts panel
- [ ] Plan tab shows latest plan markdown
- [ ] Tests tab shows latest test_results with PASS/FAIL parsed
- [ ] Versions tab lists snapshots from `GET /sessions/{id}/versions`
- [ ] Rollback button per snapshot triggers `POST /sessions/{id}/rollback?version=<label>`
- [ ] Telemetry tab shows phase durations, schema fingerprint, drift warning, pattern metrics
- [ ] Patterns tab shows cards from `GET /patterns`

### AC-7: Error states
- [ ] API errors show toast notification
- [ ] SSE `error` event shows inline error in streaming panel
- [ ] 401 response shows "API Key required" alert
- [ ] Missing session (404) redirects to session list
- [ ] Empty `top_matches` shows "No candidates found" with "Create New" as primary action

### AC-8: Accessibility
- [ ] All interactive elements have visible focus indicators
- [ ] Status badges have text labels (not color-only)
- [ ] HITL response textarea auto-focuses when panel mounts
- [ ] Keyboard: Ctrl+Enter submits new session form; Enter submits HITL response (except plan textarea)
- [ ] Color contrast ≥ 4.5:1 for all text

---

## 9. Out of scope for v1

- Multi-user / auth beyond the existing Bearer token
- Real-time collaboration
- Chatflow visual graph preview
- Mobile layout
- i18n
- Dark/light theme toggle (dark only for v1)

---

## 10. Open questions (to resolve by UX-2)

1. Should the Patterns tab allow saving a new pattern manually from the UI, or is it read-only?
2. Does the audit trail (`GET /sessions/{id}/summary`) return enough structured data for the Artifacts panel, or do we need it to return JSON?
3. Should the completed session panel auto-load audit trail, or require a button click?
4. What is the desired behavior when a session fails mid-graph (not a HITL interrupt, but an actual exception)?
