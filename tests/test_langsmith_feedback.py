"""Tests for flowise_dev_agent.util.langsmith.feedback (DD-086).

Uses mocked LangSmith Client to verify feedback submission logic.
"""

from __future__ import annotations

from unittest import mock

import pytest

from flowise_dev_agent.util.langsmith import feedback as feedback_mod


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


@pytest.mark.asyncio
async def test_submit_with_run_id(mock_client):
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
async def test_submit_rejected(mock_client):
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
async def test_resolves_run_id_from_thread(mock_client):
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
async def test_skips_when_run_id_unresolvable(mock_client):
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
async def test_truncates_long_comment(mock_client):
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
async def test_disabled_when_no_client():
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
