"""FastAPI service for the Flowise Builder co-pilot agent.

Wraps the LangGraph graph in an HTTP API with two core flows:

  1. Start a session:  POST /sessions
       Initializes state, runs graph until first interrupt (plan approval),
       and returns the interrupt payload for the developer to review.

  2. Resume a session: POST /sessions/{thread_id}/resume
       Sends the developer's response, continues the graph until the next
       interrupt or completion, and returns the result.

Human-in-the-loop flow:
  POST /sessions        → runs discover + plan → INTERRUPT: plan_approval
  POST .../resume       → developer approves/edits plan
  (if approved)         → runs patch + test + converge → INTERRUPT: result_review
  POST .../resume       → developer accepts or requests iteration
  (if accepted)         → status: completed

See DESIGN_DECISIONS.md — DD-011, DD-012.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = logging.getLogger("flowise_dev_agent.api")

# ---------------------------------------------------------------------------
# API key authentication (optional — enabled when AGENT_API_KEY is set)
# ---------------------------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)


def _verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    """Verify Bearer token matches AGENT_API_KEY env var.

    If AGENT_API_KEY is not set, all requests are allowed (open dev mode).
    If set, every request must carry 'Authorization: Bearer <key>'.
    See DESIGN_DECISIONS.md — DD-028.
    """
    api_key = os.getenv("AGENT_API_KEY")
    if not api_key:
        return  # open access in dev mode
    if not credentials or credentials.credentials != api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ---------------------------------------------------------------------------
# Lifespan: create graph + client once at startup, close client on shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: initialize the agent on startup, clean up on shutdown."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from flowise_dev_agent.agent.graph import build_graph, create_engine
    from flowise_dev_agent.agent.tools import FloviseDomain
    from flowise_dev_agent.instance_pool import FlowiseClientPool
    from flowise_dev_agent.reasoning import ReasoningSettings
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    reasoning_settings = ReasoningSettings.from_env()

    db_path = os.getenv("SESSIONS_DB_PATH", "sessions.db")

    langsmith_key = os.getenv("LANGCHAIN_API_KEY")
    if langsmith_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "flowise-dev-agent")
        logger.info("LangSmith tracing enabled: project=%s", os.environ["LANGCHAIN_PROJECT"])

    logger.info(
        "Starting Flowise Dev Agent | Flowise: %s | Engine: %s | DB: %s",
        settings.api_endpoint,
        reasoning_settings.provider,
        db_path,
    )

    from flowise_dev_agent.agent.pattern_store import PatternStore

    pattern_db_path = os.getenv("PATTERN_DB_PATH", db_path)

    pool = FlowiseClientPool.from_env()
    default_client = pool.get(None)  # default instance for pattern save + graph wiring

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        engine = create_engine(reasoning_settings)
        domains = [FloviseDomain(default_client)]
        pattern_store = await PatternStore.open(pattern_db_path)

        graph = build_graph(
            engine,
            domains,
            checkpointer=checkpointer,
            client=default_client,
            pattern_store=pattern_store,
        )

        app.state.graph = graph
        app.state.pool = pool
        app.state.pattern_store = pattern_store

        yield

    await pattern_store.close()
    await pool.close_all()

    logger.info("Shutting down Flowise Dev Agent")
    await client.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


_rate_limit = os.getenv("RATE_LIMIT_SESSIONS_PER_MIN", "10")
limiter = Limiter(key_func=get_remote_address, default_limits=[f"{_rate_limit}/minute"])

app = FastAPI(
    title="Flowise Development Agent API",
    description=(
        "Co-development agent for building Flowise chatflows. "
        "Wraps the Flowise Builder Orchestrator loop (discover → plan → patch → test → converge) "
        "as a conversational HTTP API with human-in-the-loop review at key checkpoints."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class StartSessionRequest(BaseModel):
    """Request body for POST /sessions."""

    requirement: str = Field(
        ...,
        description="What the developer wants to build or change in Flowise.",
        examples=["Build a customer support chatbot with memory that uses GPT-4o"],
    )
    thread_id: str | None = Field(
        None,
        description=(
            "Optional session ID. If not provided, a UUID is generated. "
            "Store this ID to resume the session later."
        ),
    )
    test_trials: int = Field(
        1,
        ge=1,
        le=5,
        description=(
            "Number of times to run each test case (happy-path and edge case). "
            "1 = pass@1 (default, fastest). 2+ = pass^k reliability testing — "
            "all k trials must pass for a test to count as PASS. "
            "Higher values give more confidence before the DONE signal."
        ),
    )
    flowise_instance_id: str | None = Field(
        None,
        description=(
            "Target Flowise instance ID from FLOWISE_INSTANCES config. "
            "Leave empty to use the default instance. "
            "See DESIGN_DECISIONS.md — DD-032."
        ),
    )


class ResumeSessionRequest(BaseModel):
    """Request body for POST /sessions/{thread_id}/resume."""

    response: str = Field(
        ...,
        description=(
            "Developer's reply to the current interrupt. "
            "For plan_approval: 'approved' to proceed, or describe what to change. "
            "For result_review: 'accepted' to finish, or describe what to iterate."
        ),
        examples=["approved", "Change the model to claude-sonnet-4-6 instead of gpt-4o"],
    )


class InterruptPayload(BaseModel):
    """Data surfaced to the developer at a human-in-the-loop interrupt point."""

    type: str = Field(
        ...,
        description=(
            "'clarification': requirement is ambiguous — answer the questions then the session continues. "
            "'credential_check': required credentials are missing — create them in Flowise "
            "then reply with the credential ID(s). "
            "'plan_approval': review and approve or revise the structured plan. "
            "'result_review': review test results and accept or request another iteration."
        ),
    )
    prompt: str = Field(..., description="Instructions for the developer on how to respond.")
    plan: str | None = Field(None, description="The structured plan (present on plan_approval).")
    test_results: str | None = Field(None, description="Test output (present on result_review).")
    chatflow_id: str | None = Field(None, description="Chatflow being worked on (if known).")
    iteration: int = Field(0, description="Which iteration this is (0-indexed).")
    missing_credentials: list[str] | None = Field(
        None,
        description=(
            "Credential types required but not found in Flowise (present on credential_check). "
            "Example: ['openAIApi', 'anthropicApi']. "
            "Create these in Flowise (Settings → Credentials → Add New), "
            "then reply with the credential ID(s)."
        ),
    )


class SessionSummary(BaseModel):
    """Lightweight session entry returned by GET /sessions."""

    thread_id: str = Field(..., description="Session identifier.")
    status: str = Field(..., description="'pending_interrupt', 'completed', or 'in_progress'.")
    iteration: int = Field(0, description="Current iteration count.")
    chatflow_id: str | None = Field(None, description="The Flowise chatflow ID being built.")
    total_input_tokens: int = Field(0, description="Cumulative LLM prompt tokens used this session.")
    total_output_tokens: int = Field(0, description="Cumulative LLM completion tokens used this session.")


class SessionResponse(BaseModel):
    """Response for all session endpoints."""

    thread_id: str = Field(..., description="Session identifier. Store this to resume later.")
    status: Literal["pending_interrupt", "completed", "error"] = Field(
        ...,
        description=(
            "pending_interrupt: graph is paused waiting for developer input. "
            "completed: Definition of Done met and developer accepted. "
            "error: an unhandled error occurred."
        ),
    )
    iteration: int = Field(0, description="Current iteration count.")
    chatflow_id: str | None = Field(None, description="The Flowise chatflow ID being built.")
    interrupt: InterruptPayload | None = Field(
        None,
        description="Present when status is 'pending_interrupt'. Contains data for the developer.",
    )
    message: str | None = Field(
        None,
        description="Human-readable summary. Present on completion or error.",
    )
    total_input_tokens: int = Field(0, description="Cumulative LLM prompt tokens used this session.")
    total_output_tokens: int = Field(0, description="Cumulative LLM completion tokens used this session.")


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


def _get_graph(request: Request):
    return request.app.state.graph


def _get_client(request: Request, instance_id: str | None = None):
    """Resolve a FlowiseClient from the pool for the given instance_id."""
    pool = request.app.state.pool
    try:
        return pool.get(instance_id)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_response(graph, config: dict, thread_id: str) -> SessionResponse:
    """Inspect the graph state and build a SessionResponse.

    Checks for pending interrupts first. If none, the graph is complete.
    """
    try:
        snapshot = graph.get_state(config)
    except Exception as e:
        logger.error("Failed to get graph state for thread %s: %s", thread_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to read session state: {e}")

    state = snapshot.values

    # Collect all pending interrupts from all tasks
    pending_interrupts: list[dict] = []
    for task in snapshot.tasks:
        for intr in getattr(task, "interrupts", []):
            pending_interrupts.append(intr.value)

    in_tok = state.get("total_input_tokens", 0) or 0
    out_tok = state.get("total_output_tokens", 0) or 0

    if pending_interrupts:
        raw = pending_interrupts[0]
        interrupt = InterruptPayload(
            type=raw.get("type", "unknown"),
            prompt=raw.get("prompt", ""),
            plan=raw.get("plan"),
            test_results=raw.get("test_results"),
            chatflow_id=raw.get("chatflow_id") or state.get("chatflow_id"),
            iteration=raw.get("iteration", state.get("iteration", 0)),
            missing_credentials=raw.get("missing_credentials"),
        )
        return SessionResponse(
            thread_id=thread_id,
            status="pending_interrupt",
            iteration=state.get("iteration", 0),
            chatflow_id=state.get("chatflow_id"),
            interrupt=interrupt,
            total_input_tokens=in_tok,
            total_output_tokens=out_tok,
        )

    # No interrupts — graph finished
    if not snapshot.next:
        return SessionResponse(
            thread_id=thread_id,
            status="completed",
            iteration=state.get("iteration", 0),
            chatflow_id=state.get("chatflow_id"),
            message=(
                f"Chatflow '{state.get('chatflow_id')}' built successfully. "
                f"Definition of Done met after {state.get('iteration', 0)} iteration(s)."
            ),
            total_input_tokens=in_tok,
            total_output_tokens=out_tok,
        )

    # Unexpected: graph is still mid-run after ainvoke returned
    logger.warning("Graph for thread %s returned without interrupt or completion", thread_id)
    return SessionResponse(
        thread_id=thread_id,
        status="pending_interrupt",
        iteration=state.get("iteration", 0),
        chatflow_id=state.get("chatflow_id"),
        message="Graph is mid-execution — retry the request.",
        total_input_tokens=in_tok,
        total_output_tokens=out_tok,
    )


def _initial_state(
    requirement: str,
    test_trials: int = 1,
    flowise_instance_id: str | None = None,
) -> dict:
    """Build the initial AgentState dict for a new session."""
    return {
        "requirement": requirement,
        "messages": [],
        "chatflow_id": None,
        "discovery_summary": None,
        "plan": None,
        "test_results": None,
        "iteration": 0,
        "done": False,
        "developer_feedback": None,
        "clarification": None,
        "credentials_missing": None,
        "converge_verdict": None,
        "test_trials": test_trials,
        "flowise_instance_id": flowise_instance_id,
        "domain_context": {},
        "total_input_tokens": 0,
        "total_output_tokens": 0,
    }


# ---------------------------------------------------------------------------
# SSE helpers (used by streaming endpoints)
# ---------------------------------------------------------------------------


def _sse_from_event(event: dict) -> str | None:
    """Convert a LangGraph astream_events v2 event to an SSE data line, or None to skip."""
    kind = event.get("event")
    data = event.get("data", {})

    if kind == "on_chat_model_stream":
        chunk = data.get("chunk")
        if chunk is None:
            return None
        content = getattr(chunk, "content", "") or ""
        # Anthropic returns a list of content blocks; flatten to text
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in content
            )
        if content:
            return f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"

    elif kind == "on_tool_start":
        return f"data: {json.dumps({'type': 'tool_call', 'name': event.get('name', '')})}\n\n"

    elif kind == "on_tool_end":
        output = str(data.get("output", ""))[:200]
        return f"data: {json.dumps({'type': 'tool_result', 'name': event.get('name', ''), 'preview': output}, default=str)}\n\n"

    return None


def _sse_final(snapshot, thread_id: str) -> str:
    """Build the terminal SSE event (interrupt or done) from a post-stream state snapshot."""
    pending: list[dict] = []
    for task in snapshot.tasks:
        for intr in getattr(task, "interrupts", []):
            pending.append(intr.value)
    if pending:
        return f"data: {json.dumps({'type': 'interrupt', **pending[0]}, default=str)}\n\n"
    return f"data: {json.dumps({'type': 'done', 'thread_id': thread_id})}\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/instances", tags=["system"], dependencies=[Depends(_verify_api_key)])
async def list_instances(request: Request) -> dict:
    """List registered Flowise instance IDs from the client pool.

    Useful for confirming which instance IDs are valid before starting a session
    with a specific flowise_instance_id.

    See DESIGN_DECISIONS.md — DD-032.
    """
    pool = request.app.state.pool
    return {
        "default": pool.default_id,
        "instances": pool.instance_ids,
    }


@app.get("/health", tags=["system"], dependencies=[Depends(_verify_api_key)])
async def health(request: Request) -> dict:
    """Health check. Verifies the API and Flowise connection are both up."""
    client = request.app.state.client
    try:
        result = await client.ping()
        flowise_ok = "error" not in result
    except Exception as e:
        flowise_ok = False
        result = {"error": str(e)}

    return {
        "api": "ok",
        "flowise": "ok" if flowise_ok else "unreachable",
        "flowise_detail": result,
    }


@app.post("/sessions", response_model=SessionResponse, tags=["sessions"], dependencies=[Depends(_verify_api_key)])
@limiter.limit(f"{os.getenv('RATE_LIMIT_SESSIONS_PER_MIN', '10')}/minute")
async def create_session(request: Request, body: StartSessionRequest) -> SessionResponse:
    """Start a new co-development session.

    Runs the Discover + Plan phases, then pauses at the first human checkpoint
    (plan_approval). The developer reviews the plan and calls /sessions/{id}/resume
    to proceed or request changes.

    Returns a thread_id that must be stored to resume the session.
    """
    graph = _get_graph(request)
    thread_id = body.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    logger.info("Creating session %s: %r", thread_id, body.requirement[:80])

    try:
        await graph.ainvoke(
            _initial_state(body.requirement, body.test_trials, body.flowise_instance_id),
            config=config,
        )
    except Exception as e:
        logger.exception("Session %s failed during initial run", thread_id)
        raise HTTPException(status_code=500, detail=str(e))

    return _build_response(graph, config, thread_id)


@app.post("/sessions/{thread_id}/resume", response_model=SessionResponse, tags=["sessions"], dependencies=[Depends(_verify_api_key)])
async def resume_session(
    thread_id: str,
    body: ResumeSessionRequest,
    request: Request,
) -> SessionResponse:
    """Resume a paused session with the developer's response.

    Called after receiving a 'pending_interrupt' status. The response field
    carries the developer's input:
      - For plan_approval: 'approved' or feedback on what to change
      - For result_review: 'accepted' or feedback for another iteration

    The graph continues until the next interrupt or completion.
    """
    from langgraph.types import Command

    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    # Verify the session exists before resuming
    try:
        snapshot = graph.get_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found.")

    if not snapshot.tasks and not snapshot.next:
        raise HTTPException(
            status_code=409,
            detail=f"Session '{thread_id}' is already completed. Start a new session.",
        )

    logger.info("Resuming session %s with response: %r", thread_id, body.response[:80])

    try:
        await graph.ainvoke(Command(resume=body.response), config=config)
    except Exception as e:
        logger.exception("Session %s failed on resume", thread_id)
        raise HTTPException(status_code=500, detail=str(e))

    return _build_response(graph, config, thread_id)


@app.get("/sessions/{thread_id}", response_model=SessionResponse, tags=["sessions"], dependencies=[Depends(_verify_api_key)])
async def get_session(thread_id: str, request: Request) -> SessionResponse:
    """Get the current state of a session without advancing it.

    Useful for checking session status after a timeout or reconnecting
    to an in-progress session.
    """
    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        graph.get_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found.")

    return _build_response(graph, config, thread_id)


@app.get("/sessions/{thread_id}/summary", tags=["sessions"], dependencies=[Depends(_verify_api_key)])
async def get_session_summary(thread_id: str, request: Request) -> dict:
    """Return a human-readable markdown summary of a session (DD-034).

    Formats existing AgentState fields into a markdown document suitable
    for team handoffs, compliance audits, and debugging. No new state is
    created — this is a pure read-only formatting operation.
    """
    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        snapshot = graph.get_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found.")

    s = snapshot.values
    lines = [
        f"# Session `{thread_id}`",
        f"",
        f"**Requirement**: {s.get('requirement', '—')}",
        f"**Chatflow**: `{s.get('chatflow_id') or '(not yet created)'}`",
        f"**Status**: {'completed' if s.get('done') else 'in progress'}",
        f"**Iterations**: {s.get('iteration', 0)}",
        f"**Tokens**: {s.get('total_input_tokens', 0):,} in / {s.get('total_output_tokens', 0):,} out",
        f"",
    ]
    if s.get("clarification"):
        lines += ["## Clarifications", "", s["clarification"], ""]
    if s.get("plan"):
        lines += ["## Approved Plan", "", s["plan"], ""]
    if s.get("discovery_summary"):
        lines += ["## Discovery Summary", "", s["discovery_summary"], ""]
    if s.get("test_results"):
        lines += ["## Test Results", "", s["test_results"], ""]

    return {"thread_id": thread_id, "summary": "\n".join(lines)}


@app.get("/sessions", response_model=list[SessionSummary], tags=["sessions"], dependencies=[Depends(_verify_api_key)])
async def list_sessions(request: Request) -> list[SessionSummary]:
    """List all sessions stored in the checkpoint database.

    Returns a lightweight summary per session. Token totals and chatflow_id
    are read from the latest checkpoint state for each thread.

    See DESIGN_DECISIONS.md — DD-030.
    """
    graph = _get_graph(request)
    checkpointer = graph.checkpointer

    # Fetch all distinct thread IDs directly from SQLite
    async with checkpointer.conn.execute(
        "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
    ) as cur:
        thread_ids: list[str] = [row[0] async for row in cur]

    summaries: list[SessionSummary] = []
    for tid in thread_ids:
        try:
            cfg = {"configurable": {"thread_id": tid}}
            snap = await graph.aget_state(cfg)
            sv = snap.values

            # Determine status
            has_interrupts = any(
                getattr(task, "interrupts", []) for task in snap.tasks
            )
            if has_interrupts:
                status = "pending_interrupt"
            elif sv.get("done") or not snap.next:
                status = "completed"
            else:
                status = "in_progress"

            summaries.append(SessionSummary(
                thread_id=tid,
                status=status,
                iteration=sv.get("iteration", 0),
                chatflow_id=sv.get("chatflow_id"),
                total_input_tokens=sv.get("total_input_tokens", 0) or 0,
                total_output_tokens=sv.get("total_output_tokens", 0) or 0,
            ))
        except Exception as e:
            logger.warning("Could not read state for thread %s: %s", tid, e)
            summaries.append(SessionSummary(thread_id=tid, status="error"))

    return summaries


@app.delete("/sessions/{thread_id}", tags=["sessions"], dependencies=[Depends(_verify_api_key)])
async def delete_session(thread_id: str, request: Request) -> dict:
    """Delete a session and all its checkpoint data from the database.

    Permanently removes the thread's checkpoints and write logs from SQLite.
    This action is irreversible.

    See DESIGN_DECISIONS.md — DD-030.
    """
    graph = _get_graph(request)
    checkpointer = graph.checkpointer

    # Verify the thread exists before deleting
    async with checkpointer.conn.execute(
        "SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1", (thread_id,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found.")

    await checkpointer.adelete_thread(thread_id)
    logger.info("Deleted session %s", thread_id)
    return {"deleted": True, "thread_id": thread_id}


@app.post("/sessions/{thread_id}/rollback", response_model=SessionResponse, tags=["sessions"], dependencies=[Depends(_verify_api_key)])
async def rollback_session(thread_id: str, request: Request) -> SessionResponse:
    """Rollback the chatflow to the last snapshot taken during this session.

    Calls rollback_chatflow on the snapshot saved most recently by the agent's
    snapshot_chatflow tool call. Requires at least one patch to have run.

    See DESIGN_DECISIONS.md — DD-026.
    """
    from flowise_dev_agent.agent.tools import rollback_session_chatflow

    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        snapshot = graph.get_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found.")

    chatflow_id = snapshot.values.get("chatflow_id")
    if not chatflow_id:
        raise HTTPException(
            status_code=409,
            detail="No chatflow_id in session state — nothing to rollback.",
        )

    instance_id = snapshot.values.get("flowise_instance_id")
    client = _get_client(request, instance_id)

    logger.info("Rolling back chatflow %s for session %s", chatflow_id, thread_id)
    result = await rollback_session_chatflow(client, chatflow_id, thread_id)
    if "error" in result:
        raise HTTPException(status_code=409, detail=result["error"])

    return _build_response(graph, config, thread_id)


@app.get("/patterns", tags=["patterns"], dependencies=[Depends(_verify_api_key)])
async def list_patterns(request: Request, q: str | None = None) -> list[dict]:
    """List or search the pattern library.

    Optionally pass ?q=keywords to search for patterns matching the keywords.
    Without a query, returns the 20 most recently saved patterns.

    See DESIGN_DECISIONS.md — DD-031.
    """
    store = getattr(request.app.state, "pattern_store", None)
    if store is None:
        return []
    if q:
        return await store.search_patterns(q)
    return await store.list_patterns()


@app.post("/sessions/stream", tags=["sessions"], dependencies=[Depends(_verify_api_key)])
@limiter.limit(f"{os.getenv('RATE_LIMIT_SESSIONS_PER_MIN', '10')}/minute")
async def stream_create_session(request: Request, body: StartSessionRequest) -> StreamingResponse:
    """Start a new session and stream progress as Server-Sent Events.

    Identical to POST /sessions but returns a streaming response instead of
    blocking until the first interrupt. Events are emitted as the graph runs:

      data: {"type": "token",       "content": "..."}         ← LLM output token
      data: {"type": "tool_call",   "name": "..."}            ← tool being invoked
      data: {"type": "tool_result", "name": "...", "preview": "..."}
      data: {"type": "interrupt",   "type": "plan_approval", ...}  ← HITL pause
      data: {"type": "done",        "thread_id": "..."}       ← session complete
      data: {"type": "error",       "detail": "..."}          ← unhandled exception

    See DESIGN_DECISIONS.md — DD-025.
    """
    graph = _get_graph(request)
    thread_id = body.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    logger.info("Streaming new session %s: %r", thread_id, body.requirement[:80])

    async def event_stream():
        try:
            async for event in graph.astream_events(
                _initial_state(body.requirement, body.test_trials, body.flowise_instance_id),
                config=config,
                version="v2",
            ):
                sse = _sse_from_event(event)
                if sse:
                    yield sse
            snapshot = await graph.aget_state(config)
            yield _sse_final(snapshot, thread_id)
        except Exception as e:
            logger.exception("SSE stream failed for new session %s", thread_id)
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/sessions/{thread_id}/stream", tags=["sessions"], dependencies=[Depends(_verify_api_key)])
async def stream_resume_session(
    thread_id: str,
    body: ResumeSessionRequest,
    request: Request,
) -> StreamingResponse:
    """Resume a paused session and stream progress as Server-Sent Events.

    Identical to POST /sessions/{thread_id}/resume but streams events live
    instead of blocking. The final event is always either 'interrupt' (another
    HITL pause) or 'done' (session complete).

    curl example:
      curl -N -X POST http://localhost:8000/sessions/<id>/stream \\
           -H "Content-Type: application/json" \\
           -d '{"response": "approved"}'

    See DESIGN_DECISIONS.md — DD-025.
    """
    from langgraph.types import Command

    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    logger.info("Streaming resume session %s: %r", thread_id, body.response[:80])

    async def event_stream():
        try:
            async for event in graph.astream_events(
                Command(resume=body.response),
                config=config,
                version="v2",
            ):
                sse = _sse_from_event(event)
                if sse:
                    yield sse
            snapshot = await graph.aget_state(config)
            yield _sse_final(snapshot, thread_id)
        except Exception as e:
            logger.exception("SSE stream failed for session %s", thread_id)
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Entry point (for uvicorn programmatic launch)
# ---------------------------------------------------------------------------


def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Launch the FastAPI server via uvicorn."""
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "flowise_dev_agent.api:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
