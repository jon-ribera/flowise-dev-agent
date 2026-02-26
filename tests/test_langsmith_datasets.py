"""Tests for flowise_dev_agent.util.langsmith.datasets.

Uses mocked LangSmith Client to verify trace-to-dataset logic.
"""

from __future__ import annotations

from unittest import mock

import pytest

from flowise_dev_agent.util.langsmith import datasets as datasets_mod


@pytest.fixture(autouse=True)
def _enable_langsmith(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")


@pytest.fixture()
def mock_client():
    client = mock.MagicMock()
    with mock.patch(
        "flowise_dev_agent.util.langsmith.get_client", return_value=client
    ):
        yield client


@pytest.mark.asyncio
async def test_save_session_success(mock_client):
    fake_run = mock.MagicMock()
    fake_run.id = "run-abc"
    mock_client.list_runs.return_value = [fake_run]

    result = await datasets_mod.save_session_to_dataset("thread-1")
    assert result is True
    mock_client.create_example_from_run.assert_called_once_with(
        run_id="run-abc", dataset_name="flowise-agent-golden-set"
    )


@pytest.mark.asyncio
async def test_save_session_no_runs_found(mock_client):
    mock_client.list_runs.return_value = []
    result = await datasets_mod.save_session_to_dataset("thread-unknown")
    assert result is False
    mock_client.create_example_from_run.assert_not_called()


@pytest.mark.asyncio
async def test_save_session_custom_dataset(mock_client):
    fake_run = mock.MagicMock()
    fake_run.id = "run-xyz"
    mock_client.list_runs.return_value = [fake_run]

    result = await datasets_mod.save_session_to_dataset("t", dataset_name="custom-ds")
    assert result is True
    assert mock_client.create_example_from_run.call_args.kwargs["dataset_name"] == "custom-ds"


@pytest.mark.asyncio
async def test_disabled_when_no_client():
    with mock.patch(
        "flowise_dev_agent.util.langsmith.get_client", return_value=None
    ):
        assert await datasets_mod.save_session_to_dataset("t") is False
