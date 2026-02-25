"""Postgres checkpointer factory for flowise-dev-agent.

Requires:
  POSTGRES_DSN  postgresql://user:pass@host:port/db

Raises RuntimeError on startup if POSTGRES_DSN is not set.

Usage:

    dsn = os.environ["POSTGRES_DSN"]
    async with make_checkpointer(dsn) as cp:
        graph = build_graph(..., checkpointer=cp)

The CheckpointerAdapter wraps AsyncPostgresSaver and adds two helpers
that api.py uses in place of the old SQLite-specific .conn.execute() calls:

    await cp.list_thread_ids()   -> list[str]
    await cp.thread_exists(tid)  -> bool

All other LangGraph methods (aput, aget, alist, aput_writes, …) are
transparently delegated to the underlying AsyncPostgresSaver.

See roadmap9_production_graph_runtime_hardening.md — Milestone 9.1.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

logger = logging.getLogger("flowise_dev_agent.persistence.checkpointer")


class CheckpointerAdapter:
    """Wraps AsyncPostgresSaver with helper methods for api.py list/delete endpoints.

    LangGraph calls methods on the checkpointer via duck-typing (no isinstance
    checks), so __getattr__ delegation is safe and complete.
    """

    def __init__(self, checkpointer: object) -> None:
        object.__setattr__(self, "_cp", checkpointer)

    # ------------------------------------------------------------------
    # Transparent delegation to AsyncPostgresSaver
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> object:
        return getattr(object.__getattribute__(self, "_cp"), name)

    # ------------------------------------------------------------------
    # Postgres-native helpers used by api.py
    # ------------------------------------------------------------------

    async def list_thread_ids(self) -> list[str]:
        """Return all distinct thread IDs from the checkpoints table."""
        cp = object.__getattribute__(self, "_cp")
        async with cp.conn.cursor() as cur:
            await cur.execute(
                "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
            )
            rows = await cur.fetchall()
        return [row[0] for row in rows]

    async def thread_exists(self, thread_id: str) -> bool:
        """Return True if at least one checkpoint exists for thread_id."""
        cp = object.__getattribute__(self, "_cp")
        async with cp.conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM checkpoints WHERE thread_id = %s LIMIT 1",
                (thread_id,),
            )
            row = await cur.fetchone()
        return row is not None


@asynccontextmanager
async def make_checkpointer(
    dsn: str,
) -> AsyncGenerator[CheckpointerAdapter, None]:
    """Async context manager that yields a Postgres-backed LangGraph checkpointer.

    Calls cp.setup() on entry to create LangGraph checkpoint tables if they
    do not already exist.

    Args:
        dsn: Postgres connection string (e.g. from POSTGRES_DSN env var).

    Yields:
        CheckpointerAdapter wrapping AsyncPostgresSaver.

    Raises:
        ImportError: if langgraph-checkpoint-postgres / psycopg is not installed.
        Exception:   if the Postgres connection cannot be established.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore[import]

    logger.info("Using Postgres checkpointer: dsn=%s", _redact_dsn(dsn))
    async with AsyncPostgresSaver.from_conn_string(dsn) as cp:
        await cp.setup()
        yield CheckpointerAdapter(cp)


def _redact_dsn(dsn: str) -> str:
    """Replace password in DSN with *** for safe logging."""
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(dsn)
        if parsed.password:
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            netloc = f"{parsed.username}:***@{netloc}"
            redacted = parsed._replace(netloc=netloc)
            return urlunparse(redacted)
    except Exception:
        pass
    return dsn
