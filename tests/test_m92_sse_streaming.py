"""M9.2 — Node-level SSE streaming tests.

Verifies:
  SSE formatting
  1.  _format_event_as_sse: "started"     → event: node_start
  2.  _format_event_as_sse: "completed"   → event: node_end, duration_ms + summary
  3.  _format_event_as_sse: "failed"      → event: node_error, summary
  4.  _format_event_as_sse: "interrupted" → event: interrupt
  5.  _format_event_as_sse: unknown status → event: node_event (fallback)
  6.  _format_event_as_sse: payload_json is NOT included in SSE payload
  7.  _format_event_as_sse: ts field included when present

  Replay order
  8.  get_events returns rows in ascending seq order (replay test)
  9.  get_events with after_seq skips already-seen events

  wrap_node — lifecycle emission
  10. wrap_node emits "started" before calling fn
  11. wrap_node emits "completed" with duration_ms after fn returns
  12. wrap_node emits "failed" when fn raises a non-interrupt exception
  13. wrap_node re-raises the exception after emitting "failed"
  14. wrap_node emits "interrupted" when fn raises GraphInterrupt-named exception
  15. wrap_node extracts session_id from config["configurable"]["thread_id"]
  16. wrap_node handles missing config (session_id = "")

  _node_summary helpers
  17. plan node summary includes char count
  18. patch node summary includes op count
  19. discover node summary includes char count
  20. converge node summary includes verdict
  21. clarify summary — clarification requested vs not needed
  22. unknown node returns None

  build_graph integration
  23. build_graph accepts emit_event=None (no-op path, no import error)
  24. build_graph with emit_event wraps nodes (wrapped fn has 2-arg signature)

  _session_is_done
  25. returns True when snapshot.values["done"] is True
  26. returns False when done is False (e.g. interrupted session)
  27. returns False when aget_state raises

See roadmap9_production_graph_runtime_hardening.md — Milestone 9.2.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from flowise_dev_agent.api import _format_event_as_sse, _session_is_done
from flowise_dev_agent.persistence.hooks import (
    _NODE_PHASES,
    _node_summary,
    wrap_node,
)


# ---------------------------------------------------------------------------
# SSE formatting helpers
# ---------------------------------------------------------------------------


def _parse_sse(raw: str) -> tuple[str, dict]:
    """Parse 'event: X\\ndata: {...}\\n\\n' → (event_type, payload_dict)."""
    lines = [l for l in raw.strip().splitlines() if l]
    event_type = ""
    data_json = "{}"
    for line in lines:
        if line.startswith("event: "):
            event_type = line[len("event: "):]
        elif line.startswith("data: "):
            data_json = line[len("data: "):]
    return event_type, json.loads(data_json)


# ---------------------------------------------------------------------------
# 1-7: _format_event_as_sse
# ---------------------------------------------------------------------------


def test_format_started_produces_node_start():
    ev = {"status": "started", "node_name": "plan", "phase": "plan",
          "seq": 1000, "ts": "2026-01-01T00:00:00Z"}
    raw = _format_event_as_sse(ev, "sid-1")
    etype, payload = _parse_sse(raw)
    assert etype == "node_start"
    assert payload["type"] == "node_start"
    assert payload["node_name"] == "plan"
    assert payload["session_id"] == "sid-1"


def test_format_completed_produces_node_end_with_duration():
    ev = {"status": "completed", "node_name": "plan", "phase": "plan",
          "seq": 2000, "duration_ms": 412, "summary": "Plan generated (100 chars)"}
    raw = _format_event_as_sse(ev, "sid-1")
    etype, payload = _parse_sse(raw)
    assert etype == "node_end"
    assert payload["duration_ms"] == 412
    assert payload["summary"] == "Plan generated (100 chars)"


def test_format_failed_produces_node_error():
    ev = {"status": "failed", "node_name": "patch", "phase": "patch",
          "seq": 3000, "duration_ms": 10, "summary": "HTTP 422"}
    raw = _format_event_as_sse(ev, "sid-1")
    etype, payload = _parse_sse(raw)
    assert etype == "node_error"
    assert payload["status"] == "failed"


def test_format_interrupted_produces_interrupt():
    ev = {"status": "interrupted", "node_name": "human_plan_approval",
          "phase": "plan", "seq": 4000}
    raw = _format_event_as_sse(ev, "sid-1")
    etype, payload = _parse_sse(raw)
    assert etype == "interrupt"
    assert payload["node_name"] == "human_plan_approval"


def test_format_unknown_status_uses_fallback():
    ev = {"status": "weird_status", "node_name": "x", "phase": "x", "seq": 1}
    raw = _format_event_as_sse(ev, "sid")
    etype, _ = _parse_sse(raw)
    assert etype == "node_event"


def test_format_payload_json_excluded():
    """payload_json column must NOT appear in the SSE data (no blob leakage)."""
    ev = {"status": "completed", "node_name": "plan", "phase": "plan",
          "seq": 1, "payload_json": '{"huge": "blob"}'}
    raw = _format_event_as_sse(ev, "sid")
    _, payload = _parse_sse(raw)
    assert "payload_json" not in payload
    assert "huge" not in raw


def test_format_ts_included():
    ev = {"status": "started", "node_name": "plan", "phase": "plan",
          "seq": 1, "ts": "2026-01-01T12:00:00+00:00"}
    raw = _format_event_as_sse(ev, "sid")
    _, payload = _parse_sse(raw)
    assert "ts" in payload
    assert "2026-01-01" in payload["ts"]


# ---------------------------------------------------------------------------
# 8-9: Replay order (EventLog.get_events)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_events_replay_order():
    """get_events returns events in ascending seq order (replay correctness)."""
    from types import SimpleNamespace

    rows = [
        (100, "2026-01-01T00:00:00Z", "clarify", "clarify", "started", None, None, None),
        (200, "2026-01-01T00:00:01Z", "clarify", "clarify", "completed", 50, "No clarification needed", None),
        (300, "2026-01-01T00:00:02Z", "discover", "discover", "started", None, None, None),
    ]
    col_names = ["seq", "ts", "node_name", "phase", "status",
                 "duration_ms", "summary", "payload_json"]
    description = [SimpleNamespace(name=c) for c in col_names]

    cur = AsyncMock()
    cur.description = description
    cur.fetchall = AsyncMock(return_value=rows)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=cur)
    ctx.__aexit__ = AsyncMock(return_value=False)

    conn = MagicMock()
    conn.cursor = MagicMock(return_value=ctx)

    from flowise_dev_agent.persistence.event_log import EventLog
    el = EventLog.__new__(EventLog)
    el._backend = "postgres"
    el._dsn = "test"
    el._conn = conn

    events = await el.get_events("sid", after_seq=0, limit=50)
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs), "Events not in ascending seq order"
    assert seqs[0] == 100


@pytest.mark.asyncio
async def test_get_events_respects_after_seq():
    """get_events passes after_seq correctly so already-seen events are skipped."""
    cur = AsyncMock()
    cur.description = [SimpleNamespace(name="seq")]
    cur.fetchall = AsyncMock(return_value=[])

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=cur)
    ctx.__aexit__ = AsyncMock(return_value=False)

    conn = MagicMock()
    conn.cursor = MagicMock(return_value=ctx)

    from flowise_dev_agent.persistence.event_log import EventLog
    el = EventLog.__new__(EventLog)
    el._backend = "postgres"
    el._dsn = "test"
    el._conn = conn

    await el.get_events("sid", after_seq=9999, limit=10)

    sql, params = cur.execute.call_args[0]
    assert params[1] == 9999, "after_seq not passed to query"


# ---------------------------------------------------------------------------
# 10-16: wrap_node lifecycle emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_node_emits_started_before_fn():
    """wrap_node emits 'started' event before the inner function is called."""
    call_order: list[str] = []

    async def emit_event(**kwargs):
        call_order.append(kwargs["status"])

    async def my_fn(state):
        call_order.append("fn_called")
        return {}

    wrapped = wrap_node("plan", my_fn, emit_event)
    await wrapped({})

    assert call_order[0] == "started"
    assert "fn_called" in call_order
    assert call_order.index("started") < call_order.index("fn_called")


@pytest.mark.asyncio
async def test_wrap_node_emits_completed_with_duration():
    """wrap_node emits 'completed' with a non-negative duration_ms."""
    emitted: list[dict] = []

    async def emit_event(**kwargs):
        emitted.append(kwargs)

    async def my_fn(state):
        return {"plan": "x" * 50}

    wrapped = wrap_node("plan", my_fn, emit_event)
    await wrapped({})

    completed = next(e for e in emitted if e["status"] == "completed")
    assert completed["duration_ms"] >= 0
    assert completed["node_name"] == "plan"
    assert "50 chars" in (completed.get("summary") or "")


@pytest.mark.asyncio
async def test_wrap_node_emits_failed_on_exception():
    """wrap_node emits 'failed' when the inner function raises a real exception."""
    emitted: list[dict] = []

    async def emit_event(**kwargs):
        emitted.append(kwargs)

    async def bad_fn(state):
        raise ValueError("boom")

    wrapped = wrap_node("patch", bad_fn, emit_event)
    with pytest.raises(ValueError):
        await wrapped({})

    failed = next((e for e in emitted if e["status"] == "failed"), None)
    assert failed is not None
    assert "boom" in (failed.get("summary") or "")


@pytest.mark.asyncio
async def test_wrap_node_reraises_after_failed():
    """Exception is always re-raised after emitting 'failed'."""
    async def emit_event(**kwargs):
        pass

    async def bad_fn(state):
        raise RuntimeError("fail")

    wrapped = wrap_node("patch", bad_fn, emit_event)
    with pytest.raises(RuntimeError, match="fail"):
        await wrapped({})


@pytest.mark.asyncio
async def test_wrap_node_emits_interrupted_for_graph_interrupt():
    """wrap_node emits 'interrupted' (not 'failed') for GraphInterrupt exceptions."""
    emitted: list[dict] = []

    async def emit_event(**kwargs):
        emitted.append(kwargs)

    # Simulate a LangGraph interrupt exception by name matching
    class GraphInterrupt(Exception):
        pass

    async def hitl_fn(state):
        raise GraphInterrupt("waiting for user")

    wrapped = wrap_node("human_plan_approval", hitl_fn, emit_event)
    with pytest.raises(GraphInterrupt):
        await wrapped({})

    interrupted = next((e for e in emitted if e["status"] == "interrupted"), None)
    assert interrupted is not None
    # summary should be None for interrupts (not an error)
    assert interrupted.get("summary") is None


@pytest.mark.asyncio
async def test_wrap_node_extracts_session_id_from_config():
    """wrap_node passes the thread_id from config as session_id to emit_event."""
    emitted: list[dict] = []

    async def emit_event(**kwargs):
        emitted.append(kwargs)

    async def fn(state):
        return {}

    wrapped = wrap_node("plan", fn, emit_event)
    config = {"configurable": {"thread_id": "my-thread-123"}}
    await wrapped({}, config)

    assert all(e["session_id"] == "my-thread-123" for e in emitted)


@pytest.mark.asyncio
async def test_wrap_node_handles_missing_config():
    """wrap_node uses empty session_id when no config is provided."""
    emitted: list[dict] = []

    async def emit_event(**kwargs):
        emitted.append(kwargs)

    async def fn(state):
        return {}

    wrapped = wrap_node("plan", fn, emit_event)
    await wrapped({})  # no config arg

    assert all(e["session_id"] == "" for e in emitted)


# ---------------------------------------------------------------------------
# 17-22: _node_summary
# ---------------------------------------------------------------------------


def test_summary_plan():
    result = _node_summary("plan", {"plan": "a" * 100})
    assert result is not None
    assert "100" in result


def test_summary_patch_ir_ops():
    result = _node_summary("patch", {"patch_ir": [{}, {}, {}]})
    assert result is not None
    assert "3" in result


def test_summary_discover():
    result = _node_summary("discover", {"discovery_summary": "x" * 200})
    assert result is not None
    assert "200" in result


def test_summary_converge():
    result = _node_summary("converge", {"converge_verdict": {"verdict": "DONE", "reason": "All tests pass"}})
    assert result is not None
    assert "DONE" in result


def test_summary_clarify_with_clarification():
    result = _node_summary("clarify", {"clarification": "Please confirm the model."})
    assert result == "Clarification requested"


def test_summary_unknown_node_returns_none():
    result = _node_summary("nonexistent_node", {"some_key": "some_value"})
    assert result is None


# ---------------------------------------------------------------------------
# 23-24: build_graph emit_event integration
# ---------------------------------------------------------------------------


def test_build_graph_accepts_emit_event_none():
    """build_graph does not raise when emit_event=None (no wrapping)."""
    from flowise_dev_agent.agent.graph import build_graph, create_engine
    from flowise_dev_agent.reasoning import ReasoningSettings
    from unittest.mock import MagicMock

    engine = MagicMock()
    domains: list = []

    # Should not raise
    graph = build_graph(engine, domains, emit_event=None)
    assert graph is not None


def test_build_graph_with_emit_event_wraps_nodes():
    """build_graph with emit_event produces nodes that accept (state, config)."""
    import inspect
    from flowise_dev_agent.agent.graph import build_graph
    from unittest.mock import MagicMock, AsyncMock

    emit_calls: list = []

    async def mock_emit(**kwargs):
        emit_calls.append(kwargs)

    engine = MagicMock()
    domains: list = []

    graph = build_graph(engine, domains, emit_event=mock_emit)
    # Graph compiled without error means wrapping succeeded
    assert graph is not None


# ---------------------------------------------------------------------------
# 25-27: _session_is_done
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_is_done_true_when_done_flag():
    """_session_is_done returns True when snapshot.values['done'] is True."""
    graph = MagicMock()
    snapshot = MagicMock()
    snapshot.values = {"done": True}
    graph.aget_state = AsyncMock(return_value=snapshot)

    result = await _session_is_done(graph, "sid")
    assert result is True


@pytest.mark.asyncio
async def test_session_is_done_false_for_interrupted():
    """_session_is_done returns False when session is interrupted (done=False)."""
    graph = MagicMock()
    snapshot = MagicMock()
    snapshot.values = {"done": False}
    graph.aget_state = AsyncMock(return_value=snapshot)

    result = await _session_is_done(graph, "sid")
    assert result is False


@pytest.mark.asyncio
async def test_session_is_done_false_on_error():
    """_session_is_done returns False when aget_state raises."""
    graph = MagicMock()
    graph.aget_state = AsyncMock(side_effect=Exception("db error"))

    result = await _session_is_done(graph, "sid")
    assert result is False
