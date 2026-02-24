# Roadmap 6: UI & Agent Iteration Fixes

**Status:** Planning
**Created:** 2026-02-23
**Branch:** TBD (new branch off main)
**Predecessor:** None — independent of R4 and R5

---

## Context

After M1/M2 end-to-end testing, four issues were identified:

1. **Chatflow re-creation bug** — on every HITL iterate cycle, the v1 patch node creates a brand-new chatflow instead of updating the one from the first patch. Root cause: the LLM is never told a chatflow already exists, so it defaults to `create_chatflow` each time.

2. **Plan approval — no way to select between approaches** — when the LLM presents multiple implementation approaches in the plan (e.g. "UPDATE OR CREATE"), the Approve button sends only "approved" with no way to specify which approach to take. This needs a general mechanism: 2, 3, or more selectable options rendered as clickable buttons.

3. **Result review — no Rollback button** — `result_review` has no structured Rollback option. The developer has to type freeform text to revert.

4. **Session deletion missing from UI** — `DELETE /sessions/{thread_id}` already exists in the backend (api.py:717) but there is no delete button in the sidebar.

5. **Session naming** — sessions show a truncated UUID (`abc123ef0134d…`) which is meaningless. Developers want LLM-generated short titles at session creation and the ability to rename them inline (like Claude's sidebar UX).

---

## Change 1 — Fix Chatflow Re-Creation (v1 Patch Node)

**File:** `flowise_dev_agent/agent/graph.py`

**Root cause:** `_make_patch_node()` (lines 887–945) builds the LLM user context without mentioning `chatflow_id`. The LLM sees the original plan ("CREATE a new chatflow…") and calls `create_chatflow` again on every iteration.

**Fix:** In `_make_patch_node()`, read `chatflow_id = state.get("chatflow_id")` and inject it into the user context message:

```python
existing_note = ""
if chatflow_id:
    existing_note = (
        f"\n\nIMPORTANT: Chatflow '{chatflow_id}' already exists for this session. "
        "Use `update_chatflow` to modify it. Do NOT call `create_chatflow` — "
        "that would create a duplicate."
    )

ctx = [
    Message(
        role="user",
        content=(
            f"Requirement:\n{state['requirement']}\n\n"
            f"Discovery summary:\n{state.get('discovery_summary') or '(none)'}"
            f"{existing_note}"   # ← injected
        ),
    ),
    ...
]
```

Also pass the selected approach from `developer_feedback` into the patch context (feeds into Change 2):

```python
feedback = state.get("developer_feedback") or ""
if feedback:
    existing_note += f"\n\nDeveloper selected approach: {feedback}"
```

**No change to v2 patch node** — it already handles this correctly at line 1186 (programmatic CREATE vs UPDATE).

---

## Change 2 — Structured Plan Options (Plan Approval)

When the LLM presents multiple approaches, users need to select one via a clickable button — not guess by typing freeform text. This mechanism handles 2, 3, or more alternatives generically.

### 2a. Update plan node system prompt to emit structured approaches

**File:** `flowise_dev_agent/agent/graph.py`

Add an `## APPROACHES` section format to the plan system prompt:

```
If the plan has multiple viable implementation approaches, list them under:
## APPROACHES
1. <short label>: <one-sentence description>
2. <short label>: <one-sentence description>
(omit this section if there is only one clear approach)
```

### 2b. Add `options` to `InterruptPayload` and parse from plan

**File:** `flowise_dev_agent/api.py`

```python
options: list[str] | None = Field(None, description="Selectable approach labels when the plan presents multiple choices")
```

**File:** `flowise_dev_agent/agent/graph.py`

Add `_parse_plan_options(plan_text: str) -> list[str] | None` helper — regex-extracts numbered items under `## APPROACHES`, returns their labels, or `None` if the section is absent.

In `_make_human_plan_approval_node()`:

```python
options = _parse_plan_options(state["plan"])
interrupt_payload = {
    "type": "plan_approval",
    "plan": state["plan"],
    "iteration": state.get("iteration", 0),
    "options": options,   # ← new
    "prompt": "...",
}
```

### 2c. UI: render option buttons when `interrupt.options` is present

**File:** `flowise_dev_agent/static/index.html`

Replace the hardcoded single "✓ Approve Plan" button with dynamic option rendering:

- If `interrupt.options` has entries: render each as a selectable card button; enable "✓ Approve Selected Approach" only after one is chosen
- If no options: show original "✓ Approve Plan" button (unchanged)
- Selected approach sent as `"approved - approach: {label}"` via existing `quickReply()` / resume flow

```javascript
if (interrupt.options && interrupt.options.length > 0) {
    // render selectable approach cards
    // ✓ Approve Selected Approach button (disabled until selection)
} else {
    // original single Approve Plan button
}
```

---

## Change 3 — Rollback Button on Result Review

### 3a. Backend: handle "rollback" response in `human_result_review`

**File:** `flowise_dev_agent/agent/graph.py`

In `_make_human_result_review_node()` (lines 1700–1743), add a rollback branch before the accept/iterate logic:

```python
if developer_response.strip().lower() in ("rollback", "revert"):
    return {
        "done": True,
        "developer_feedback": "[rollback requested by developer]",
    }
```

No new API endpoint needed — rollback is already wired via `POST /sessions/{id}/rollback`.

### 3b. UI: add Rollback button to result_review interrupt

**File:** `flowise_dev_agent/static/index.html`

Add alongside existing "✓ Accept" button (around line 662):

```html
<button onclick="quickReply('accepted')">✓ Accept</button>
<button onclick="quickReply('rollback')" class="btn-danger">↩ Rollback</button>
```

`quickReply()` already exists — no new JS needed.

---

## Change 4 — Session Delete Button in UI

**File:** `flowise_dev_agent/static/index.html`

`DELETE /sessions/{thread_id}` is already implemented at api.py:717. Only a UI change is needed.

Add trash icon to each session row in the sidebar (around line 718):

```html
<button class="s-delete" onclick="deleteSession(event,'${esc(s.thread_id)}')" title="Delete session">🗑</button>
```

Add `deleteSession()` JS function:

```javascript
async function deleteSession(evt, threadId) {
    evt.stopPropagation();
    if (!confirm('Delete this session? This cannot be undone.')) return;
    await apiFetch(`/sessions/${threadId}`, { method: 'DELETE' });
    state.sessions = state.sessions.filter(s => s.thread_id !== threadId);
    if (state.threadId === threadId) transition('idle');
    render();
}
```

CSS: trash icon hidden until session row is hovered.

---

## Change 5 — Session Naming

### 5a. Add `session_name` to AgentState

**File:** `flowise_dev_agent/agent/state.py`

```python
session_name: str | None  # short LLM-generated display title; editable by developer
```

### 5b. Generate name at session creation

**File:** `flowise_dev_agent/api.py`

Add `_generate_session_name(requirement, engine) -> str` helper — makes a single short LLM call for a 4–6 word title; falls back to first 60 chars of requirement if the call fails.

Call in both `create_session` and `stream_create_session` before `_initial_state()`:

```python
session_name = await _generate_session_name(body.requirement, _get_engine(request))
initial = _initial_state(..., session_name=session_name)
```

### 5c. Expose `session_name` in `SessionSummary` and `GET /sessions`

**File:** `flowise_dev_agent/api.py`

Add to `SessionSummary`:
```python
session_name: str | None = Field(None)
```

Update `list_sessions()` to extract `sv.get("session_name")` from state values.

### 5d. Add `PATCH /sessions/{thread_id}/name` endpoint

**File:** `flowise_dev_agent/api.py`

```python
class RenameSessionRequest(BaseModel):
    name: str = Field(..., max_length=120)

@app.patch("/sessions/{thread_id}/name", ...)
async def rename_session(thread_id: str, body: RenameSessionRequest, request: Request) -> dict:
    graph = _get_graph(request)
    await graph.aupdate_state({"configurable": {"thread_id": thread_id}}, {"session_name": body.name})
    return {"thread_id": thread_id, "session_name": body.name}
```

### 5e. UI sidebar: show session_name with inline rename

**File:** `flowise_dev_agent/static/index.html`

- **Title row:** `s.session_name || shortId(s.thread_id)` as the primary display name
- **Pencil icon:** visible on hover; clicking switches to an inline `<input>` pre-filled with current name
- **Save/cancel:** Enter or blur saves via `PATCH /sessions/{id}/name`; Escape cancels
- **Thread ID:** demoted to `.s-meta` secondary line (small, dimmed)

---

## Files Modified

| File | Changes |
|------|---------|
| `flowise_dev_agent/agent/graph.py` | Inject `chatflow_id` + `developer_feedback` into v1 patch context; `_parse_plan_options()` helper; `options` in plan_approval payload; rollback branch in result_review node |
| `flowise_dev_agent/agent/state.py` | Add `session_name: str \| None` field |
| `flowise_dev_agent/api.py` | `options` field in `InterruptPayload`; `_generate_session_name()` helper; `session_name` in `_initial_state()`; `SessionSummary` update; `list_sessions()` update; `RenameSessionRequest` + `PATCH /sessions/{id}/name` |
| `flowise_dev_agent/static/index.html` | Dynamic approach option cards for plan_approval; Rollback button for result_review; delete button + `deleteSession()`; session name display + inline rename |

---

## Design Decisions to Add

| DD | Title |
|----|-------|
| DD-059 | v1 patch node chatflow context injection — `chatflow_id` and `developer_feedback` injected into LLM user message to prevent duplicate chatflow creation on iteration |
| DD-060 | Structured plan `## APPROACHES` section — plan node emits machine-readable approach list; `InterruptPayload.options` carries labels to UI; selected approach routed back to patch node |
| DD-061 | `session_name` in `AgentState` — LLM-generated 4–6 word title set at session creation; editable via `PATCH /sessions/{id}/name` using `aupdate_state()` |

---

## Acceptance Criteria

| # | Criterion | Change |
|---|-----------|--------|
| AC-1 | Second patch iteration calls `update_chatflow`, not `create_chatflow` | C1 |
| AC-2 | Plan with `## APPROACHES` section surfaces clickable option buttons in UI | C2 |
| AC-3 | Plan without `## APPROACHES` shows original single Approve button | C2 |
| AC-4 | Clicking "↩ Rollback" at result_review completes session with rollback note | C3 |
| AC-5 | Trash icon appears on session hover; confirm → session removed from sidebar | C4 |
| AC-6 | New session sidebar title shows LLM-generated name within 1s of creation | C5 |
| AC-7 | Clicking pencil → inline input → Enter saves new name via PATCH endpoint | C5 |
| AC-8 | Renamed session name persists after page refresh | C5 |
| AC-9 | All 28 tests in `tests/test_patch_ir.py` still pass | All |

---

## Related

- [roadmap3_architecture_optimization.md](roadmap3_architecture_optimization.md) — M1/M2 complete; v1/v2 patch node architecture
- [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) — DD-059 through DD-061 (reserved)
- [flowise_dev_agent/agent/graph.py](flowise_dev_agent/agent/graph.py) — `_make_patch_node()` (v1, lines 887–945), `_make_human_plan_approval_node()` (lines 859–868), `_make_human_result_review_node()` (lines 1700–1743)
- [flowise_dev_agent/api.py](flowise_dev_agent/api.py) — `InterruptPayload` (lines 220–246), `SessionSummary` (lines 249–257), `DELETE /sessions/{id}` (lines 717–739)
- [flowise_dev_agent/static/index.html](flowise_dev_agent/static/index.html) — interrupt rendering (lines 591–676), sidebar (lines 718–729)
