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

import asyncio
import json
import logging
import os
import pathlib
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = logging.getLogger("flowise_dev_agent.api")

# ---------------------------------------------------------------------------
# Runtime mode (M7.1, DD-066)
# ---------------------------------------------------------------------------
# FLOWISE_COMPAT_LEGACY=1/true/yes → pass capabilities=None (pre-refactor behaviour).
# Unset or any other value         → capability-first default (DomainCapability path).
_COMPAT_LEGACY: bool = os.environ.get("FLOWISE_COMPAT_LEGACY", "").lower() in (
    "1", "true", "yes"
)

# ---------------------------------------------------------------------------
# Persistence config (M9.1, DD-078)
# ---------------------------------------------------------------------------
# POSTGRES_DSN must be set.  The agent will fail to start without it.
# Example: postgresql://postgres:postgres@localhost:5432/flowise_dev_agent
_POSTGRES_DSN: str | None = os.environ.get("POSTGRES_DSN")

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

    from flowise_dev_agent.agent.graph import build_graph, create_engine, make_default_capabilities
    from flowise_dev_agent.agent.tools import FloviseDomain
    from flowise_dev_agent.instance_pool import FlowiseClientPool
    from flowise_dev_agent.persistence import EventLog, make_checkpointer
    from flowise_dev_agent.reasoning import ReasoningSettings

    reasoning_settings = ReasoningSettings.from_env()

    # M9.1: Postgres DSN is required.  Fail fast with a clear message.
    postgres_dsn = _POSTGRES_DSN or os.getenv("POSTGRES_DSN")
    if not postgres_dsn:
        raise RuntimeError(
            "POSTGRES_DSN environment variable is not set. "
            "Start a local Postgres instance with:\n"
            "  docker compose -f docker-compose.postgres.yml up -d\n"
            "Then set:\n"
            "  POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/flowise_dev_agent"
        )

    langsmith_key = os.getenv("LANGCHAIN_API_KEY")
    if langsmith_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "flowise-dev-agent")
        logger.info("LangSmith tracing enabled: project=%s", os.environ["LANGCHAIN_PROJECT"])

    logger.info(
        "Starting Flowise Dev Agent | Flowise: %s | Engine: %s | Persistence: postgres",
        os.getenv("FLOWISE_API_ENDPOINT", "(from env)"),
        reasoning_settings.provider,
    )

    from flowise_dev_agent.agent.pattern_store import PatternStore

    pattern_db_path = os.getenv("PATTERN_DB_PATH", "sessions.db")

    pool = FlowiseClientPool.from_env()
    default_client = pool.get(None)  # default instance for pattern save + graph wiring

    # M9.1: EventLog shares the same Postgres DSN; owns its own connection.
    event_log = EventLog(dsn=postgres_dsn)
    await event_log.setup()

    async with make_checkpointer(postgres_dsn) as checkpointer:
        engine = create_engine(reasoning_settings)
        domains = [FloviseDomain(default_client)]
        pattern_store = await PatternStore.open(pattern_db_path)

        # M7.1 (DD-066): capability-first is the default; compat_legacy only when opted in.
        _capabilities = None if _COMPAT_LEGACY else make_default_capabilities(engine, domains)
        _runtime_mode = "compat_legacy" if _COMPAT_LEGACY else "capability_first"
        logger.info("Runtime mode: %s (FLOWISE_COMPAT_LEGACY=%s)", _runtime_mode, _COMPAT_LEGACY)

        graph = build_graph(
            engine,
            domains,
            checkpointer=checkpointer,
            client=default_client,
            pattern_store=pattern_store,
            capabilities=_capabilities,
            emit_event=event_log.insert_event,  # M9.2: node lifecycle → session_events
        )
        app.state.runtime_mode = _runtime_mode

        app.state.graph = graph
        app.state.pool = pool
        app.state.pattern_store = pattern_store
        app.state.engine = engine
        app.state.event_log = event_log  # M9.1: available to all endpoints

        yield

    await pattern_store.close()
    await pool.close_all()
    await event_log.close()

    logger.info("Shutting down Flowise Dev Agent")


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

