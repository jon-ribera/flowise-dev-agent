"""M9.5 — NodeSchemaStore repair gating correctness tests.

Verifies _compute_action_detail() decision logic and the enriched repair event
recorded by get_or_repair().

Decision tree under test
------------------------
1. Node not in local index          → update_new_node
2. Both sides have a version string:
     versions equal                 → skip_same_version
     versions differ                → update_changed_version_or_hash
3. No complete version pair, hash comparison:
     hashes equal                   → skip_same_version
     hashes differ, no versions     → update_no_version_info
     hashes differ, partial version → update_changed_version_or_hash

See roadmap9_production_graph_runtime_hardening.md — Milestone 9.5.
"""

from __future__ import annotations

import json

import pytest

from flowise_dev_agent.knowledge.provider import NodeSchemaStore, _normalize_api_schema


# ---------------------------------------------------------------------------
# Helpers — build a lightweight in-memory NodeSchemaStore
# ---------------------------------------------------------------------------


def _make_store(index: dict[str, dict]) -> NodeSchemaStore:
    """Return a NodeSchemaStore with a pre-populated _index (no disk I/O)."""
    store = NodeSchemaStore.__new__(NodeSchemaStore)
    store._index = dict(index)
    store._meta = {}
    return store


def _minimal_schema(name: str, version: str = "", extra: str = "") -> dict:
    """Minimal normalised schema dict."""
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
# A) Action correctness (spec-required cases)
# ---------------------------------------------------------------------------


class TestActionCorrectness:
    """The four spec-required gating cases plus the new-node case."""

    def test_same_version_skips(self):
        """Same version on both sides → skip_same_version."""
        local = _minimal_schema("chatOpenAI", version="2")
        store = _make_store({"chatOpenAI": local})
        api_raw = {"name": "chatOpenAI", "version": "2", "baseClasses": ["chatOpenAI"]}

        action, _ = store._compute_action_detail("chatOpenAI", api_raw)
        assert action == "skip_same_version"

    def test_different_version_updates(self):
        """Different version on both sides → update_changed_version_or_hash."""
        local = _minimal_schema("chatOpenAI", version="1")
        store = _make_store({"chatOpenAI": local})
        api_raw = {"name": "chatOpenAI", "version": "2", "baseClasses": ["chatOpenAI"]}

        action, _ = store._compute_action_detail("chatOpenAI", api_raw)
        assert action == "update_changed_version_or_hash"

    def test_no_version_same_hash_skips(self):
        """No version on either side, identical content → skip_same_version."""
        api_raw = {
            "name": "customNode",
            "label": "customNode",
            "type": "customNode",
            "baseClasses": ["customNode"],
            "inputAnchors": [],
            "inputParams": [],
            "outputAnchors": [],
        }
        # Store the already-normalised form so local_hash == api_hash
        local = _normalize_api_schema(api_raw)
        store = _make_store({"customNode": local})

        action, _ = store._compute_action_detail("customNode", api_raw)
        assert action == "skip_same_version"

    def test_no_version_different_hash_updates(self):
        """No version on either side, content differs → update_no_version_info."""
        local = _minimal_schema("customNode")
        store = _make_store({"customNode": local})
        api_raw = {
            "name": "customNode",
            "label": "customNode",
            "type": "customNode",
            "baseClasses": ["customNode"],
            "inputAnchors": [],
            "inputParams": [{"name": "newParam", "type": "string", "label": "New"}],
            "outputAnchors": [],
        }

        action, _ = store._compute_action_detail("customNode", api_raw)
        assert action == "update_no_version_info"

    def test_new_node_always_updates(self):
        """Node absent from local index → update_new_node."""
        store = _make_store({})
        api_raw = {"name": "brandNewNode", "version": "1", "baseClasses": ["brandNewNode"]}

        action, _ = store._compute_action_detail("brandNewNode", api_raw)
        assert action == "update_new_node"

    def test_compute_action_wrapper_returns_string(self):
        """_compute_action (backwards-compat wrapper) must still return a plain string."""
        local = _minimal_schema("chatOpenAI", version="3")
        store = _make_store({"chatOpenAI": local})
        api_raw = {"name": "chatOpenAI", "version": "3", "baseClasses": ["chatOpenAI"]}

        result = store._compute_action("chatOpenAI", api_raw)
        assert isinstance(result, str)
        assert result == "skip_same_version"


