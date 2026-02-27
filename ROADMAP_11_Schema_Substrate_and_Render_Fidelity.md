# ROADMAP11 — Cache-First Schema Substrate with Bounded MCP Repair + UI Refresh

## Purpose

Roadmap 11 eliminates the white-screen rendering problem in agent-created Flowise chatflows by replacing the lossy Markdown-parsed schema snapshot with a full-fidelity, API-populated Postgres-backed schema cache. It also fixes 3 compiler gaps (credential inputParam, viewport, dynamic node height), adds operator-facing refresh UX, and introduces proactive schema drift detection.

### Root cause analysis

Agent-created chatflows render as blank white screens in Flowise because the schema snapshot (`flowise_nodes.snapshot.json`) is populated from Markdown documentation parsing, which drops **7+ UI-critical fields** per inputParam:

| Missing field | Purpose |
|---|---|
| `step` | Numeric input step size (e.g., `0.1` for temperature) |
| `rows` | Textarea row height |
| `additionalParams` | Controls "Additional Parameters" drawer rendering |
| `loadMethod` | Dynamic option loading (e.g., `listModels` for asyncOptions) |
| `credentialNames` | Links credential selector to the correct credential type |
| `options` | Dropdown option arrays (label/name pairs) |
| `show` | Conditional visibility rules |

The compiler (`_build_node_data`, `_graph_node_to_flowise`) faithfully passes through whatever the snapshot contains — it strips nothing. The data source is the sole bottleneck. Three additional compiler gaps compound the problem:

- **GAP 4**: `BindCredential` sets `data.credential` (value) but never adds a credential inputParam to `data.inputParams[]` — the Flowise React Flow renderer needs both.
- **GAP 7**: `to_flow_data()` returns `{nodes, edges}` only — no `viewport` key. Flowise defaults to an origin that may not show the canvas.
- **GAP 8**: `_graph_node_to_flowise()` hardcodes `height: 500` — nodes with many parameters overflow or waste space.

### Solution

1. **Schema Substrate**: Replace Markdown-parsed snapshot with API-first population into a Postgres-backed 3-tier cache (memory → Postgres → MCP fetch).
2. **Renderer Fidelity**: Fix the 3 compiler gaps (credential inputParam synthesis, viewport, dynamic height) and enforce a render-safe schema contract.
3. **Refresh UX**: Add `POST /platform/schema/refresh` with SSE progress streaming, backpressure control, and cross-instance coordination.
4. **Drift Detection**: Proactive schema drift check in Phase A + compile-time gap metrics.

### What does NOT change in this roadmap

- The deterministic compiler pipeline (`compile_patch_ops`, `_build_node_data`) — richer data flows through automatically since these functions already deep-copy schema verbatim.
- `AnchorDictionaryStore` interface — rebuilds from richer data without changes.
- All 18 graph nodes, HITL interrupts (4 points), FastAPI session/system endpoints (16 routes).
- `CredentialStore`, `TemplateStore` interfaces — unchanged in M11.1.
- Patch IR operations (`AddNode`, `SetParam`, `Connect`, `BindCredential`).
- Test suite: all 591 existing tests continue to pass at every milestone boundary.

---

## Guiding principles

1. **Schema is a platform substrate, not LLM context.** The LLM signals "I need X" — the platform ensures it's available. No LLM-controlled caching policy. Deterministic rules only.
2. **MCP is the source of truth, but never per-run by default.** Only hit the Flowise API on cache miss, TTL expiry, version mismatch, explicit UI refresh, or compile-time gap detection.
3. **Single source of truth for schemas.** The Postgres cache is authoritative across sessions and across replicas. Memory dict is a hot-path optimization scoped to a single process. File snapshot is a seed/fallback for dev/test without Postgres.
4. **Bounded repair budget.** `_MAX_SCHEMA_REPAIRS` (10/iteration) is preserved. 5+ repairs in a single compile triggers a drift warning, not an unbounded fetch loop.
5. **Backwards compatibility at every step.** Each milestone produces a passing test suite. No milestone breaks the existing agent session flow.
6. **No secrets in the schema cache.** Credential schemas store only structural metadata (id, name, credentialName, timestamps). The `_CRED_ALLOWLIST` pattern from DD-064 extends to all credential-adjacent data in `schema_cache`. `encryptedData`, API keys, tokens, and passwords are never written to Postgres.

---

## Architecture: 3-Tier Schema Cache

```
Memory (hot dict)  →  Postgres (warm, persistent)  →  MCP fetch (cold, bounded)
     O(1) lookup        TTL-gated, across sessions      Max 10/session, single API call
   per-process only     shared across replicas           semaphore-gated (max 5 concurrent)
```

**Cache key**: `(base_url, schema_kind, type_key)` — supports multi-tenant implicitly without additional design.

**Refresh triggers** (all deterministic):

| Trigger | Scope | When |
|---|---|---|
| Cache miss | Single node type | `get_or_repair()` falls through memory + Postgres |
| TTL expired | Per-entry | `fetched_at + ttl_seconds < now()` on Postgres read |
| Version mismatch | Per-entry | `content_hash` differs from fresh fetch |
| UI refresh | Operator-scoped | `POST /platform/schema/refresh` |
| Compile-time gap | Session-scoped | 5+ MCP repairs in single `compile_flow_data` call |

**Write-back contract**: Every MCP repair writes to all 3 tiers (memory → Postgres → confirms). No tier can become stale relative to another within a session.

### Cross-tier consistency model

Postgres is the source of truth across replicas. Memory is a per-process hot cache with bounded staleness:

