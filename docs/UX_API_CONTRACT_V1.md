# API Contract — Flowise Dev Agent UI v1

**For:** `feat/ux-worldclass-ui-v1` Next.js UI
**Backend:** FastAPI on `:8000`
**Auth:** `Authorization: Bearer <AGENT_API_KEY>` (omit header in open-dev mode when `AGENT_API_KEY` is unset)
**Base URL:** `http://localhost:8000` (dev) — configured via `NEXT_PUBLIC_API_URL` env var

---

## Auth

All endpoints require `Authorization: Bearer <key>` when `AGENT_API_KEY` is set server-side.
In open-dev mode (no `AGENT_API_KEY`), all requests are allowed without a header.
The UI stores the API key in `localStorage` under key `flowise_agent_api_key`.
On `401`, show "API Key required" alert and focus the key input in the top bar.

---

## Endpoints

### System

#### `GET /health`
Health check. Returns `{ api: "ok", flowise: "ok"|"unreachable", flowise_detail: {...} }`.
UI uses this on mount to show a connection badge.

#### `GET /instances`
List registered Flowise instance IDs.
Response: `{ default: string|null, instances: string[] }`
UI uses this to populate the Advanced section of the New Session Modal.

---

### Sessions

#### `GET /sessions`

List all sessions, newest-first by default.

**Query params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `sort` | `"desc"\|"asc"` | `"desc"` | Sort order (desc = newest first) |
| `limit` | `integer` | none | Max sessions to return |

**Response:** `SessionSummary[]`

```typescript
interface SessionSummary {
  thread_id: string;
  status: "pending_interrupt" | "completed" | "in_progress" | "error";
  iteration: number;
  chatflow_id: string | null;
  total_input_tokens: number;
  total_output_tokens: number;
  session_name: string | null;
  runtime_mode: "capability_first" | "compat_legacy" | null;
  total_repair_events: number;
  total_phases_timed: number;
  knowledge_repair_count: number;
  get_node_calls_total: number;
  phase_durations_ms: Record<string, number>;
  schema_fingerprint: string | null;
  drift_detected: boolean;
  pattern_metrics: Record<string, unknown> | null;
  updated_at: string | null; // ISO 8601
}
```

**UI usage:** Session List (S1). Auto-poll every 5s while any session has `status === "in_progress"`.

---

#### `POST /sessions/stream`

Start a new session and stream progress as Server-Sent Events.

**Request body:**
```typescript
interface StartSessionRequest {
  requirement: string;          // required
  thread_id?: string;           // optional — UI generates via crypto.randomUUID()
  test_trials?: number;         // 1–5, default 1
  flowise_instance_id?: string; // optional
  webhook_url?: string;         // optional HTTPS URL
}
```

**Response:** `text/event-stream`

SSE events:
```
data: {"type": "token",       "content": "..."}
data: {"type": "tool_call",   "name": "..."}
data: {"type": "tool_result", "name": "...", "preview": "..."}
data: {"type": "interrupt",   "type": "plan_approval"|"clarification"|"credential_check"|"result_review"|"select_target", "prompt": "...", "plan": "...", "options": [...], "top_matches": [...], "test_results": "...", "missing_credentials": [...], "chatflow_id": "...", "iteration": 0}
data: {"type": "done",        "thread_id": "..."}
data: {"type": "error",       "detail": "..."}
```

**UI flow:**
1. UI calls `POST /sessions/stream` with `{ requirement, thread_id: crypto.randomUUID(), test_trials }`
2. Navigates immediately to `/sessions/[thread_id]`
3. Subscribes to the SSE stream
4. Renders events in real time (tokens → streaming panel, interrupt → HITL panel, done → completed panel)

---

#### `POST /sessions/{thread_id}/stream`

Resume a paused session and stream continuation events.

**Request body:**
```typescript
interface ResumeSessionRequest {
  response: string; // developer's reply to the current interrupt
}
```

**Response:** Same SSE event stream as `POST /sessions/stream`.

**Common `response` values:**
- `"approved"` — approve the plan
- `"approved - approach: <label>"` — approve a specific approach
- `"accepted"` — accept test results, mark done
- `"rollback"` — trigger chatflow rollback
- `"<chatflow_id>"` — select a target chatflow (for `select_target` interrupt)
- `"create new"` — create new instead of updating (for `select_target`)
- Any other text — iteration feedback (plan or test re-runs)

---

#### `GET /sessions/{thread_id}/stream?after_seq={N}`

Stream node lifecycle events for the Phase Timeline (M9.2).
Returns all events with `seq > after_seq` from Postgres, then streams new events as they arrive.

**Query params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `after_seq` | `integer` | `0` | Replay events after this sequence number |

**Response:** `text/event-stream`

SSE events:
```
event: node_start
data: {"node_name": "...", "phase": "...", "status": "started", "seq": 1}

event: node_end
data: {"node_name": "...", "phase": "...", "status": "completed", "duration_ms": 412, "summary": "...", "seq": 2}

event: node_error
data: {"node_name": "...", "phase": "...", "status": "failed", "duration_ms": 99, "summary": "...", "seq": 3}

event: interrupt
data: {"node_name": "...", "phase": "...", "status": "interrupted", "seq": 4}

event: done
data: {"session_id": "..."}
```

