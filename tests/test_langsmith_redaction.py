"""Tests for flowise_dev_agent.util.langsmith.redaction (DD-084).

Verifies that API keys, credentials, passwords, JWTs, Postgres DSNs,
and env-var literal values are redacted before reaching LangSmith traces.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from flowise_dev_agent.util.langsmith.redaction import (
    hide_inputs,
    hide_metadata,
    hide_outputs,
    redact_dict,
    redact_string,
    redact_value,
)


# ---------------------------------------------------------------------------
# redact_string
# ---------------------------------------------------------------------------


class TestRedactString:
    def test_anthropic_key(self):
        s = "key=sk-ant-api03-iEw23LByBOlHpnZV5QDwg3w9sJG33LoQUYeeHxAmd2l2ew"
        result = redact_string(s)
        assert "sk-ant-" not in result
        assert "***REDACTED_ANTHROPIC_KEY***" in result

    def test_openai_key_sk_proj(self):
        s = "key=sk-proj-bPUiQV9_Lph5ATpAatdGSWj37fSEux8ZmlhwVVPB4k7W"
        result = redact_string(s)
        assert "sk-proj-" not in result
        assert "***REDACTED_OPENAI_KEY***" in result

    def test_langsmith_key(self):
        s = "key=lsv2_pt_" + "a" * 32 + "_" + "b" * 10
        result = redact_string(s)
        assert "lsv2_pt_" not in result
        assert "***REDACTED_LANGSMITH_KEY***" in result

    def test_github_token(self):
        s = "token=ghp_" + "X" * 36
        result = redact_string(s)
        assert "ghp_" not in result
        assert "***REDACTED_GITHUB_TOKEN***" in result

    def test_bearer_token(self):
        s = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature"
        result = redact_string(s)
        assert "eyJ" not in result

    def test_jwt_token(self):
        s = "token=eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0In0.sig_value_here"
        result = redact_string(s)
        assert "eyJ" not in result
        assert "***REDACTED_JWT***" in result

    def test_postgres_dsn(self):
        s = "dsn=postgresql://postgres:secretpass@localhost:5432/mydb"
        result = redact_string(s)
        assert "secretpass" not in result
        assert "postgresql://***:***@" in result

    def test_non_sensitive_unchanged(self):
        s = "Hello world, this is normal text with no secrets."
        assert redact_string(s) == s

    def test_env_var_literal_scrub(self):
        fake_key = "rQDMz82MopWBAqHhh_5i76f3NvGGHAxBk_WHwikIB2c"
        with mock.patch.dict(os.environ, {"FLOWISE_API_KEY": fake_key}):
            s = f"Using key {fake_key} in request"
            result = redact_string(s)
            assert fake_key not in result
            assert "***REDACTED_FLOWISE_API_KEY***" in result

    def test_short_env_var_not_scrubbed(self):
        """Env values <= 8 chars are too short to safely scrub by literal match."""
        with mock.patch.dict(os.environ, {"FLOWISE_API_KEY": "short"}):
            s = "The word short appears in text"
            assert redact_string(s) == s


# ---------------------------------------------------------------------------
# redact_dict
# ---------------------------------------------------------------------------


class TestRedactDict:
    def test_sensitive_field_fully_redacted(self):
        d = {"api_key": "sk-ant-abc123def456ghi789jkl012", "name": "test"}
        result = redact_dict(d)
        assert result["api_key"] == "***REDACTED***"
        assert result["name"] == "test"

    def test_nested_dict(self):
        d = {
            "config": {
                "password": "secret123",
                "host": "localhost",
            }
        }
        result = redact_dict(d)
        assert result["config"]["password"] == "***REDACTED***"
        assert result["config"]["host"] == "localhost"

    def test_list_values(self):
        d = {
            "keys": [
                "sk-ant-api03-longkeyvalue1234567890abcdef",
                "normal-value",
            ]
        }
        result = redact_dict(d)
        assert "sk-ant-" not in result["keys"][0]
        assert result["keys"][1] == "normal-value"

    def test_depth_limit_prevents_stack_overflow(self):
        # Build a deeply nested dict
        d: dict = {"value": "safe"}
        for _ in range(15):
            d = {"nested": d}
        # Should not raise
        result = redact_dict(d)
        assert isinstance(result, dict)

    def test_all_sensitive_field_names(self):
        """Every field in _SENSITIVE_FIELDS is redacted."""
        from flowise_dev_agent.util.langsmith.redaction import _SENSITIVE_FIELDS

        d = {field: f"value_for_{field}" for field in _SENSITIVE_FIELDS}
        result = redact_dict(d)
        for field in _SENSITIVE_FIELDS:
            assert result[field] == "***REDACTED***", f"{field} was not redacted"


# ---------------------------------------------------------------------------
# redact_value
# ---------------------------------------------------------------------------


class TestRedactValue:
    def test_string(self):
        assert "sk-ant-" not in redact_value(
            "sk-ant-api03-longkeyvalue1234567890abcdef"
        )

    def test_dict(self):
        result = redact_value({"password": "secret"})
        assert result["password"] == "***REDACTED***"

    def test_list(self):
        result = redact_value(["safe", {"api_key": "secret"}])
        assert result[0] == "safe"
        assert result[1]["api_key"] == "***REDACTED***"

    def test_tuple(self):
        result = redact_value(("safe", "also_safe"))
        assert isinstance(result, tuple)
        assert result == ("safe", "also_safe")

    def test_int_passthrough(self):
        assert redact_value(42) == 42

    def test_none_passthrough(self):
        assert redact_value(None) is None


# ---------------------------------------------------------------------------
# hide_inputs / hide_outputs / hide_metadata
# ---------------------------------------------------------------------------


class TestHideCallbacks:
    def test_hide_inputs(self):
        inputs = {"prompt": "Use key sk-ant-api03-abcdefghijklmnopqrstuvwxyz"}
        result = hide_inputs(inputs)
        assert "sk-ant-" not in result["prompt"]

    def test_hide_outputs(self):
        outputs = {"response": "DSN=postgresql://user:pass123@host:5432/db"}
        result = hide_outputs(outputs)
        assert "pass123" not in result["response"]

    def test_hide_metadata(self):
        meta = {
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "thread_id": "abc-123",
        }
        result = hide_metadata(meta)
        assert result["ANTHROPIC_API_KEY"] == "***REDACTED***"
        assert result["thread_id"] == "abc-123"