1. **Memory entries carry `content_hash`**. Each memory dict entry stores the `content_hash` from the Postgres row that populated it.
2. **Post-refresh invalidation**: When a refresh completes (M11.3), the process that ran the refresh clears its memory cache for the affected `(base_url, schema_kind)` scope. Other replicas rely on TTL expiry (default 24h for node schemas) — acceptable because schema changes are infrequent (Flowise upgrades, not per-request).
3. **No distributed cache required**. Memory is best-effort; Postgres is authoritative. A memory miss falls through to Postgres (cheap query, connection-pooled). Worst case on a stale memory hit: the process uses a schema that's at most `ttl_seconds` old — identical to today's file-snapshot behavior, but with a 24h ceiling instead of unbounded staleness.
4. **Startup population**: On process start, `NodeSchemaStore._load()` reads from Postgres if `pg_cache.is_populated()`. This seeds the memory tier from the shared persistent tier, so all replicas converge on the same data within one startup cycle.

### Credential data safety boundaries

Schema cache entries for `schema_kind = 'credential'` follow the same allowlist pattern established in DD-064:

- **What is cached**: `credential_id`, `name`, `credentialName` (the Flowise type, e.g. `"openAIApi"`), `tags`, `created_at`, `updated_at`. This is structural metadata — what credential types exist and which nodes need them.
- **What is cached in node schemas**: `credentialNames` field (array of credential type strings, e.g. `["openAIApi"]`). This is part of the node schema and tells the renderer which credential selector to show. It contains no secret material.
- **What is NEVER cached**: `encryptedData`, `plainDataObj`, API keys, tokens, passwords, or any field not in the allowlist. Redaction happens BEFORE persistence — `_strip_credential_secrets()` is called on every credential entry before `put()` or `put_batch()`.
- **Enforcement**: `SchemaCache.put()` and `put_batch()` call `_strip_credential_secrets()` when `schema_kind == 'credential'`. Load-time validation (matching `_validate_allowlist()` pattern) rejects any entry with banned keys.

---

## M11.1 — Schema Substrate (DD-104, DD-105)

### Goal

Replace the Markdown-parsed file snapshot with a Postgres-backed 3-tier schema cache. API-sourced schemas contain all fields the Flowise renderer requires — `_normalize_api_schema()` already preserves them via `dict(inp)`. The problem is purely the data source.

### Why now

Every subsequent milestone depends on full-fidelity schemas being available. M11.2 (credential inputParam synthesis) needs `credentialNames`. M11.3 (refresh UX) needs the Postgres table. M11.4 (drift detection) needs cache counts and staleness queries.

### Changes

**DD-104: Postgres Schema Cache Table**

```sql
CREATE TABLE IF NOT EXISTS schema_cache (
    base_url     TEXT        NOT NULL,
    schema_kind  TEXT        NOT NULL,  -- 'node' | 'template' | 'credential'
    type_key     TEXT        NOT NULL,  -- e.g. 'chatOpenAI'
    schema_json  JSONB       NOT NULL,
    content_hash TEXT        NOT NULL,  -- SHA-256 for version gating
    version      TEXT,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ttl_seconds  INT         NOT NULL DEFAULT 86400,
    PRIMARY KEY (base_url, schema_kind, type_key)
);
CREATE INDEX IF NOT EXISTS idx_schema_cache_kind ON schema_cache (schema_kind);
CREATE INDEX IF NOT EXISTS idx_schema_cache_fetched ON schema_cache (fetched_at);
```

DDL executed via `IF NOT EXISTS` pattern (matching `session_events` and `checkpoints` tables). No Alembic migration — the table is application-managed like existing persistence tables.

**DD-105: 3-Tier Lookup Contract**

`NodeSchemaStore` gains a `pg_cache: SchemaCache | None` parameter. Lookup order:

1. **Memory** (`_index` dict) — O(1), exists today. Each entry carries its `content_hash`.
2. **Postgres** (`schema_cache` table) — TTL-gated, cross-session persistence.
3. **MCP fetch** (`get_node()` via FlowiseMCPTools) — bounded by `_MAX_SCHEMA_REPAIRS`.

Write-back: MCP repair writes to all 3 tiers. First startup against a new Flowise instance: `list_nodes()` → semaphore-gated `get_node()` (max 5 concurrent) → Postgres batch insert.

File snapshot (`flowise_nodes.snapshot.json`) remains as seed for dev/test environments without Postgres.

**Memory cache carries `content_hash`**: Each in-memory entry stores the `content_hash` of the Postgres/API source. After a refresh completes, the owning process invalidates its memory cache for the refreshed scope. Other replicas naturally expire via TTL.

**Credential safety in `put()`/`put_batch()`**: When `schema_kind == 'credential'`, entries are stripped through `_strip_credential_secrets()` before persistence. This mirrors the `_CRED_ALLOWLIST` enforcement in `CredentialStore` (DD-064). Node schemas (`schema_kind == 'node'`) are stored verbatim — they contain no secret material (only `credentialNames`, which is a list of type strings like `["openAIApi"]`).

### Key class

