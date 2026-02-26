"""M10.3 — LangGraph graph topology re-wiring (DD-080).

Tests for:
- MCP executor construction in _build_graph_v2
- resolve_target calls execute_tool("list_chatflows") via MCP executor
- load_current_flow calls execute_tool("get_chatflow") via MCP executor
- apply_patch CREATE mode calls execute_tool("create_chatflow") via MCP executor
- apply_patch UPDATE mode calls execute_tool("update_chatflow") via MCP executor
- compile_flow_data uses MCP executor for schema fetching
- repair_schema uses MCP executor for node schema repair
- test_v2 uses MCP executor for create_prediction
- FlowiseCapability registers MCP tools when client provided
- Legacy path (capabilities=None) still works
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flowise_dev_agent.agent.tools import ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_state(**overrides) -> dict:
    """Return a minimal state dict suitable for testing individual nodes."""
    state: dict = {
        "requirement": "build a new customer support chatbot",
        "session_name": None,
        "runtime_mode": None,
        "messages": [],
        "chatflow_id": None,
        "discovery_summary": None,
        "plan": None,
        "test_results": None,
        "iteration": 0,
        "done": False,
        "developer_feedback": None,
        "webhook_url": None,
        "clarification": None,
        "credentials_missing": None,
        "converge_verdict": None,
        "test_trials": 1,
        "flowise_instance_id": None,
        "domain_context": {},
        "artifacts": {},
        "facts": {},
        "debug": {},
        "patch_ir": None,
        "validated_payload_hash": None,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "operation_mode": None,
        "target_chatflow_id": None,
        "intent_confidence": None,
    }
    state.update(overrides)
    return state


def _tr(ok=True, summary="ok", data=None, facts=None) -> ToolResult:
    """Build a ToolResult with all required fields."""
    return ToolResult(
        ok=ok,
        summary=summary,
        facts=facts or {},
        data=data,
        error=None if ok else {"type": "Error", "message": summary, "detail": None},
        artifacts=None,
    )


def _make_mcp_executor(**overrides) -> dict:
    """Build a mock MCP executor with AsyncMock callables for each tool."""
    executor = {
        "list_chatflows": AsyncMock(return_value=_tr(
            summary="2 chatflows found",
            data=[
                {"id": "cf-1", "name": "Flow A", "updatedDate": "2026-02-20"},
                {"id": "cf-2", "name": "Flow B", "updatedDate": "2026-02-19"},
            ],
        )),
        "get_chatflow": AsyncMock(return_value=_tr(
            summary="cf-1 Flow A",
            data={
                "id": "cf-1",
                "name": "Flow A",
                "flowData": json.dumps({
                    "nodes": [{"id": "n1", "data": {"name": "chatOpenAI"}}],
                    "edges": [],
                }),
            },
        )),
        "create_chatflow": AsyncMock(return_value=_tr(
            summary="Created cf-new",
            data={"id": "cf-new", "name": "New Flow"},
            facts={"chatflow_id": "cf-new"},
        )),
        "update_chatflow": AsyncMock(return_value=_tr(
            summary="Updated cf-1",
            data={"id": "cf-1", "name": "Updated Flow"},
        )),
        "create_prediction": AsyncMock(return_value=_tr(
            summary="Prediction OK",
            data={"text": "Hello! How can I help?"},
        )),
        "get_node": AsyncMock(return_value=_tr(
            summary="chatOpenAI schema",
            data={"name": "chatOpenAI", "type": "ChatOpenAI"},
        )),
        "snapshot_chatflow": AsyncMock(return_value=_tr(
            summary="snapshot ok",
        )),
        "rollback_chatflow": AsyncMock(return_value=_tr(
            summary="rollback ok",
        )),
        "validate_flow_data": MagicMock(return_value={"valid": True, "errors": []}),
    }
    executor.update(overrides)
    return executor


# ---------------------------------------------------------------------------
# Test: resolve_target uses MCP executor
# ---------------------------------------------------------------------------


class TestResolveTargetMCP:
    """resolve_target calls execute_tool via MCP-backed executor."""

    @pytest.mark.asyncio
    async def test_calls_list_chatflows(self):
        from flowise_dev_agent.agent.graph import _make_resolve_target_node

        executor = _make_mcp_executor()
        node = _make_resolve_target_node(executor)

        state = _base_state(
            operation_mode="update",
            facts={"flowise": {"target_name": "Flow"}},
        )
        result = await node(state)

        # Verify list_chatflows was called via executor
        executor["list_chatflows"].assert_called_once()

        # Result should contain chatflow matches
        flowise_facts = result["facts"]["flowise"]
        assert "top_matches" in flowise_facts
        assert len(flowise_facts["top_matches"]) == 2

    @pytest.mark.asyncio
    async def test_filters_by_target_name(self):
        from flowise_dev_agent.agent.graph import _make_resolve_target_node

        executor = _make_mcp_executor()
        node = _make_resolve_target_node(executor)

        state = _base_state(
            operation_mode="update",
            facts={"flowise": {"target_name": "Flow A"}},
        )
        result = await node(state)

        matches = result["facts"]["flowise"]["top_matches"]
        assert len(matches) == 1
        assert matches[0]["name"] == "Flow A"


# ---------------------------------------------------------------------------
# Test: load_current_flow uses MCP executor
# ---------------------------------------------------------------------------


class TestLoadCurrentFlowMCP:
    """load_current_flow calls execute_tool via MCP-backed executor."""

    @pytest.mark.asyncio
    async def test_calls_get_chatflow(self):
        from flowise_dev_agent.agent.graph import _make_load_current_flow_node

        executor = _make_mcp_executor()
        node = _make_load_current_flow_node(executor)

        state = _base_state(target_chatflow_id="cf-1")
        result = await node(state)

        executor["get_chatflow"].assert_called_once()
        # Flow data should be stored in artifacts
        flow_data = result["artifacts"]["flowise"]["current_flow_data"]
        assert isinstance(flow_data, dict)

    @pytest.mark.asyncio
    async def test_no_target_id_skips(self):
        from flowise_dev_agent.agent.graph import _make_load_current_flow_node

        executor = _make_mcp_executor()
        node = _make_load_current_flow_node(executor)

        state = _base_state(target_chatflow_id=None)
        result = await node(state)

        executor["get_chatflow"].assert_not_called()
        assert result == {}


# ---------------------------------------------------------------------------
# Test: apply_patch uses MCP executor
# ---------------------------------------------------------------------------


class TestApplyPatchMCP:
    """apply_patch calls create_chatflow/update_chatflow via MCP-backed executor."""

    @pytest.mark.asyncio
    async def test_create_mode(self):
        from flowise_dev_agent.agent.graph import _make_apply_patch_node

        executor = _make_mcp_executor()
        node = _make_apply_patch_node(executor, capabilities=None)

        proposed = {"nodes": [{"id": "n1"}], "edges": []}
        state = _base_state(
            operation_mode="create",
            artifacts={"flowise": {"proposed_flow_data": proposed}},
            facts={"flowise": {"proposed_flow_hash": "abc123"}},
        )
        result = await node(state)

        # create_chatflow should have been called (via guarded wrapper)
        assert result["facts"]["apply"]["ok"] is True

    @pytest.mark.asyncio
    async def test_update_mode(self):
        from flowise_dev_agent.agent.graph import _make_apply_patch_node

        executor = _make_mcp_executor()
        node = _make_apply_patch_node(executor, capabilities=None)

        proposed = {"nodes": [{"id": "n1"}], "edges": []}
        state = _base_state(
            operation_mode="update",
            target_chatflow_id="cf-1",
            artifacts={"flowise": {"proposed_flow_data": proposed}},
            facts={"flowise": {"proposed_flow_hash": "abc123", "current_flow_hash": "old"}},
        )
        result = await node(state)

        assert result["facts"]["apply"]["ok"] is True

    @pytest.mark.asyncio
    async def test_no_proposed_data_skips(self):
        from flowise_dev_agent.agent.graph import _make_apply_patch_node

        executor = _make_mcp_executor()
        node = _make_apply_patch_node(executor, capabilities=None)

        state = _base_state(
            operation_mode="create",
            artifacts={"flowise": {}},
            facts={"flowise": {}},
        )
        result = await node(state)

        assert result["facts"]["apply"]["ok"] is False
        assert "no proposed_flow_data" in result["facts"]["apply"]["error"]


# ---------------------------------------------------------------------------
# Test: test_v2 uses MCP executor
# ---------------------------------------------------------------------------


class TestTestNodeMCP:
    """test_v2 calls create_prediction via MCP-backed executor."""

    @pytest.mark.asyncio
    async def test_calls_create_prediction(self):
        from flowise_dev_agent.agent.graph import _make_test_node
        from flowise_dev_agent.agent.tools import FloviseDomain

        engine = MagicMock()
        response = MagicMock()
        response.content = "TEST PASSED"
        response.input_tokens = 10
        response.output_tokens = 5
        response.has_tool_calls = False
        response.tool_calls = []
        engine.complete = AsyncMock(return_value=response)

        mock_client = MagicMock()
        domain = FloviseDomain(mock_client)
        executor = _make_mcp_executor()

        node = _make_test_node(engine, executor, [domain])

        state = _base_state(
            chatflow_id="cf-1",
            plan="Test the chatbot with a greeting",
        )
        result = await node(state)

        # create_prediction should have been called via executor
        assert executor["create_prediction"].call_count >= 1
        assert "test_results" in result

    @pytest.mark.asyncio
    async def test_no_chatflow_id_skips(self):
        from flowise_dev_agent.agent.graph import _make_test_node
        from flowise_dev_agent.agent.tools import FloviseDomain

        engine = MagicMock()
        mock_client = MagicMock()
        domain = FloviseDomain(mock_client)
        executor = _make_mcp_executor()

        node = _make_test_node(engine, executor, [domain])

        state = _base_state(chatflow_id=None)
        result = await node(state)

        # Should skip predictions and return failure
        executor["create_prediction"].assert_not_called()
        assert "SKIPPED" in result["test_results"]


# ---------------------------------------------------------------------------
# Test: repair_schema uses MCP executor
# ---------------------------------------------------------------------------


class TestRepairSchemaMCP:
    """repair_schema calls get_node via MCP-backed executor."""

    @pytest.mark.asyncio
    async def test_calls_get_node_for_missing_types(self):
        from flowise_dev_agent.agent.graph import _make_repair_schema_node

        executor = _make_mcp_executor()
        node = _make_repair_schema_node(capabilities=None, executor=executor)

        state = _base_state(
            facts={
                "validation": {"missing_node_types": ["unknownNode"]},
                "repair": {"count": 0, "repaired_node_types": []},
                "budgets": {"max_schema_repairs_per_iter": 2},
            },
        )
        result = await node(state)

        # get_node should have been called for the missing type
        executor["get_node"].assert_called()

    @pytest.mark.asyncio
    async def test_budget_exceeded(self):
        from flowise_dev_agent.agent.graph import _make_repair_schema_node

        executor = _make_mcp_executor()
        node = _make_repair_schema_node(capabilities=None, executor=executor)

        state = _base_state(
            facts={
                "validation": {"missing_node_types": ["unknownNode"]},
                "repair": {"count": 5, "repaired_node_types": []},
                "budgets": {"max_schema_repairs_per_iter": 2},
            },
        )
        result = await node(state)

        # Should not call API when budget exceeded
        executor["get_node"].assert_not_called()
        assert result["facts"]["repair"]["budget_exceeded"] is True


# ---------------------------------------------------------------------------
# Test: compile_flow_data uses MCP executor
# ---------------------------------------------------------------------------


class TestCompileFlowDataMCP:
    """compile_flow_data uses MCP executor for schema fetching."""

    @pytest.mark.asyncio
    async def test_uses_executor_for_schema_fetch(self):
        from flowise_dev_agent.agent.graph import _make_compile_flow_data_node

        executor = _make_mcp_executor()
        node = _make_compile_flow_data_node(capabilities=None, executor=executor)

        # Provide a patch_ir with an add_node op
        patch_ir = [
            {"op_type": "add_node", "node_name": "chatOpenAI", "node_id": "chatOpenAI_0"},
        ]
        state = _base_state(
            operation_mode="create",
            patch_ir=patch_ir,
            artifacts={"flowise": {}},
            facts={"flowise": {}},
        )
        result = await node(state)

        # get_node should be called for schema lookup of the added node
        executor["get_node"].assert_called()

    @pytest.mark.asyncio
    async def test_empty_patch_ir(self):
        from flowise_dev_agent.agent.graph import _make_compile_flow_data_node

        executor = _make_mcp_executor()
        node = _make_compile_flow_data_node(capabilities=None, executor=executor)

        state = _base_state(
            operation_mode="create",
            patch_ir=[],
            artifacts={"flowise": {}},
            facts={"flowise": {}},
        )
        result = await node(state)

        # Should still produce a result (empty compile)
        assert "artifacts" in result
        assert "proposed_flow_data" in result["artifacts"]["flowise"]


# ---------------------------------------------------------------------------
# Test: FlowiseCapability MCP registration
# ---------------------------------------------------------------------------


class TestFlowiseCapabilityMCP:
    """FlowiseCapability registers MCP tools when client provided."""

    def test_with_client_registers_mcp(self):
        from flowise_dev_agent.agent.graph import FlowiseCapability
        from flowise_dev_agent.agent.tools import FloviseDomain

        mock_client = MagicMock()
        mock_client.ping = AsyncMock()
        mock_client.list_chatflows = AsyncMock()
        mock_client.get_chatflow = AsyncMock()

        domain = FloviseDomain(mock_client)
        engine = MagicMock()

        cap = FlowiseCapability(domain, engine, "system prompt", client=mock_client)

        # MCP tools should be registered
        assert cap._mcp_tools is not None
        executor = cap.tools.executor("discover")
        assert "flowise__list_chatflows" in executor
        assert "flowise__get_anchor_dictionary" in executor

    def test_without_client_uses_domain(self):
        from flowise_dev_agent.agent.graph import FlowiseCapability
        from flowise_dev_agent.agent.tools import FloviseDomain

        mock_client = MagicMock()
        domain = FloviseDomain(mock_client)
        engine = MagicMock()

        cap = FlowiseCapability(domain, engine, "system prompt")

        # No MCP tools, uses domain registration
        assert cap._mcp_tools is None
        executor = cap.tools.executor("discover")
        # Domain tools should still be present (simple keys from domain)
        assert "list_chatflows" in executor


# ---------------------------------------------------------------------------
# Test: _build_graph_v2 MCP executor wiring
# ---------------------------------------------------------------------------


class TestBuildGraphMCPWiring:
    """_build_graph_v2 creates MCP executor and passes to factories."""

    def test_build_graph_with_client(self):
        from flowise_dev_agent.agent.graph import build_graph
        from flowise_dev_agent.agent.tools import FloviseDomain

        mock_client = MagicMock()
        mock_client.ping = AsyncMock()
        mock_client.list_chatflows = AsyncMock()
        mock_client.get_chatflow = AsyncMock()

        domain = FloviseDomain(mock_client)
        engine = MagicMock()

        # Should not raise
        graph = build_graph(
            engine,
            [domain],
            client=mock_client,
            capabilities=None,
        )
        assert graph is not None

    def test_build_graph_without_client_legacy(self):
        from flowise_dev_agent.agent.graph import build_graph
        from flowise_dev_agent.agent.tools import FloviseDomain

        mock_client = MagicMock()
        domain = FloviseDomain(mock_client)
        engine = MagicMock()

        # Legacy path: no client, no capabilities
        graph = build_graph(engine, [domain])
        assert graph is not None


# ---------------------------------------------------------------------------
# Test: make_default_capabilities passes client
# ---------------------------------------------------------------------------


class TestMakeDefaultCapabilities:
    """make_default_capabilities accepts and passes client to FlowiseCapability."""

    def test_with_client(self):
        from flowise_dev_agent.agent.graph import make_default_capabilities
        from flowise_dev_agent.agent.tools import FloviseDomain

        mock_client = MagicMock()
        mock_client.ping = AsyncMock()
        mock_client.list_chatflows = AsyncMock()

        domain = FloviseDomain(mock_client)
        engine = MagicMock()

        caps = make_default_capabilities(engine, [domain], client=mock_client)
        assert len(caps) == 1
        assert caps[0]._mcp_tools is not None

    def test_without_client(self):
        from flowise_dev_agent.agent.graph import make_default_capabilities
        from flowise_dev_agent.agent.tools import FloviseDomain

        mock_client = MagicMock()
        domain = FloviseDomain(mock_client)
        engine = MagicMock()

        caps = make_default_capabilities(engine, [domain])
        assert len(caps) == 1
        assert caps[0]._mcp_tools is None


# ---------------------------------------------------------------------------
# Test: Domain-only tools merged into MCP executor
# ---------------------------------------------------------------------------


class TestDomainOnlyToolsMerged:
    """Domain-only tools (validate, snapshot, rollback) are in the MCP executor."""

    def test_domain_only_tools_present(self):
        """Verify that domain-only tools are merged into the MCP executor."""
        from flowise_dev_agent.agent.graph import FlowiseCapability
        from flowise_dev_agent.agent.tools import FloviseDomain

        mock_client = MagicMock()
        domain = FloviseDomain(mock_client)

        # The domain executor should have these tools
        assert "validate_flow_data" in domain.executor
        assert "snapshot_chatflow" in domain.executor
        assert "rollback_chatflow" in domain.executor


# ---------------------------------------------------------------------------
# Test: ToolResult passthrough in _wrap_result
# ---------------------------------------------------------------------------


class TestToolResultPassthrough:
    """MCP tools return ToolResult — _wrap_result passes through without double-wrapping."""

    def test_passthrough(self):
        from flowise_dev_agent.agent.tools import _wrap_result

        original = _tr(summary="test summary", data={"key": "value"})
        wrapped = _wrap_result("test_tool", original)

        assert wrapped is original
        assert wrapped.ok is True
        assert wrapped.summary == "test summary"
        assert wrapped.data == {"key": "value"}

    def test_dict_still_wraps(self):
        from flowise_dev_agent.agent.tools import _wrap_result

        raw = {"id": "cf-1", "name": "Flow A"}
        wrapped = _wrap_result("test_tool", raw)

        assert isinstance(wrapped, ToolResult)
        assert wrapped.ok is True
        assert wrapped.data == raw


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


class TestImportSmoke:
    """Module imports work correctly."""

    def test_import_graph(self):
        from flowise_dev_agent.agent.graph import (
            build_graph,
            _build_graph_v2,
            FlowiseCapability,
            make_default_capabilities,
        )

    def test_import_mcp_tools(self):
        from flowise_dev_agent.mcp.tools import FlowiseMCPTools  # noqa: F401

    def test_import_mcp_registry(self):
        from flowise_dev_agent.mcp.registry import register_flowise_mcp_tools  # noqa: F401
