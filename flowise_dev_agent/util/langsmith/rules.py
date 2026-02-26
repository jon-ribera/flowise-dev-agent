"""Automation rule helpers for LangSmith (DD-088).

LangSmith v0.4.x does not expose automation rules via the Python SDK.
Rules must be configured in the LangSmith UI.

This module provides:
- ``add_to_annotation_queue()`` — programmatically route a run to the review queue.
- ``add_to_dataset()``          — programmatically save a run to a dataset.
- ``setup_instructions()``      — markdown instructions for UI automation rules.

Usage in api.py (fire-and-forget after session completes)::

    from flowise_dev_agent.util.langsmith.rules import (
        add_to_annotation_queue,
        add_to_dataset,
    )

    if state.get("done"):
        asyncio.create_task(add_to_dataset(run_id))
    else:
        asyncio.create_task(add_to_annotation_queue(run_id))
"""

from __future__ import annotations

import logging

logger = logging.getLogger("flowise_dev_agent.util.langsmith.rules")


async def add_to_annotation_queue(
    run_id: str,
    queue_name: str = "agent-review-queue",
) -> bool:
    """Add a specific run to the annotation queue for human review."""
    from flowise_dev_agent.util.langsmith import get_client

    client = get_client()
    if client is None:
        return False

    try:
        queues = list(client.list_annotation_queues(name=queue_name))
        if not queues:
            logger.warning("Annotation queue '%s' not found", queue_name)
            return False

        queue_id = queues[0].id
        client.add_runs_to_annotation_queue(queue_id, run_ids=[run_id])
        logger.info("Run %s added to annotation queue '%s'", run_id, queue_name)
        return True
    except Exception as exc:
        logger.debug("Failed to add run to annotation queue: %s", exc)
        return False


async def add_to_dataset(
    run_id: str,
    dataset_name: str = "flowise-agent-golden-set",
) -> bool:
    """Save a run as an example in the golden dataset."""
    from flowise_dev_agent.util.langsmith import get_client

    client = get_client()
    if client is None:
        return False

    try:
        client.create_example_from_run(
            run_id=run_id,
            dataset_name=dataset_name,
        )
        logger.info("Run %s added to dataset '%s'", run_id, dataset_name)
        return True
    except Exception as exc:
        logger.debug("Failed to add run to dataset: %s", exc)
        return False


def setup_instructions() -> str:
    """Return markdown instructions for LangSmith UI automation rules.

    Print or log these instructions to guide manual setup:

        print(setup_instructions())
    """
    return """\
## LangSmith Automation Rules Setup

Configure these rules in the LangSmith UI under:
  Project "flowise-dev-agent" > Settings > Rules

### Rule 1: Route Failed Sessions to Annotation Queue
- **Filter**: `has(metadata, "agent.done") and eq(metadata["agent.done"], false)`
- **Action**: Add to annotation queue "agent-review-queue"
- **Sampling**: 100%

### Rule 2: Sample Successful Sessions to Golden Dataset
- **Filter**: `has(metadata, "agent.done") and eq(metadata["agent.done"], true)`
- **Action**: Add to dataset "flowise-agent-golden-set"
- **Sampling**: 20%

### Rule 3: Flag Low-Confidence Intent Classification
- **Filter**: `has(metadata, "agent.intent_confidence") and lt(metadata["agent.intent_confidence"], 0.7)`
- **Action**: Add to annotation queue "agent-review-queue"
- **Sampling**: 100%

### Rule 4: Flag High Iteration Count
- **Filter**: `has(tags, "iterations:4+")`
- **Action**: Add to annotation queue "agent-review-queue"
- **Sampling**: 100%
"""
