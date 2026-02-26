"""M10.3a — Patch IR Anchor Contract Update (DD-095).

Tests for:
- Exact-match anchor resolution path
- Deprecated fuzzy fallback path with metrics
- validate_patch_ops anchor validation with node_type_map
- Anchor resolution metrics (exact vs fuzzy counts and rates)
- CompileResult anchor_metrics integration
- LangSmith metadata extraction of anchor telemetry
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from flowise_dev_agent.agent.compiler import (
    CompileResult,
    GraphIR,
    _resolve_anchor_id,
    _resolve_anchor_id_fuzzy_deprecated,
    compile_patch_ops,
)
from flowise_dev_agent.agent.patch_ir import (
    AddNode,
    Connect,
    SetParam,
    validate_patch_ops,
)


# ---------------------------------------------------------------------------
# Fixtures: minimal node schemas
# ---------------------------------------------------------------------------

TOOL_AGENT_SCHEMA = {
    "name": "toolAgent",
    "inputAnchors": [
        {"id": "{nodeId}-input-tools-Tool", "name": "tools", "type": "Tool"},
        {"id": "{nodeId}-input-memory-BaseChatMemory", "name": "memory", "type": "BaseChatMemory"},
        {"id": "{nodeId}-input-model-BaseChatModel", "name": "model", "type": "BaseChatModel"},
    ],
    "outputAnchors": [
        {
            "id": "{nodeId}-output-toolAgent-AgentExecutor|BaseChain|Runnable",
            "name": "toolAgent",
            "type": "AgentExecutor | BaseChain | Runnable",
        },
    ],
}

CHAT_OPENAI_SCHEMA = {
    "name": "chatOpenAI",
    "inputAnchors": [
        {"id": "{nodeId}-input-cache-BaseCache", "name": "cache", "type": "BaseCache"},
    ],
    "outputAnchors": [
        {
            "id": "{nodeId}-output-chatOpenAI-ChatOpenAI",
            "name": "chatOpenAI",
            "type": "ChatOpenAI",
        },
    ],
}

BUFFER_MEMORY_SCHEMA = {
    "name": "bufferMemory",
    "inputAnchors": [],
    "outputAnchors": [
        {
            "id": "{nodeId}-output-bufferMemory-BufferMemory|BaseChatMemory|BaseMemory",
            "name": "bufferMemory",
            "type": "BufferMemory | BaseChatMemory | BaseMemory",
        },
    ],
}


# ---------------------------------------------------------------------------
# Test 1: Exact-match path
# ---------------------------------------------------------------------------


class TestExactMatchPath:
    """With canonical anchor names, _resolve_anchor_id uses exact match."""

    def test_exact_input_anchor_by_name(self):
        """anchor name 'memory' matches toolAgent's input anchor exactly."""
        metrics: dict = {}
        result = _resolve_anchor_id(
            TOOL_AGENT_SCHEMA, "toolAgent_0", "memory", "input",
            metrics=metrics,
        )
        assert result == "toolAgent_0-input-memory-BaseChatMemory"
        assert metrics.get("exact_name_matches", 0) == 1
        assert metrics.get("fuzzy_fallbacks", 0) == 0

    def test_exact_output_anchor_by_name(self):
        """anchor name 'chatOpenAI' matches output anchor exactly."""
        metrics: dict = {}
        result = _resolve_anchor_id(
            CHAT_OPENAI_SCHEMA, "chatOpenAI_0", "chatOpenAI", "output",
            metrics=metrics,
        )
        assert result == "chatOpenAI_0-output-chatOpenAI-ChatOpenAI"
        assert metrics.get("exact_name_matches", 0) == 1

    def test_case_insensitive_name_match(self):
        """Case-insensitive name match counts as exact."""
        metrics: dict = {}
        result = _resolve_anchor_id(
            TOOL_AGENT_SCHEMA, "toolAgent_0", "Memory", "input",
            metrics=metrics,
        )
        assert result is not None
        assert "memory" in result
        assert metrics.get("exact_name_matches", 0) == 1
        assert metrics.get("fuzzy_fallbacks", 0) == 0

    def test_model_anchor_exact(self):
        """anchor name 'model' matches toolAgent's model input."""
        result = _resolve_anchor_id(
            TOOL_AGENT_SCHEMA, "toolAgent_0", "model", "input",
        )
        assert result == "toolAgent_0-input-model-BaseChatModel"


# ---------------------------------------------------------------------------
# Test 2: Deprecated fuzzy fallback path
# ---------------------------------------------------------------------------


