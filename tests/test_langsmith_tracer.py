"""Tests for flowise_dev_agent.util.langsmith.tracer."""

from __future__ import annotations

import os
from unittest import mock

from flowise_dev_agent.util.langsmith.tracer import _is_dev_environment, dev_tracer


class TestIsDevEnvironment:
    def test_default_is_dev(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LANGSMITH_ENVIRONMENT", None)
            assert _is_dev_environment() is True

    def test_dev_explicit(self):
        with mock.patch.dict(os.environ, {"LANGSMITH_ENVIRONMENT": "dev"}):
            assert _is_dev_environment() is True

    def test_local(self):
        with mock.patch.dict(os.environ, {"LANGSMITH_ENVIRONMENT": "local"}):
            assert _is_dev_environment() is True

    def test_test_disabled(self):
        with mock.patch.dict(os.environ, {"LANGSMITH_ENVIRONMENT": "test"}):
            assert _is_dev_environment() is False

    def test_prod_disabled(self):
        with mock.patch.dict(os.environ, {"LANGSMITH_ENVIRONMENT": "prod"}):
            assert _is_dev_environment() is False


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