```python
# flowise_dev_agent/knowledge/schema_cache.py

class SchemaCache:
    """Postgres-backed schema cache with TTL gating and content-hash versioning."""

    def __init__(self, pool: AsyncConnectionPool, base_url: str) -> None: ...

    async def setup(self) -> None:
        """Execute DDL (IF NOT EXISTS). Safe to call on every startup."""

    async def get(self, schema_kind: str, type_key: str) -> dict | None:
        """TTL-gated lookup. Returns None if missing or expired.
        Returns dict with '_content_hash' key for memory-tier tracking."""

    async def put(
        self, schema_kind: str, type_key: str, schema_json: dict,
        version: str | None = None, ttl_seconds: int = 86400,
    ) -> None:
        """Upsert single entry with SHA-256 content hash.
        When schema_kind == 'credential', strips secrets via _strip_credential_secrets()."""

    async def put_batch(
        self, schema_kind: str,
        entries: list[tuple[str, dict, str | None]],  # (type_key, schema_json, version)
        ttl_seconds: int = 86400,
    ) -> None:
        """Batch upsert for initial population.
        When schema_kind == 'credential', strips secrets from each entry."""

    async def is_populated(self, schema_kind: str, min_count: int = 100) -> bool:
        """True if cache has >= min_count entries for this kind."""

    async def stale_keys(self, schema_kind: str) -> list[str]:
        """Return type_keys where fetched_at + ttl_seconds < now()."""

    async def count(self, schema_kind: str) -> int:
        """Count entries for a schema kind."""

    async def missing_keys(self, schema_kind: str, known_keys: list[str]) -> list[str]:
        """Return keys from known_keys that are not in cache."""

    async def invalidate(self, schema_kind: str) -> int:
        """Delete all entries for (base_url, schema_kind). Returns count deleted.
        Used by refresh to force re-population."""

    async def refresh_stats(self) -> dict:
        """Return {node_count, credential_count, template_count, last_refresh, stale_count}."""


def _strip_credential_secrets(entry: dict) -> dict:
    """Strip all keys except allowlisted metadata from a credential entry.
    Allowlist: credential_id, name, credentialName, tags, created_at, updated_at.
    Mirrors _CRED_ALLOWLIST from provider.py (DD-064)."""
```

### Files

| File | Change |
|---|---|
| `knowledge/schema_cache.py` | **NEW** — `SchemaCache` class (DDL, get/put/put_batch/count/is_populated/stale_keys/missing_keys/invalidate/refresh_stats), `_strip_credential_secrets()` |
| `knowledge/provider.py` | `NodeSchemaStore.__init__` gains `pg_cache: SchemaCache | None`; `_load()` reads Postgres first when available; `get_or_repair()` uses 3-tier lookup with write-back; memory entries carry `content_hash` |
| `knowledge/refresh.py` | New `--api-populate` flag: bulk MCP fetch → Postgres (replaces `--nodes` as authoritative source) |
| `api.py` | `lifespan()` creates `SchemaCache`, calls `setup()`, passes to knowledge provider |
| `agent/graph.py` | `FlowiseCapability.__init__` passes `pg_pool` to knowledge provider |

### What stays

- `compile_patch_ops()`, `_build_node_data()` — unchanged (richer data flows through automatically)
- `AnchorDictionaryStore` interface — unchanged (rebuilds from richer data)
- `CredentialStore`, `TemplateStore` — unchanged in M11.1
- All 18 graph nodes, HITL interrupts, FastAPI routes — unchanged
- `_normalize_api_schema()` — already preserves all fields; no changes needed

### What's deprecated

- `refresh.py --nodes` (Markdown parsing) — kept for dev/test without Postgres, no longer authoritative
- File-based snapshot as primary source — seed/fallback only when Postgres unavailable

### Tests: `tests/test_m111_schema_substrate.py` (~30 tests)

- `SchemaCache` CRUD: put/get single entry
- TTL gating: expired entry returns `None`
- Batch insert: `put_batch()` with 10+ entries
- `stale_keys()` returns only expired entries
- `is_populated()` threshold check
- `count()` and `missing_keys()` helpers
- `invalidate()` removes all entries for (base_url, schema_kind)
- 3-tier lookup: memory hit (no Postgres call)
- 3-tier lookup: memory miss → Postgres hit
- 3-tier lookup: memory + Postgres miss → MCP repair
- Write-back: MCP repair result persisted to memory + Postgres
- Memory entry carries `content_hash` from source
- Post-refresh: memory cache invalidated for refreshed scope
- Backwards compat: `pg_cache=None` → file snapshot fallback (existing behavior)
- API-populated schema preserves `credentialNames`, `loadMethod`, `step`, `rows`, `options`, `additionalParams`, `show`
- `--api-populate` bulk fetch populates Postgres
- Multi-instance: different `base_url` entries coexist without collision
- Case-insensitive fallback (`_lower_index`) still works with Postgres-sourced data
- Content hash: same schema → no update; changed schema → upserted
- Credential safety: `put()` with `schema_kind='credential'` strips `encryptedData`
- Credential safety: `put_batch()` with `schema_kind='credential'` strips secrets from all entries
- Credential safety: node schema `credentialNames` field preserved (not a secret)
- Credential safety: load-time validation rejects entries with banned keys
- `get()` return includes `_content_hash` for memory tracking

### Acceptance criteria

- `pytest tests/test_m111_schema_substrate.py -v` — all 30 tests pass
- `NodeSchemaStore` with `pg_cache` set loads from Postgres on startup
- `NodeSchemaStore` without `pg_cache` loads from file snapshot (backwards compat)
- Schema fetched via MCP contains `credentialNames`, `loadMethod`, `step`, `rows`, `options`, `additionalParams`, `show` — verified by assertion
- `python -m flowise_dev_agent.knowledge.refresh --api-populate` populates Postgres from live Flowise
- `schema_kind='credential'` entries never contain `encryptedData`, `plainDataObj`, or any key outside the allowlist
- Memory entries carry `content_hash`; `invalidate()` clears them after refresh

### Design decisions

**DD-104**: Postgres Schema Cache Table — `schema_cache` table with `(base_url, schema_kind, type_key)` composite primary key, JSONB schema storage, SHA-256 content hash for version gating, and configurable TTL. Follows existing DDL pattern (`IF NOT EXISTS`, no Alembic). Indexes on `schema_kind` and `fetched_at` for refresh queries. Credential entries are stripped of secrets before persistence via `_strip_credential_secrets()` — mirrors DD-064 `_CRED_ALLOWLIST` pattern.