# ---------------------------------------------------------------------------
# B) Detail dict content (M9.5 transparency requirement)
# ---------------------------------------------------------------------------


class TestGatingDetail:
    """_compute_action_detail must populate the detail dict for every case."""

    def test_version_match_detail(self):
        """Same-version detail uses comparison_method='version' and explains the match."""
        local = _minimal_schema("chatOpenAI", version="2")
        store = _make_store({"chatOpenAI": local})
        api_raw = {"name": "chatOpenAI", "version": "2", "baseClasses": ["chatOpenAI"]}

        _, detail = store._compute_action_detail("chatOpenAI", api_raw)
        assert detail["comparison_method"] == "version"
        assert detail["local_version"] == "2"
        assert detail["api_version"] == "2"
        assert "match" in detail["decision_reason"].lower()

    def test_version_change_detail(self):
        """Different-version detail captures both version strings and change direction."""
        local = _minimal_schema("chatOpenAI", version="1")
        store = _make_store({"chatOpenAI": local})
        api_raw = {"name": "chatOpenAI", "version": "2", "baseClasses": ["chatOpenAI"]}

        _, detail = store._compute_action_detail("chatOpenAI", api_raw)
        assert detail["comparison_method"] == "version"
        assert detail["local_version"] == "1"
        assert detail["api_version"] == "2"
        # Reason must mention both versions
        assert "1" in detail["decision_reason"]
        assert "2" in detail["decision_reason"]

    def test_hash_comparison_detail_has_hashes(self):
        """No-version case must include local_hash and api_hash in detail."""
        api_raw = {
            "name": "customNode",
            "label": "customNode",
            "type": "customNode",
            "baseClasses": ["customNode"],
            "inputAnchors": [],
            "inputParams": [],
            "outputAnchors": [],
        }
        local = _normalize_api_schema(api_raw)
        store = _make_store({"customNode": local})

        _, detail = store._compute_action_detail("customNode", api_raw)
        assert detail["comparison_method"] == "hash"
        assert "local_hash" in detail
        assert "api_hash" in detail
        # Both hashes must be non-empty hex strings
        assert len(detail["local_hash"]) == 16
        assert len(detail["api_hash"]) == 16

    def test_hash_match_detail_reason(self):
        """Hash-equal case reports 'content unchanged' in decision_reason."""
        api_raw = {
            "name": "customNode",
            "label": "customNode",
            "type": "customNode",
            "baseClasses": ["customNode"],
            "inputAnchors": [],
            "inputParams": [],
            "outputAnchors": [],
        }
        local = _normalize_api_schema(api_raw)
        store = _make_store({"customNode": local})

        _, detail = store._compute_action_detail("customNode", api_raw)
        assert "unchanged" in detail["decision_reason"].lower() or "match" in detail["decision_reason"].lower()

    def test_hash_differ_no_version_detail_reason(self):
        """Hash-differ, no-version case reports 'conservative update' in decision_reason."""
        local = _minimal_schema("customNode")
        store = _make_store({"customNode": local})
        api_raw = {
            "name": "customNode",
            "label": "customNode",
            "type": "customNode",
            "baseClasses": ["customNode"],
            "inputAnchors": [],
            "inputParams": [{"name": "p", "type": "string", "label": "P"}],
            "outputAnchors": [],
        }

        _, detail = store._compute_action_detail("customNode", api_raw)
        assert detail["comparison_method"] == "hash"
        assert detail["local_hash"] != detail["api_hash"]
        reason = detail["decision_reason"].lower()
        assert "conservative" in reason or "differ" in reason

    def test_new_node_detail(self):
        """New-node detail uses comparison_method='new_node' with None versions."""
        store = _make_store({})
        api_raw = {"name": "brandNew", "version": "1", "baseClasses": ["brandNew"]}

        _, detail = store._compute_action_detail("brandNew", api_raw)
        assert detail["comparison_method"] == "new_node"
        assert detail["local_version"] is None
        assert detail["api_version"] is None

    def test_detail_always_has_required_keys(self):
        """All four gating paths must always return the mandatory detail keys."""
        required_keys = {"comparison_method", "decision_reason", "local_version", "api_version"}
        cases = [
            # (store_index, api_raw)
            (
                {},
                {"name": "n", "version": "1", "baseClasses": ["n"]},
            ),
            (
                {"n": _minimal_schema("n", version="1")},
                {"name": "n", "version": "1", "baseClasses": ["n"]},
            ),
            (
                {"n": _minimal_schema("n", version="1")},
                {"name": "n", "version": "2", "baseClasses": ["n"]},
            ),
            (
                {"n": _normalize_api_schema({"name": "n", "label": "n", "type": "n",
                                             "baseClasses": ["n"], "inputAnchors": [],
                                             "inputParams": [], "outputAnchors": []})},
                {"name": "n", "label": "n", "type": "n", "baseClasses": ["n"],
                 "inputAnchors": [], "inputParams": [], "outputAnchors": []},
            ),
        ]
        for idx, (index, api_raw) in enumerate(cases):
            store = _make_store(index)
            _, detail = store._compute_action_detail("n", api_raw)
            for key in required_keys:
                assert key in detail, (
                    f"Case {idx}: detail missing key '{key}'. detail={detail}"
                )


