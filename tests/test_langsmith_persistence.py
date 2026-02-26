"""Tests for LangSmith persistence: feedback (DD-086), datasets (DD-088), and tracer (DD-088).

Merged from test_langsmith_feedback.py, test_langsmith_datasets.py, and test_langsmith_tracer.py.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from flowise_dev_agent.util.langsmith import feedback as feedback_mod
from flowise_dev_agent.util.langsmith import datasets as datasets_mod
from flowise_dev_agent.util.langsmith.tracer import _is_dev_environment, dev_tracer


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_langsmith(monkeypatch):
    """Ensure LangSmith appears enabled for all tests in this module."""
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")


@pytest.fixture()
def mock_client():
    """Return a mocked LangSmith Client and patch get_client to return it."""
    client = mock.MagicMock()
    with mock.patch(
        "flowise_dev_agent.util.langsmith.get_client", return_value=client
    ):
        yield client


# ===========================================================================
# Feedback tests (from test_langsmith_feedback.py)
# ===========================================================================


@pytest.mark.asyncio
async def test_feedback_submit_with_run_id(mock_client):
    """When run_id is provided, feedback is created directly."""
    await feedback_mod.submit_hitl_feedback(
        thread_id="thread-1",
        interrupt_type="plan_approval",
        approved=True,
        developer_response="Looks good!",
        run_id="run-abc",
    )
    mock_client.create_feedback.assert_called_once_with(
        run_id="run-abc",
        key="hitl_plan_approval",
        score=1.0,
        comment="Looks good!",
    )


@pytest.mark.asyncio
async def test_feedback_submit_rejected(mock_client):
    """Rejected approval creates feedback with score=0.0."""
    await feedback_mod.submit_hitl_feedback(
        thread_id="thread-1",
        interrupt_type="result_review",
        approved=False,
        developer_response="Needs more work",
        run_id="run-xyz",
    )
    mock_client.create_feedback.assert_called_once_with(
        run_id="run-xyz",
        key="hitl_result_review",
        score=0.0,
        comment="Needs more work",
    )


@pytest.mark.asyncio
async def test_feedback_resolves_run_id_from_thread(mock_client):
    """When run_id is not provided, resolves from thread_id via list_runs."""
    fake_run = mock.MagicMock()
    fake_run.id = "resolved-run-id"
    mock_client.list_runs.return_value = [fake_run]

    await feedback_mod.submit_hitl_feedback(
        thread_id="thread-2",
        interrupt_type="plan_approval",
        approved=True,
        developer_response="ok",
    )

    mock_client.list_runs.assert_called_once()
    mock_client.create_feedback.assert_called_once()
    assert mock_client.create_feedback.call_args.kwargs["run_id"] == "resolved-run-id"


@pytest.mark.asyncio
async def test_feedback_skips_when_run_id_unresolvable(mock_client):
    """When no run_id found, feedback is silently skipped."""
    mock_client.list_runs.return_value = []

    await feedback_mod.submit_hitl_feedback(
        thread_id="thread-unknown",
        interrupt_type="plan_approval",
        approved=True,
        developer_response="ok",
    )

    mock_client.create_feedback.assert_not_called()


@pytest.mark.asyncio
async def test_feedback_truncates_long_comment(mock_client):
    """Developer response is truncated to 500 chars."""
    long_response = "x" * 1000

    await feedback_mod.submit_hitl_feedback(
        thread_id="t",
        interrupt_type="plan_approval",
        approved=True,
        developer_response=long_response,
        run_id="run-1",
    )

    comment = mock_client.create_feedback.call_args.kwargs["comment"]
    assert len(comment) == 500


@pytest.mark.asyncio
async def test_feedback_disabled_when_no_client():
    """When LangSmith is disabled, feedback is silently skipped."""
    with mock.patch(
        "flowise_dev_agent.util.langsmith.get_client", return_value=None
    ):
        # Should not raise
        await feedback_mod.submit_hitl_feedback(
            thread_id="t",
            interrupt_type="plan_approval",
            approved=True,
            developer_response="ok",
        )


# ===========================================================================
# Dataset tests (from test_langsmith_datasets.py)
# ===========================================================================


@pytest.mark.asyncio
async def test_dataset_save_session_success(mock_client):
    fake_run = mock.MagicMock()
    fake_run.id = "run-abc"
    mock_client.list_runs.return_value = [fake_run]

    result = await datasets_mod.save_session_to_dataset("thread-1")
    assert result is True
    mock_client.create_example_from_run.assert_called_once_with(
        run_id="run-abc", dataset_name="flowise-agent-golden-set"
    )


@pytest.mark.asyncio
async def test_dataset_save_session_no_runs_found(mock_client):
    mock_client.list_runs.return_value = []
    result = await datasets_mod.save_session_to_dataset("thread-unknown")
    assert result is False
    mock_client.create_example_from_run.assert_not_called()


@pytest.mark.asyncio
async def test_dataset_save_session_custom_dataset(mock_client):
    fake_run = mock.MagicMock()
    fake_run.id = "run-xyz"
    mock_client.list_runs.return_value = [fake_run]

    result = await datasets_mod.save_session_to_dataset("t", dataset_name="custom-ds")
    assert result is True
    assert mock_client.create_example_from_run.call_args.kwargs["dataset_name"] == "custom-ds"


@pytest.mark.asyncio
async def test_dataset_disabled_when_no_client():
    with mock.patch(
        "flowise_dev_agent.util.langsmith.get_client", return_value=None
    ):
        assert await datasets_mod.save_session_to_dataset("t") is False


# ===========================================================================
# Tracer tests (from test_langsmith_tracer.py)
# ===========================================================================


_IS_DEV_CASES = [
    # (env_value_or_sentinel, expected)
    (None, True),       # default (unset) -> dev
    ("dev", True),      # explicit dev
    ("local", True),    # local counts as dev
    ("test", False),    # test is NOT dev
    ("prod", False),    # prod is NOT dev
]


@pytest.mark.parametrize(
    "env_value, expected",
    _IS_DEV_CASES,
    ids=["default_unset", "dev_explicit", "local", "test_disabled", "prod_disabled"],
)
def test_is_dev_environment(env_value, expected):
    """_is_dev_environment returns correct result for each LANGSMITH_ENVIRONMENT value."""
    if env_value is None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LANGSMITH_ENVIRONMENT", None)
            assert _is_dev_environment() is expected
    else:
        with mock.patch.dict(os.environ, {"LANGSMITH_ENVIRONMENT": env_value}):
            assert _is_dev_environment() is expected


class TestDevTracer:
    def test_noop_in_prod(self):
        """In prod, decorator returns the original function unchanged."""
        with mock.patch.dict(os.environ, {"LANGSMITH_ENVIRONMENT": "prod"}):
            @dev_tracer("my_fn")
            def my_fn(x):
                return x + 1

            assert my_fn(1) == 2
            # Should be the original function (no wrapping)
            assert my_fn.__name__ == "my_fn"

    def test_wraps_in_dev(self):
        """In dev, decorator wraps with @traceable (if langsmith installed)."""
        with mock.patch.dict(os.environ, {"LANGSMITH_ENVIRONMENT": "dev"}):
            @dev_tracer("add_one", tags=["test"])
            def add_one(x):
                return x + 1

            # Function still works
            assert add_one(5) == 6
