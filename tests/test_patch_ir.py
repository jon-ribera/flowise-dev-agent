"""Tests for Milestone 2: Patch IR, deterministic compiler, and WriteGuard.

Covers the three minimum acceptance tests specified in the roadmap:
  Test 1 — Determinism: same ops → same payload_hash every time
  Test 2 — Write guard enforcement: write without validate_flow_data raises PermissionError
  Test 3 — IR validation: Connect referencing non-existent anchor is caught

Plus: JSON roundtrip, op parsing, compiler diff summary, guard lifecycle.

See roadmap3_architecture_optimization.md — Milestone 2 Acceptance Criteria.
"""

import hashlib
import json
import pytest

from flowise_dev_agent.agent.compiler import (
    CompileResult,
    GraphIR,
    GraphNode,
    compile_patch_ops,
)
from flowise_dev_agent.agent.patch_ir import (
    AddNode,
    BindCredential,
    Connect,
    PatchIRValidationError,
    SetParam,
    op_from_dict,
    op_to_dict,
    ops_from_json,
    ops_to_json,
    validate_patch_ops,
)
from flowise_dev_agent.agent.tools import WriteGuard


# ---------------------------------------------------------------------------
# Minimal Flowise node schema (pre-processed by _get_node_processed)
# ---------------------------------------------------------------------------

_CHAT_OPENAI_SCHEMA = {
    "name": "chatOpenAI",
    "label": "ChatOpenAI",
    "type": "ChatOpenAI",
    "version": 6,
    "baseClasses": ["BaseChatModel", "BaseLanguageModel"],
    "category": "Chat Models",
    "description": "OpenAI chat model",
    "inputAnchors": [],
    "inputParams": [
        {
            "label": "Model Name",
            "name": "modelName",
            "type": "options",
            "id": "{nodeId}-input-modelName-options",
            "default": "gpt-3.5-turbo",
        },
        {
            "label": "Temperature",
            "name": "temperature",
            "type": "number",
            "id": "{nodeId}-input-temperature-number",
            "default": 0.9,
        },
    ],
    "outputAnchors": [
        {
            "id": "{nodeId}-output-chatOpenAI-BaseChatModel|BaseLanguageModel",
            "name": "chatOpenAI",
            "label": "ChatOpenAI",
            "type": "BaseChatModel | BaseLanguageModel",
        }
    ],
    "outputs": {},
}

_CONV_CHAIN_SCHEMA = {
    "name": "conversationChain",
    "label": "Conversation Chain",
    "type": "ConversationChain",
    "version": 3,
    "baseClasses": ["ConversationChain", "LLMChain", "BaseChain"],
    "category": "Chains",
    "description": "Conversation chain with memory",
    "inputAnchors": [
        {
            "label": "Chat Model",
            "name": "model",
            "type": "BaseChatModel",
            "id": "{nodeId}-input-model-BaseChatModel",
        },
    ],
    "inputParams": [
        {
            "label": "System Message",
            "name": "systemMessagePrompt",
            "type": "string",
            "id": "{nodeId}-input-systemMessagePrompt-string",
            "default": "You are a helpful assistant.",
        }
    ],
    "outputAnchors": [
        {
            "id": "{nodeId}-output-conversationChain-ConversationChain|LLMChain|BaseChain",
            "name": "conversationChain",
            "label": "Conversation Chain",
            "type": "ConversationChain | LLMChain | BaseChain",
        }
    ],
    "outputs": {},
}


# ---------------------------------------------------------------------------
# Test 1: Determinism — same ops → same payload_hash every run
# ---------------------------------------------------------------------------


