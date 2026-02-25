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


async def _list_thread_ids(cp: object) -> list[str]:
    """Return all distinct thread IDs from the checkpoints table."""
    async with cp.conn.cursor() as cur:  # type: ignore[union-attr]
        await cur.execute(
            "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
        )
        rows = await cur.fetchall()
    return [row[0] for row in rows]


async def _thread_exists(cp: object, thread_id: str) -> bool:
    """Return True if at least one checkpoint exists for thread_id."""
    async with cp.conn.cursor() as cur:  # type: ignore[union-attr]
        await cur.execute(
            "SELECT 1 FROM checkpoints WHERE thread_id = %s LIMIT 1",
            (thread_id,),
        )
        row = await cur.fetchone()
    return row is not None


@asynccontextmanager
async def make_checkpointer(
    dsn: str,
) -> AsyncGenerator[object, None]:
    """Async context manager that yields a Postgres-backed LangGraph checkpointer.

    Calls cp.setup() on entry to create LangGraph checkpoint tables if they
    do not already exist.

    Yields the raw AsyncPostgresSaver (a BaseCheckpointSaver subclass) so that
    LangGraph's isinstance guard passes.  The helpers list_thread_ids() and
    thread_exists() are monkey-patched onto the instance for api.py use.

    Args:
        dsn: Postgres connection string (e.g. from POSTGRES_DSN env var).

    Raises:
        ImportError: if langgraph-checkpoint-postgres / psycopg is not installed.
        Exception:   if the Postgres connection cannot be established.
    """
    import types
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore[import]

    logger.info("Using Postgres checkpointer: dsn=%s", _redact_dsn(dsn))
    async with AsyncPostgresSaver.from_conn_string(dsn) as cp:
        await cp.setup()
        # Attach helpers so api.py can call cp.list_thread_ids() / cp.thread_exists()
        # without breaking LangGraph's isinstance(cp, BaseCheckpointSaver) guard.
        cp.list_thread_ids = types.MethodType(_list_thread_ids, cp)  # type: ignore[attr-defined]
        cp.thread_exists = types.MethodType(_thread_exists, cp)  # type: ignore[attr-defined]
        yield cp


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
