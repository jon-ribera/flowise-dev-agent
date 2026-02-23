"""Flowise Builder co-pilot agent.

Entry points:
    build_graph(engine, domains, checkpointer=None) → CompiledGraph
    create_agent(flowise_settings, reasoning_settings) → (CompiledGraph, FlowiseClient)

See DESIGN_DECISIONS.md — DD-007 through DD-010.
"""

from flowise_dev_agent.agent.graph import build_graph, create_agent
from flowise_dev_agent.agent.state import AgentState
from flowise_dev_agent.agent.tools import DomainTools, FloviseDomain

__all__ = [
    "build_graph",
    "create_agent",
    "AgentState",
    "DomainTools",
    "FloviseDomain",
]
