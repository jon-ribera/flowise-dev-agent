"""WorkdayCapability — Custom MCP wiring for the Workday domain (Milestone 7.5).

Implements Workday integration via Flowise's built-in Custom MCP tool config:
  - selectedTool = "customMCP"
  - selectedToolConfig.mcpServerConfig = <STRINGIFIED JSON>  (url + auth header)
  - selectedToolConfig.mcpActions = ["getMyInfo", "searchForWorker", "getWorkers"]

This approach uses a *blueprint* in schemas/workday_mcp.snapshot.json rather than
live MCP endpoint discovery.  No real Workday API calls are made — the agent
generates Patch IR ops that wire the Flowise Tool node to call the Workday MCP
server at runtime via the tenant-configured URL.

How to activate in production:
  1. Run ``python -m flowise_dev_agent.knowledge.refresh --workday-mcp`` to confirm
     the blueprint snapshot is present.
  2. Pass ``WorkdayCapability()`` to ``build_graph(capabilities=[..., WorkdayCapability()])``.
  3. The plan produced by the plan node should mention Workday worker operations.
  4. The compile_ops() output will contain an AddNode + BindCredential for the MCP
     tool.  Phase C of _make_patch_node_v2 will resolve the real credential_id.

Non-goals for this milestone:
  - No live MCP server connection or tools/list call.
  - No Workday REST/SOAP API integration (WorkdayApiStore remains a stub).
  - No agentflow — wiring targets CHATFLOW only.

See roadmap7_multi_domain_runtime_hardening.md — Milestone 7.5.
See DESIGN_DECISIONS.md — DD-047, DD-065.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from flowise_dev_agent.agent.domain import (
    DomainCapability,
    DomainDiscoveryResult,
    DomainPatchResult,
    TestSuite,
    ValidationReport,
    Verdict,
)
from flowise_dev_agent.agent.patch_ir import AddNode, BindCredential, validate_patch_ops
from flowise_dev_agent.agent.registry import ToolRegistry
from flowise_dev_agent.agent.tools import DomainTools
from flowise_dev_agent.reasoning import ToolDef

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MCP wiring constants
# ---------------------------------------------------------------------------

_MCP_SELECTED_TOOL = "customMCP"
_MCP_URL_PLACEHOLDER = "https://<tenant>.workday.com/mcp"
_MCP_AUTH_VAR = "$vars.beartoken"
_MCP_DEFAULT_ACTIONS: list[str] = ["getMyInfo", "searchForWorker", "getWorkers"]
_MCP_TOOL_NODE_NAME = "tool"          # Flowise Tool node type
_MCP_TOOL_NODE_ID = "workdayMcpTool_0"
_MCP_CREDENTIAL_TYPE = "workdayOAuth"
_MCP_CREDENTIAL_PLACEHOLDER = "workday-oauth-auto"  # resolved at patch time (Phase C)
_MCP_DEFAULT_BLUEPRINT_ID = "workday_default"


def _build_mcp_server_config_str(url: str, auth_var: str) -> str:
    """Return the mcpServerConfig as a STRINGIFIED JSON (Flowise persists it as a string).

    The resulting string must contain 'url' and 'headers.Authorization' so that
    Flowise's Custom MCP integration can extract the server URL and auth header.
    """
    return json.dumps(
        {
            "url": url,
            "headers": {"Authorization": auth_var},
        },
        separators=(",", ":"),
    )


# ---------------------------------------------------------------------------
# Workday placeholder tool definitions (discover phase)
# ---------------------------------------------------------------------------

_WORKDAY_DISCOVER_TOOLS: list[ToolDef] = [
    ToolDef(
        name="get_worker",
        description=(
            "[STUB] Retrieve a Workday worker profile by WID or employee ID. "
            "Not connected to real Workday API — returns placeholder data only. "
            "See flowise_dev_agent/agent/domains/workday.py activation checklist."
        ),
        parameters={
            "type": "object",
            "properties": {
                "worker_id": {
                    "type": "string",
                    "description": "Workday WID or employee ID (e.g. 'WID:abc123')",
                }
            },
            "required": ["worker_id"],
        },
    ),
    ToolDef(
        name="list_business_processes",
        description=(
            "[STUB] List available Workday business process types. "
            "Not connected to real Workday API — returns placeholder data only."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
]


async def _stub_get_worker(worker_id: str) -> dict:
    """Placeholder: returns synthetic data without calling any external API."""
    return {
        "worker_id": worker_id,
        "name": "STUB — Workday API not configured",
        "status": "stub",
        "note": (
            "Configure real Workday MCP tools in flowise_dev_agent/agent/domains/workday.py "
            "to enable real data. See the activation checklist at the top of that file."
        ),
    }


async def _stub_list_business_processes() -> list[dict]:
    """Placeholder: returns empty list without calling any external API."""
    return [
        {
            "type": "STUB",
            "name": "Workday API not configured",
            "note": "See activation checklist in flowise_dev_agent/agent/domains/workday.py",
        }
    ]


# ---------------------------------------------------------------------------
# WorkdayDomainTools — DomainTools data descriptor
# ---------------------------------------------------------------------------


class WorkdayDomainTools(DomainTools):
    """DomainTools descriptor for the Workday domain.

    Provides discover-only placeholder tools.  patch and test are empty because
    Workday write operations are wired via compile_ops() → Patch IR, not direct
    tool calls.
    """

    def __init__(self) -> None:
        super().__init__(
            name="workday",
            discover=_WORKDAY_DISCOVER_TOOLS,
            patch=[],
            test=[],
            executor={
                "get_worker": _stub_get_worker,
                "list_business_processes": _stub_list_business_processes,
            },
            discover_context=(
                "WORKDAY DOMAIN (Custom MCP, Milestone 7.5):\n"
                "Workday integration uses Flowise's Custom MCP tool configuration. "
                "The agent will wire a Tool node with selectedTool='customMCP', "
                "mcpServerConfig pointing to the Workday MCP server, and a fixed set "
                "of MCP actions (getMyInfo, searchForWorker, getWorkers). "
                "Credential type: workdayOAuth (resolved at patch time). "
                "chatflow_only: true — agentflow wiring is not supported."
            ),
        )


# ---------------------------------------------------------------------------
# WorkdayCapability — DomainCapability behavioral wrapper
# ---------------------------------------------------------------------------


class WorkdayCapability(DomainCapability):
    """Workday DomainCapability — Custom MCP blueprint-based wiring (Milestone 7.5).

    discover():
        Loads the workday_default blueprint from WorkdayMcpStore (snapshot) and
        returns a DomainDiscoveryResult with MCP wiring facts.  No live MCP calls.

    compile_ops():
        Deterministically generates AddNode + BindCredential Patch IR ops for
        Flowise Custom MCP wiring.  No LLM call — the blueprint drives the ops.

    validate() / generate_tests() / evaluate():
        Remain stubs — not in scope for this milestone.

    Registered namespaced tools:
        "workday.get_worker"               (discover phase, placeholder)
        "workday.list_business_processes"  (discover phase, placeholder)
    """

    def __init__(
        self,
        knowledge_provider: Any | None = None,
    ) -> None:
        """
        Parameters
        ----------
        knowledge_provider:
            Optional WorkdayKnowledgeProvider instance.  When None, the default
            provider is instantiated lazily on first discover() call.
        """
        self._domain_tools = WorkdayDomainTools()
        self._registry = ToolRegistry()
        self._registry.register_domain(self._domain_tools)
        self._registry.register_context(
            "workday", "discover", self._domain_tools.discover_context
        )
        self._knowledge_provider = knowledge_provider

    def _get_mcp_store(self):
        """Return the WorkdayMcpStore, instantiating the provider if needed."""
        if self._knowledge_provider is None:
            from flowise_dev_agent.knowledge.workday_provider import WorkdayKnowledgeProvider
            self._knowledge_provider = WorkdayKnowledgeProvider()
        return self._knowledge_provider.mcp_store

    @property
    def name(self) -> str:
        return "workday"

    @property
    def tools(self) -> ToolRegistry:
        return self._registry

    @property
    def domain_tools(self) -> DomainTools:
        return self._domain_tools

    async def discover(self, context: dict[str, Any]) -> DomainDiscoveryResult:
        """Blueprint-driven discovery — no live Workday MCP calls.

        Loads the ``workday_default`` blueprint from WorkdayMcpStore and returns
        structured facts describing the Custom MCP wiring parameters.

        Returns a DomainDiscoveryResult with:
          summary:   Human-readable description of available MCP actions.
          facts:     mcp_mode, mcp_actions, mcp_server_url, auth_var, blueprint_id,
                     credential_type, oauth_credential_id (placeholder if unknown).
          artifacts: selected_tool, mcp_actions (for Patch IR generation).
        """
        requirement = context.get("requirement", "")

        mcp_store = self._get_mcp_store()

        # Keyword extraction from requirement for blueprint search
        keywords = [w.lower() for w in requirement.split() if len(w) > 3]
        keywords.extend(["workday", "mcp", "worker"])  # always include domain keywords

        blueprints = mcp_store.find(keywords, limit=1)
        if not blueprints:
            # Fall back to direct get of the default blueprint
            bp = mcp_store.get(_MCP_DEFAULT_BLUEPRINT_ID)
        else:
            bp = blueprints[0]

        if bp is None:
            # Snapshot missing or empty — use module-level defaults
            logger.warning(
                "[WorkdayCapability.discover] No blueprints found in snapshot — "
                "using module-level defaults"
            )
            bp = {
                "blueprint_id": _MCP_DEFAULT_BLUEPRINT_ID,
                "selected_tool": _MCP_SELECTED_TOOL,
                "mcp_server_url_placeholder": _MCP_URL_PLACEHOLDER,
                "auth_var": _MCP_AUTH_VAR,
                "mcp_actions": list(_MCP_DEFAULT_ACTIONS),
                "credential_type": _MCP_CREDENTIAL_TYPE,
            }

        blueprint_id: str = bp.get("blueprint_id", _MCP_DEFAULT_BLUEPRINT_ID)
        selected_tool: str = bp.get("selected_tool", _MCP_SELECTED_TOOL)
        mcp_server_url: str = bp.get("mcp_server_url_placeholder", _MCP_URL_PLACEHOLDER)
        auth_var: str = bp.get("auth_var", _MCP_AUTH_VAR)
        mcp_actions: list[str] = list(bp.get("mcp_actions") or _MCP_DEFAULT_ACTIONS)
        credential_type: str = bp.get("credential_type", _MCP_CREDENTIAL_TYPE)

        n_actions = len(mcp_actions)
        actions_str = ", ".join(mcp_actions)
        summary = (
            f"Workday Custom MCP blueprint '{blueprint_id}' loaded. "
            f"{n_actions} MCP action(s): {actions_str}. "
            f"selectedTool={selected_tool!r}. "
            f"Credential type: {credential_type}. "
            f"MCP server URL placeholder: {mcp_server_url}. "
            f"Auth var: {auth_var}. "
            f"chatflow_only=true — Patch IR will wire a Flowise Tool node."
        )

        facts: dict[str, Any] = {
            "blueprint_id": blueprint_id,
            "mcp_mode": selected_tool,
            "mcp_actions": mcp_actions,
            "mcp_server_url": mcp_server_url,
            "auth_var": auth_var,
            "credential_type": credential_type,
            "oauth_credential_id": _MCP_CREDENTIAL_PLACEHOLDER,
        }

        artifacts: dict[str, Any] = {
            "selected_tool": selected_tool,
            "mcp_actions": mcp_actions,
        }

        debug: dict[str, Any] = {
            "blueprint_raw": bp,
            "blueprint_id": blueprint_id,
            "discover_source": "workday_mcp_snapshot",
        }

        logger.info(
            "[WorkdayCapability.discover] Blueprint '%s' — %d action(s): %s",
            blueprint_id,
            n_actions,
            actions_str,
        )

        return DomainDiscoveryResult(
            summary=summary,
            facts=facts,
            artifacts=artifacts,
            debug=debug,
            tool_results=[],
        )

    async def compile_ops(self, plan: str) -> DomainPatchResult:
        """Generate Patch IR ops for Flowise Custom MCP wiring.

        Deterministically emits:
          1. AddNode  — Tool node with Custom MCP configuration in params.
          2. BindCredential — workdayOAuth placeholder (resolved by Phase C at patch time).

        The ``selectedToolConfig.mcpServerConfig`` param value is a STRINGIFIED JSON
        containing ``url`` and ``headers.Authorization``.

        The ``credential_id`` on BindCredential is a placeholder (``workday-oauth-auto``).
        The real Flowise credential UUID is resolved during Phase C of _make_patch_node_v2.

        Returns DomainPatchResult(stub=False, ops=[...]).
        """
        # Parse plan for any specific action mentions (optional refinement)
        mcp_actions = self._parse_plan_actions(plan)

        mcp_server_config_str = _build_mcp_server_config_str(
            _MCP_URL_PLACEHOLDER, _MCP_AUTH_VAR
        )

        ops = [
            AddNode(
                node_name=_MCP_TOOL_NODE_NAME,
                node_id=_MCP_TOOL_NODE_ID,
                label="Workday MCP",
                params={
                    "selectedTool": _MCP_SELECTED_TOOL,
                    "selectedToolConfig.mcpServerConfig": mcp_server_config_str,
                    "selectedToolConfig.mcpActions": mcp_actions,
                },
            ),
            BindCredential(
                node_id=_MCP_TOOL_NODE_ID,
                credential_id=_MCP_CREDENTIAL_PLACEHOLDER,
                credential_type=_MCP_CREDENTIAL_TYPE,
            ),
        ]

        errors, _warnings = validate_patch_ops(ops)
        if errors:
            msg = f"Workday compile_ops validation failed: {'; '.join(errors)}"
            logger.error("[WorkdayCapability.compile_ops] %s", msg)
            return DomainPatchResult(stub=False, ops=ops, message=msg)

        msg = (
            f"{len(ops)} op(s) generated: AddNode({_MCP_TOOL_NODE_NAME}/{_MCP_TOOL_NODE_ID}) "
            f"+ BindCredential({_MCP_CREDENTIAL_TYPE}). "
            f"MCP actions: {', '.join(mcp_actions)}."
        )
        logger.info("[WorkdayCapability.compile_ops] %s", msg)
        return DomainPatchResult(stub=False, ops=ops, message=msg)

    def _parse_plan_actions(self, plan: str) -> list[str]:
        """Extract MCP action names from the plan text, falling back to defaults.

        Scans the plan for any of the known action names.  Returns the full
        default set if none are mentioned (safest for self-service scenarios).
        """
        plan_lower = plan.lower()
        mentioned = [
            action
            for action in _MCP_DEFAULT_ACTIONS
            if action.lower() in plan_lower
        ]
        return mentioned if mentioned else list(_MCP_DEFAULT_ACTIONS)

    async def validate(self, artifacts: dict[str, Any]) -> ValidationReport:
        """Stub — Workday structural validation is not in scope for M7.5."""
        return ValidationReport(
            stub=True,
            message="validate is not implemented for WorkdayCapability (future milestone).",
        )

    async def generate_tests(self, plan: str) -> TestSuite:
        return TestSuite(
            happy_question=plan[:100] if plan else "",
            edge_question="",
            domain_name="workday",
            metadata={"mcp_mode": "customMCP"},
        )

    async def evaluate(self, results: dict[str, Any]) -> Verdict:
        return Verdict(
            done=False,
            verdict="ITERATE",
            category="INCOMPLETE",
            reason=(
                "Workday domain evaluation is not implemented — "
                "test results from Workday Custom MCP nodes require manual review."
            ),
            fixes=[
                "Inspect the Flowise chatflow test results to verify the Workday "
                "MCP Tool node returns expected data for getMyInfo / searchForWorker.",
                "Configure the real Workday OAuth credential ID via "
                "'python -m flowise_dev_agent.knowledge.refresh --credentials'.",
            ],
        )
