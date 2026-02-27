"""M11.1 — SchemaCache unit tests (DD-104).

Tests the Postgres-backed schema cache module in isolation using mocked
database connections. No real Postgres or Flowise instance required.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flowise_dev_agent.knowledge.schema_cache import (
    SchemaCache,
    _content_hash,
    _strip_credential_secrets,
    _CRED_BANNED_KEYS,
    _CRED_SCHEMA_ALLOWLIST,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_pool():
    """Create a mock AsyncConnectionPool with cursor context managers.

    psycopg pattern: pool.connection() is async CM, conn.cursor() is sync
    returning an async CM.
    """
    pool = MagicMock()
    conn = MagicMock()   # sync object — cursor() is a regular method
    cur = AsyncMock()

    # pool.connection() → async context manager → conn
    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    pool.connection.return_value = conn_ctx

    # conn.cursor() → sync call returning async context manager → cur
    cur_ctx = MagicMock()
    cur_ctx.__aenter__ = AsyncMock(return_value=cur)
    cur_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.cursor.return_value = cur_ctx

    return pool, conn, cur


# ---------------------------------------------------------------------------
# _content_hash tests
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_deterministic(self):
        schema = {"name": "chatOpenAI", "type": "node"}
        h1 = _content_hash(schema)
        h2 = _content_hash(schema)
        assert h1 == h2

    def test_key_order_independent(self):
        s1 = {"b": 2, "a": 1}
        s2 = {"a": 1, "b": 2}
        assert _content_hash(s1) == _content_hash(s2)

    def test_different_data_different_hash(self):
        s1 = {"name": "chatOpenAI"}
        s2 = {"name": "openAIEmbeddings"}
        assert _content_hash(s1) != _content_hash(s2)

    def test_hash_is_sha256_hex(self):
        h = _content_hash({"x": 1})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# _strip_credential_secrets tests
# ---------------------------------------------------------------------------


class TestStripCredentialSecrets:
    def test_clean_entry_unchanged(self):
        entry = {"credential_id": "abc", "name": "test", "type": "openAIApi"}
        result = _strip_credential_secrets(entry)
        assert result == entry

    def test_strips_encryptedData(self):
        entry = {
            "credential_id": "abc",
            "name": "test",
            "encryptedData": "SUPERSECRET",
        }
        result = _strip_credential_secrets(entry)
        assert "encryptedData" not in result
        assert result["credential_id"] == "abc"
        assert result["name"] == "test"

    def test_strips_multiple_banned_keys(self):
        entry = {
            "credential_id": "abc",
            "apiKey": "sk-xxx",
            "password": "hunter2",
            "plainDataObj": {"key": "val"},
        }
        result = _strip_credential_secrets(entry)
        assert set(result.keys()) == {"credential_id"}

    def test_preserves_allowlisted_keys_only(self):
        entry = {
            "credential_id": "id1",
            "name": "n",
            "credentialName": "openAIApi",
            "type": "openAIApi",
            "tags": ["tag1"],
            "created_at": "2026-01-01",
            "updated_at": "2026-02-01",
            "random_field": "dropped",
        }
        result = _strip_credential_secrets(entry)
        assert "random_field" not in result
        assert set(result.keys()).issubset(_CRED_SCHEMA_ALLOWLIST)


# ---------------------------------------------------------------------------
# SchemaCache.setup tests
# ---------------------------------------------------------------------------


class TestSchemaCacheSetup:
    @pytest.mark.asyncio
    async def test_setup_executes_ddl(self):
        pool, conn, cur = _mock_pool()
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")
        await cache.setup()

        # Should have executed 4 DDL statements (2 tables + 2 indexes)
        assert cur.execute.call_count == 4


# ---------------------------------------------------------------------------
# SchemaCache.get tests
# ---------------------------------------------------------------------------


class TestSchemaCacheGet:
    @pytest.mark.asyncio
    async def test_get_returns_none_on_miss(self):
        pool, conn, cur = _mock_pool()
        cur.fetchone = AsyncMock(return_value=None)
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        result = await cache.get("node", "chatOpenAI")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_schema_on_hit(self):
        pool, conn, cur = _mock_pool()
        schema = {"name": "chatOpenAI", "inputParams": []}
        cur.fetchone = AsyncMock(return_value={
            "schema_json": schema,
            "schema_hash": "abc123",
            "fetched_at": "2026-02-26T10:00:00Z",
            "ttl_seconds": 86400,
        })
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        result = await cache.get("node", "chatOpenAI")
        assert result is not None
        assert result["name"] == "chatOpenAI"
        assert result["_schema_hash"] == "abc123"

    @pytest.mark.asyncio
    async def test_get_parses_json_string(self):
        """When Postgres returns schema_json as a string, it should be parsed."""
        pool, conn, cur = _mock_pool()
        schema = {"name": "chatOpenAI"}
        cur.fetchone = AsyncMock(return_value={
            "schema_json": json.dumps(schema),
            "schema_hash": "h",
            "fetched_at": "2026-02-26T10:00:00Z",
            "ttl_seconds": 86400,
        })
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        result = await cache.get("node", "chatOpenAI")
        assert result["name"] == "chatOpenAI"


# ---------------------------------------------------------------------------
# SchemaCache.put tests
# ---------------------------------------------------------------------------


class TestSchemaCachePut:
    @pytest.mark.asyncio
    async def test_put_returns_hash_and_key(self):
        pool, conn, cur = _mock_pool()
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        schema = {"name": "chatOpenAI", "type": "node"}
        result = await cache.put("node", "chatOpenAI", schema)

        assert "schema_hash" in result
        assert result["type_key"] == "chatOpenAI"
        assert len(result["schema_hash"]) == 64

    @pytest.mark.asyncio
    async def test_put_calls_execute(self):
        pool, conn, cur = _mock_pool()
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        await cache.put("node", "chatOpenAI", {"name": "chatOpenAI"})
        assert cur.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_put_credential_strips_secrets(self):
        pool, conn, cur = _mock_pool()
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        schema = {
            "credential_id": "abc",
            "name": "test",
            "encryptedData": "SUPERSECRET",
        }
        await cache.put("credential", "openAIApi", schema)

        # Verify the payload passed to execute does not contain secrets
        call_args = cur.execute.call_args
        payload_json = call_args[0][1][5]  # 6th param is the JSON string
        parsed = json.loads(payload_json)
        assert "encryptedData" not in parsed
        assert "credential_id" in parsed


# ---------------------------------------------------------------------------
# SchemaCache.put_batch tests
# ---------------------------------------------------------------------------


class TestSchemaCachePutBatch:
    @pytest.mark.asyncio
    async def test_put_batch_inserts_all_entries(self):
        pool, conn, cur = _mock_pool()
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        entries = [(f"node_{i}", {"name": f"node_{i}"}) for i in range(10)]
        total = await cache.put_batch("node", entries)

        assert total == 10
        assert cur.execute.call_count == 10

    @pytest.mark.asyncio
    async def test_put_batch_chunks_at_50(self):
        pool, conn, cur = _mock_pool()
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        entries = [(f"node_{i}", {"name": f"node_{i}"}) for i in range(120)]
        total = await cache.put_batch("node", entries, chunk_size=50)

        assert total == 120
        # 3 chunks: 50 + 50 + 20 = 120 individual execute calls
        assert cur.execute.call_count == 120
        # But pool.connection() should be called 3 times (once per chunk)
        assert pool.connection.call_count == 3

    @pytest.mark.asyncio
    async def test_put_batch_credential_strips_all_entries(self):
        pool, conn, cur = _mock_pool()
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        entries = [
            ("cred1", {"credential_id": "1", "encryptedData": "SECRET1"}),
            ("cred2", {"credential_id": "2", "password": "pw"}),
        ]
        await cache.put_batch("credential", entries)

        # Check both payloads
        for call in cur.execute.call_args_list:
            payload = json.loads(call[0][1][5])
            for key in _CRED_BANNED_KEYS:
                assert key not in payload


# ---------------------------------------------------------------------------
# SchemaCache.count / is_populated tests
# ---------------------------------------------------------------------------


class TestSchemaCacheCount:
    @pytest.mark.asyncio
    async def test_count_returns_value(self):
        pool, conn, cur = _mock_pool()
        cur.fetchone = AsyncMock(return_value={"count": 303})
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        result = await cache.count("node")
        assert result == 303

    @pytest.mark.asyncio
    async def test_is_populated_true(self):
        pool, conn, cur = _mock_pool()
        cur.fetchone = AsyncMock(return_value={"count": 200})
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        assert await cache.is_populated("node", min_count=100) is True

    @pytest.mark.asyncio
    async def test_is_populated_false(self):
        pool, conn, cur = _mock_pool()
        cur.fetchone = AsyncMock(return_value={"count": 50})
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        assert await cache.is_populated("node", min_count=100) is False


# ---------------------------------------------------------------------------
# SchemaCache.invalidate tests
# ---------------------------------------------------------------------------


class TestSchemaCacheInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_executes_delete(self):
        pool, conn, cur = _mock_pool()
        cur.rowcount = 42
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        result = await cache.invalidate("node")
        assert result == 42
        assert cur.execute.call_count == 1


# ---------------------------------------------------------------------------
# SchemaCache.stale_keys tests
# ---------------------------------------------------------------------------


class TestSchemaCacheStaleKeys:
    @pytest.mark.asyncio
    async def test_stale_keys_returns_expired(self):
        pool, conn, cur = _mock_pool()
        cur.fetchall = AsyncMock(return_value=[
            {"type_key": "oldNode1"},
            {"type_key": "oldNode2"},
        ])
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        keys = await cache.stale_keys("node")
        assert keys == ["oldNode1", "oldNode2"]

    @pytest.mark.asyncio
    async def test_stale_keys_returns_empty_when_fresh(self):
        pool, conn, cur = _mock_pool()
        cur.fetchall = AsyncMock(return_value=[])
        cache = SchemaCache(pool=pool, base_url="http://localhost:3000")

        keys = await cache.stale_keys("node")
        assert keys == []
