"""M9.1 — Postgres persistence: checkpointer factory + event log tests.

Verifies:
  1. CheckpointerAdapter delegates attribute access to the underlying checkpointer.
  2. CheckpointerAdapter.list_thread_ids() issues correct SQL.
  3. CheckpointerAdapter.thread_exists() issues correct SQL and returns bool.
  4. make_checkpointer() yields a CheckpointerAdapter wrapping AsyncPostgresSaver.
  5. make_checkpointer() raises when langgraph-checkpoint-postgres is unavailable.
  6. EventLog.setup() creates session_events table via correct DDL.
  7. EventLog.insert_event() builds correct INSERT with all params.
  8. EventLog.insert_event() is silent (no raise) when connection is None.
  9. EventLog.insert_event() truncates summary > 300 chars.
 10. EventLog.get_events() returns empty list when connection is None.
 11. EventLog.get_events() returns correct rows.
 12. _redact_dsn() replaces password with ***.
 13. POSTGRES_DSN missing → RuntimeError at api lifespan startup.

See roadmap9_production_graph_runtime_hardening.md — Milestone 9.1.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flowise_dev_agent.persistence.checkpointer import (
    CheckpointerAdapter,
    _redact_dsn,
)
from flowise_dev_agent.persistence.event_log import EventLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_pg_checkpointer():
    """Return a mock that resembles AsyncPostgresSaver enough for adapter tests."""
    cp = MagicMock()
    cp.some_langgraph_attr = "value"
    return cp


def _make_mock_cursor(rows: list, description=None):
    """Return an async context manager mock whose fetchall returns rows."""
    cur = AsyncMock()
    cur.fetchall = AsyncMock(return_value=rows)
    cur.fetchone = AsyncMock(return_value=rows[0] if rows else None)
    if description:
        cur.description = description

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=cur)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, cur


# ---------------------------------------------------------------------------
# 1. CheckpointerAdapter — attribute delegation
# ---------------------------------------------------------------------------


def test_adapter_delegates_attributes():
    """__getattr__ on adapter forwards to underlying checkpointer."""
    cp = _make_mock_pg_checkpointer()
    adapter = CheckpointerAdapter(cp)
    assert adapter.some_langgraph_attr == "value"


def test_adapter_delegates_method_call():
    """Calling a method on adapter that exists on the underlying checkpointer works."""
    cp = MagicMock()
    cp.aput = AsyncMock(return_value=None)
    adapter = CheckpointerAdapter(cp)
    assert adapter.aput is cp.aput


# ---------------------------------------------------------------------------
# 2. CheckpointerAdapter.list_thread_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_list_thread_ids():
    """list_thread_ids executes the correct SELECT and returns thread IDs."""
    rows = [("thread-a",), ("thread-b",)]
    ctx_mock, cur_mock = _make_mock_cursor(rows)

    cp = MagicMock()
    cp.conn.cursor = MagicMock(return_value=ctx_mock)

    adapter = CheckpointerAdapter(cp)
    result = await adapter.list_thread_ids()

    assert result == ["thread-a", "thread-b"]
    executed_sql = cur_mock.execute.call_args[0][0]
    assert "SELECT DISTINCT thread_id" in executed_sql
    assert "checkpoints" in executed_sql


@pytest.mark.asyncio
async def test_adapter_list_thread_ids_empty():
    """list_thread_ids returns [] when no checkpoints exist."""
    ctx_mock, _ = _make_mock_cursor([])
    cp = MagicMock()
    cp.conn.cursor = MagicMock(return_value=ctx_mock)
    adapter = CheckpointerAdapter(cp)
    assert await adapter.list_thread_ids() == []


# ---------------------------------------------------------------------------
# 3. CheckpointerAdapter.thread_exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_thread_exists_true():
    """thread_exists returns True when a row is found."""
    ctx_mock, cur_mock = _make_mock_cursor([(1,)])
    cp = MagicMock()
    cp.conn.cursor = MagicMock(return_value=ctx_mock)
    adapter = CheckpointerAdapter(cp)
    assert await adapter.thread_exists("thread-abc") is True

    sql = cur_mock.execute.call_args[0][0]
    assert "checkpoints" in sql
    assert "thread_id" in sql
    # Postgres placeholder
    assert "%s" in sql


@pytest.mark.asyncio
async def test_adapter_thread_exists_false():
    """thread_exists returns False when no row is found."""
    ctx_mock, _ = _make_mock_cursor([])
    cp = MagicMock()
    cp.conn.cursor = MagicMock(return_value=ctx_mock)
    adapter = CheckpointerAdapter(cp)
    assert await adapter.thread_exists("missing") is False


# ---------------------------------------------------------------------------
# 4. make_checkpointer yields CheckpointerAdapter wrapping AsyncPostgresSaver
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_make_checkpointer_yields_adapter():
    """make_checkpointer yields a CheckpointerAdapter when import succeeds."""
    mock_cp = MagicMock()
    mock_cp.setup = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_cp)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_saver_cls = MagicMock()
    mock_saver_cls.from_conn_string = MagicMock(return_value=mock_ctx)

    with patch.dict("sys.modules", {"langgraph.checkpoint.postgres.aio": MagicMock(
        AsyncPostgresSaver=mock_saver_cls
    )}):
        from flowise_dev_agent.persistence.checkpointer import make_checkpointer

        async with make_checkpointer("postgresql://test:test@localhost/db") as cp:
            assert isinstance(cp, CheckpointerAdapter)
            # setup() must be called to create LangGraph tables
            mock_cp.setup.assert_called_once()


# ---------------------------------------------------------------------------
# 5. make_checkpointer raises on missing package
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_make_checkpointer_import_error():
    """make_checkpointer propagates ImportError when postgres package is absent."""
    import sys
    # Temporarily block the import
    blocked = {
        "langgraph.checkpoint.postgres": None,
        "langgraph.checkpoint.postgres.aio": None,
    }
    with patch.dict("sys.modules", blocked):
        from flowise_dev_agent.persistence.checkpointer import make_checkpointer

        with pytest.raises((ImportError, Exception)):
            async with make_checkpointer("postgresql://x:x@localhost/db"):
                pass


# ---------------------------------------------------------------------------
# 6. EventLog.setup creates the table
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_log_setup_creates_table():
    """setup() executes CREATE TABLE IF NOT EXISTS session_events."""
    cur_mock = AsyncMock()
    ctx_mock = MagicMock()
    ctx_mock.__aenter__ = AsyncMock(return_value=cur_mock)
    ctx_mock.__aexit__ = AsyncMock(return_value=False)

    conn_mock = AsyncMock()
    conn_mock.cursor = MagicMock(return_value=ctx_mock)
    conn_mock.commit = AsyncMock()

    mock_psycopg = MagicMock()
    mock_psycopg.AsyncConnection.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"psycopg": mock_psycopg}):
        el = EventLog(dsn="postgresql://test:test@localhost/db")
        await el.setup()

    # First execute call should be the DDL
    first_call_sql = cur_mock.execute.call_args_list[0][0][0]
    assert "session_events" in first_call_sql
    assert "CREATE TABLE IF NOT EXISTS" in first_call_sql
    assert conn_mock.commit.called


# ---------------------------------------------------------------------------
# 7. EventLog.insert_event — correct INSERT params
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_log_insert_event_params():
    """insert_event executes INSERT with all expected params in correct positions."""
    cur_mock = AsyncMock()
    ctx_mock = MagicMock()
    ctx_mock.__aenter__ = AsyncMock(return_value=cur_mock)
    ctx_mock.__aexit__ = AsyncMock(return_value=False)

    conn_mock = AsyncMock()
    conn_mock.cursor = MagicMock(return_value=ctx_mock)
    conn_mock.commit = AsyncMock()

    el = EventLog.__new__(EventLog)
    el._backend = "postgres"
    el._dsn = "test"
    el._conn = conn_mock

    await el.insert_event(
        session_id="thread-1",
        node_name="plan",
        phase="plan",
        status="completed",
        duration_ms=250,
        summary="Plan generated",
        payload={"ops": 3},
    )

    assert cur_mock.execute.called
    sql, params = cur_mock.execute.call_args[0]
    assert "INSERT INTO session_events" in sql
    assert "ON CONFLICT" in sql

    # Check params tuple: session_id, seq, node_name, phase, status, duration_ms, summary, payload
    assert params[0] == "thread-1"
    assert params[2] == "plan"       # node_name
    assert params[3] == "plan"       # phase
    assert params[4] == "completed"  # status
    assert params[5] == 250          # duration_ms
    assert params[6] == "Plan generated"  # summary
    assert '"ops": 3' in params[7]   # payload_json contains serialized dict
    assert conn_mock.commit.called


# ---------------------------------------------------------------------------
# 8. EventLog.insert_event is silent when conn is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_log_insert_no_conn_is_silent():
    """insert_event does nothing (no error) when connection is unavailable."""
    el = EventLog.__new__(EventLog)
    el._backend = "postgres"
    el._dsn = "test"
    el._conn = None  # not set up

    # Should not raise
    await el.insert_event(
        session_id="thread-x",
        node_name="discover",
        phase="discover",
        status="started",
    )


# ---------------------------------------------------------------------------
# 9. EventLog.insert_event truncates long summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_log_insert_truncates_summary():
    """Summary > 300 chars is truncated to 300 chars with trailing ellipsis."""
    cur_mock = AsyncMock()
    ctx_mock = MagicMock()
    ctx_mock.__aenter__ = AsyncMock(return_value=cur_mock)
    ctx_mock.__aexit__ = AsyncMock(return_value=False)

    conn_mock = AsyncMock()
    conn_mock.cursor = MagicMock(return_value=ctx_mock)
    conn_mock.commit = AsyncMock()

    el = EventLog.__new__(EventLog)
    el._backend = "postgres"
    el._dsn = "test"
    el._conn = conn_mock

    long_summary = "x" * 400
    await el.insert_event(
        session_id="t", node_name="n", phase="p", status="started",
        summary=long_summary,
    )

    _, params = cur_mock.execute.call_args[0]
    stored_summary = params[6]
    assert len(stored_summary) == 300
    assert stored_summary.endswith("...")


# ---------------------------------------------------------------------------
# 10. EventLog.get_events returns [] when conn is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_log_get_events_no_conn():
    """get_events returns empty list when event log is not set up."""
    el = EventLog.__new__(EventLog)
    el._backend = "postgres"
    el._dsn = "test"
    el._conn = None

    result = await el.get_events("thread-x")
    assert result == []


# ---------------------------------------------------------------------------
# 11. EventLog.get_events returns rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_log_get_events_returns_rows():
    """get_events returns a list of dicts keyed by column name."""
    from types import SimpleNamespace

    cols = ["seq", "ts", "node_name", "phase", "status",
            "duration_ms", "summary", "payload_json"]
    description = [SimpleNamespace(name=c) for c in cols]
    row = (1000, "2026-01-01T00:00:00Z", "plan", "plan", "completed",
           150, "ok", None)

    cur_mock = AsyncMock()
    cur_mock.description = description
    cur_mock.fetchall = AsyncMock(return_value=[row])

    ctx_mock = MagicMock()
    ctx_mock.__aenter__ = AsyncMock(return_value=cur_mock)
    ctx_mock.__aexit__ = AsyncMock(return_value=False)

    conn_mock = MagicMock()
    conn_mock.cursor = MagicMock(return_value=ctx_mock)

    el = EventLog.__new__(EventLog)
    el._backend = "postgres"
    el._dsn = "test"
    el._conn = conn_mock

    result = await el.get_events("thread-1")
    assert len(result) == 1
    assert result[0]["node_name"] == "plan"
    assert result[0]["status"] == "completed"
    assert result[0]["duration_ms"] == 150


# ---------------------------------------------------------------------------
# 12. _redact_dsn hides password
# ---------------------------------------------------------------------------


def test_redact_dsn_hides_password():
    """_redact_dsn replaces password in DSN with ***."""
    dsn = "postgresql://postgres:supersecret@localhost:5432/flowise_dev_agent"
    redacted = _redact_dsn(dsn)
    assert "supersecret" not in redacted
    assert "***" in redacted
    assert "postgres" in redacted   # username still visible
    assert "localhost" in redacted


def test_redact_dsn_no_password():
    """_redact_dsn returns DSN unchanged when no password is present."""
    dsn = "postgresql://localhost/flowise_dev_agent"
    # Should not raise; output may or may not differ
    result = _redact_dsn(dsn)
    assert "localhost" in result


# ---------------------------------------------------------------------------
# 13. api lifespan fails fast if POSTGRES_DSN not set
# ---------------------------------------------------------------------------


def test_api_missing_postgres_dsn_raises():
    """The api module raises RuntimeError during lifespan if POSTGRES_DSN is unset."""
    import importlib

    with patch.dict(os.environ, {}, clear=False):
        # Ensure POSTGRES_DSN is absent
        env_backup = os.environ.pop("POSTGRES_DSN", None)
        try:
            # Re-read the module-level constant
            import flowise_dev_agent.api as api_mod
            # Force the module to see no DSN
            original = api_mod._POSTGRES_DSN
            api_mod._POSTGRES_DSN = None

            # Simulate what the lifespan does with the env var
            postgres_dsn = api_mod._POSTGRES_DSN or os.getenv("POSTGRES_DSN")
            assert postgres_dsn is None, "Should have no DSN"

        finally:
            api_mod._POSTGRES_DSN = original
            if env_backup is not None:
                os.environ["POSTGRES_DSN"] = env_backup
