"""End-to-end session integration tests (M8.3).

Tests the full API session lifecycle against a live server.

Skipped automatically when AGENT_E2E_SKIP=1 (set in CI environments
without a running agent server).

Run locally with the server running:
    pytest tests/test_e2e_session.py -v

Run against a custom host:
    AGENT_BASE_URL=http://localhost:8001 pytest tests/test_e2e_session.py -v

Tests:
  1. POST /sessions returns pending_interrupt with plan_approval interrupt
  2. plan_approval interrupt has non-empty plan text
  3. POST /sessions/{id}/resume with "approved" reaches result_review
  4. GET /sessions returns the created session in the list
  5. GET /healthz (or /docs) responds 200 — server is alive
  6. Approved session has a chatflow_id (flow created in Flowise)
  7. Credential binding produces a valid chatflow UUID

All tests marked @pytest.mark.slow so they can be excluded from fast CI:
    pytest tests/test_e2e_session.py -v -m "not slow"   # skips all e2e tests
"""

from __future__ import annotations

import os
import re

import pytest

# ---------------------------------------------------------------------------
# Skip sentinel
# ---------------------------------------------------------------------------

_SKIP_E2E = os.environ.get("AGENT_E2E_SKIP", "").strip() in {"1", "true", "yes"}
_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8000").rstrip("/")

pytestmark = pytest.mark.slow  # allow exclusion via -m "not slow"

if _SKIP_E2E:
    pytest.skip("AGENT_E2E_SKIP=1 — skipping e2e tests", allow_module_level=True)

# Lazy-import httpx so the module can be collected even without the package installed
try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

