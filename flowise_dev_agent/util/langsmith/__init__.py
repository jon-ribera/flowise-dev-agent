"""LangSmith observability utilities for the Flowise Dev Agent.

Provides a lazy-initialized singleton Client, an is_enabled() check,
and a ContextVar for propagating session IDs into HITL feedback nodes.

Mirrors agent-forge's src/app/util/langsmith/ package structure.
"""

from __future__ import annotations

import contextvars
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langsmith import Client

logger = logging.getLogger("flowise_dev_agent.util.langsmith")

# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_client: Client | None = None


def get_client() -> Client | None:
    """Return the shared LangSmith Client, or None if tracing is disabled."""
    global _client
    if not is_enabled():
        return None
    if _client is None:
        from langsmith import Client as _Cls

        _client = _Cls()
        logger.info("LangSmith Client initialized")
    return _client


def is_enabled() -> bool:
    """Return True when LangSmith tracing is active."""
    return os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"


# ---------------------------------------------------------------------------
# ContextVar — set in wrap_node(), read by HITL feedback (DD-086)
# ---------------------------------------------------------------------------

current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "langsmith_session_id", default=""
)
