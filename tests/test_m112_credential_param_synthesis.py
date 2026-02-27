"""M11.2 — Credential inputParam synthesis tests (DD-106).

Tests _ensure_credential_input_param:
- Inserts credential inputParam[0] when node requires credentials
- No-op when already present (idempotent)
- Works with both top-level 'credential' and 'credentialNames' fields
- BindCredential sets data["credential"] and schema has credential param
"""

from __future__ import annotations

import copy

import pytest

from flowise_dev_agent.agent.compiler import (
    AddNode,
    BindCredential,
    GraphIR,
    _build_node_data,
    _ensure_credential_input_param,
    compile_patch_ops,
)


# ---------------------------------------------------------------------------
# Sample schemas
# ---------------------------------------------------------------------------

_SCHEMA_WITH_CREDENTIAL = {
    "name": "chatOpenAI",
    "label": "ChatOpenAI",
    "baseClasses": ["BaseChatModel"],
    "credential": "openAIApi",
    "inputAnchors": [],
    "inputParams": [
        {"name": "modelName", "type": "string", "id": "{nodeId}-input-modelName-string"},
    ],
    "outputAnchors": [
        {"id": "{nodeId}-output-chatOpenAI-BaseChatModel", "name": "chatOpenAI", "type": "BaseChatModel"},
    ],
}

_SCHEMA_WITH_CREDENTIAL_NAMES = {
    "name": "chatOpenAI",
    "label": "ChatOpenAI",
    "baseClasses": ["BaseChatModel"],
    "credentialNames": ["openAIApi", "azureOpenAIApi"],
    "inputAnchors": [],
    "inputParams": [
        {"name": "modelName", "type": "string", "id": "{nodeId}-input-modelName-string"},
    ],
    "outputAnchors": [
        {"id": "{nodeId}-output-chatOpenAI-BaseChatModel", "name": "chatOpenAI", "type": "BaseChatModel"},
    ],
}

_SCHEMA_NO_CREDENTIAL = {
    "name": "bufferMemory",
    "label": "Buffer Memory",
    "baseClasses": ["BaseMemory"],
    "inputAnchors": [],
    "inputParams": [
        {"name": "sessionId", "type": "string", "id": "{nodeId}-input-sessionId-string"},
    ],
    "outputAnchors": [
        {"id": "{nodeId}-output-bufferMemory-BaseMemory", "name": "bufferMemory", "type": "BaseMemory"},
    ],
}

_SCHEMA_WITH_EXISTING_CRED_PARAM = {
    "name": "chatOpenAI",
    "label": "ChatOpenAI",
    "baseClasses": ["BaseChatModel"],
    "credential": "openAIApi",
    "inputAnchors": [],
    "inputParams": [
        {
            "label": "Connect Credential",
            "name": "credential",
            "type": "credential",
            "credentialNames": ["openAIApi"],
            "id": "{nodeId}-input-credential-credential",
        },
        {"name": "modelName", "type": "string", "id": "{nodeId}-input-modelName-string"},
    ],
    "outputAnchors": [
        {"id": "{nodeId}-output-chatOpenAI-BaseChatModel", "name": "chatOpenAI", "type": "BaseChatModel"},
    ],
}


# ---------------------------------------------------------------------------
# _ensure_credential_input_param tests
# ---------------------------------------------------------------------------


