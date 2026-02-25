"""Session event log — Postgres-backed node lifecycle persistence.

Persists node lifecycle events to a session_events table in Postgres.
Inserts are fire-and-forget: errors are logged and never raised so a
failing event log never blocks agent execution.

Table schema:

  session_id   TEXT        — LangGraph thread_id
  seq          BIGINT      — nanosecond epoch (monotonically increasing, unique)
  ts           TIMESTAMPTZ — set by Postgres DEFAULT now()
  node_name    TEXT        — LangGraph node name  (e.g. "plan", "patch")
  phase        TEXT        — logical phase label  (e.g. "discover", "patch")
  status       TEXT        — started | completed | failed | interrupted
  duration_ms  INT NULL    — elapsed ms (set on completed / failed events)
  summary      TEXT NULL   — ≤300 char human-readable description
  payload_json JSONB NULL  — bounded structured payload (caller's responsibility)

Usage:

    event_log = EventLog(dsn=os.environ["POSTGRES_DSN"])
    await event_log.setup()
    ...
    await event_log.insert_event(
        session_id="thread-abc",
        node_name="plan",
        phase="plan",
        status="completed",
        duration_ms=412,
        summary="Plan generated with 3 ops",
    )
    await event_log.close()

See roadmap9_production_graph_runtime_hardening.md — Milestone 9.1.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger("flowise_dev_agent.persistence.event_log")

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL_TABLE = """
CREATE TABLE IF NOT EXISTS session_events (
    session_id   TEXT        NOT NULL,
    seq          BIGINT      NOT NULL,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    node_name    TEXT        NOT NULL,
    phase        TEXT        NOT NULL,
    status       TEXT        NOT NULL,
    duration_ms  INT,
    summary      TEXT,
    payload_json JSONB,
    PRIMARY KEY (session_id, seq)
)
"""

_DDL_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_session_events_session_id "
    "ON session_events (session_id)"
)

# ---------------------------------------------------------------------------
# DML
# ---------------------------------------------------------------------------

_INSERT = """
INSERT INTO session_events
    (session_id, seq, node_name, phase, status, duration_ms, summary, payload_json)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
ON CONFLICT (session_id, seq) DO NOTHING
"""

_SELECT = """
SELECT seq, ts, node_name, phase, status, duration_ms, summary, payload_json
FROM session_events
WHERE session_id = %s AND seq > %s
ORDER BY seq
LIMIT %s
"""


# ---------------------------------------------------------------------------
# EventLog
# ---------------------------------------------------------------------------


class EventLog:
    """Writes node lifecycle events to the session_events Postgres table.

    Args:
        dsn: Postgres connection string (e.g. from POSTGRES_DSN env var).
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """Open connection and create session_events table if absent."""
        try:
            import psycopg  # type: ignore[import]
        except ImportError as exc:
            logger.error(
                "psycopg is not installed; event log disabled. "
                "Install with: pip install 'psycopg[binary]>=3.1'. %s",
                exc,
            )
            return

        try:
            conn = await psycopg.AsyncConnection.connect(
                self._dsn, autocommit=False
            )
            async with conn.cursor() as cur:
                await cur.execute(_DDL_TABLE)
                await cur.execute(_DDL_INDEX)
            await conn.commit()
            self._conn = conn
            logger.info("EventLog ready (Postgres)")
        except Exception as exc:
            logger.error(
                "EventLog: failed to connect to Postgres (%s); "
                "event log disabled.",
                exc,
            )
            self._conn = None

    async def close(self) -> None:
        """Close the Postgres connection."""
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception as exc:
                logger.debug("EventLog close error (ignored): %s", exc)
            finally:
                self._conn = None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def insert_event(
        self,
        session_id: str,
        node_name: str,
        phase: str,
        status: str,
        duration_ms: int | None = None,
        summary: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Insert one node lifecycle event.  Errors are logged and suppressed.

        Args:
            session_id:  LangGraph thread_id.
            node_name:   LangGraph node name (e.g. "plan", "patch").
            phase:       Logical phase label (e.g. "discover", "patch").
            status:      "started" | "completed" | "failed" | "interrupted".
            duration_ms: Elapsed milliseconds (set on completed/failed).
            summary:     ≤300 char human-readable description.
            payload:     Small structured dict (bounded — caller's responsibility).
        """
        if self._conn is None:
            return  # event log not available; silently skip

        # Nanosecond epoch gives a monotonically increasing BIGINT that is
        # unique within a session without a DB round-trip.
        seq = time.time_ns()

        if summary and len(summary) > 300:
            summary = summary[:297] + "..."

        payload_str: str | None = None
        if payload is not None:
            try:
                payload_str = json.dumps(payload, default=str)
            except Exception:
                payload_str = None

        try:
            async with self._conn.cursor() as cur:
                await cur.execute(
                    _INSERT,
                    (session_id, seq, node_name, phase, status,
                     duration_ms, summary, payload_str),
                )
            await self._conn.commit()
        except Exception as exc:
            logger.error(
                "EventLog: insert failed [%s/%s/%s]: %s",
                session_id, node_name, status, exc,
            )

    # ------------------------------------------------------------------
    # Read  (consumed by M9.2 SSE streaming)
    # ------------------------------------------------------------------

    async def get_events(
        self,
        session_id: str,
        after_seq: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return events for session_id with seq > after_seq, ordered by seq.

        Returns an empty list if the event log is unavailable.
        Used by the M9.2 SSE streaming endpoint.
        """
        if self._conn is None:
            return []

        try:
            async with self._conn.cursor() as cur:
                await cur.execute(_SELECT, (session_id, after_seq, limit))
                cols = [d.name for d in cur.description]
                rows = await cur.fetchall()
            return [dict(zip(cols, row)) for row in rows]
        except Exception as exc:
            logger.error("EventLog.get_events failed: %s", exc)
            return []
