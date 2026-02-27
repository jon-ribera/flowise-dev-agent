"""M11.1 — NodeSchemaStore 3-tier lookup tests (DD-105).

Tests the 3-tier lookup contract: memory → Postgres → MCP repair.
All external dependencies (Postgres, Flowise API) are mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flowise_dev_agent.knowledge.provider import NodeSchemaStore, _normalize_api_schema


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------

_SAMPLE_SCHEMA = {
    "node_type": "chatOpenAI",
    "name": "chatOpenAI",
    "label": "ChatOpenAI",
    "baseClasses": ["BaseChatModel"],
    "inputAnchors": [],
    "inputParams": [{"name": "modelName", "type": "string"}],
    "outputAnchors": [
        {"id": "{nodeId}-output-chatOpenAI-BaseChatModel", "name": "chatOpenAI", "type": "BaseChatModel"}
    ],
    "outputs": {},
}

_SAMPLE_API_RAW = {
    "name": "chatOpenAI",
    "label": "ChatOpenAI",
    "baseClasses": ["BaseChatModel"],
    "inputs": [
        {"name": "modelName", "type": "string"},
    ],
    "outputs": [],
}


def _make_snapshot_file(tmp_path: Path, schemas: list[dict]) -> Path:
    """Write a temporary snapshot JSON file."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(schemas, indent=2), encoding="utf-8")
    return snapshot


def _mock_pg_cache(get_result=None, is_populated_result=False):
    """Create a mock SchemaCache with configurable responses."""
    pg = AsyncMock()
    pg.get = AsyncMock(return_value=get_result)
    pg.put = AsyncMock(return_value={"schema_hash": "abc123", "type_key": "test"})
    pg.is_populated = AsyncMock(return_value=is_populated_result)
    pg._pool = MagicMock()
    pg._base_url = "http://localhost:3000"
    return pg


# ---------------------------------------------------------------------------
# Tier 1: Memory hit — no Postgres or API calls
# ---------------------------------------------------------------------------


class TestTier1MemoryHit:
    @pytest.mark.asyncio
    async def test_memory_hit_skips_postgres_and_api(self, tmp_path):
        """When the node exists in memory, Postgres and API should not be called."""
        snapshot = _make_snapshot_file(tmp_path, [_SAMPLE_SCHEMA])
        pg = _mock_pg_cache()
        api_fetcher = AsyncMock(return_value=_SAMPLE_API_RAW)

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=pg,
        )

        result = await store.get_or_repair("chatOpenAI", api_fetcher)

        assert result is not None
        assert result["node_type"] == "chatOpenAI"
        pg.get.assert_not_called()
        api_fetcher.assert_not_called()

    @pytest.mark.asyncio
    async def test_memory_hit_case_insensitive(self, tmp_path):
        """Case-insensitive fallback should hit memory without Postgres/API."""
        snapshot = _make_snapshot_file(tmp_path, [_SAMPLE_SCHEMA])
        pg = _mock_pg_cache()
        api_fetcher = AsyncMock()

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=pg,
        )

        result = await store.get_or_repair("CHATOPENAI", api_fetcher)

        assert result is not None
        assert result["node_type"] == "chatOpenAI"
        pg.get.assert_not_called()
        api_fetcher.assert_not_called()

    def test_sync_get_hits_memory(self, tmp_path):
        """Synchronous get() should return from memory without touching Postgres."""
        snapshot = _make_snapshot_file(tmp_path, [_SAMPLE_SCHEMA])
        pg = _mock_pg_cache()

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=pg,
        )

        result = store.get("chatOpenAI")
        assert result is not None
        assert result["node_type"] == "chatOpenAI"


# ---------------------------------------------------------------------------
# Tier 2: Postgres hit — loads into memory
# ---------------------------------------------------------------------------


class TestTier2PostgresHit:
    @pytest.mark.asyncio
    async def test_pg_hit_loads_into_memory(self, tmp_path):
        """On memory miss + Postgres hit, schema should load into memory."""
        # Empty snapshot — memory will miss
        snapshot = _make_snapshot_file(tmp_path, [])
        pg_schema = {**_SAMPLE_SCHEMA, "_schema_hash": "pg_hash_123"}
        pg = _mock_pg_cache(get_result=pg_schema)
        api_fetcher = AsyncMock()

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=pg,
        )

        result = await store.get_or_repair("chatOpenAI", api_fetcher)

        assert result is not None
        assert result["node_type"] == "chatOpenAI"
        assert result["_schema_hash"] == "pg_hash_123"
        pg.get.assert_called_once_with("node", "chatOpenAI")
        api_fetcher.assert_not_called()

        # Verify it was loaded into memory — subsequent call should not touch Postgres
        pg.get.reset_mock()
        result2 = await store.get_or_repair("chatOpenAI", api_fetcher)
        assert result2 is not None
        pg.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_pg_hit_populates_lower_index(self, tmp_path):
        """Postgres hit should also populate case-insensitive fallback index."""
        snapshot = _make_snapshot_file(tmp_path, [])
        pg = _mock_pg_cache(get_result={**_SAMPLE_SCHEMA, "_schema_hash": "h"})
        api_fetcher = AsyncMock()

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=pg,
        )

        # First call via exact name — populates memory + lower_index
        await store.get_or_repair("chatOpenAI", api_fetcher)

        # Second call via case-insensitive — should hit memory
        pg.get.reset_mock()
        result = await store.get_or_repair("CHATOPENAI", api_fetcher)
        assert result is not None
        pg.get.assert_not_called()


