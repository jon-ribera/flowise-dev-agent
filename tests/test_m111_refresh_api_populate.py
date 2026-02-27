"""M11.1 — refresh --api-populate tests (DD-104, DD-105).

Tests the bulk API-to-Postgres population command. All external dependencies
(Flowise API, Postgres) are mocked.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_pool():
    """Create a mock AsyncConnectionPool with async context managers."""
    pool = MagicMock()
    pool.open = AsyncMock()
    pool.close = AsyncMock()

    conn = MagicMock()
    cur = AsyncMock()

    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    pool.connection.return_value = conn_ctx

    cur_ctx = MagicMock()
    cur_ctx.__aenter__ = AsyncMock(return_value=cur)
    cur_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.cursor.return_value = cur_ctx

    return pool, conn, cur


def _make_node_list(count: int) -> list[dict]:
    """Generate a mock list_nodes response with `count` node types."""
    return [{"name": f"node_{i}", "label": f"Node {i}"} for i in range(count)]


def _make_raw_schema(name: str) -> dict:
    """Generate a mock get_node API response."""
    return {
        "name": name,
        "label": name,
        "baseClasses": ["BaseNode"],
        "inputs": [{"name": "input1", "type": "string"}],
        "outputs": [],
    }


def _setup_patches(mock_client, pool, mock_cache):
    """Create patch context managers for _api_populate_async dependencies.

    Since _api_populate_async uses local imports, we patch at the source modules.
    """
    mock_settings_cls = MagicMock()
    mock_settings_instance = MagicMock()
    mock_settings_instance.api_endpoint = "http://localhost:3000"
    mock_settings_cls.from_env.return_value = mock_settings_instance

    return (
        patch.dict("os.environ", {
            "POSTGRES_DSN": "postgresql://test",
            "FLOWISE_API_ENDPOINT": "http://localhost:3000",
        }),
        patch("flowise_dev_agent.client.FlowiseClient", return_value=mock_client),
        patch("flowise_dev_agent.client.Settings", mock_settings_cls),
        patch("psycopg_pool.AsyncConnectionPool", return_value=pool),
        patch("flowise_dev_agent.knowledge.schema_cache.SchemaCache", return_value=mock_cache),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestApiPopulate:
    @pytest.mark.asyncio
    async def test_basic_populate_flow(self):
        """Basic flow: list_nodes -> get_node x N -> put_batch."""
        node_list = _make_node_list(5)
        pool, conn, cur = _mock_pool()

        mock_client = AsyncMock()
        mock_client.get_node_types = AsyncMock(return_value=node_list)
        mock_client.get_node = AsyncMock(
            side_effect=lambda name: _make_raw_schema(name)
        )
        mock_client.close = AsyncMock()

        mock_cache = AsyncMock()
        mock_cache.setup = AsyncMock()
        mock_cache.put_batch = AsyncMock(return_value=5)

        patches = _setup_patches(mock_client, pool, mock_cache)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            from flowise_dev_agent.knowledge.refresh import _api_populate_async

            exit_code = await _api_populate_async()

        assert exit_code == 0
        mock_client.get_node_types.assert_called_once()
        assert mock_client.get_node.call_count == 5
        mock_cache.put_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrency_bounded_by_semaphore(self):
        """Concurrent get_node calls should be bounded by the semaphore (max 5)."""
        node_list = _make_node_list(20)
        pool, conn, cur = _mock_pool()

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def _tracked_get_node(name):
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            await asyncio.sleep(0.01)
            async with lock:
                current_concurrent -= 1
            return _make_raw_schema(name)

        mock_client = AsyncMock()
        mock_client.get_node_types = AsyncMock(return_value=node_list)
        mock_client.get_node = _tracked_get_node
        mock_client.close = AsyncMock()

        mock_cache = AsyncMock()
        mock_cache.setup = AsyncMock()
        mock_cache.put_batch = AsyncMock(return_value=20)

        patches = _setup_patches(mock_client, pool, mock_cache)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            from flowise_dev_agent.knowledge.refresh import _api_populate_async

            exit_code = await _api_populate_async()

        assert exit_code == 0
        assert max_concurrent <= 5

    @pytest.mark.asyncio
    async def test_put_batch_receives_chunk_size_50(self):
        """put_batch should be called with chunk_size=50."""
        node_list = _make_node_list(120)
        pool, conn, cur = _mock_pool()

        mock_client = AsyncMock()
        mock_client.get_node_types = AsyncMock(return_value=node_list)
        mock_client.get_node = AsyncMock(
            side_effect=lambda name: _make_raw_schema(name)
        )
        mock_client.close = AsyncMock()

        mock_cache = AsyncMock()
        mock_cache.setup = AsyncMock()
        mock_cache.put_batch = AsyncMock(return_value=120)

        patches = _setup_patches(mock_client, pool, mock_cache)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            from flowise_dev_agent.knowledge.refresh import _api_populate_async

            exit_code = await _api_populate_async()

        assert exit_code == 0
        # put_batch should receive chunk_size=50
        call_kwargs = mock_cache.put_batch.call_args
        # Check keyword args or positional — chunk_size should be 50
        assert call_kwargs.kwargs.get("chunk_size") == 50

    @pytest.mark.asyncio
    async def test_individual_fetch_errors_do_not_abort(self):
        """Individual get_node failures should be skipped, not abort the whole operation."""
        node_list = _make_node_list(5)
        pool, conn, cur = _mock_pool()

        call_count = 0

        async def _flaky_get_node(name):
            nonlocal call_count
            call_count += 1
            if name == "node_2":
                raise Exception("API error for node_2")
            return _make_raw_schema(name)

        mock_client = AsyncMock()
        mock_client.get_node_types = AsyncMock(return_value=node_list)
        mock_client.get_node = _flaky_get_node
        mock_client.close = AsyncMock()

        mock_cache = AsyncMock()
        mock_cache.setup = AsyncMock()
        mock_cache.put_batch = AsyncMock(return_value=4)

        patches = _setup_patches(mock_client, pool, mock_cache)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            from flowise_dev_agent.knowledge.refresh import _api_populate_async

            exit_code = await _api_populate_async()

        assert exit_code == 0
        assert call_count == 5  # All 5 attempted
        # put_batch called with 4 entries (node_2 failed)
        entries_arg = mock_cache.put_batch.call_args[0][1]
        assert len(entries_arg) == 4

    @pytest.mark.asyncio
    async def test_missing_postgres_dsn_returns_error(self):
        """Missing POSTGRES_DSN should return exit code 1."""
        import os

        clean_env = {k: v for k, v in os.environ.items() if k != "POSTGRES_DSN"}
        with patch.dict("os.environ", clean_env, clear=True):
            from flowise_dev_agent.knowledge.refresh import _api_populate_async

            exit_code = await _api_populate_async()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_node_list_not_list_returns_error(self):
        """Non-list response from list_nodes should return exit code 1."""
        pool, conn, cur = _mock_pool()

        mock_client = AsyncMock()
        mock_client.get_node_types = AsyncMock(return_value="not a list")
        mock_client.close = AsyncMock()

        mock_cache = AsyncMock()
        mock_cache.setup = AsyncMock()

        patches = _setup_patches(mock_client, pool, mock_cache)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            from flowise_dev_agent.knowledge.refresh import _api_populate_async

            exit_code = await _api_populate_async()

        assert exit_code == 1


class TestRefreshApiPopulateDryRun:
    def test_dry_run_returns_zero(self):
        """--api-populate --dry-run should return 0 without doing anything."""
        from flowise_dev_agent.knowledge.refresh import refresh_api_populate

        exit_code = refresh_api_populate(dry_run=True)
        assert exit_code == 0