**DD-105**: 3-Tier Lookup Contract — Memory → Postgres → MCP hierarchy with deterministic refresh triggers. Write-back ensures all tiers stay consistent within a session. File snapshot demoted to seed/fallback. `SchemaCache` is injected via constructor (dependency inversion), not a module-level global. Memory entries carry `content_hash` for staleness awareness. Cross-replica consistency relies on Postgres as source of truth + TTL expiry — no distributed cache required.

---

## M11.2 — Renderer Fidelity (DD-106, DD-107)

### Goal

Fix the 3 remaining compiler gaps that prevent correct Flowise UI rendering, even when full-fidelity schemas are available. Define and enforce a render-safe schema contract.

### Why now

M11.1 delivers full schemas, but 3 compiler gaps remain:
- **GAP 4**: `BindCredential` sets the credential value but never adds the credential inputParam schema entry to `data.inputParams[]`. The Flowise React Flow renderer needs both to show the credential selector dropdown.
- **GAP 7**: `to_flow_data()` returns `{nodes, edges}` without a `viewport` key. Flowise defaults to an origin that may not show the positioned canvas.
- **GAP 8**: `_graph_node_to_flowise()` hardcodes `height: 500`. Nodes with many parameters overflow; nodes with few waste space.

### Changes

**DD-106: Credential InputParam Synthesis**

New function `_ensure_credential_input_param(data, credential_id, credential_type)` — called during `BindCredential` processing in `compile_patch_ops()`.

Logic:
1. Check if `data["inputParams"]` already contains an entry with `"type": "credential"`. If yes, no-op (API-sourced schemas already include it).
2. Otherwise, synthesize from `data.get("credential_required")` or the `credentialNames` field:
   ```python
   {
       "label": "Connect Credential",
       "name": "credential",
       "type": "credential",
       "credentialNames": [credential_type],  # e.g., ["openAIApi"]
       "optional": False,
   }
   ```
3. Insert at position 0 of `data["inputParams"]` (Flowise convention).

This handles both old schemas (pre-M11.1, no credential inputParam) and new schemas (M11.1+, credential inputParam already present from API).

**DD-107: Viewport + Dynamic Node Height + Render-Safe Schema Contract**

`to_flow_data()` changes:
```python
def to_flow_data(self) -> dict:
    return {
        "nodes": [self._graph_node_to_flowise(n) for n in self.nodes.values()],
        "edges": [self._graph_edge_to_flowise(e) for e in self.edges],
        "viewport": {"x": 0, "y": 0, "zoom": 0.8},
    }
```

New function `_compute_node_height(data)`:
```python
def _compute_node_height(data: dict) -> int:
    """Compute node height based on anchor and parameter count."""
    anchors = len(data.get("inputAnchors", [])) + len(data.get("outputAnchors", []))
    params = len(data.get("inputParams", []))
    height = 80 + anchors * 65 + params * 50 + 20  # base + anchors + params + padding
    return max(300, min(height, 2000))  # clamp [300, 2000]
```

`_graph_node_to_flowise()` uses `_compute_node_height(node.data)` instead of hardcoded `500`.

**Render-safe schema contract**: `_ensure_render_safe(data)` is called by `_build_node_data()` after deep-copying the schema. It enforces minimum structural requirements for Flowise React Flow rendering:

| Rule | Condition | Fix applied |
|---|---|---|
| Options present | `type == "options"` or `type == "multiOptions"` | Ensure `options` key exists (default `[]`) |
| Load method present | `type == "asyncOptions"` | Ensure `loadMethod` key exists (default `""`) |
| Native numeric defaults | `type == "number"` and `default` is a string | Coerce to `float` |
| Native boolean defaults | `type == "boolean"` and `default` is a string | Coerce `"true"/"false"` to `bool` |
| Credential param position | credential required and `inputParams[0].type != "credential"` | Handled by `_ensure_credential_input_param()` |

This is applied at normalization time (inside `_build_node_data()`), not as a separate validation pass. The rules are deterministic — no LLM involvement, no MCP calls, no repair loops. They fix structural gaps in schemas regardless of source (Markdown fallback or API).

### Files

| File | Change |
|---|---|
| `agent/compiler.py` | `_compute_node_height()` (new), `_ensure_credential_input_param()` (new), `_ensure_render_safe()` (new), `_graph_node_to_flowise()` uses dynamic height, `to_flow_data()` adds viewport, `BindCredential` handler calls `_ensure_credential_input_param()`, `_build_node_data()` calls `_ensure_render_safe()` |
| `agent/tools.py` | `_validate_flow_data()` emits warning when viewport missing (non-blocking) |

### What stays

- `_resolve_anchor_id()`, `_auto_position()`, `CompileResult` — unchanged
- Patch IR operations — unchanged
- `from_flow_data()` — viewport key naturally preserved in round-trip

### Tests: `tests/test_m112_renderer_fidelity.py` (~25 tests)

- `_compute_node_height()`: minimal node → 300 (floor)
- `_compute_node_height()`: many params → scales correctly
- `_compute_node_height()`: extreme count → 2000 (ceiling)
- Dynamic height in `_graph_node_to_flowise()` output (not 500)
- Viewport key present in `to_flow_data()` with x, y, zoom
- Viewport zoom value is 0.8
- Credential inputParam synthesis: missing → added at position 0
- Credential inputParam synthesis: already present → no-op (no duplicate)
- Credential inputParam: synthesized entry has correct `credentialNames`
- `BindCredential` produces both `data.credential` (value) and inputParams entry (schema)
- Round-trip: `from_flow_data(to_flow_data())` preserves viewport
- `_validate_flow_data()` warns on missing viewport
- `_validate_flow_data()` passes with viewport present
- End-to-end: compile a flow with BindCredential → all 3 fixes present in output
- Render-safe: `type=options` param gets `options: []` if missing
- Render-safe: `type=asyncOptions` param gets `loadMethod: ""` if missing
- Render-safe: `type=number` with string default `"0.9"` → coerced to `0.9`
- Render-safe: `type=boolean` with string default `"true"` → coerced to `True`
- Render-safe: `type=number` with non-numeric string default → left unchanged (no crash)
- Render-safe: `type=options` with `options` already present → no-op
- Render-safe: applied to both API-sourced and Markdown-sourced schemas