**UI usage:** Phase Timeline (S3a). On page load: fetch `?after_seq=0` to replay full history. On reconnect: fetch `?after_seq=<last_seq>` to replay missed events. Use exponential backoff (1s → 2s → 4s, max 3 attempts).

**Phase → node mapping:**
| Phase | Nodes |
|-------|-------|
| Classify | classify_intent |
| Hydrate | hydrate_context |
| Resolve | resolve_target, hitl_select_target |
| Load | load_current_flow, summarize_current_flow |
| Plan | plan_v2, hitl_plan_v2 |
| Patch | define_patch_scope, compile_patch_ir, compile_flow_data, validate, repair_schema, preflight_validate_patch |
| Apply | apply_patch, test_v2, evaluate, hitl_review_v2 |

---

#### `GET /sessions/{thread_id}`

Get current session state without advancing the graph.

**Response:** `SessionResponse`

```typescript
interface SessionResponse {
  thread_id: string;
  status: "pending_interrupt" | "completed" | "error";
  iteration: number;
  chatflow_id: string | null;
  interrupt: InterruptPayload | null;
  message: string | null;
  total_input_tokens: number;
  total_output_tokens: number;
}

interface InterruptPayload {
  type: "clarification" | "credential_check" | "plan_approval" | "result_review" | "select_target";
  prompt: string;
  plan: string | null;
  test_results: string | null;
  chatflow_id: string | null;
  iteration: number;
  options: string[] | null;
  missing_credentials: string[] | null;
  top_matches?: Array<{ id: string; name: string; updated_at: string }>;
  pattern_used?: boolean;
  pattern_id?: number | null;
}
```

**UI usage:** On page load for `/sessions/[id]` — if session has an interrupt, render correct HITL panel immediately without waiting for SSE.

---

#### `DELETE /sessions/{thread_id}`

Permanently delete a session and all checkpoint data.
Response: `{ deleted: true, thread_id: string }`

---

#### `PATCH /sessions/{thread_id}/name`

Rename a session.
Request: `{ name: string }` (max 120 chars)
Response: `{ thread_id: string, session_name: string }`

---

#### `GET /sessions/{thread_id}/summary`

Audit trail markdown for a session.
Response: `{ thread_id: string, summary: string }` (summary is markdown text)
UI renders this inline in the Completed panel (S3h) when "View Audit Trail" is toggled.

---

#### `GET /sessions/{thread_id}/versions`

List chatflow version snapshots.
Response: `{ thread_id: string, versions: VersionSnapshot[], count: number }`

```typescript
interface VersionSnapshot {
  version_label: string;
  chatflow_id: string;
  timestamp: string; // ISO 8601
  name?: string;
}
```

---

#### `POST /sessions/{thread_id}/rollback?version={label}`

Roll back chatflow to a named snapshot.
Query param `version` is optional — omit to roll back to most recent snapshot.
Response: `SessionResponse`

---

### Patterns

#### `GET /patterns?q={keywords}`

List or search saved chatflow patterns.
Query param `q` is optional — without it returns 20 most recent patterns.
Response: `PatternSummary[]`

```typescript
interface PatternSummary {
  id: number;
  name: string;
  description?: string;
  tags: string[];
  success_count: number;
  category?: string;
}
```

---

## SSE Connection Management

### POST SSE (active stream)
- Created by `POST /sessions/stream` or `POST /sessions/{id}/stream`
- Lives for the duration of one graph run (until `interrupt` or `done` event)
- On `interrupt`: stop reading, show HITL panel
- On `done`: stop reading, show Completed panel
- On `error`: stop reading, show error state + toast

### GET SSE (node lifecycle — Phase Timeline)
- Created by `GET /sessions/{id}/stream?after_seq=N`
- Long-lived — stays open to receive future node events
- On disconnect: reconnect with `after_seq=<last_seq_received>` using exponential backoff
- Backoff: 1s → 2s → 4s, max 3 attempts, then show "Connection lost" + retry button
- On `done` event: stop reconnecting

---

## Error Handling

| HTTP status | UI behavior |
|-------------|-------------|
| `401` | Show "API Key required" alert, focus key input |
| `404` | Redirect to session list (`/`) |
| `409` | Toast: `detail` message |
| `422` | Form validation error, highlight field |
| `429` | Toast: "Rate limit exceeded — wait a moment" |
| `500` | Toast: `detail` message + show error in streaming panel |
| Network error | Retry with exponential backoff (SSE only), toast for non-SSE |

---

## Environment Variables (Next.js)

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | FastAPI base URL |
| `NEXT_PUBLIC_FLOWISE_URL` | `http://localhost:3000` | Flowise UI base URL (for links) |

---

## CORS

FastAPI allows `http://localhost:3001` (Next.js dev) and `http://localhost:3000` by default.
Override with `CORS_ORIGINS` env var (comma-separated list).

---

*Generated for Milestone UX-1 — 2026-02-24*
