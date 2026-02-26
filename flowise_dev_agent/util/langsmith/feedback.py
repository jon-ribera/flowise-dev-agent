"""Submit HITL feedback to LangSmith (DD-086).

Wires developer approval/rejection at plan_approval and result_review
interrupt points as LangSmith feedback (thumbs up/down + comment).

Feedback is submitted asynchronously and fire-and-forget — failures
are logged but never block the graph.

Usage in HITL nodes::

    from flowise_dev_agent.util.langsmith import current_session_id
    from flowise_dev_agent.util.langsmith.feedback import submit_hitl_feedback

    asyncio.create_task(submit_hitl_feedback(
        thread_id=current_session_id.get(),
        interrupt_type="plan_approval",
        approved=True,
        developer_response="Looks good, proceed.",
    ))
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("flowise_dev_agent.util.langsmith.feedback")


async def submit_hitl_feedback(
    thread_id: str,
    interrupt_type: str,
    approved: bool,
    developer_response: str,
    run_id: str | None = None,
) -> None:
    """Submit HITL feedback to LangSmith.

    Parameters
    ----------
    thread_id:
        LangGraph thread ID (used to find the run if *run_id* not given).
    interrupt_type:
        ``"plan_approval"`` or ``"result_review"``.
    approved:
        Whether the developer approved.
    developer_response:
        The developer's raw response text.
    run_id:
        Optional LangSmith run ID (if known from config).
    """
    from flowise_dev_agent.util.langsmith import get_client

    client = get_client()
    if client is None:
        return

    try:
        target_run_id = run_id

        # Resolve run_id from thread_id if not provided
        if not target_run_id and thread_id:
            runs = list(client.list_runs(
                project_name="flowise-dev-agent",
                filter=(
                    'has(metadata, "thread_id") and '
                    f'eq(metadata["thread_id"], "{thread_id}")'
                ),
                is_root=True,
                limit=1,
            ))
            if runs:
                target_run_id = str(runs[0].id)

        if not target_run_id:
            logger.debug(
                "Could not resolve run_id for thread %s — skipping feedback",
                thread_id,
            )
            return

        key = f"hitl_{interrupt_type}"
        score = 1.0 if approved else 0.0
        comment = (developer_response or "")[:500]

        client.create_feedback(
            run_id=target_run_id,
            key=key,
            score=score,
            comment=comment,
        )
        logger.info(
            "LangSmith feedback submitted: thread=%s type=%s approved=%s",
            thread_id,
            interrupt_type,
            approved,
        )
    except Exception as exc:
        logger.debug("LangSmith feedback submission failed (non-fatal): %s", exc)
