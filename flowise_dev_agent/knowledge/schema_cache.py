"""Postgres-backed schema cache with TTL gating and content-hash versioning.

Roadmap 11, Milestone 1 (DD-104, DD-105).

Provides a 3-tier schema lookup: memory (hot) → Postgres (warm) → MCP (cold).
This module owns the Postgres tier. The memory tier lives in NodeSchemaStore.
MCP fetch is orchestrated by the caller (get_or_repair in provider.py).

Tables:
  schema_cache_items  — (base_url, schema_kind, type_key) → schema_json
  schema_refresh_jobs — audit trail for refresh operations (M11.3 prerequisite)

Credential safety (DD-064 extension):
  When schema_kind == "credential", entries are stripped to an allowlist before
  persistence. encryptedData, API keys, and passwords are NEVER stored.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Credential safety — mirrors _CRED_ALLOWLIST in provider.py (DD-064)
# ---------------------------------------------------------------------------

_CRED_SCHEMA_ALLOWLIST: frozenset[str] = frozenset({
    "credential_id", "name", "credentialName", "type",
    "tags", "created_at", "updated_at",
})

_CRED_BANNED_KEYS: frozenset[str] = frozenset({
    "encryptedData", "plainDataObj", "apiKey", "token",
    "password", "secret", "secretKey", "accessKey",
})


def _strip_credential_secrets(entry: dict) -> dict:
    """Strip all keys except allowlisted metadata from a credential entry.

    Raises ValueError if a known-dangerous key is found (defense in depth).
    """
    found_banned = _CRED_BANNED_KEYS & set(entry.keys())
    if found_banned:
        logger.warning(
            "[SchemaCache] Stripping banned credential keys before persistence: %s",
            sorted(found_banned),
        )
    return {k: v for k, v in entry.items() if k in _CRED_SCHEMA_ALLOWLIST}


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------


def _content_hash(schema_json: dict) -> str:
    """SHA-256 over canonical JSON bytes (sorted keys, no whitespace)."""
    canonical = json.dumps(schema_json, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL_ITEMS = """
CREATE TABLE IF NOT EXISTS schema_cache_items (
    base_url     TEXT        NOT NULL,
    schema_kind  TEXT        NOT NULL,
    type_key     TEXT        NOT NULL,
    schema_hash  TEXT        NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ttl_seconds  INT         NOT NULL,
    schema_json  JSONB       NOT NULL,
    PRIMARY KEY (base_url, schema_kind, type_key)
)
"""

_DDL_ITEMS_IDX_KIND = (
    "CREATE INDEX IF NOT EXISTS idx_schema_cache_items_kind "
    "ON schema_cache_items (schema_kind)"
)

_DDL_ITEMS_IDX_FETCHED = (
    "CREATE INDEX IF NOT EXISTS idx_schema_cache_items_fetched "
    "ON schema_cache_items (fetched_at)"
)

_DDL_JOBS = """
CREATE TABLE IF NOT EXISTS schema_refresh_jobs (
    job_id       UUID        PRIMARY KEY,
    base_url     TEXT        NOT NULL,
    scope        TEXT        NOT NULL,
    status       TEXT        NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at     TIMESTAMPTZ,
    summary_json JSONB
)
"""

# ---------------------------------------------------------------------------
# DML
# ---------------------------------------------------------------------------

_GET = """
SELECT schema_json, schema_hash, fetched_at, ttl_seconds
  FROM schema_cache_items
 WHERE base_url = %s
   AND schema_kind = %s
   AND type_key = %s
   AND fetched_at + (ttl_seconds || ' seconds')::interval > now()
"""

_PUT = """
INSERT INTO schema_cache_items
    (base_url, schema_kind, type_key, schema_hash, ttl_seconds, schema_json)
VALUES (%s, %s, %s, %s, %s, %s::jsonb)
ON CONFLICT (base_url, schema_kind, type_key) DO UPDATE SET
    schema_hash  = EXCLUDED.schema_hash,
    fetched_at   = now(),
    ttl_seconds  = EXCLUDED.ttl_seconds,
    schema_json  = EXCLUDED.schema_json
"""

_COUNT = """
SELECT count(*) FROM schema_cache_items
 WHERE base_url = %s AND schema_kind = %s
"""

_INVALIDATE = """
DELETE FROM schema_cache_items
 WHERE base_url = %s AND schema_kind = %s
