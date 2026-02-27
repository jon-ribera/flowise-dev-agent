"""M11.3 — Schema refresh executor tests (DD-108).

Tests:
- Bounded concurrency (no more than N concurrent get_node calls)
- Batch writes with chunk size 50
- Failure handling updates status=failed
- Progress updates during execution
- Scope filtering (nodes, credentials, marketplace, all)
- Advisory lock released on completion and on failure
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from flowise_dev_agent.platform.refresh_service import (
    RefreshService,
    _BATCH_CHUNK_SIZE,
    _FETCH_CONCURRENCY,
)


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
    cache.put_batch = AsyncMock(return_value=10)
    cache.refresh_stats = AsyncMock(return_value={})
    return cache


def _mock_client(node_count: int = 10):
    """Create a mock FlowiseClient with configurable node count."""
    client = AsyncMock()
    client.list_nodes = AsyncMock(
        return_value=[{"name": f"node_{i}"} for i in range(node_count)]
    )
    client.get_node = AsyncMock(side_effect=lambda name: {
        "name": name,
        "baseClasses": ["BaseChatModel"],
        "inputs": [
            {"name": "temperature", "type": "number", "default": "0.9"},
        ],
    })
    client.list_credentials = AsyncMock(return_value=[
        {"id": "cred-1", "name": "openAI", "type": "openAIApi"},
    ])
    client.list_marketplace_templates = AsyncMock(return_value=[
        {"templateName": "rag-basic", "type": "CHATFLOW"},
    ])
    return client


# ---------------------------------------------------------------------------
# Bounded concurrency tests
# ---------------------------------------------------------------------------


class TestBoundedConcurrency:
    @pytest.mark.asyncio
    async def test_max_concurrent_get_node_calls(self):
        """No more than _FETCH_CONCURRENCY concurrent get_node calls."""
        cache = _mock_cache()
        concurrent_count = 0
        max_concurrent = 0
        node_count = 20

        client = _mock_client(node_count=node_count)

        # Replace get_node with a tracking mock
        async def _tracking_get_node(name):
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.01)  # simulate network delay
            concurrent_count -= 1
            return {
                "name": name,
                "baseClasses": ["Base"],
                "inputs": [],
            }

        client.get_node = AsyncMock(side_effect=_tracking_get_node)

        service = RefreshService(cache=cache, client=client)
        # Run _execute directly instead of start_refresh (which uses create_task)
        await service._execute("test-job-id", "nodes", False)

        assert max_concurrent <= _FETCH_CONCURRENCY
        assert max_concurrent > 0  # at least some concurrency
        assert client.get_node.call_count == node_count

    @pytest.mark.asyncio
    async def test_concurrency_constant_value(self):
        """_FETCH_CONCURRENCY is 5 (design spec)."""
        assert _FETCH_CONCURRENCY == 5


# ---------------------------------------------------------------------------
# Batch write tests
# ---------------------------------------------------------------------------


class TestBatchWrites:
    @pytest.mark.asyncio
    async def test_batch_chunk_size_constant(self):
        """_BATCH_CHUNK_SIZE is 50 (design spec)."""
        assert _BATCH_CHUNK_SIZE == 50

    @pytest.mark.asyncio
    async def test_put_batch_called_with_node_entries(self):
        """Executor calls put_batch with fetched node schemas."""
        cache = _mock_cache()
        client = _mock_client(node_count=5)

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "nodes", False)

        # put_batch should be called for nodes
        cache.put_batch.assert_called()
        # Find the call with schema_kind="node"
        node_calls = [
            c for c in cache.put_batch.call_args_list
            if c[0][0] == "node" or c[1].get("schema_kind") == "node"
        ]
        # Should have at least one batch call for nodes
        # The call args: put_batch("node", entries, ttl_seconds=86400, chunk_size=50)
        found_node_batch = False
        for c in cache.put_batch.call_args_list:
            args = c[0]
            if len(args) >= 1 and args[0] == "node":
                found_node_batch = True
                entries = args[1]
                assert len(entries) == 5
                break
        assert found_node_batch, "put_batch should be called with schema_kind='node'"


# ---------------------------------------------------------------------------
# Failure handling tests
# ---------------------------------------------------------------------------


class TestFailureHandling:
    @pytest.mark.asyncio
    async def test_node_fetch_failure_increments_failed_count(self):
        """Individual get_node failures are counted, don't crash the job."""
        cache = _mock_cache()
        client = _mock_client(node_count=3)

        call_count = 0
        async def _flaky_get_node(name):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Network error")
            return {
                "name": name,
                "baseClasses": ["Base"],
                "inputs": [],
            }

        client.get_node = AsyncMock(side_effect=_flaky_get_node)

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "nodes", False)

        # Job should still complete as success (partial failures are OK)
        final_update = cache.update_job.call_args_list[-1]
        status = final_update[0][1]
        assert status == "success"

        # Summary should show the failure
        summary = final_update[0][2]
        assert summary["nodes_failed"] == 1
        assert summary["nodes_fetched"] == 2

    @pytest.mark.asyncio
    async def test_list_nodes_failure_marks_error(self):
        """If list_nodes returns non-list, error is recorded."""
        cache = _mock_cache()
        client = _mock_client()
        client.list_nodes = AsyncMock(return_value="unexpected")

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "nodes", False)

        # Should still succeed but with error noted
        final_update = cache.update_job.call_args_list[-1]
        summary = final_update[0][2]
        assert any("non-list" in e for e in summary["errors"])

    @pytest.mark.asyncio
    async def test_catastrophic_failure_marks_job_failed(self):
        """Unhandled exception marks job as failed."""
        cache = _mock_cache()
        client = _mock_client()
        client.list_nodes = AsyncMock(side_effect=RuntimeError("Connection refused"))

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "nodes", False)

        final_update = cache.update_job.call_args_list[-1]
        status = final_update[0][1]
        assert status == "failed"

    @pytest.mark.asyncio
    async def test_advisory_lock_released_on_success(self):
        """Advisory lock is released after successful completion."""
        cache = _mock_cache()
        service = RefreshService(cache=cache, client=_mock_client(node_count=2))
        await service._execute("test-job-id", "nodes", False)
        cache.release_advisory_lock.assert_called_once_with("nodes")

    @pytest.mark.asyncio
    async def test_advisory_lock_released_on_failure(self):
        """Advisory lock is released even on failure."""
        cache = _mock_cache()
        client = _mock_client()
        client.list_nodes = AsyncMock(side_effect=RuntimeError("boom"))

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "nodes", False)

        cache.release_advisory_lock.assert_called_once_with("nodes")


