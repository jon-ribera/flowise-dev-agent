"""Pattern library — persistent store for successful chatflow patterns.

After each DONE verdict the agent saves the requirement keywords and flowData
to a SQLite table. Future Discover phases call search_patterns() to find
relevant prior art before hitting the Flowise API.

Table schema (v1 original columns):
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

M7.3 migration adds (DD-068):
    domain            TEXT DEFAULT 'flowise'  -- domain that produced this pattern
    node_types        TEXT DEFAULT ''         -- JSON array of node type names
    category          TEXT DEFAULT ''         -- chatflow category from PATTERN section
    schema_fingerprint TEXT DEFAULT ''        -- NodeSchemaStore fingerprint at save time
    last_used_at      REAL DEFAULT NULL       -- Unix timestamp of last apply_as_base_graph call

See DESIGN_DECISIONS.md — DD-031, DD-068.
"""

from __future__ import annotations

import datetime
import json
import logging
import time
from typing import Any

logger = logging.getLogger("flowise_dev_agent.agent.pattern_store")


# ---------------------------------------------------------------------------
# M9.9 helpers — schema compatibility + category inference
# ---------------------------------------------------------------------------


def _is_pattern_schema_compatible(
    pattern: dict, current_fingerprint: str | None
) -> bool:
    """True if pattern was trained on the same schema or has no fingerprint.

    Compatibility rules:
      - stored fingerprint is None/empty → treat as compatible (old pattern).
      - current_fingerprint is None/empty → cannot check, assume compatible.
      - both present → compatible only when they are equal.

    M9.9 (DD-068 extension).
    """
    stored = pattern.get("schema_fingerprint") or None
    if stored is None:
        return True
    if not current_fingerprint:
        return True
    return stored == current_fingerprint


