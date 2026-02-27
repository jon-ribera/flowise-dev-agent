"""Domain tool plugin system for the Flowise Builder co-pilot.

DomainTools is the plugin interface for adding new tool domains to the agent.
Each domain (Flowise, Workday, etc.) registers:
  - Tool definitions per phase (discover / patch / test)
  - An executor mapping (tool_name → async callable)
  - Optional system prompt additions per phase

The graph merges tools from all registered domains before calling each node,
so the LLM sees all available tools from all domains simultaneously.

Current domains:
  FloviseDomain — wraps FlowiseClient (native MCP, 51 tools)
  PatternDomain — wraps PatternStore (pattern library search)

Planned domains:
  WorkdayDomain — will wrap Workday Agent Gateway MCP client (v2)
  See agent/domains/workday.py for the stub and activation checklist.

Tool results are normalized through the ToolResult envelope. Only the compact
.summary field is injected into LLM context; raw .data is stored in state['debug'].
See DD-048 (ToolResult as single transformation point).

See DESIGN_DECISIONS.md — DD-008, DD-048.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time as _time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from flowise_dev_agent.client import FlowiseClient
from flowise_dev_agent.reasoning import ToolDef

logger = logging.getLogger("flowise_dev_agent.agent.tools")


# ---------------------------------------------------------------------------
# Plugin interface
# ---------------------------------------------------------------------------


@dataclass
class DomainTools:
    """Plugin interface for a tool domain.

    Implement this dataclass to add a new domain (e.g., Workday) to the agent.
    The graph calls _merge_tools() before each phase to combine all domains.

    Fields:
        name:             Domain identifier, e.g. "flowise" or "workday".
        discover:         Read-only tools for the Discover phase.
        patch:            Write tools for the Patch phase.
        test:             Testing/validation tools for the Test phase.
        executor:         Mapping of tool_name → async callable.
                          All three phases share one executor per domain.
        discover_context: Extra text appended to the Discover system prompt.
                          Use to give the LLM domain-specific guidance.
        patch_context:    Extra text appended to the Patch system prompt.
        test_context:     Extra text appended to the Test system prompt.
    """

    name: str
    discover: list[ToolDef] = field(default_factory=list)
    patch: list[ToolDef] = field(default_factory=list)
    test: list[ToolDef] = field(default_factory=list)
    executor: dict[str, Callable[..., Any]] = field(default_factory=dict)

    # Optional per-phase system prompt additions (injected after base prompt)
    discover_context: str = ""
    patch_context: str = ""
    test_context: str = ""


# ---------------------------------------------------------------------------
# Merger
# ---------------------------------------------------------------------------


def merge_tools(
    domains: list[DomainTools],
    phase: str,
) -> tuple[list[ToolDef], dict[str, Callable[..., Any]]]:
    """Merge tool definitions and executors from all domains for a given phase.

    Args:
        domains: All registered DomainTools instances.
        phase:   "discover" | "patch" | "test"

    Returns:
        (merged_tool_defs, merged_executor)
        The merged_executor maps every tool_name across all domains
        to its async callable.
    """
    merged_defs: list[ToolDef] = []
    merged_executor: dict[str, Callable[..., Any]] = {}

    for domain in domains:
        phase_tools: list[ToolDef] = getattr(domain, phase, [])
        merged_defs.extend(phase_tools)
        merged_executor.update(domain.executor)

    return merged_defs, merged_executor


def merge_context(domains: list[DomainTools], phase: str) -> str:
    """Collect all domain-specific system prompt additions for a phase."""
    parts = []
    for domain in domains:
        ctx: str = getattr(domain, f"{phase}_context", "")
        if ctx.strip():
            parts.append(f"--- {domain.name.upper()} CONTEXT ---\n{ctx.strip()}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Flowise domain — wraps FlowiseClient
# ---------------------------------------------------------------------------


class FloviseDomain(DomainTools):
    """Tool domain for the Flowise MCP (native).

    Wraps the FlowiseClient async methods as tool executors and declares
    ToolDef schemas for each phase.

    Context injection priority:
      1. flowise_dev_agent/skills/flowise_builder.md (editable, preferred)
      2. Hardcoded _FLOWISE_*_CONTEXT constants (fallback)

    Usage:
        domain = FloviseDomain(flowise_client)
        graph = build_graph(engine, domains=[domain])
    """

    def __init__(self, client: FlowiseClient) -> None:
        from flowise_dev_agent.agent.skills import load_skill
        skill = load_skill("flowise_builder")

        super().__init__(
            name="flowise",
            discover=_FLOWISE_DISCOVER_TOOLS,
            patch=_FLOWISE_PATCH_TOOLS,
            test=_FLOWISE_TEST_TOOLS,
            executor=_make_flowise_executor(client),
            discover_context=skill.discover_context if skill else _FLOWISE_DISCOVER_CONTEXT,
            patch_context=skill.patch_context if skill else _FLOWISE_PATCH_CONTEXT,
            test_context=skill.test_context if skill else _FLOWISE_TEST_CONTEXT,
        )


# ---------------------------------------------------------------------------
# Flowise tool definitions (ToolDef objects with JSON Schema parameters)
# ---------------------------------------------------------------------------


def _td(name: str, description: str, properties: dict[str, Any], required: list[str]) -> ToolDef:
    """Shorthand constructor for ToolDef with a standard JSON Schema wrapper."""
    return ToolDef(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": required,
        },
    )


_FLOWISE_DISCOVER_TOOLS: list[ToolDef] = [
    _td(
        "list_chatflows",
        "List all chatflows in Flowise. Returns id, name, and type for each.",
        {}, [],
    ),
    _td(
        "get_chatflow",
        "Get full details of a chatflow, including its flowData (nodes and edges JSON).",
        {"chatflow_id": {"type": "string", "description": "The chatflow ID to retrieve"}},
        ["chatflow_id"],
    ),
    _td(
        "list_nodes",
        "List all available Flowise node types (name, category, label). 303 nodes across 24 categories.",
        {}, [],
    ),
    _td(
        "get_node",
        (
            "Get the full schema for a specific Flowise node type, pre-processed for flowData. "
            "Returns inputAnchors (node-connection points with {nodeId} placeholder IDs), "
            "inputParams (configurable fields), outputAnchors, and outputs. "
            "DISCOVER PHASE: Do NOT call this — all 303 schemas are pre-loaded locally and the "
            "patch phase resolves them automatically. Only call during discover to verify an "
            "unusual parameter that cannot be inferred from context. "
            "PATCH PHASE: Call freely for any node you are adding — never guess the schema."
        ),
        {"name": {"type": "string", "description": "Node type name, e.g. 'chatOpenAI', 'conversationChain'"}},
        ["name"],
    ),
    _td(
        "list_credentials",
        (
            "List all saved credentials in Flowise (names, types, IDs). "
            "Check this to verify required credentials exist before building."
        ),
        {}, [],
    ),
    _td(
        "list_marketplace_templates",
        (
            "List pre-built Flowise marketplace templates. "
            "Always check here before building from scratch — a template may already exist."
        ),
        {}, [],
    ),
]

_FLOWISE_PATCH_TOOLS: list[ToolDef] = [
    _td(
        "validate_flow_data",
        (
            "Validate flowData structure before create_chatflow or update_chatflow. "
            "Checks: valid JSON, all nodes have inputAnchors/inputParams/outputAnchors/outputs, "
            "all edges reference valid node IDs and anchor handles. "
            "MANDATORY: call this and fix ALL errors before any chatflow write."
        ),
        {"flow_data_str": {"type": "string", "description": "The complete flowData JSON string to validate"}},
        ["flow_data_str"],
    ),
    _td(
        "get_chatflow",
        (
            "Read the current chatflow before making any changes. "
            "MANDATORY: always call this before update_chatflow. Parse flowData to understand the current state."
        ),
        {"chatflow_id": {"type": "string"}},
        ["chatflow_id"],
    ),
    _td(
        "create_chatflow",
        (
            "Create a new chatflow with complete flow_data. "
            "flow_data must be a JSON string with 'nodes' and 'edges' arrays. "
            "Minimum valid flow_data: '{\"nodes\":[],\"edges\":[]}'."
        ),
        {
            "name": {"type": "string", "description": "Display name for the chatflow"},
            "flow_data": {
                "type": "string",
                "description": "Complete flowData as a JSON string. Must include nodes and edges arrays.",
            },
            "description": {"type": "string", "description": "Optional description"},
            "chatflow_type": {
                "type": "string",
                "enum": ["CHATFLOW", "AGENTFLOW"],
                "description": "Use CHATFLOW for standard flows. AGENTFLOW only for sequential/multi-agent.",
                "default": "CHATFLOW",
            },
        },
        ["name", "flow_data"],
    ),
    _td(
        "update_chatflow",
        (
            "Update an existing chatflow. "
            "RULES: (1) Always call get_chatflow first to read the current state. "
            "(2) Print a Change Summary before calling this. "
            "(3) Pass only the fields you want to change. "
            "(4) flow_data must be the COMPLETE updated JSON string — not a diff."
        ),
        {
            "chatflow_id": {"type": "string"},
            "name": {"type": "string"},
            "flow_data": {
                "type": "string",
                "description": "Complete updated flowData JSON string (not a partial diff).",
            },
            "description": {"type": "string"},
            "deployed": {"type": "boolean"},
            "is_public": {"type": "boolean"},
            "category": {"type": "string"},
        },
        ["chatflow_id"],
    ),
    _td(
        "snapshot_chatflow",
        (
            "Save the current chatflow state as a versioned snapshot before making changes. "
            "REQUIRED before every update_chatflow — this enables rollback if the patch breaks the flow. "
            "Use the session thread_id as session_id. "
            "version_label is auto-generated (v1.0, v2.0, …) when omitted."
        ),
        {
            "chatflow_id": {"type": "string"},
            "session_id": {"type": "string", "description": "The session thread_id (used to scope snapshots)"},
            "version_label": {"type": "string", "description": "Optional label (e.g. 'v2.0'). Auto-assigned if omitted."},
        },
        ["chatflow_id", "session_id"],
    ),
    _td(
        "list_credentials",
        "List credential IDs needed for binding to nodes (data.credential and data.inputs.credential).",
        {}, [],
    ),
    _td(
        "get_node",
        (
            "Get a node's schema pre-processed for flowData embedding: inputAnchors, inputParams, "
            "outputAnchors (with {nodeId} placeholder IDs), and outputs. Replace {nodeId} with your "
            "actual node ID before embedding in flowData."
        ),
        {"name": {"type": "string"}},
        ["name"],
    ),
]

_FLOWISE_TEST_TOOLS: list[ToolDef] = [
    _td(
        "create_prediction",
        (
            "Send a test message to a chatflow and get the AI response. "
            "Always use override_config with a unique sessionId to isolate test sessions from production history."
        ),
        {
            "chatflow_id": {"type": "string"},
            "question": {"type": "string", "description": "The test input to send"},
            "override_config": {
                "type": "string",
                "description": (
                    "JSON string with override config. Always include a unique sessionId: "
                    "'{\"sessionId\": \"test-<unique-suffix>\"}'"
                ),
            },
            "history": {
                "type": "string",
                "description": "Optional JSON array of prior messages to inject as context.",
            },
        },
        ["chatflow_id", "question"],
    ),
    _td(
        "get_chatflow",
        "Verify the chatflow exists and is saved before testing.",
        {"chatflow_id": {"type": "string"}},
        ["chatflow_id"],
    ),
    _td(
        "upsert_vector",
        (
            "Load documents into the vector store for RAG chatflows. "
            "REQUIRED before testing any RAG flow — the vector store is empty until upserted. "
            "Call this after creating or modifying a RAG chatflow and before running create_prediction."
        ),
        {"chatflow_id": {"type": "string"}},
        ["chatflow_id"],
    ),
]

# ---------------------------------------------------------------------------
# Flowise domain-specific system prompt additions
# ---------------------------------------------------------------------------

_FLOWISE_DISCOVER_CONTEXT = """
FLOWISE-SPECIFIC DISCOVERY RULES (M9.3 — knowledge-first):
- Call list_chatflows first to find existing flows relevant to the requirement.
- For any candidate chatflow, call get_chatflow to read its flowData (nodes, edges, prompts).
- Do NOT call get_node during discover — all 303 node schemas are pre-loaded locally and the
  patch phase resolves them automatically for every node in the approved plan. Calling get_node
  here wastes tokens and provides no accuracy benefit over the local snapshot.