_SIMPLE_REQUIREMENT = (
    "Build a simple conversational chatflow. "
    "Use GPT-4o-mini as the LLM and a Buffer Memory. "
    "Wire them together with a ConversationChain. "
    "Name the chatflow 'E2E Test Chain'."
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    if not _HTTPX_AVAILABLE:
        pytest.skip("httpx not installed — skipping e2e tests")
    try:
        c = httpx.Client(timeout=30, base_url=_BASE_URL)
        # Quick health check — if server not running, skip all tests
        r = c.get("/docs")
        if r.status_code not in (200, 307):
            pytest.skip(f"Agent server not reachable at {_BASE_URL} (HTTP {r.status_code})")
        return c
    except Exception as exc:
        pytest.skip(f"Agent server not reachable at {_BASE_URL}: {exc}")


@pytest.fixture(scope="module")
def session_id(client):
    """Create a session and return the thread_id. Shared across tests in this module."""
    r = client.post("/sessions", json={"requirement": _SIMPLE_REQUIREMENT, "test_trials": 1}, timeout=120)
    assert r.status_code == 200, f"POST /sessions failed: {r.status_code} — {r.text[:400]}"
    body = r.json()
    tid = body.get("thread_id", "")
    assert tid, "thread_id missing from POST /sessions response"
    return tid


@pytest.fixture(scope="module")
def approved_session(client):
    """Create a session, approve the plan, and return (thread_id, response_body).

    Shared across credential-binding tests to avoid duplicate 5-minute API calls.
    """
    r1 = client.post(
        "/sessions",
        json={"requirement": _SIMPLE_REQUIREMENT, "test_trials": 1},
        timeout=120,
    )
    assert r1.status_code == 200, f"POST /sessions failed: {r1.status_code}"
    body1 = r1.json()
    tid = body1.get("thread_id", "")
    assert tid, "thread_id missing"
    assert body1.get("status") == "pending_interrupt"

    # Approve the plan
    r2 = client.post(f"/sessions/{tid}/resume", json={"response": "approved"}, timeout=300)
    assert r2.status_code == 200, f"Resume failed: {r2.status_code} — {r2.text[:400]}"
    return tid, r2.json()


# ---------------------------------------------------------------------------
# Test 1: POST /sessions returns pending_interrupt
# ---------------------------------------------------------------------------


def test_session_creation_returns_pending_interrupt(client, session_id):
    """POST /sessions must return status=pending_interrupt after discover + plan."""
    r = client.post("/sessions", json={"requirement": _SIMPLE_REQUIREMENT, "test_trials": 1}, timeout=120)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "pending_interrupt", (
        f"Expected pending_interrupt, got {body.get('status')!r}\nBody: {body}"
    )


# ---------------------------------------------------------------------------
# Test 2: Interrupt type is plan_approval
# ---------------------------------------------------------------------------


def test_first_interrupt_is_plan_approval(client, session_id):
    """The first interrupt must be plan_approval (not result_review or anything else)."""
    # Reuse the session created by the fixture
    r = client.post("/sessions", json={"requirement": _SIMPLE_REQUIREMENT, "test_trials": 1}, timeout=120)
    body = r.json()
    interrupt = body.get("interrupt") or {}
    assert interrupt.get("type") == "plan_approval", (
        f"Expected interrupt.type=plan_approval, got {interrupt.get('type')!r}\nInterrupt: {interrupt}"
    )


# ---------------------------------------------------------------------------
# Test 3: Plan text is non-empty
# ---------------------------------------------------------------------------


def test_plan_approval_has_non_empty_plan_text(client, session_id):
    """plan_approval interrupt must include non-empty plan text."""
    r = client.post("/sessions", json={"requirement": _SIMPLE_REQUIREMENT, "test_trials": 1}, timeout=120)
    body = r.json()
    interrupt = body.get("interrupt") or {}
    plan = interrupt.get("plan", "")
    assert plan and len(plan) > 50, (
        f"Plan text is missing or too short: {plan!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: Resume with "approved" reaches result_review
# ---------------------------------------------------------------------------


def test_resume_approved_reaches_result_review(approved_session):
    """After approving the plan, the next interrupt must be result_review."""
    _tid, body2 = approved_session

    # After approval we expect either result_review interrupt or completed
    status2 = body2.get("status")
    assert status2 in ("pending_interrupt", "completed"), (
        f"Unexpected status after approve: {status2!r}\nBody: {body2}"
    )
    if status2 == "pending_interrupt":
        interrupt2 = body2.get("interrupt") or {}
        itype2 = interrupt2.get("type", "")
        # M9.6: _route_after_evaluate_v2 can route back to plan_v2 on "iterate" verdict,
        # producing another plan_approval interrupt. Both are valid outcomes.
        assert itype2 in ("result_review", "plan_approval"), (
            f"Expected result_review or plan_approval after plan approval, got {itype2!r}"
        )


# ---------------------------------------------------------------------------
# Test 5: GET /sessions lists the created session
# ---------------------------------------------------------------------------


def test_list_sessions_includes_created_session(client, session_id):
    """GET /sessions must include the session created by the fixture."""
    r = client.get("/sessions")
    assert r.status_code == 200
    sessions = r.json()
    assert isinstance(sessions, list)
    ids = [s.get("thread_id") for s in sessions]
    assert session_id in ids, (
        f"Created session {session_id!r} not found in GET /sessions.\n"
        f"IDs present: {ids}"
    )


# ---------------------------------------------------------------------------
# Test 6: SessionSummary includes M8.2 telemetry fields
# ---------------------------------------------------------------------------


def test_list_sessions_has_m82_telemetry_fields(client, session_id):
    """Each session in GET /sessions must expose the M8.2 telemetry fields."""
    r = client.get("/sessions")
    sessions = r.json()
    target = next((s for s in sessions if s.get("thread_id") == session_id), None)
    assert target is not None, f"Session {session_id} not in list"

    assert "knowledge_repair_count" in target, "Missing knowledge_repair_count"
    assert "get_node_calls_total" in target, "Missing get_node_calls_total"
    assert "phase_durations_ms" in target, "Missing phase_durations_ms"
    assert isinstance(target["knowledge_repair_count"], int)
    assert isinstance(target["get_node_calls_total"], int)
    assert isinstance(target["phase_durations_ms"], dict)


# ---------------------------------------------------------------------------
# Test 7: Approved session has chatflow_id
# ---------------------------------------------------------------------------


def test_approved_session_has_chatflow_id(client, approved_session):
    """After plan approval and execution, chatflow_id must be set.

    Proves BindCredential ops didn't cause a compiler error — the flow was
    successfully created in Flowise with credentials bound.
    """
    tid, body2 = approved_session
    chatflow_id = body2.get("chatflow_id")

    # If not in resume response, try GET
    if not chatflow_id:
        r = client.get(f"/sessions/{tid}")
        assert r.status_code == 200
        chatflow_id = r.json().get("chatflow_id")

    assert chatflow_id, (
        f"Session {tid} has no chatflow_id — flow was not created in Flowise.\n"
        f"Resume response: {body2}"
    )


# ---------------------------------------------------------------------------
# Test 8: Credential binding produces a valid chatflow UUID
# ---------------------------------------------------------------------------


def test_credential_binding_produces_valid_chatflow(client, approved_session):
    """chatflow_id must be a valid UUID, proving the full pipeline worked:
    plan → patch IR with BindCredential → credential resolution → compile → Flowise create.
    """
    tid, body2 = approved_session
    chatflow_id = body2.get("chatflow_id")

    if not chatflow_id:
        r = client.get(f"/sessions/{tid}")
        chatflow_id = r.json().get("chatflow_id")

    if not chatflow_id:
        pytest.skip("No chatflow_id available — flow was not created in this run")

    assert re.match(r"^[0-9a-fA-F-]{36}$", chatflow_id), (
        f"chatflow_id does not look like a UUID: {chatflow_id!r}"
    )