# ---------------------------------------------------------------------------
# C) Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Version normalisation and boundary conditions."""

    def test_integer_version_treated_as_string(self):
        """api_raw version as int (e.g. 2) must be compared correctly to local '2'."""
        local = _minimal_schema("chatOpenAI", version="2")
        store = _make_store({"chatOpenAI": local})
        # Flowise sometimes returns version as integer, not string
        api_raw = {"name": "chatOpenAI", "version": 2, "baseClasses": ["chatOpenAI"]}

        action, detail = store._compute_action_detail("chatOpenAI", api_raw)
        assert action == "skip_same_version", (
            "Integer version 2 must match string version '2'"
        )
        assert detail["api_version"] == "2"

    def test_zero_version_treated_as_absent(self):
        """version=0 is falsy and must be treated as 'no version' (hash fallback)."""
        local = _minimal_schema("chatOpenAI")
        local["version"] = 0
        store = _make_store({"chatOpenAI": local})
        api_raw = {"name": "chatOpenAI", "version": 0, "baseClasses": ["chatOpenAI"]}

        _, detail = store._compute_action_detail("chatOpenAI", api_raw)
        # With version=0 on both sides the comparison falls through to hash
        assert detail["comparison_method"] == "hash"

    def test_partial_version_presence_falls_to_hash(self):
        """Local has version, API does not → fall through to hash comparison."""
        local = _minimal_schema("chatOpenAI", version="3")
        store = _make_store({"chatOpenAI": local})
        # API raw has no version field
        api_raw = {"name": "chatOpenAI", "baseClasses": ["chatOpenAI"],
                   "inputAnchors": [], "inputParams": [], "outputAnchors": []}

        _, detail = store._compute_action_detail("chatOpenAI", api_raw)
        assert detail["comparison_method"] == "hash", (
            "When only one side has a version, hash comparison must be used"
        )

    def test_whitespace_version_treated_as_absent(self):
        """version='  ' (blank) is treated the same as no version."""
        local = _minimal_schema("chatOpenAI")
        local["version"] = "  "
        store = _make_store({"chatOpenAI": local})
        api_raw = {"name": "chatOpenAI", "version": "  ", "baseClasses": ["chatOpenAI"]}

        _, detail = store._compute_action_detail("chatOpenAI", api_raw)
        assert detail["comparison_method"] == "hash"
