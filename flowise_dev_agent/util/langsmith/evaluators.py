"""Code-based evaluators for LangSmith (DD-087).

Five pure-function evaluators that score agent session quality. They operate
on state dicts and return ``{"key": str, "score": float, "comment": str}``.

These run both as online evaluators on production traces and offline in CI
against the golden dataset — no LLM calls, no side effects.

Evaluators
----------
- ``compile_success``       — did flow_data compile and deploy?
- ``intent_confidence``     — is classification confidence above threshold?
- ``iteration_efficiency``  — did the session converge in <= 3 iterations?
- ``token_budget``          — per-phase token budgets respected?
- ``plan_quality``          — plan section completeness + metadata sections
"""

from __future__ import annotations

from typing import Any


def compile_success(run_output: dict[str, Any], **kwargs: Any) -> dict:
    """Evaluator: Did the chatflow compile and deploy successfully?

    Score 1.0 when:
    - ``chatflow_id`` is set (something was created/updated)
    - ``done`` is True (converge said DONE)
    - No error verdict in converge_verdict
    """
    chatflow_id = run_output.get("chatflow_id")
    done = run_output.get("done", False)

    verdict = run_output.get("converge_verdict") or {}
    verdict_ok = verdict.get("verdict") != "ITERATE"

    score = 1.0 if (chatflow_id and done and verdict_ok) else 0.0

    return {
        "key": "compile_success",
        "score": score,
        "comment": (
            f"chatflow_id={'set' if chatflow_id else 'missing'}, "
            f"done={done}, verdict={verdict.get('verdict', 'none')}"
        ),
    }


def intent_confidence(
    run_output: dict[str, Any],
    *,
    threshold: float = 0.7,
    **kwargs: Any,
) -> dict:
    """Evaluator: Is intent classification confidence above threshold?

    Returns the raw confidence as the score (continuous 0.0-1.0).
    """
    confidence = run_output.get("intent_confidence") or 0.0
    return {
        "key": "intent_confidence",
        "score": float(confidence),
        "comment": f"confidence={confidence:.2f}, threshold={threshold}",
    }


def iteration_efficiency(
    run_output: dict[str, Any],
    *,
    max_iterations: int = 3,
    **kwargs: Any,
) -> dict:
    """Evaluator: Did session converge in <= max_iterations?

    Score 1.0 when done=True and iteration <= max_iterations.
    """
    iteration = run_output.get("iteration", 0)
    done = run_output.get("done", False)
    score = 1.0 if (done and iteration <= max_iterations) else 0.0
    return {
        "key": "iteration_efficiency",
        "score": score,
        "comment": f"iterations={iteration}, done={done}, max={max_iterations}",
    }


# Per-phase token budgets (reasonable defaults for a dev copilot)
_PHASE_TOKEN_BUDGETS: dict[str, int] = {
    "discover": 15_000,
    "plan": 8_000,
    "patch": 20_000,
    "test": 10_000,
    "evaluate": 5_000,
    "converge": 5_000,
}


def token_budget(run_output: dict[str, Any], **kwargs: Any) -> dict:
    """Evaluator: Were per-phase token budgets respected?

    Score = 1.0 - (violations / total_phases).  Clipped to [0.0, 1.0].
    """
    flowise_debug = (run_output.get("debug") or {}).get("flowise", {}) or {}
    phase_metrics: list[Any] = flowise_debug.get("phase_metrics") or []

    violations: list[str] = []
    total_phases = 0
    for pm in phase_metrics:
        if not isinstance(pm, dict):
            continue
        phase = pm.get("phase", "")
        total_tokens = pm.get("input_tokens", 0) + pm.get("output_tokens", 0)
        budget = _PHASE_TOKEN_BUDGETS.get(phase, 25_000)
        total_phases += 1
        if total_tokens > budget:
            violations.append(f"{phase}: {total_tokens}/{budget}")

    score = max(0.0, 1.0 - len(violations) / max(total_phases, 1))
    return {
        "key": "token_budget",
        "score": round(score, 3),
        "comment": (
            f"violations={violations}" if violations else "all phases within budget"
        ),
    }


def plan_quality(run_output: dict[str, Any], **kwargs: Any) -> dict:
    """Evaluator: Plan completeness and metadata section presence.

    Score = (section_completeness * 0.7) + (metadata_completeness * 0.3).

    Checks for required plan sections (GOAL, INPUTS, OUTPUTS, CONSTRAINTS,
    SUCCESS CRITERIA, PATTERN, ACTION) and metadata blocks (DOMAINS,
    CREDENTIALS, DATA_CONTRACTS).
    """
    plan = run_output.get("plan") or ""

    required_sections = [
        "GOAL", "INPUTS", "OUTPUTS", "CONSTRAINTS",
        "SUCCESS CRITERIA", "PATTERN", "ACTION",
    ]
    found = sum(1 for s in required_sections if s.upper() in plan.upper())
    completeness = found / len(required_sections) if required_sections else 0.0

    metadata_markers = ["## DOMAINS", "## CREDENTIALS", "## DATA_CONTRACTS"]
    metadata_found = sum(1 for m in metadata_markers if m in plan)
    metadata_score = metadata_found / len(metadata_markers) if metadata_markers else 0.0

    score = round((completeness * 0.7) + (metadata_score * 0.3), 2)

    missing = [s for s in required_sections if s.upper() not in plan.upper()]
    return {
        "key": "plan_quality",
        "score": score,
        "comment": (
            f"sections={found}/{len(required_sections)}, "
            f"metadata={metadata_found}/{len(metadata_markers)}"
            + (f", missing={missing}" if missing else "")
        ),
    }


ALL_EVALUATORS = [
    compile_success,
    intent_confidence,
    iteration_efficiency,
    token_budget,
    plan_quality,
]
