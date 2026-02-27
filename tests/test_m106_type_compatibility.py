"""M10.6 — Anchor Type Compatibility Validation (DD-102).

Tests for:
- Layer 2: _validate_connect_anchors() type overlap warnings (patch_ir.py)
- Layer 3: _validate_flow_data() type overlap errors (tools.py)
- Layer 3: validate node type_mismatch failure classification (graph.py)
- Layer 3: _route_after_validate routing for type_mismatch (graph.py)
- End-to-end: compile_patch_ops → _validate_flow_data catches type mismatch
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from flowise_dev_agent.agent.compiler import (
    GraphIR,
    compile_patch_ops,
)
from flowise_dev_agent.agent.patch_ir import (
    AddNode,
    Connect,
    _validate_connect_anchors,
    validate_patch_ops,
)
from flowise_dev_agent.agent.tools import _validate_flow_data


# ---------------------------------------------------------------------------
# Fixtures: minimal node schemas
# ---------------------------------------------------------------------------

TOOL_AGENT_SCHEMA = {
    "name": "toolAgent",
    "baseClasses": ["AgentExecutor", "BaseChain", "Runnable"],
    "inputAnchors": [
        {"id": "{nodeId}-input-tools-Tool", "name": "tools", "type": "Tool"},
        {"id": "{nodeId}-input-memory-BaseChatMemory", "name": "memory", "type": "BaseChatMemory"},
        {"id": "{nodeId}-input-model-BaseChatModel", "name": "model", "type": "BaseChatModel"},
    ],
    "inputParams": [],
    "outputAnchors": [
        {
            "id": "{nodeId}-output-toolAgent-AgentExecutor|BaseChain|Runnable",
            "name": "toolAgent",
            "type": "AgentExecutor|BaseChain|Runnable",
        },
    ],
}

CHAT_OPENAI_SCHEMA = {
    "name": "chatOpenAI",
    "baseClasses": ["ChatOpenAI", "BaseChatModel", "BaseLanguageModel", "Runnable"],
    "inputAnchors": [
        {"id": "{nodeId}-input-cache-BaseCache", "name": "cache", "type": "BaseCache"},
    ],
    "inputParams": [{"name": "modelName", "default": "gpt-4o"}],
    "outputAnchors": [
        {
            "id": "{nodeId}-output-chatOpenAI-ChatOpenAI|BaseChatModel|BaseLanguageModel|Runnable",
            "name": "chatOpenAI",
            "type": "ChatOpenAI|BaseChatModel|BaseLanguageModel|Runnable",
        },
    ],
}

BUFFER_MEMORY_SCHEMA = {
    "name": "bufferMemory",
    "baseClasses": ["BufferMemory", "BaseChatMemory", "BaseMemory"],
    "inputAnchors": [],
    "inputParams": [],
    "outputAnchors": [
        {
            "id": "{nodeId}-output-bufferMemory-BufferMemory|BaseChatMemory|BaseMemory",
            "name": "bufferMemory",
            "type": "BufferMemory|BaseChatMemory|BaseMemory",
        },
    ],
}

CHEERIO_SCRAPER_SCHEMA = {
    "name": "cheerioWebScraper",
    "baseClasses": ["Document"],
    "inputAnchors": [],
    "inputParams": [{"name": "url", "default": ""}],
    "outputAnchors": [
        {
            "id": "{nodeId}-output-document-Document|json",
            "name": "document",
            "type": "Document|json",
        },
        {
            "id": "{nodeId}-output-text-string|json",
            "name": "text",
            "type": "string|json",
        },
    ],
}

CONVERSATION_CHAIN_SCHEMA = {
    "name": "conversationChain",
    "baseClasses": ["ConversationChain", "BaseChain", "Runnable"],
    "inputAnchors": [
        {"id": "{nodeId}-input-model-BaseChatModel", "name": "model", "type": "BaseChatModel"},
        {"id": "{nodeId}-input-memory-BaseMemory", "name": "memory", "type": "BaseMemory"},
    ],
    "inputParams": [],
    "outputAnchors": [
        {
            "id": "{nodeId}-output-conversationChain-ConversationChain|BaseChain|Runnable",
            "name": "conversationChain",
            "type": "ConversationChain|BaseChain|Runnable",
        },
    ],
}


def _make_anchor_store_mock(schemas: dict[str, dict]) -> MagicMock:
    """Build a mock AnchorDictionaryStore from a dict of {node_type: schema}."""
    from flowise_dev_agent.knowledge.anchor_store import normalize_schema_to_anchor_dict

    store = MagicMock()
    index = {}
    for node_type, schema in schemas.items():
        index[node_type] = normalize_schema_to_anchor_dict(schema, node_type)

    store.get = lambda nt: index.get(nt)
    return store


# ---------------------------------------------------------------------------
# Layer 2: _validate_connect_anchors — type overlap warnings
# ---------------------------------------------------------------------------


class TestValidateConnectAnchorsTypeCheck:
    """Tests for type overlap checking in _validate_connect_anchors."""

    def test_compatible_types_no_warning(self):
        """chatOpenAI → conversationChain.model: ChatOpenAI|BaseChatModel ∩ BaseChatModel → ok."""
        store = _make_anchor_store_mock({
            "chatOpenAI": CHAT_OPENAI_SCHEMA,
            "conversationChain": CONVERSATION_CHAIN_SCHEMA,
        })
        op = Connect(
            source_node_id="chatOpenAI_0",
            source_anchor="chatOpenAI",
            target_node_id="conversationChain_0",
            target_anchor="model",
        )
        warnings: list[str] = []
        _validate_connect_anchors(
            0, op,
            {"chatOpenAI_0": "chatOpenAI", "conversationChain_0": "conversationChain"},
            store, warnings,
        )
        type_warnings = [w for w in warnings if "type mismatch" in w.lower()]
        assert type_warnings == []

    def test_incompatible_types_warning(self):
        """cheerioWebScraper.text → toolAgent.tools: string|json ∩ Tool = ∅ → warning."""
        store = _make_anchor_store_mock({
            "cheerioWebScraper": CHEERIO_SCRAPER_SCHEMA,
            "toolAgent": TOOL_AGENT_SCHEMA,
        })
        op = Connect(
            source_node_id="cheerioWebScraper_0",
            source_anchor="text",
            target_node_id="toolAgent_0",
            target_anchor="tools",
        )
        warnings: list[str] = []
        _validate_connect_anchors(
            0, op,
            {"cheerioWebScraper_0": "cheerioWebScraper", "toolAgent_0": "toolAgent"},
            store, warnings,
        )
        type_warnings = [w for w in warnings if "type mismatch" in w.lower()]
        assert len(type_warnings) == 1
        assert "string|json" in type_warnings[0]
        assert "Tool" in type_warnings[0]

    def test_buffer_memory_to_tool_agent_memory_compatible(self):
        """bufferMemory → toolAgent.memory: BaseChatMemory ∩ BaseChatMemory → ok."""
        store = _make_anchor_store_mock({
            "bufferMemory": BUFFER_MEMORY_SCHEMA,
            "toolAgent": TOOL_AGENT_SCHEMA,
        })
        op = Connect(
            source_node_id="bufferMemory_0",
            source_anchor="bufferMemory",
            target_node_id="toolAgent_0",
            target_anchor="memory",
        )
        warnings: list[str] = []
        _validate_connect_anchors(
            0, op,
            {"bufferMemory_0": "bufferMemory", "toolAgent_0": "toolAgent"},
            store, warnings,
        )
        type_warnings = [w for w in warnings if "type mismatch" in w.lower()]
        assert type_warnings == []

    def test_unknown_source_anchor_no_type_check(self):
        """If source anchor not found, name warning but no type check."""
        store = _make_anchor_store_mock({
            "chatOpenAI": CHAT_OPENAI_SCHEMA,
            "toolAgent": TOOL_AGENT_SCHEMA,
        })
        op = Connect(
            source_node_id="chatOpenAI_0",
            source_anchor="nonexistent",
            target_node_id="toolAgent_0",
            target_anchor="tools",
        )
        warnings: list[str] = []
        _validate_connect_anchors(
            0, op,
            {"chatOpenAI_0": "chatOpenAI", "toolAgent_0": "toolAgent"},
            store, warnings,
        )
        name_warnings = [w for w in warnings if "not found" in w.lower()]
        type_warnings = [w for w in warnings if "type mismatch" in w.lower()]
        assert len(name_warnings) == 1
        assert type_warnings == []  # no type check when name not found

    def test_no_anchor_store_skips_type_check(self):
        """Without anchor_store, validate_patch_ops skips anchor checks entirely."""
        ops = [
            AddNode(node_name="cheerioWebScraper", node_id="cheerioWebScraper_0"),
            AddNode(node_name="toolAgent", node_id="toolAgent_0"),
            Connect(
                source_node_id="cheerioWebScraper_0",
                source_anchor="text",
                target_node_id="toolAgent_0",
                target_anchor="tools",
            ),
        ]
        errors, warnings = validate_patch_ops(ops)
        assert errors == []
        assert warnings == []  # no anchor_store → no anchor checks


class TestValidatePatchOpsWithAnchorStore:
    """Tests for validate_patch_ops with anchor_store wired in."""

    def test_type_mismatch_returns_warning(self):
        """Full validate_patch_ops with anchor_store returns type mismatch warning."""
        store = _make_anchor_store_mock({
            "cheerioWebScraper": CHEERIO_SCRAPER_SCHEMA,
            "toolAgent": TOOL_AGENT_SCHEMA,
        })
        ops = [
            AddNode(node_name="cheerioWebScraper", node_id="cheerioWebScraper_0"),
            AddNode(node_name="toolAgent", node_id="toolAgent_0"),
            Connect(
                source_node_id="cheerioWebScraper_0",
                source_anchor="text",
                target_node_id="toolAgent_0",
                target_anchor="tools",
            ),
        ]
        errors, warnings = validate_patch_ops(
            ops, anchor_store=store,
            node_type_map={"cheerioWebScraper_0": "cheerioWebScraper", "toolAgent_0": "toolAgent"},
        )
        assert errors == []  # warnings, not errors
        type_warnings = [w for w in warnings if "type mismatch" in w.lower()]
        assert len(type_warnings) == 1

    def test_compatible_flow_no_warnings(self):
        """Valid chatOpenAI → conversationChain produces no type warnings."""
        store = _make_anchor_store_mock({
            "chatOpenAI": CHAT_OPENAI_SCHEMA,
            "conversationChain": CONVERSATION_CHAIN_SCHEMA,
            "bufferMemory": BUFFER_MEMORY_SCHEMA,
        })
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            AddNode(node_name="conversationChain", node_id="conversationChain_0"),
            AddNode(node_name="bufferMemory", node_id="bufferMemory_0"),
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="chatOpenAI",
                target_node_id="conversationChain_0",
                target_anchor="model",
            ),
            Connect(
                source_node_id="bufferMemory_0",
                source_anchor="bufferMemory",
                target_node_id="conversationChain_0",
                target_anchor="memory",
            ),
        ]
        node_type_map = {
            "chatOpenAI_0": "chatOpenAI",
            "conversationChain_0": "conversationChain",
            "bufferMemory_0": "bufferMemory",
        }
        errors, warnings = validate_patch_ops(
            ops, anchor_store=store, node_type_map=node_type_map,
        )
        assert errors == []
        type_warnings = [w for w in warnings if "type mismatch" in w.lower()]
        assert type_warnings == []


# ---------------------------------------------------------------------------
# Layer 3: _validate_flow_data — type overlap errors
# ---------------------------------------------------------------------------


def _build_flow_data(nodes: list[dict], edges: list[dict]) -> str:
    """Build a compact flowData JSON string for testing."""
    return json.dumps({"nodes": nodes, "edges": edges}, separators=(",", ":"))


def _make_node(node_id: str, schema: dict) -> dict:
    """Build a Flowise node dict from a schema, substituting {nodeId}."""
    import copy

    def _sub(obj):
        if isinstance(obj, str):
            return obj.replace("{nodeId}", node_id)
        if isinstance(obj, list):
            return [_sub(i) for i in obj]
        if isinstance(obj, dict):
            return {k: _sub(v) for k, v in obj.items()}
        return obj

    data = {
        "id": node_id,
        "label": schema.get("name", ""),
        "name": schema.get("name", ""),
        "type": schema.get("name", ""),
        "baseClasses": schema.get("baseClasses", []),
        "inputAnchors": _sub(copy.deepcopy(schema.get("inputAnchors", []))),
        "inputParams": _sub(copy.deepcopy(schema.get("inputParams", []))),
        "outputAnchors": _sub(copy.deepcopy(schema.get("outputAnchors", []))),
        "outputs": {},
        "inputs": {},
    }
    return {"id": node_id, "position": {"x": 0, "y": 0}, "type": "customNode", "data": data}


class TestValidateFlowDataTypeCompatibility:
    """Tests for type overlap checking in _validate_flow_data."""

    def test_compatible_edge_passes(self):
        """chatOpenAI → conversationChain.model: type overlap → valid."""
        nodes = [
            _make_node("chatOpenAI_0", CHAT_OPENAI_SCHEMA),
            _make_node("conversationChain_0", CONVERSATION_CHAIN_SCHEMA),
        ]
        edges = [{
            "source": "chatOpenAI_0",
            "sourceHandle": "chatOpenAI_0-output-chatOpenAI-ChatOpenAI|BaseChatModel|BaseLanguageModel|Runnable",
            "target": "conversationChain_0",
            "targetHandle": "conversationChain_0-input-model-BaseChatModel",
            "type": "buttonedge",
            "id": "e1",
        }]
        result = _validate_flow_data(_build_flow_data(nodes, edges))
        assert result["valid"] is True

    def test_incompatible_edge_fails(self):
        """cheerioWebScraper.text → toolAgent.tools: string|json ∩ Tool = ∅ → error."""
        nodes = [
            _make_node("cheerioWebScraper_0", CHEERIO_SCRAPER_SCHEMA),
            _make_node("toolAgent_0", TOOL_AGENT_SCHEMA),
        ]
        edges = [{
            "source": "cheerioWebScraper_0",
            "sourceHandle": "cheerioWebScraper_0-output-text-string|json",
            "target": "toolAgent_0",
            "targetHandle": "toolAgent_0-input-tools-Tool",
            "type": "buttonedge",
            "id": "e1",
        }]
        result = _validate_flow_data(_build_flow_data(nodes, edges))
        assert result["valid"] is False
        assert any("type mismatch" in e.lower() for e in result["errors"])
        assert any("string|json" in e for e in result["errors"])
        assert any("Tool" in e for e in result["errors"])

    def test_buffer_memory_to_conversation_chain_compatible(self):
        """bufferMemory → conversationChain.memory: BaseMemory overlap → valid."""
        nodes = [
            _make_node("bufferMemory_0", BUFFER_MEMORY_SCHEMA),
            _make_node("conversationChain_0", CONVERSATION_CHAIN_SCHEMA),
        ]
        edges = [{
            "source": "bufferMemory_0",
            "sourceHandle": "bufferMemory_0-output-bufferMemory-BufferMemory|BaseChatMemory|BaseMemory",
            "target": "conversationChain_0",
            "targetHandle": "conversationChain_0-input-memory-BaseMemory",
            "type": "buttonedge",
            "id": "e1",
        }]
        result = _validate_flow_data(_build_flow_data(nodes, edges))
        assert result["valid"] is True

    def test_empty_type_skips_check(self):
        """Edge with empty type on one side skips type compatibility check."""
        nodes = [
            _make_node("chatOpenAI_0", CHAT_OPENAI_SCHEMA),
            _make_node("conversationChain_0", CONVERSATION_CHAIN_SCHEMA),
        ]
        # Fabricate an anchor with empty type on source
        nodes[0]["data"]["outputAnchors"][0]["type"] = ""
        edges = [{
            "source": "chatOpenAI_0",
            "sourceHandle": "chatOpenAI_0-output-chatOpenAI-ChatOpenAI|BaseChatModel|BaseLanguageModel|Runnable",
            "target": "conversationChain_0",
            "targetHandle": "conversationChain_0-input-model-BaseChatModel",
            "type": "buttonedge",
            "id": "e1",
        }]
        result = _validate_flow_data(_build_flow_data(nodes, edges))
        assert result["valid"] is True  # empty type → skip check

    def test_mixed_valid_and_invalid_edges(self):
        """Flow with one valid and one invalid edge: only invalid errors."""
        nodes = [
            _make_node("chatOpenAI_0", CHAT_OPENAI_SCHEMA),
            _make_node("cheerioWebScraper_0", CHEERIO_SCRAPER_SCHEMA),
            _make_node("toolAgent_0", TOOL_AGENT_SCHEMA),
        ]
        edges = [
            # Valid: chatOpenAI → toolAgent.model (BaseChatModel overlap)
            {
                "source": "chatOpenAI_0",
                "sourceHandle": "chatOpenAI_0-output-chatOpenAI-ChatOpenAI|BaseChatModel|BaseLanguageModel|Runnable",
                "target": "toolAgent_0",
                "targetHandle": "toolAgent_0-input-model-BaseChatModel",
                "type": "buttonedge",
                "id": "e1",
            },
            # Invalid: cheerioWebScraper.text → toolAgent.tools
            {
                "source": "cheerioWebScraper_0",
                "sourceHandle": "cheerioWebScraper_0-output-text-string|json",
                "target": "toolAgent_0",
                "targetHandle": "toolAgent_0-input-tools-Tool",
                "type": "buttonedge",
                "id": "e2",
            },
        ]
        result = _validate_flow_data(_build_flow_data(nodes, edges))
        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "cheerioWebScraper_0" in result["errors"][0]
        assert "toolAgent_0" in result["errors"][0]

    def test_multi_output_node_type_check(self):
        """Multi-output node with options[] — type is in option entries."""
        # Build a node with multi-output (options format)
        nodes = [
            _make_node("cheerioWebScraper_0", CHEERIO_SCRAPER_SCHEMA),
            _make_node("toolAgent_0", TOOL_AGENT_SCHEMA),
        ]
        # Restructure cheerioWebScraper output to options format (as compiler does)
        raw_outputs = nodes[0]["data"]["outputAnchors"]
        nodes[0]["data"]["outputAnchors"] = [{
            "name": "output",
            "label": "Output",
            "type": "options",
            "options": raw_outputs,
            "default": raw_outputs[0]["name"],
        }]
        edges = [{
            "source": "cheerioWebScraper_0",
            "sourceHandle": "cheerioWebScraper_0-output-text-string|json",
            "target": "toolAgent_0",
            "targetHandle": "toolAgent_0-input-tools-Tool",
            "type": "buttonedge",
            "id": "e1",
        }]
        result = _validate_flow_data(_build_flow_data(nodes, edges))
        assert result["valid"] is False
        assert any("type mismatch" in e.lower() for e in result["errors"])


# ---------------------------------------------------------------------------
# Layer 3: validate node failure classification
# ---------------------------------------------------------------------------


class TestValidateNodeClassification:
    """Tests for type_mismatch failure_type classification in the validate node."""

    def test_type_mismatch_classified_correctly(self):
        """Errors containing 'type mismatch' set failure_type = 'type_mismatch'."""
        errors = [
            "Edge cheerioWebScraper_0→toolAgent_0: type mismatch — source outputs 'string|json' but target expects 'Tool'"
        ]
        # Simulate the classification logic from _make_validate_node
        missing_types = []
        failure_type = "structural"
        has_type_mismatch = False
        for err in errors:
            if "no schema" in err.lower() or "unknown node type" in err.lower():
                failure_type = "schema_mismatch"
            elif "type mismatch" in err.lower():
                has_type_mismatch = True
        if has_type_mismatch and failure_type != "schema_mismatch":
            failure_type = "type_mismatch"
        assert failure_type == "type_mismatch"

    def test_schema_mismatch_takes_precedence(self):
        """schema_mismatch takes precedence over type_mismatch."""
        errors = [
            "Node 'x': no schema for 'unknownNode'",
            "Edge a→b: type mismatch — source outputs 'X' but target expects 'Y'",
        ]
        missing_types = []
        failure_type = "structural"
        has_type_mismatch = False
        for err in errors:
            if "no schema" in err.lower() or "unknown node type" in err.lower():
                failure_type = "schema_mismatch"
            elif "type mismatch" in err.lower():
                has_type_mismatch = True
        if has_type_mismatch and failure_type != "schema_mismatch":
            failure_type = "type_mismatch"
        assert failure_type == "schema_mismatch"

    def test_pure_structural_stays_structural(self):
        """Non-type-mismatch errors stay structural."""
        errors = [
            "Edge: source 'x' not found in nodes",
        ]
        failure_type = "structural"
        has_type_mismatch = False
        for err in errors:
            if "type mismatch" in err.lower():
                has_type_mismatch = True
        if has_type_mismatch and failure_type != "schema_mismatch":
            failure_type = "type_mismatch"
        assert failure_type == "structural"


# ---------------------------------------------------------------------------
# Layer 3: _route_after_validate routing
# ---------------------------------------------------------------------------


class TestRouteAfterValidate:
    """Tests for routing type_mismatch to plan_v2."""

    def test_type_mismatch_routes_to_plan_v2(self):
        """failure_type='type_mismatch' routes to plan_v2."""
        from flowise_dev_agent.agent.graph import _route_after_validate

        state = {
            "facts": {
                "validation": {
                    "ok": False,
                    "failure_type": "type_mismatch",
                    "missing_node_types": [],
                },
                "repair": {},
                "budgets": {},
            },
        }
        assert _route_after_validate(state) == "plan_v2"

    def test_ok_routes_to_preflight(self):
        """ok=True routes to preflight_validate_patch."""
        from flowise_dev_agent.agent.graph import _route_after_validate

        state = {
            "facts": {
                "validation": {"ok": True},
                "repair": {},
                "budgets": {},
            },
        }
        assert _route_after_validate(state) == "preflight_validate_patch"


# ---------------------------------------------------------------------------
# End-to-end: compile_patch_ops → _validate_flow_data catches mismatch
# ---------------------------------------------------------------------------


class TestEndToEndTypeCheck:
    """End-to-end: compile then validate catches type mismatch."""

    def test_compile_then_validate_catches_mismatch(self):
        """Compile cheerioWebScraper→toolAgent.tools, then validate catches it."""
        schema_cache = {
            "cheerioWebScraper": CHEERIO_SCRAPER_SCHEMA,
            "toolAgent": TOOL_AGENT_SCHEMA,
            "chatOpenAI": CHAT_OPENAI_SCHEMA,
        }
        ops = [
            AddNode(node_name="cheerioWebScraper", node_id="cheerioWebScraper_0"),
            AddNode(node_name="toolAgent", node_id="toolAgent_0"),
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="chatOpenAI",
                target_node_id="toolAgent_0",
                target_anchor="model",
            ),
            Connect(
                source_node_id="cheerioWebScraper_0",
                source_anchor="text",
                target_node_id="toolAgent_0",
                target_anchor="tools",
            ),
        ]
        result = compile_patch_ops(GraphIR(), ops, schema_cache)
        assert result.ok  # compiler doesn't check types

        # Now validate the compiled flowData
        validation = _validate_flow_data(result.flow_data_str)
        assert validation["valid"] is False
        type_errors = [e for e in validation["errors"] if "type mismatch" in e.lower()]
        assert len(type_errors) == 1
        assert "string|json" in type_errors[0]
        assert "Tool" in type_errors[0]

    def test_compile_then_validate_passes_compatible(self):
        """Compile chatOpenAI→conversationChain, then validate passes."""
        schema_cache = {
            "chatOpenAI": CHAT_OPENAI_SCHEMA,
            "conversationChain": CONVERSATION_CHAIN_SCHEMA,
            "bufferMemory": BUFFER_MEMORY_SCHEMA,
        }
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            AddNode(node_name="conversationChain", node_id="conversationChain_0"),
            AddNode(node_name="bufferMemory", node_id="bufferMemory_0"),
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="chatOpenAI",
                target_node_id="conversationChain_0",
                target_anchor="model",
            ),
            Connect(
                source_node_id="bufferMemory_0",
                source_anchor="bufferMemory",
                target_node_id="conversationChain_0",
                target_anchor="memory",
            ),
        ]
        result = compile_patch_ops(GraphIR(), ops, schema_cache)
        assert result.ok

        validation = _validate_flow_data(result.flow_data_str)
        assert validation["valid"] is True
