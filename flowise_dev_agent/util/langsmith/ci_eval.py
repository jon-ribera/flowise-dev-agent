"""CI evaluation integration — run golden dataset evaluations.

Provides ``run_golden_set_eval()`` for use in pytest or CI pipelines.

Usage::

    # In a pytest test:
    @pytest.mark.slow
    async def test_golden_set_regression():
        results = await run_golden_set_eval()
        assert results["compile_success"]["mean_score"] >= 0.9
        assert results["iteration_efficiency"]["mean_score"] >= 0.7

    # From the CLI:
    python -m flowise_dev_agent.util.langsmith.ci_eval [--dataset NAME]
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("flowise_dev_agent.util.langsmith.ci_eval")


async def run_golden_set_eval(
    dataset_name: str = "flowise-agent-golden-set",
) -> dict[str, dict[str, Any]]:
    """Run all evaluators against the golden dataset and return aggregated scores.

    Returns
    -------
    dict
        Mapping evaluator key → ``{"mean_score": float, "count": int}``.

    Raises
    ------
    RuntimeError
        If LangSmith is not configured.
    """
    from flowise_dev_agent.util.langsmith import get_client
    from flowise_dev_agent.util.langsmith.evaluators import ALL_EVALUATORS

    client = get_client()
    if client is None:
        raise RuntimeError("LangSmith is not configured (LANGCHAIN_API_KEY not set)")

    # Fetch dataset examples
    datasets = list(client.list_datasets(dataset_name=dataset_name))
    if not datasets:
        raise RuntimeError(f"Dataset '{dataset_name}' not found in LangSmith")

    dataset_id = datasets[0].id
    examples = list(client.list_examples(dataset_id=dataset_id))

    if not examples:
        logger.warning("Dataset '%s' has no examples — returning empty results", dataset_name)
        return {}

    # Run each evaluator against each example's source run output
    aggregated: dict[str, dict[str, Any]] = {}
    for example in examples:
        # The example's outputs represent the agent's final state
        run_output = example.outputs or {}

        for eval_fn in ALL_EVALUATORS:
            try:
                result = eval_fn(run_output)
            except Exception as exc:
                logger.warning("Evaluator %s failed on example %s: %s", eval_fn.__name__, example.id, exc)
                continue

            key = result.get("key", eval_fn.__name__)
            if key not in aggregated:
                aggregated[key] = {"scores": [], "count": 0}
            aggregated[key]["scores"].append(result.get("score", 0.0))
            aggregated[key]["count"] += 1

    # Compute means
    for key, data in aggregated.items():
        scores = data["scores"]
        data["mean_score"] = sum(scores) / len(scores) if scores else 0.0
        del data["scores"]  # keep return value clean

    return aggregated


def cli_main() -> None:
    """CLI entry point: ``python -m flowise_dev_agent.util.langsmith.ci_eval``."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Run golden dataset evaluations")
    parser.add_argument(
        "--dataset",
        default="flowise-agent-golden-set",
        help="Dataset name (default: flowise-agent-golden-set)",
    )
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    import os
    if os.getenv("LANGCHAIN_API_KEY"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"

    results = asyncio.run(run_golden_set_eval(args.dataset))

    print(f"\n{'Evaluator':<25} {'Mean Score':>10} {'Count':>6}")
    print("-" * 45)
    for key, data in sorted(results.items()):
        print(f"{key:<25} {data['mean_score']:>10.3f} {data['count']:>6}")

    # Exit non-zero if any evaluator scores below 0.5
    failures = [k for k, d in results.items() if d["mean_score"] < 0.5]
    if failures:
        print(f"\nFAILED evaluators: {failures}")
        raise SystemExit(1)
    else:
        print("\nAll evaluators above threshold.")


if __name__ == "__main__":
    cli_main()