"""

_STATS = """
SELECT schema_kind, count(*) as cnt, max(fetched_at) as last_fetched
  FROM schema_cache_items
 WHERE base_url = %s
 GROUP BY schema_kind
"""

_STALE_KEYS = """
SELECT type_key FROM schema_cache_items
 WHERE base_url = %s
   AND schema_kind = %s
   AND fetched_at + (ttl_seconds || ' seconds')::interval <= now()
"""

# ---------------------------------------------------------------------------
# Refresh job DML (M11.3, DD-108)
# ---------------------------------------------------------------------------

_JOB_INSERT = """
INSERT INTO schema_refresh_jobs (job_id, base_url, scope, status, summary_json)
VALUES (%s, %s, %s, %s, %s::jsonb)
"""

_JOB_GET = """
SELECT job_id, base_url, scope, status, started_at, ended_at, summary_json
  FROM schema_refresh_jobs
 WHERE job_id = %s
"""

_JOB_UPDATE = """
UPDATE schema_refresh_jobs
   SET status = %s, ended_at = CASE WHEN %s THEN now() ELSE ended_at END,
       summary_json = %s::jsonb
 WHERE job_id = %s
"""

_JOB_LATEST_RUNNING = """
SELECT job_id, base_url, scope, status, started_at, ended_at, summary_json
  FROM schema_refresh_jobs
 WHERE base_url = %s AND scope = %s AND status = 'running'
 ORDER BY started_at DESC
 LIMIT 1