def _infer_category_from_node_types(node_types: list[str]) -> str:
    """Infer a chatflow category label from the list of node type names.

    Priority order (first match wins):
      1. "rag"            — any node containing "vectorStore" or "retriev"
      2. "tool_agent"     — any node containing "toolAgent"
      3. "conversational" — chatOpenAI + conversationChain both present
      4. "custom"         — catch-all

    M9.9 (DD-068 extension).
    """
    lower_names = [n.lower() for n in node_types]

    if any("vectorstore" in n or "retriev" in n for n in lower_names):
        return "rag"
    if any("toolagent" in n for n in lower_names):
        return "tool_agent"
    has_chat_model = any(
        "chatopenai" in n or "chatanthropic" in n or "chatollamalocal" in n
        for n in lower_names
    )
    has_conv_chain = any("conversationchain" in n for n in lower_names)
    if has_chat_model and has_conv_chain:
        return "conversational"
    return "custom"


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS patterns (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    requirement_text  TEXT    NOT NULL,
    requirement_keys  TEXT    NOT NULL,
    flow_data         TEXT    NOT NULL,
    chatflow_id       TEXT,
    created_at        REAL    NOT NULL,
    success_count     INTEGER DEFAULT 1,
    domain            TEXT    DEFAULT 'flowise',
    node_types        TEXT    DEFAULT '',
    category          TEXT    DEFAULT '',
    schema_fingerprint TEXT   DEFAULT '',
    last_used_at      REAL    DEFAULT NULL
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_patterns_keys ON patterns (requirement_keys)
"""

# M7.3: columns added by migration (absent from older DBs)
_M73_COLUMNS: list[tuple[str, str]] = [
    ("domain",             "TEXT DEFAULT 'flowise'"),
    ("node_types",         "TEXT DEFAULT ''"),
    ("category",           "TEXT DEFAULT ''"),
    ("schema_fingerprint", "TEXT DEFAULT ''"),
    ("last_used_at",       "REAL DEFAULT NULL"),
]


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
        """Open the SQLite connection, create the patterns table, and run migrations."""
        import aiosqlite
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute(_CREATE_TABLE)
        await self._conn.execute(_CREATE_INDEX)
        await self._conn.commit()
        await self._migrate_schema()
        logger.info("PatternStore ready: %s", self._db_path)

    async def _migrate_schema(self) -> None:
        """Add M7.3 columns to existing patterns tables (safe to re-run).

        Uses PRAGMA table_info to detect missing columns, then issues
        ALTER TABLE ... ADD COLUMN for each absent column.  This is safe
        to run on fresh DBs (the columns are already present from _CREATE_TABLE)
        and on older DBs that pre-date M7.3.

        See DD-068.
        """
        if not self._conn:
            return
        # Read current column names
        existing_cols: set[str] = set()
        async with self._conn.execute("PRAGMA table_info(patterns)") as cur:
            async for row in cur:
                existing_cols.add(row[1])  # row[1] = column name

        added: list[str] = []
        for col_name, col_def in _M73_COLUMNS:
            if col_name not in existing_cols:
                await self._conn.execute(
                    f"ALTER TABLE patterns ADD COLUMN {col_name} {col_def}"
                )
                added.append(col_name)

        if added:
            await self._conn.commit()
            logger.info("PatternStore: migrated schema — added columns: %s", added)
        else:
            logger.debug("PatternStore: schema already up-to-date (no migration needed)")

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
        domain: str = "flowise",
        node_types: str = "",
        category: str = "",
        schema_fingerprint: str = "",
    ) -> int:
        """Save a successful chatflow pattern to the library.

        M7.3 adds optional structured metadata (DD-068):
          domain:             Which DomainCapability produced this pattern.
          node_types:         JSON array string of node type names in the chatflow.
          category:           Chatflow category label (from the PATTERN plan section).
          schema_fingerprint: Fingerprint of NodeSchemaStore snapshot at save time.

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
                (name, requirement_text, requirement_keys, flow_data, chatflow_id,
                 created_at, domain, node_types, category, schema_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name, requirement_text, requirement_keys, flow_data, chatflow_id,
                time.time(), domain, node_types, category, schema_fingerprint,
            ),
        )
        await self._conn.commit()
        pattern_id = cur.lastrowid
        logger.info(
            "PatternStore: saved pattern id=%d name=%r domain=%s category=%r",
            pattern_id, name, domain, category,
        )
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
    # Read — existing search
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

    # ------------------------------------------------------------------
    # Read — M7.3 structured search
    # ------------------------------------------------------------------

    async def search_patterns_filtered(
        self,
        keywords: str,
        domain: str | None = None,
        category: str | None = None,
        node_types: list[str] | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Structured keyword search with optional domain/category/node_types filters.

        M7.3 (DD-068).  Extends search_patterns() with:
          domain:     SQL WHERE domain = ? (exact match, case-sensitive).
          category:   SQL WHERE category = ? (exact match, case-sensitive).
          node_types: Python-side JSON overlap check after SQL fetch.  Any
                      pattern whose node_types JSON array contains at least one
                      element from the node_types filter list is retained.

        When none of the optional filters are supplied this is equivalent to
        search_patterns() with the same keyword ranking.

        Returns a list of dicts with keys:
            id, name, requirement_text, flow_data, chatflow_id, success_count,
            domain, node_types, category, schema_fingerprint
        """
        if not self._conn:
            return []

        words = [w.lower().strip() for w in keywords.split() if w.strip()]
        if not words:
            # No keywords: fall back to most-recent / highest success_count
            words = []

        # Build keyword scoring expression (0 if no words supplied)
        if words:
            like_clauses = " + ".join(
                f"(CASE WHEN lower(requirement_keys) LIKE ? THEN 1 ELSE 0 END)"
                for _ in words
            )
            score_expr = f"({like_clauses}) AS match_score"
            kw_params: list[Any] = [f"%{w}%" for w in words]
            where_parts = ["match_score > 0"]
        else:
            score_expr = "1 AS match_score"
            kw_params = []
            where_parts = []

        # Domain / category SQL filters
        extra_params: list[Any] = []
        if domain is not None:
            where_parts.append("domain = ?")
            extra_params.append(domain)
        if category is not None:
            where_parts.append("category = ?")
            extra_params.append(category)

        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # Fetch a larger batch when node_types post-filter is applied
        sql_limit = max(limit * 5, 20) if node_types else limit

        query = f"""
            SELECT id, name, requirement_text, flow_data, chatflow_id, success_count,
                   domain, node_types, category, schema_fingerprint, last_used_at,
                   {score_expr}
            FROM patterns
            {where_sql}
            ORDER BY match_score DESC, success_count DESC
            LIMIT ?
        """
        params: list[Any] = kw_params + extra_params + [sql_limit]

        async with self._conn.execute(query, params) as cur:
            rows = await cur.fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            # last_used_at stored as Unix float; convert to ISO-8601 for callers
            _last_used_raw = row[10]
            _last_used_iso: str | None = None
            if _last_used_raw is not None:
                try:
                    _last_used_iso = datetime.datetime.fromtimestamp(
                        float(_last_used_raw), tz=datetime.timezone.utc
                    ).isoformat()
                except (TypeError, ValueError, OSError):
                    pass

            results.append({
                "id": row[0],
                "name": row[1],
                "requirement_text": row[2],
                "flow_data": row[3],
                "chatflow_id": row[4],
                "success_count": row[5],
                "domain": row[6],
                "node_types": row[7],
                "category": row[8],
                "schema_fingerprint": row[9],
                "last_used_at": _last_used_iso,
            })

        # Python-side node_types overlap filter
        if node_types and results:
            filter_set = set(node_types)
            filtered: list[dict[str, Any]] = []
            for r in results:
                saved_nt: list[str] = []
                try:
                    saved_nt = json.loads(r.get("node_types") or "[]") or []
                except (ValueError, TypeError):
                    pass
                if not saved_nt or filter_set.intersection(saved_nt):
                    filtered.append(r)
            results = filtered

        results = results[:limit]
        logger.debug(
            "PatternStore.search_patterns_filtered(%r, domain=%r) → %d results",
            keywords, domain, len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Read — M7.3 base graph seeding
    # ------------------------------------------------------------------

    async def apply_as_base_graph(self, pattern_id: int) -> "GraphIR":  # type: ignore[name-defined]
        """Return a GraphIR seeded from a saved pattern's flow_data.

        M7.3 (DD-068): used by the plan node to give patch v2 a pre-built
        base graph, reducing AddNode ops and improving compilation accuracy.

        Side-effects:
          - Increments success_count by 1.
          - Sets last_used_at to the current Unix timestamp.

        Returns an empty GraphIR if the pattern_id is not found or
        flow_data is empty/malformed.
        """
        from flowise_dev_agent.agent.compiler import GraphIR  # local to avoid circular import

        if not self._conn:
            return GraphIR()

        async with self._conn.execute(
            "SELECT flow_data FROM patterns WHERE id = ?",
            (pattern_id,),
        ) as cur:
            row = await cur.fetchone()

        if row is None:
            logger.warning("PatternStore.apply_as_base_graph: id=%d not found", pattern_id)
            return GraphIR()

        flow_data_raw = row[0]

        # Track usage
        await self._conn.execute(
            "UPDATE patterns SET success_count = success_count + 1, last_used_at = ? WHERE id = ?",
            (time.time(), pattern_id),
        )
        await self._conn.commit()

        graph_ir = GraphIR.from_flow_data(flow_data_raw)
        logger.info(
            "PatternStore.apply_as_base_graph: id=%d → %d nodes, %d edges",
            pattern_id, len(graph_ir.nodes), len(graph_ir.edges),
        )
        return graph_ir

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    async def list_patterns(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recently saved patterns (no keyword filter)."""
        if not self._conn:
            return []
        async with self._conn.execute(
            "SELECT id, name, requirement_text, chatflow_id, success_count, domain, category "
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
                "domain": r[5],
                "category": r[6],
            }
            for r in rows
        ]
