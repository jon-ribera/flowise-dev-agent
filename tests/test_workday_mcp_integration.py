"""Integration smoke tests for Milestone 7.5 — Workday Custom MCP wiring.

Covers the acceptance tests from the roadmap:
  Test group 1 — WorkdayMcpStore blueprint loading + search.
  Test group 2 — WorkdayCapability.discover() facts.
  Test group 3 — WorkdayCapability.compile_ops() Patch IR structure.
  Test group 4 — validate_patch_ops() passes on produced ops.
  Test group 5 — mcpServerConfig is a STRING with correct keys.
  Test group 6 — refresh_workday_mcp() writes snapshot.

All tests use mocked / in-memory data — no live Flowise or Workday API calls.

See roadmap7_multi_domain_runtime_hardening.md — Milestone 7.5.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from flowise_dev_agent.agent.domains.workday import (
    WorkdayCapability,
    _MCP_AUTH_VAR,
    _MCP_CREDENTIAL_PLACEHOLDER,
    _MCP_CREDENTIAL_TYPE,
    _MCP_DEFAULT_ACTIONS,
    _MCP_SELECTED_TOOL,
    _MCP_TOOL_NODE_ID,
    _MCP_TOOL_NODE_NAME,
    _build_mcp_server_config_str,
)
from flowise_dev_agent.agent.patch_ir import AddNode, BindCredential, validate_patch_ops
from flowise_dev_agent.knowledge.workday_provider import (
    WorkdayKnowledgeProvider,
    WorkdayMcpStore,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_BLUEPRINT = {
    "blueprint_id": "workday_default",
    "description": "Default Workday MCP actions for worker lookup and self-service",
    "selected_tool": "customMCP",
    "mcp_server_url_placeholder": "https://<tenant>.workday.com/mcp",
    "auth_var": "$vars.beartoken",
    "mcp_actions": ["getMyInfo", "searchForWorker", "getWorkers"],
    "credential_type": "workdayOAuth",
    "chatflow_only": True,
    "category": "HR",
    "tags": ["workday", "mcp", "worker", "hr", "custom-mcp"],
}


def _write_snapshot(path: Path, blueprints: list[dict]) -> None:
    path.write_text(json.dumps(blueprints, indent=2), encoding="utf-8")


@pytest.fixture
def tmp_snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "workday_mcp.snapshot.json"
    _write_snapshot(snap, [_SAMPLE_BLUEPRINT])
    return snap


@pytest.fixture
def mcp_store(tmp_snapshot: Path, tmp_path: Path) -> WorkdayMcpStore:
    return WorkdayMcpStore(
        snapshot_path=tmp_snapshot,
        meta_path=tmp_path / "workday_mcp.meta.json",
    )


@pytest.fixture
def workday_cap(tmp_snapshot: Path, tmp_path: Path) -> WorkdayCapability:
    """WorkdayCapability wired to the tmp snapshot via a real provider."""
    provider = WorkdayKnowledgeProvider(schemas_dir=tmp_path)
    # Populate the store's snapshot
    _write_snapshot(tmp_snapshot, [_SAMPLE_BLUEPRINT])
    return WorkdayCapability(knowledge_provider=provider)


# ---------------------------------------------------------------------------
# Test group 1 — WorkdayMcpStore
# ---------------------------------------------------------------------------


class TestWorkdayMcpStore:

    def test_item_count_loads_from_snapshot(self, mcp_store: WorkdayMcpStore):
        assert mcp_store.item_count == 1

    def test_get_by_blueprint_id(self, mcp_store: WorkdayMcpStore):
        bp = mcp_store.get("workday_default")
        assert bp is not None
        assert bp["blueprint_id"] == "workday_default"

    def test_get_returns_none_for_unknown_id(self, mcp_store: WorkdayMcpStore):
        assert mcp_store.get("does_not_exist") is None

    def test_find_returns_matching_blueprint(self, mcp_store: WorkdayMcpStore):
        results = mcp_store.find(["workday", "worker"], limit=3)
        assert len(results) == 1
        assert results[0]["blueprint_id"] == "workday_default"

    def test_find_with_no_keywords_returns_all(self, mcp_store: WorkdayMcpStore):
        results = mcp_store.find([], limit=5)
        assert len(results) == 1

    def test_find_returns_empty_for_no_match(self, mcp_store: WorkdayMcpStore):
        results = mcp_store.find(["salesforce", "crm"], limit=3)
        assert results == []

    def test_is_stale_without_meta_file(self, mcp_store: WorkdayMcpStore):
        # No meta file exists → not stale by assumption
        assert mcp_store.is_stale() is False

    def test_empty_snapshot_gives_zero_count(self, tmp_path: Path):
        snap = tmp_path / "empty.json"
        _write_snapshot(snap, [])
        store = WorkdayMcpStore(snapshot_path=snap, meta_path=tmp_path / "m.json")
        assert store.item_count == 0

    def test_missing_snapshot_gives_zero_count(self, tmp_path: Path):
        store = WorkdayMcpStore(
            snapshot_path=tmp_path / "missing.json",
            meta_path=tmp_path / "m.json",
        )
        assert store.item_count == 0


# ---------------------------------------------------------------------------
# Test group 2 — WorkdayCapability.discover()
# ---------------------------------------------------------------------------


class TestWorkdayCapabilityDiscover:

    @pytest.mark.asyncio
    async def test_discover_returns_non_stub_result(self, workday_cap: WorkdayCapability):
        result = await workday_cap.discover({"requirement": "search for worker"})
        assert result.facts.get("stub") is None  # not a stub result

    @pytest.mark.asyncio
    async def test_discover_facts_contain_mcp_mode(self, workday_cap: WorkdayCapability):
        result = await workday_cap.discover({"requirement": "find worker info"})
        assert result.facts["mcp_mode"] == "customMCP"

    @pytest.mark.asyncio
    async def test_discover_facts_contain_mcp_actions(self, workday_cap: WorkdayCapability):
        result = await workday_cap.discover({"requirement": "list workers"})
        assert result.facts["mcp_actions"] == _MCP_DEFAULT_ACTIONS

    @pytest.mark.asyncio
    async def test_discover_facts_contain_credential_type(self, workday_cap: WorkdayCapability):
        result = await workday_cap.discover({"requirement": "get my workday info"})
        assert result.facts["credential_type"] == "workdayOAuth"

    @pytest.mark.asyncio
    async def test_discover_facts_contain_mcp_server_url(self, workday_cap: WorkdayCapability):
        result = await workday_cap.discover({"requirement": "workday mcp"})
        assert "mcp_server_url" in result.facts
        assert "<tenant>" in result.facts["mcp_server_url"]

    @pytest.mark.asyncio
    async def test_discover_facts_contain_auth_var(self, workday_cap: WorkdayCapability):
        result = await workday_cap.discover({"requirement": "hr worker lookup"})
        assert result.facts["auth_var"] == "$vars.beartoken"

    @pytest.mark.asyncio
    async def test_discover_artifacts_contain_selected_tool(self, workday_cap: WorkdayCapability):
        result = await workday_cap.discover({"requirement": "workday"})
        assert result.artifacts["selected_tool"] == "customMCP"

    @pytest.mark.asyncio
    async def test_discover_summary_mentions_actions(self, workday_cap: WorkdayCapability):
        result = await workday_cap.discover({"requirement": "worker"})
        assert "getMyInfo" in result.summary or "action" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_discover_falls_back_to_defaults_on_empty_snapshot(self, tmp_path: Path):
        """When the snapshot is empty, discover() uses module-level defaults."""
        snap = tmp_path / "workday_mcp.snapshot.json"
        _write_snapshot(snap, [])
        provider = WorkdayKnowledgeProvider(schemas_dir=tmp_path)
        cap = WorkdayCapability(knowledge_provider=provider)
        result = await cap.discover({"requirement": "workday worker"})
        assert result.facts["mcp_mode"] == "customMCP"
        assert result.facts["mcp_actions"] == _MCP_DEFAULT_ACTIONS


# ---------------------------------------------------------------------------
# Test group 3 — WorkdayCapability.compile_ops() structure
# ---------------------------------------------------------------------------


class TestWorkdayCompileOpsStructure:

    @pytest.mark.asyncio
    async def test_compile_ops_not_stub(self, workday_cap: WorkdayCapability):
        result = await workday_cap.compile_ops("build a chatflow using Workday MCP")
        assert result.stub is False

    @pytest.mark.asyncio
    async def test_compile_ops_has_two_ops(self, workday_cap: WorkdayCapability):
        result = await workday_cap.compile_ops("hire employee via Workday")
        assert len(result.ops) == 2

    @pytest.mark.asyncio
    async def test_compile_ops_first_op_is_add_node(self, workday_cap: WorkdayCapability):
        result = await workday_cap.compile_ops("worker lookup")
        assert isinstance(result.ops[0], AddNode)

    @pytest.mark.asyncio
    async def test_compile_ops_second_op_is_bind_credential(self, workday_cap: WorkdayCapability):
        result = await workday_cap.compile_ops("worker lookup")
        assert isinstance(result.ops[1], BindCredential)

    @pytest.mark.asyncio
    async def test_add_node_has_correct_node_name(self, workday_cap: WorkdayCapability):
        result = await workday_cap.compile_ops("Workday MCP chatflow")
        add_op = result.ops[0]
        assert isinstance(add_op, AddNode)
        assert add_op.node_name == _MCP_TOOL_NODE_NAME

    @pytest.mark.asyncio
    async def test_add_node_has_correct_node_id(self, workday_cap: WorkdayCapability):
        result = await workday_cap.compile_ops("Workday MCP chatflow")
        add_op = result.ops[0]
        assert isinstance(add_op, AddNode)
        assert add_op.node_id == _MCP_TOOL_NODE_ID

    @pytest.mark.asyncio
    async def test_add_node_selected_tool_is_custom_mcp(self, workday_cap: WorkdayCapability):
        result = await workday_cap.compile_ops("build chatflow")
        add_op = result.ops[0]
        assert isinstance(add_op, AddNode)
        assert add_op.params["selectedTool"] == "customMCP"

    @pytest.mark.asyncio
    async def test_add_node_mcp_actions_are_default(self, workday_cap: WorkdayCapability):
        result = await workday_cap.compile_ops("lookup worker profile")
        add_op = result.ops[0]
        assert isinstance(add_op, AddNode)
        actions = add_op.params["selectedToolConfig.mcpActions"]
        assert actions == _MCP_DEFAULT_ACTIONS

    @pytest.mark.asyncio
    async def test_add_node_mcp_actions_mentions_specific_if_in_plan(
        self, workday_cap: WorkdayCapability
    ):
        """When plan mentions a specific action, only that one should be returned (or all)."""
        result = await workday_cap.compile_ops(
            "I only need getMyInfo from Workday, nothing else"
        )
        add_op = result.ops[0]
        assert isinstance(add_op, AddNode)
        actions = add_op.params["selectedToolConfig.mcpActions"]
        # getMyInfo is in the plan — it should be the only action or part of the list
        assert "getMyInfo" in actions

    @pytest.mark.asyncio
    async def test_bind_credential_has_correct_type(self, workday_cap: WorkdayCapability):
        result = await workday_cap.compile_ops("Workday")
        bind_op = result.ops[1]
        assert isinstance(bind_op, BindCredential)
        assert bind_op.credential_type == "workdayOAuth"

    @pytest.mark.asyncio
    async def test_bind_credential_has_non_empty_id(self, workday_cap: WorkdayCapability):
        """credential_id must be non-empty (placeholder) so validate_patch_ops passes."""
        result = await workday_cap.compile_ops("Workday")
        bind_op = result.ops[1]
        assert isinstance(bind_op, BindCredential)
        assert bind_op.credential_id  # non-empty

    @pytest.mark.asyncio
    async def test_bind_credential_node_id_matches_add_node(
        self, workday_cap: WorkdayCapability
    ):
        result = await workday_cap.compile_ops("Workday")
        add_op = result.ops[0]
        bind_op = result.ops[1]
        assert isinstance(add_op, AddNode)
        assert isinstance(bind_op, BindCredential)
        assert bind_op.node_id == add_op.node_id


# ---------------------------------------------------------------------------
# Test group 4 — validate_patch_ops() on produced ops
# ---------------------------------------------------------------------------


class TestWorkdayOpsValidation:

    @pytest.mark.asyncio
    async def test_validate_patch_ops_returns_no_errors(self, workday_cap: WorkdayCapability):
        result = await workday_cap.compile_ops("Workday hire employee chatflow")
        errors = validate_patch_ops(result.ops)
        assert errors == [], f"Unexpected validation errors: {errors}"

    @pytest.mark.asyncio
    async def test_compile_ops_message_is_non_empty(self, workday_cap: WorkdayCapability):
        result = await workday_cap.compile_ops("Workday MCP")
        assert result.message  # non-empty string

    @pytest.mark.asyncio
    async def test_compiled_ops_list_has_add_node_before_bind_credential(
        self, workday_cap: WorkdayCapability
    ):
        """AddNode must precede BindCredential for validate_patch_ops to resolve the node_id."""
        result = await workday_cap.compile_ops("Workday")
        first_add = next(
            (i for i, op in enumerate(result.ops) if isinstance(op, AddNode)), None
        )
        first_bind = next(
            (i for i, op in enumerate(result.ops) if isinstance(op, BindCredential)), None
        )
        assert first_add is not None
        assert first_bind is not None
        assert first_add < first_bind, "AddNode must come before BindCredential"


# ---------------------------------------------------------------------------
# Test group 5 — mcpServerConfig is a STRING with correct structure
# ---------------------------------------------------------------------------


class TestMcpServerConfigFormat:

    def test_build_mcp_server_config_str_returns_string(self):
        result = _build_mcp_server_config_str(
            "https://tenant.workday.com/mcp", "$vars.beartoken"
        )
        assert isinstance(result, str)

    def test_build_mcp_server_config_str_is_valid_json(self):
        result = _build_mcp_server_config_str(
            "https://tenant.workday.com/mcp", "$vars.beartoken"
        )
        parsed = json.loads(result)  # must not raise
        assert isinstance(parsed, dict)

    def test_build_mcp_server_config_str_has_url_key(self):
        result = _build_mcp_server_config_str(
            "https://tenant.workday.com/mcp", "$vars.beartoken"
        )
        parsed = json.loads(result)
        assert "url" in parsed

    def test_build_mcp_server_config_str_has_authorization_header(self):
        result = _build_mcp_server_config_str(
            "https://tenant.workday.com/mcp", "$vars.beartoken"
        )
        parsed = json.loads(result)
        assert "headers" in parsed
        assert "Authorization" in parsed["headers"]

    def test_build_mcp_server_config_str_authorization_value_is_auth_var(self):
        auth_var = "$vars.beartoken"
        result = _build_mcp_server_config_str("https://x.workday.com/mcp", auth_var)
        parsed = json.loads(result)
        assert parsed["headers"]["Authorization"] == auth_var

    @pytest.mark.asyncio
    async def test_compile_ops_mcp_server_config_is_a_string(
        self, workday_cap: WorkdayCapability
    ):
        result = await workday_cap.compile_ops("Workday chatflow")
        add_op = result.ops[0]
        assert isinstance(add_op, AddNode)
        mcp_config = add_op.params["selectedToolConfig.mcpServerConfig"]
        assert isinstance(mcp_config, str), (
            "mcpServerConfig must be a STRING (Flowise persists it as stringified JSON), "
            f"got {type(mcp_config).__name__}"
        )

    @pytest.mark.asyncio
    async def test_compile_ops_mcp_server_config_contains_url(
        self, workday_cap: WorkdayCapability
    ):
        result = await workday_cap.compile_ops("Workday chatflow")
        add_op = result.ops[0]
        assert isinstance(add_op, AddNode)
        mcp_config_str = add_op.params["selectedToolConfig.mcpServerConfig"]
        parsed = json.loads(mcp_config_str)
        assert "url" in parsed

    @pytest.mark.asyncio
    async def test_compile_ops_mcp_server_config_contains_authorization(
        self, workday_cap: WorkdayCapability
    ):
        result = await workday_cap.compile_ops("Workday chatflow")
        add_op = result.ops[0]
        assert isinstance(add_op, AddNode)
        mcp_config_str = add_op.params["selectedToolConfig.mcpServerConfig"]
        parsed = json.loads(mcp_config_str)
        assert parsed["headers"]["Authorization"] == _MCP_AUTH_VAR


# ---------------------------------------------------------------------------
# Test group 6 — refresh_workday_mcp()
# ---------------------------------------------------------------------------


class TestRefreshWorkdayMcp:

    def test_refresh_writes_snapshot(self, tmp_path: Path, monkeypatch):
        """refresh_workday_mcp() writes snapshot + meta files."""
        import flowise_dev_agent.knowledge.refresh as refresh_mod

        snap = tmp_path / "workday_mcp.snapshot.json"
        meta = tmp_path / "workday_mcp.meta.json"

        monkeypatch.setattr(refresh_mod, "_SCHEMAS_DIR", tmp_path)
        monkeypatch.setattr(refresh_mod, "_REPO_ROOT", tmp_path)
        monkeypatch.delenv("WORKDAY_MCP_CATALOG_PATH", raising=False)

        exit_code = refresh_mod.refresh_workday_mcp(dry_run=False)

        assert exit_code == 0
        assert snap.exists(), "Snapshot file was not written"
        assert meta.exists(), "Meta file was not written"

    def test_refresh_snapshot_is_valid_json_array(self, tmp_path: Path, monkeypatch):
        import flowise_dev_agent.knowledge.refresh as refresh_mod

        snap = tmp_path / "workday_mcp.snapshot.json"
        monkeypatch.setattr(refresh_mod, "_SCHEMAS_DIR", tmp_path)
        monkeypatch.setattr(refresh_mod, "_REPO_ROOT", tmp_path)
        monkeypatch.delenv("WORKDAY_MCP_CATALOG_PATH", raising=False)

        refresh_mod.refresh_workday_mcp(dry_run=False)

        data = json.loads(snap.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_refresh_snapshot_contains_default_blueprint(self, tmp_path: Path, monkeypatch):
        import flowise_dev_agent.knowledge.refresh as refresh_mod

        snap = tmp_path / "workday_mcp.snapshot.json"
        monkeypatch.setattr(refresh_mod, "_SCHEMAS_DIR", tmp_path)
        monkeypatch.setattr(refresh_mod, "_REPO_ROOT", tmp_path)
        monkeypatch.delenv("WORKDAY_MCP_CATALOG_PATH", raising=False)

        refresh_mod.refresh_workday_mcp(dry_run=False)

        blueprints = json.loads(snap.read_text(encoding="utf-8"))
        ids = [b.get("blueprint_id") for b in blueprints]
        assert "workday_default" in ids

    def test_refresh_dry_run_does_not_write(self, tmp_path: Path, monkeypatch):
        import flowise_dev_agent.knowledge.refresh as refresh_mod

        snap = tmp_path / "workday_mcp.snapshot.json"
        monkeypatch.setattr(refresh_mod, "_SCHEMAS_DIR", tmp_path)
        monkeypatch.setattr(refresh_mod, "_REPO_ROOT", tmp_path)
        monkeypatch.delenv("WORKDAY_MCP_CATALOG_PATH", raising=False)

        exit_code = refresh_mod.refresh_workday_mcp(dry_run=True)

        assert exit_code == 0
        assert not snap.exists(), "Dry run must not write the snapshot file"

    def test_refresh_meta_has_ok_status(self, tmp_path: Path, monkeypatch):
        import flowise_dev_agent.knowledge.refresh as refresh_mod

        meta = tmp_path / "workday_mcp.meta.json"
        monkeypatch.setattr(refresh_mod, "_SCHEMAS_DIR", tmp_path)
        monkeypatch.setattr(refresh_mod, "_REPO_ROOT", tmp_path)
        monkeypatch.delenv("WORKDAY_MCP_CATALOG_PATH", raising=False)

        refresh_mod.refresh_workday_mcp(dry_run=False)

        meta_data = json.loads(meta.read_text(encoding="utf-8"))
        assert meta_data["status"] == "ok"
        assert "fingerprint" in meta_data
        assert "generated_at" in meta_data