### Acceptance criteria

- `pytest tests/test_m112_renderer_fidelity.py -v` — all 25 tests pass
- Compiled flow data contains `viewport` key with `{x, y, zoom}`
- Node heights vary based on parameter count (not fixed 500)
- `BindCredential` produces both `data.credential` and a credential entry in `data.inputParams`
- `type=options` params always have `options` key in compiled output
- `type=asyncOptions` params always have `loadMethod` key in compiled output
- Numeric and boolean defaults are native types, not strings
- Agent-created chatflow opens in Flowise UI without white screen (manual verification)

### Design decisions

**DD-106**: Credential InputParam Synthesis — `_ensure_credential_input_param()` is called during `BindCredential` processing, not during schema normalization. This keeps the compiler self-contained and handles both old (Markdown-sourced) and new (API-sourced) schemas. The function is idempotent — safe to call multiple times.

**DD-107**: Viewport, Dynamic Node Height, and Render-Safe Contract — viewport is a static `{x: 0, y: 0, zoom: 0.8}` (Flowise default). Dynamic height uses a linear formula with floor/ceiling clamps, matching Flowise's own auto-sizing behavior. No runtime measurement — purely schema-driven. The render-safe contract (`_ensure_render_safe()`) is applied at normalization time inside `_build_node_data()` — deterministic fixes, no repair loops, no MCP calls. Rules are minimal: only fix what Flowise React Flow strictly requires to render without error.

### Dependencies

M11.1 (full-fidelity schemas make `credentialNames` available), but the fix also handles old schemas gracefully.

---

## M11.3 — Refresh UX (DD-108, DD-109)

### Goal

Add operator-facing schema refresh endpoints with SSE progress streaming, cross-instance coordination, and backpressure control. Replace CLI-only refresh with an API-first contract that supports UI integration.

### Why now

Schema refresh is CLI-only (`python -m flowise_dev_agent.knowledge.refresh --nodes`). No UI trigger, no progress monitoring, no audit trail. Operators need a way to refresh schemas after Flowise upgrades or node plugin installs without SSH access.

### Changes

**DD-108: POST /platform/schema/refresh**

New `/platform/` route prefix (new endpoints, not modifying existing 16 session/system routes).

```
POST /platform/schema/refresh
  Request body:
    {
      "kinds": ["node"],           // "node" | "template" | "credential" — filter scope
      "force": false               // true = skip version gating, re-fetch everything
    }
  Response (200):
    {
      "refresh_id": "uuid",
      "status": "started"
    }
  Response (409 — refresh already running):
    {
      "refresh_id": "existing-uuid",
      "status": "already_running",
      "started_at": "2026-02-26T10:30:00Z"
    }
```

The endpoint returns immediately. The refresh runs as a background task using the existing `asyncio.create_task` pattern from session management.

**Cross-instance coordination**: Refresh jobs are coordinated via a Postgres advisory lock keyed on `hashtext(base_url || '::' || scope)`. This ensures only one refresh per `(base_url, scope)` runs at a time across all replicas:

```python
# Inside SchemaRefreshService.refresh():
lock_key = hashlib.md5(f"{self._base_url}::{scope}".encode()).digest()[:4]
advisory_key = int.from_bytes(lock_key, "big", signed=True)

async with pool.connection() as conn:
    acquired = await conn.fetchval(
        "SELECT pg_try_advisory_lock($1)", advisory_key
    )
    if not acquired:
        return RefreshSummary(status="already_running", ...)
    try:
        # ... perform refresh ...
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", advisory_key)
```

- `pg_try_advisory_lock` is non-blocking: if another replica holds the lock, the request returns `409` immediately.
- Advisory locks are session-scoped (released on connection close) — no risk of orphaned locks on crash.
- No new tables needed — Postgres advisory locks are built-in.

**Post-refresh memory invalidation**: After a refresh completes successfully, the owning process calls `NodeSchemaStore.invalidate_memory(schema_kind)` to clear its in-memory cache for the refreshed scope. The next `get()` call re-populates from the freshly-updated Postgres tier. Other replicas converge via TTL expiry.

**DD-109: SSE Progress Streaming with Backpressure**

```
GET /platform/schema/refresh/{refresh_id}/stream
  SSE events:
    event: schema_refresh_start
    data: {"refresh_id": "uuid", "kinds": ["node"], "total": 303}

    event: schema_refresh_progress
    data: {"type_key": "chatOpenAI", "status": "updated", "index": 1, "total": 303}

    event: schema_refresh_progress
    data: {"type_key": "openAIEmbeddings", "status": "skipped", "index": 2, "total": 303}

    event: schema_refresh_complete
    data: {"refresh_id": "uuid", "updated": 47, "skipped": 253, "errors": 3, "duration_ms": 12400}
```

Reuses existing SSE pattern from `GET /sessions/{id}/stream`. Progress callbacks from `SchemaRefreshService` are written to an in-memory queue consumed by the SSE endpoint.

**Backpressure and concurrency control**: MCP `get_node()` calls are bounded by an `asyncio.Semaphore(5)` — max 5 concurrent API calls during bulk refresh. This prevents overwhelming the Flowise API when refreshing 300+ node types:

