"""Node lifecycle event emission hooks for LangGraph graph nodes.

Provides wrap_node() — a factory that wraps any LangGraph node function with
before/after event emission so node start, completion, failure, and HITL
interrupts are recorded to the session_events table.

Design:
  - The wrapper accepts (state, config=None).  LangGraph v0.2 inspects the
    function signature and passes `config` when the node declares it, giving
    us the thread_id (= session_id) without modifying node internals.
  - Errors are emitted but always re-raised so graph routing is unaffected.
  - GraphInterrupt exceptions are treated as "interrupted", not "failed".
  - emit_event is the EventLog.insert_event bound method; errors inside it are
    already swallowed by EventLog, so the wrapper never masks graph errors.

See roadmap9_production_graph_runtime_hardening.md — Milestone 9.2.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from langchain_core.runnables import RunnableConfig

# ---------------------------------------------------------------------------
# Node → phase mapping
# ---------------------------------------------------------------------------

#: Maps every registered graph node name to a logical phase label used in
#: the session_events table.  Unknown nodes fall back to their own name.
_NODE_PHASES: dict[str, str] = {
    "clarify":              "clarify",
    "discover":             "discover",
    "check_credentials":    "credentials",
    "plan":                 "plan",
    "human_plan_approval":  "plan",
    "patch":                "patch",
    "test":                 "test",
    "converge":             "evaluate",
    "human_result_review":  "evaluate",
}

#: Exception class names that indicate a LangGraph HITL interrupt rather than
#: a real error.  Checked by name to avoid a hard import dependency on
#: langgraph internals across different versions.
_INTERRUPT_CLASS_NAMES: frozenset[str] = frozenset({
    "GraphInterrupt",
    "NodeInterrupt",
})


# ---------------------------------------------------------------------------
# Node summary helpers
# ---------------------------------------------------------------------------

def _node_summary(node_name: str, result: dict[str, Any]) -> str | None:
    """Extract a compact (≤200 char) human-readable summary from a node result.

    Returns None if the result contains nothing interesting.  Never includes
    raw blobs, full plan text, or large payloads.
    """
    if not isinstance(result, dict):
        return None

    match node_name:
        case "clarify":
            c = result.get("clarification")
            return "Clarification requested" if c else "No clarification needed"

        case "discover":
            ds = result.get("discovery_summary") or ""
            return f"Discovery complete ({len(ds)} chars)" if ds else None

        case "check_credentials":
            missing = result.get("credentials_missing") or []
            if missing:
                return f"{len(missing)} credential(s) missing"
            return "All credentials present"

        case "plan":
            plan = result.get("plan") or ""
            return f"Plan generated ({len(plan)} chars)" if plan else None

        case "human_plan_approval":
            fb = result.get("developer_feedback")
            return "Plan approved" if fb is None else "Plan revision requested"

        case "patch":
            ops = result.get("patch_ir")
            if isinstance(ops, list):
                return f"{len(ops)} IR ops compiled"
            # Legacy path: no patch_ir key
            cid = result.get("chatflow_id")
            return f"Patch written (chatflow_id={cid})" if cid else "Patch complete"

        case "test":
            tr = result.get("test_results") or ""
            return f"Tests complete ({len(tr)} chars)" if tr else "Tests complete"

        case "converge":
            vd = result.get("converge_verdict") or {}
            v = vd.get("verdict", "")
            reason = vd.get("reason", "")
            parts = [f"Verdict: {v}"] if v else []
            if reason:
                parts.append(reason[:80])
            return " — ".join(parts) or None

        case "human_result_review":
            fb = result.get("developer_feedback")
            return "Result accepted" if fb is None else "Iteration requested"

    return None


# ---------------------------------------------------------------------------
# Node wrapper
# ---------------------------------------------------------------------------

def wrap_node(
    node_name: str,
    fn: Callable,
    emit_event: Callable,
) -> Callable:
    """Return a wrapped version of *fn* that emits lifecycle events.

    The returned coroutine has signature ``(state, config=None)`` so that
    LangGraph passes the RunnableConfig (containing the thread_id) when the
    node is invoked.

    Args:
        node_name:   Registered LangGraph node name (e.g. "plan", "patch").
        fn:          Original async node function ``(state) -> dict``.
        emit_event:  Async callable with the same signature as
                     ``EventLog.insert_event``.  Called with keyword args.
    """
    phase = _NODE_PHASES.get(node_name, node_name)

    async def wrapped(state: Any, config: Optional[RunnableConfig] = None) -> dict:
        # Extract session_id from LangGraph RunnableConfig
        session_id: str = ""
        if config is not None:
            session_id = (config.get("configurable") or {}).get("thread_id", "")

        # ── node_start ───────────────────────────────────────────────────
        await emit_event(
            session_id=session_id,
            node_name=node_name,
            phase=phase,
            status="started",
        )

        start = time.monotonic()
        try:
            result = await fn(state)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            is_interrupt = type(exc).__name__ in _INTERRUPT_CLASS_NAMES
            # ── interrupt / node_error ───────────────────────────────────
            await emit_event(
                session_id=session_id,
                node_name=node_name,
                phase=phase,
                status="interrupted" if is_interrupt else "failed",
                duration_ms=duration_ms,
                summary=None if is_interrupt else str(exc)[:200],
            )
            raise  # always re-raise; graph routing must not be interrupted

        duration_ms = int((time.monotonic() - start) * 1000)
        # ── node_end ─────────────────────────────────────────────────────
        await emit_event(
            session_id=session_id,
            node_name=node_name,
            phase=phase,
            status="completed",
            duration_ms=duration_ms,
            summary=_node_summary(node_name, result),
        )
        return result

    # Preserve the original function name for LangGraph introspection
    wrapped.__name__ = fn.__name__ if hasattr(fn, "__name__") else node_name
    wrapped.__qualname__ = getattr(fn, "__qualname__", node_name)
    return wrapped
