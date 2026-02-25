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
    # Phase A
    "classify_intent":          "classify",
    "hydrate_context":          "hydrate",
    # Phase B (UPDATE)
    "resolve_target":           "resolve",
    "hitl_select_target":       "resolve",
    # Phase C (UPDATE)
    "load_current_flow":        "load",
    "summarize_current_flow":   "summarize",
    # Phase D
    "plan_v2":                  "plan",
    "hitl_plan_v2":             "plan",
    "define_patch_scope":       "patch",
    "compile_patch_ir":         "patch",
    "compile_flow_data":        "patch",
    # Phase E
    "validate":                 "patch",
    "repair_schema":            "patch",
    # Phase F
    "preflight_validate_patch": "patch",
    "apply_patch":              "patch",
    "test_v2":                  "test",
    "evaluate":                 "evaluate",
    "hitl_review_v2":           "evaluate",
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
        case "classify_intent":
            mode = result.get("operation_mode")
            conf = result.get("intent_confidence")
            if mode:
                conf_str = f" (confidence={conf:.2f})" if conf is not None else ""
                return f"Intent: {mode}{conf_str}"
            return None

        case "hydrate_context":
            facts = result.get("facts") or {}
            flowise = facts.get("flowise") or {}
            nc = flowise.get("node_count", 0)
            return f"Schema loaded: {nc} node types" if nc else "Schema hydrated (empty)"

        case "resolve_target":
            facts = result.get("facts") or {}
            matches = (facts.get("flowise") or {}).get("top_matches") or []
            return f"Resolved {len(matches)} candidate chatflow(s)"

        case "hitl_select_target":
            mode = result.get("operation_mode")
            tid = result.get("target_chatflow_id")
            if mode == "create":
                return "Target: create new chatflow"
            return f"Target selected: {tid}" if tid else "Target selection pending"

        case "load_current_flow":
            facts = result.get("facts") or {}
            h = (facts.get("flowise") or {}).get("current_flow_hash")
            return f"Flow loaded (hash={h[:8]}…)" if h else "Flow load attempted"

        case "summarize_current_flow":
            facts = result.get("facts") or {}
            summary = (facts.get("flowise") or {}).get("flow_summary") or {}
            nc = summary.get("node_count", 0)
            ec = summary.get("edge_count", 0)
            return f"Flow summarized: {nc} nodes, {ec} edges"

        case "plan_v2":
            plan = result.get("plan") or ""
            return f"Plan generated ({len(plan)} chars)" if plan else None

        case "hitl_plan_v2":
            fb = result.get("developer_feedback")
            return "Plan approved" if fb is None else "Plan revision requested"

        case "define_patch_scope":
            facts = result.get("facts") or {}
            patch = facts.get("patch") or {}
            max_ops = patch.get("max_ops")
            focus = patch.get("focus_area")
            parts = []
            if max_ops is not None:
                parts.append(f"max_ops={max_ops}")
            if focus:
                parts.append(f"focus={focus[:40]}")
            return "Scope: " + ", ".join(parts) if parts else "Scope defined"

        case "compile_patch_ir":
            ops = result.get("patch_ir") or []
            return f"{len(ops)} IR op(s) compiled"

        case "compile_flow_data":
            facts = result.get("facts") or {}
            h = (facts.get("flowise") or {}).get("proposed_flow_hash")
            return f"Flow compiled (hash={h[:8]}…)" if h else "Flow compilation attempted"

        case "validate":
            facts = result.get("facts") or {}
            v = facts.get("validation") or {}
            ok = v.get("ok")
            ftype = v.get("failure_type")
            if ok:
                return "Validation passed"
            return f"Validation failed: {ftype}" if ftype else "Validation failed"

        case "repair_schema":
            facts = result.get("facts") or {}
            repair = facts.get("repair") or {}
            count = repair.get("count", 0)
            repaired = repair.get("repaired_node_types") or []
            return f"Schema repair #{count}: {len(repaired)} type(s) recovered"

        case "preflight_validate_patch":
            facts = result.get("facts") or {}
            pf = facts.get("preflight") or {}
            ok = pf.get("ok")
            reason = pf.get("reason")
            if ok:
                return "Preflight passed"
            return f"Preflight failed: {reason}" if reason else "Preflight failed"

        case "apply_patch":
            cid = result.get("chatflow_id")
            facts = result.get("facts") or {}
            apply = facts.get("apply") or {}
            ok = apply.get("ok")
            if ok and cid:
                return f"Patch applied (chatflow_id={cid})"
            return "Patch apply failed" if not ok else "Patch applied"

        case "test_v2":
            tr = result.get("test_results") or ""
            return f"Tests complete ({len(tr)} chars)" if tr else "Tests complete"

        case "evaluate":
            facts = result.get("facts") or {}
            vd = facts.get("verdict") or {}
            verdict = vd.get("verdict", "")
            reason = vd.get("reason", "")
            parts = [f"Verdict: {verdict}"] if verdict else []
            if reason:
                parts.append(reason[:80])
            return " — ".join(parts) or None

        case "hitl_review_v2":
            fb = result.get("developer_feedback")
            done = result.get("done")
            if done:
                return "Result accepted"
            return "Iteration requested" if fb else "Review pending"

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
