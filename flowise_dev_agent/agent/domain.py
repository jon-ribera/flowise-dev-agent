"""DomainCapability — behavioral abstraction boundary for agent domain plugins.

DomainCapability is the primary abstraction for v2 of the agent architecture.
It wraps a DomainTools (data descriptor) and adds behavioral lifecycle methods:

  discover()       — structured discovery producing DomainDiscoveryResult
  compile_ops()    — STUB (Patch IR, NOT implemented per hard constraints M1)
  validate()       — STUB (deterministic validation, NOT implemented M1)
  generate_tests() — returns TestSuite using existing test logic
  evaluate()       — returns Verdict using existing converge logic

Relationship to DomainTools:
  DomainTools      = data descriptor (list of ToolDef + executor dict)
  DomainCapability = behavioral wrapper around DomainTools
  FlowiseCapability wraps FloviseDomain (existing DomainTools subclass)

Concrete implementations:
  FlowiseCapability — in graph.py (co-located with _react + _parse_converge_verdict)
  WorkdayCapability — in agent/domains/workday.py (stub, no real API)

Migration note:
  DomainCapability wraps DomainTools; it does not replace it.
  graph.py can use either the old DomainTools path (capabilities=None) or the
  new DomainCapability path (capabilities=[...]). Both co-exist during transition.

See DESIGN_DECISIONS.md — DD-046.
See roadmap3_architecture_optimization.md — Milestone 1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flowise_dev_agent.agent.registry import ToolRegistry
    from flowise_dev_agent.agent.tools import DomainTools, ToolResult


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass
class DomainDiscoveryResult:
    """Structured output from DomainCapability.discover().

    summary:      Human-readable text for the LLM planning context.
                  Stored in state['discovery_summary'] (flowise domain) or
                  state['domain_context'][domain_name] (other domains).
                  Must be compact — no raw JSON blobs.
    facts:        Extracted structured facts. Stored in state['facts'][domain_name].
                  Keys are tool-specific: chatflow_id, node_names, credential_types.
    artifacts:    Persistent references (IDs, hashes) produced during discover.
                  Stored in state['artifacts'][domain_name].
    debug:        Raw tool output digests, keyed by iteration number.
                  Stored in state['debug'][domain_name]. NOT injected into LLM.
                  Format: {iteration_int: {tool_name: content_string}}
    tool_results: ToolResult objects for each tool call made during discover.
                  Available for introspection and unit testing.
    """

    summary: str
    facts: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    debug: dict[str, Any] = field(default_factory=dict)
    tool_results: list["ToolResult"] = field(default_factory=list)


@dataclass
class DomainPatchResult:
    """Result from DomainCapability.compile_ops().

    STUB in Milestone 1 — not implemented per hard constraints (no Patch IR).
    Placeholder so the DomainCapability interface is complete and testable.

    Milestone 2 will replace this stub with a real PatchIR-carrying result.
    See roadmap3_architecture_optimization.md — Milestone 2.
    """

    stub: bool = True
    message: str = "compile_ops is not implemented in Milestone 1 (Patch IR deferred)."


@dataclass
class ValidationReport:
    """Result from DomainCapability.validate().

    STUB in Milestone 1 — not implemented per hard constraints (no deterministic compiler).
    Placeholder so the DomainCapability interface is complete and testable.

    Milestone 2 will replace this stub with real structural validation.
    See roadmap3_architecture_optimization.md — Milestone 2.
    """

    stub: bool = True
    message: str = "validate is not implemented in Milestone 1 (deterministic compiler deferred)."


@dataclass
class TestSuite:
    """Result from DomainCapability.generate_tests().

    In Milestone 1, generate_tests() returns the existing test logic configuration.
    It does not generate new test cases algorithmically.

    happy_question:  Input for the happy-path test case.
    edge_question:   Input for the edge-case test case (often "").
    domain_name:     Which domain these tests target.
    metadata:        Optional domain-specific test configuration.
    """

    happy_question: str
    edge_question: str
    domain_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Verdict:
    """Result from DomainCapability.evaluate().

    Typed form of the converge_verdict dict used throughout the codebase.
    Provides to_dict() / from_dict() for full backwards compatibility with
    the existing plan node logic that reads state['converge_verdict'].

    done:     True if Definition of Done is met.
    verdict:  "DONE" or "ITERATE"
    category: None | "CREDENTIAL" | "STRUCTURE" | "LOGIC" | "INCOMPLETE"
    reason:   One-line description of the verdict.
    fixes:    Specific repair instructions for the plan node.

    Relationship to legacy converge_verdict:
        state['converge_verdict'] = verdict.to_dict()   (written by converge node)
        Verdict.from_dict(state['converge_verdict'])    (for typed access)
    """

    done: bool
    verdict: str      # "DONE" | "ITERATE"
    category: str | None
    reason: str
    fixes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to the legacy converge_verdict dict format.

        The converge_verdict dict schema (unchanged from v1):
          {"verdict": "DONE"|"ITERATE", "category": ..., "reason": ..., "fixes": [...]}
        """
        return {
            "verdict": self.verdict,
            "category": self.category,
            "reason": self.reason,
            "fixes": self.fixes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Verdict":
        """Reconstruct from a legacy converge_verdict dict."""
        return cls(
            done=d.get("verdict") == "DONE",
            verdict=d.get("verdict", "ITERATE"),
            category=d.get("category"),
            reason=d.get("reason", ""),
            fixes=d.get("fixes", []),
        )


# ---------------------------------------------------------------------------
# DomainCapability ABC
# ---------------------------------------------------------------------------


class DomainCapability(ABC):
    """Abstract behavioral interface for a domain plugin.

    DomainCapability is the primary abstraction boundary. Implementing this
    class is all that is required to add a new domain to the agent.

    Concrete implementations:
      FlowiseCapability  — in graph.py (wraps FloviseDomain)
      WorkdayCapability  — in agent/domains/workday.py (stub)

    The relationship to DomainTools:
      DomainTools owns tool definitions and the executor dict (data).
      DomainCapability adds lifecycle methods on top (behaviour).
      The domain_tools property bridges the two worlds.

    graph.py co-existence:
      build_graph(capabilities=None) → old DomainTools path unchanged.
      build_graph(capabilities=[...]) → new DomainCapability path for discover.
      All other nodes (plan, patch, test, converge) continue to use DomainTools.

    See DD-046 and roadmap3_architecture_optimization.md — Milestone 1.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Domain identifier. Must be unique across all registered capabilities.

        Examples: "flowise", "workday", "servicenow"
        Used as the key in state['artifacts'], state['facts'], state['debug'].
        Also used as the namespace prefix in ToolRegistry (e.g. "flowise.get_node").
        """
        ...

    @property
    @abstractmethod
    def tools(self) -> "ToolRegistry":
        """The ToolRegistry for this domain.

        The registry holds namespaced tool defs + executors for all phases.
        Nodes call registry.tool_defs(phase) and registry.executor(phase) to
        get what they need.
        """
        ...

    @property
    @abstractmethod
    def domain_tools(self) -> "DomainTools":
        """The underlying DomainTools instance.

        Provides backwards compatibility: graph.py node factories that still
        call merge_tools(domains) can extract domain_tools from each capability.
        """
        ...

    @abstractmethod
    async def discover(self, context: dict[str, Any]) -> DomainDiscoveryResult:
        """Execute the discovery phase for this domain.

        context: dict containing the current agent state fields relevant to
                 discovery. Expected keys:
                   requirement: str        — the developer's original requirement
                   clarification: str|None — answers to clarifying questions
                   developer_feedback: str|None — feedback from prior ITERATE
                   iteration: int          — current iteration number (0 = first)
                   domain_context: dict    — existing per-domain summaries

        The LLM remains in control of tool selection via the _react() loop.
        discover() feeds the loop and post-processes its output into structured types.

        Returns a DomainDiscoveryResult with:
          summary:   text for state['discovery_summary'] or state['domain_context']
          facts:     structured data for state['facts'][self.name]
          artifacts: produced references for state['artifacts'][self.name]
          debug:     raw tool outputs for state['debug'][self.name] (NOT LLM context)
        """
        ...

    @abstractmethod
    async def compile_ops(self, plan: str) -> DomainPatchResult:
        """STUB — Compile plan text into patch operations.

        NOT IMPLEMENTED in Milestone 1 (no Patch IR per hard constraints).
        Concrete implementations must return DomainPatchResult(stub=True).

        Milestone 2 will implement this with a real PatchIR schema.
        See roadmap3_architecture_optimization.md — Milestone 2.
        """
        ...

    @abstractmethod
    async def validate(self, artifacts: dict[str, Any]) -> ValidationReport:
        """STUB — Validate artifacts against domain rules.

        NOT IMPLEMENTED in Milestone 1 (no deterministic compiler per hard constraints).
        Concrete implementations must return ValidationReport(stub=True).

        Milestone 2 will implement this with real structural validation.
        See roadmap3_architecture_optimization.md — Milestone 2.
        """
        ...

    @abstractmethod
    async def generate_tests(self, plan: str) -> TestSuite:
        """Generate test cases from the plan text.

        In Milestone 1, wraps the existing test logic:
          happy_question = first 100 chars of plan (or requirement)
          edge_question  = "" (empty input boundary test)

        Returns a TestSuite for use by the test node.
        """
        ...

    @abstractmethod
    async def evaluate(self, results: dict[str, Any]) -> Verdict:
        """Evaluate test results against the Definition of Done.

        results: dict with keys:
          test_results: str     — from state['test_results']
          chatflow_id: str|None — from state['chatflow_id']
          plan: str|None        — from state['plan']
          iteration: int        — from state['iteration']

        In Milestone 1, wraps _parse_converge_verdict() from graph.py.
        Returns a Verdict. Use verdict.to_dict() to write to state['converge_verdict'].
        """
        ...
