"""WorkdayCapability — discover-only stub for the Workday domain.

This module is a structural placeholder demonstrating how a new domain is added
to the FloWise Dev Agent. It implements the full DomainCapability interface but
makes no real Workday API calls.

ACTIVATION CHECKLIST (when real Workday MCP tools become available):
  1. Replace _WORKDAY_DISCOVER_TOOLS with real Workday MCP ToolDefs.
  2. Replace _stub_get_worker with real async callables that call the Workday API.
  3. Replace WorkdayCapability.discover() body with a real _react() loop call
     (same pattern as FlowiseCapability.discover() in graph.py).
  4. Update workday_extend.md skill file with real discovery rules.
  5. Pass WorkdayCapability() to build_graph(capabilities=[..., WorkdayCapability()]).

No other files need to change. The orchestrator is domain-agnostic.

See DESIGN_DECISIONS.md — DD-047.
See roadmap3_architecture_optimization.md — Milestone 1 (stub), Milestone 3 (real).
See flowise_dev_agent/skills/workday_extend.md — domain-specific skill guidance.
"""

from __future__ import annotations

from flowise_dev_agent.agent.domain import (
    DomainCapability,
    DomainDiscoveryResult,
    DomainPatchResult,
    TestSuite,
    ValidationReport,
    Verdict,
)
from flowise_dev_agent.agent.registry import ToolRegistry
from flowise_dev_agent.agent.tools import DomainTools
from flowise_dev_agent.reasoning import ToolDef


# ---------------------------------------------------------------------------
# Workday placeholder tool definitions
# ---------------------------------------------------------------------------
#
# These are structural stubs. They demonstrate the naming convention
# (workday.get_worker) and parameter schema without making real API calls.
# Replace with real MCP tool schemas when Workday connectivity is available.

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
    """DomainTools descriptor for the Workday domain (stub).

    Provides discover-only placeholder tools. patch and test are empty because
    no Workday write operations are available yet.

    When real Workday MCP tools are available, add real ToolDefs to the
    discover list and/or add patch/test tools as appropriate.
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
                "WORKDAY DOMAIN (STUB):\n"
                "Workday MCP tools are not yet configured. "
                "The available tools (get_worker, list_business_processes) return "
                "placeholder data only. To activate real Workday integration, complete "
                "the checklist in flowise_dev_agent/agent/domains/workday.py. "
                "If a requirement involves Workday data, note the required operations "
                "in the discovery summary so they can be wired up when the API is available."
            ),
        )


# ---------------------------------------------------------------------------
# WorkdayCapability — DomainCapability behavioral wrapper
# ---------------------------------------------------------------------------


class WorkdayCapability(DomainCapability):
    """Discover-only DomainCapability stub for the Workday domain.

    discover() returns a DomainDiscoveryResult without making real API calls.
    All other methods return their respective stubs.

    How to activate (when real Workday MCP tools are available):
      1. Replace WorkdayDomainTools tool defs and executor with real implementations.
      2. Replace discover() body:
            from flowise_dev_agent.agent.graph import _react
            summary, new_msgs, in_tok, out_tok = await _react(
                engine, [user_msg], system, tool_defs, executor, max_rounds=20
            )
            # ... extract facts and debug from new_msgs ...
            return DomainDiscoveryResult(summary=summary, facts=facts, debug=debug)
      3. Add engine parameter to __init__ and pass it from build_graph.

    Registered namespaced tools:
      "workday.get_worker"               (discover phase)
      "workday.list_business_processes"  (discover phase)
    """

    def __init__(self) -> None:
        self._domain_tools = WorkdayDomainTools()
        self._registry = ToolRegistry()
        self._registry.register_domain(self._domain_tools)
        self._registry.register_context(
            "workday", "discover", self._domain_tools.discover_context
        )

    @property
    def name(self) -> str:
        return "workday"

    @property
    def tools(self) -> ToolRegistry:
        return self._registry

    @property
    def domain_tools(self) -> DomainTools:
        return self._domain_tools

    async def discover(self, context: dict) -> DomainDiscoveryResult:
        """Stub discover: returns a placeholder result without calling any tools.

        When real Workday tools are available, replace this body with a _react() call.
        """
        return DomainDiscoveryResult(
            summary=(
                "WORKDAY DOMAIN: stub active — no real data fetched. "
                "Workday MCP tools are not yet configured. "
                "See flowise_dev_agent/agent/domains/workday.py for the activation checklist."
            ),
            facts={"stub": True, "domain": "workday"},
            artifacts={},
            debug={"reason": "WorkdayCapability.discover() is a stub — no API calls made"},
            tool_results=[],
        )

    async def compile_ops(self, plan: str) -> DomainPatchResult:
        return DomainPatchResult()

    async def validate(self, artifacts: dict) -> ValidationReport:
        return ValidationReport()

    async def generate_tests(self, plan: str) -> TestSuite:
        return TestSuite(
            happy_question="",
            edge_question="",
            domain_name="workday",
            metadata={"stub": True},
        )

    async def evaluate(self, results: dict) -> Verdict:
        return Verdict(
            done=False,
            verdict="ITERATE",
            category="INCOMPLETE",
            reason="Workday domain is a stub — no real evaluation available.",
            fixes=[
                "Configure real Workday MCP tools and update WorkdayCapability "
                "(see flowise_dev_agent/agent/domains/workday.py activation checklist)."
            ],
        )
