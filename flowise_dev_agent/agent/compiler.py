"""Deterministic Flowise flowData compiler.

Takes a base GraphIR (snapshot of existing chatflow) + a list of PatchOp objects
and produces a CompileResult with:
  flow_data:      dict (ready to serialize and pass to Flowise API)
  flow_data_str:  JSON string (exact payload to write)
  payload_hash:   SHA-256 of flow_data_str (used by WriteGuard)
  diff_summary:   human-readable summary of what changed
  errors:         list of strings (empty = success)

The compiler is deterministic: given the same inputs it always produces the
same output. The LLM NEVER writes handle IDs or edge IDs — those are derived
from node schemas and node IDs here.

Canonical flowData format:
  {
    "nodes": [
      {
        "id": "chatOpenAI_0",
        "position": {"x": 100, "y": 100},
        "type": "customNode",
        "data": {
          "id": "chatOpenAI_0",
          "label": "ChatOpenAI",
          "name": "chatOpenAI",
          "type": "ChatOpenAI",
          "baseClasses": [...],
          "inputAnchors": [...],
          "inputParams": [...],
          "outputAnchors": [...],
          "outputs": {},
          "inputs": {"modelName": "gpt-4o", ...},
          "selected": false
        },
        ...
      }
    ],
    "edges": [
      {
        "source": "chatOpenAI_0",
        "sourceHandle": "chatOpenAI_0-output-chatOpenAI-BaseChatModel|...",
        "target": "conversationChain_0",
        "targetHandle": "conversationChain_0-input-model-BaseChatModel",
        "type": "buttonedge",
        "id": "chatOpenAI_0-chatOpenAI-conversationChain_0-BaseChatModel"
      }
    ]
  }

See DESIGN_DECISIONS.md — DD-051, DD-052.
See roadmap3_architecture_optimization.md — Milestone 2.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from flowise_dev_agent.agent.patch_ir import (
    AddNode,
    BindCredential,
    Connect,
    PatchOp,
    SetParam,
)

logger = logging.getLogger("flowise_dev_agent.agent.compiler")

# Auto-layout grid constants (pixels)
_GRID_X: int = 300
_GRID_Y: int = 200
_START_X: int = 100
_START_Y: int = 100


# ---------------------------------------------------------------------------
# Canonical Graph IR
# ---------------------------------------------------------------------------


@dataclass
class GraphNode:
    """A node in the Canonical Graph IR.

    id:        Unique node ID in the flow (e.g. "chatOpenAI_0").
    node_name: Flowise node type name (e.g. "chatOpenAI").
    label:     Display label.
    position:  {x, y} pixel coordinates for the canvas.
    data:      Full Flowise node data object (inputAnchors, inputParams, etc.).
    """

    id: str
    node_name: str
    label: str
    position: dict[str, float]
    data: dict[str, Any]


@dataclass
class GraphEdge:
    """An edge in the Canonical Graph IR.

    id:            Deterministic edge ID: "{src}-{src_anchor}-{tgt}-{tgt_anchor}"
    source:        Source node ID.
    target:        Target node ID.
    source_handle: Full Flowise sourceHandle string (output anchor ID).
    target_handle: Full Flowise targetHandle string (input anchor ID).
    type:          Edge render type (always "buttonedge" for Flowise).
    """

    id: str
    source: str
    target: str
    source_handle: str
    target_handle: str
    type: str = "buttonedge"


@dataclass
class GraphIR:
    """Canonical representation of a Flowise chatflow.

    Constructed either from raw Flowise flowData (via from_flow_data()) or
    incrementally by the compiler when applying PatchOps.
    """

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def node_ids(self) -> set[str]:
        """Return the set of all node IDs currently in the graph."""
        return {n.id for n in self.nodes}

    def get_node(self, node_id: str) -> GraphNode | None:
        """Find a node by ID. Returns None if not found."""
        return next((n for n in self.nodes if n.id == node_id), None)

    def to_flow_data(self) -> dict[str, Any]:
        """Convert to the Flowise flowData dict format for API writes."""
        return {
            "nodes": [_graph_node_to_flowise(n) for n in self.nodes],
            "edges": [_graph_edge_to_flowise(e) for e in self.edges],
        }

    def to_flow_data_str(self) -> str:
        """Serialize to a compact JSON string (no whitespace)."""
        return json.dumps(self.to_flow_data(), separators=(",", ":"))

    @classmethod
    def from_flow_data(cls, flow_data: dict[str, Any] | str) -> "GraphIR":
        """Parse raw Flowise flowData into a GraphIR.

        Tolerates missing keys and malformed JSON (returns empty GraphIR on error).
        """
        if isinstance(flow_data, str):
            if not flow_data.strip():
                return cls()
            try:
                flow_data = json.loads(flow_data)
            except json.JSONDecodeError:
                return cls()

        nodes: list[GraphNode] = []
        for raw_node in flow_data.get("nodes", []) or []:
            nodes.append(GraphNode(
                id=raw_node.get("id", ""),
                node_name=raw_node.get("data", {}).get("name", ""),
                label=raw_node.get("data", {}).get("label", ""),
                position=raw_node.get("position") or {"x": _START_X, "y": _START_Y},
                data=copy.deepcopy(raw_node.get("data") or {}),
            ))

        edges: list[GraphEdge] = []
        for raw_edge in flow_data.get("edges", []) or []:
            edges.append(GraphEdge(
                id=raw_edge.get("id", ""),
                source=raw_edge.get("source", ""),
                target=raw_edge.get("target", ""),
                source_handle=raw_edge.get("sourceHandle", ""),
                target_handle=raw_edge.get("targetHandle", ""),
                type=raw_edge.get("type", "buttonedge"),
            ))

        return cls(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# CompileResult
# ---------------------------------------------------------------------------


@dataclass
class CompileResult:
    """Result of compiling PatchOps against a base GraphIR.

    flow_data:      Final graph in Flowise API dict format.
    flow_data_str:  Compact JSON string of flow_data (no extra whitespace).
                    This is the exact string passed to create_chatflow / update_chatflow.
    payload_hash:   SHA-256 hex digest of flow_data_str.
                    WriteGuard requires this hash to authorize the write.
    diff_summary:   Human-readable summary of changes (NODES ADDED / EDGES ADDED, etc.).
    errors:         Compilation errors. Empty list = success (use .ok property).
    """

    flow_data: dict[str, Any]
    flow_data_str: str
    payload_hash: str
    diff_summary: str
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when compilation succeeded (no errors)."""
        return not self.errors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _auto_position(index: int, existing_nodes: list[GraphNode]) -> dict[str, float]:
    """Compute a grid position for the (index)th new node.

    Places new nodes to the right of the rightmost existing node, then wraps
    to a new row every 4 columns. Returns a deterministic {x, y} dict.
    """
    if existing_nodes:
        max_x = max(
            (n.position.get("x", _START_X) for n in existing_nodes),
            default=float(_START_X),
        )
        base_y = min(
            (n.position.get("y", _START_Y) for n in existing_nodes),
            default=float(_START_Y),
        )
    else:
        max_x = float(_START_X - _GRID_X)
        base_y = float(_START_Y)

    col = index % 4
    row = index // 4
    return {
        "x": max_x + _GRID_X * (col + 1),
        "y": base_y + _GRID_Y * row,
    }