# ---------------------------------------------------------------------------
# Tier 3: MCP repair — triggers API fetch + write-back
# ---------------------------------------------------------------------------


class TestTier3MCPRepair:
    @pytest.mark.asyncio
    async def test_mcp_repair_triggers_api_and_writeback(self, tmp_path):
        """On full miss (memory + Postgres), API should be called and result written back."""
        snapshot = _make_snapshot_file(tmp_path, [])
        pg = _mock_pg_cache(get_result=None)
        api_fetcher = AsyncMock(return_value=_SAMPLE_API_RAW)

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=pg,
        )

        result = await store.get_or_repair("chatOpenAI", api_fetcher)

        assert result is not None
        assert result["node_type"] == "chatOpenAI"
        # API was called exactly once
        api_fetcher.assert_called_once_with("chatOpenAI")
        # Write-back to Postgres
        pg.put.assert_called_once()
        call_args = pg.put.call_args
        assert call_args[0][0] == "node"
        assert call_args[0][1] == "chatOpenAI"

    @pytest.mark.asyncio
    async def test_mcp_repair_writes_to_memory(self, tmp_path):
        """After MCP repair, subsequent calls should hit memory."""
        snapshot = _make_snapshot_file(tmp_path, [])
        pg = _mock_pg_cache(get_result=None)
        api_fetcher = AsyncMock(return_value=_SAMPLE_API_RAW)

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=pg,
        )

        await store.get_or_repair("chatOpenAI", api_fetcher)

        # Reset mocks and call again
        pg.get.reset_mock()
        api_fetcher.reset_mock()
        result2 = await store.get_or_repair("chatOpenAI", api_fetcher)

        assert result2 is not None
        pg.get.assert_not_called()
        api_fetcher.assert_not_called()

    @pytest.mark.asyncio
    async def test_mcp_repair_api_failure_returns_none(self, tmp_path):
        """API failure should return None gracefully."""
        snapshot = _make_snapshot_file(tmp_path, [])
        pg = _mock_pg_cache(get_result=None)
        api_fetcher = AsyncMock(side_effect=Exception("API down"))

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=pg,
        )

        result = await store.get_or_repair("unknownNode", api_fetcher)
        assert result is None

    @pytest.mark.asyncio
    async def test_mcp_repair_api_returns_error(self, tmp_path):
        """API returning error dict should return None."""
        snapshot = _make_snapshot_file(tmp_path, [])
        pg = _mock_pg_cache(get_result=None)
        api_fetcher = AsyncMock(return_value={"error": "not found"})

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=pg,
        )

        result = await store.get_or_repair("unknownNode", api_fetcher)
        assert result is None
        pg.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_pg_writeback_failure_does_not_block(self, tmp_path):
        """Postgres write-back failure should log but still return the schema."""
        snapshot = _make_snapshot_file(tmp_path, [])
        pg = _mock_pg_cache(get_result=None)
        pg.put = AsyncMock(side_effect=Exception("Postgres down"))
        api_fetcher = AsyncMock(return_value=_SAMPLE_API_RAW)

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=pg,
        )

        result = await store.get_or_repair("chatOpenAI", api_fetcher)
        # Schema should still be returned despite Postgres failure
        assert result is not None
        assert result["node_type"] == "chatOpenAI"


# ---------------------------------------------------------------------------
# pg_cache=None: preserves file-only behavior
# ---------------------------------------------------------------------------


class TestNoPgCacheFallback:
    @pytest.mark.asyncio
    async def test_no_pg_cache_uses_snapshot_only(self, tmp_path):
        """With pg_cache=None, lookup should use file snapshot only."""
        snapshot = _make_snapshot_file(tmp_path, [_SAMPLE_SCHEMA])
        api_fetcher = AsyncMock()

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=None,
        )

        result = await store.get_or_repair("chatOpenAI", api_fetcher)
        assert result is not None
        api_fetcher.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_pg_cache_repair_skips_writeback(self, tmp_path):
        """With pg_cache=None, MCP repair should NOT attempt Postgres write-back."""
        snapshot = _make_snapshot_file(tmp_path, [])
        api_fetcher = AsyncMock(return_value=_SAMPLE_API_RAW)

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=None,
        )

        result = await store.get_or_repair("chatOpenAI", api_fetcher)
        assert result is not None
        # No Postgres interaction — pg_cache is None
        assert store._pg_cache is None

    @pytest.mark.asyncio
    async def test_no_snapshot_file_returns_none(self, tmp_path):
        """Missing snapshot file + no pg_cache should return None."""
        api_fetcher = AsyncMock(side_effect=Exception("should not be called"))

        store = NodeSchemaStore(
            snapshot_path=tmp_path / "nonexistent.json",
            meta_path=tmp_path / "meta.json",
            pg_cache=None,
        )

        result = store.get("chatOpenAI")
        assert result is None


