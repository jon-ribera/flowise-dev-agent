"""ToolRegistry v2 — namespaced, phase-gated, ToolResult-producing tool registry.

Naming convention: "<domain>__<tool_name>"  (double-underscore — dots are rejected by Claude API)
  flowise__get_node
  flowise__list_chatflows
  workday__get_worker    (stub — no real Workday API yet)
  patterns__search_patterns

Phase permissions: each tool declares which phases it is available in.
  Phases: "discover" | "patch" | "test"

Backwards compatibility: executor() returns BOTH the namespaced key
("flowise__get_node") AND the simple key ("get_node") so existing code using
bare tool names continues to work without modification.

See DESIGN_DECISIONS.md — DD-046, DD-049.
See roadmap3_architecture_optimization.md — Milestone 1.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from flowise_dev_agent.reasoning import ToolDef

if TYPE_CHECKING:
    from flowise_dev_agent.agent.tools import DomainTools, ToolResult


@dataclass
class RegistryEntry:
    """A single registered tool in the ToolRegistry.

    Fields:
        tool_def:    ToolDef with the namespaced name ("flowise__get_node").
                     This is what is sent to the LLM.
        phases:      Frozenset of phases this tool is available in.
                     e.g. frozenset({"discover"}) or frozenset({"patch", "test"})
        callable_:   The async callable that executes the tool.
        simple_name: The bare name without namespace (e.g. "get_node").
                     Used for dual-key executor and for _find() lookups.
        namespace:   The domain prefix (e.g. "flowise", "workday").
    """

    tool_def: ToolDef
    phases: frozenset[str]
    callable_: Callable[..., Any]
    simple_name: str
    namespace: str


class ToolRegistry:
    """Namespaced, phase-gated registry of tools from all domains.

    Usage — manual registration:
        registry = ToolRegistry()
        registry.register(
            namespace="flowise",
            tool_def=ToolDef(name="get_node", description="...", parameters={...}),
            phases={"discover", "patch"},
            fn=my_async_fn,
        )

    Usage — bulk registration from a DomainTools instance:
        registry.register_domain(flowise_domain)
        # Registers all tools from discover/patch/test lists with correct phases.
        # Tools appearing in multiple phase lists get a merged phase set.

    Getting tools for the LLM (namespaced names):
        tool_defs = registry.tool_defs(phase="discover")
        # → [ToolDef(name="flowise__get_node", ...), ToolDef(name="patterns__search_patterns", ...)]

    Getting executor for graph.py (dual-keyed for backwards compat):
        executor = registry.executor(phase="discover")
        # → {"flowise__get_node": fn, "get_node": fn, "patterns__search_patterns": fn, ...}

    Getting merged system prompt additions:
        context = registry.context(phase="discover")
        # → "--- FLOWISE CONTEXT ---\\n...\\n\\n--- PATTERNS CONTEXT ---\\n..."

    Direct tool execution (returns ToolResult):
        result = await registry.call("flowise__get_node", {"name": "chatOpenAI"})
    """

    def __init__(self) -> None:
        self._entries: list[RegistryEntry] = []
        self._namespace_contexts: dict[tuple[str, str], str] = {}

    def register(
        self,
        namespace: str,
        tool_def: ToolDef,
        phases: set[str],
        fn: Callable[..., Any],
    ) -> None:
        """Register a single tool under a namespace.

        tool_def.name should be the simple (un-namespaced) name.
        The registry creates the namespaced name as "<namespace>__<tool_def.name>"
        and replaces the name in the stored ToolDef so the LLM sees namespaced names.

        If a tool with the same namespaced name already exists (e.g. from a prior call
        with different phases), the new entry replaces it. This allows re-registering
        a tool with an expanded phase set.
        """
        simple_name = tool_def.name
        namespaced_name = f"{namespace}__{simple_name}"

        # Replace existing entry for the same namespaced name (idempotent re-registration)
        self._entries = [
            e for e in self._entries
            if not (e.namespace == namespace and e.simple_name == simple_name)
        ]

        namespaced_td = ToolDef(
            name=namespaced_name,
            description=tool_def.description,
            parameters=tool_def.parameters,
        )
        self._entries.append(RegistryEntry(
            tool_def=namespaced_td,
            phases=frozenset(phases),
            callable_=fn,
            simple_name=simple_name,
            namespace=namespace,
        ))

    def register_domain(
        self,
        domain: "DomainTools",
        phases_map: dict[str, set[str]] | None = None,
    ) -> None:
        """Register all tools from a DomainTools instance with their default phases.

        Each tool is registered once even if it appears in multiple phase lists
        (e.g. get_chatflow appears in both discover and patch). Its phase set is
        the union of all lists it appears in.

        phases_map: optional override for specific tool names.
            E.g. {"get_chatflow": {"discover", "patch", "test"}} to add test phase.
            Tools not in phases_map use the default (inferred from domain.discover/patch/test).
        """
        # Build per-tool phase sets from DomainTools structure
        per_tool_phases: dict[str, set[str]] = {}
        for td in domain.discover:
            per_tool_phases.setdefault(td.name, set()).add("discover")
        for td in domain.patch:
            per_tool_phases.setdefault(td.name, set()).add("patch")
        for td in domain.test:
            per_tool_phases.setdefault(td.name, set()).add("test")

        # Deduplicate ToolDef objects (keep last definition for each tool name)
        seen_tds: dict[str, ToolDef] = {}
        for td in domain.discover + domain.patch + domain.test:
            seen_tds[td.name] = td

        for tool_name, td in seen_tds.items():
            fn = domain.executor.get(tool_name)
            if fn is None:
                continue
            override = phases_map.get(tool_name) if phases_map else None
            phases = override if override is not None else per_tool_phases.get(tool_name, set())
            self.register(
                namespace=domain.name,
                tool_def=td,
                phases=phases,
                fn=fn,
            )

    def register_context(self, namespace: str, phase: str, context: str) -> None:
        """Register a per-domain, per-phase system prompt addition.

        Called by DomainCapability implementations to attach their domain-specific
        guidance text (e.g. FLOWISE-SPECIFIC DISCOVERY RULES) to the registry.
        Retrieved via context(phase).
        """
        self._namespace_contexts[(namespace, phase)] = context

    def tool_defs(self, phase: str) -> list[ToolDef]:
        """Return all ToolDefs available for the given phase.

        Names are namespaced (e.g. "flowise__get_node") for unambiguous LLM tool calling.
        """
        return [e.tool_def for e in self._entries if phase in e.phases]

    def executor(self, phase: str) -> dict[str, Callable[..., Any]]:
        """Return an executor dict for the given phase.

        Dual-keyed for backwards compatibility (DD-049):
          "flowise__get_node" → fn  (namespaced, used by LLM in v2 sessions)
          "get_node"          → fn  (simple, used by legacy code)

        When two domains have a tool with the same simple name (e.g. both "get_node"),
        the last registered domain's callable wins for the simple key. The namespaced
        keys are always unambiguous.
        """
        result: dict[str, Callable[..., Any]] = {}
        for e in self._entries:
            if phase in e.phases:
                result[e.tool_def.name] = e.callable_   # "flowise.get_node"
                result[e.simple_name] = e.callable_     # "get_node" (backwards compat)
        return result

    def context(self, phase: str) -> str:
        """Return merged domain context text for the given phase.

        Each domain's context is prefixed with '--- DOMAIN CONTEXT ---'.
        Used by _build_system_prompt() in graph.py.
        """
        parts: list[str] = []
        seen_namespaces: set[str] = set()
        for e in self._entries:
            if phase in e.phases and e.namespace not in seen_namespaces:
                seen_namespaces.add(e.namespace)
                ctx = self._namespace_contexts.get((e.namespace, phase), "")
                if ctx.strip():
                    parts.append(f"--- {e.namespace.upper()} CONTEXT ---\n{ctx.strip()}")
        return "\n\n".join(parts)

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> "ToolResult":
        """Execute a tool by name (namespaced or simple) and return a ToolResult.

        Used by DomainCapability implementations that want structured ToolResult
        objects directly (e.g. for structured discover() output). The graph's
        _react loop continues to use execute_tool() via executor() which also
        produces ToolResults internally.

        Returns a ToolResult with ok=False if the tool is not found.
        """
        from flowise_dev_agent.agent.tools import ToolResult, execute_tool

        entry = self._find(tool_name)
        if entry is None:
            return ToolResult(
                ok=False,
                summary=f"Unknown tool: {tool_name!r}",
                facts={},
                data=None,
                error={
                    "type": "UnknownTool",
                    "message": f"No tool named {tool_name!r} in registry",
                    "detail": None,
                },
                artifacts=None,
            )
        return await execute_tool(
            tool_name,
            arguments,
            {tool_name: entry.callable_},
        )

    def _find(self, tool_name: str) -> RegistryEntry | None:
        """Find an entry by namespaced or simple name. Returns None if not found."""
        for e in self._entries:
            if e.tool_def.name == tool_name or e.simple_name == tool_name:
                return e
        return None

    def __repr__(self) -> str:
        namespaces = sorted({e.namespace for e in self._entries})
        return (
            f"ToolRegistry(namespaces={namespaces!r}, "
            f"tools={[e.tool_def.name for e in self._entries]!r})"
        )
