"""M11.2 — FlowData viewport and dynamic node height tests (DD-107).

Tests:
- to_flow_data() includes viewport with x, y, zoom
- Node heights vary with param count (not fixed 500)
- Height is clamped between 260 and 900
"""

from __future__ import annotations

import copy

import pytest

from flowise_dev_agent.agent.compiler import (
    AddNode,
    GraphIR,
    GraphNode,
    _compute_node_height,
    compile_patch_ops,
)


# ---------------------------------------------------------------------------
# _compute_node_height tests
# ---------------------------------------------------------------------------

class TestComputeNodeHeight:
    def test_empty_node(self):
        """Node with no params or anchors gets base height."""
        data = {"inputParams": [], "inputAnchors": []}
        assert _compute_node_height(data) == 260

    def test_scales_with_params(self):
        """Height increases with visible param count."""
        data = {
            "inputParams": [
                {"name": f"p{i}", "type": "string"} for i in range(10)
            ],
            "inputAnchors": [],
        }
        height = _compute_node_height(data)
        # 260 + 10 * 22 = 480
        assert height == 480

    def test_scales_with_anchors(self):
        """Height increases with input anchor count."""
        data = {
            "inputParams": [],
            "inputAnchors": [
                {"name": f"a{i}", "type": "SomeType"} for i in range(5)
            ],
        }
        height = _compute_node_height(data)
        # 260 + 5 * 12 = 320
        assert height == 320

    def test_combined_params_and_anchors(self):
        """Both params and anchors contribute."""
        data = {
            "inputParams": [{"name": f"p{i}", "type": "string"} for i in range(10)],
            "inputAnchors": [{"name": f"a{i}", "type": "T"} for i in range(5)],
        }
        height = _compute_node_height(data)
        # 260 + 10*22 + 5*12 = 260 + 220 + 60 = 540
        assert height == 540

    def test_hidden_params_excluded(self):
        """Params with show=False are not counted."""
        data = {
            "inputParams": [
                {"name": "visible", "type": "string"},
                {"name": "hidden", "type": "string", "show": False},
                {"name": "also_visible", "type": "string", "show": True},
            ],
            "inputAnchors": [],
        }
        height = _compute_node_height(data)
        # 260 + 2 * 22 = 304
        assert height == 304

    def test_max_clamp(self):
        """Height is clamped to 900 maximum."""
        data = {
            "inputParams": [{"name": f"p{i}", "type": "string"} for i in range(50)],
            "inputAnchors": [],
        }
        height = _compute_node_height(data)
        # 260 + 50*22 = 1360 → clamped to 900
        assert height == 900

    def test_min_clamp(self):
        """Height never goes below 260."""
        data = {}
        assert _compute_node_height(data) == 260

    def test_no_fixed_500(self):
        """A typical node should NOT be exactly 500 (the old hardcoded value)."""
        data = {
            "inputParams": [
                {"name": "model", "type": "string"},
                {"name": "temp", "type": "number"},
                {"name": "streaming", "type": "boolean"},
            ],
            "inputAnchors": [
                {"name": "memory", "type": "BaseMemory"},
            ],
        }
        height = _compute_node_height(data)
        # 260 + 3*22 + 1*12 = 338
        assert height != 500
        assert height == 338


# ---------------------------------------------------------------------------
# Viewport tests
# ---------------------------------------------------------------------------

class TestViewport:
    def test_to_flow_data_includes_viewport(self):
        """to_flow_data() must return viewport with x, y, zoom."""
        ir = GraphIR()
        fd = ir.to_flow_data()
        assert "viewport" in fd
        assert fd["viewport"]["x"] == 0
        assert fd["viewport"]["y"] == 0
        assert fd["viewport"]["zoom"] == 0.5

    def test_viewport_in_compiled_output(self):
        """compile_patch_ops result includes viewport."""
        schema = {
            "name": "chatOpenAI",
            "label": "ChatOpenAI",
            "baseClasses": ["BaseChatModel"],
            "inputAnchors": [],
            "inputParams": [],
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
        assert "viewport" in result.flow_data
        assert result.flow_data["viewport"]["zoom"] == 0.5


# ---------------------------------------------------------------------------
# Integration: height varies in compiled output
# ---------------------------------------------------------------------------

class TestCompiledHeight:
    def test_compiled_height_varies_with_params(self):
        """Compiled nodes should have different heights based on param count."""
        small_schema = {
            "name": "bufferMemory",
            "label": "Buffer Memory",
            "baseClasses": ["BaseMemory"],
            "inputAnchors": [],
            "inputParams": [
                {"name": "sessionId", "type": "string", "id": "{nodeId}-input-sessionId-string"},
            ],
            "outputAnchors": [
                {"id": "{nodeId}-output-bufferMemory-BaseMemory", "name": "bufferMemory", "type": "BaseMemory"},
            ],
        }
        big_schema = {
            "name": "chatOpenAI",
            "label": "ChatOpenAI",
            "baseClasses": ["BaseChatModel"],
            "inputAnchors": [
                {"name": "memory", "type": "BaseMemory", "id": "{nodeId}-input-memory-BaseMemory"},
            ],
            "inputParams": [
                {"name": f"p{i}", "type": "string", "id": f"{{nodeId}}-input-p{i}-string"}
                for i in range(15)
            ],
            "outputAnchors": [
                {"id": "{nodeId}-output-chatOpenAI-BaseChatModel", "name": "chatOpenAI", "type": "BaseChatModel"},
            ],
        }

        result = compile_patch_ops(
            GraphIR(),
            [
                AddNode(node_name="bufferMemory", node_id="bufferMemory_0"),
                AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            ],
            {"bufferMemory": small_schema, "chatOpenAI": big_schema},
        )
        assert result.ok

        heights = {n["id"]: n["height"] for n in result.flow_data["nodes"]}
        assert heights["bufferMemory_0"] < heights["chatOpenAI_0"]
        # Neither should be 500
        assert heights["bufferMemory_0"] != 500
        assert heights["chatOpenAI_0"] != 500
