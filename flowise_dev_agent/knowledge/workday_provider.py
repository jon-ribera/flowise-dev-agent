"""Workday knowledge provider — Milestone 4 scaffold; WorkdayMcpStore real (M7.5).

Roadmap 6, Milestone 4: scaffolded WorkdayKnowledgeProvider and WorkdayApiStore.
Roadmap 7, Milestone 7.5: WorkdayMcpStore now loads blueprints from the snapshot
and exposes get() / find() / is_stale() / item_count without raising NotImplementedError.

Design rationale (DD-065):
- Mirrors the FlowiseKnowledgeProvider pattern (provider.py) for consistency.
- Snapshot file: schemas/workday_mcp.snapshot.json — blueprint list, NOT live MCP data.
- No imports from flowise_dev_agent.knowledge.provider — intentionally independent.
- WorkdayApiStore remains a stub (no real Workday REST/SOAP calls in scope).

Public surface:
    WorkdayKnowledgeProvider — holds WorkdayMcpStore + WorkdayApiStore.
    WorkdayMcpStore          — real (M7.5): blueprint lookup + keyword search.
    WorkdayApiStore          — stub; Workday REST/SOAP deferred to future milestone.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCHEMAS_DIR = _REPO_ROOT / "schemas"

_WORKDAY_MCP_SNAPSHOT = _SCHEMAS_DIR / "workday_mcp.snapshot.json"
_WORKDAY_MCP_META = _SCHEMAS_DIR / "workday_mcp.meta.json"
_WORKDAY_API_SNAPSHOT = _SCHEMAS_DIR / "workday_api.snapshot.json"
_WORKDAY_API_META = _SCHEMAS_DIR / "workday_api.meta.json"

_NOT_IMPLEMENTED_MSG = (
    "WorkdayApiStore is a stub. "
    "Real Workday REST/SOAP API integration is deferred to a future milestone. "
    "See roadmap7_multi_domain_runtime_hardening.md."
)


# ---------------------------------------------------------------------------
# WorkdayMcpStore — real implementation (Milestone 7.5)
# ---------------------------------------------------------------------------


class WorkdayMcpStore:
    """Blueprint store for Workday Custom MCP tool configurations.

    Loads from schemas/workday_mcp.snapshot.json — a list of blueprint dicts
    describing how to wire Workday via Flowise's ``customMCP`` selected_tool.

    Each blueprint has a unique ``blueprint_id`` key.

    Refresh:
        python -m flowise_dev_agent.knowledge.refresh --workday-mcp

    See roadmap7_multi_domain_runtime_hardening.md — Milestone 7.5.
    """

    def __init__(
        self,
        snapshot_path: Path = _WORKDAY_MCP_SNAPSHOT,
        meta_path: Path = _WORKDAY_MCP_META,
    ) -> None:
        self._snapshot_path = snapshot_path
        self._meta_path = meta_path
        self._data: list[dict[str, Any]] | None = None
        self._index: dict[str, dict[str, Any]] = {}
        logger.debug("[WorkdayMcpStore] Initialised — snapshot: %s", snapshot_path)

    # ------------------------------------------------------------------
    # Internal loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Lazily load blueprints from the snapshot file."""
        if self._data is not None:
            return
        if not self._snapshot_path.exists():
            logger.warning(
                "[WorkdayMcpStore] Snapshot not found at %s — returning empty store",
                self._snapshot_path,
            )
            self._data = []
            self._index = {}
            return
        try:
            raw = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("[WorkdayMcpStore] Failed to parse snapshot: %s", exc)
            self._data = []
            self._index = {}
            return
        if not isinstance(raw, list):
            logger.error(
                "[WorkdayMcpStore] Snapshot is not a JSON array — treating as empty"
            )
            self._data = []
            self._index = {}
            return
        self._data = [entry for entry in raw if isinstance(entry, dict)]
        self._index = {
            entry["blueprint_id"]: entry
            for entry in self._data
            if entry.get("blueprint_id")
        }
        logger.debug("[WorkdayMcpStore] Loaded %d blueprint(s)", len(self._data))

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get(self, blueprint_id: str) -> dict[str, Any] | None:
        """Return a blueprint by its blueprint_id, or None if not found."""
        self._load()
        return self._index.get(blueprint_id)

    def find(self, tags: list[str], limit: int = 3) -> list[dict[str, Any]]:
        """Return blueprints whose description, mcp_actions, or tags overlap with *tags*.

        Keyword search: any tag substring match against description, mcp_actions list,
        or the blueprint's own tags list.  Returns up to *limit* results.
        """
        self._load()
        if not tags or not self._data:
            return (self._data or [])[:limit]

        keywords = [t.lower() for t in tags]
        scored: list[tuple[int, dict]] = []
        for bp in self._data:
            score = 0
            desc = (bp.get("description") or "").lower()
            bp_tags = [t.lower() for t in (bp.get("tags") or [])]
            actions = [a.lower() for a in (bp.get("mcp_actions") or [])]
            category = (bp.get("category") or "").lower()
            search_corpus = " ".join([desc, category] + bp_tags + actions)
            for kw in keywords:
                if kw in search_corpus:
                    score += 1
            if score > 0:
                scored.append((score, bp))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [bp for _, bp in scored[:limit]]

    def is_stale(self, ttl_seconds: int | None = None) -> bool:
        """Return True if the snapshot is older than *ttl_seconds*.

        Reads ``generated_at`` from the meta file.  Returns False when the meta
        file is absent (not stale by assumption — just refresh not yet run).
        """
        if not self._meta_path.exists():
            return False
        try:
            meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
            generated_at_str = meta.get("generated_at")
            if not generated_at_str:
                return False
            generated_at = datetime.datetime.fromisoformat(
                generated_at_str.replace("Z", "+00:00")
            )
            now = datetime.datetime.now(datetime.timezone.utc)
            age_seconds = (now - generated_at).total_seconds()
            effective_ttl = ttl_seconds if ttl_seconds is not None else 86400
            return age_seconds > effective_ttl
        except Exception as exc:
            logger.debug("[WorkdayMcpStore] is_stale() error: %s", exc)
            return False

    @property
    def item_count(self) -> int:
        """Return number of loaded blueprints."""
        self._load()
        return len(self._data or [])


