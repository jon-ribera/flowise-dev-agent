"""Environment-aware ``@dev_tracer`` decorator.

Adapts agent-forge's pattern: only traces functions in dev environments.
In test and production, the decorator is a transparent no-op.

Usage::

    from flowise_dev_agent.util.langsmith.tracer import dev_tracer

    @dev_tracer("refresh_node_schemas", tags=["knowledge"])
    async def refresh_node_schemas(...):
        ...

    @dev_tracer("compile_patch_ir", run_type="chain")
    def compile_patch_ir(...):
        ...

See DESIGN_DECISIONS.md — DD-084 (redaction applied automatically).
"""

from __future__ import annotations

import os
from typing import Any, Callable


def _is_dev_environment() -> bool:
    """Check if we are in a development environment.

    Reads ``LANGSMITH_ENVIRONMENT`` env var (default: ``dev``).
    Returns True for ``dev``, ``development``, ``local``.
    """
    env = os.getenv("LANGSMITH_ENVIRONMENT", "dev").lower()
    return env in ("dev", "development", "local")


def dev_tracer(
    name: str | None = None,
    *,
    run_type: str = "chain",
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> Callable:
    """Decorator that traces a function with LangSmith only in dev environment.

    In test/prod, the function runs without tracing overhead.

    Parameters
    ----------
    name:
        Run name in LangSmith. Defaults to the function's ``__name__``.
    run_type:
        LangSmith run type (``chain``, ``tool``, ``llm``, etc.).
    metadata:
        Additional metadata to attach to the trace.
    tags:
        Additional tags for the trace.
    """
    def decorator(fn: Callable) -> Callable:
        if not _is_dev_environment():
            return fn  # no-op in non-dev environments

        try:
            from langsmith import traceable

            from flowise_dev_agent.util.langsmith.redaction import (
                hide_inputs,
                hide_outputs,
            )

            traced = traceable(
                name=name or getattr(fn, "__name__", "unknown"),
                run_type=run_type,
                metadata=metadata or {},
                tags=tags or [],
                hide_inputs=hide_inputs,
                hide_outputs=hide_outputs,
            )(fn)
            return traced
        except ImportError:
            return fn  # langsmith not installed

    return decorator
