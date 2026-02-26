"""Regression tests for the _build_response race condition.

Verifies that _build_response does NOT return status="completed" when the
graph has just been initialized (done=False) but has no pending next nodes.
This race condition caused a "Built Successfully" flash in the UI.

See Bug 1 in the plan: vivid-stargazing-fox.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Minimal stand-ins for the LangGraph snapshot structure
# ---------------------------------------------------------------------------

@dataclass
class FakeInterrupt:
    value: dict


@dataclass
class FakeTask:
    interrupts: list[FakeInterrupt] = field(default_factory=list)


@dataclass
class FakeSnapshot:
    values: dict[str, Any]
    next: tuple[str, ...]
    tasks: list[FakeTask] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _initial_state_stub(**overrides: Any) -> dict:
    """Return a minimal initial-state dict resembling _initial_state output."""
    base: dict[str, Any] = {
        "requirement": "build a chatflow",
        "session_name": "Test Session",
        "done": False,
        "iteration": 0,
        "chatflow_id": None,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_completed_when_done_true():
    """When the graph finishes (done=True, next=()), status should be 'completed'."""
    from flowise_dev_agent.api import _build_response

    snapshot = FakeSnapshot(
        values=_initial_state_stub(done=True, iteration=2, chatflow_id="abc123"),
        next=(),
        tasks=[],
    )
    graph = AsyncMock()
    graph.aget_state.return_value = snapshot

    with patch("flowise_dev_agent.api._enrich_langsmith_run", new_callable=AsyncMock):
        resp = await _build_response(graph, {"configurable": {"thread_id": "t1"}}, "t1")

    assert resp.status == "completed"
    assert resp.iteration == 2
    assert resp.chatflow_id == "abc123"


@pytest.mark.asyncio
async def test_mid_run_when_done_false_no_next():
    """Race condition scenario: done=False, next=(), no interrupts.

    This happens when the GET arrives between checkpoint write and first node
    scheduling during a streaming session. Must NOT return 'completed'.
    """
    from flowise_dev_agent.api import _build_response

    snapshot = FakeSnapshot(
        values=_initial_state_stub(done=False),
        next=(),
        tasks=[],
    )
    graph = AsyncMock()
    graph.aget_state.return_value = snapshot

    with patch("flowise_dev_agent.api._enrich_langsmith_run", new_callable=AsyncMock):
        resp = await _build_response(graph, {"configurable": {"thread_id": "t2"}}, "t2")

    # Must NOT be "completed" — the graph hasn't actually finished
    assert resp.status != "completed"
    assert resp.status == "pending_interrupt"
    assert "mid-execution" in (resp.message or "").lower()


@pytest.mark.asyncio
async def test_interrupt_returns_pending():
    """When a HITL interrupt is pending, status should be 'pending_interrupt'."""
    from flowise_dev_agent.api import _build_response

    interrupt_payload = {
        "type": "plan_approval",
        "prompt": "Approve this plan?",
        "plan": "Step 1: do stuff",
    }
    snapshot = FakeSnapshot(
        values=_initial_state_stub(done=False, iteration=1),
        next=("hitl_plan_v2",),
        tasks=[FakeTask(interrupts=[FakeInterrupt(value=interrupt_payload)])],
    )
    graph = AsyncMock()
    graph.aget_state.return_value = snapshot

    with patch("flowise_dev_agent.api._enrich_langsmith_run", new_callable=AsyncMock):
        resp = await _build_response(graph, {"configurable": {"thread_id": "t3"}}, "t3")

    assert resp.status == "pending_interrupt"
    assert resp.interrupt is not None
    assert resp.interrupt.type == "plan_approval"