class TestEnsureCredentialInputParam:
    def test_inserts_credential_param_from_top_level(self):
        """Schema with top-level 'credential' field gets param inserted."""
        data = {
            "inputParams": [
                {"name": "modelName", "type": "string"},
            ],
        }
        schema = {"credential": "openAIApi"}

        _ensure_credential_input_param(data, schema, "chatOpenAI_0")

        assert len(data["inputParams"]) == 2
        cred = data["inputParams"][0]
        assert cred["name"] == "credential"
        assert cred["type"] == "credential"
        assert cred["credentialNames"] == ["openAIApi"]
        assert cred["id"] == "chatOpenAI_0-input-credential-credential"
        assert cred["optional"] is False

    def test_inserts_credential_param_from_credential_names(self):
        """Schema with 'credentialNames' list gets param inserted."""
        data = {"inputParams": []}
        schema = {"credentialNames": ["openAIApi", "azureOpenAIApi"]}

        _ensure_credential_input_param(data, schema, "chatOpenAI_0")

        cred = data["inputParams"][0]
        assert cred["credentialNames"] == ["openAIApi", "azureOpenAIApi"]

    def test_no_op_when_already_present(self):
        """Calling twice does not duplicate."""
        data = {
            "inputParams": [
                {"name": "credential", "type": "credential", "credentialNames": ["openAIApi"]},
                {"name": "modelName", "type": "string"},
            ],
        }
        schema = {"credential": "openAIApi"}

        _ensure_credential_input_param(data, schema, "chatOpenAI_0")

        assert len(data["inputParams"]) == 2
        assert data["inputParams"][0]["name"] == "credential"

    def test_no_op_when_no_credential_required(self):
        """Schema without credential requirement doesn't inject."""
        data = {"inputParams": [{"name": "sessionId", "type": "string"}]}
        schema = {"name": "bufferMemory"}

        _ensure_credential_input_param(data, schema, "bufferMemory_0")

        assert len(data["inputParams"]) == 1
        assert data["inputParams"][0]["name"] == "sessionId"

    def test_credential_is_first_param(self):
        """Credential param is inserted at position 0."""
        data = {
            "inputParams": [
                {"name": "temp", "type": "number"},
                {"name": "model", "type": "string"},
            ],
        }
        schema = {"credential": "openAIApi"}

        _ensure_credential_input_param(data, schema, "node_0")

        assert data["inputParams"][0]["name"] == "credential"
        assert data["inputParams"][1]["name"] == "temp"
        assert data["inputParams"][2]["name"] == "model"


# ---------------------------------------------------------------------------
# Integration: _build_node_data + credential synthesis
# ---------------------------------------------------------------------------


class TestBuildNodeDataCredential:
    def test_build_node_data_injects_credential(self):
        """_build_node_data inserts credential param for credential-bearing schema."""
        schema = copy.deepcopy(_SCHEMA_WITH_CREDENTIAL)
        data = _build_node_data("chatOpenAI", "chatOpenAI_0", "ChatOpenAI", schema, {})

        # First inputParam should be the credential
        assert data["inputParams"][0]["name"] == "credential"
        assert data["inputParams"][0]["type"] == "credential"

    def test_build_node_data_no_duplicate_with_existing(self):
        """Schema that already has credential param should not get a duplicate."""
        schema = copy.deepcopy(_SCHEMA_WITH_EXISTING_CRED_PARAM)
        data = _build_node_data("chatOpenAI", "chatOpenAI_0", "ChatOpenAI", schema, {})

        cred_count = sum(1 for p in data["inputParams"] if p.get("type") == "credential")
        assert cred_count == 1

    def test_build_node_data_no_credential_for_memory(self):
        """Non-credential schema should not get credential param."""
        schema = copy.deepcopy(_SCHEMA_NO_CREDENTIAL)
        data = _build_node_data("bufferMemory", "bufferMemory_0", "Buffer Memory", schema, {})

        for p in data["inputParams"]:
            assert p.get("type") != "credential"


# ---------------------------------------------------------------------------
# Integration: BindCredential + credential param present
# ---------------------------------------------------------------------------


class TestBindCredentialWithParam:
    def test_bind_credential_sets_value(self):
        """BindCredential sets data.credential and data.inputs.credential."""
        schema = copy.deepcopy(_SCHEMA_WITH_CREDENTIAL)
        result = compile_patch_ops(
            GraphIR(),
            [
                AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0"),
                BindCredential(node_id="chatOpenAI_0", credential_id="cred-uuid-123"),
            ],
            {"chatOpenAI": schema},
        )
        assert result.ok

        node = result.flow_data["nodes"][0]
        assert node["data"]["credential"] == "cred-uuid-123"
        assert node["data"]["inputs"]["credential"] == "cred-uuid-123"

        # Credential inputParam should exist
        cred_params = [p for p in node["data"]["inputParams"] if p.get("type") == "credential"]
        assert len(cred_params) == 1
