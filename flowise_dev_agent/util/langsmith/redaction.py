"""Redaction layer for LangSmith traces (DD-084).

Ensures no API keys, credentials, passwords, JWTs, or connection strings
leak into LangSmith traces.  Adapts agent-forge's
``src/app/util/langsmith/redaction.py`` pattern for the Flowise Dev Agent.

Usage::

    from flowise_dev_agent.util.langsmith.redaction import (
        hide_inputs,
        hide_outputs,
        hide_metadata,
    )

    # Pass to @traceable or LangSmith Client wrapper
    @traceable(hide_inputs=hide_inputs, hide_outputs=hide_outputs)
    def my_function(...): ...

    # Or apply manually
    clean_meta = hide_metadata(raw_metadata)
"""

from __future__ import annotations

import os
import re
from typing import Any

# ---------------------------------------------------------------------------
# Regex patterns for sensitive values
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Anthropic API key (sk-ant-api03-...)
    (re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}"), "***REDACTED_ANTHROPIC_KEY***"),
    # OpenAI API key (sk-proj-... or sk-...)
    (re.compile(r"sk-proj-[a-zA-Z0-9_\-]{20,}"), "***REDACTED_OPENAI_KEY***"),
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "***REDACTED_OPENAI_KEY***"),
    # LangSmith API key (lsv2_pt_...)
    (re.compile(r"lsv2_pt_[a-zA-Z0-9_]{20,}"), "***REDACTED_LANGSMITH_KEY***"),
    # GitHub token (ghp_...)
    (re.compile(r"ghp_[a-zA-Z0-9]{20,}"), "***REDACTED_GITHUB_TOKEN***"),
    # Bearer token in Authorization headers
    (re.compile(r"Bearer\s+[a-zA-Z0-9._\-]{20,}"), "Bearer ***REDACTED***"),
    # JWT (eyJ...)
    (
        re.compile(
            r"eyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]+"
        ),
        "***REDACTED_JWT***",
    ),
    # Postgres DSN with password  postgresql://user:pass@host
    (re.compile(r"postgresql://[^:]+:[^@]+@"), "postgresql://***:***@"),
]

# ---------------------------------------------------------------------------
# Field names whose values should be entirely replaced
# ---------------------------------------------------------------------------

_SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        # Generic
        "api_key",
        "apiKey",
        "api_secret",
        "password",
        "secret",
        "token",
        "credential_id",
        "encrypted_data",
        "authorization",
        # Env-var key names that might appear as dict keys
        "FLOWISE_API_KEY",
        "FLOWISE_PASSWORD",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "AGENT_API_KEY",
        "LANGCHAIN_API_KEY",
        "POSTGRES_DSN",
        "GHE_TOKEN",
        "GITHUB_TOKEN",
    }
)

# Env vars whose *literal values* should be scrubbed if they appear in strings
_ENV_VARS_TO_SCRUB: tuple[str, ...] = (
    "FLOWISE_API_KEY",
    "FLOWISE_PASSWORD",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AGENT_API_KEY",
    "LANGCHAIN_API_KEY",
    "GHE_TOKEN",
    "GITHUB_TOKEN",
)

_MAX_DEPTH = 10


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def redact_string(value: str) -> str:
    """Apply all regex patterns and literal env-var scrubbing to a string."""
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)

    for env_key in _ENV_VARS_TO_SCRUB:
        env_val = os.getenv(env_key, "")
        if env_val and len(env_val) > 8 and env_val in value:
            value = value.replace(env_val, f"***REDACTED_{env_key}***")

    return value


def redact_value(value: Any, depth: int = 0) -> Any:
    """Recursively redact sensitive content from an arbitrary value."""
    if depth > _MAX_DEPTH:
        return value
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, dict):
        return redact_dict(value, depth)
    if isinstance(value, (list, tuple)):
        redacted = [redact_value(v, depth + 1) for v in value]
        return type(value)(redacted) if isinstance(value, tuple) else redacted
    return value


def redact_dict(data: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Recursively redact sensitive fields and values in a dict."""
    if depth > _MAX_DEPTH:
        return data
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key in _SENSITIVE_FIELDS:
            result[key] = "***REDACTED***"
        else:
            result[key] = redact_value(value, depth + 1)
    return result


# ---------------------------------------------------------------------------
# LangSmith callbacks
# ---------------------------------------------------------------------------


def hide_inputs(inputs: dict) -> dict:
    """LangSmith ``hide_inputs`` callback."""
    return redact_dict(inputs)


def hide_outputs(outputs: dict) -> dict:
    """LangSmith ``hide_outputs`` callback."""
    return redact_dict(outputs)


def hide_metadata(metadata: dict) -> dict:
    """Redact sensitive data from run metadata before submission."""
    return redact_dict(metadata)
