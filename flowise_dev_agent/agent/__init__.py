"""Flowise Builder co-pilot agent.

Entry points:
    build_graph(engine, domains, checkpointer=None, capabilities=None) → CompiledGraph
    create_agent(flowise_settings, reasoning_settings) → (CompiledGraph, FlowiseClient)

v2 abstractions (DD-046, DD-048, DD-049):
    ToolResult        — normalized tool execution result envelope
    ToolRegistry      — namespaced, phase-gated tool registry
    DomainCapability  — behavioral ABC for domain plugins
    FlowiseCapability — DomainCapability wrapping FloviseDomain
    WorkdayCapability — DomainCapability stub for Workday (no real API)
    Result models     — DomainDiscoveryResult, DomainPatchResult, ValidationReport,
                        TestSuite, Verdict

See DESIGN_DECISIONS.md — DD-007 through DD-010, DD-046–DD-050.
See roadmap3_architecture_optimization.md for the milestone plan.
"""

from flowise_dev_agent.agent.domain import (
    DomainCapability,
    DomainDiscoveryResult,
    DomainPatchResult,
    TestSuite,
    ValidationReport,
    Verdict,
)
from flowise_dev_agent.agent.graph import FlowiseCapability, build_graph, create_agent
from flowise_dev_agent.agent.registry import ToolRegistry
from flowise_dev_agent.agent.state import AgentState
from flowise_dev_agent.agent.tools import DomainTools, FloviseDomain, ToolResult

__all__ = [
    # Core graph / agent entry points
    "build_graph",
    "create_agent",
    # State
    "AgentState",
    # DomainTools (v1 — still primary for plan/patch/test nodes)
    "DomainTools",
    "FloviseDomain",
    # v2 tool execution (DD-048)
    "ToolResult",
    # v2 registry (DD-049)
    "ToolRegistry",
    # v2 capability contract (DD-046)
    "DomainCapability",
    "FlowiseCapability",
    # v2 result models
    "DomainDiscoveryResult",
    "DomainPatchResult",
    "TestSuite",
    "ValidationReport",
    "Verdict",
]