class TestFuzzyFallbackPath:
    """Legacy type-name anchors resolve via deprecated fuzzy fallback."""

    def test_type_name_resolves_via_fuzzy(self):
        """'BaseChatMemory' (a type name, not anchor name) resolves via fuzzy pass 3."""
        metrics: dict = {"fuzzy_fallbacks": 0, "fuzzy_details": []}
        result = _resolve_anchor_id(
            TOOL_AGENT_SCHEMA, "toolAgent_0", "BaseChatMemory", "input",
            metrics=metrics,
        )
        assert result == "toolAgent_0-input-memory-BaseChatMemory"
        assert metrics["fuzzy_fallbacks"] == 1
        assert len(metrics["fuzzy_details"]) == 1
        detail = metrics["fuzzy_details"][0]
        assert detail["node"] == "toolAgent_0"
        assert detail["anchor"] == "BaseChatMemory"
        assert detail["resolved_to"] == "memory"
        assert detail["pass"] == 3

    def test_type_suffix_resolves_via_fuzzy(self):
        """'ChatModel' (suffix of BaseChatModel) resolves via fuzzy pass 4."""
        metrics: dict = {"fuzzy_fallbacks": 0, "fuzzy_details": []}
        result = _resolve_anchor_id(
            TOOL_AGENT_SCHEMA, "toolAgent_0", "ChatModel", "input",
            metrics=metrics,
        )
        assert result is not None
        assert metrics["fuzzy_fallbacks"] == 1
        assert metrics["fuzzy_details"][0]["pass"] == 4

    def test_token_subset_resolves_via_fuzzy(self):
        """'BaseMemory' (token subset of BaseChatMemory) resolves via fuzzy pass 5."""
        metrics: dict = {"fuzzy_fallbacks": 0, "fuzzy_details": []}
        result = _resolve_anchor_id(
            TOOL_AGENT_SCHEMA, "toolAgent_0", "BaseMemory", "input",
            metrics=metrics,
        )
        assert result is not None
        assert metrics["fuzzy_fallbacks"] == 1
        assert metrics["fuzzy_details"][0]["pass"] == 5

    def test_unknown_anchor_returns_none(self):
        """Completely unknown anchor returns None."""
        result = _resolve_anchor_id(
            TOOL_AGENT_SCHEMA, "toolAgent_0", "nonExistentAnchor", "input",
        )
        assert result is None

    def test_fuzzy_deprecated_function_directly(self):
        """_resolve_anchor_id_fuzzy_deprecated handles the fuzzy passes."""
        anchors = TOOL_AGENT_SCHEMA["inputAnchors"]
        metrics: dict = {"fuzzy_fallbacks": 0, "fuzzy_details": []}
        result = _resolve_anchor_id_fuzzy_deprecated(
            anchors, "toolAgent_0", "BaseChatModel", "input",
            metrics=metrics,
        )
        assert result is not None
        assert metrics["fuzzy_fallbacks"] == 1


# ---------------------------------------------------------------------------
# Test 3: validate_patch_ops anchor validation
# ---------------------------------------------------------------------------


