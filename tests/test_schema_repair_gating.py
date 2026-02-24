"""Unit tests for NodeSchemaStore._compute_action repair gating (M8.1C).

_compute_action(node_type, api_raw) decides whether the local snapshot should be
updated when a live API response is available.  The logic is:

  1. Node not in local index           -> update_new_node
  2. Both sides have a version string:
     - versions match                  -> skip_same_version
     - versions differ                 -> update_changed_version_or_hash
  3. No version on either side (fall through to hash comparison):
     - hashes match                    -> skip_same_version
     - hashes differ, no version info  -> update_no_version_info
  4. One side has version, other does not:
     - hashes match                    -> skip_same_version
     - hashes differ                   -> update_changed_version_or_hash

These tests exercise the four cases documented in the Roadmap 8 plan (M8.1C).
"""

from __future__ import annotations

import json

import pytest

from flowise_dev_agent.knowledge.provider import NodeSchemaStore, _normalize_api_schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(index: dict[str, dict]) -> NodeSchemaStore:
    """Build a NodeSchemaStore with a pre-populated _index (no disk I/O)."""
    store = NodeSchemaStore.__new__(NodeSchemaStore)
    store._index = index
    store._meta = {}
    return store


def _minimal_schema(name: str, version: str = "", extra: str = "") -> dict:
    """Return a minimal normalized schema dict for testing."""
    s: dict = {
        "name": name,
        "label": name,
        "type": name,
        "baseClasses": [name],
        "inputAnchors": [],
        "inputParams": [],
        "outputAnchors": [],
    }
    if version:
        s["version"] = version
    if extra:
        s["_extra"] = extra
    return s


# ---------------------------------------------------------------------------
# Case 1: Same version — skip
# ---------------------------------------------------------------------------


def test_same_version_skips(tmp_path):
    """When local and API version strings match, no update is needed."""
    local = _minimal_schema("chatOpenAI", version="2")
    store = _make_store({"chatOpenAI": local})

    api_raw = {"name": "chatOpenAI", "version": "2", "baseClasses": ["chatOpenAI"]}
    action = store._compute_action("chatOpenAI", api_raw)

    assert action == "skip_same_version"


# ---------------------------------------------------------------------------
# Case 2: Different version — update
# ---------------------------------------------------------------------------


def test_different_version_updates():
    """When local version is older than the API version, force an update."""
    local = _minimal_schema("chatOpenAI", version="1")
    store = _make_store({"chatOpenAI": local})

    api_raw = {"name": "chatOpenAI", "version": "2", "baseClasses": ["chatOpenAI"]}
    action = store._compute_action("chatOpenAI", api_raw)

    assert action == "update_changed_version_or_hash"


# ---------------------------------------------------------------------------
# Case 3: No version on either side, same content (hash match) — skip
# ---------------------------------------------------------------------------


def test_no_version_same_hash_skips():
    """When neither side has a version but the normalized content is identical,
    the hash comparison detects no change and skips the update."""
    api_raw = {
        "name": "customNode",
        "label": "customNode",
        "type": "customNode",
        "baseClasses": ["customNode"],
        "inputAnchors": [],
        "inputParams": [],
        "outputAnchors": [],
    }
    # Store the already-normalized form so local_hash == api_hash
    local = _normalize_api_schema(api_raw)
    store = _make_store({"customNode": local})

    action = store._compute_action("customNode", api_raw)

    assert action == "skip_same_version"


# ---------------------------------------------------------------------------
# Case 4: No version on either side, different content (hash mismatch) — update
# ---------------------------------------------------------------------------


def test_no_version_different_hash_updates():
    """When neither side has a version and the normalized content differs,
    the hash mismatch triggers a conservative update."""
    local = _minimal_schema("customNode")
    store = _make_store({"customNode": local})

    # api_raw with an extra field that changes the hash after normalization
    api_raw = {
        "name": "customNode",
        "label": "customNode",
        "type": "customNode",
        "baseClasses": ["customNode"],
        "inputAnchors": [],
        "inputParams": [{"name": "newParam", "type": "string", "label": "New Param"}],
        "outputAnchors": [],
    }
    action = store._compute_action("customNode", api_raw)

    assert action == "update_no_version_info"


# ---------------------------------------------------------------------------
# Bonus case: Node not in local index — always update
# ---------------------------------------------------------------------------


def test_new_node_always_updates():
    """A node type not present in the local snapshot is always added."""
    store = _make_store({})  # empty index

    api_raw = {"name": "brandNewNode", "version": "1", "baseClasses": ["brandNewNode"]}
    action = store._compute_action("brandNewNode", api_raw)

    assert action == "update_new_node"