# ---------------------------------------------------------------------------
# load_from_pg startup behavior
# ---------------------------------------------------------------------------


class TestLoadFromPg:
    @pytest.mark.asyncio
    async def test_load_from_pg_when_populated(self):
        """When Postgres is populated, load_from_pg should return True."""
        pg = _mock_pg_cache(is_populated_result=True)

        # Mock the pool's connection to return rows
        # psycopg pattern: pool.connection() is async CM, conn.cursor() is sync
        conn = MagicMock()
        cur = AsyncMock()
        cur.fetchall = AsyncMock(return_value=[
            {"type_key": "chatOpenAI", "schema_json": _SAMPLE_SCHEMA, "schema_hash": "h1"},
            {"type_key": "openAIEmbeddings", "schema_json": {"node_type": "openAIEmbeddings"}, "schema_hash": "h2"},
        ])

        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)

        cur_ctx = MagicMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)

        pg._pool.connection.return_value = conn_ctx
        conn.cursor.return_value = cur_ctx

        store = NodeSchemaStore(
            snapshot_path=Path("/tmp/nonexistent.json"),
            meta_path=Path("/tmp/meta.json"),
            pg_cache=pg,
        )

        result = await store.load_from_pg()
        assert result is True
        assert store._loaded_from_pg is True
        assert "chatOpenAI" in store._index
        assert "openAIEmbeddings" in store._index
        assert len(store._index) == 2

    @pytest.mark.asyncio
    async def test_load_from_pg_when_not_populated(self):
        """When Postgres is not populated, load_from_pg should return False."""
        pg = _mock_pg_cache(is_populated_result=False)

        store = NodeSchemaStore(
            snapshot_path=Path("/tmp/nonexistent.json"),
            meta_path=Path("/tmp/meta.json"),
            pg_cache=pg,
        )

        result = await store.load_from_pg()
        assert result is False
        assert store._loaded_from_pg is False

    @pytest.mark.asyncio
    async def test_load_from_pg_none_cache(self):
        """With pg_cache=None, load_from_pg should return False immediately."""
        store = NodeSchemaStore(
            snapshot_path=Path("/tmp/nonexistent.json"),
            meta_path=Path("/tmp/meta.json"),
            pg_cache=None,
        )

        result = await store.load_from_pg()
        assert result is False

    @pytest.mark.asyncio
    async def test_load_from_pg_exception_returns_false(self):
        """Postgres errors during load should return False (fallback to file)."""
        pg = _mock_pg_cache(is_populated_result=True)
        pg._pool = MagicMock()

        # Make connection raise
        pg._pool.connection.side_effect = Exception("connection failed")

        store = NodeSchemaStore(
            snapshot_path=Path("/tmp/nonexistent.json"),
            meta_path=Path("/tmp/meta.json"),
            pg_cache=pg,
        )

        result = await store.load_from_pg()
        assert result is False


# ---------------------------------------------------------------------------
# Postgres error fallthrough
# ---------------------------------------------------------------------------


class TestPostgresErrorFallthrough:
    @pytest.mark.asyncio
    async def test_pg_get_error_falls_through_to_api(self, tmp_path):
        """When Postgres get() raises, lookup should fall through to MCP repair."""
        snapshot = _make_snapshot_file(tmp_path, [])
        pg = _mock_pg_cache()
        pg.get = AsyncMock(side_effect=Exception("Postgres timeout"))
        api_fetcher = AsyncMock(return_value=_SAMPLE_API_RAW)

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
            pg_cache=pg,
        )

        result = await store.get_or_repair("chatOpenAI", api_fetcher)
        assert result is not None
        assert result["node_type"] == "chatOpenAI"
        api_fetcher.assert_called_once_with("chatOpenAI")


# ---------------------------------------------------------------------------
# invalidate_memory
# ---------------------------------------------------------------------------


class TestInvalidateMemory:
    def test_invalidate_clears_index(self, tmp_path):
        """invalidate_memory should clear the in-memory index."""
        snapshot = _make_snapshot_file(tmp_path, [_SAMPLE_SCHEMA])

        store = NodeSchemaStore(
            snapshot_path=snapshot,
            meta_path=tmp_path / "meta.json",
        )

        # Force load
        store.get("chatOpenAI")
        assert len(store._index) == 1

        count = store.invalidate_memory()
        assert count == 1
        assert len(store._index) == 0
        assert store._loaded is False
        assert store._loaded_from_pg is False