class TestValidatePatchOpsAnchors:
    """validate_patch_ops with anchor_store + node_type_map."""

    def _make_anchor_store(self):
        """Create a minimal mock anchor store."""
        store = MagicMock()
        store.get.side_effect = lambda node_type: {
            "toolAgent": {
                "node_type": "toolAgent",
                "input_anchors": [
                    {"name": "tools", "type": "Tool"},
                    {"name": "memory", "type": "BaseChatMemory"},
                    {"name": "model", "type": "BaseChatModel"},
                ],
                "output_anchors": [
                    {"name": "toolAgent", "type": "AgentExecutor | BaseChain | Runnable"},
                ],
            },
            "chatOpenAI": {
                "node_type": "chatOpenAI",
                "input_anchors": [
                    {"name": "cache", "type": "BaseCache"},
                ],
                "output_anchors": [
                    {"name": "chatOpenAI", "type": "ChatOpenAI"},
                ],
            },
        }.get(node_type)
        return store

    def test_valid_anchors_no_warnings(self):
        """Correct canonical anchor names produce no warnings."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            AddNode(node_name="toolAgent", node_id="toolAgent_0"),
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="chatOpenAI",
                target_node_id="toolAgent_0",
                target_anchor="model",
            ),
        ]
        errors, warnings = validate_patch_ops(
            ops,
            anchor_store=self._make_anchor_store(),
        )
        assert errors == []
        assert warnings == []

    def test_invalid_target_anchor_warns(self):
        """Invalid target anchor name produces a warning with valid options."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            AddNode(node_name="toolAgent", node_id="toolAgent_0"),
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="chatOpenAI",
                target_node_id="toolAgent_0",
                target_anchor="BaseChatModel",  # type name, not anchor name
            ),
        ]
        errors, warnings = validate_patch_ops(
            ops,
            anchor_store=self._make_anchor_store(),
        )
        assert errors == []
        assert len(warnings) == 1
        assert "BaseChatModel" in warnings[0]
        assert "Valid options" in warnings[0]
        assert "model" in warnings[0]

    def test_invalid_source_anchor_warns(self):
        """Invalid source anchor name produces a warning."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            AddNode(node_name="toolAgent", node_id="toolAgent_0"),
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="ChatOpenAI",  # type name, not anchor name
                target_node_id="toolAgent_0",
                target_anchor="model",
            ),
        ]
        errors, warnings = validate_patch_ops(
            ops,
            anchor_store=self._make_anchor_store(),
        )
        # "ChatOpenAI" != "chatOpenAI" (case-sensitive anchor names)
        assert len(warnings) >= 1
        assert any("ChatOpenAI" in w for w in warnings)

    def test_missing_node_type_mapping_warns(self):
        """Missing node_type mapping produces a skip warning."""
        ops = [
            Connect(
                source_node_id="unknown_0",
                source_anchor="output",
                target_node_id="unknown_1",
                target_anchor="input",
            ),
        ]
        errors, warnings = validate_patch_ops(
            ops,
            base_node_ids={"unknown_0", "unknown_1"},
            anchor_store=self._make_anchor_store(),
            node_type_map={},  # empty map
        )
        assert len(warnings) >= 2  # one for source, one for target
        assert any("no node_type mapping" in w for w in warnings)

    def test_with_node_type_map_from_caller(self):
        """node_type_map from caller is used for validation."""
        ops = [
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="chatOpenAI",
                target_node_id="toolAgent_0",
                target_anchor="model",
            ),
        ]
        errors, warnings = validate_patch_ops(
            ops,
            base_node_ids={"chatOpenAI_0", "toolAgent_0"},
            anchor_store=self._make_anchor_store(),
            node_type_map={
                "chatOpenAI_0": "chatOpenAI",
                "toolAgent_0": "toolAgent",
            },
        )
        assert errors == []
        assert warnings == []

    def test_no_anchor_store_skips_validation(self):
        """Without anchor_store, no anchor validation is performed."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            AddNode(node_name="toolAgent", node_id="toolAgent_0"),
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="INVALID",
                target_node_id="toolAgent_0",
                target_anchor="ALSO_INVALID",
            ),
        ]
        errors, warnings = validate_patch_ops(ops)
        assert errors == []
        assert warnings == []  # no anchor validation without store

    def test_returns_tuple(self):
        """validate_patch_ops returns (errors, warnings) tuple."""
        ops = [AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0")]
        result = validate_patch_ops(ops)
        assert isinstance(result, tuple)
        assert len(result) == 2
        errors, warnings = result
        assert isinstance(errors, list)
        assert isinstance(warnings, list)


# ---------------------------------------------------------------------------
# Test 4: Metrics correctness
# ---------------------------------------------------------------------------


class TestMetricsCorrectness:
    """Exact vs fuzzy counts computed correctly; exact_match_rate matches."""

    def test_all_exact_matches(self):
        """All canonical names → exact_match_rate = 1.0."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            AddNode(node_name="toolAgent", node_id="toolAgent_0"),
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="chatOpenAI",
                target_node_id="toolAgent_0",
                target_anchor="model",
            ),
        ]
        schema_cache = {
            "chatOpenAI": CHAT_OPENAI_SCHEMA,
            "toolAgent": TOOL_AGENT_SCHEMA,
        }
        result = compile_patch_ops(GraphIR(), ops, schema_cache)
        metrics = result.anchor_metrics

        assert metrics["total_connections"] == 1
        assert metrics["exact_name_matches"] == 2  # source + target
        assert metrics["fuzzy_fallbacks"] == 0
        assert metrics["exact_match_rate"] == 1.0
        assert metrics["fuzzy_details"] == []

    def test_mixed_exact_and_fuzzy(self):
        """One exact + one fuzzy → rate = 0.5."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            AddNode(node_name="toolAgent", node_id="toolAgent_0"),
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="chatOpenAI",       # exact match
                target_node_id="toolAgent_0",
                target_anchor="BaseChatModel",     # fuzzy fallback
            ),
        ]
        schema_cache = {
            "chatOpenAI": CHAT_OPENAI_SCHEMA,
            "toolAgent": TOOL_AGENT_SCHEMA,
        }
        result = compile_patch_ops(GraphIR(), ops, schema_cache)
        metrics = result.anchor_metrics

        assert metrics["total_connections"] == 1
        assert metrics["exact_name_matches"] == 1
        assert metrics["fuzzy_fallbacks"] == 1
        assert metrics["exact_match_rate"] == pytest.approx(0.5)
        assert len(metrics["fuzzy_details"]) == 1

    def test_all_fuzzy(self):
        """All type-name anchors → rate = 0.0."""
        # Use bufferMemory source with "BaseChatMemory" — this does NOT
        # case-match the anchor name "bufferMemory", so it requires fuzzy.
        # (ChatOpenAI case-insensitively matches chatOpenAI → exact, not fuzzy.)
        ops = [
            AddNode(node_name="bufferMemory", node_id="bufferMemory_0"),
            AddNode(node_name="toolAgent", node_id="toolAgent_0"),
            Connect(
                source_node_id="bufferMemory_0",
                source_anchor="BaseChatMemory",    # fuzzy (type name ≠ anchor name)
                target_node_id="toolAgent_0",
                target_anchor="BaseChatModel",     # fuzzy (type name ≠ anchor name)
            ),
        ]
        schema_cache = {
            "bufferMemory": BUFFER_MEMORY_SCHEMA,
            "toolAgent": TOOL_AGENT_SCHEMA,
        }
        result = compile_patch_ops(GraphIR(), ops, schema_cache)
        metrics = result.anchor_metrics

        assert metrics["fuzzy_fallbacks"] == 2
        assert metrics["exact_name_matches"] == 0
        assert metrics["exact_match_rate"] == pytest.approx(0.0)

    def test_no_connections(self):
        """No Connect ops → vacuously 1.0."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
        ]
        schema_cache = {"chatOpenAI": CHAT_OPENAI_SCHEMA}
        result = compile_patch_ops(GraphIR(), ops, schema_cache)
        metrics = result.anchor_metrics

        assert metrics["total_connections"] == 0
        assert metrics["exact_match_rate"] == 1.0

    def test_compile_result_has_anchor_metrics(self):
        """CompileResult always has anchor_metrics dict."""
        ops = []
        result = compile_patch_ops(GraphIR(), ops, {})
        assert hasattr(result, "anchor_metrics")
        assert isinstance(result.anchor_metrics, dict)
        assert "total_connections" in result.anchor_metrics
        assert "exact_name_matches" in result.anchor_metrics
        assert "fuzzy_fallbacks" in result.anchor_metrics
        assert "exact_match_rate" in result.anchor_metrics


# ---------------------------------------------------------------------------
# Test 5: LangSmith metadata extraction
# ---------------------------------------------------------------------------


class TestLangSmithAnchorMetrics:
    """LangSmith metadata extraction includes anchor resolution telemetry."""

    def test_anchor_metrics_in_metadata(self):
        from flowise_dev_agent.util.langsmith.metadata import extract_session_metadata

        state = {
            "debug": {
                "flowise": {
                    "anchor_resolution": {
                        "total_connections": 5,
                        "exact_name_matches": 4,
                        "fuzzy_fallbacks": 1,
                        "exact_match_rate": 0.8,
                    },
                },
            },
        }
        meta = extract_session_metadata(state)
        assert meta["telemetry.anchor_exact_match_rate"] == 0.8
        assert meta["telemetry.anchor_fuzzy_fallbacks"] == 1
        assert meta["telemetry.anchor_total_connections"] == 5

    def test_no_anchor_metrics_graceful(self):
        from flowise_dev_agent.util.langsmith.metadata import extract_session_metadata

        state = {"debug": {"flowise": {}}}
        meta = extract_session_metadata(state)
        # Should not have anchor keys when no data
        assert "telemetry.anchor_exact_match_rate" not in meta

    def test_empty_state_graceful(self):
        from flowise_dev_agent.util.langsmith.metadata import extract_session_metadata

        meta = extract_session_metadata({})
        assert "telemetry.anchor_exact_match_rate" not in meta


# ---------------------------------------------------------------------------
# Test 6: Connect docstring update
# ---------------------------------------------------------------------------


class TestConnectDocstring:
    """Connect docstring reflects canonical anchor name contract."""

    def test_connect_docstring_mentions_canonical(self):
        from flowise_dev_agent.agent.patch_ir import Connect

        doc = Connect.__doc__ or ""
        assert "canonical" in doc.lower()
        assert "DEPRECATED" in doc
        assert "get_anchor_dictionary" in doc

    def test_connect_docstring_target_is_name(self):
        """target_anchor described as NAME, not TYPE."""
        from flowise_dev_agent.agent.patch_ir import Connect

        doc = Connect.__doc__ or ""
        assert "Canonical NAME" in doc


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


class TestImportSmoke:
    """Module imports work correctly."""

    def test_import_compiler(self):
        from flowise_dev_agent.agent.compiler import (  # noqa: F401
            _resolve_anchor_id,
            _resolve_anchor_id_fuzzy_deprecated,
            compile_patch_ops,
            CompileResult,
        )

    def test_import_patch_ir(self):
        from flowise_dev_agent.agent.patch_ir import (  # noqa: F401
            Connect,
            validate_patch_ops,
        )

    def test_import_metadata(self):
        from flowise_dev_agent.util.langsmith.metadata import (  # noqa: F401
            extract_session_metadata,
        )