```python
class SchemaRefreshService:
    _FETCH_CONCURRENCY = 5  # max concurrent get_node() calls
    _BATCH_INSERT_SIZE = 50  # Postgres batch insert chunk size

    async def _fetch_all_nodes(self, node_names: list[str], ...) -> ...:
        sem = asyncio.Semaphore(self._FETCH_CONCURRENCY)
        async def _fetch_one(name: str) -> ...:
            async with sem:
                return await self._mcp_tools.get_node(name)
        results = await asyncio.gather(
            *[_fetch_one(n) for n in node_names],
            return_exceptions=True,
        )
        # Batch insert to Postgres in chunks of _BATCH_INSERT_SIZE
        for chunk in _chunked(results, self._BATCH_INSERT_SIZE):
            await self._schema_cache.put_batch("node", chunk)
```

Progress reporting reflects the bounded concurrency — `index` increments as each node completes, not when the gather starts.

**Stats endpoint:**
```
GET /platform/schema/stats
  Response:
    {
      "node_count": 303,
      "credential_count": 12,
      "template_count": 45,
      "last_refresh": "2026-02-26T10:30:00Z",
      "stale_count": 7
    }
```

### Key class

```python
# flowise_dev_agent/knowledge/refresh_service.py

class SchemaRefreshService:
    """Orchestrates MCP → Postgres schema refresh with progress callbacks,
    cross-instance advisory locking, and bounded fetch concurrency."""

    _FETCH_CONCURRENCY = 5   # max concurrent get_node() calls
    _BATCH_INSERT_SIZE = 50   # Postgres batch insert chunk size

    def __init__(
        self,
        schema_cache: SchemaCache,
        mcp_tools: FlowiseMCPTools,
        knowledge_provider: FlowiseKnowledgeProvider,
        pool: AsyncConnectionPool,
    ) -> None: ...

    async def refresh(
        self,
        kinds: list[str],
        force: bool = False,
        on_progress: Callable[[dict], None] | None = None,
    ) -> RefreshSummary:
        """Acquire advisory lock, fetch schemas with bounded concurrency,
        batch-insert to Postgres, invalidate memory cache."""


@dataclass(frozen=True)
class RefreshSummary:
    refresh_id: str
    status: str  # "completed" | "already_running" | "failed"
    updated: int
    skipped: int
    errors: int
    duration_ms: int
    error_details: list[dict]
```

### Files

| File | Change |
|---|---|
| `knowledge/refresh_service.py` | **NEW** — `SchemaRefreshService` class + `RefreshSummary` dataclass |
| `api.py` | 3 new endpoints: `POST /platform/schema/refresh`, `GET /platform/schema/refresh/{id}/stream`, `GET /platform/schema/stats` |
| `knowledge/schema_cache.py` | `refresh_stats()` method (counts + last refresh time) |

### What stays

- All 16 existing session/system endpoints — unchanged
- CLI `refresh.py` — continues to work for scripted/CI usage
- Graph topology, HITL interrupts — unchanged

### Tests: `tests/test_m113_refresh_ux.py` (~22 tests)

- POST `/platform/schema/refresh` returns `refresh_id` and `status: "started"`
- Scoped refresh: `kinds: ["node"]` only refreshes node schemas
- `force: true` skips version gating (re-fetches all)
- `force: false` skips entries with matching `content_hash`
- SSE stream emits `schema_refresh_start` event
- SSE stream emits `schema_refresh_progress` per node type
- SSE stream emits `schema_refresh_complete` with counts
- `RefreshSummary` counts: `updated`, `skipped`, `errors`
- Concurrent refresh on same instance rejected (advisory lock — returns 409 with existing refresh_id)
- Cross-instance: advisory lock prevents parallel refresh for same base_url (mock two connections)
- Advisory lock released on completion (second refresh succeeds after first finishes)
- Advisory lock released on crash (connection close releases session-scoped lock)
- Stats endpoint returns `node_count`, `credential_count`, `template_count`
- Stats endpoint returns `last_refresh` timestamp
- Stats endpoint returns `stale_count`
- Error in single node fetch does not abort entire refresh
- `RefreshSummary.error_details` captures failed type_keys
- Progress callback receives correct `index` and `total`
- Backpressure: max 5 concurrent `get_node()` calls (semaphore enforced)
- Batch inserts: Postgres writes happen in chunks of 50
- Post-refresh: memory cache invalidated for refreshed scope
- Credential refresh: secrets stripped before Postgres insert

### Acceptance criteria

- `pytest tests/test_m113_refresh_ux.py -v` — all 22 tests pass
- `POST /platform/schema/refresh` triggers background refresh and returns immediately
- SSE stream shows real-time progress per node type
- `GET /platform/schema/stats` returns accurate counts from Postgres
- Concurrent refresh attempts on same `(base_url, scope)` return 409 (advisory lock)
- Max 5 concurrent MCP `get_node()` calls during bulk refresh (semaphore)
- Postgres writes happen in batches of 50 (not one-by-one)
- Memory cache invalidated after refresh completes
- Credential entries stripped of secrets before persistence

### Design decisions

**DD-108**: Schema Refresh API Endpoint — new `/platform/` route prefix keeps refresh endpoints separate from existing session/system routes. Returns `refresh_id` immediately for async tracking. Background task pattern matches existing session management. Cross-instance coordination via Postgres advisory lock (`pg_try_advisory_lock`) keyed on `hash(base_url + scope)` — no new tables, no Redis, session-scoped (auto-released on connection close). Post-refresh memory invalidation ensures the refreshing process sees updated data immediately.

**DD-109**: SSE Progress Streaming with Backpressure — reuses existing SSE infrastructure (`StreamingResponse`, `text/event-stream`). Progress events are per-node-type granularity (not per-field). `schema_refresh_complete` includes summary counts for UI display. In-memory queue (not Postgres) for progress events — they're ephemeral and session-scoped. MCP fetch concurrency bounded by `asyncio.Semaphore(5)` — prevents API overload during 300+ node refresh. Postgres writes batched in chunks of 50 for throughput.

