"""M11.4 — Render-safe contract validator tests (DD-110).

Tests:
- Options param missing options list → flagged
- AsyncOptions param missing loadMethod → flagged
- Credential param missing credentialNames → flagged (warning)
- Numeric default as string → flagged (warning)
- Boolean default as string → flagged (warning)
- Credential requirement without credential inputParam → flagged (error)
- Valid schemas pass without issues
- Flow-level validation aggregates across nodes
"""

from __future__ import annotations

import pytest

from flowise_dev_agent.knowledge.drift import (
    DriftIssue,
    DriftMetrics,
    DriftResult,
    validate_flow_render_contract,
    validate_node_render_contract,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_data(
    name: str = "chatOpenAI",
    node_id: str = "chatOpenAI_0",
    input_params: list | None = None,
    **extras,
) -> dict:
    """Build a minimal node data dict for testing."""
    return {
        "id": node_id,
        "name": name,
        "inputParams": input_params or [],
        **extras,
    }


# ---------------------------------------------------------------------------
# Rule 1: options param must have options list
# ---------------------------------------------------------------------------


class TestOptionsContract:
    def test_options_missing_list_flagged(self):
        """type=options without 'options' list → error."""
        data = _node_data(input_params=[
            {"name": "outputParser", "type": "options"},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert not result.ok
        assert len(result.issues) == 1
        assert result.issues[0].severity == "error"
        assert "options" in result.issues[0].message.lower()

    def test_options_with_none_flagged(self):
        """type=options with options=None → error."""
        data = _node_data(input_params=[
            {"name": "outputParser", "type": "options", "options": None},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert not result.ok
        assert result.issues[0].severity == "error"

    def test_options_with_empty_list_ok(self):
        """type=options with options=[] → ok (empty is valid)."""
        data = _node_data(input_params=[
            {"name": "outputParser", "type": "options", "options": []},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok
        assert len(result.issues) == 0

    def test_options_with_populated_list_ok(self):
        """type=options with populated options → ok."""
        data = _node_data(input_params=[
            {"name": "model", "type": "options", "options": [
                {"label": "gpt-4o", "name": "gpt-4o"},
            ]},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok


# ---------------------------------------------------------------------------
# Rule 2: asyncOptions must have loadMethod
# ---------------------------------------------------------------------------


class TestAsyncOptionsContract:
    def test_async_options_missing_load_method_flagged(self):
        """type=asyncOptions without loadMethod → error."""
        data = _node_data(input_params=[
            {"name": "modelName", "type": "asyncOptions"},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert not result.ok
        assert result.issues[0].severity == "error"
        assert "loadmethod" in result.issues[0].message.lower()

    def test_async_options_with_empty_load_method_flagged(self):
        """type=asyncOptions with loadMethod='' → error."""
        data = _node_data(input_params=[
            {"name": "modelName", "type": "asyncOptions", "loadMethod": ""},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert not result.ok

    def test_async_options_with_load_method_ok(self):
        """type=asyncOptions with loadMethod present → ok."""
        data = _node_data(input_params=[
            {"name": "modelName", "type": "asyncOptions", "loadMethod": "listModels"},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok


# ---------------------------------------------------------------------------
# Rule 3: credential param missing credentialNames
# ---------------------------------------------------------------------------


class TestCredentialParamContract:
    def test_credential_param_missing_credential_names_warning(self):
        """type=credential without credentialNames → warning."""
        data = _node_data(input_params=[
            {"name": "credential", "type": "credential"},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        # This is a warning, not error
        assert result.ok  # warnings don't fail
        assert len(result.issues) == 1
        assert result.issues[0].severity == "warning"
        assert "credentialnames" in result.issues[0].message.lower()

    def test_credential_param_with_credential_names_ok(self):
        """type=credential with credentialNames → ok."""
        data = _node_data(input_params=[
            {"name": "credential", "type": "credential", "credentialNames": ["openAIApi"]},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok
        assert len(result.issues) == 0


# ---------------------------------------------------------------------------
# Rule 4: numeric defaults must be native
# ---------------------------------------------------------------------------


class TestNumericDefaultContract:
    def test_number_default_string_flagged(self):
        """type=number with string default → warning."""
        data = _node_data(input_params=[
            {"name": "temperature", "type": "number", "default": "0.9"},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok  # warnings only
        assert len(result.issues) == 1
        assert result.issues[0].severity == "warning"
        assert "string" in result.issues[0].message.lower()

    def test_number_default_native_ok(self):
        """type=number with native float default → ok."""
        data = _node_data(input_params=[
            {"name": "temperature", "type": "number", "default": 0.9},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok
        assert len(result.issues) == 0

    def test_number_default_int_ok(self):
        """type=number with native int default → ok."""
        data = _node_data(input_params=[
            {"name": "maxTokens", "type": "number", "default": 1024},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok

    def test_number_no_default_ok(self):
        """type=number without default → ok."""
        data = _node_data(input_params=[
            {"name": "temperature", "type": "number"},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok


# ---------------------------------------------------------------------------
# Rule 5: boolean defaults must be native
# ---------------------------------------------------------------------------


class TestBooleanDefaultContract:
    def test_boolean_default_string_flagged(self):
        """type=boolean with string default → warning."""
        data = _node_data(input_params=[
            {"name": "streaming", "type": "boolean", "default": "true"},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok  # warning only
        assert len(result.issues) == 1
        assert result.issues[0].severity == "warning"

    def test_boolean_default_native_ok(self):
        """type=boolean with native bool default → ok."""
        data = _node_data(input_params=[
            {"name": "streaming", "type": "boolean", "default": True},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok


# ---------------------------------------------------------------------------
# Rule 6: credential requirement without credential inputParam
# ---------------------------------------------------------------------------


class TestCredentialRequirementContract:
    def test_credential_required_but_no_param_flagged(self):
        """Node has credentialNames but no credential inputParam → error."""
        data = _node_data(
            input_params=[
                {"name": "temperature", "type": "number", "default": 0.9},
            ],
            credentialNames=["openAIApi"],
        )
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert not result.ok
        assert any(
            "credential" in i.message.lower() and i.severity == "error"
            for i in result.issues
        )

    def test_top_level_credential_value_no_false_positive(self):
        """Node with runtime 'credential' (bound value) but no credentialNames → no error.

        The 'credential' key in compiled data is the bound credential VALUE from
        BindCredential, not a schema-level requirement indicator.
        Only credentialNames triggers the credential inputParam check.
        """
        data = _node_data(
            input_params=[
                {"name": "temperature", "type": "number", "default": 0.9},
            ],
            credential="513db410-c4c3-4818-a716-6f386aba8a82",
        )
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok

    def test_credential_required_with_param_ok(self):
        """Node has credentialNames and credential inputParam → ok."""
        data = _node_data(
            input_params=[
                {"name": "credential", "type": "credential", "credentialNames": ["openAIApi"]},
                {"name": "temperature", "type": "number", "default": 0.9},
            ],
            credentialNames=["openAIApi"],
        )
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok

    def test_no_credential_requirement_ok(self):
        """Node without credential requirement → ok."""
        data = _node_data(input_params=[
            {"name": "temperature", "type": "number", "default": 0.9},
        ])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok


# ---------------------------------------------------------------------------
# Aggregate: valid schema
# ---------------------------------------------------------------------------


class TestValidSchema:
    def test_fully_valid_node_ok(self):
        """A well-formed node with all contracts met passes."""
        data = _node_data(
            input_params=[
                {"name": "credential", "type": "credential", "credentialNames": ["openAIApi"]},
                {"name": "modelName", "type": "asyncOptions", "loadMethod": "listModels"},
                {"name": "temperature", "type": "number", "default": 0.9},
                {"name": "streaming", "type": "boolean", "default": True},
                {"name": "topP", "type": "options", "options": [
                    {"label": "Default", "name": "default"},
                ]},
            ],
            credentialNames=["openAIApi"],
        )
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok
        assert len(result.issues) == 0

    def test_empty_node_ok(self):
        """A node with no inputParams is ok (no contracts to violate)."""
        data = _node_data(input_params=[])
        result = validate_node_render_contract(data, "chatOpenAI_0")
        assert result.ok

    def test_multiple_violations_all_reported(self):
        """Multiple violations in one node are all surfaced."""
        data = _node_data(
            input_params=[
                {"name": "model", "type": "options"},  # missing options
                {"name": "models", "type": "asyncOptions"},  # missing loadMethod
                {"name": "temp", "type": "number", "default": "0.9"},  # string default
            ],
        )
        result = validate_node_render_contract(data, "chatOpenAI_0")
        # 2 errors (options + asyncOptions) + 1 warning (number default)
        assert not result.ok
        assert len(result.issues) == 3


# ---------------------------------------------------------------------------
# Flow-level validation
# ---------------------------------------------------------------------------


class TestFlowRenderContract:
    def test_valid_flow_ok(self):
        """Flow with well-formed nodes passes."""
        flow_data = {
            "nodes": [
                {
                    "id": "chatOpenAI_0",
                    "data": _node_data(input_params=[
                        {"name": "temperature", "type": "number", "default": 0.9},
                    ]),
                },
                {
                    "id": "bufferMemory_0",
                    "data": _node_data(name="bufferMemory", node_id="bufferMemory_0"),
                },
            ],
            "edges": [],
        }
        result = validate_flow_render_contract(flow_data)
        assert result.ok

    def test_flow_with_drift_aggregates_issues(self):
        """Issues from multiple nodes are aggregated."""
        flow_data = {
            "nodes": [
                {
                    "id": "chatOpenAI_0",
                    "data": _node_data(input_params=[
                        {"name": "model", "type": "options"},  # missing options
                    ]),
                },
                {
                    "id": "toolAgent_0",
                    "data": _node_data(
                        name="toolAgent",
                        node_id="toolAgent_0",
                        input_params=[
                            {"name": "models", "type": "asyncOptions"},  # missing loadMethod
                        ],
                    ),
                },
            ],
            "edges": [],
        }
        result = validate_flow_render_contract(flow_data)
        assert not result.ok
        assert len(result.issues) == 2
        types = result.affected_node_types
        assert "chatOpenAI" in types
        assert "toolAgent" in types

    def test_empty_flow_ok(self):
        """Empty flow is valid."""
        result = validate_flow_render_contract({"nodes": [], "edges": []})
        assert result.ok

    def test_flow_missing_nodes_ok(self):
        """Flow without nodes key is valid."""
        result = validate_flow_render_contract({})
        assert result.ok


# ---------------------------------------------------------------------------
# DriftResult properties
# ---------------------------------------------------------------------------


class TestDriftResultProperties:
    def test_severity_error(self):
        result = DriftResult(ok=False, issues=[
            DriftIssue("n0", "t0", "f", "msg", "error"),
        ])
        assert result.severity == "error"

    def test_severity_warning(self):
        result = DriftResult(ok=True, issues=[
            DriftIssue("n0", "t0", "f", "msg", "warning"),
        ])
        assert result.severity == "warning"

    def test_severity_ok(self):
        result = DriftResult(ok=True, issues=[])
        assert result.severity == "ok"

    def test_human_readable(self):
        result = DriftResult(ok=False, issues=[
            DriftIssue("chatOpenAI_0", "chatOpenAI", "inputParams.model.options",
                       "missing options list", "error"),
        ])
        lines = result.human_readable
        assert len(lines) == 1
        assert "[ERROR]" in lines[0]
        assert "chatOpenAI" in lines[0]
