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

Uses AsyncConnectionPool (not a single connection) so concurrent graph
invocations each get their own Postgres connection.

See roadmap9_production_graph_runtime_hardening.md — Milestone 9.1.
"""

from __future__ import annotations

import logging
import os
import types
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres._ainternal import get_connection  # type: ignore[import]
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore[import]

logger = logging.getLogger("flowise_dev_agent.persistence.checkpointer")

_POOL_MIN = int(os.getenv("POSTGRES_POOL_MIN", "2"))
_POOL_MAX = int(os.getenv("POSTGRES_POOL_MAX", "10"))


async def _list_thread_ids(cp: object) -> list[str]:
    """Return all distinct thread IDs from the checkpoints table.

    When the checkpointer is backed by a pool, acquires its own connection
    so it never conflicts with concurrent graph operations.
    """
    async with get_connection(cp.conn) as conn:  # type: ignore[union-attr]
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
            )
            rows = await cur.fetchall()
    return [row["thread_id"] for row in rows]


async def _thread_exists(cp: object, thread_id: str) -> bool:
    """Return True if at least one checkpoint exists for thread_id."""
    async with get_connection(cp.conn) as conn:  # type: ignore[union-attr]
        async with conn.cursor() as cur:
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

    Creates an AsyncConnectionPool (min=2, max=10 by default, configurable via
    POSTGRES_POOL_MIN / POSTGRES_POOL_MAX) so concurrent graph invocations each
    get their own connection instead of fighting over a single one.

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
    logger.info(
        "Using Postgres checkpointer (pool min=%d max=%d): dsn=%s",
        _POOL_MIN, _POOL_MAX, _redact_dsn(dsn),
    )
    pool = AsyncConnectionPool(
        conninfo=dsn,
        min_size=_POOL_MIN,
        max_size=_POOL_MAX,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    try:
        cp = AsyncPostgresSaver(conn=pool)
        await cp.setup()
        # Attach helpers so api.py can call cp.list_thread_ids() / cp.thread_exists()
        # without breaking LangGraph's isinstance(cp, BaseCheckpointSaver) guard.
        cp.list_thread_ids = types.MethodType(_list_thread_ids, cp)  # type: ignore[attr-defined]
        cp.thread_exists = types.MethodType(_thread_exists, cp)  # type: ignore[attr-defined]
        yield cp
    finally:
        await pool.close()


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
