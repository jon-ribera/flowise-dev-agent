"""M11.2 — Anchor field preservation tests (DD-106).

Tests:
- Input anchors preserve 'list' field when present in raw schema
- Output anchors preserve 'description' when present
- Anchors survive normalization and compilation
"""

from __future__ import annotations

import copy

import pytest

from flowise_dev_agent.agent.compiler import (
    AddNode,
    GraphIR,
    _build_node_data,
    compile_patch_ops,
)
from flowise_dev_agent.knowledge.provider import _normalize_api_schema


# ---------------------------------------------------------------------------
# Normalization: anchor field preservation
# ---------------------------------------------------------------------------


class TestAnchorFieldPreservation:
    def test_input_anchor_preserves_list_field(self):
        """Input anchors with list=True must preserve the field through normalization."""
        raw = {
            "name": "toolAgent",
            "baseClasses": ["AgentExecutor"],
            "inputs": [
                {
                    "name": "tools",
                    "type": "Tool",
                    "label": "Tools",
                    "list": True,
                    "description": "List of tools the agent can use",
                },
            ],
        }
        schema = _normalize_api_schema(raw)

        # "tools" is not a primitive type → goes to inputAnchors
        assert len(schema["inputAnchors"]) == 1
        anchor = schema["inputAnchors"][0]
        assert anchor["list"] is True
        assert anchor["name"] == "tools"
        assert anchor["description"] == "List of tools the agent can use"

    def test_input_anchor_without_list_field(self):
        """Anchors without list field should not have it injected."""
        raw = {
            "name": "conversationChain",
            "baseClasses": ["ConversationChain"],
            "inputs": [
                {"name": "model", "type": "BaseChatModel", "label": "Model"},
            ],
        }
        schema = _normalize_api_schema(raw)
        anchor = schema["inputAnchors"][0]
        assert "list" not in anchor

    def test_output_anchor_preserves_description(self):
        """Output anchors with description must preserve it."""
        raw = {
            "name": "memoryVectorStore",
            "baseClasses": ["VectorStore"],
            "inputs": [],
            "outputAnchors": [
                {
                    "id": "{nodeId}-output-retriever-BaseRetriever",
                    "name": "retriever",
                    "type": "BaseRetriever",
                    "label": "Retriever",
                    "description": "Retriever interface for vector lookups",
                },
            ],
        }
        schema = _normalize_api_schema(raw)
        oa = schema["outputAnchors"][0]
        assert oa["description"] == "Retriever interface for vector lookups"

    def test_input_param_preserves_all_fields(self):
        """inputParams should preserve every field from the raw input."""
        raw = {
            "name": "chatOpenAI",
            "baseClasses": ["BaseChatModel"],
            "inputs": [
                {
                    "name": "temperature",
                    "type": "number",
                    "label": "Temperature",
                    "step": 0.1,
                    "default": "0.9",
                    "optional": True,
                    "additionalParams": True,
                    "show": True,
                    "description": "Controls randomness",
                    "rows": 1,
                },
            ],
        }
        schema = _normalize_api_schema(raw)
        param = schema["inputParams"][0]
        assert param["step"] == 0.1
        assert param["optional"] is True
        assert param["additionalParams"] is True
        assert param["show"] is True
        assert param["rows"] == 1
        assert param["description"] == "Controls randomness"


# ---------------------------------------------------------------------------
# Compilation: anchors survive _build_node_data
# ---------------------------------------------------------------------------


class TestAnchorsInCompilation:
    def test_list_field_survives_build_node_data(self):
        """list field on inputAnchors survives _build_node_data compilation."""
        schema = {
            "name": "toolAgent",
            "label": "Tool Agent",
            "baseClasses": ["AgentExecutor"],
            "inputAnchors": [
                {
                    "name": "tools",
                    "type": "Tool",
                    "label": "Tools",
                    "list": True,
                    "id": "{nodeId}-input-tools-Tool",
                },
            ],
            "inputParams": [],
            "outputAnchors": [
                {"id": "{nodeId}-output-toolAgent-AgentExecutor", "name": "toolAgent", "type": "AgentExecutor"},
            ],
        }
        data = _build_node_data("toolAgent", "toolAgent_0", "Tool Agent", schema, {})

        anchor = data["inputAnchors"][0]
        assert anchor["list"] is True
        assert anchor["id"] == "toolAgent_0-input-tools-Tool"

    def test_anchors_survive_compile_patch_ops(self):
        """Anchor fields should survive the full compile_patch_ops pipeline."""
        schema = {
            "name": "toolAgent",
            "label": "Tool Agent",
            "baseClasses": ["AgentExecutor"],
            "inputAnchors": [
                {
                    "name": "tools",
                    "type": "Tool",
                    "label": "Tools",
                    "list": True,
                    "id": "{nodeId}-input-tools-Tool",
                },
            ],
            "inputParams": [
                {"name": "prefix", "type": "string", "id": "{nodeId}-input-prefix-string"},
            ],
            "outputAnchors": [
                {"id": "{nodeId}-output-toolAgent-AgentExecutor", "name": "toolAgent", "type": "AgentExecutor"},
            ],
        }

        result = compile_patch_ops(
            GraphIR(),
            [AddNode(node_name="toolAgent", node_id="toolAgent_0")],
            {"toolAgent": schema},
        )
        assert result.ok

        node_data = result.flow_data["nodes"][0]["data"]
        anchor = node_data["inputAnchors"][0]
        assert anchor["list"] is True
        assert anchor["name"] == "tools"

    def test_node_id_substituted_in_anchors(self):
        """All {nodeId} placeholders should be replaced with actual node ID."""
        schema = {
            "name": "chatOpenAI",
            "label": "ChatOpenAI",
            "baseClasses": ["BaseChatModel"],
            "inputAnchors": [
                {"name": "memory", "type": "BaseMemory", "id": "{nodeId}-input-memory-BaseMemory"},
            ],
            "inputParams": [
                {"name": "model", "type": "string", "id": "{nodeId}-input-model-string"},
            ],
            "outputAnchors": [
                {"id": "{nodeId}-output-chatOpenAI-BaseChatModel", "name": "chatOpenAI", "type": "BaseChatModel"},
            ],
        }

        result = compile_patch_ops(
            GraphIR(),
            [AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0")],
            {"chatOpenAI": schema},
        )
        assert result.ok

        node_data = result.flow_data["nodes"][0]["data"]
        # Input anchor ID should have node ID substituted
        assert node_data["inputAnchors"][0]["id"] == "chatOpenAI_0-input-memory-BaseMemory"
        # Input param ID
        assert node_data["inputParams"][0]["id"] == "chatOpenAI_0-input-model-string"
        # Output anchor (may be wrapped for multi-output, but single-output stays flat)
        assert "chatOpenAI_0" in node_data["outputAnchors"][0].get("id", "")