class TestDeterminism:
    """compile_patch_ops must produce the same payload_hash for identical inputs."""

    def _minimal_ops(self):
        return [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0", label="ChatOpenAI"),
            AddNode(node_name="conversationChain", node_id="chain_0", label="Conversation"),
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="chatOpenAI",
                target_node_id="chain_0",
                target_anchor="BaseChatModel",
            ),
            SetParam(node_id="chain_0", param_name="systemMessagePrompt", value="You are a bot."),
        ]

    def _schema_cache(self):
        return {
            "chatOpenAI": _CHAT_OPENAI_SCHEMA,
            "conversationChain": _CONV_CHAIN_SCHEMA,
        }

    def test_same_hash_on_repeated_calls(self):
        """Running the compiler twice with the same inputs produces the same hash."""
        ops = self._minimal_ops()
        schema = self._schema_cache()

        r1 = compile_patch_ops(GraphIR(), ops, schema)
        r2 = compile_patch_ops(GraphIR(), ops, schema)

        assert r1.ok, f"First compile failed: {r1.errors}"
        assert r2.ok, f"Second compile failed: {r2.errors}"
        assert r1.payload_hash == r2.payload_hash, (
            f"Hash is not deterministic: {r1.payload_hash!r} vs {r2.payload_hash!r}"
        )

    def test_hash_is_sha256_of_flow_data_str(self):
        """payload_hash is the SHA-256 hex digest of flow_data_str."""
        ops = self._minimal_ops()
        result = compile_patch_ops(GraphIR(), ops, self._schema_cache())
        assert result.ok, result.errors

        expected = hashlib.sha256(result.flow_data_str.encode("utf-8")).hexdigest()
        assert result.payload_hash == expected

    def test_different_ops_different_hash(self):
        """Different ops produce different hashes."""
        ops_a = [AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0")]
        ops_b = [AddNode(node_name="chatOpenAI", node_id="chatOpenAI_1")]
        schema = {"chatOpenAI": _CHAT_OPENAI_SCHEMA}

        r_a = compile_patch_ops(GraphIR(), ops_a, schema)
        r_b = compile_patch_ops(GraphIR(), ops_b, schema)

        assert r_a.ok and r_b.ok
        assert r_a.payload_hash != r_b.payload_hash

    def test_flow_data_str_is_valid_json(self):
        """flow_data_str deserializes to a dict with nodes and edges arrays."""
        result = compile_patch_ops(GraphIR(), self._minimal_ops(), self._schema_cache())
        assert result.ok

        parsed = json.loads(result.flow_data_str)
        assert "nodes" in parsed
        assert "edges" in parsed
        assert isinstance(parsed["nodes"], list)
        assert isinstance(parsed["edges"], list)

    def test_edge_id_is_deterministic(self):
        """Edge IDs are derived from node IDs + anchor names (stable, no random component)."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            AddNode(node_name="conversationChain", node_id="chain_0"),
            Connect(
                source_node_id="chatOpenAI_0", source_anchor="chatOpenAI",
                target_node_id="chain_0", target_anchor="BaseChatModel",
            ),
        ]
        schema = {
            "chatOpenAI": _CHAT_OPENAI_SCHEMA,
            "conversationChain": _CONV_CHAIN_SCHEMA,
        }
        r1 = compile_patch_ops(GraphIR(), ops, schema)
        r2 = compile_patch_ops(GraphIR(), ops, schema)

        edges_1 = json.loads(r1.flow_data_str)["edges"]
        edges_2 = json.loads(r2.flow_data_str)["edges"]

        assert edges_1[0]["id"] == edges_2[0]["id"]
        assert edges_1[0]["id"] == "chatOpenAI_0-chatOpenAI-chain_0-BaseChatModel"


# ---------------------------------------------------------------------------
# Test 2: Write guard enforcement
# ---------------------------------------------------------------------------


class TestWriteGuard:
    """WriteGuard must block writes that do not have a matching authorized hash."""

    def test_write_blocked_without_prior_validation(self):
        """Calling check() without a prior authorize() raises PermissionError."""
        guard = WriteGuard()
        with pytest.raises(PermissionError, match="ValidationRequired"):
            guard.check('{"nodes":[],"edges":[]}')

    def test_write_allowed_after_valid_authorization(self):
        """check() does not raise when the payload matches the authorized hash."""
        payload = '{"nodes":[],"edges":[]}'
        guard = WriteGuard()
        guard.authorize(payload)
        guard.check(payload)  # must not raise

    def test_write_blocked_when_payload_changes_after_validation(self):
        """check() raises HashMismatch when the payload differs from what was authorized."""
        original = '{"nodes":[],"edges":[]}'
        modified = '{"nodes":[{"id":"extra"}],"edges":[]}'

        guard = WriteGuard()
        guard.authorize(original)

        with pytest.raises(PermissionError, match="HashMismatch"):
            guard.check(modified)

    def test_authorize_returns_hash_stored_in_guard(self):
        """authorize() returns the SHA-256 of the payload and stores it."""
        payload = '{"nodes":[],"edges":[]}'
        guard = WriteGuard()
        returned_hash = guard.authorize(payload)

        expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        assert returned_hash == expected
        assert guard.authorized_hash == expected

    def test_revoke_clears_authorization(self):
        """revoke() clears the authorized hash; subsequent check() raises ValidationRequired."""
        payload = '{"nodes":[],"edges":[]}'
        guard = WriteGuard()
        guard.authorize(payload)
        guard.revoke()

        assert guard.authorized_hash is None
        with pytest.raises(PermissionError, match="ValidationRequired"):
            guard.check(payload)

    def test_guarded_executor_blocks_write_without_validation(self):
        """_make_flowise_executor with guard: write without validate → PermissionError."""
        # We test the guard wrappers directly (without a real FlowiseClient).
        guard = WriteGuard()

        # Simulate what the guarded create wrapper does
        def _check_then_write(flow_data: str) -> None:
            guard.check(flow_data)

        with pytest.raises(PermissionError, match="ValidationRequired"):
            _check_then_write('{"nodes":[],"edges":[]}')

    def test_guarded_executor_allows_write_after_validation(self):
        """_make_flowise_executor with guard: validate then write with same payload → no error."""
        guard = WriteGuard()
        payload = '{"nodes":[],"edges":[]}'

        guard.authorize(payload)  # validate records hash
        guard.check(payload)      # write matches hash → no error


# ---------------------------------------------------------------------------
# Test 3: IR validation — Connect to non-existent node is caught
# ---------------------------------------------------------------------------


class TestPatchIRValidation:
    """validate_patch_ops must catch structural problems before they reach the compiler."""

    def test_connect_to_nonexistent_source_node_is_caught(self):
        """Connect referencing a source_node_id not in base graph or AddNode ops → error."""
        ops = [
            # Only adds target node; source_node_id "ghost_0" is never declared
            AddNode(node_name="conversationChain", node_id="chain_0"),
            Connect(
                source_node_id="ghost_0",     # does NOT exist
                source_anchor="output",
                target_node_id="chain_0",
                target_anchor="BaseChatModel",
            ),
        ]
        errors, _warnings = validate_patch_ops(ops, base_node_ids=set())
        assert any("ghost_0" in e for e in errors), f"Expected error about ghost_0, got: {errors}"

    def test_connect_to_nonexistent_target_node_is_caught(self):
        """Connect referencing a target_node_id not in graph or ops → error."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="chatOpenAI",
                target_node_id="missing_chain",   # not declared
                target_anchor="BaseChatModel",
            ),
        ]
        errors, _warnings = validate_patch_ops(ops)
        assert any("missing_chain" in e for e in errors), f"Got: {errors}"

    def test_existing_base_nodes_are_valid_refs(self):
        """Connect referencing nodes in base_node_ids (existing graph) is valid."""
        ops = [
            Connect(
                source_node_id="chatOpenAI_0",    # exists in base
                source_anchor="chatOpenAI",
                target_node_id="chain_0",          # exists in base
                target_anchor="BaseChatModel",
            ),
        ]
        errors, _warnings = validate_patch_ops(ops, base_node_ids={"chatOpenAI_0", "chain_0"})
        assert errors == [], f"Unexpected errors: {errors}"

    def test_duplicate_node_id_in_add_ops_is_caught(self):
        """Two AddNode ops with the same node_id → error."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="shared_id"),
            AddNode(node_name="conversationChain", node_id="shared_id"),  # duplicate
        ]
        errors, _warnings = validate_patch_ops(ops)
        assert any("shared_id" in e for e in errors), f"Got: {errors}"

    def test_missing_required_fields_are_caught(self):
        """AddNode without node_name or node_id → errors."""
        ops = [
            AddNode(node_name="", node_id="chatOpenAI_0"),   # empty node_name
            AddNode(node_name="conversationChain", node_id=""),  # empty node_id
        ]
        errors, _warnings = validate_patch_ops(ops)
        assert len(errors) >= 2, f"Expected at least 2 errors, got: {errors}"

    def test_bind_credential_missing_id_is_caught(self):
        """BindCredential with empty credential_id → error."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            BindCredential(node_id="chatOpenAI_0", credential_id=""),
        ]
        errors, _warnings = validate_patch_ops(ops)
        assert any("credential_id" in e for e in errors), f"Got: {errors}"

    def test_valid_ops_produce_no_errors(self):
        """A well-formed ops list passes validation with no errors."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0", label="LLM"),
            AddNode(node_name="conversationChain", node_id="chain_0"),
            Connect(
                source_node_id="chatOpenAI_0",
                source_anchor="chatOpenAI",
                target_node_id="chain_0",
                target_anchor="BaseChatModel",
            ),
            BindCredential(node_id="chatOpenAI_0", credential_id="cred-uuid-123"),
            SetParam(node_id="chain_0", param_name="systemMessagePrompt", value="Hello!"),
        ]
        errors, _warnings = validate_patch_ops(ops)
        assert errors == [], f"Unexpected validation errors: {errors}"


# ---------------------------------------------------------------------------
# Bonus: JSON roundtrip
# ---------------------------------------------------------------------------


class TestJsonRoundtrip:
    """ops_to_json + ops_from_json must be lossless for all op types."""

    def test_all_op_types_roundtrip(self):
        original_ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0", label="LLM",
                    params={"modelName": "gpt-4o", "temperature": 0.2}),
            SetParam(node_id="chain_0", param_name="systemMessage", value="Be helpful."),
            Connect(source_node_id="chatOpenAI_0", source_anchor="chatOpenAI",
                    target_node_id="chain_0", target_anchor="BaseChatModel"),
            BindCredential(node_id="chatOpenAI_0", credential_id="cred-123",
                           credential_type="openAIApi"),
        ]
        json_str = ops_to_json(original_ops)
        restored_ops = ops_from_json(json_str)

        assert len(restored_ops) == 4
        assert isinstance(restored_ops[0], AddNode)
        assert restored_ops[0].node_name == "chatOpenAI"
        assert restored_ops[0].params["modelName"] == "gpt-4o"
        assert isinstance(restored_ops[1], SetParam)
        assert restored_ops[1].value == "Be helpful."
        assert isinstance(restored_ops[2], Connect)
        assert restored_ops[2].target_anchor == "BaseChatModel"
        assert isinstance(restored_ops[3], BindCredential)
        assert restored_ops[3].credential_type == "openAIApi"

    def test_ops_from_json_strips_code_fence(self):
        """ops_from_json tolerates ```json...``` fencing from LLM output."""
        fenced = '```json\n[{"op_type":"add_node","node_name":"chatOpenAI","node_id":"n0"}]\n```'
        ops = ops_from_json(fenced)
        assert len(ops) == 1
        assert isinstance(ops[0], AddNode)
        assert ops[0].node_id == "n0"

    def test_unknown_op_type_raises_value_error(self):
        """op_from_dict with unknown op_type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown op_type"):
            op_from_dict({"op_type": "delete_node", "node_id": "n0"})

    def test_extra_keys_are_ignored(self):
        """op_from_dict silently drops keys not in the dataclass fields."""
        d = {"op_type": "add_node", "node_name": "chatOpenAI", "node_id": "n0", "_unknown": "x"}
        op = op_from_dict(d)
        assert isinstance(op, AddNode)
        assert not hasattr(op, "_unknown")


