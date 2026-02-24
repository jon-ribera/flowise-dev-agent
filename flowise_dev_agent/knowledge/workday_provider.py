"""Workday knowledge provider — Milestone 4 stubs.

Roadmap 6, Milestone 4: scaffolds the WorkdayKnowledgeProvider and its two
sub-stores (WorkdayMcpStore, WorkdayApiStore).  All public lookup methods raise
NotImplementedError — real implementations are deferred to Milestone 5+.

Design rationale (DD-065):
- Mirrors the FlowiseKnowledgeProvider pattern (provider.py) so that future
  implementors have a clear template to follow.
- Snapshot files (workday_mcp.snapshot.json, workday_api.snapshot.json) exist
  on disk with status="stub" so that the refresh CLI can already accept
  --workday-mcp / --workday-api flags without failing.
- No imports from flowise_dev_agent.knowledge.provider — intentionally
  independent to avoid coupling Workday and Flowise knowledge layers.
- DomainCapability integration (WorkdayCapability in agent/domains/workday.py)
  will accept a WorkdayKnowledgeProvider in a future milestone.

Public surface:
    WorkdayKnowledgeProvider — holds WorkdayMcpStore + WorkdayApiStore.
    WorkdayMcpStore          — stub; future: Workday MCP endpoint metadata.
    WorkdayApiStore          — stub; future: Workday REST/SOAP API metadata.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCHEMAS_DIR = _REPO_ROOT / "schemas"

_WORKDAY_MCP_SNAPSHOT = _SCHEMAS_DIR / "workday_mcp.snapshot.json"
_WORKDAY_MCP_META = _SCHEMAS_DIR / "workday_mcp.meta.json"
_WORKDAY_API_SNAPSHOT = _SCHEMAS_DIR / "workday_api.snapshot.json"
_WORKDAY_API_META = _SCHEMAS_DIR / "workday_api.meta.json"

_NOT_IMPLEMENTED_MSG = (
    "WorkdayKnowledgeProvider is a Milestone 4 stub. "
    "Real implementation is deferred to Milestone 5+. "
    "See roadmap6_architecture_optimization.md section on Workday integration."
)


# ---------------------------------------------------------------------------
# WorkdayMcpStore
# ---------------------------------------------------------------------------


class WorkdayMcpStore:
    """Stub store for Workday MCP endpoint metadata.

    Milestone 4: scaffold only — all lookup methods raise NotImplementedError.

    Future implementation:
    - Will load from schemas/workday_mcp.snapshot.json.
    - Will expose get(endpoint_name) → dict | None for MCP tool descriptions.
    - Refresh CLI: python -m flowise_dev_agent.knowledge.refresh --workday-mcp
    """

    def __init__(
        self,
        snapshot_path: Path = _WORKDAY_MCP_SNAPSHOT,
        meta_path: Path = _WORKDAY_MCP_META,
    ) -> None:
        self._snapshot_path = snapshot_path
        self._meta_path = meta_path
        logger.debug(
            "[WorkdayMcpStore] Initialised (stub) — snapshot: %s", snapshot_path
        )

    def get(self, endpoint_name: str) -> dict:
        """Return MCP endpoint metadata by name.

        Raises
        ------
        NotImplementedError
            Always — WorkdayMcpStore is a Milestone 4 stub.
        """
        raise NotImplementedError(
            f"WorkdayMcpStore.get({endpoint_name!r}) is not implemented. "
            + _NOT_IMPLEMENTED_MSG
        )

    def find(self, tags: list[str], limit: int = 3) -> list[dict]:
        """Search MCP endpoints by tags.

        Raises
        ------
        NotImplementedError
            Always — WorkdayMcpStore is a Milestone 4 stub.
        """
        raise NotImplementedError(
            f"WorkdayMcpStore.find(tags={tags!r}) is not implemented. "
            + _NOT_IMPLEMENTED_MSG
        )

    def is_stale(self, ttl_seconds: int | None = None) -> bool:
        """Return staleness flag for the MCP snapshot.

        Raises
        ------
        NotImplementedError
            Always — WorkdayMcpStore is a Milestone 4 stub.
        """
        raise NotImplementedError(
            "WorkdayMcpStore.is_stale() is not implemented. " + _NOT_IMPLEMENTED_MSG
        )

    @property
    def item_count(self) -> int:
        """Return number of loaded MCP endpoints.

        Raises
        ------
        NotImplementedError
            Always — WorkdayMcpStore is a Milestone 4 stub.
        """
        raise NotImplementedError(
            "WorkdayMcpStore.item_count is not implemented. " + _NOT_IMPLEMENTED_MSG
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
            "[WorkdayKnowledgeProvider] Initialised (stub) — "
            "all lookup methods raise NotImplementedError until Milestone 5+"
        )

    @property
    def mcp_store(self) -> WorkdayMcpStore:
        """The Workday MCP endpoint sub-store (Milestone 4 stub)."""
        return self._mcp_store

    @property
    def api_store(self) -> WorkdayApiStore:
        """The Workday API endpoint sub-store (Milestone 4 stub)."""
        return self._api_store