- Call list_credentials to verify the credentials needed by your planned nodes already exist.
- Call list_marketplace_templates and check if a pre-built template covers the requirement.
- Pay special attention to:
  - data.credential vs data.inputs.credential (both must be set for credential-bearing nodes)
  - Edge handle format: {nodeId}-{direction}-{paramName}-{baseClasses joined by |}
  - Node categories: Sequential Agents / Agent Flows / Multi Agents are AgentFlow-only —
    do NOT use them in Chatflows.
"""

_FLOWISE_PATCH_CONTEXT = """
FLOWISE-SPECIFIC PATCH RULES (non-negotiable):
1. READ BEFORE WRITE — call get_chatflow and parse flowData before any update.
2. ONE CHANGE PER ITERATION — one node addition, one prompt edit, or one edge rewire.
3. CREDENTIAL BINDING at both levels:
     data.credential = "<credential_id>"
     data.inputs.credential = "<credential_id>"
   Failure here causes "OPENAI_API_KEY environment variable is missing" at runtime.
4. MINIMUM flow_data: {"nodes":[],"edges":[]} — never bare {}.
5. PRESERVE existing node IDs and edge IDs unless explicitly adding new nodes.
6. CHANGE SUMMARY before update_chatflow:
   - Nodes added/removed/modified (use node.id as key)
   - Edges added/removed (source→target(type))
   - Prompts changed (field name, before/after first 200 chars)
