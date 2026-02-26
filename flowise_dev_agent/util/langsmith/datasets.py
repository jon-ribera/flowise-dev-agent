"""Trace-to-dataset utilities.

Save interesting sessions to the golden dataset for regression testing.

Usage (programmatic)::

    from flowise_dev_agent.util.langsmith.datasets import save_session_to_dataset
    await save_session_to_dataset("thread-abc-123")

Usage (CLI)::

    python -m flowise_dev_agent.util.langsmith.datasets <thread_id> [--dataset NAME]
"""

from __future__ import annotations

import logging

logger = logging.getLogger("flowise_dev_agent.util.langsmith.datasets")


async def save_session_to_dataset(
    thread_id: str,
    dataset_name: str = "flowise-agent-golden-set",
    note: str = "",
) -> bool:
    """Save a session's root run to the golden dataset.

    Looks up the most recent root run for *thread_id* and creates a
    dataset example from it.

    Returns True on success, False otherwise (never raises).
    """
    from flowise_dev_agent.util.langsmith import get_client

    client = get_client()
    if client is None:
        logger.warning("LangSmith not enabled; cannot save to dataset")
        return False

    try:
        runs = list(client.list_runs(
            project_name="flowise-dev-agent",
            filter=(
                'has(metadata, "thread_id") and '
                f'eq(metadata["thread_id"], "{thread_id}")'
            ),
            is_root=True,
            limit=1,
        ))
        if not runs:
            logger.warning("No runs found for thread %s", thread_id)
            return False

        run = runs[0]
        client.create_example_from_run(
            run_id=str(run.id),
            dataset_name=dataset_name,
        )
        logger.info("Session %s saved to dataset '%s'", thread_id, dataset_name)
        return True
    except Exception as exc:
        logger.warning("Failed to save session to dataset: %s", exc)
        return False


def cli_main() -> None:
    """CLI entry point for saving sessions to the golden dataset."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        description="Save a session to the LangSmith golden dataset"
    )
    parser.add_argument("thread_id", help="Session thread ID to save")
    parser.add_argument(
        "--dataset",
        default="flowise-agent-golden-set",
        help="Target dataset name (default: flowise-agent-golden-set)",
    )
    parser.add_argument("--note", default="", help="Optional note for the example")
    args = parser.parse_args()

    # Load env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    import os
    if os.getenv("LANGCHAIN_API_KEY"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"

    success = asyncio.run(save_session_to_dataset(args.thread_id, args.dataset, args.note))
    if success:
        print(f"Saved session {args.thread_id} to dataset {args.dataset}")
    else:
        print(f"Failed to save session {args.thread_id}")
        raise SystemExit(1)


if __name__ == "__main__":
    cli_main()
