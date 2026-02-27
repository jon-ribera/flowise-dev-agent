"""M11.2 — Render-safe schema contract tests (DD-106).

Tests that _normalize_api_schema() produces render-safe inputParam dicts:
- options params have an options list
- asyncOptions params have loadMethod
- number defaults are coerced to numeric
- boolean defaults are coerced to bool
- UI-relevant fields (step, rows, show, etc.) are preserved
"""

from __future__ import annotations

import pytest

from flowise_dev_agent.knowledge.provider import (
    _coerce_default,
    _normalize_api_schema,
    _validate_render_safe,
)


# ---------------------------------------------------------------------------
# _coerce_default tests
# ---------------------------------------------------------------------------


class TestCoerceDefault:
    def test_float_string(self):
        assert _coerce_default("0.9", "number") == 0.9

    def test_int_string(self):
        assert _coerce_default("10", "number") == 10
        assert isinstance(_coerce_default("10", "number"), int)

    def test_float_stays_float(self):
        assert _coerce_default("8.3", "number") == 8.3
        assert isinstance(_coerce_default("8.3", "number"), float)

    def test_bool_true(self):
        assert _coerce_default("True", "boolean") is True
        assert _coerce_default("true", "boolean") is True

    def test_bool_false(self):
        assert _coerce_default("False", "boolean") is False
        assert _coerce_default("false", "boolean") is False

    def test_bool_detected_from_value(self):
        """Even without boolean type hint, True/False strings coerce."""
        assert _coerce_default("True", "string") is True
        assert _coerce_default("False", "string") is False

    def test_json_object(self):
        result = _coerce_default('{"key": "val"}', "json")
        assert result == {"key": "val"}

    def test_json_array(self):
        result = _coerce_default('[1, 2, 3]', "json")
        assert result == [1, 2, 3]

    def test_invalid_json_stays_string(self):
        result = _coerce_default("{not valid", "json")
        assert result == "{not valid"

    def test_non_numeric_stays_string(self):
        result = _coerce_default("gpt-4o", "number")
        assert result == "gpt-4o"

    def test_empty_string_stays(self):
        assert _coerce_default("", "number") == ""

    def test_none_stays(self):
        assert _coerce_default(None, "number") is None

    def test_already_native_passthrough(self):
        assert _coerce_default(0.9, "number") == 0.9
        assert _coerce_default(True, "boolean") is True
        assert _coerce_default(42, "number") == 42


# ---------------------------------------------------------------------------
# _validate_render_safe tests
# ---------------------------------------------------------------------------


class TestValidateRenderSafe:
    def test_options_missing_options_list(self):
        param = {"name": "mode", "type": "options"}
        warnings = _validate_render_safe(param)
        assert len(warnings) == 1
        assert "options" in warnings[0].lower()
        # Should have set options to []
        assert param["options"] == []

    def test_options_with_options_list(self):
        param = {"name": "mode", "type": "options", "options": [{"label": "A", "name": "a"}]}
        warnings = _validate_render_safe(param)
        assert len(warnings) == 0

    def test_async_options_missing_load_method(self):
        param = {"name": "model", "type": "asyncOptions"}
        warnings = _validate_render_safe(param)
        assert len(warnings) == 1
        assert "loadMethod" in warnings[0]

    def test_async_options_with_load_method(self):
        param = {"name": "model", "type": "asyncOptions", "loadMethod": "listModels"}
        warnings = _validate_render_safe(param)
        assert len(warnings) == 0

    def test_number_non_numeric_default(self):
        param = {"name": "temp", "type": "number", "default": "not a number"}
        warnings = _validate_render_safe(param)
        assert len(warnings) == 1
        assert "not numeric" in warnings[0]

    def test_number_numeric_default_ok(self):
        param = {"name": "temp", "type": "number", "default": 0.9}
        assert _validate_render_safe(param) == []

    def test_boolean_non_bool_default(self):
        param = {"name": "flag", "type": "boolean", "default": "yes"}
        warnings = _validate_render_safe(param)
        assert len(warnings) == 1
        assert "not bool" in warnings[0]

    def test_boolean_bool_default_ok(self):
        param = {"name": "flag", "type": "boolean", "default": True}
        assert _validate_render_safe(param) == []


# ---------------------------------------------------------------------------
# Full normalization integration tests
# ---------------------------------------------------------------------------


class TestNormalizationRenderSafe:
    def test_number_default_coerced(self):
        raw = {
            "name": "chatOpenAI",
            "baseClasses": ["BaseChatModel"],
            "inputs": [
                {"name": "temperature", "type": "number", "default": "0.9"},
            ],
        }
        schema = _normalize_api_schema(raw)
        temp_param = schema["inputParams"][0]
        assert temp_param["default"] == 0.9
        assert isinstance(temp_param["default"], float)

    def test_boolean_default_coerced(self):
        raw = {
            "name": "chatOpenAI",
            "baseClasses": ["BaseChatModel"],
            "inputs": [
                {"name": "streaming", "type": "boolean", "default": "True"},
            ],
        }
        schema = _normalize_api_schema(raw)
        param = schema["inputParams"][0]
        assert param["default"] is True

    def test_options_param_gets_empty_list(self):
        raw = {
            "name": "testNode",
            "baseClasses": ["Base"],
            "inputs": [
                {"name": "mode", "type": "options"},
            ],
        }
        schema = _normalize_api_schema(raw)
        param = schema["inputParams"][0]
        assert param["options"] == []

    def test_ui_fields_preserved(self):
        """UI-relevant fields from Flowise API must survive normalization."""
        raw = {
            "name": "chatOpenAI",
            "baseClasses": ["BaseChatModel"],
            "inputs": [
                {
                    "name": "systemMessage",
                    "type": "string",
                    "label": "System Message",
                    "rows": 4,
                    "step": 0.1,
                    "additionalParams": True,
                    "show": True,
                    "loadMethod": "listModels",
                    "credentialNames": ["openAIApi"],
                    "options": [{"label": "A", "name": "a"}],
                    "description": "A very long description that should not be truncated.",
                    "optional": True,
                    "default": "Hello",
                    "placeholder": "Enter message...",
                },
            ],
        }
        schema = _normalize_api_schema(raw)
        param = schema["inputParams"][0]

        # All fields preserved
        assert param["label"] == "System Message"
        assert param["rows"] == 4
        assert param["step"] == 0.1
        assert param["additionalParams"] is True
        assert param["show"] is True
        assert param["loadMethod"] == "listModels"
        assert param["credentialNames"] == ["openAIApi"]
        assert param["options"] == [{"label": "A", "name": "a"}]
        assert param["optional"] is True
        assert param["default"] == "Hello"
        assert param["placeholder"] == "Enter message..."
        # Description NOT truncated — full string preserved
        assert param["description"] == "A very long description that should not be truncated."
