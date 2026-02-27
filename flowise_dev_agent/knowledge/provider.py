"""FlowiseKnowledgeProvider — local-first node schema store with repair fallback.

Roadmap 6, Milestones 1–3.

Design constraints (from ROADMAP6_Platform Knowledge.md):
- MUST NOT create a parallel capability fork.
- MUST NOT inject full snapshot into prompts.
- Default: read from local JSON snapshot (O(1) lookup).
- Fallback: targeted API call ONLY for a missing/stale entry (repair-only).

Integration points (the ONLY files that touch this module):
- agent/graph.py — FlowiseCapability.__init__ instantiates FlowiseKnowledgeProvider;
                    _make_patch_node_v2 Phase D uses node_schemas.get_or_repair();
                    _make_patch_node_v2 Phase C.2 uses credential_store.resolve_or_repair();
                    _make_plan_node uses template_store.find() for planning hints.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — must exactly match tools.py to classify anchors vs params
# ---------------------------------------------------------------------------

# Flowise input types that map to inputParams (configurable fields).
# Any type NOT in this set is an inputAnchor (node-connection point).
# Keep in sync with _FLOWISE_PRIMITIVE_TYPES in agent/tools.py.
_PRIMITIVE_TYPES: frozenset[str] = frozenset({
    "string", "number", "boolean", "password", "json", "code",
    "file", "date", "credential", "asyncOptions", "options",
    "datagrid", "tabs", "multiOptions", "array",
})

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_NODES_SNAPSHOT = _SCHEMAS_DIR / "flowise_nodes.snapshot.json"
_NODES_META = _SCHEMAS_DIR / "flowise_nodes.meta.json"
_TEMPLATES_SNAPSHOT = _SCHEMAS_DIR / "flowise_templates.snapshot.json"
_TEMPLATES_META = _SCHEMAS_DIR / "flowise_templates.meta.json"

# Default TTL for the template snapshot (24 h). Override via env var.
_DEFAULT_TEMPLATE_TTL = 86_400

_CRED_SNAPSHOT = _SCHEMAS_DIR / "flowise_credentials.snapshot.json"
_CRED_META = _SCHEMAS_DIR / "flowise_credentials.meta.json"

# Default TTL for the credential snapshot (1 h). Override via env var.
# Credentials change more frequently than node schemas or templates.
_DEFAULT_CREDENTIAL_TTL = 3_600

# Allowlist: ONLY these keys may appear in flowise_credentials.snapshot.json.
# Any other key (encryptedData, apiKey, token, password, …) is stripped by the
# refresh job and triggers an error if found at load time. See DD-064.
_CRED_ALLOWLIST: frozenset[str] = frozenset({
    "credential_id", "name", "type", "tags", "created_at", "updated_at",
})

# UUID v4 pattern — used to distinguish UUID lookups from name/type lookups.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Schema normalisation
# ---------------------------------------------------------------------------


def _normalize_api_schema(raw: dict) -> dict:
    """Convert a raw Flowise API get_node response to the normalized snapshot format.

    The output format matches _get_node_processed() in agent/tools.py so that
    schema_cache entries populated from the local snapshot are structurally
    identical to entries populated from a live API call.  This is the ONLY place
    that performs this transformation — keeping it here means tools.py is never
    imported by the knowledge layer.
    """
    node_name = raw.get("name", "")
    base_classes = raw.get("baseClasses", [])
    raw_inputs = raw.get("inputs", [])

    input_anchors: list[dict] = []
    input_params: list[dict] = []

    for inp in raw_inputs:
        entry = dict(inp)
        inp_type = entry.get("type", "")
        entry["id"] = f"{{nodeId}}-input-{entry.get('name', '')}-{inp_type}"
        if inp_type in _PRIMITIVE_TYPES:
            input_params.append(entry)
        else:
            input_anchors.append(entry)

    # Build outputAnchors from the authoritative source — in priority order:
    #   1. raw["outputs"] — present in Flowise API responses, contains real output names
    #      (e.g. "retriever", "vectorStore") and their baseClasses per output slot.
    #   2. raw["outputAnchors"] — legacy field; used when "outputs" is absent.
    #   3. Synthesize from node-level baseClasses — fallback for single-output nodes
    #      where the API provides neither field.
    raw_outputs = raw.get("outputs") or []  # Flowise API: [{name, label, baseClasses}]
    raw_oa = raw.get("outputAnchors") or []  # Legacy field

    if raw_outputs:
        output_anchors = []
        for out in raw_outputs:
            out_name = out.get("name") or node_name
            out_bcs = out.get("baseClasses") or base_classes
            out_type = "|".join(out_bcs)
            output_anchors.append(
                {
                    "id": f"{{nodeId}}-output-{out_name}-{out_type}",
                    "name": out_name,
                    "label": out.get("label", out_name),
                    "type": " | ".join(out_bcs),
                }
            )
    elif raw_oa:
        output_anchors = []
        for oa in raw_oa:
            entry = dict(oa)
            oa_id = entry.get("id", "")
            if oa_id and "{nodeId}" not in oa_id:
                oa_type = entry.get("type", "")
                oa_name = entry.get("name", node_name)
                entry["id"] = f"{{nodeId}}-output-{oa_name}-{oa_type}"
            output_anchors.append(entry)
    else:
        output_anchors = [
            {
                "id": f"{{nodeId}}-output-{node_name}-{'|'.join(base_classes)}",
                "name": node_name,
                "label": raw.get("label", node_name),
                "type": " | ".join(base_classes),
            }
        ]

    return {
        **raw,
        # Canonical index key — always present, matches the node_type field in the snapshot
        "node_type": node_name,
        "inputAnchors": input_anchors,
        "inputParams": input_params,
        "outputAnchors": output_anchors,
        "outputs": {},
        "_flowdata_note": (
            "Replace {nodeId} in all 'id' fields with your actual node ID "
            "(e.g. 'chatOpenAI_0'). Embed inputAnchors, inputParams, outputAnchors, "
            "and outputs verbatim in each flowData node's data object."
        ),
    }


# ---------------------------------------------------------------------------
# NodeSchemaStore
# ---------------------------------------------------------------------------


class NodeSchemaStore:
    """Local-first node schema lookup backed by schemas/flowise_nodes.snapshot.json.

    Lifecycle:
      - Snapshot is loaded lazily on first get() call.
      - Fingerprint is validated at load time; a mismatch triggers a warning but
        does not block — the on-disk bytes are used as-is.
      - Repair: when a node_type is absent, get_or_repair() calls the provided
        api_fetcher coroutine for ONLY that node type, normalises the result, and
        patches the in-memory index + persists to disk.
      - Thread safety: reads are safe (Python GIL).  Repair writes are idempotent
        and occur rarely; no lock is used in this milestone.

    The store is intentionally NOT a DomainCapability and has NO async event loop,
    no background task, and no network I/O except in get_or_repair().
    """

    def __init__(
        self,
        snapshot_path: Path = _NODES_SNAPSHOT,
        meta_path: Path = _NODES_META,
    ) -> None:
        self._snapshot_path = snapshot_path
        self._meta_path = meta_path
        # node_type → processed schema dict (camelCase keys, matching schema_cache format)
        self._index: dict[str, dict] = {}
        # M10.7: lowered node_type → canonical node_type (case-insensitive fallback)
        self._lower_index: dict[str, str] = {}
        self._repair_events: list[dict[str, Any]] = []
        self._loaded = False
        # M8.2: total get_or_repair calls this session (cache hits + misses)
        self._call_count: int = 0

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load snapshot into memory index. Idempotent; called lazily."""
        if self._loaded:
            return
        self._loaded = True

        if not self._snapshot_path.exists():
            logger.info(
                "[NodeSchemaStore] Snapshot not found at %s — "
                "run: python -m flowise_dev_agent.knowledge.refresh --nodes",
                self._snapshot_path,
            )
            return

        try:
            raw_bytes = self._snapshot_path.read_bytes()

            # Fingerprint check (warn only — do not block)
            if self._meta_path.exists():
                meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
                stored = meta.get("fingerprint") or meta.get("sha256")
                if stored:
                    actual = hashlib.sha256(raw_bytes).hexdigest()
                    if actual != stored:
                        logger.warning(
                            "[NodeSchemaStore] Fingerprint mismatch — snapshot may be "
                            "externally modified. Proceeding with on-disk content."
                        )

            nodes: list[dict] = json.loads(raw_bytes.decode("utf-8"))
            for node in nodes:
                key = node.get("node_type") or node.get("name")
                if key:
                    self._index[key] = node
                    self._lower_index[key.lower()] = key

            logger.info(
                "[NodeSchemaStore] Loaded %d node schemas from snapshot (no API calls needed)",
                len(self._index),
            )
        except Exception:
            logger.exception("[NodeSchemaStore] Failed to load snapshot")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def meta_fingerprint(self) -> str | None:
        """Return the fingerprint stored in the snapshot meta file, or None.

        Used by M7.3 to record which schema version was active when a pattern
        was saved.  Returns None when the meta file is absent or malformed.
        See DD-068.
        """
        if not self._meta_path.exists():
            return None
        try:
            meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
            return meta.get("fingerprint") or meta.get("sha256") or None
        except Exception:
            return None

    def get(self, node_type: str) -> dict | None:
        """Return the processed schema for node_type from snapshot, or None.

        Uses exact match first, then case-insensitive fallback (M10.7 — DD-103).
        This is the fast, synchronous, no-network path. If None is returned,
        callers SHOULD use get_or_repair() to trigger a targeted API fetch.
        """
        self._load()
        schema = self._index.get(node_type)
        if schema is not None:
            logger.debug("[NodeSchemaStore] Cache HIT: %s — no API call", node_type)
            return schema
        # M10.7: case-insensitive fallback
        canonical = self._lower_index.get(node_type.lower())
        if canonical is not None:
            logger.info(
                "[NodeSchemaStore] Case-insensitive match: '%s' → '%s'",
                node_type, canonical,
            )
            return self._index.get(canonical)
        return None

    async def get_or_repair(
        self,
        node_type: str,
        api_fetcher,
        repair_events_out: list[dict] | None = None,
    ) -> dict | None:
        """Return schema from snapshot, or fetch from API if missing (repair-only).

        Parameters
        ----------
        node_type:
            Flowise node type name (e.g. "chatOpenAI").
        api_fetcher:
            Async callable: (node_type: str) -> dict | None.
            Called ONLY when node_type is absent from the snapshot.
            Should be the existing tool executor for "get_node".
        repair_events_out:
            Optional list to append repair event dicts into. These are written
            to debug["flowise"]["knowledge_repair_events"] by the caller.

        Returns
        -------
        The processed schema dict (camelCase keys, matching schema_cache format),
        or None if both local lookup and API repair fail.
        """
        self._load()
        self._call_count += 1  # M8.2: count every call (hits + misses)

        # --- Fast path: local snapshot hit (exact, then case-insensitive) ---
        local = self._index.get(node_type)
        if local is None:
            canonical = self._lower_index.get(node_type.lower())
            if canonical is not None:
                local = self._index.get(canonical)
                logger.info(
                    "[NodeSchemaStore] Case-insensitive match: '%s' → '%s'",
                    node_type, canonical,
                )
        if local is not None:
            logger.debug(
                "[NodeSchemaStore] Cache HIT: %s — skipping API get_node call", node_type
            )
            return local

        # --- Slow path: API repair ---
        logger.info(
            "[NodeSchemaStore] REPAIR triggered: '%s' not in snapshot — "
            "calling API get_node (ONE targeted call only)",
            node_type,
        )

        try:
            api_raw = await api_fetcher(node_type)
        except Exception as exc:
            logger.warning(
                "[NodeSchemaStore] REPAIR fetch failed for '%s': %s", node_type, exc
            )
            self._record_event(node_type, "fetch_error", {}, repair_events_out)
            return None

        if not api_raw or not isinstance(api_raw, dict) or "error" in api_raw:
            logger.warning(
                "[NodeSchemaStore] REPAIR: API returned no usable schema for '%s'", node_type
            )
            self._record_event(node_type, "api_no_schema", {}, repair_events_out)
            return None

        # --- Version/hash gating (M9.5) ---
        # _compute_action_detail returns both the decision string and a full
        # gating context dict that is written into the repair event for
        # observability (comparison_method, decision_reason, local/api hashes).
        action, gating_detail = self._compute_action_detail(node_type, api_raw)
        self._record_event(node_type, action, gating_detail, repair_events_out)

        if action == "skip_same_version":
            logger.info(
                "[NodeSchemaStore] REPAIR: version unchanged for '%s' — keeping local copy",
                node_type,
            )
            return self._index.get(node_type)

        # Normalise to snapshot format and update in-memory index + disk
        normalized = _normalize_api_schema(api_raw)
        self._index[node_type] = normalized
        self._persist()
        logger.info(
            "[NodeSchemaStore] REPAIR applied: action=%s for '%s' — snapshot updated",
            action,
            node_type,
        )
        return normalized

    # ------------------------------------------------------------------
    # Repair event helpers
    # ------------------------------------------------------------------

    def _record_event(
        self,
        node_type: str,
        action: str,
        extra: dict,
        out: list | None,
    ) -> None:
        event: dict[str, Any] = {
            "node_type": node_type,
            "timestamp": time.time(),
            "action": action,
            **extra,
        }
        self._repair_events.append(event)
        if out is not None:
            out.append(event)

    def _compute_action_detail(
        self, node_type: str, api_raw: dict
    ) -> "tuple[str, dict[str, Any]]":
        """Determine whether to overwrite the local schema and explain why.

        M9.5: Single source of truth for repair gating.  Returns both the
        action string and a detail dict that is injected into the repair event
        for full observability.

        Decision tree
        -------------
        1. Node not in local index          → update_new_node
        2. Both sides have a version string:
             versions equal                 → skip_same_version
             versions differ                → update_changed_version_or_hash
        3. Fall through to hash comparison:
             hashes equal                   → skip_same_version
             hashes differ, no versions     → update_no_version_info
             hashes differ, partial version → update_changed_version_or_hash

        Returns
        -------
        (action, detail_dict)

        action is one of:
          "update_new_node"
          "skip_same_version"
          "update_changed_version_or_hash"
          "update_no_version_info"

        detail_dict keys (always present):
          comparison_method : "new_node" | "version" | "hash"
          decision_reason   : human-readable explanation
          local_version     : str | None
          api_version       : str | None

        Additional keys present only for "hash" method:
          local_hash  : first 16 hex chars of local content hash
          api_hash    : first 16 hex chars of normalised API content hash
        """
        existing = self._index.get(node_type)
        if existing is None:
            return "update_new_node", {
                "comparison_method": "new_node",
                "decision_reason": "node not present in local snapshot — adding fresh",
                "local_version": None,
                "api_version": None,
            }

        local_ver = str(existing.get("version") or "").strip()
        api_ver   = str(api_raw.get("version")  or "").strip()

        if local_ver and api_ver:
            # Version strings available on both sides — compare directly
            if local_ver == api_ver:
                return "skip_same_version", {
                    "comparison_method": "version",
                    "decision_reason": f"versions match ({local_ver!r}) — keeping local copy",
                    "local_version": local_ver,
                    "api_version": api_ver,
                }
            return "update_changed_version_or_hash", {
                "comparison_method": "version",
                "decision_reason": f"version changed {local_ver!r} → {api_ver!r}",
                "local_version": local_ver,
                "api_version": api_ver,
            }

        # No complete version pair — fall back to content hash comparison
        local_hash_full = hashlib.sha256(
            json.dumps(existing, sort_keys=True, default=str).encode()
        ).hexdigest()
        normalized   = _normalize_api_schema(api_raw)
        api_hash_full = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, default=str).encode()
        ).hexdigest()

        base_detail: dict[str, Any] = {
            "comparison_method": "hash",
            "local_version": local_ver or None,
            "api_version":   api_ver  or None,
            "local_hash": local_hash_full[:16],
            "api_hash":   api_hash_full[:16],
        }

        if local_hash_full == api_hash_full:
            return "skip_same_version", {
                **base_detail,
                "decision_reason": "hash match — content unchanged",
            }
        if not local_ver and not api_ver:
            return "update_no_version_info", {
                **base_detail,
                "decision_reason": "hash differs, no version on either side — conservative update",
            }
        return "update_changed_version_or_hash", {
            **base_detail,
            "decision_reason": (
                f"hash differs, partial version info "
                f"(local={local_ver!r}, api={api_ver!r})"
            ),
        }

    def _compute_action(self, node_type: str, api_raw: dict) -> str:
        """Return the action string for the given node_type / api_raw pair.

        Thin wrapper around _compute_action_detail for backwards compatibility.
        Callers that need the full gating context should use _compute_action_detail
        directly.

        Returns one of:
          "update_new_node"
          "skip_same_version"
          "update_changed_version_or_hash"
          "update_no_version_info"
        """
        action, _ = self._compute_action_detail(node_type, api_raw)
        return action

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        """Write current index to snapshot.json and recompute meta fingerprint."""
        try:
            self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            nodes = list(self._index.values())
            content = json.dumps(nodes, indent=2, ensure_ascii=False)
            content_bytes = content.encode("utf-8")
            self._snapshot_path.write_bytes(content_bytes)

            digest = hashlib.sha256(content_bytes).hexdigest()

            # Preserve any extra fields already in meta (e.g. source, flowise_version)
            existing_meta: dict = {}
            if self._meta_path.exists():
                try:
                    existing_meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            meta = {
                **existing_meta,
                "snapshot_file": str(self._snapshot_path.relative_to(_REPO_ROOT)),
                "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                "source": existing_meta.get("source", "repair"),
                "node_count": len(nodes),
                "fingerprint": digest,
                "status": "ok",
            }
            self._meta_path.write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            logger.exception("[NodeSchemaStore] Failed to persist snapshot after repair")

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def repair_events(self) -> list[dict]:
        """All repair events recorded this session (for debug state)."""
        return list(self._repair_events)

    @property
    def node_count(self) -> int:
        self._load()
        return len(self._index)


