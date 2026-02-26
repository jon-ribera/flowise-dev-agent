"""AnchorDictionaryStore — canonical anchor dictionary derived from NodeSchemaStore.

Milestone 10.2a (DD-093).

This is a **derived view** of NodeSchemaStore: it consumes NodeSchemaStore._index
and builds per-node-type anchor dictionaries with canonical names, types, id
templates, and advisory compatible_types lists.

It does NOT introduce a parallel snapshot file or pipeline.  If the underlying
NodeSchemaStore is refreshed or repaired, callers should discard and recreate the
AnchorDictionaryStore (or call invalidate()).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Regex to split CamelCase tokens: "BaseChatMemory" -> ["Base", "Chat", "Memory"]
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def compute_compatible_types(type_str: str) -> list[str]:
    """Compute compatible_types from a pipe-separated type string.

    Strategy:
    1. Split on ``|`` (with surrounding whitespace stripped).
    2. For each type token, add it to the list.
    3. Also add CamelCase parent tokens: for "BaseChatMemory" add "BaseMemory"
       by dropping one middle CamelCase segment at a time, plus any suffix
       formed by the last N segments.

    The result is deduplicated and ordered: explicit types first, then derived
    parent tokens.

    ``compatible_types`` is **advisory only** — never used as a hard gate.
    """
    if not type_str:
        return []

    # Step 1: split on pipe
    explicit = [t.strip() for t in type_str.split("|") if t.strip()]

    # Step 2: derive CamelCase parent tokens
    derived: list[str] = []
    for token in explicit:
        parts = _CAMEL_RE.split(token)
        if len(parts) <= 1:
            continue
        # Generate parent tokens by dropping middle segments.
        # e.g. "BaseChatMemory" -> parts=["Base","Chat","Memory"]
        #   drop "Chat" -> "BaseMemory"
        # e.g. "BaseChatOpenAI" -> parts=["Base","Chat","Open","A","I"]
        #   We generate: first + last (skip middles of len>2)
        for i in range(1, len(parts) - 1):
            parent = "".join(parts[:i] + parts[i + 1 :])
            if parent not in explicit and parent not in derived:
                derived.append(parent)

    return explicit + derived


def normalize_schema_to_anchor_dict(schema: dict, node_type: str) -> dict:
    """Convert a node schema (snapshot format) to canonical anchor dictionary.

    Parameters
    ----------
    schema:
        A single node schema dict from NodeSchemaStore._index, with keys
        ``inputAnchors``, ``outputAnchors``, etc.
    node_type:
        The canonical node type name (e.g. ``"toolAgent"``).

    Returns
    -------
    A dict with ``node_type``, ``input_anchors``, ``output_anchors``.
    """
    input_anchors = []
    for anchor in schema.get("inputAnchors", []):
        entry = _make_anchor_entry(anchor, node_type, "input")
        input_anchors.append(entry)

    output_anchors = []
    for anchor in schema.get("outputAnchors", []):
        entry = _make_anchor_entry(anchor, node_type, "output")
        output_anchors.append(entry)

    return {
        "node_type": node_type,
        "input_anchors": input_anchors,
        "output_anchors": output_anchors,
    }


def _make_anchor_entry(
    anchor: dict, node_type: str, direction: str
) -> dict[str, Any]:
    """Build a single canonical anchor entry from raw schema anchor data."""
    name = anchor.get("name", "")
    type_str = anchor.get("type", "")
    optional = anchor.get("optional", False)

    # id_template: prefer schema-provided id, else fabricate
    schema_id = anchor.get("id", "")
    if schema_id:
        id_template = schema_id
        entry: dict[str, Any] = {
            "name": name,
            "type": type_str,
            "optional": bool(optional),
            "id_template": id_template,
            "compatible_types": compute_compatible_types(type_str),
        }
    else:
        # Fabricate from convention
        id_template = f"{{nodeId}}-{direction}-{name}-{type_str}"
        entry = {
            "name": name,
            "type": type_str,
            "optional": bool(optional),
            "id_template": id_template,
            "id_source": "fabricated",
            "compatible_types": compute_compatible_types(type_str),
        }

    return entry


# ---------------------------------------------------------------------------
# AnchorDictionaryStore
# ---------------------------------------------------------------------------


class AnchorDictionaryStore:
    """Canonical anchor dictionary derived from NodeSchemaStore.

    This is a read-through view: it lazily builds indices from the underlying
    NodeSchemaStore._index on first access and caches the result.

    If the NodeSchemaStore is refreshed or repaired, call ``invalidate()`` to
    force a rebuild on the next access.
    """

    def __init__(
        self,
        node_schema_store: Any,  # NodeSchemaStore (avoid circular import)
        api_fetcher: Optional[Callable] = None,
    ) -> None:
        self._nss = node_schema_store
        self._api_fetcher = api_fetcher

        # Primary index: node_type -> {node_type, input_anchors, output_anchors}
        self._by_node_type: dict[str, dict] = {}
        # Secondary indices for O(1) cross-node lookups
        self._by_anchor_name: dict[str, list[dict]] = {}
        self._by_type_token: dict[str, list[dict]] = {}

        self._built = False

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        """Build all indices from NodeSchemaStore._index."""
        if self._built:
            return

        # Ensure NSS has loaded its snapshot
        self._nss._load()

        self._by_node_type.clear()
        self._by_anchor_name.clear()
        self._by_type_token.clear()

        for node_type, schema in self._nss._index.items():
            entry = normalize_schema_to_anchor_dict(schema, node_type)
            self._by_node_type[node_type] = entry

            # Populate secondary indices
            for direction in ("input_anchors", "output_anchors"):
                for anchor in entry[direction]:
                    aname = anchor["name"]
                    self._by_anchor_name.setdefault(aname, []).append(
                        {"node_type": node_type, "direction": direction, **anchor}
                    )
                    for ctype in anchor.get("compatible_types", []):
                        self._by_type_token.setdefault(ctype, []).append(
                            {"node_type": node_type, "direction": direction, **anchor}
                        )

        self._built = True
        logger.info(
            "[AnchorDictionaryStore] Built anchor dictionaries for %d node types",
            len(self._by_node_type),
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def invalidate(self) -> None:
        """Force rebuild on next access (call after NSS refresh/repair)."""
        self._built = False
        self._by_node_type.clear()
        self._by_anchor_name.clear()
        self._by_type_token.clear()

    def get(self, node_type: str) -> dict | None:
        """Return anchor dictionary for node_type, or None if not in snapshot.

        Sync, O(1) from warm cache.
        """
        self._build()
        return self._by_node_type.get(node_type)

    async def get_or_repair(
        self,
        node_type: str,
        api_fetcher: Optional[Callable] = None,
    ) -> dict | None:
        """Return anchor dictionary, repairing from API if missing.

        If the node_type is not in the current index, calls api_fetcher to
        retrieve the raw schema, normalizes it into the canonical anchor
        dictionary format, and updates the indices.

        Parameters
        ----------
        node_type:
            Flowise node type name.
        api_fetcher:
            Async callable: (node_type: str) -> dict | None.
            Falls back to self._api_fetcher if not provided.
        """
        self._build()

        cached = self._by_node_type.get(node_type)
        if cached is not None:
            return cached

        fetcher = api_fetcher or self._api_fetcher
        if fetcher is None:
            logger.warning(
                "[AnchorDictionaryStore] No api_fetcher — cannot repair '%s'",
                node_type,
            )
            return None

        logger.info(
            "[AnchorDictionaryStore] REPAIR: '%s' not in index — fetching via API",
            node_type,
        )

        try:
            raw = await fetcher(node_type)
        except Exception as exc:
            logger.warning(
                "[AnchorDictionaryStore] REPAIR fetch failed for '%s': %s",
                node_type,
                exc,
            )
            return None

        if not raw or not isinstance(raw, dict) or "error" in raw:
            logger.warning(
                "[AnchorDictionaryStore] REPAIR: API returned no usable schema for '%s'",
                node_type,
            )
            return None

        # Normalize: the raw API response needs _normalize_api_schema first
        # (to produce snapshot-format keys), then our anchor normalization.
        from flowise_dev_agent.knowledge.provider import _normalize_api_schema

        normalized_schema = _normalize_api_schema(raw)
        entry = normalize_schema_to_anchor_dict(normalized_schema, node_type)

        # Update indices
        self._by_node_type[node_type] = entry
        for direction in ("input_anchors", "output_anchors"):
            for anchor in entry[direction]:
                aname = anchor["name"]
                self._by_anchor_name.setdefault(aname, []).append(
                    {"node_type": node_type, "direction": direction, **anchor}
                )
                for ctype in anchor.get("compatible_types", []):
                    self._by_type_token.setdefault(ctype, []).append(
                        {"node_type": node_type, "direction": direction, **anchor}
                    )

        logger.info(
            "[AnchorDictionaryStore] REPAIR applied for '%s': "
            "%d inputs, %d outputs",
            node_type,
            len(entry["input_anchors"]),
            len(entry["output_anchors"]),
        )
        return entry

    def by_anchor_name(self, name: str) -> list[dict]:
        """Return all anchor entries across all node types with this name."""
        self._build()
        return self._by_anchor_name.get(name, [])

    def by_type_token(self, type_token: str) -> list[dict]:
        """Return all anchor entries compatible with this type token."""
        self._build()
        return self._by_type_token.get(type_token, [])

    @property
    def node_count(self) -> int:
        """Number of node types with anchor dictionaries."""
        self._build()
        return len(self._by_node_type)
