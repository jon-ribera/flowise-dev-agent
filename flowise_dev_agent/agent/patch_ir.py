"""Patch IR — typed, validated, JSON-serializable operations for Flowise flowData patching.

Each op describes a single atomic change to a chatflow:
  AddNode        — add a new node of a given Flowise node type
  SetParam       — set a configurable input parameter on an existing node
  Connect        — connect two nodes via named anchors
  BindCredential — bind a credential ID to a node (both data.credential levels)

The LLM produces a list of these ops as JSON.  The deterministic compiler in
compiler.py translates them into the final flowData payload.

The LLM NEVER writes handle IDs or edge IDs — those are computed by the
compiler from node schemas and node IDs.

See DESIGN_DECISIONS.md — DD-051.
See roadmap3_architecture_optimization.md — Milestone 2.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any, Union


# ---------------------------------------------------------------------------
# Patch IR operation types
# ---------------------------------------------------------------------------


@dataclass
class AddNode:
    """Add a new node of type `node_name` with ID `node_id` to the flow.

    node_name:  Flowise node type name (e.g. "chatOpenAI", "conversationChain").
                Must exist in the Flowise node registry. The compiler calls
                get_node(node_name) to resolve the full schema.
    node_id:    Unique ID for this node within the flow.
                Convention: "<node_name>_<index>" e.g. "chatOpenAI_0".
    label:      Optional display label. Defaults to schema label when None.
    position:   Optional {x, y} layout hint in pixels.  Auto-placed when None.
    params:     Key → value dict of inputParams to set (data.inputs).
                Only include params you want to set; others keep schema defaults.
    """

    op_type: str = "add_node"
    node_name: str = ""
    node_id: str = ""
    label: str | None = None
    position: dict[str, float] | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class SetParam:
    """Set a single configurable input parameter on an existing node.

    node_id:    ID of the node to modify (must already exist in the graph).
    param_name: Key in data.inputs (e.g. "modelName", "temperature", "systemMessage").
    value:      New value to assign.
    """

    op_type: str = "set_param"
    node_id: str = ""
    param_name: str = ""
    value: Any = None


@dataclass
class Connect:
    """Connect two nodes by their canonical anchor names.

    The compiler resolves the actual handle IDs from node schemas.
    The LLM MUST call get_anchor_dictionary(node_type) to obtain the exact
    anchor name before emitting Connect ops.

    source_node_id:  ID of the node providing the output.
    source_anchor:   Canonical NAME from the output anchor dictionary
                     (e.g. "chatOpenAI", "conversationChain").
                     Usually the node_name itself for single-output nodes.
    target_node_id:  ID of the node receiving the input.
    target_anchor:   Canonical NAME from the input anchor dictionary
                     (e.g. "memory", "model", "tools").

    DEPRECATED: Using type names (e.g. "BaseChatModel", "BaseMemory") as
    anchor values still works via a fuzzy fallback in the compiler, but
    emits a deprecation warning and increments fuzzy_fallbacks metrics.
    New sessions should always use canonical names from the anchor dictionary.
    """

    op_type: str = "connect"
    source_node_id: str = ""
    source_anchor: str = ""
    target_node_id: str = ""
    target_anchor: str = ""


@dataclass
class BindCredential:
    """Bind a Flowise credential to a node at both required levels.

    Sets both:
      node.data.credential        = credential_id
      node.data.inputs.credential = credential_id

    Both must be set for credential-bearing nodes (DD-013 / PATCH RULE #3).
    Missing either level causes "OPENAI_API_KEY environment variable is missing"
    at runtime even when the credential exists in Flowise.

    node_id:         ID of the node to bind the credential to.
    credential_id:   The Flowise credential UUID (from list_credentials).
    credential_type: Optional documentation string (e.g. "openAIApi").
                     Not used by the compiler; included for human readability.
    """

    op_type: str = "bind_credential"
    node_id: str = ""
    credential_id: str = ""
    credential_type: str | None = None


# Union type for all Patch IR ops
PatchOp = Union[AddNode, SetParam, Connect, BindCredential]

# Discriminator map: op_type string → dataclass
_OP_TYPE_MAP: dict[str, type] = {
    "add_node": AddNode,
    "set_param": SetParam,
    "connect": Connect,
    "bind_credential": BindCredential,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class PatchIRValidationError(Exception):
    """Raised when Patch IR operations fail structural validation.

    errors: list of human-readable error strings, one per problem found.
    """

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def validate_patch_ops(
    ops: list[PatchOp],
    base_node_ids: set[str] | None = None,
    anchor_store=None,
    node_type_map: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Validate a list of Patch IR ops. Returns (errors, warnings).

    Checks performed:
    - Required string fields are non-empty
    - No duplicate node_ids across AddNode ops in the same ops list
    - Connect / SetParam / BindCredential reference node_ids that exist in either
      `base_node_ids` (nodes already in the graph) or declared by an AddNode in this list
    - (Optional) Anchor name validation when anchor_store and node_type_map provided

    base_node_ids: optional set of existing node IDs in the base graph.
                   When None, only cross-op references are validated.
    anchor_store:  optional AnchorDictionaryStore. When provided along with
                   node_type_map, Connect anchors are validated against canonical
                   anchor dictionaries. compatible_types are advisory only — never
                   a hard gate.
    node_type_map: optional {node_id → node_type} mapping. Built from base graph
                   nodes + AddNode ops. Required for anchor validation.
    """
    errors: list[str] = []
    warnings: list[str] = []
    seen_add_ids: set[str] = set()
    known_ids: set[str] = set(base_node_ids or set())

    # Build node_type_map from AddNode ops
    _add_node_types: dict[str, str] = {}

    # Pass 1: collect AddNode IDs (they must come before references in ops list
    # logically, but we allow any order by pre-scanning first).
    for i, op in enumerate(ops):
        if isinstance(op, AddNode):
            if not op.node_name:
                errors.append(f"ops[{i}] AddNode: node_name is required")
            if not op.node_id:
                errors.append(f"ops[{i}] AddNode: node_id is required")
            elif op.node_id in seen_add_ids:
                errors.append(f"ops[{i}] AddNode: duplicate node_id '{op.node_id}'")
            else:
                seen_add_ids.add(op.node_id)
                known_ids.add(op.node_id)
                _add_node_types[op.node_id] = op.node_name

    # Union node_type_map: caller's map + AddNode ops
    _effective_type_map: dict[str, str] = {}
    if node_type_map:
        _effective_type_map.update(node_type_map)
    _effective_type_map.update(_add_node_types)

    # Pass 2: validate references in non-AddNode ops
    for i, op in enumerate(ops):
        if isinstance(op, SetParam):
            if not op.node_id:
                errors.append(f"ops[{i}] SetParam: node_id is required")
            elif op.node_id not in known_ids:
                errors.append(
                    f"ops[{i}] SetParam: node_id '{op.node_id}' not found "
                    "in base graph or AddNode ops"
                )
            if not op.param_name:
                errors.append(f"ops[{i}] SetParam: param_name is required")

        elif isinstance(op, Connect):
            if not op.source_node_id:
                errors.append(f"ops[{i}] Connect: source_node_id is required")
            elif op.source_node_id not in known_ids:
                errors.append(
                    f"ops[{i}] Connect: source_node_id '{op.source_node_id}' not found "
                    "in base graph or AddNode ops"
                )
            if not op.target_node_id:
                errors.append(f"ops[{i}] Connect: target_node_id is required")
            elif op.target_node_id not in known_ids:
                errors.append(
                    f"ops[{i}] Connect: target_node_id '{op.target_node_id}' not found "
                    "in base graph or AddNode ops"
                )
            if not op.source_anchor:
                errors.append(f"ops[{i}] Connect: source_anchor is required")
            if not op.target_anchor:
                errors.append(f"ops[{i}] Connect: target_anchor is required")

            # Anchor name validation (advisory — warnings only)
            if anchor_store is not None:
                _validate_connect_anchors(
                    i, op, _effective_type_map, anchor_store, warnings,
                )

        elif isinstance(op, BindCredential):
            if not op.node_id:
                errors.append(f"ops[{i}] BindCredential: node_id is required")
            elif op.node_id not in known_ids:
                errors.append(
                    f"ops[{i}] BindCredential: node_id '{op.node_id}' not found "
                    "in base graph or AddNode ops"
                )
            if not op.credential_id:
                errors.append(f"ops[{i}] BindCredential: credential_id is required")

    return errors, warnings


def _validate_connect_anchors(
    op_idx: int,
    op: Connect,
    type_map: dict[str, str],
    anchor_store,
    warnings: list[str],
) -> None:
    """Validate Connect anchor names and type compatibility against canonical
    anchor dictionaries.

    Adds warnings (never errors) for:
    - Unknown anchor names (so the compiler can still attempt fuzzy fallback)
    - Type-incompatible connections (source output types ∩ target input types = ∅)
    """
    # Source anchor validation
    src_node_type = type_map.get(op.source_node_id)
    src_anchor_entry: dict[str, Any] | None = None
    if src_node_type is None:
        warnings.append(
            f"ops[{op_idx}] Connect: no node_type mapping for source '{op.source_node_id}'"
        )
    else:
        src_dict = anchor_store.get(src_node_type)
        if src_dict is not None:
            output_anchors = src_dict.get("output_anchors", [])
            output_names = [a["name"] for a in output_anchors]
            if op.source_anchor not in output_names:
                warnings.append(
                    f"ops[{op_idx}] Connect: source_anchor '{op.source_anchor}' "
                    f"not found in {src_node_type} output anchors. "
                    f"Valid options: {output_names}"
                )
            else:
                src_anchor_entry = next(
                    (a for a in output_anchors if a["name"] == op.source_anchor),
                    None,
                )

    # Target anchor validation
    tgt_node_type = type_map.get(op.target_node_id)
    tgt_anchor_entry: dict[str, Any] | None = None
    if tgt_node_type is None:
        warnings.append(
            f"ops[{op_idx}] Connect: no node_type mapping for target '{op.target_node_id}'"
        )
    else:
        tgt_dict = anchor_store.get(tgt_node_type)
        if tgt_dict is not None:
            input_anchors = tgt_dict.get("input_anchors", [])
            input_names = [a["name"] for a in input_anchors]
            if op.target_anchor not in input_names:
                warnings.append(
                    f"ops[{op_idx}] Connect: target_anchor '{op.target_anchor}' "
                    f"not found in {tgt_node_type} input anchors. "
                    f"Valid options: {input_names}"
                )
            else:
                tgt_anchor_entry = next(
                    (a for a in input_anchors if a["name"] == op.target_anchor),
                    None,
                )

    # Type compatibility check (M10.6 — DD-102)
    if src_anchor_entry is not None and tgt_anchor_entry is not None:
        src_type_str = src_anchor_entry.get("type", "")
        tgt_type_str = tgt_anchor_entry.get("type", "")
        if src_type_str and tgt_type_str:
            src_types = {t.strip() for t in src_type_str.split("|") if t.strip()}
            tgt_types = {t.strip() for t in tgt_type_str.split("|") if t.strip()}
            if src_types and tgt_types and not src_types & tgt_types:
                warnings.append(
                    f"ops[{op_idx}] Connect: type mismatch — "
                    f"{op.source_node_id}.{op.source_anchor} outputs "
                    f"'{src_type_str}' but {op.target_node_id}.{op.target_anchor} "
                    f"expects '{tgt_type_str}'"
                )


# ---------------------------------------------------------------------------
# JSON serialization / deserialization
# ---------------------------------------------------------------------------


def op_to_dict(op: PatchOp) -> dict[str, Any]:
    """Serialize a single PatchOp to a JSON-safe dict."""
    return dataclasses.asdict(op)


def op_from_dict(d: dict[str, Any]) -> PatchOp:
    """Deserialize a dict to a typed PatchOp.

    Raises ValueError for unknown op_type.
    Unknown keys are silently dropped (forward-compatibility).
    """
    op_type = d.get("op_type")
    cls = _OP_TYPE_MAP.get(op_type)  # type: ignore[arg-type]
    if cls is None:
        raise ValueError(
            f"Unknown op_type: {op_type!r}. Valid types: {list(_OP_TYPE_MAP)}"
        )
    valid_fields = {f.name for f in dataclasses.fields(cls)}
    filtered = {k: v for k, v in d.items() if k in valid_fields}
    return cls(**filtered)


def ops_to_json(ops: list[PatchOp]) -> str:
    """Serialize a list of PatchOp objects to a pretty-printed JSON string."""
    return json.dumps([op_to_dict(op) for op in ops], indent=2)


def ops_from_json(s: str) -> list[PatchOp]:
    """Deserialize a JSON string (or code-fenced block) to a list of PatchOp objects.

    Tolerates LLM output that wraps the JSON array in ```json...``` fences.
    Raises ValueError if the string is not a valid JSON array or contains
    unknown op_type values.
    """
    # Strip optional ```json...``` fencing from LLM output
    stripped = s.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Drop first line (```json or ```) and last line (```)
        inner = "\n".join(lines[1:] if lines[-1].strip() == "```" else lines[1:])
        # Remove trailing ``` if present
        if inner.rstrip().endswith("```"):
            inner = inner.rstrip()[:-3].rstrip()
        stripped = inner.strip()

    raw_list = json.loads(stripped)
    if not isinstance(raw_list, list):
        raise ValueError(
            f"Expected a JSON array of ops, got {type(raw_list).__name__}"
        )
    return [op_from_dict(item) for item in raw_list]
