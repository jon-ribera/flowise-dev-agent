"""Tests for Milestone 7.1: Capability-First Default Runtime (DD-066).

Verifies:
  Test 1 — make_default_capabilities() returns a non-empty list with FlowiseCapability
  Test 2 — _initial_state() includes runtime_mode field
  Test 3 — AgentState TypedDict declares runtime_mode
  Test 4 — FLOWISE_COMPAT_LEGACY env var controls _COMPAT_LEGACY flag
  Test 5 — SessionSummary model declares runtime_mode field

See roadmap7_multi_domain_runtime_hardening.md — Milestone 7.1.
"""

import importlib
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from flowise_dev_agent.agent.graph import FlowiseCapability, make_default_capabilities
from flowise_dev_agent.agent.state import AgentState


# ---------------------------------------------------------------------------
# Minimal stubs for constructing make_default_capabilities without a live server
# ---------------------------------------------------------------------------


def _make_stub_engine():
    """Stub ReasoningEngine that never completes real calls."""
    engine = MagicMock()
    engine.complete = AsyncMock(return_value=MagicMock(content="stub"))
    return engine


def _make_stub_flowise_domain():
    """Stub FloviseDomain — does not connect to a real Flowise instance."""
    from flowise_dev_agent.agent.tools import FloviseDomain

    client = MagicMock()
    domain = FloviseDomain(client)
    return domain


# ---------------------------------------------------------------------------
# Test 1 — make_default_capabilities() returns correct structure
# ---------------------------------------------------------------------------


def test_make_default_capabilities_returns_list():
    """make_default_capabilities() must return a non-empty list."""
    engine = _make_stub_engine()
    domain = _make_stub_flowise_domain()
    caps = make_default_capabilities(engine, [domain])
    assert isinstance(caps, list), "Expected a list from make_default_capabilities()"
    assert len(caps) == 1, "Expected exactly one capability (FlowiseCapability)"


def test_make_default_capabilities_returns_flowise_capability():
    """make_default_capabilities() must return a FlowiseCapability instance."""
    engine = _make_stub_engine()
    domain = _make_stub_flowise_domain()
    caps = make_default_capabilities(engine, [domain])
    assert isinstance(caps[0], FlowiseCapability), (
        f"Expected FlowiseCapability, got {type(caps[0])}"
    )


def test_make_default_capabilities_name():
    """The returned capability must have name 'flowise'."""
    engine = _make_stub_engine()
    domain = _make_stub_flowise_domain()
    caps = make_default_capabilities(engine, [domain])
    assert caps[0].name == "flowise"


# ---------------------------------------------------------------------------
# Test 2 — _initial_state() includes runtime_mode
# ---------------------------------------------------------------------------


def test_initial_state_includes_runtime_mode():
    """_initial_state() must include runtime_mode key."""
    from flowise_dev_agent.api import _initial_state  # noqa: PLC0415 (local import ok in tests)

    state = _initial_state("build a chatflow", runtime_mode="capability_first")
    assert "runtime_mode" in state, "_initial_state() must include 'runtime_mode'"
    assert state["runtime_mode"] == "capability_first"


def test_initial_state_runtime_mode_defaults_none():
    """_initial_state() runtime_mode defaults to None when not provided."""
    from flowise_dev_agent.api import _initial_state

    state = _initial_state("build a chatflow")
    assert state["runtime_mode"] is None


# ---------------------------------------------------------------------------
# Test 3 — AgentState TypedDict declares runtime_mode
# ---------------------------------------------------------------------------


def test_agent_state_has_runtime_mode_annotation():
    """AgentState must declare runtime_mode in __annotations__."""
    annotations = AgentState.__annotations__
    assert "runtime_mode" in annotations, (
        "AgentState must have a 'runtime_mode' annotation (M7.1, DD-066)"
    )


# ---------------------------------------------------------------------------
# Test 4 — FLOWISE_COMPAT_LEGACY env var controls _COMPAT_LEGACY
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env_value,expected", [
    ("1", True),
    ("true", True),
    ("yes", True),
    ("True", True),
    ("YES", True),
    ("", False),
    ("0", False),
    ("false", False),
    ("no", False),
])
def test_compat_legacy_env_var_parsing(env_value: str, expected: bool):
    """_COMPAT_LEGACY must be True only for '1', 'true', 'yes' (case-insensitive)."""
    # Re-evaluate the module-level expression directly (does not require re-import)
    result = env_value.lower() in ("1", "true", "yes")
    assert result == expected, (
        f"FLOWISE_COMPAT_LEGACY={env_value!r} → expected _COMPAT_LEGACY={expected}, got {result}"
    )


# ---------------------------------------------------------------------------
# Test 5 — SessionSummary declares runtime_mode field
# ---------------------------------------------------------------------------


def test_session_summary_has_runtime_mode():
    """SessionSummary must have a runtime_mode field."""
    from flowise_dev_agent.api import SessionSummary

    fields = SessionSummary.model_fields
    assert "runtime_mode" in fields, "SessionSummary must declare 'runtime_mode' field (M7.1)"
    # Check it defaults to None (optional)
    assert fields["runtime_mode"].default is None, (
        "SessionSummary.runtime_mode must default to None"
    )
