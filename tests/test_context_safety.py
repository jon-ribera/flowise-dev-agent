"""Context safety gate tests (M8.3 — DD-074).

Ensures that raw snapshot blobs and large JSON payloads never leak into the
LLM message transcript (state["messages"]).

Design contract (DD-048, DD-050):
  - result_to_str(ToolResult) → ToolResult.summary  (compact, prompt-safe)
  - ToolResult.data            → state["debug"]      (never reaches messages)
  - Discover node (capability path) returns "messages": [] so tool raw outputs
    are never injected into the transcript

Tests:
  1. result_to_str enforces summary-only contract for ToolResult
  2. result_to_str passes plain strings through unchanged
  3. result_to_str falls back to json.dumps for arbitrary objects
  4. A ToolResult with large raw data produces a compact summary in messages
  5. No message in a mock state contains raw JSON >500 chars
  6. ToolResult.data is never the same object as ToolResult.summary
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from flowise_dev_agent.agent.tools import ToolResult, result_to_str
from flowise_dev_agent.reasoning import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BIG_JSON = json.dumps({"nodes": [{"id": f"node_{i}", "data": {"x": i * 100}} for i in range(50)]})
assert len(_BIG_JSON) > 500, "fixture must be >500 chars"

_COMPACT_SUMMARY = "5 nodes found in snapshot"


def _make_tool_result(summary: str = _COMPACT_SUMMARY, data: Any = None) -> ToolResult:
    return ToolResult(ok=True, summary=summary, facts={}, data=data or _BIG_JSON, error=None, artifacts=None)


def _is_raw_json_blob(text: str | None, threshold: int = 500) -> bool:
    """Return True if text looks like a raw JSON blob (parseable + over threshold)."""
    if not text or len(text) <= threshold:
        return False
    try:
        parsed = json.loads(text)
        # Only flag as raw blob if it's a dict/list (not a scalar)
        return isinstance(parsed, (dict, list))
    except (json.JSONDecodeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# 1. result_to_str enforces summary-only contract for ToolResult
# ---------------------------------------------------------------------------


def test_result_to_str_uses_summary_not_data():
    """result_to_str must return ToolResult.summary, not ToolResult.data."""
    tr = _make_tool_result()
    result = result_to_str(tr)
    assert result == _COMPACT_SUMMARY
    assert result != _BIG_JSON


def test_result_to_str_summary_is_never_raw_json_blob():
    """The string returned by result_to_str must not be a parseable JSON blob >500 chars."""
    tr = _make_tool_result()
    result = result_to_str(tr)
    assert not _is_raw_json_blob(result), (
        f"result_to_str returned a raw JSON blob ({len(result)} chars)"
    )


# ---------------------------------------------------------------------------
# 2. result_to_str passes plain strings through
# ---------------------------------------------------------------------------


def test_result_to_str_plain_string_passthrough():
    """Plain strings are returned as-is (no transformation)."""
    assert result_to_str("hello") == "hello"
    assert result_to_str("") == ""


def test_result_to_str_long_plain_string_allowed():
    """A long plain string (not a ToolResult) is returned unchanged — no blanket truncation."""
    long_str = "x" * 600
    assert result_to_str(long_str) == long_str


# ---------------------------------------------------------------------------
# 3. result_to_str fallback for arbitrary objects
# ---------------------------------------------------------------------------


def test_result_to_str_dict_becomes_json():
    """Dicts are serialised to JSON strings."""
    d = {"key": "value"}
    result = result_to_str(d)
    assert json.loads(result) == d


def test_result_to_str_none_becomes_string():
    """None is converted to a string representation, not left as None."""
    result = result_to_str(None)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 4. Large raw data in ToolResult stays out of the transcript
# ---------------------------------------------------------------------------


def test_tool_result_data_never_reaches_message():
    """When a ToolResult with a large raw data blob is converted for a message,
    the message content must be the summary, not the data."""
    large_data = _BIG_JSON  # >500 chars, valid JSON
    summary = "50 nodes fetched"
    tr = ToolResult(ok=True, summary=summary, facts={}, data=large_data, error=None, artifacts=None)

    message_content = result_to_str(tr)

    assert message_content == summary
    assert len(message_content) < 200
    assert not _is_raw_json_blob(message_content)


def test_tool_result_data_is_independent_of_summary():
    """ToolResult.data and .summary must be distinct objects."""
    tr = _make_tool_result()
    assert tr.data is not tr.summary
    assert tr.data != tr.summary


# ---------------------------------------------------------------------------
# 5. Mock state: no message contains raw JSON >500 chars
# ---------------------------------------------------------------------------


def _make_mock_state_messages() -> list[Message]:
    """Build a realistic message list simulating a discover + plan + patch session.
    All tool results are formatted via result_to_str (compact summaries only).
    """
    messages: list[Message] = [
        Message(role="user", content="Build a conversational RAG chatflow."),
        Message(role="assistant", content="I'll start by discovering available nodes and credentials."),
        # Tool call + compact result (via result_to_str)
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "tc1", "name": "list_chatflows", "input": {}}],
        ),
        Message(
            role="tool_result",
            content=result_to_str(
                ToolResult(ok=True, summary="3 chatflows found", facts={}, data=_BIG_JSON, error=None, artifacts=None)
            ),
            tool_call_id="tc1",
            tool_name="list_chatflows",
        ),
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "tc2", "name": "get_node", "input": {"name": "chatOpenAI"}}],
        ),
        Message(
            role="tool_result",
            content=result_to_str(
                ToolResult(ok=True, summary="chatOpenAI schema retrieved", facts={}, data=_BIG_JSON, error=None, artifacts=None)
            ),
            tool_call_id="tc2",
            tool_name="get_node",
        ),
        Message(role="assistant", content="Discovery complete. Planning the flow now."),
        Message(role="assistant", content="Plan:\n1. Add chatOpenAI\n2. Add memory\n3. Wire chain"),
    ]
    return messages


def test_no_message_contains_raw_json_blob():
    """No message in a realistic session transcript must contain raw JSON >500 chars."""
    messages = _make_mock_state_messages()
    violations: list[str] = []

    for i, msg in enumerate(messages):
        if msg.content and _is_raw_json_blob(msg.content):
            violations.append(
                f"Message[{i}] role={msg.content[:40]!r} contains raw JSON blob "
                f"({len(msg.content)} chars)"
            )

    assert not violations, "\n".join(violations)


def test_tool_result_messages_are_compact():
    """All tool_result messages must be under 300 chars (summary contract)."""
    messages = _make_mock_state_messages()
    violations: list[str] = []

    for i, msg in enumerate(messages):
        if msg.role == "tool_result" and msg.content:
            if len(msg.content) > 300:
                violations.append(
                    f"Message[{i}] tool_result is {len(msg.content)} chars (expected ≤ 300)"
                )

    assert not violations, "\n".join(violations)


# ---------------------------------------------------------------------------
# 6. debug state values must not appear in messages
# ---------------------------------------------------------------------------


def test_debug_data_not_in_message_content():
    """Values stored in state['debug'] must never appear verbatim in messages."""
    debug_value = _BIG_JSON  # what would go into state["debug"]["flowise"]["raw"]
    tr = ToolResult(ok=True, summary="compact", facts={}, data=debug_value, error=None, artifacts=None)

    msg_content = result_to_str(tr)

    # The exact debug value must not appear in the message
    assert debug_value not in msg_content
    assert msg_content == "compact"
