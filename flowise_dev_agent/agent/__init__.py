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

Milestone 2 — Patch IR + deterministic compiler (DD-051, DD-052):
    AddNode, SetParam, Connect, BindCredential — Patch IR op dataclasses
    PatchIRValidationError — raised when ops fail structural validation
    ops_to_json / ops_from_json — JSON roundtrip for Patch IR ops
    GraphIR, CompileResult — canonical graph IR and compiler output
    compile_patch_ops — deterministic flowData compiler
    WriteGuard — same-iteration hash enforcement at write time

See DESIGN_DECISIONS.md — DD-007 through DD-010, DD-046–DD-052.
See roadmap3_architecture_optimization.md for the milestone plan.
"""

from flowise_dev_agent.agent.compiler import CompileResult, GraphIR, compile_patch_ops
from flowise_dev_agent.agent.domain import (
    DomainCapability,
    DomainDiscoveryResult,
    DomainPatchResult,
    TestSuite,
    ValidationReport,
    Verdict,
)
from flowise_dev_agent.agent.graph import FlowiseCapability, build_graph, create_agent
from flowise_dev_agent.agent.patch_ir import (
    AddNode,
    BindCredential,
    Connect,
    PatchIRValidationError,
    SetParam,
    ops_from_json,
    ops_to_json,
    validate_patch_ops,
)
from flowise_dev_agent.agent.registry import ToolRegistry
from flowise_dev_agent.agent.state import AgentState
from flowise_dev_agent.agent.tools import DomainTools, FloviseDomain, ToolResult, WriteGuard

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
    # M2 Patch IR schema (DD-051)
    "AddNode",
    "SetParam",
    "Connect",
    "BindCredential",
    "PatchIRValidationError",
    "validate_patch_ops",
    "ops_to_json",
    "ops_from_json",
    # M2 deterministic compiler (DD-051)
    "GraphIR",
    "CompileResult",
    "compile_patch_ops",
    # M2 write guard (DD-052)
    "WriteGuard",
]
