"""Tests for flowise_dev_agent.util.langsmith.rules (DD-088).

Uses mocked LangSmith Client to verify routing logic.
"""

from __future__ import annotations

from unittest import mock

import pytest

from flowise_dev_agent.util.langsmith import rules as rules_mod


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
async def test_add_to_annotation_queue(mock_client):
    queue = mock.MagicMock()
    queue.id = "queue-id-1"
    mock_client.list_annotation_queues.return_value = [queue]

    result = await rules_mod.add_to_annotation_queue("run-1")
    assert result is True
    mock_client.add_runs_to_annotation_queue.assert_called_once_with(
        "queue-id-1", run_ids=["run-1"]
    )


@pytest.mark.asyncio
async def test_annotation_queue_not_found(mock_client):
    mock_client.list_annotation_queues.return_value = []
    result = await rules_mod.add_to_annotation_queue("run-1")
    assert result is False


@pytest.mark.asyncio
async def test_add_to_dataset(mock_client):
    result = await rules_mod.add_to_dataset("run-2")
    assert result is True
    mock_client.create_example_from_run.assert_called_once_with(
        run_id="run-2", dataset_name="flowise-agent-golden-set"
    )


@pytest.mark.asyncio
async def test_disabled_when_no_client():
    with mock.patch(
        "flowise_dev_agent.util.langsmith.get_client", return_value=None
    ):
        assert await rules_mod.add_to_annotation_queue("r") is False
        assert await rules_mod.add_to_dataset("r") is False


def test_setup_instructions():
    text = rules_mod.setup_instructions()
    assert "Rule 1" in text
    assert "annotation queue" in text.lower()
    assert "golden" in text.lower() or "dataset" in text.lower()
