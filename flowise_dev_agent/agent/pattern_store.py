"""Pattern library — persistent store for successful chatflow patterns.

After each DONE verdict the agent saves the requirement keywords and flowData
to a SQLite table. Future Discover phases call search_patterns() to find
relevant prior art before hitting the Flowise API.

Table schema:
    patterns (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        name              TEXT NOT NULL,
        requirement_text  TEXT NOT NULL,      -- full original requirement
        requirement_keys  TEXT NOT NULL,      -- space-separated keywords (for LIKE search)
        flow_data         TEXT NOT NULL,      -- chatflow flowData JSON string
        chatflow_id       TEXT,               -- Flowise chatflow ID (optional reference)
        created_at        REAL NOT NULL,      -- Unix timestamp
        success_count     INTEGER DEFAULT 1   -- times this pattern was used successfully
    )

See DESIGN_DECISIONS.md — DD-031.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("flowise_dev_agent.agent.pattern_store")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS patterns (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL,
    requirement_text TEXT    NOT NULL,
    requirement_keys TEXT    NOT NULL,
    flow_data        TEXT    NOT NULL,
    chatflow_id      TEXT,
    created_at       REAL    NOT NULL,
    success_count    INTEGER DEFAULT 1
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_patterns_keys ON patterns (requirement_keys)
"""


class PatternStore:
    """Async SQLite-backed store for successful chatflow patterns.

    Lifecycle:
        async with PatternStore.open(db_path) as store:
            await store.save_pattern(...)
            results = await store.search_patterns(...)

    Or create manually:
        store = PatternStore(db_path)
        await store.setup()
        ...
        await store.close()
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """Open the SQLite connection and create the patterns table."""
        import aiosqlite
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute(_CREATE_TABLE)
        await self._conn.execute(_CREATE_INDEX)
        await self._conn.commit()
        logger.info("PatternStore ready: %s", self._db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @classmethod
    async def open(cls, db_path: str) -> "PatternStore":
        """Factory: create + setup in one call (for use without async with)."""
        store = cls(db_path)
        await store.setup()
        return store

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save_pattern(
        self,
        name: str,
        requirement_text: str,
        flow_data: str,
        chatflow_id: str | None = None,
    ) -> int:
        """Save a successful chatflow pattern to the library.

        Returns the new pattern ID.
        """
        if not self._conn:
            raise RuntimeError("PatternStore.setup() not called")

        # Build keyword string: lowercase first 20 words of requirement
        words = requirement_text.lower().split()[:20]
        requirement_keys = " ".join(words)

        cur = await self._conn.execute(
            """
            INSERT INTO patterns
                (name, requirement_text, requirement_keys, flow_data, chatflow_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, requirement_text, requirement_keys, flow_data, chatflow_id, time.time()),
        )
        await self._conn.commit()
        pattern_id = cur.lastrowid
        logger.info("PatternStore: saved pattern id=%d name=%r", pattern_id, name)
        return pattern_id  # type: ignore[return-value]

    async def increment_success(self, pattern_id: int) -> None:
        """Bump the success_count for a pattern (called when it's reused)."""
        if not self._conn:
            return
        await self._conn.execute(
            "UPDATE patterns SET success_count = success_count + 1 WHERE id = ?",
            (pattern_id,),
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def search_patterns(self, keywords: str, limit: int = 3) -> list[dict[str, Any]]:
        """Full-text keyword search. Returns the top `limit` matching patterns.

        Splits `keywords` on whitespace, then finds patterns whose
        requirement_keys contain ANY of the words. Results are ranked by
        the number of matching words (most matches first), then by
        success_count descending.

        Returns a list of dicts with keys:
            id, name, requirement_text, flow_data, chatflow_id, success_count
        """
        if not self._conn:
            return []

        words = [w.lower().strip() for w in keywords.split() if w.strip()]
        if not words:
            return []

        # Build a CASE expression to count how many keywords match
        like_clauses = " + ".join(
            f"(CASE WHEN lower(requirement_keys) LIKE ? THEN 1 ELSE 0 END)"
            for _ in words
        )
        params = [f"%{w}%" for w in words] + [limit]

        query = f"""
            SELECT id, name, requirement_text, flow_data, chatflow_id, success_count,
                   ({like_clauses}) AS match_score
            FROM patterns
            WHERE match_score > 0
            ORDER BY match_score DESC, success_count DESC
            LIMIT ?
        """

        async with self._conn.execute(query, params) as cur:
            rows = await cur.fetchall()

        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "name": row[1],
                "requirement_text": row[2],
                "flow_data": row[3],
                "chatflow_id": row[4],
                "success_count": row[5],
            })

        logger.debug("PatternStore.search_patterns(%r) → %d results", keywords, len(results))
        return results

    async def list_patterns(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recently saved patterns (no keyword filter)."""
        if not self._conn:
            return []
        async with self._conn.execute(
            "SELECT id, name, requirement_text, chatflow_id, success_count "
            "FROM patterns ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        return [
            {
                "id": r[0],
                "name": r[1],
                "requirement_text": r[2],
                "chatflow_id": r[3],
                "success_count": r[4],
            }
            for r in rows
        ]
