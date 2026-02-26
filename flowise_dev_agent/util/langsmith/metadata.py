"""Enrich LangSmith run metadata with internal telemetry (DD-085).

Extracts PhaseMetrics, converge verdicts, intent classification, pattern
metrics, token totals, and schema drift from AgentState and formats them
as flat metadata dicts suitable for LangSmith filtering.

Naming convention — all keys are dot-namespaced by domain:

    agent.operation_mode      agent.intent_confidence   agent.iteration
    agent.pattern_used        agent.pattern_id          agent.runtime_mode
    agent.done

    telemetry.total_input_tokens   telemetry.total_output_tokens
    telemetry.schema_fingerprint   telemetry.drift_detected
    telemetry.total_phases_timed   telemetry.total_repair_events
    telemetry.phase_ms.<name>      (per-phase durations)

    verdict.value      verdict.category    verdict.reason

    pattern.pattern_used   pattern.pattern_id   pattern.ops_in_base
"""

from __future__ import annotations

from typing import Any


def extract_session_metadata(state: dict[str, Any]) -> dict[str, Any]:
    """Extract flat metadata dict from current AgentState for LangSmith.

    All values are JSON-serialisable primitives (str, int, float, bool, None).
    Missing fields default gracefully — never raises.
    """
    meta: dict[str, Any] = {}

    # -- Agent-level ----------------------------------------------------------
    meta["agent.operation_mode"] = state.get("operation_mode") or "unknown"
    meta["agent.intent_confidence"] = state.get("intent_confidence") or 0.0
    meta["agent.iteration"] = state.get("iteration", 0)
    meta["agent.pattern_used"] = bool(state.get("pattern_used"))
    meta["agent.pattern_id"] = state.get("pattern_id")
    meta["agent.runtime_mode"] = state.get("runtime_mode") or "unknown"
    meta["agent.done"] = bool(state.get("done"))

    # -- Token totals ---------------------------------------------------------
    meta["telemetry.total_input_tokens"] = state.get("total_input_tokens", 0) or 0
    meta["telemetry.total_output_tokens"] = state.get("total_output_tokens", 0) or 0

    # -- Schema / drift -------------------------------------------------------
    flowise_facts = (state.get("facts") or {}).get("flowise", {}) or {}
    meta["telemetry.schema_fingerprint"] = flowise_facts.get("schema_fingerprint") or ""
    prior_fp = flowise_facts.get("prior_schema_fingerprint") or ""
    current_fp = flowise_facts.get("schema_fingerprint") or ""
    meta["telemetry.drift_detected"] = bool(
        current_fp and prior_fp and current_fp != prior_fp
    )

    # -- PhaseMetrics summary -------------------------------------------------
    flowise_debug = (state.get("debug") or {}).get("flowise", {}) or {}
    phase_metrics: list[Any] = flowise_debug.get("phase_metrics") or []
    meta["telemetry.total_phases_timed"] = len(phase_metrics)
    meta["telemetry.total_repair_events"] = sum(
        m.get("repair_events", 0)
        for m in phase_metrics
        if isinstance(m, dict)
    )

    # Per-phase durations (flat: telemetry.phase_ms.discover, etc.)
    for pm in phase_metrics:
        if isinstance(pm, dict) and "phase" in pm:
            meta[f"telemetry.phase_ms.{pm['phase']}"] = pm.get("duration_ms", 0.0)

    # -- Pattern metrics ------------------------------------------------------
    pattern_metrics = flowise_debug.get("pattern_metrics")
    if pattern_metrics and isinstance(pattern_metrics, dict):
        meta["pattern.pattern_used"] = bool(pattern_metrics.get("pattern_used"))
        meta["pattern.pattern_id"] = pattern_metrics.get("pattern_id")
        meta["pattern.ops_in_base"] = pattern_metrics.get("ops_in_base", 0)

    # -- Anchor resolution metrics (M10.3a) -----------------------------------
    anchor_res = flowise_debug.get("anchor_resolution")
    if anchor_res and isinstance(anchor_res, dict):
        meta["telemetry.anchor_exact_match_rate"] = anchor_res.get("exact_match_rate", 1.0)
        meta["telemetry.anchor_fuzzy_fallbacks"] = anchor_res.get("fuzzy_fallbacks", 0)
        meta["telemetry.anchor_total_connections"] = anchor_res.get("total_connections", 0)

    # -- Converge verdict -----------------------------------------------------
    verdict = state.get("converge_verdict")
    if verdict and isinstance(verdict, dict):
        meta["verdict.value"] = verdict.get("verdict", "")
        meta["verdict.category"] = verdict.get("category") or ""
        meta["verdict.reason"] = (verdict.get("reason") or "")[:200]

    return meta


def extract_outcome_tags(state: dict[str, Any]) -> list[str]:
    """Derive outcome-based tags from final state for LangSmith run tagging.

    Returns a list of tags like:
        ["outcome:completed", "mode:create", "pattern:reused"]
    """
    tags: list[str] = []

    if state.get("done"):
        tags.append("outcome:completed")
    else:
        tags.append("outcome:incomplete")

    op_mode = state.get("operation_mode")
    if op_mode:
        tags.append(f"mode:{op_mode}")

    if state.get("pattern_used"):
        tags.append("pattern:reused")

    # Iteration count bucket
    iteration = state.get("iteration", 0)
    if iteration <= 1:
        tags.append("iterations:1")
    elif iteration <= 3:
        tags.append("iterations:2-3")
    else:
        tags.append("iterations:4+")

    return tags