# ---------------------------------------------------------------------------
# Bonus: compiler behaviour
# ---------------------------------------------------------------------------


class TestCompiler:
    """Additional compiler tests for edge cases."""

    def test_missing_schema_produces_error_not_exception(self):
        """AddNode without a schema in schema_cache produces a compile error (not a crash)."""
        ops = [AddNode(node_name="unknownNode", node_id="n0")]
        result = compile_patch_ops(GraphIR(), ops, schema_cache={})
        assert not result.ok
        assert any("schema" in e.lower() or "unknownNode" in e for e in result.errors)

    def test_set_param_on_nonexistent_node_produces_error(self):
        """SetParam referencing a missing node_id → compile error."""
        ops = [SetParam(node_id="ghost", param_name="modelName", value="gpt-4o")]
        result = compile_patch_ops(GraphIR(), ops, schema_cache={})
        assert not result.ok
        assert any("ghost" in e for e in result.errors)

    def test_bind_credential_sets_both_data_levels(self):
        """BindCredential sets data.credential AND data.inputs.credential."""
        base = GraphIR(nodes=[
            GraphNode(
                id="chatOpenAI_0",
                node_name="chatOpenAI",
                label="ChatOpenAI",
                position={"x": 100, "y": 100},
                data={"id": "chatOpenAI_0", "inputs": {}, "inputAnchors": [],
                      "inputParams": [], "outputAnchors": [], "outputs": {}},
            )
        ])
        ops = [BindCredential(node_id="chatOpenAI_0", credential_id="cred-xyz")]
        result = compile_patch_ops(base, ops, schema_cache={})
        assert result.ok, result.errors

        nodes = json.loads(result.flow_data_str)["nodes"]
        data = next(n["data"] for n in nodes if n["id"] == "chatOpenAI_0")
        assert data["credential"] == "cred-xyz", "data.credential not set"
        assert data["inputs"]["credential"] == "cred-xyz", "data.inputs.credential not set"

    def test_diff_summary_lists_added_nodes_and_edges(self):
        """diff_summary contains NODES ADDED and EDGES ADDED lines."""
        ops = [
            AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
            AddNode(node_name="conversationChain", node_id="chain_0"),
            Connect(
                source_node_id="chatOpenAI_0", source_anchor="chatOpenAI",
                target_node_id="chain_0", target_anchor="BaseChatModel",
            ),
        ]
        schema = {
            "chatOpenAI": _CHAT_OPENAI_SCHEMA,
            "conversationChain": _CONV_CHAIN_SCHEMA,
        }
        result = compile_patch_ops(GraphIR(), ops, schema)
        assert "NODES ADDED" in result.diff_summary
        assert "chatOpenAI_0" in result.diff_summary
        assert "EDGES ADDED" in result.diff_summary

    def test_graph_ir_from_flow_data_roundtrip(self):
        """GraphIR.from_flow_data → to_flow_data preserves node and edge counts."""
        flow_data = {
            "nodes": [
                {
                    "id": "n1",
                    "position": {"x": 100, "y": 200},
                    "type": "customNode",
                    "data": {"id": "n1", "name": "chatOpenAI", "label": "ChatOpenAI",
                             "inputAnchors": [], "inputParams": [], "outputAnchors": [],
                             "outputs": {}, "inputs": {}, "selected": False},
                }
            ],
            "edges": [],
        }
        graph = GraphIR.from_flow_data(flow_data)
        assert len(graph.nodes) == 1
        assert graph.nodes[0].id == "n1"
        rebuilt = graph.to_flow_data()
        assert len(rebuilt["nodes"]) == 1
        assert rebuilt["nodes"][0]["id"] == "n1"