### Dependencies

M11.1 (`SchemaCache` table must exist).

---

## M11.4 — Drift Detection + Auto-Repair (DD-110, DD-111)

### Goal

Detect schema drift proactively (Flowise upgrades, new node plugins) and surface it before compile-time failures. Track cache tier hit metrics for observability.

### Why now

Schema drift is currently detected only at compile time via per-node MCP repair. There's no proactive detection, no batch response, and no visibility into cache effectiveness. Operators discover stale schemas only when chatflow creation fails.

### Changes

**DD-110: Compile-Time Gap Detection**

MCP repair in `compile_flow_data` writes back to all 3 tiers (memory + Postgres + confirms). `CompileResult` gains a `schema_gap_metrics` field:

```python
@dataclass
class CompileResult:
    # ... existing fields ...
    schema_gap_metrics: dict | None = None
    # {
    #   "memory_hits": 12,
    #   "postgres_hits": 3,
    #   "api_repairs": 2,
    #   "total_lookups": 17,
    # }
```

If `api_repairs >= 5` in a single `compile_flow_data` call, emit a `schema_drift_detected` event to the session event log. This surfaces in the UI via the existing SSE stream.

**DD-111: Proactive Drift Check (Phase A)**

`hydrate_context` calls `list_nodes()` once per session (lightweight — returns names only). Compares the count against the Postgres cache count.

Decision logic:
- Delta > 5 → `facts["flowise"]["schema_drift"] = {drift_detected: True, delta: N, new_types: [...]}`
- Delta <= 5 → `facts["flowise"]["schema_drift"] = {drift_detected: False}`

The `plan_v2` node references `facts["flowise"]["schema_drift"]` for refresh recommendation in the plan output. The drift check is bounded to exactly one `list_nodes()` call — no cascading fetches.

### Files

| File | Change |
|---|---|
| `agent/graph.py` | `_make_compile_flow_data_node()` write-back to Postgres on MCP repair; `_make_hydrate_context_node()` drift check via `_check_schema_drift()` helper |
| `agent/compiler.py` | `CompileResult` gains `schema_gap_metrics` field |
| `knowledge/schema_cache.py` | `count()` and `missing_keys()` methods (added in M11.1 class definition, wired here) |
| `knowledge/provider.py` | `get_or_repair()` writes to Postgres on successful MCP repair |

### What stays

- `_compute_action_detail()` per-node version gating — unchanged
- `_MAX_SCHEMA_REPAIRS` budget (10/iteration) — unchanged
- `validate_patch_ops()`, all HITL interrupts — unchanged
- `SessionSummary` existing fields — unchanged (new metrics added alongside)

### Tests: `tests/test_m114_drift_detection.py` (~17 tests)

- Compile repair writes back to Postgres + memory (3-tier write-back)
- `schema_gap_metrics` tracks `memory_hits` correctly
- `schema_gap_metrics` tracks `postgres_hits` correctly
- `schema_gap_metrics` tracks `api_repairs` correctly
- `schema_gap_metrics` tracks `total_lookups` correctly
- 5+ API repairs triggers `schema_drift_detected` event emission
- 4 or fewer API repairs does NOT trigger event
- Drift check: live node count > cache count → `drift_detected: True`
- Drift check: counts equal → `drift_detected: False`
- Drift check: delta <= 5 → `drift_detected: False`
- Drift check: `new_types` contains correct missing type keys
- Drift check bounded: exactly one `list_nodes()` call (mock assert)
- Drift result stored in `facts["flowise"]["schema_drift"]`
- `plan_v2` receives drift info when present
- Graceful skip when no MCP client available
- Graceful skip when no Postgres pool available
- `SessionSummary` includes `schema_gap_metrics` when present

### Acceptance criteria

- `pytest tests/test_m114_drift_detection.py -v` — all 17 tests pass
- MCP repair during compile writes back to Postgres (verified by subsequent Postgres read)
- `CompileResult.schema_gap_metrics` populated after every compile
- 5+ repairs emits `schema_drift_detected` to SSE stream
- New Flowise session detects schema drift in Phase A hydrate_context
- Drift detection makes exactly one `list_nodes()` API call

### Design decisions

**DD-110**: Compile-Time Schema Gap Detection — `schema_gap_metrics` added to `CompileResult` for per-compile observability. 5+ API repairs threshold chosen because typical compile involves 5-8 node types; 5+ repairs means most schemas were stale. Event emission uses existing `emit_event` pattern — fire-and-forget, never blocks graph.

**DD-111**: Proactive Drift Detection via Version Comparison — count-based heuristic (not hash comparison) for Phase A check because `list_nodes()` returns only names (lightweight). Threshold of delta > 5 avoids false positives from minor Flowise config differences. New types stored in `facts` for LLM context — the plan node can recommend a refresh. No automatic bulk fetch — that's the operator's decision via M11.3 refresh UX.

### Dependencies

M11.1 (SchemaCache for write-back and count queries) + M11.3 (event emission pattern for drift warnings).

---

## Sequencing

```
M11.1 (Schema Substrate) ─┬─→ M11.2 (Renderer Fidelity)   [parallel after table exists]
                           └─→ M11.3 (Refresh UX) ──→ M11.4 (Drift Detection)
```

M11.1 is the foundation — all other milestones depend on the Postgres cache table. M11.2 and M11.3 can proceed in parallel once M11.1 ships. M11.4 requires both M11.1 (for cache queries) and M11.3 (for event emission infrastructure).

---

## Cross-Cutting Concerns

### Gap 1: Multi-Instance Coordination

**Problem**: Multiple replicas could attempt concurrent refreshes, wasting API budget and causing write conflicts.