def _resolve_anchor_id(
    schema: dict[str, Any],
    node_id: str,
    anchor_name: str,
    direction: str,
) -> str | None:
    """Resolve the full anchor ID for a given anchor name in a processed node schema.

    direction: "output" → searches outputAnchors
               "input"  → searches inputAnchors

    Replaces the {nodeId} placeholder with the actual node_id.
    Returns None if the anchor is not found.
    """
    if direction == "output":
        anchors = schema.get("outputAnchors") or []
    else:
        anchors = schema.get("inputAnchors") or []

    for anchor in anchors:
        anchor_anchor_name = anchor.get("name", "")
        if (
            anchor_anchor_name == anchor_name
            or anchor_anchor_name.lower() == anchor_name.lower()
        ):
            anchor_id = anchor.get("id", "")
            return anchor_id.replace("{nodeId}", node_id)

    return None


def _build_node_data(
    node_name: str,
    node_id: str,
    label: str,
    schema: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Build a Flowise node data object from schema + caller-provided params.

    Replaces all {nodeId} placeholders with the actual node_id throughout
    inputAnchors, inputParams, and outputAnchors.
    """

    def _substitute(obj: Any) -> Any:
        if isinstance(obj, str):
            return obj.replace("{nodeId}", node_id)
        if isinstance(obj, list):
            return [_substitute(item) for item in obj]
        if isinstance(obj, dict):
            return {k: _substitute(v) for k, v in obj.items()}
        return obj

    input_anchors = _substitute(copy.deepcopy(schema.get("inputAnchors") or []))
    input_params = _substitute(copy.deepcopy(schema.get("inputParams") or []))
    output_anchors = _substitute(copy.deepcopy(schema.get("outputAnchors") or []))

    # Build the inputs dict (configurable values)
    inputs: dict[str, Any] = {}
    # Seed with schema defaults
    for param in input_params:
        param_name = param.get("name", "")
        if param_name:
            inputs[param_name] = param.get("default", "")
    # Apply caller-provided params (override defaults)
    inputs.update(params)

    return {
        "id": node_id,
        "label": label or schema.get("label", node_name),
        "version": schema.get("version", 1),
        "name": node_name,
        "type": schema.get("type", node_name),
        "baseClasses": list(schema.get("baseClasses") or []),
        "category": schema.get("category", ""),
        "description": schema.get("description", ""),
        "inputAnchors": input_anchors,
        "inputParams": input_params,
        "outputAnchors": output_anchors,
        "outputs": {},
        "inputs": inputs,
        "selected": False,
    }


def _graph_node_to_flowise(node: GraphNode) -> dict[str, Any]:
    """Serialize a GraphNode to the Flowise flowData node JSON format."""
    return {
        "id": node.id,
        "position": node.position,
        "type": "customNode",
        "data": node.data,
        "width": 300,
        "height": 500,
        "selected": False,
        "positionAbsolute": node.position,
        "dragging": False,
    }


def _graph_edge_to_flowise(edge: GraphEdge) -> dict[str, Any]:
    """Serialize a GraphEdge to the Flowise flowData edge JSON format."""
    return {
        "source": edge.source,
        "sourceHandle": edge.source_handle,
        "target": edge.target,
        "targetHandle": edge.target_handle,
        "type": edge.type,
        "id": edge.id,
    }


# ---------------------------------------------------------------------------
# Deterministic compiler
# ---------------------------------------------------------------------------


def compile_patch_ops(
    base_graph: GraphIR,
    ops: list[PatchOp],
    schema_cache: dict[str, dict[str, Any]],
) -> CompileResult:
    """Apply Patch IR ops to base_graph, return compiled flowData + hash + diff.

    Parameters
    ----------
    base_graph:    The current graph state. For new chatflows, pass GraphIR().
    ops:           Ordered list of PatchOp to apply (AddNode first, then others).
    schema_cache:  {node_name → _get_node_processed() result}
                   Required for AddNode ops. Missing schema → compilation error.

    Returns
    -------
    CompileResult with:
      - flow_data / flow_data_str: the final compiled Flowise flowData
      - payload_hash: SHA-256 of flow_data_str (for WriteGuard)
      - diff_summary: human-readable change log
      - errors: non-empty when compilation encountered unresolvable problems

    Rules
    -----
    - Node IDs come from the ops (LLM chooses them, must be unique).
    - Anchor IDs are derived deterministically from schema or existing node data.
    - Edge IDs: "{src_node_id}-{src_anchor}-{tgt_node_id}-{tgt_anchor}" (stable).
    - Position: respected if provided in op.position; auto-placed otherwise.
    - LLM NEVER writes handle strings — only anchor names.
    """
    errors: list[str] = []
    graph = copy.deepcopy(base_graph)
    diff_lines: list[str] = []
    new_node_count: int = 0

    def _get_schema_for_node(node_id: str, node_name: str) -> dict[str, Any]:
        """Try schema_cache first, then fall back to existing node's data."""
        if node_name in schema_cache:
            return schema_cache[node_name]
        existing = graph.get_node(node_id)
        if existing:
            return existing.data
        return {}

    for op in ops:

        # ------------------------------------------------------------------
        # AddNode
        # ------------------------------------------------------------------
        if isinstance(op, AddNode):
            schema = schema_cache.get(op.node_name)
            if schema is None:
                errors.append(
                    f"AddNode '{op.node_id}': no schema for '{op.node_name}' in schema_cache. "
                    "Ensure get_node(name) was called for this node type during Discover."
                )
                continue

            pos = op.position or _auto_position(new_node_count, list(graph.nodes))
            data = _build_node_data(
                op.node_name, op.node_id,
                op.label or "",
                schema, op.params,
            )
            graph.nodes.append(GraphNode(
                id=op.node_id,
                node_name=op.node_name,
                label=data["label"],
                position=pos,
                data=data,
            ))
            new_node_count += 1
            diff_lines.append(
                f'NODES ADDED: [{op.node_id}] label="{data["label"]}" name="{op.node_name}"'
            )

        # ------------------------------------------------------------------
        # SetParam
        # ------------------------------------------------------------------
        elif isinstance(op, SetParam):
            node = graph.get_node(op.node_id)
            if node is None:
                errors.append(f"SetParam: node_id '{op.node_id}' not found in graph")
                continue
            node.data.setdefault("inputs", {})[op.param_name] = op.value
            diff_lines.append(
                f'NODES MODIFIED: [{op.node_id}] '
                f'field="{op.param_name}" value="{str(op.value)[:80]}"'
            )

        # ------------------------------------------------------------------
        # Connect
        # ------------------------------------------------------------------
        elif isinstance(op, Connect):
            src_node = graph.get_node(op.source_node_id)
            tgt_node = graph.get_node(op.target_node_id)

            if src_node is None:
                errors.append(
                    f"Connect: source_node_id '{op.source_node_id}' not found in graph"
                )
                continue
            if tgt_node is None:
                errors.append(
                    f"Connect: target_node_id '{op.target_node_id}' not found in graph"
                )
                continue

            src_schema = _get_schema_for_node(op.source_node_id, src_node.node_name)
            src_handle = _resolve_anchor_id(
                src_schema, op.source_node_id, op.source_anchor, "output"
            )
            if src_handle is None:
                # Graceful fallback: construct handle from convention
                src_handle = (
                    f"{op.source_node_id}-output-{op.source_anchor}-{op.source_anchor}"
                )
                logger.warning(
                    "Could not resolve output anchor '%s' on node '%s' (schema missing "
                    "or anchor not found); using fallback handle '%s'",
                    op.source_anchor, op.source_node_id, src_handle,
                )

            tgt_schema = _get_schema_for_node(op.target_node_id, tgt_node.node_name)
            tgt_handle = _resolve_anchor_id(
                tgt_schema, op.target_node_id, op.target_anchor, "input"
            )
            if tgt_handle is None:
                tgt_handle = (
                    f"{op.target_node_id}-input-{op.target_anchor}-{op.target_anchor}"
                )
                logger.warning(
                    "Could not resolve input anchor '%s' on node '%s'; "
                    "using fallback handle '%s'",
                    op.target_anchor, op.target_node_id, tgt_handle,
                )

            # Deterministic edge ID — stable across compiler runs
            edge_id = (
                f"{op.source_node_id}-{op.source_anchor}"
                f"-{op.target_node_id}-{op.target_anchor}"
            )
            graph.edges.append(GraphEdge(
                id=edge_id,
                source=op.source_node_id,
                target=op.target_node_id,
                source_handle=src_handle,
                target_handle=tgt_handle,
            ))
            diff_lines.append(
                f"EDGES ADDED: {op.source_node_id}\u2192{op.target_node_id}"
                f"({op.source_anchor}\u2192{op.target_anchor})"
            )

        # ------------------------------------------------------------------
        # BindCredential
        # ------------------------------------------------------------------
        elif isinstance(op, BindCredential):
            node = graph.get_node(op.node_id)
            if node is None:
                errors.append(
                    f"BindCredential: node_id '{op.node_id}' not found in graph"
                )
                continue
            # Set at both required levels (DD-013)
            node.data["credential"] = op.credential_id
            node.data.setdefault("inputs", {})["credential"] = op.credential_id
            ctype_tag = f" [{op.credential_type}]" if op.credential_type else ""
            diff_lines.append(
                f"NODES MODIFIED: [{op.node_id}] credential={op.credential_id}{ctype_tag}"
            )

    # Compile to JSON
    flow_data = graph.to_flow_data()
    flow_data_str = json.dumps(flow_data, separators=(",", ":"))
    payload_hash = hashlib.sha256(flow_data_str.encode("utf-8")).hexdigest()
    diff_summary = "\n".join(diff_lines) if diff_lines else "(no changes)"

    return CompileResult(
        flow_data=flow_data,
        flow_data_str=flow_data_str,
        payload_hash=payload_hash,
        diff_summary=diff_summary,
        errors=errors,
    )