from fastapi.middleware.cors import CORSMiddleware

_CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3001,http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    flowise_instance_id: str | None = Field(
        None,
        description=(
            "Target Flowise instance ID from FLOWISE_INSTANCES config. "
            "Leave empty to use the default instance. "
            "See DESIGN_DECISIONS.md — DD-032."
        ),
    )
    webhook_url: str | None = Field(
        None,
        description=(
            "Optional HTTPS URL to POST interrupt payloads to (DD-037). "
            "Called when clarification, credential_check, plan_approval, or "
            "result_review interrupts fire. Retried up to 3 times on failure."
        ),
    )


class ResumeSessionRequest(BaseModel):
    """Request body for POST /sessions/{thread_id}/resume."""

    response: str = Field(
        ...,
        description=(
            "Developer's reply to the current interrupt. "
            "For plan_approval: 'approved' to proceed, 'approved - approach: <label>' to select "
            "a specific approach, or describe what to change. "
            "For result_review: 'accepted' to finish, 'rollback' to revert, "
            "or describe what to iterate."
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
    options: list[str] | None = Field(
        None,
        description=(
            "Selectable approach labels extracted from the plan's ## APPROACHES section. "
            "Present only on plan_approval when the plan offers multiple implementation paths. "
            "Send 'approved - approach: <label>' to select one."
        ),
    )
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
    session_name: str | None = Field(None, description="Short display title generated at session creation.")
    runtime_mode: str | None = Field(None, description="'capability_first' or 'compat_legacy' — routing mode used for this session (M7.1).")
    total_repair_events: int = Field(0, description="Total schema/credential repair events this session (M7.4).")
    total_phases_timed: int = Field(0, description="Number of phases with captured timing data (M7.4).")
    knowledge_repair_count: int = Field(0, description="Node schema repairs triggered this session (M8.2).")
    get_node_calls_total: int = Field(0, description="Total get_node calls served from local cache this session (M8.2).")
    phase_durations_ms: dict[str, float] = Field(default_factory=dict, description="Per-phase wall-clock durations in ms (M8.2).")
    schema_fingerprint: str | None = Field(None, description="Current NodeSchemaStore snapshot fingerprint (M9.7).")
    drift_detected: bool = Field(False, description="True when schema fingerprint changed vs prior iteration (M9.7).")
    pattern_metrics: dict | None = Field(None, description="Pattern usage metrics from last patch iteration (M9.7).")
    updated_at: str | None = Field(None, description="ISO 8601 timestamp of last checkpoint update.")


class RenameSessionRequest(BaseModel):
    """Request body for PATCH /sessions/{thread_id}/name."""

    name: str = Field(..., max_length=120, description="New display name for the session.")


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


async def _build_response(graph, config: dict, thread_id: str) -> SessionResponse:
    """Inspect the graph state and build a SessionResponse.

    Checks for pending interrupts first. If none, the graph is complete.
    Uses aget_state (async) because the checkpointer is Postgres-backed (M9.1).
    """
    try:
        snapshot = await graph.aget_state(config)
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
            options=raw.get("options"),
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


async def _generate_session_name(requirement: str, engine) -> str:
    """Generate a concise 4–6 word display title from the session requirement.

    Makes a single low-cost LLM call. Falls back to the first 60 chars of the
    requirement if the call fails or returns empty output. See DD-061.
    """
    from flowise_dev_agent.reasoning import Message as _Msg

    try:
        messages = [
            _Msg(
                role="user",
                content=(
                    "Generate a concise 4–6 word title for this task. "
                    "No quotes, no punctuation at the end, no markdown:\n"
                    f"{requirement[:300]}"
                ),
            )
        ]
        response = await engine.complete(messages, temperature=0.3)
        title = (response.content or "").strip()
        if title:
            return title[:80]
    except Exception:
        pass
    # Fallback: first 60 chars
    short = requirement[:60].rstrip()
    return short + ("\u2026" if len(requirement) > 60 else "")


def _initial_state(
    requirement: str,
    test_trials: int = 1,
    flowise_instance_id: str | None = None,
    webhook_url: str | None = None,
    session_name: str | None = None,
    runtime_mode: str | None = None,
) -> dict:
    """Build the initial AgentState dict for a new session."""
    return {
        "requirement": requirement,
        "session_name": session_name,
        "runtime_mode": runtime_mode,
        "messages": [],
        "chatflow_id": None,
        "discovery_summary": None,
        "plan": None,
        "test_results": None,
        "iteration": 0,
        "done": False,
        "developer_feedback": None,
        "webhook_url": webhook_url,
        "clarification": None,
        "credentials_missing": None,
        "converge_verdict": None,
        "test_trials": test_trials,
        "flowise_instance_id": flowise_instance_id,
        "domain_context": {},
        "artifacts": {},
        "facts": {},
        "debug": {},
        "patch_ir": None,
        "validated_payload_hash": None,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        # M9.6 — Topology v2 fields
        "operation_mode": None,
        "target_chatflow_id": None,
        "intent_confidence": None,
        # M9.9 — Pattern library fields
        "pattern_used": False,
        "pattern_id": None,
    }


# ---------------------------------------------------------------------------
# SSE helpers (used by streaming endpoints)
# ---------------------------------------------------------------------------


_NODE_PROGRESS: dict[str, str] = {
    # M9.6 v2 topology nodes
    "classify_intent":          "\n--- Classifying intent (create vs update) ---\n",
    "hydrate_context":          "\n--- Loading local schema metadata ---\n",
    "resolve_target":           "\n--- Resolving update target chatflow ---\n",
    "hitl_select_target":       "\n--- [INTERRUPT] Select target chatflow ---\n",
    "load_current_flow":        "\n--- Loading current chatflow data ---\n",
    "summarize_current_flow":   "\n--- Summarizing current flow structure ---\n",
    "plan_v2":                  "\n--- Planning chatflow architecture ---\n",
    "hitl_plan_v2":             "\n--- [INTERRUPT] Plan approval ---\n",
    "define_patch_scope":       "\n--- Defining patch scope and budgets ---\n",
    "compile_patch_ir":         "\n--- Generating Patch IR operations ---\n",
    "compile_flow_data":        "\n--- Compiling flow data (deterministic) ---\n",
    "validate":                 "\n--- Validating compiled flow ---\n",
    "repair_schema":            "\n--- Repairing missing node schemas ---\n",
    "preflight_validate_patch": "\n--- Pre-flight budget check ---\n",
    "apply_patch":              "\n--- Applying patch to Flowise ---\n",
    "test_v2":                  "\n--- Running test cases ---\n",
    "evaluate":                 "\n--- Evaluating patch result ---\n",
    "hitl_review_v2":           "\n--- [INTERRUPT] Review changes ---\n",
}


def _sse_from_event(event: dict) -> str | None:
    """Convert a LangGraph astream_events v2 event to an SSE data line, or None to skip.

    The custom ReasoningEngine bypasses LangChain's ChatModel layer, so
    on_chat_model_stream events are never emitted.  We instead surface
    on_chain_start events for named graph nodes as phase-progress tokens
    so the developer sees live feedback while the graph runs.
    """
    kind = event.get("event")
    data = event.get("data", {})

    if kind == "on_chat_model_stream":
        # Fires only when a LangChain ChatModel is used directly (future proofing).
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

    elif kind == "on_chain_start":
        # Emit a progress line whenever a named graph node starts executing.
        node = event.get("metadata", {}).get("langgraph_node", "")
        label = _NODE_PROGRESS.get(node)
        if label:
            return f"data: {json.dumps({'type': 'token', 'content': label})}\n\n"

    elif kind == "on_chain_stream":
        # Custom events emitted by execute_tool() via get_stream_writer() appear here
        # when astream_events is called with stream_mode="custom".
        # chunk is the exact dict passed to the stream writer.
        chunk = data.get("chunk", {})
        if isinstance(chunk, dict):
            ev_type = chunk.get("type")
            if ev_type == "tool_call":
                return f"data: {json.dumps({'type': 'tool_call', 'name': chunk.get('name', '')})}\n\n"
            if ev_type == "tool_result":
                return f"data: {json.dumps({'type': 'tool_result', 'name': chunk.get('name', ''), 'preview': chunk.get('preview', '')})}\n\n"

    elif kind == "on_tool_start":
        # Fires only for LangChain Tool objects (future proofing)
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
    client = _get_client(request)
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
    engine = request.app.state.engine
    thread_id = body.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    logger.info("Creating session %s: %r", thread_id, body.requirement[:80])

    session_name = await _generate_session_name(body.requirement, engine)

    try:
        await graph.ainvoke(
            _initial_state(
                body.requirement,
                body.test_trials,
                body.flowise_instance_id,
                body.webhook_url,
                session_name,
                runtime_mode=getattr(request.app.state, "runtime_mode", None),
            ),
            config=config,
        )
    except Exception as e:
        logger.exception("Session %s failed during initial run", thread_id)
        raise HTTPException(status_code=500, detail=str(e))

    return await _build_response(graph, config, thread_id)


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
        snapshot = await graph.aget_state(config)
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

    return await _build_response(graph, config, thread_id)


@app.get("/sessions/{thread_id}", response_model=SessionResponse, tags=["sessions"], dependencies=[Depends(_verify_api_key)])
async def get_session(thread_id: str, request: Request) -> SessionResponse:
    """Get the current state of a session without advancing it.

    Useful for checking session status after a timeout or reconnecting
    to an in-progress session.
    """
    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        await graph.aget_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found.")

    return await _build_response(graph, config, thread_id)


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
        snapshot = await graph.aget_state(config)
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
async def list_sessions(
    request: Request,
    limit: int | None = None,
    sort: str = "desc",
) -> list[SessionSummary]:
    """List all sessions stored in the checkpoint database.

    Returns a lightweight summary per session. Token totals and chatflow_id
    are read from the latest checkpoint state for each thread.

    See DESIGN_DECISIONS.md — DD-030.
    """
    graph = _get_graph(request)
    checkpointer = graph.checkpointer

    # M9.1: use adapter helper — works with Postgres (and any future backend).
    thread_ids: list[str] = await checkpointer.list_thread_ids()

    summaries: list[SessionSummary] = []
    for tid in thread_ids:
        try:
            cfg = {"configurable": {"thread_id": tid}}
            snap = await graph.aget_state(cfg)
            sv = snap.values

            _updated_at: str | None = None
            try:
                _updated_at = snap.metadata.get("created_at") if snap.metadata else None
            except Exception:
                pass

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

            # M7.4 / M8.2: extract phase_metrics telemetry from debug state
            _flowise_debug: dict = (sv.get("debug") or {}).get("flowise", {}) or {}
            _phase_metrics: list = _flowise_debug.get("phase_metrics") or []
            _repair_events = sum(
                m.get("repair_events", 0)
                for m in _phase_metrics
                if isinstance(m, dict)
            )
            # M8.2: knowledge_repair_count from explicit repair events list length
            _kr_events: list = _flowise_debug.get("knowledge_repair_events") or []
            _knowledge_repair_count = len(_kr_events)
            # M8.2: get_node_calls_total accumulated across all patch iterations
            _get_node_calls: int = _flowise_debug.get("get_node_calls_total", 0) or 0
            # M8.2: phase_durations_ms — map phase name to duration for each timed phase.
            # When the same phase name appears in multiple iterations the last one wins,
            # consistent with the single-dict shape.
            _phase_durations: dict[str, float] = {
                m["phase"]: m.get("duration_ms", 0.0)
                for m in _phase_metrics
                if isinstance(m, dict) and "phase" in m
            }
            # M9.7: schema_fingerprint + drift_detected
            _flowise_facts: dict = (sv.get("facts") or {}).get("flowise", {}) or {}
            _schema_fp: str | None = _flowise_facts.get("schema_fingerprint")
            _prior_fp: str | None = _flowise_facts.get("prior_schema_fingerprint")
            _drift_detected: bool = bool(
                _schema_fp and _prior_fp and _schema_fp != _prior_fp
            )
            # M9.7: pattern_metrics from debug["flowise"]["pattern_metrics"]
            _pattern_metrics: dict | None = _flowise_debug.get("pattern_metrics") or None
            summaries.append(SessionSummary(
                thread_id=tid,
                status=status,
                iteration=sv.get("iteration", 0),
                chatflow_id=sv.get("chatflow_id"),
                total_input_tokens=sv.get("total_input_tokens", 0) or 0,
                total_output_tokens=sv.get("total_output_tokens", 0) or 0,
                session_name=sv.get("session_name"),
                runtime_mode=sv.get("runtime_mode"),
                total_repair_events=_repair_events,
                total_phases_timed=len(_phase_metrics),
                knowledge_repair_count=_knowledge_repair_count,
                get_node_calls_total=_get_node_calls,
                phase_durations_ms=_phase_durations,
                schema_fingerprint=_schema_fp,
                drift_detected=_drift_detected,
                pattern_metrics=_pattern_metrics,
                updated_at=_updated_at,
            ))
        except Exception as e:
            logger.warning("Could not read state for thread %s: %s", tid, e)
            summaries.append(SessionSummary(thread_id=tid, status="error"))

    # Default: newest-first (reverse insertion order from checkpointer)
    if sort != "asc":
        summaries.reverse()
    if limit is not None and limit > 0:
        summaries = summaries[:limit]
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

    # M9.1: use adapter helper — works with Postgres (and any future backend).
    if not await checkpointer.thread_exists(thread_id):
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found.")

    await checkpointer.adelete_thread(thread_id)
    logger.info("Deleted session %s", thread_id)
    return {"deleted": True, "thread_id": thread_id}


@app.patch("/sessions/{thread_id}/name", tags=["sessions"], dependencies=[Depends(_verify_api_key)])
async def rename_session(thread_id: str, body: RenameSessionRequest, request: Request) -> dict:
    """Update the display name of a session (DD-061).

    Stores the new name in the session's checkpointed state so it persists
    across page refreshes. The name is shown in the sidebar instead of the
    raw thread UUID.
    """
    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    # Verify session exists
    try:
        snap = await graph.aget_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found.")
    if not snap.values:
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found.")

    await graph.aupdate_state(config, {"session_name": body.name})
    logger.info("Renamed session %s → %r", thread_id, body.name)
    return {"thread_id": thread_id, "session_name": body.name}


@app.get("/sessions/{thread_id}/versions", tags=["sessions"], dependencies=[Depends(_verify_api_key)])
async def list_session_versions(thread_id: str, request: Request) -> dict:
    """List all chatflow version snapshots taken during this session (DD-039).

    Returns snapshot metadata (chatflow_id, name, version_label, timestamp)
    without the bulky flowData payload.  Use the version_label from this list
    with POST /sessions/{id}/rollback?version=<label> to restore a specific version.

    Snapshots are ordered oldest-first (append order).
    """
    from flowise_dev_agent.agent.tools import list_session_snapshots

    versions = list_session_snapshots(thread_id)
    return {"thread_id": thread_id, "versions": versions, "count": len(versions)}


@app.post("/sessions/{thread_id}/rollback", response_model=SessionResponse, tags=["sessions"], dependencies=[Depends(_verify_api_key)])
async def rollback_session(
    thread_id: str,
    request: Request,
    version: str | None = None,
) -> SessionResponse:
    """Rollback the chatflow to a specific (or the latest) snapshot (DD-039).

    Pass ?version=<label> (e.g. ?version=v2.0) to restore a named snapshot.
    Omit the query parameter to roll back to the most recent snapshot.

    Use GET /sessions/{id}/versions to see available version labels.

    See DESIGN_DECISIONS.md — DD-026, DD-039.
    """
    from flowise_dev_agent.agent.tools import rollback_session_chatflow

    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        snapshot = await graph.aget_state(config)
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

    logger.info(
        "Rolling back chatflow %s for session %s (version=%s)",
        chatflow_id, thread_id, version or "latest",
    )
    result = await rollback_session_chatflow(client, chatflow_id, thread_id, version)
    if "error" in result:
        raise HTTPException(status_code=409, detail=result["error"])

    return await _build_response(graph, config, thread_id)


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
    engine = request.app.state.engine
    thread_id = body.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    logger.info("Streaming new session %s: %r", thread_id, body.requirement[:80])

    session_name = await _generate_session_name(body.requirement, engine)

    async def event_stream():
        yield ": connected\n\n"  # flush immediately so the browser sees open connection
        try:
            async for event in graph.astream_events(
                _initial_state(body.requirement, body.test_trials, body.flowise_instance_id, body.webhook_url, session_name),
                config=config,
                version="v2",
                stream_mode="custom",
            ):
                sse = _sse_from_event(event)
                if sse:
                    yield sse
            snapshot = await graph.aget_state(config)
            yield _sse_final(snapshot, thread_id)
        except Exception as e:
            logger.exception("SSE stream failed for new session %s", thread_id)
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        yield ": connected\n\n"  # flush immediately so the browser sees open connection
        try:
            async for event in graph.astream_events(
                Command(resume=body.response),
                config=config,
                version="v2",
                stream_mode="custom",
            ):
                sse = _sse_from_event(event)
                if sse:
                    yield sse
            snapshot = await graph.aget_state(config)
            yield _sse_final(snapshot, thread_id)
        except Exception as e:
            logger.exception("SSE stream failed for session %s", thread_id)
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# M9.2 — Node-level event SSE endpoint helpers
# ---------------------------------------------------------------------------

#: SSE event-type name for each status value stored in session_events.
_STATUS_TO_SSE_EVENT: dict[str, str] = {
    "started":     "node_start",
    "completed":   "node_end",
    "failed":      "node_error",
    "interrupted": "interrupt",
}

#: How often (in seconds) to poll the event log for new events.
_SSE_POLL_INTERVAL: float = float(os.environ.get("SSE_POLL_INTERVAL", "2"))

#: How many consecutive empty polls before emitting a keepalive comment.
_SSE_KEEPALIVE_AFTER: int = int(os.environ.get("SSE_KEEPALIVE_AFTER", "15"))


def _format_event_as_sse(event: dict, session_id: str) -> str:
    """Format one session_events row as an SSE message.

    SSE format (RFC 8725):
        event: <event_type>
        data: <json_payload>
        (blank line)

    payload_json is intentionally excluded to keep events small (no blobs).
    """
    status = event.get("status", "")
    event_type = _STATUS_TO_SSE_EVENT.get(status, "node_event")

    payload: dict = {
        "type":      event_type,
        "session_id": session_id,
        "node_name": event.get("node_name", ""),
        "phase":     event.get("phase", ""),
        "status":    status,
        "seq":       event.get("seq"),
    }
    if event.get("duration_ms") is not None:
        payload["duration_ms"] = event["duration_ms"]
    if event.get("summary"):
        payload["summary"] = event["summary"]
    ts = event.get("ts")
    if ts is not None:
        payload["ts"] = str(ts)

    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


async def _session_is_done(graph, session_id: str) -> bool:
    """Return True when the session has completed (done=True in state).

    Returns False for interrupted (HITL-paused) sessions because they are
    still active and may receive a resume call.  Returns False on error.
    """
    config = {"configurable": {"thread_id": session_id}}
    try:
        snapshot = await graph.aget_state(config)
        if snapshot is None or not snapshot.values:
            return False
        return bool(snapshot.values.get("done", False))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# M9.2 — GET /sessions/{session_id}/stream
# ---------------------------------------------------------------------------


@app.get(
    "/sessions/{session_id}/stream",
    tags=["sessions"],
    dependencies=[Depends(_verify_api_key)],
)
async def stream_session_events(
    session_id: str,
    request: Request,
    after_seq: int = 0,
) -> StreamingResponse:
    """Stream node lifecycle events for a session as Server-Sent Events.

    Replays all persisted events first (``seq > after_seq``), then polls for
    new events every ``SSE_POLL_INTERVAL`` seconds until:
      - the session completes (``done=True`` in state) and no more events arrive,
      - or the client disconnects.

    Use ``?after_seq=N`` to resume streaming from a known position (avoids
    replaying events the client already received).

    SSE event types emitted:

      event: node_start
      data: {"type":"node_start","session_id":"...","node_name":"plan","phase":"plan",
             "status":"started","seq":1234567890}

      event: node_end
      data: {"type":"node_end","session_id":"...","node_name":"plan","phase":"plan",
             "status":"completed","duration_ms":412,"summary":"Plan generated (234 chars)",
             "seq":1234567891}

      event: node_error
      data: {"type":"node_error","session_id":"...","node_name":"patch","phase":"patch",
             "status":"failed","duration_ms":50,"summary":"HTTP 422","seq":...}

      event: interrupt
      data: {"type":"interrupt","session_id":"...","node_name":"human_plan_approval",
             "phase":"plan","status":"interrupted","duration_ms":1,"seq":...}

      event: done
      data: {"type":"done","session_id":"..."}

    No LLM tokens are streamed.  No raw tool payloads are included.

    See roadmap9_production_graph_runtime_hardening.md — Milestone 9.2.
    """
    graph = _get_graph(request)
    event_log = getattr(request.app.state, "event_log", None)

    # Validate session exists before opening the stream.
    config = {"configurable": {"thread_id": session_id}}
    try:
        snapshot = await graph.aget_state(config)
    except Exception:
        raise HTTPException(
            status_code=404, detail=f"Session '{session_id}' not found."
        )
    if snapshot is None or not snapshot.values:
        raise HTTPException(
            status_code=404, detail=f"Session '{session_id}' not found."
        )

    async def event_stream():
        yield ": connected\n\n"

        cursor = after_seq
        idle_polls = 0
        # Check done status every N polls to avoid hammering Postgres.
        _DONE_CHECK_EVERY = 5
        poll_count = 0

        while True:
            # ── client disconnect ─────────────────────────────────────
            if await request.is_disconnected():
                break

            # ── fetch new events from DB ──────────────────────────────
            if event_log is not None:
                try:
                    events = await event_log.get_events(
                        session_id, after_seq=cursor, limit=50
                    )
                except Exception as exc:
                    logger.warning("SSE event fetch error for %s: %s", session_id, exc)
                    events = []
            else:
                events = []

            if events:
                idle_polls = 0
                for ev in events:
                    cursor = max(cursor, ev["seq"])
                    yield _format_event_as_sse(ev, session_id)
            else:
                idle_polls += 1

            # ── keepalive comment (prevents proxy timeouts) ───────────
            if idle_polls > 0 and idle_polls % _SSE_KEEPALIVE_AFTER == 0:
                yield ": keepalive\n\n"

            # ── done check ────────────────────────────────────────────
            poll_count += 1
            if poll_count % _DONE_CHECK_EVERY == 0:
                if await _session_is_done(graph, session_id):
                    # Drain any final events written between last poll and now
                    if event_log is not None:
                        try:
                            final = await event_log.get_events(
                                session_id, after_seq=cursor, limit=50
                            )
                            for ev in final:
                                cursor = max(cursor, ev["seq"])
                                yield _format_event_as_sse(ev, session_id)
                        except Exception:
                            pass
                    yield (
                        "event: done\n"
                        f"data: {json.dumps({'type': 'done', 'session_id': session_id})}"
                        "\n\n"
                    )
                    break

            await asyncio.sleep(_SSE_POLL_INTERVAL)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Developer web UI
# ---------------------------------------------------------------------------

_STATIC_DIR = pathlib.Path(__file__).parent / "static"


@app.get("/ui", include_in_schema=False)
async def serve_ui() -> FileResponse:
    """Serve the local developer web UI (single-page HTML app)."""
    return FileResponse(_STATIC_DIR / "index.html", media_type="text/html")


# ---------------------------------------------------------------------------
# Entry point (for uvicorn programmatic launch)
# ---------------------------------------------------------------------------


def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Launch the FastAPI server via uvicorn."""
    import sys
    import uvicorn
    # Windows: psycopg async requires SelectorEventLoop (not the default ProactorEventLoop)
    if sys.platform == "win32":
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "flowise_dev_agent.api:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    serve()