# ---------------------------------------------------------------------------
# Scope filtering tests
# ---------------------------------------------------------------------------


class TestScopeFiltering:
    @pytest.mark.asyncio
    async def test_scope_nodes_only_fetches_nodes(self):
        """scope='nodes' only calls list_nodes/get_node."""
        cache = _mock_cache()
        client = _mock_client(node_count=2)

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "nodes", False)

        client.list_nodes.assert_called_once()
        client.list_credentials.assert_not_called()
        client.list_marketplace_templates.assert_not_called()

    @pytest.mark.asyncio
    async def test_scope_credentials_only(self):
        """scope='credentials' only calls list_credentials."""
        cache = _mock_cache()
        client = _mock_client()

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "credentials", False)

        client.list_nodes.assert_not_called()
        client.list_credentials.assert_called_once()
        client.list_marketplace_templates.assert_not_called()

    @pytest.mark.asyncio
    async def test_scope_marketplace_only(self):
        """scope='marketplace' only calls list_marketplace_templates."""
        cache = _mock_cache()
        client = _mock_client()

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "marketplace", False)

        client.list_nodes.assert_not_called()
        client.list_credentials.assert_not_called()
        client.list_marketplace_templates.assert_called_once()

    @pytest.mark.asyncio
    async def test_scope_all_fetches_everything(self):
        """scope='all' calls all three fetch methods."""
        cache = _mock_cache()
        client = _mock_client(node_count=2)

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "all", False)

        client.list_nodes.assert_called_once()
        client.list_credentials.assert_called_once()
        client.list_marketplace_templates.assert_called_once()


# ---------------------------------------------------------------------------
# Progress update tests
# ---------------------------------------------------------------------------


class TestProgressUpdates:
    @pytest.mark.asyncio
    async def test_progress_updated_during_execution(self):
        """Job summary is updated incrementally during node fetch."""
        cache = _mock_cache()
        client = _mock_client(node_count=15)

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "nodes", False)

        # update_job should be called multiple times:
        # at least once for initial nodes_total, progress updates, and final
        assert cache.update_job.call_count >= 2

    @pytest.mark.asyncio
    async def test_final_summary_has_correct_counts(self):
        """Final summary has accurate node counts."""
        cache = _mock_cache()
        client = _mock_client(node_count=5)

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "nodes", False)

        final_update = cache.update_job.call_args_list[-1]
        summary = final_update[0][2]
        assert summary["nodes_total"] == 5
        assert summary["nodes_fetched"] == 5
        assert summary["nodes_failed"] == 0

    @pytest.mark.asyncio
    async def test_credential_count_in_summary(self):
        """Credential fetch count appears in summary."""
        cache = _mock_cache()
        client = _mock_client()

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "credentials", False)

        final_update = cache.update_job.call_args_list[-1]
        summary = final_update[0][2]
        assert summary["credentials_fetched"] == 1

    @pytest.mark.asyncio
    async def test_template_count_in_summary(self):
        """Template fetch count appears in summary."""
        cache = _mock_cache()
        client = _mock_client()

        service = RefreshService(cache=cache, client=client)
        await service._execute("test-job-id", "marketplace", False)

        final_update = cache.update_job.call_args_list[-1]
        summary = final_update[0][2]
        assert summary["templates_fetched"] == 1
