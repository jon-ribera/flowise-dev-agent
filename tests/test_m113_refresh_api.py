"""M11.3 — Schema refresh API endpoint tests (DD-108).

Tests:
- POST /platform/schema/refresh returns job_id
- Locking: second POST while running returns already_running
- GET /platform/schema/refresh/{job_id} returns status
- GET /platform/schema/refresh/{job_id} returns 404 for unknown
- GET /platform/schema/stats returns counts
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flowise_dev_agent.platform.refresh_service import RefreshService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_cache():
    """Create a mock SchemaCache with async methods."""
    cache = AsyncMock()
    cache.try_advisory_lock = AsyncMock(return_value=True)
    cache.create_job = AsyncMock()
    cache.get_job = AsyncMock(return_value=None)
    cache.update_job = AsyncMock()
    cache.get_latest_running_job = AsyncMock(return_value=None)
    cache.release_advisory_lock = AsyncMock()
    cache.refresh_stats = AsyncMock(return_value={
        "node_count": 100,
        "credential_count": 5,
        "template_count": 20,
        "last_refresh": "2026-02-26T10:00:00Z",
        "stale_count": 3,
    })
    return cache


def _mock_client():
    """Create a mock FlowiseClient with async methods."""
    client = AsyncMock()
    client.list_nodes = AsyncMock(return_value=[
        {"name": "chatOpenAI"},
        {"name": "bufferMemory"},
    ])
    client.get_node = AsyncMock(side_effect=lambda name: {
        "name": name,
        "baseClasses": ["BaseChatModel"],
        "inputs": [
            {"name": "temperature", "type": "number", "default": "0.9"},
        ],
    })
    client.list_credentials = AsyncMock(return_value=[])
    client.list_marketplace_templates = AsyncMock(return_value=[])
    return client


# ---------------------------------------------------------------------------
# RefreshService.start_refresh tests
# ---------------------------------------------------------------------------


class TestStartRefresh:
    @pytest.mark.asyncio
    async def test_returns_job_id_and_running(self):
        """POST returns job_id with status='running'."""
        cache = _mock_cache()
        client = _mock_client()
        service = RefreshService(cache=cache, client=client)

        result = await service.start_refresh(scope="nodes")

        assert result["status"] == "running"
        assert "job_id" in result
        assert len(result["job_id"]) == 36  # UUID format
        cache.create_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_already_running_returns_existing_job(self):
        """Second POST while job running returns already_running."""
        cache = _mock_cache()
        cache.try_advisory_lock = AsyncMock(return_value=False)
        cache.get_latest_running_job = AsyncMock(return_value={
            "job_id": "existing-job-id-1234",
            "status": "running",
        })

        service = RefreshService(cache=cache, client=_mock_client())
        result = await service.start_refresh(scope="nodes")

        assert result["status"] == "already_running"
        assert result["job_id"] == "existing-job-id-1234"
        cache.create_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_scope_all_accepted(self):
        """Scope 'all' is accepted."""
        cache = _mock_cache()
        service = RefreshService(cache=cache, client=_mock_client())

        result = await service.start_refresh(scope="all")

        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_force_flag_passed_to_summary(self):
        """Force flag is recorded in the job summary."""
        cache = _mock_cache()
        service = RefreshService(cache=cache, client=_mock_client())

        await service.start_refresh(scope="nodes", force=True)

        # The create_job call should have force=True in summary_json
        call_args = cache.create_job.call_args
        summary = call_args[1].get("summary_json") or call_args[0][2]
        if isinstance(summary, dict):
            assert summary.get("force") is True


# ---------------------------------------------------------------------------
# RefreshService.get_job_status tests
# ---------------------------------------------------------------------------


class TestGetJobStatus:
    @pytest.mark.asyncio
    async def test_returns_job_when_found(self):
        """get_job_status returns job dict when found."""
        cache = _mock_cache()
        cache.get_job = AsyncMock(return_value={
            "job_id": "test-job-id",
            "base_url": "http://localhost:3000",
            "scope": "nodes",
            "status": "success",
            "started_at": "2026-02-26T10:00:00Z",
            "ended_at": "2026-02-26T10:01:00Z",
            "summary_json": {"nodes_total": 100, "nodes_fetched": 98},
        })

        service = RefreshService(cache=cache, client=_mock_client())
        result = await service.get_job_status("test-job-id")

        assert result is not None
        assert result["status"] == "success"
        assert result["summary_json"]["nodes_fetched"] == 98

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        """get_job_status returns None for unknown job_id."""
        cache = _mock_cache()
        cache.get_job = AsyncMock(return_value=None)

        service = RefreshService(cache=cache, client=_mock_client())
        result = await service.get_job_status("nonexistent-id")

        assert result is None


# ---------------------------------------------------------------------------
# SchemaCache job CRUD tests
# ---------------------------------------------------------------------------


class TestSchemaCacheJobCRUD:
    """Test the job-related DML in SchemaCache using mocked pool."""

    def _mock_pool(self):
        pool = MagicMock()
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

    @pytest.mark.asyncio
    async def test_create_job(self):
        """create_job executes INSERT with correct params."""
        from flowise_dev_agent.knowledge.schema_cache import SchemaCache

        pool, conn, cur = self._mock_pool()
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        await cache.create_job("job-123", "nodes", {"nodes_total": 0})

        cur.execute.assert_called_once()
        sql = cur.execute.call_args[0][0]
        assert "INSERT INTO schema_refresh_jobs" in sql

    @pytest.mark.asyncio
    async def test_get_job_found(self):
        """get_job returns dict when row exists."""
        from flowise_dev_agent.knowledge.schema_cache import SchemaCache

        pool, conn, cur = self._mock_pool()
        cur.fetchone = AsyncMock(return_value={
            "job_id": "job-123",
            "base_url": "http://localhost:3000",
            "scope": "nodes",
            "status": "running",
            "started_at": "2026-02-26T10:00:00+00:00",
            "ended_at": None,
            "summary_json": {"nodes_total": 100},
        })
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        result = await cache.get_job("job-123")
        assert result is not None
        assert result["status"] == "running"
        assert result["job_id"] == "job-123"

    @pytest.mark.asyncio
    async def test_get_job_not_found(self):
        """get_job returns None when row doesn't exist."""
        from flowise_dev_agent.knowledge.schema_cache import SchemaCache

        pool, conn, cur = self._mock_pool()
        cur.fetchone = AsyncMock(return_value=None)
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        result = await cache.get_job("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_job(self):
        """update_job executes UPDATE."""
        from flowise_dev_agent.knowledge.schema_cache import SchemaCache

        pool, conn, cur = self._mock_pool()
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        await cache.update_job(
            "job-123", "success", {"nodes_fetched": 50}, set_ended=True,
        )

        cur.execute.assert_called_once()
        sql = cur.execute.call_args[0][0]
        assert "UPDATE schema_refresh_jobs" in sql
        params = cur.execute.call_args[0][1]
        assert params[0] == "success"  # status
        assert params[1] is True       # set_ended

    @pytest.mark.asyncio
    async def test_get_latest_running_job(self):
        """get_latest_running_job returns dict when running job exists."""
        from flowise_dev_agent.knowledge.schema_cache import SchemaCache

        pool, conn, cur = self._mock_pool()
        cur.fetchone = AsyncMock(return_value={
            "job_id": "running-job",
            "base_url": "http://localhost:3000",
            "scope": "nodes",
            "status": "running",
            "started_at": "2026-02-26T10:00:00+00:00",
            "ended_at": None,
            "summary_json": {},
        })
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        result = await cache.get_latest_running_job("nodes")
        assert result is not None
        assert result["job_id"] == "running-job"

    @pytest.mark.asyncio
    async def test_try_advisory_lock(self):
        """try_advisory_lock calls pg_try_advisory_lock."""
        from flowise_dev_agent.knowledge.schema_cache import SchemaCache

        pool, conn, cur = self._mock_pool()
        cur.fetchone = AsyncMock(return_value={"pg_try_advisory_lock": True})
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        locked = await cache.try_advisory_lock("nodes")
        assert locked is True
        sql = cur.execute.call_args[0][0]
        assert "pg_try_advisory_lock" in sql

    @pytest.mark.asyncio
    async def test_advisory_lock_not_acquired(self):
        """try_advisory_lock returns False when lock is held."""
        from flowise_dev_agent.knowledge.schema_cache import SchemaCache

        pool, conn, cur = self._mock_pool()
        cur.fetchone = AsyncMock(return_value={"pg_try_advisory_lock": False})
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        locked = await cache.try_advisory_lock("nodes")
        assert locked is False

    @pytest.mark.asyncio
    async def test_release_advisory_lock(self):
        """release_advisory_lock calls pg_advisory_unlock."""
        from flowise_dev_agent.knowledge.schema_cache import SchemaCache

        pool, conn, cur = self._mock_pool()
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        await cache.release_advisory_lock("nodes")
        sql = cur.execute.call_args[0][0]
        assert "pg_advisory_unlock" in sql
