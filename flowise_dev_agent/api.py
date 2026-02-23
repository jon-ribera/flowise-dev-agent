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

import logging
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("flowise_dev_agent.api")


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

    from flowise_dev_agent.agent import create_agent
    from cursorwise.config import Settings
    from flowise_dev_agent.reasoning import ReasoningSettings

    settings = Settings.from_env()
    reasoning_settings = ReasoningSettings.from_env()

    logger.info(
        "Starting Flowise Dev Agent | Flowise: %s | Engine: %s",
        settings.api_endpoint,
        reasoning_settings.provider,
    )

    graph, client = create_agent(settings, reasoning_settings)
    app.state.graph = graph
    app.state.client = client

    yield

    logger.info("Shutting down Flowise Dev Agent")
    await client.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


def _get_graph(request: Request):
    return request.app.state.graph


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
        )

    # Unexpected: graph is still mid-run after ainvoke returned
    logger.warning("Graph for thread %s returned without interrupt or completion", thread_id)
    return SessionResponse(
        thread_id=thread_id,
        status="pending_interrupt",
        iteration=state.get("iteration", 0),
        chatflow_id=state.get("chatflow_id"),
        message="Graph is mid-execution — retry the request.",
    )


def _initial_state(requirement: str, test_trials: int = 1) -> dict:
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
        "credentials_missing": None,
        "converge_verdict": None,
        "test_trials": test_trials,
        "domain_context": {},
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health", tags=["system"])
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


@app.post("/sessions", response_model=SessionResponse, tags=["sessions"])
async def create_session(body: StartSessionRequest, request: Request) -> SessionResponse:
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
        await graph.ainvoke(_initial_state(body.requirement, body.test_trials), config=config)
    except Exception as e:
        logger.exception("Session %s failed during initial run", thread_id)
        raise HTTPException(status_code=500, detail=str(e))

    return _build_response(graph, config, thread_id)


@app.post("/sessions/{thread_id}/resume", response_model=SessionResponse, tags=["sessions"])
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


@app.get("/sessions/{thread_id}", response_model=SessionResponse, tags=["sessions"])
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