**Solution**: Postgres advisory lock in M11.3 (`pg_try_advisory_lock` keyed on `hash(base_url + scope)`). Non-blocking — duplicate requests return 409 immediately with the existing refresh_id. Session-scoped locks auto-release on crash/disconnect. No new tables.

**Where defined**: M11.3 DD-108 (refresh endpoint) + M11.1 DD-105 (write-back contract).

### Gap 2: Cache Invalidation Between Tiers

**Problem**: Memory cache on one replica could serve stale data after another replica refreshes Postgres.

**Solution**: Memory entries carry `content_hash`. Post-refresh, the owning process invalidates its memory cache. Other replicas rely on TTL expiry (24h default). No distributed cache needed — staleness is bounded by TTL, same as today's file-snapshot behavior but with a ceiling.

**Where defined**: M11.1 DD-105 (cross-tier consistency model) + M11.3 DD-108 (post-refresh invalidation).

### Gap 3: Render-Safe Schema Contract

**Problem**: Even with full API data, some schemas may have structurally incomplete params (missing `options[]` for type=options, string defaults for numbers).

**Solution**: `_ensure_render_safe()` in M11.2 — deterministic fixer applied at normalization time inside `_build_node_data()`. No repair loops, no MCP calls. 5 rules covering options, asyncOptions, numeric defaults, boolean defaults, and credential position.

**Where defined**: M11.2 DD-107.

### Gap 4: Refresh Backpressure

**Problem**: Bulk refresh of 300+ nodes could overwhelm the Flowise API with concurrent requests.

**Solution**: `asyncio.Semaphore(5)` in M11.3 `SchemaRefreshService`. Postgres writes batched in chunks of 50. Progress reporting reflects actual completion, not gather initiation.

**Where defined**: M11.3 DD-109.

### Gap 5: Credential Data Safety

**Problem**: Schema cache could accidentally persist secret material from credential API responses.

**Solution**: `_strip_credential_secrets()` in M11.1 `SchemaCache` — called on every `put()`/`put_batch()` when `schema_kind == 'credential'`. Mirrors `_CRED_ALLOWLIST` from DD-064. Node schemas are safe — `credentialNames` is a type-string array, not secret data. Load-time validation rejects banned keys.

**Where defined**: M11.1 DD-104 (credential safety boundaries in architecture section + SchemaCache class).

---

## DD Allocation

| DD | Milestone | Title |
|---|---|---|
| DD-104 | M11.1 | Postgres Schema Cache Table |
| DD-105 | M11.1 | 3-Tier Lookup Contract |
| DD-106 | M11.2 | Credential InputParam Synthesis |
| DD-107 | M11.2 | Viewport, Dynamic Node Height, and Render-Safe Contract |
| DD-108 | M11.3 | Schema Refresh API with Cross-Instance Advisory Locking |
| DD-109 | M11.3 | SSE Progress Streaming with Backpressure Control |
| DD-110 | M11.4 | Compile-Time Schema Gap Detection |
| DD-111 | M11.4 | Proactive Drift Detection via Version Comparison |

Next free DD after R11: **DD-112**

---

## Test Summary

| Milestone | New Tests | Cumulative |
|---|---|---|
| Pre-R11 | — | 591 |
| M11.1 | ~30 | ~621 |
| M11.2 | ~25 | ~646 |
| M11.3 | ~22 | ~668 |
| M11.4 | ~17 | ~685 |

---

## Verification

1. **M11.1**: `pytest tests/test_m111_schema_substrate.py -v` — 3-tier lookup works, API-sourced schemas contain all renderer-critical fields, credential entries stripped of secrets
2. **M11.2**: Create a chatflow via agent → opens in Flowise UI without white screen (credential selector renders, nodes sized correctly, canvas positioned, options/asyncOptions params render correctly)
3. **M11.3**: `POST /platform/schema/refresh` → SSE stream shows progress → `GET /platform/schema/stats` shows updated counts → concurrent POST returns 409
4. **M11.4**: Start session against a Flowise with a new node type → drift detected in Phase A → compile uses MCP repair → schema persisted to Postgres for next session
5. **Full suite**: `pytest tests/ -x --ignore=tests/e2e -q` — 685+ tests, no regressions

---

## Key file inventory

### New files (6)

| File | Purpose |
|---|---|
| `flowise_dev_agent/knowledge/schema_cache.py` | `SchemaCache` class — Postgres-backed 3-tier cache with credential safety |
| `flowise_dev_agent/knowledge/refresh_service.py` | `SchemaRefreshService` — orchestrates MCP → Postgres refresh with advisory locking + backpressure |
| `tests/test_m111_schema_substrate.py` | M11.1 tests |
| `tests/test_m112_renderer_fidelity.py` | M11.2 tests |
| `tests/test_m113_refresh_ux.py` | M11.3 tests |
| `tests/test_m114_drift_detection.py` | M11.4 tests |

### Modified files (6)

| File | Milestones | Changes |
|---|---|---|
| `knowledge/provider.py` | M11.1, M11.4 | 3-tier lookup in `NodeSchemaStore`, memory entries carry `content_hash`, `invalidate_memory()`, Postgres write-back on repair |
| `knowledge/refresh.py` | M11.1 | `--api-populate` flag for bulk MCP → Postgres |
| `agent/compiler.py` | M11.2, M11.4 | `_compute_node_height()`, `_ensure_credential_input_param()`, `_ensure_render_safe()`, viewport, `schema_gap_metrics` |
| `agent/tools.py` | M11.2 | viewport warning in `_validate_flow_data()` |
| `agent/graph.py` | M11.1, M11.4 | Pool injection, compile write-back, drift check in hydrate_context |
| `api.py` | M11.1, M11.3 | SchemaCache setup in lifespan, 3 new `/platform/` endpoints |