# ---------------------------------------------------------------------------
# TemplateStore
# ---------------------------------------------------------------------------


class TemplateStore:
    """Local-first marketplace template metadata store.

    Milestone 2: stores a metadata-only snapshot (no flowData).
    Stale detection via TTL (TEMPLATE_SNAPSHOT_TTL_SECONDS env var, default 86400 s).

    Public interface:
      - find(tags, limit=3) → list of slim {templateName, description, categories, usecases}
      - is_stale(ttl_seconds=None) → bool
      - template_count → int

    This store has NO network I/O.  To refresh the snapshot run:
        python -m flowise_dev_agent.knowledge.refresh --templates

    Prompt-hygiene guardrail: find() returns at most `limit` (default 3) entries,
    each with description capped at 200 chars.  The full catalog is NEVER injected
    into an LLM prompt.
    """

    def __init__(
        self,
        snapshot_path: Path = _TEMPLATES_SNAPSHOT,
        meta_path: Path = _TEMPLATES_META,
    ) -> None:
        self._snapshot_path = snapshot_path
        self._meta_path = meta_path
        self._index: list[dict] = []
        self._generated_at: float | None = None
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load snapshot into memory. Idempotent; called lazily."""
        if self._loaded:
            return
        self._loaded = True

        if not self._snapshot_path.exists():
            logger.info(
                "[TemplateStore] Snapshot not found at %s — "
                "run: python -m flowise_dev_agent.knowledge.refresh --templates",
                self._snapshot_path,
            )
            return

        try:
            raw = json.loads(self._snapshot_path.read_bytes().decode("utf-8"))
            if isinstance(raw, list):
                self._index = [
                    t for t in raw if isinstance(t, dict) and t.get("templateName")
                ]

            # Read generated_at from meta for TTL checks.
            if self._meta_path.exists():
                try:
                    meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
                    ga = meta.get("generated_at")
                    if ga:
                        dt = datetime.datetime.fromisoformat(ga.replace("Z", "+00:00"))
                        self._generated_at = dt.timestamp()
                except Exception:
                    pass

            logger.info(
                "[TemplateStore] Loaded %d templates from snapshot",
                len(self._index),
            )
        except Exception:
            logger.exception("[TemplateStore] Failed to load snapshot")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_stale(self, ttl_seconds: int | None = None) -> bool:
        """Return True if the snapshot is older than ttl_seconds.

        If no generated_at is recorded (empty or missing meta), returns True.
        Override TTL via TEMPLATE_SNAPSHOT_TTL_SECONDS env var.
        """
        self._load()
        if ttl_seconds is None:
            ttl_seconds = int(
                os.environ.get("TEMPLATE_SNAPSHOT_TTL_SECONDS", str(_DEFAULT_TEMPLATE_TTL))
            )
        if self._generated_at is None:
            return True
        return (time.time() - self._generated_at) > ttl_seconds

    def find(self, tags: list[str], limit: int = 3) -> list[dict]:
        """Return up to `limit` templates whose metadata matches any of the given tags.

        Tags are matched (case-insensitive substring) against:
            templateName, categories, usecases, description.

        Templates are ranked by descending match score (number of tag hits).
        Returns slim dicts: templateName, description (≤200 chars), categories, usecases.
        Serves results even when stale (logs a debug warning).
        """
        self._load()
        if not self._index:
            return []

        norm_tags = [t.lower().strip() for t in tags if t.strip() and len(t.strip()) >= 3]
        if not norm_tags:
            return []

        if self.is_stale():
            logger.debug(
                "[TemplateStore] Snapshot is stale — serving cached results. "
                "Run: python -m flowise_dev_agent.knowledge.refresh --templates"
            )

        scored: list[tuple[int, dict]] = []
        for t in self._index:
            name = (t.get("templateName") or "").lower()
            desc = (t.get("description") or "").lower()
            cats = t.get("categories") or []
            uses = t.get("usecases") or []
            cats_str = (" ".join(cats) if isinstance(cats, list) else str(cats)).lower()
            uses_str = (" ".join(uses) if isinstance(uses, list) else str(uses)).lower()
            corpus = f"{name} {desc} {cats_str} {uses_str}"
            score = sum(1 for tag in norm_tags if tag in corpus)
            if score > 0:
                scored.append((score, t))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for _, t in scored[:limit]:
            results.append({
                "templateName": t.get("templateName"),
                "description": (t.get("description") or "")[:200],
                "categories": t.get("categories"),
                "usecases": t.get("usecases"),
            })
        return results

    @property
    def template_count(self) -> int:
        self._load()
        return len(self._index)


# ---------------------------------------------------------------------------
# CredentialStore helpers
# ---------------------------------------------------------------------------


def _normalize_credential(raw: dict) -> dict:
    """Normalise a raw Flowise API credential response to the allowlisted snapshot format.

    Handles two shapes:
      - Live API response: uses ``id``, ``credentialName``, ``createdDate``, ``updatedDate``.
      - Already-normalised snapshot entry: uses the allowlist keys directly.

    Only the six allowlisted keys are returned — all others are silently dropped.
    """
    cred_id = raw.get("credential_id") or raw.get("id") or ""
    name = raw.get("name") or ""
    cred_type = raw.get("type") or raw.get("credentialName") or ""
    tags = raw.get("tags") or []
    created_at = raw.get("created_at") or raw.get("createdDate") or ""
    updated_at = raw.get("updated_at") or raw.get("updatedDate") or ""
    return {
        "credential_id": str(cred_id),
        "name": str(name),
        "type": str(cred_type),
        "tags": tags if isinstance(tags, list) else [],
        "created_at": str(created_at),
        "updated_at": str(updated_at),
    }


def _validate_allowlist(entry: dict, index: int = -1) -> list[str]:
    """Return violation messages for any key in *entry* not in ``_CRED_ALLOWLIST``.

    Called at snapshot load time.  Violations are errors — the refresh job MUST
    strip banned keys before writing.
    """
    extra = set(entry.keys()) - _CRED_ALLOWLIST
    if not extra:
        return []
    label = entry.get("name") or entry.get("credential_id") or f"entry[{index}]"
    return [f"Credential '{label}' contains non-allowlisted keys: {sorted(extra)}"]


# ---------------------------------------------------------------------------
# CredentialStore
# ---------------------------------------------------------------------------


class CredentialStore:
    """Local-first credential metadata store.

    Milestone 3: stores allowlisted metadata only — no secrets, no encrypted data.

    Security contract
    -----------------
    Allowlist: ``credential_id``, ``name``, ``type``, ``tags``, ``created_at``,
    ``updated_at``.  Any other key in the snapshot file triggers an error at load
    time and is stripped defensively.  The refresh job enforces the same rule
    before writing.

    This snapshot MUST NOT be committed to git (see .gitignore).

    TTL
    ---
    ``CREDENTIAL_SNAPSHOT_TTL_SECONDS`` env var (default 3600 s = 1 h).
    A stale snapshot still serves cached results; callers use ``is_stale()``
    to decide whether to trigger a refresh.

    Public interface
    ----------------
    ``resolve(name_or_type_or_id)``          → str | None  (sync, no I/O)
    ``resolve_or_repair(q, api_fetcher)``    → str | None  (async, repair fallback)
    ``is_stale(ttl_seconds=None)``           → bool
    ``all_by_type(credential_type)``         → list[dict]
    ``credential_count``                     → int
    """

    def __init__(
        self,
        snapshot_path: Path = _CRED_SNAPSHOT,
        meta_path: Path = _CRED_META,
    ) -> None:
        self._snapshot_path = snapshot_path
        self._meta_path = meta_path
        # Indices built at load time
        self._by_id: dict[str, dict] = {}           # credential_id → entry
        self._by_name: dict[str, dict] = {}         # lowercase name → entry
        self._by_type: dict[str, list[dict]] = {}   # lowercase type → [entries]
        self._generated_at: float | None = None
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load snapshot into memory indices. Idempotent; called lazily."""
        if self._loaded:
            return
        self._loaded = True

        if not self._snapshot_path.exists():
            logger.info(
                "[CredentialStore] Snapshot not found at %s — "
                "run: python -m flowise_dev_agent.knowledge.refresh --credentials",
                self._snapshot_path,
            )
            return

        try:
            raw_bytes = self._snapshot_path.read_bytes()
            entries = json.loads(raw_bytes.decode("utf-8"))
            if not isinstance(entries, list):
                logger.warning("[CredentialStore] Snapshot is not a list — skipping")
                return

            violations: list[str] = []
            for i, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                v = _validate_allowlist(entry, i)
                if v:
                    violations.extend(v)
                    # Strip defensively — do not expose secrets even if present
                    entry = {k: val for k, val in entry.items() if k in _CRED_ALLOWLIST}
                self._index_entry(entry)

            if violations:
                logger.error(
                    "[CredentialStore] ALLOWLIST VIOLATION(S) in snapshot — "
                    "%d entry/entries contain banned keys. "
                    "Refresh to fix: python -m flowise_dev_agent.knowledge.refresh --credentials\n%s",
                    len(violations),
                    "\n".join(violations[:5]),
                )

            # Read generated_at from meta for TTL checks
            if self._meta_path.exists():
                try:
                    meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
                    ga = meta.get("generated_at")
                    if ga:
                        dt = datetime.datetime.fromisoformat(ga.replace("Z", "+00:00"))
                        self._generated_at = dt.timestamp()
                except Exception:
                    pass

            count = len(self._by_id)
            logger.info(
                "[CredentialStore] Loaded %d credential(s) from snapshot",
                count,
            )
        except Exception:
            logger.exception("[CredentialStore] Failed to load snapshot")

    def _index_entry(self, entry: dict) -> None:
        cid = entry.get("credential_id") or ""
        name = entry.get("name") or ""
        ctype = entry.get("type") or ""
        if cid:
            self._by_id[cid] = entry
        if name:
            self._by_name[name.lower()] = entry
        if ctype:
            self._by_type.setdefault(ctype.lower(), []).append(entry)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_stale(self, ttl_seconds: int | None = None) -> bool:
        """Return True if the snapshot is older than *ttl_seconds*.

        If no ``generated_at`` is recorded, returns True (treat as stale).
        """
        self._load()
        if ttl_seconds is None:
            ttl_seconds = int(
                os.environ.get(
                    "CREDENTIAL_SNAPSHOT_TTL_SECONDS", str(_DEFAULT_CREDENTIAL_TTL)
                )
            )
        if self._generated_at is None:
            return True
        return (time.time() - self._generated_at) > ttl_seconds

    def resolve(self, name_or_type_or_id: str) -> str | None:
        """Return the ``credential_id`` for a name, type, or UUID. Synchronous, no I/O.

        Lookup order
        ------------
        1. By ``credential_id`` (UUID match).
        2. By exact ``name`` (case-insensitive).
        3. By ``type`` — returns the first match (use ``all_by_type`` to get all).

        Returns ``None`` if not found in the local snapshot.
        """
        self._load()
        if not name_or_type_or_id:
            return None
        query = name_or_type_or_id.strip()

        # 1. By id (UUID pattern)
        if _UUID_RE.match(query):
            entry = self._by_id.get(query)
            if entry:
                logger.debug("[CredentialStore] HIT by id: %s…", query[:8])
                return entry["credential_id"]

        # 2. By name
        entry = self._by_name.get(query.lower())
        if entry:
            logger.debug("[CredentialStore] HIT by name: %r", query)
            return entry["credential_id"]

        # 3. By type
        matches = self._by_type.get(query.lower())
        if matches:
            logger.debug(
                "[CredentialStore] HIT by type: %r → %d match(es)", query, len(matches)
            )
            return matches[0]["credential_id"]

        return None

    async def resolve_or_repair(
        self,
        name_or_type_or_id: str,
        api_fetcher,
        repair_events_out: list[dict] | None = None,
    ) -> str | None:
        """Resolve ``credential_id``, falling back to a full ``list_credentials`` fetch.

        Parameters
        ----------
        name_or_type_or_id:
            Credential name, type, or UUID.
        api_fetcher:
            Async callable: ``() -> list[dict]`` — returns the raw Flowise credential list.
            Called ONLY when the credential is not found locally.
        repair_events_out:
            Optional list to record repair event dicts into.

        Returns
        -------
        ``credential_id`` string, or ``None`` if not found even after repair.
        """
        self._load()

        # Fast path
        local = self.resolve(name_or_type_or_id)
        if local is not None:
            return local

        # Slow path: repair via full credential list fetch
        logger.info(
            "[CredentialStore] REPAIR triggered: '%s' not in snapshot — "
            "calling API list_credentials (one call only)",
            name_or_type_or_id,
        )

        try:
            raw_list = await api_fetcher()
        except Exception as exc:
            logger.warning("[CredentialStore] REPAIR fetch failed: %s", exc)
            self._record_event(
                name_or_type_or_id, "fetch_error", {}, repair_events_out
            )
            return None

        if not isinstance(raw_list, list):
            logger.warning(
                "[CredentialStore] REPAIR: unexpected API response type: %s",
                type(raw_list).__name__,
            )
            self._record_event(
                name_or_type_or_id, "api_unexpected_type", {}, repair_events_out
            )
            return None

        # Normalise + strip to allowlist, then update indices + persist
        fresh = [
            _normalize_credential(r)
            for r in raw_list
            if isinstance(r, dict) and (r.get("id") or r.get("credential_id"))
        ]
        for entry in fresh:
            cid = entry.get("credential_id") or ""
            if cid and cid not in self._by_id:
                self._index_entry(entry)

        all_entries = list(self._by_id.values())
        self._persist(all_entries)

        self._record_event(
            name_or_type_or_id,
            "credential_repair",
            {"fetched_count": len(fresh)},
            repair_events_out,
        )

        # Retry after repair
        result = self.resolve(name_or_type_or_id)
        if result:
            logger.info(
                "[CredentialStore] REPAIR resolved '%s' successfully", name_or_type_or_id
            )
        else:
            logger.warning(
                "[CredentialStore] REPAIR: '%s' not found even after API fetch — "
                "check that the credential type/name matches exactly",
                name_or_type_or_id,
            )
        return result

    def all_by_type(self, credential_type: str) -> list[dict]:
        """Return all credentials of the given *credential_type* (slim dicts, no secrets)."""
        self._load()
        return list(self._by_type.get(credential_type.lower(), []))

    @property
    def credential_count(self) -> int:
        self._load()
        return len(self._by_id)

    @property
    def available_types(self) -> list[str]:
        """Return sorted list of credential type strings present in the snapshot (original case)."""
        self._load()
        # _by_type keys are lowercased; recover original case from entry dicts
        seen: dict[str, str] = {}
        for entries in self._by_type.values():
            for entry in entries:
                orig = entry.get("type", "")
                if orig and orig.lower() not in seen:
                    seen[orig.lower()] = orig
        return sorted(seen.values())

    @property
    def available_credentials_summary(self) -> list[dict[str, str | int]]:
        """Return a summary of available credentials grouped by type.

        Each entry: ``{"type": "openAIApi", "count": 2, "names": "key-prod, key-dev"}``.
        When count == 1, ``names`` is the single credential name.
        """
        self._load()
        result: list[dict[str, str | int]] = []
        # Iterate in sorted order of original-case type
        type_map: dict[str, tuple[str, list[str]]] = {}
        for entries in self._by_type.values():
            for entry in entries:
                orig_type = entry.get("type", "")
                name = entry.get("name", "")
                key = orig_type.lower()
                if key not in type_map:
                    type_map[key] = (orig_type, [])
                if name:
                    type_map[key][1].append(name)
        for _key in sorted(type_map):
            orig_type, names = type_map[_key]
            result.append({
                "type": orig_type,
                "count": len(names) or 1,
                "names": ", ".join(sorted(names)) if names else "",
            })
        return result

    # ------------------------------------------------------------------
    # Repair event helpers
    # ------------------------------------------------------------------

    def _record_event(
        self,
        query: str,
        action: str,
        extra: dict,
        out: list | None,
    ) -> None:
        event: dict[str, Any] = {
            "query": query,
            "timestamp": time.time(),
            "action": action,
            **extra,
        }
        if out is not None:
            out.append(event)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, entries: list[dict]) -> None:
        """Write *entries* to snapshot + recompute meta fingerprint.

        Final safety pass: strips any non-allowlisted key before writing,
        even if the in-memory entries were already clean.
        """
        clean = [
            {k: v for k, v in e.items() if k in _CRED_ALLOWLIST}
            for e in entries
        ]
        try:
            self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(clean, indent=2, ensure_ascii=False)
            content_bytes = content.encode("utf-8")
            self._snapshot_path.write_bytes(content_bytes)

            digest = hashlib.sha256(content_bytes).hexdigest()

            existing_meta: dict = {}
            if self._meta_path.exists():
                try:
                    existing_meta = json.loads(
                        self._meta_path.read_text(encoding="utf-8")
                    )
                except Exception:
                    pass

            meta = {
                **existing_meta,
                "snapshot_file": str(
                    self._snapshot_path.relative_to(_REPO_ROOT)
                ),
                "generated_at": (
                    datetime.datetime.now(datetime.timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                ),
                "source": existing_meta.get("source", "repair"),
                "credential_count": len(clean),
                "fingerprint": digest,
                "status": "ok",
            }
            self._meta_path.write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            # Update in-memory generated_at
            self._generated_at = time.time()
        except Exception:
            logger.exception(
                "[CredentialStore] Failed to persist snapshot after repair"
            )


# ---------------------------------------------------------------------------
# FlowiseKnowledgeProvider
# ---------------------------------------------------------------------------


class FlowiseKnowledgeProvider:
    """Single provider for all Flowise local-first platform knowledge.

    Milestones 1–3:
      - NodeSchemaStore  (M1) — node type schemas, O(1) lookup + repair fallback
      - TemplateStore    (M2) — marketplace template metadata, TTL-based staleness
      - CredentialStore  (M3) — credential metadata only (allowlisted), TTL 1 h

    This class is NOT a DomainCapability. It is a read-only data provider
    instantiated once inside FlowiseCapability.__init__ and held for the
    lifetime of the graph.

    Guardrails:
      - No async event loop or background thread.
      - No network I/O except inside get_or_repair() / resolve_or_repair().
      - Snapshot data MUST NOT be injected wholesale into LLM prompts.
    """

    def __init__(self, schemas_dir: Path | None = None) -> None:
        base = schemas_dir or _SCHEMAS_DIR
        self._node_schemas = NodeSchemaStore(
            base / "flowise_nodes.snapshot.json",
            base / "flowise_nodes.meta.json",
        )
        self._template_store = TemplateStore(
            base / "flowise_templates.snapshot.json",
            base / "flowise_templates.meta.json",
        )
        self._credential_store = CredentialStore(
            base / "flowise_credentials.snapshot.json",
            base / "flowise_credentials.meta.json",
        )
        self._anchor_store: AnchorDictionaryStore | None = None  # lazy M10.2a

    @property
    def node_schemas(self) -> NodeSchemaStore:
        """The node schema sub-store."""
        return self._node_schemas

    @property
    def template_store(self) -> TemplateStore:
        """The marketplace template metadata sub-store (Milestone 2)."""
        return self._template_store

    @property
    def credential_store(self) -> CredentialStore:
        """The credential metadata sub-store (Milestone 3, allowlisted — no secrets)."""
        return self._credential_store

    @property
    def anchor_dictionary(self) -> "AnchorDictionaryStore":
        """Canonical anchor dictionary derived from NodeSchemaStore (M10.2a, DD-093).

        Lazy: created on first access and reused for session lifetime.
        """
        if self._anchor_store is None:
            from flowise_dev_agent.knowledge.anchor_store import AnchorDictionaryStore

            self._anchor_store = AnchorDictionaryStore(self._node_schemas)
        return self._anchor_store
