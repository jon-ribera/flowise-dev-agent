"""Tests for LangSmith security: redaction (DD-084) and routing rules (DD-088).

Merged from test_langsmith_redaction.py and test_langsmith_rules.py.
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
from flowise_dev_agent.util.langsmith import rules as rules_mod


# ---------------------------------------------------------------------------
# redact_string — parametrized pattern tests
# ---------------------------------------------------------------------------


class TestRedactString:
    @pytest.mark.parametrize(
        "label, input_str, absent, present",
        [
            (
                "anthropic_key",
                "key=sk-ant-api03-iEw23LByBOlHpnZV5QDwg3w9sJG33LoQUYeeHxAmd2l2ew",
                "sk-ant-",
                "***REDACTED_ANTHROPIC_KEY***",
            ),
            (
                "openai_key_sk_proj",
                "key=sk-proj-bPUiQV9_Lph5ATpAatdGSWj37fSEux8ZmlhwVVPB4k7W",
                "sk-proj-",
                "***REDACTED_OPENAI_KEY***",
            ),
            (
                "langsmith_key",
                "key=lsv2_pt_" + "a" * 32 + "_" + "b" * 10,
                "lsv2_pt_",
                "***REDACTED_LANGSMITH_KEY***",
            ),
            (
                "github_token",
                "token=ghp_" + "X" * 36,
                "ghp_",
                "***REDACTED_GITHUB_TOKEN***",
            ),
            (
                "bearer_token",
                "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature",
                "eyJ",
                None,
            ),
            (
                "jwt_token",
                "token=eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0In0.sig_value_here",
                "eyJ",
                "***REDACTED_JWT***",
            ),
            (
                "postgres_dsn",
                "dsn=postgresql://postgres:secretpass@localhost:5432/mydb",
                "secretpass",
                "postgresql://***:***@",
            ),
            (
                "non_sensitive_unchanged",
                "Hello world, this is normal text with no secrets.",
                None,
                None,
            ),
        ],
        ids=[
            "anthropic_key",
            "openai_key_sk_proj",
            "langsmith_key",
            "github_token",
            "bearer_token",
            "jwt_token",
            "postgres_dsn",
            "non_sensitive_unchanged",
        ],
    )
    def test_pattern(self, label, input_str, absent, present):
        result = redact_string(input_str)
        if absent is not None:
            assert absent not in result, f"[{label}] expected '{absent}' to be absent"
        if present is not None:
            assert present in result, f"[{label}] expected '{present}' to be present"
        if absent is None and present is None:
            # non_sensitive_unchanged: string should be identical
            assert result == input_str

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
# redact_value — parametrized type dispatch
# ---------------------------------------------------------------------------


class TestRedactValue:
    @pytest.mark.parametrize(
        "label, input_val, check",
        [
            (
                "string",
                "sk-ant-api03-longkeyvalue1234567890abcdef",
                lambda r: "sk-ant-" not in r,
            ),
            (
                "dict",
                {"password": "secret"},
                lambda r: r["password"] == "***REDACTED***",
            ),
            (
                "list",
                ["safe", {"api_key": "secret"}],
                lambda r: r[0] == "safe" and r[1]["api_key"] == "***REDACTED***",
            ),
            (
                "tuple",
                ("safe", "also_safe"),
                lambda r: isinstance(r, tuple) and r == ("safe", "also_safe"),
            ),
            (
                "int",
                42,
                lambda r: r == 42,
            ),
            (
                "none",
                None,
                lambda r: r is None,
            ),
        ],
        ids=["string", "dict", "list", "tuple", "int", "none"],
    )
    def test_type_dispatch(self, label, input_val, check):
        result = redact_value(input_val)
        assert check(result), f"[{label}] redact_value check failed"


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


# ---------------------------------------------------------------------------
# Rules routing (from test_langsmith_rules.py)
# ---------------------------------------------------------------------------


class TestRulesRouting:
    @pytest.fixture(autouse=True)
    def _enable_langsmith(self, monkeypatch):
        monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")

    @pytest.fixture()
    def mock_client(self):
        client = mock.MagicMock()
        with mock.patch(
            "flowise_dev_agent.util.langsmith.get_client", return_value=client
        ):
            yield client

    @pytest.mark.asyncio
    async def test_add_to_annotation_queue(self, mock_client):
        queue = mock.MagicMock()
        queue.id = "queue-id-1"
        mock_client.list_annotation_queues.return_value = [queue]

        result = await rules_mod.add_to_annotation_queue("run-1")
        assert result is True
        mock_client.add_runs_to_annotation_queue.assert_called_once_with(
            "queue-id-1", run_ids=["run-1"]
        )

    @pytest.mark.asyncio
    async def test_annotation_queue_not_found(self, mock_client):
        mock_client.list_annotation_queues.return_value = []
        result = await rules_mod.add_to_annotation_queue("run-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_add_to_dataset(self, mock_client):
        result = await rules_mod.add_to_dataset("run-2")
        assert result is True
        mock_client.create_example_from_run.assert_called_once_with(
            run_id="run-2", dataset_name="flowise-agent-golden-set"
        )

    @pytest.mark.asyncio
    async def test_disabled_when_no_client(self):
        with mock.patch(
            "flowise_dev_agent.util.langsmith.get_client", return_value=None
        ):
            assert await rules_mod.add_to_annotation_queue("r") is False
            assert await rules_mod.add_to_dataset("r") is False

    def test_setup_instructions(self):
        text = rules_mod.setup_instructions()
        assert "Rule 1" in text
        assert "annotation queue" in text.lower()
        assert "golden" in text.lower() or "dataset" in text.lower()