7. New node labels: short, readable, no special characters.

COMMON ERROR TABLE:
| Error | Cause | Fix |
|---|---|---|
| nodes is not iterable (500) | flow_data was {} | Use {"nodes":[],"edges":[]} |
| NOT NULL constraint failed: tool.color | Missing color on custom tool | Add "color": "#4CAF50" |
| OPENAI_API_KEY missing | Credential only at inputs.credential | Set at BOTH data.credential AND data.inputs.credential |
| Ending node must be Chain or Agent | No terminating node | Add a Chain or Agent as the last node |
"""

_FLOWISE_TEST_CONTEXT = """
FLOWISE-SPECIFIC TEST RULES:
- Always use a unique sessionId in override_config to isolate test sessions.
  Example: override_config='{"sessionId": "test-<chatflow_id>-<timestamp>"}'
- Run at minimum: (1) happy-path input, (2) one edge case.
- Diagnose failures:
  - "Ending node must be either a Chain or Agent" → missing terminal node in flow
  - "OPENAI_API_KEY environment variable is missing" → credential binding issue
  - "404 Not Found" on prediction → wrong chatflow_id (verify with list_chatflows)
  - Empty response → check if flow is deployed (deployed: true may be required)
- For multi-turn conversation tests, use the same sessionId across multiple create_prediction calls.
"""


# ---------------------------------------------------------------------------
# Executor factory — maps tool names to FlowiseClient methods
# ---------------------------------------------------------------------------


async def _list_marketplace_templates_slim(client: FlowiseClient) -> list[dict]:
    """Return a trimmed marketplace template list (no flowData).

    The full /marketplaces/templates response is ~1.7MB (~430k tokens) because
    each of the 50 templates includes its complete flowData JSON. Stripping flowData
    reduces this to ~13KB (~3k tokens) while still giving the LLM the information
    it needs to decide whether a template matches the requirement.

    If a template looks relevant, the LLM should note its templateName and the
    developer can manually import it — or a future tool can fetch full flowData
    for a specific template by name.
    """
    templates = await client.list_marketplace_templates()
    if not isinstance(templates, list):
        return templates  # pass through errors or unexpected shapes unchanged
    return [
        {
            "templateName": t.get("templateName"),
            "type": t.get("type"),
            "categories": t.get("categories"),
            "usecases": t.get("usecases"),
            "description": t.get("description"),
        }
        for t in templates
    ]


async def _list_nodes_slim(client: FlowiseClient) -> list[dict]:
    """Return a trimmed node list (name, category, label only).

    The full /nodes response is 650KB (~162k tokens) because each of the 300+
    nodes includes its complete input/output schema. Passing that to the LLM in
    a tool result blows the 200k context limit before any useful work is done.

    The slim list (~25KB, ~6k tokens) gives the LLM enough information to choose
    which nodes to inspect with get_node() — which returns the full schema for
    the specific node types it actually needs.
    """
    nodes = await client.list_nodes()
    if not isinstance(nodes, list):
        return nodes  # pass through errors or unexpected shapes unchanged
    return [
        {"name": n.get("name"), "category": n.get("category"), "label": n.get("label")}
        for n in nodes
    ]


# Flowise input types that map to inputParams (configurable fields).
# Any input type NOT in this set is treated as an inputAnchor (node connection).
_FLOWISE_PRIMITIVE_TYPES: frozenset[str] = frozenset({
    "string", "number", "boolean", "password", "json", "code",
    "file", "date", "credential", "asyncOptions", "options",
    "datagrid", "tabs", "multiOptions", "array",
})


async def _get_node_processed(client: FlowiseClient, name: str) -> dict:
    """Return get_node schema with inputAnchors/inputParams pre-split for flowData.

    The raw get_node response contains a flat 'inputs' array mixing both
    node-connection anchors (e.g. BaseChatModel) and configurable params
    (e.g. string, number). Flowise's buildChatflow crashes with:
      TypeError: Cannot read properties of undefined (reading 'find')
    if a node's data object is missing the 'inputAnchors' key.

    This wrapper pre-computes:
      inputAnchors  — inputs with class-name types (node connections)
      inputParams   — inputs with primitive types (configurable settings)
      outputAnchors — output in flowData format
      outputs       — always {} for standard nodes

    IDs use {nodeId} as a placeholder. The agent must replace this with the
    actual node ID it assigns (e.g., replace '{nodeId}' → 'chatOpenAI_0').
    """
    schema = await client.get_node(name)
    if not isinstance(schema, dict) or "error" in schema:
        return schema

    node_name = schema.get("name", name)
    base_classes = schema.get("baseClasses", [])
    raw_inputs = schema.get("inputs", [])

    input_anchors: list[dict] = []
    input_params: list[dict] = []

    for inp in raw_inputs:
        entry = dict(inp)
        inp_type = entry.get("type", "")
        entry["id"] = f"{{nodeId}}-input-{entry.get('name', '')}-{inp_type}"
        if inp_type in _FLOWISE_PRIMITIVE_TYPES:
            input_params.append(entry)
        else:
            # Non-primitive type = class name (BaseChatModel, BaseMemory, etc.)
            input_anchors.append(entry)

    # Use the raw outputAnchors from the schema if provided (multi-output nodes like
    # ifElseFunction have two named outputs). Synthesize from baseClasses as fallback.
    raw_output_anchors = schema.get("outputAnchors") or []
    if raw_output_anchors:
        # Normalize: ensure each anchor has a {nodeId} placeholder in its id field.
        output_anchors = []
        for oa in raw_output_anchors:
            entry = dict(oa)
            oa_id = entry.get("id", "")
            if oa_id and "{nodeId}" not in oa_id:
                # Re-template with placeholder so agent can substitute its node ID.
                oa_type = entry.get("type", "")
                oa_name = entry.get("name", node_name)
                entry["id"] = f"{{nodeId}}-output-{oa_name}-{oa_type}"
            output_anchors.append(entry)
    else:
        # Standard single-output node: synthesize from baseClasses.
        output_anchors = [
            {
                "id": f"{{nodeId}}-output-{node_name}-{'|'.join(base_classes)}",
                "name": node_name,
                "label": schema.get("label", node_name),
                "type": " | ".join(base_classes),
            }
        ]

    return {
        **schema,
        "inputAnchors": input_anchors,
        "inputParams": input_params,
        "outputAnchors": output_anchors,
        "outputs": {},
        "_flowdata_note": (
            "Replace {nodeId} in all 'id' fields with your actual node ID "
            "(e.g. 'chatOpenAI_0'). Embed inputAnchors, inputParams, outputAnchors, "
            "and outputs verbatim in each flowData node's data object. "
            "Set 'inputs' to a dict of configured values (use '' for unset optional fields, "
            "and '{{otherNodeId.data.instance}}' for connected anchor values)."
        ),
    }


def _validate_flow_data(flow_data_str: str) -> dict:
    """Structural pre-flight check for flowData before any chatflow write.

    Checks:
    1. Valid JSON with 'nodes' and 'edges' arrays
    2. Every node has: data.inputAnchors, data.inputParams, data.outputAnchors, data.outputs
    3. Every edge's source/target references an existing node ID
    4. Every edge's sourceHandle/targetHandle references an existing anchor ID

    Returns {"valid": True, "node_count": N, "edge_count": M} on success.
    Returns {"valid": False, "errors": [str]} listing all problems found.
    """
    errors: list[str] = []
    try:
        flow = json.loads(flow_data_str)
    except json.JSONDecodeError as e:
        return {"valid": False, "errors": [f"Invalid JSON: {e}"]}

    nodes = flow.get("nodes", [])
    edges = flow.get("edges", [])
    if not isinstance(nodes, list):
        return {"valid": False, "errors": ["'nodes' must be a list"]}
    if not isinstance(edges, list):
        return {"valid": False, "errors": ["'edges' must be a list"]}

    node_ids: set[str] = set()
    anchor_ids: set[str] = set()

    for node in nodes:
        nid = node.get("id", "?")
        node_ids.add(nid)
        data = node.get("data", {})
        for required_key in ("inputAnchors", "inputParams", "outputAnchors", "outputs"):
            if required_key not in data:
                errors.append(f"Node '{nid}': missing data.{required_key}")
        for anchor in data.get("inputAnchors", []):
            if "id" in anchor:
                anchor_ids.add(anchor["id"])
        for anchor in data.get("outputAnchors", []):
            if "id" in anchor:
                anchor_ids.add(anchor["id"])
            # Multi-output nodes use type="options" — IDs are nested inside options[]
            for opt in anchor.get("options", []):
                if "id" in opt:
                    anchor_ids.add(opt["id"])

    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src not in node_ids:
            errors.append(f"Edge: source '{src}' not found in nodes")
        if tgt not in node_ids:
            errors.append(f"Edge: target '{tgt}' not found in nodes")
        sh = edge.get("sourceHandle")
        th = edge.get("targetHandle")
        if sh and sh not in anchor_ids:
            errors.append(f"Edge: sourceHandle '{sh}' not in any node's outputAnchors")
        if th and th not in anchor_ids:
            errors.append(f"Edge: targetHandle '{th}' not in any node's inputAnchors")

    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "node_count": len(nodes), "edge_count": len(edges)}


# ---------------------------------------------------------------------------
# Chatflow snapshot / rollback (in-memory store per session)
# ---------------------------------------------------------------------------

# Maps session_id → list of snapshots (most recent last)
_snapshots: dict[str, list[dict]] = {}


async def _snapshot_chatflow(
    client: FlowiseClient, chatflow_id: str, session_id: str, version_label: str | None = None
) -> dict:
    """Save the current chatflow flowData as a versioned snapshot before patching.

    Call this before every update_chatflow so rollback is available if the
    patch breaks the flow.  version_label is auto-generated as "v{N}.0" when
    not supplied (DD-039).
    """
    import time

    chatflow = await client.get_chatflow(chatflow_id)
    if "error" in chatflow:
        return chatflow

    existing = _snapshots.get(session_id, [])
    label = version_label or f"v{len(existing) + 1}.0"
    snap = {
        "chatflow_id": chatflow_id,
        "name": chatflow.get("name"),
        "flow_data": chatflow.get("flowData", ""),
        "version_label": label,
        "timestamp": time.time(),
    }
    _snapshots.setdefault(session_id, []).append(snap)
    logger.debug(
        "Snapshot saved for chatflow %s (session %s, label=%s, count=%d)",
        chatflow_id,
        session_id,
        label,
        len(_snapshots[session_id]),
    )
    return {"snapshotted": True, "version_label": label, "snapshot_count": len(_snapshots[session_id])}


async def _rollback_chatflow(
    client: FlowiseClient, chatflow_id: str, session_id: str, version_label: str | None = None
) -> dict:
    """Restore a specific (or the latest) snapshot for a chatflow within this session.

    If version_label is provided, the snapshot with that label is restored.
    If not, the most recent snapshot is used (DD-039).
    """
    snaps = _snapshots.get(session_id, [])
    if not snaps:
        return {"error": "No snapshots found for this session"}

    if version_label:
        matching = [s for s in snaps if s.get("version_label") == version_label]
        if not matching:
            available = [s.get("version_label") for s in snaps]
            return {"error": f"Snapshot '{version_label}' not found. Available: {available}"}
        snap = matching[-1]
    else:
        snap = snaps[-1]

    logger.info(
        "Rolling back chatflow %s to snapshot %s at %.0f (session %s)",
        chatflow_id,
        snap.get("version_label"),
        snap["timestamp"],
        session_id,
    )
    result = await client.update_chatflow(
        chatflow_id=chatflow_id,
        flow_data=snap["flow_data"],
    )
    if "error" not in result:
        result["rolled_back_to"] = snap.get("version_label")
    return result


# ---------------------------------------------------------------------------
# Discover response cache (DD-035)
# Keyed by (instance_id, tool_name) via f"{tool_name}:{id(client)}".
# TTL configured via DISCOVER_CACHE_TTL_SECS (default: 300 seconds).
# ---------------------------------------------------------------------------

_tool_cache: dict[str, tuple[Any, float]] = {}  # key → (result, expires_at)


def _cached(key: str, ttl: float, fn: Callable) -> Callable:
    """Wrap an async callable with a monotonic-clock TTL cache.

    Returns a cached value if it was stored within the last `ttl` seconds.
    Setting ttl=0 disables caching (fn is always called).
    """
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        if ttl > 0:
            now = _time.monotonic()
            if key in _tool_cache:
                value, expires_at = _tool_cache[key]
                if now < expires_at:
                    logger.debug("Cache hit: %s", key)
                    return value
        result = await fn(*args, **kwargs)
        if ttl > 0:
            _tool_cache[key] = (result, _time.monotonic() + ttl)
        return result

    return wrapper


def _make_flowise_executor(
    client: FlowiseClient,
    guard: "WriteGuard | None" = None,
) -> dict[str, Callable[..., Any]]:
    """Return tool_name → async callable mapping for the FlowiseClient.

    guard: optional WriteGuard instance.  When provided, three tools are
           wrapped with enforcement logic (DD-052):
             validate_flow_data → records authorized hash on success
             create_chatflow    → blocked if payload hash does not match
             update_chatflow    → blocked if flow_data hash does not match

           When guard is None (default), behaviour is identical to pre-M2:
           no hash tracking, no write blocking.  Backwards-compatible.
    """
    import os as _os
    _cache_ttl = float(_os.getenv("DISCOVER_CACHE_TTL_SECS", "300"))
    _client_key = id(client)

    # Base (unguarded) implementations
    def _validate_raw(flow_data_str: str) -> dict:
        return _validate_flow_data(flow_data_str)

    async def _create_raw(**kwargs: Any) -> Any:
        return await client.create_chatflow(**kwargs)

    async def _update_raw(**kwargs: Any) -> Any:
        return await client.update_chatflow(**kwargs)

    # Guarded wrappers (only active when guard is provided)
    if guard is not None:
        def _validate_guarded(flow_data_str: str) -> dict:
            result = _validate_flow_data(flow_data_str)
            if result.get("valid"):
                guard.authorize(flow_data_str)
            return result

        async def _create_guarded(**kwargs: Any) -> Any:
            flow_data = kwargs.get("flow_data", "")
            if flow_data:
                guard.check(str(flow_data))
            result = await client.create_chatflow(**kwargs)
            if flow_data:
                guard.revoke()
            return result

        async def _update_guarded(**kwargs: Any) -> Any:
            flow_data = kwargs.get("flow_data", "")
            if flow_data:
                guard.check(str(flow_data))
            result = await client.update_chatflow(**kwargs)
            if flow_data:
                guard.revoke()
            return result

        validate_fn: Callable = _validate_guarded
        create_fn: Callable = _create_guarded
        update_fn: Callable = _update_guarded
    else:
        validate_fn = _validate_raw
        create_fn = _create_raw
        update_fn = _update_raw

    return {
        # Discovery tools
        "list_chatflows": client.list_chatflows,
        "get_chatflow": client.get_chatflow,
        "list_nodes": _cached(
            f"list_nodes:{_client_key}", _cache_ttl,
            lambda: _list_nodes_slim(client),
        ),
        "get_node": lambda name: _get_node_processed(client, name),
        "list_credentials": client.list_credentials,
        "list_marketplace_templates": _cached(
            f"list_marketplace_templates:{_client_key}", _cache_ttl,
            lambda: _list_marketplace_templates_slim(client),
        ),
        # Patch tools (validate/write are optionally guarded)
        "validate_flow_data": validate_fn,
        "snapshot_chatflow": lambda chatflow_id, session_id, version_label=None: _snapshot_chatflow(client, chatflow_id, session_id, version_label),
        "rollback_chatflow": lambda chatflow_id, session_id, version_label=None: _rollback_chatflow(client, chatflow_id, session_id, version_label),
        "create_chatflow": create_fn,
        "update_chatflow": update_fn,
        # Test tools
        "create_prediction": client.create_prediction,
        "upsert_vector": client.upsert_vector,
    }


# ---------------------------------------------------------------------------
# Write guard — same-iteration hash enforcement (DD-052)
# ---------------------------------------------------------------------------


class WriteGuard:
    """Enforces same-iteration validation before any Flowise write.

    Lifecycle (one guard instance per patch iteration):
      1. A validated payload is registered via ``authorize(flow_data_str)``
         (called automatically by the guarded validate_flow_data wrapper when
         validation passes).
      2. The guarded create_chatflow / update_chatflow wrappers call
         ``check(flow_data_str)`` before writing.  If the payload changed
         since validation the write is blocked with a PermissionError.
      3. After a successful write ``revoke()`` is called so the guard cannot
         be reused for a second write without re-validation.

    Invariant: No Flowise write can succeed unless the exact payload that
    was written also passed ``validate_flow_data`` in the same iteration.

    See DD-052 and roadmap3_architecture_optimization.md — Milestone 2.
    """

    def __init__(self) -> None:
        self._authorized_hash: str | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def authorize(self, flow_data_str: str) -> str:
        """Record that this payload passed validation.

        Computes SHA-256 of ``flow_data_str`` and stores it as the
        authorized hash.  Any subsequent write with a different payload
        will be blocked by ``check()``.

        Returns the hash string (for recording in state).
        """
        h = hashlib.sha256(flow_data_str.encode("utf-8")).hexdigest()
        self._authorized_hash = h
        return h

    def check(self, flow_data_str: str) -> None:
        """Assert the payload matches the authorized hash.

        Raises PermissionError when:
          - ``authorize()`` was never called (ValidationRequired)
          - The payload hash differs from what was authorized (HashMismatch)
        """
        if self._authorized_hash is None:
            raise PermissionError(
                "ValidationRequired: flow_data has not been validated this iteration. "
                "Call validate_flow_data(flow_data) before create_chatflow or "
                "update_chatflow to register the authorized payload."
            )
        actual = hashlib.sha256(flow_data_str.encode("utf-8")).hexdigest()
        if actual != self._authorized_hash:
            raise PermissionError(
                "HashMismatch: the flow_data payload changed since validate_flow_data "
                "was called. Re-validate the new payload before writing. "
                f"(authorized={self._authorized_hash[:16]}…, "
                f"received={actual[:16]}…)"
            )

    def revoke(self) -> None:
        """Revoke write authorization (one-shot: resets after a successful write)."""
        self._authorized_hash = None

    @property
    def authorized_hash(self) -> str | None:
        """The hash of the currently authorized payload (None = not yet validated)."""
        return self._authorized_hash


# ---------------------------------------------------------------------------
# Tool execution helper (shared by all nodes via graph.py)
# ---------------------------------------------------------------------------


def _stream_write(payload: dict) -> None:
    """Emit a custom event to any active LangGraph stream writer.

    Uses get_stream_writer() from langgraph.config, which is a no-op when
    called outside a LangGraph execution context (e.g. in unit tests).
    """
    try:
        from langgraph.config import get_stream_writer  # noqa: PLC0415
        get_stream_writer()(payload)
    except Exception:
        pass



# ---------------------------------------------------------------------------
# ToolResult envelope (DD-048)
# Normalizes every tool execution result into a typed container.
# Only .summary is injected into LLM context; .data is stored to state['debug'].
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """Normalized envelope for every tool execution result.

    ok:        True if the tool completed without error.
    summary:   Compact, prompt-safe string injected into LLM context.
               Written for an LLM reader: concise, no raw JSON blobs.
               This is the ONLY field that goes into message history.
    facts:     Structured key→value deltas extracted from the result.
               Stored in state['facts'][domain], keyed by domain name.
               Examples:
                 {"chatflow_id": "abc123", "node_count": 5}
                 {"missing_credentials": ["openAIApi"]}
    data:      Raw output from the underlying tool callable.
               NOT injected into the LLM by default. Stored in state['debug'].
    error:     Present when ok=False. Dict with keys:
                 type:    Exception class name or error category.
                 message: Human-readable summary.
                 detail:  Original exception message or API error body.
    artifacts: Optional domain-specific references produced by the tool.
               Stored in state['artifacts'][domain].
               Examples:
                 {"chatflow_ids": ["abc123"], "snapshot_labels": ["v1.0"]}

    See DD-048 and roadmap3_architecture_optimization.md.
    """

    ok: bool
    summary: str
    facts: dict
    data: Any
    error: dict | None
    artifacts: dict | None


def _wrap_result(tool_name: str, raw: Any) -> "ToolResult":
    """Wrap a raw tool callable result into a ToolResult envelope.

    This is the single transformation point between the raw-result world and the
    typed ToolResult world. The 21 existing tool functions are NOT changed — wrapping
    happens here at the execute_tool() boundary.

    Summary generation rules (priority order):
      1. dict with "error" key          → ok=False, summary from error message
      2. dict with "valid" key          → validate_flow_data result
      3. dict with "id" + "name" keys   → chatflow create/get/update result
      4. dict with "snapshotted" key    → snapshot result
      5. list                           → count summary
      6. other dict                     → first 200 chars of JSON
      7. scalar / string                → first 300 chars
    """
    # Rule 0: ToolResult passthrough — MCP tools already return ToolResult envelopes
    if isinstance(raw, ToolResult):
        return raw

    # Rule 1: explicit error dict
    if isinstance(raw, dict) and "error" in raw:
        msg = str(raw["error"])
        return ToolResult(
            ok=False,
            summary=f"{tool_name} failed: {msg}",
            facts={},
            data=raw,
            error={"type": "ToolError", "message": msg, "detail": None},
            artifacts=None,
        )

    # Rule 2: validate_flow_data result
    if isinstance(raw, dict) and "valid" in raw:
        if raw["valid"]:
            return ToolResult(
                ok=True,
                summary=(
                    f"Flow data valid: {raw.get('node_count', 0)} nodes, "
                    f"{raw.get('edge_count', 0)} edges."
                ),
                facts={
                    "node_count": raw.get("node_count"),
                    "edge_count": raw.get("edge_count"),
                },
                data=raw,
                error=None,
                artifacts=None,
            )
        errors = raw.get("errors", [])
        first_error = errors[0] if errors else "unknown"
        return ToolResult(
            ok=False,
            summary=f"Flow data invalid: {len(errors)} error(s). First: {first_error}",
            facts={"validation_errors": errors},
            data=raw,
            error={
                "type": "ValidationError",
                "message": f"{len(errors)} validation error(s)",
                "detail": str(errors[:3]),
            },
            artifacts=None,
        )

    # Rule 3: chatflow create/get/update — extract ID as artifact
    if isinstance(raw, dict) and "id" in raw:
        cid = str(raw["id"])
        name = raw.get("name", cid)
        return ToolResult(
            ok=True,
            summary=f"Chatflow '{name}' (id={cid}).",
            facts={"chatflow_id": cid, "chatflow_name": name},
            data=raw,
            error=None,
            artifacts={"chatflow_ids": [cid]},
        )

    # Rule 4: snapshot result
    if isinstance(raw, dict) and "snapshotted" in raw:
        label = raw.get("version_label", "unknown")
        count = raw.get("snapshot_count", 1)
        return ToolResult(
            ok=True,
            summary=f"Snapshot saved as {label} (total: {count}).",
            facts={"snapshot_label": label},
            data=raw,
            error=None,
            artifacts={"snapshot_labels": [label]},
        )

    # Rule 5: list result
    if isinstance(raw, list):
        return ToolResult(
            ok=True,
            summary=f"{tool_name} returned {len(raw)} item(s).",
            facts={"count": len(raw)},
            data=raw,
            error=None,
            artifacts=None,
        )

    # Rule 6: other dict
    if isinstance(raw, dict):
        try:
            preview = json.dumps(raw, default=str)[:200]
        except Exception:
            preview = str(raw)[:200]
        return ToolResult(
            ok=True,
            summary=f"{tool_name}: {preview}",
            facts={},
            data=raw,
            error=None,
            artifacts=None,
        )

    # Rule 7: scalar / string
    return ToolResult(
        ok=True,
        summary=str(raw)[:300],
        facts={},
        data=raw,
        error=None,
        artifacts=None,
    )


async def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    executor: dict[str, Callable[..., Any]],
) -> "ToolResult":
    """Execute a named tool with the given arguments. Returns a ToolResult envelope.

    Emits tool_call / tool_result custom events via get_stream_writer() so
    the SSE stream receives live tool badges for each Flowise API call.

    The summary field of the returned ToolResult is safe for LLM injection.
    The data field is raw output suitable only for debug storage.

    See DD-048 (ToolResult as single transformation point).
    """
    _stream_write({"type": "tool_call", "name": tool_name})

    fn = executor.get(tool_name)
    if fn is None:
        logger.warning("Unknown tool requested: %r", tool_name)
        result = ToolResult(
            ok=False,
            summary=f"Unknown tool: {tool_name!r}. Check available tools for this phase.",
            facts={},
            data=None,
            error={
                "type": "UnknownTool",
                "message": f"Tool {tool_name!r} not found in executor",
                "detail": None,
            },
            artifacts=None,
        )
        _stream_write({"type": "tool_result", "name": tool_name, "preview": result.summary[:200]})
        return result
    try:
        raw = await fn(**arguments)
        result = _wrap_result(tool_name, raw)
        logger.debug("Tool %s(%s) → ok=%s", tool_name, list(arguments.keys()), result.ok)
        _stream_write({"type": "tool_result", "name": tool_name, "preview": result.summary[:200]})
        return result
    except TypeError as e:
        logger.warning("Tool %s called with wrong arguments %s: %s", tool_name, arguments, e)
        result = ToolResult(
            ok=False,
            summary=f"Wrong arguments for {tool_name}: {e}",
            facts={},
            data=None,
            error={"type": "TypeError", "message": str(e), "detail": None},
            artifacts=None,
        )
        _stream_write({"type": "tool_result", "name": tool_name, "preview": result.summary[:200]})
        return result
    except Exception as e:
        logger.warning("Tool %s failed: %s", tool_name, e)
        result = ToolResult(
            ok=False,
            summary=f"{tool_name} error: {e}",
            facts={},
            data=None,
            error={"type": type(e).__name__, "message": str(e), "detail": None},
            artifacts=None,
        )
        _stream_write({"type": "tool_result", "name": tool_name, "preview": result.summary[:200]})
        return result


def result_to_str(result: Any) -> str:
    """Serialize a tool result to a string for the message history.

    When given a ToolResult, returns result.summary (compact, prompt-safe).
    This is the enforcement point for the compact context policy (DD-048):
    raw JSON blobs from tool calls are NEVER injected into LLM context.

    Legacy path: accepts raw values (str, dict, list) for any code that has
    not yet been updated to use ToolResult.
    """
    if isinstance(result, ToolResult):
        return result.summary
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, default=str)
    except Exception:
        return str(result)


async def rollback_session_chatflow(
    client: FlowiseClient, chatflow_id: str, session_id: str, version_label: str | None = None
) -> dict:
    """Public wrapper for the rollback API endpoint in api.py (DD-039).

    Rolls back to the snapshot identified by version_label, or the latest
    snapshot when version_label is None.
    """
    return await _rollback_chatflow(client, chatflow_id, session_id, version_label)


def list_session_snapshots(session_id: str) -> list[dict]:
    """Return snapshot metadata for a session without the bulky flow_data field (DD-039).

    Each entry has: chatflow_id, name, version_label, timestamp.
    The list is ordered oldest-first (append order).
    """
    return [
        {k: v for k, v in snap.items() if k != "flow_data"}
        for snap in _snapshots.get(session_id, [])
    ]


# ---------------------------------------------------------------------------
# Pattern domain — wraps PatternStore as a DomainTools plugin
# ---------------------------------------------------------------------------


_PATTERN_SEARCH_TOOL = _td(
    "search_patterns",
    (
        "Search the pattern library for prior successful chatflows matching your requirement. "
        "Returns up to 3 patterns with their name, requirement, flowData, and success_count. "
        "Call this FIRST in Discover before using list_chatflows or list_nodes — "
        "if a matching pattern exists, you can reuse its flowData directly and skip most discovery. "
        "Increment success_count with use_pattern(id) when you reuse a pattern."
    ),
    {"keywords": {"type": "string", "description": "Space-separated keywords from the requirement"}},
    ["keywords"],
)

_PATTERN_USE_TOOL = _td(
    "use_pattern",
    (
        "Record that a pattern from the library is being reused. "
        "Increments its success_count so highly-reliable patterns surface first in future searches. "
        "Call this after search_patterns when you decide to base your plan on an existing pattern."
    ),
    {"pattern_id": {"type": "integer", "description": "The id returned by search_patterns"}},
    ["pattern_id"],
)


class PatternDomain(DomainTools):
    """Tool domain wrapping the pattern library (PatternStore).

    Provides `search_patterns` and `use_pattern` tools in the Discover phase
    so the LLM can check the library before doing a full Flowise API scan.

    Usage:
        store = await PatternStore.open(db_path)
        pattern_domain = PatternDomain(store)
        graph = build_graph(engine, domains=[flowise_domain, pattern_domain])

    See DESIGN_DECISIONS.md — DD-031.
    """

    def __init__(self, pattern_store: "PatternStore") -> None:  # noqa: F821
        super().__init__(
            name="patterns",
            discover=[_PATTERN_SEARCH_TOOL, _PATTERN_USE_TOOL],
            patch=[],
            test=[],
            executor={
                "search_patterns": lambda keywords: pattern_store.search_patterns(keywords),
                "use_pattern": lambda pattern_id: pattern_store.increment_success(int(pattern_id)),
            },
            discover_context=(
                "PATTERN LIBRARY:\n"
                "Call search_patterns(keywords) at the START of every Discover phase.\n"
                "If a relevant pattern is found, use its flowData as the base for the plan\n"
                "and call use_pattern(id) to record the reuse. Skip list_nodes and\n"
                "list_marketplace_templates if the pattern already matches the requirement closely.\n"
                "Patterns are ranked by relevance then success_count — higher count = more reliable."
            ),
        )