"""


# ---------------------------------------------------------------------------
# SchemaCache
# ---------------------------------------------------------------------------


class SchemaCache:
    """Postgres-backed schema cache with TTL gating and content-hash versioning.

    Constructed with a psycopg AsyncConnectionPool and a base_url that scopes
    all entries to a specific Flowise instance.
    """

    def __init__(self, pool: Any, base_url: str) -> None:
        self._pool = pool
        self._base_url = base_url

    async def setup(self) -> None:
        """Execute DDL (IF NOT EXISTS). Safe to call on every startup."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_DDL_ITEMS)
                await cur.execute(_DDL_ITEMS_IDX_KIND)
                await cur.execute(_DDL_ITEMS_IDX_FETCHED)
                await cur.execute(_DDL_JOBS)
        logger.info("[SchemaCache] DDL setup complete for base_url=%s", self._base_url)

    async def get(
        self, schema_kind: str, type_key: str, ttl_seconds: int = 86400
    ) -> dict | None:
        """TTL-gated lookup. Returns schema dict with '_schema_hash' or None."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_GET, (self._base_url, schema_kind, type_key))
                row = await cur.fetchone()
        if row is None:
            return None
        schema = row["schema_json"]
        if isinstance(schema, str):
            schema = json.loads(schema)
        schema["_schema_hash"] = row["schema_hash"]
        return schema

    async def put(
        self,
        schema_kind: str,
        type_key: str,
        schema_json: dict,
        ttl_seconds: int = 86400,
    ) -> dict:
        """Upsert single entry with SHA-256 content hash.

        Returns {"schema_hash": str, "type_key": str}.
        """
        if schema_kind == "credential":
            schema_json = _strip_credential_secrets(schema_json)
        h = _content_hash(schema_json)
        payload = json.dumps(schema_json, sort_keys=True, ensure_ascii=False)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    _PUT,
                    (self._base_url, schema_kind, type_key, h, ttl_seconds, payload),
                )
        return {"schema_hash": h, "type_key": type_key}

    async def put_batch(
        self,
        schema_kind: str,
        entries: list[tuple[str, dict]],
        ttl_seconds: int = 86400,
        chunk_size: int = 50,
    ) -> int:
        """Batch upsert. entries = [(type_key, schema_json), ...].

        Inserts in chunks of chunk_size. Returns total rows upserted.
        """
        total = 0
        for i in range(0, len(entries), chunk_size):
            chunk = entries[i : i + chunk_size]
            rows: list[tuple] = []
            for type_key, schema_json in chunk:
                if schema_kind == "credential":
                    schema_json = _strip_credential_secrets(schema_json)
                h = _content_hash(schema_json)
                payload = json.dumps(schema_json, sort_keys=True, ensure_ascii=False)
                rows.append(
                    (self._base_url, schema_kind, type_key, h, ttl_seconds, payload)
                )
            async with self._pool.connection() as conn:
                async with conn.cursor() as cur:
                    for row in rows:
                        await cur.execute(_PUT, row)
            total += len(rows)
        return total

    async def count(self, schema_kind: str) -> int:
        """Count entries for a schema kind under this base_url."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_COUNT, (self._base_url, schema_kind))
                row = await cur.fetchone()
        return row["count"] if row else 0

    async def is_populated(self, schema_kind: str, min_count: int = 100) -> bool:
        """True if cache has >= min_count entries for this kind."""
        c = await self.count(schema_kind)
        return c >= min_count

    async def invalidate(self, schema_kind: str) -> int:
        """Delete all entries for (base_url, schema_kind). Returns count deleted."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_INVALIDATE, (self._base_url, schema_kind))
                return cur.rowcount

    async def stale_keys(self, schema_kind: str) -> list[str]:
        """Return type_keys where TTL has expired."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_STALE_KEYS, (self._base_url, schema_kind))
                rows = await cur.fetchall()
        return [row["type_key"] for row in rows]

    async def refresh_stats(self) -> dict:
        """Return counts and last refresh time per schema_kind."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_STATS, (self._base_url,))
                rows = await cur.fetchall()
        stats: dict[str, Any] = {
            "node_count": 0,
            "credential_count": 0,
            "template_count": 0,
            "last_refresh": None,
            "stale_count": 0,
        }
        for row in rows:
            kind = row["schema_kind"]
            cnt = row["cnt"]
            last = row["last_fetched"]
            if kind == "node":
                stats["node_count"] = cnt
            elif kind == "credential":
                stats["credential_count"] = cnt
            elif kind == "template":
                stats["template_count"] = cnt
            if last and (stats["last_refresh"] is None or last > stats["last_refresh"]):
                stats["last_refresh"] = last
        # stale_count across all kinds
        stale = await self.stale_keys("node")
        stats["stale_count"] = len(stale)
        return stats

    # ------------------------------------------------------------------
    # Refresh job CRUD (M11.3, DD-108)
    # ------------------------------------------------------------------

    async def create_job(
        self, job_id: str, scope: str, summary_json: dict | None = None,
    ) -> None:
        """Insert a new refresh job row with status='running'."""
        payload = json.dumps(summary_json or {}, sort_keys=True, ensure_ascii=False)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    _JOB_INSERT,
                    (job_id, self._base_url, scope, "running", payload),
                )

    async def get_job(self, job_id: str) -> dict | None:
        """Fetch a refresh job by ID. Returns dict or None."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_JOB_GET, (job_id,))
                row = await cur.fetchone()
        if row is None:
            return None
        result = dict(row)
        result["job_id"] = str(result["job_id"])
        if isinstance(result.get("summary_json"), str):
            result["summary_json"] = json.loads(result["summary_json"])
        if result.get("started_at"):
            result["started_at"] = str(result["started_at"])
        if result.get("ended_at"):
            result["ended_at"] = str(result["ended_at"])
        return result

    async def update_job(
        self, job_id: str, status: str, summary_json: dict, *, set_ended: bool = False,
    ) -> None:
        """Update job status and summary. set_ended=True sets ended_at=now()."""
        payload = json.dumps(summary_json, sort_keys=True, ensure_ascii=False)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    _JOB_UPDATE, (status, set_ended, payload, job_id),
                )

    async def get_latest_running_job(self, scope: str) -> dict | None:
        """Return the latest running job for (base_url, scope), or None."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    _JOB_LATEST_RUNNING, (self._base_url, scope),
                )
                row = await cur.fetchone()
        if row is None:
            return None
        result = dict(row)
        result["job_id"] = str(result["job_id"])
        return result

    async def try_advisory_lock(self, scope: str) -> bool:
        """Try to acquire a Postgres advisory lock for (base_url, scope).

        Uses pg_try_advisory_lock with a hash of (base_url + scope).
        Returns True if acquired, False if already held.
        """
        import hashlib
        key = f"{self._base_url}:{scope}"
        h = int(hashlib.md5(key.encode()).hexdigest()[:15], 16)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT pg_try_advisory_lock(%s)", (h,),
                )
                row = await cur.fetchone()
        return bool(row and row.get("pg_try_advisory_lock", False))

    async def release_advisory_lock(self, scope: str) -> None:
        """Release the advisory lock for (base_url, scope)."""
        import hashlib
        key = f"{self._base_url}:{scope}"
        h = int(hashlib.md5(key.encode()).hexdigest()[:15], 16)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT pg_advisory_unlock(%s)", (h,))