# ---------------------------------------------------------------------------
# WorkdayApiStore
# ---------------------------------------------------------------------------


class WorkdayApiStore:
    """Stub store for Workday REST/SOAP API endpoint metadata.

    Milestone 4: scaffold only — all lookup methods raise NotImplementedError.

    Future implementation:
    - Will load from schemas/workday_api.snapshot.json.
    - Will expose get(api_name) → dict | None for API endpoint descriptions.
    - Refresh CLI: python -m flowise_dev_agent.knowledge.refresh --workday-api
    """

    def __init__(
        self,
        snapshot_path: Path = _WORKDAY_API_SNAPSHOT,
        meta_path: Path = _WORKDAY_API_META,
    ) -> None:
        self._snapshot_path = snapshot_path
        self._meta_path = meta_path
        logger.debug(
            "[WorkdayApiStore] Initialised (stub) — snapshot: %s", snapshot_path
        )

    def get(self, api_name: str) -> dict:
        """Return API endpoint metadata by name.

        Raises
        ------
        NotImplementedError
            Always — WorkdayApiStore is a Milestone 4 stub.
        """
        raise NotImplementedError(
            f"WorkdayApiStore.get({api_name!r}) is not implemented. "
            + _NOT_IMPLEMENTED_MSG
        )

    def find(self, tags: list[str], limit: int = 3) -> list[dict]:
        """Search API endpoints by tags.

        Raises
        ------
        NotImplementedError
            Always — WorkdayApiStore is a Milestone 4 stub.
        """
        raise NotImplementedError(
            f"WorkdayApiStore.find(tags={tags!r}) is not implemented. "
            + _NOT_IMPLEMENTED_MSG
        )

    def is_stale(self, ttl_seconds: int | None = None) -> bool:
        """Return staleness flag for the API snapshot.

        Raises
        ------
        NotImplementedError
            Always — WorkdayApiStore is a Milestone 4 stub.
        """
        raise NotImplementedError(
            "WorkdayApiStore.is_stale() is not implemented. " + _NOT_IMPLEMENTED_MSG
        )

    @property
    def item_count(self) -> int:
        """Return number of loaded API endpoints.

        Raises
        ------
        NotImplementedError
            Always — WorkdayApiStore is a Milestone 4 stub.
        """
        raise NotImplementedError(
            "WorkdayApiStore.item_count is not implemented. " + _NOT_IMPLEMENTED_MSG
        )

    def _stub_meta(self) -> dict:
        """Return the stub meta dict from disk (informational only)."""
        if self._meta_path.exists():
            try:
                return json.loads(self._meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"status": "stub"}


# ---------------------------------------------------------------------------
# WorkdayKnowledgeProvider
# ---------------------------------------------------------------------------


class WorkdayKnowledgeProvider:
    """Stub provider for all Workday local-first platform knowledge.

    Milestone 4: scaffold only — sub-stores raise NotImplementedError on all
    lookup methods.  The provider itself is safe to instantiate.

    Follows the same pattern as FlowiseKnowledgeProvider (provider.py) so that
    future milestones can add real implementations without changing call sites.

    Integration:
    - Will be instantiated inside WorkdayCapability.__init__ (domains/workday.py).
    - graph.py / build_graph() does NOT need to change to accommodate this.

    Usage (future — not yet wired):
        provider = WorkdayKnowledgeProvider()
        endpoint = provider.mcp_store.get("hire_employee")  # raises NotImplementedError now
    """

    def __init__(self, schemas_dir: Path | None = None) -> None:
        base = schemas_dir or _SCHEMAS_DIR
        self._mcp_store = WorkdayMcpStore(
            base / "workday_mcp.snapshot.json",
            base / "workday_mcp.meta.json",
        )
        self._api_store = WorkdayApiStore(
            base / "workday_api.snapshot.json",
            base / "workday_api.meta.json",
        )
        logger.info(
            "[WorkdayKnowledgeProvider] Initialised — "
            "WorkdayMcpStore: blueprint lookup ready; WorkdayApiStore: stub (future milestone)"
        )

    @property
    def mcp_store(self) -> WorkdayMcpStore:
        """The Workday MCP endpoint sub-store (Milestone 4 stub)."""
        return self._mcp_store

    @property
    def api_store(self) -> WorkdayApiStore:
        """The Workday API endpoint sub-store (Milestone 4 stub)."""
        return self._api_store
