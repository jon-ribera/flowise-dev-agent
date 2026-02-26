"""M10.1 — Internalize FlowiseClient (DD-078).

Tests that the new ``flowise_dev_agent.client`` package provides identical
behaviour to the removed ``cursorwise`` dependency.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestSettings:
    """Settings.from_env reads env vars correctly with defaults."""

    def test_defaults(self):
        """Default values when no env vars are set."""
        with patch.dict(os.environ, {}, clear=True):
            from flowise_dev_agent.client.config import Settings

            s = Settings.from_env()
            assert s.api_key == ""
            assert s.api_endpoint == "http://localhost:3000"
            assert s.timeout == 120
            assert s.log_level == "WARNING"

    def test_env_override(self):
        """Env vars override defaults."""
        env = {
            "FLOWISE_API_KEY": "test-key-123",
            "FLOWISE_API_ENDPOINT": "https://flowise.example.com/",
            "FLOWISE_TIMEOUT": "60",
            "CURSORWISE_LOG_LEVEL": "debug",
        }
        with patch.dict(os.environ, env, clear=True):
            from flowise_dev_agent.client.config import Settings

            s = Settings.from_env()
            assert s.api_key == "test-key-123"
            # Trailing slash stripped
            assert s.api_endpoint == "https://flowise.example.com"
            assert s.timeout == 60
            assert s.log_level == "DEBUG"

    def test_base_url(self):
        """base_url appends /api/v1."""
        from flowise_dev_agent.client.config import Settings

        s = Settings(api_key="", api_endpoint="http://localhost:3000")
        assert s.base_url == "http://localhost:3000/api/v1"

    def test_headers_with_key(self):
        """Authorization header present when api_key is set."""
        from flowise_dev_agent.client.config import Settings

        s = Settings(api_key="my-key")
        h = s.headers
        assert h["Content-Type"] == "application/json"
        assert h["Authorization"] == "Bearer my-key"

    def test_headers_without_key(self):
        """No Authorization header when api_key is empty."""
        from flowise_dev_agent.client.config import Settings

        s = Settings(api_key="")
        h = s.headers
        assert "Authorization" not in h

    def test_frozen(self):
        """Settings is immutable (frozen dataclass)."""
        from flowise_dev_agent.client.config import Settings

        s = Settings(api_key="x")
        with pytest.raises(AttributeError):
            s.api_key = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FlowiseClient instantiation
# ---------------------------------------------------------------------------


class TestFlowiseClientInit:
    """FlowiseClient wraps httpx.AsyncClient correctly."""

    def test_creates_httpx_client(self):
        from flowise_dev_agent.client import FlowiseClient, Settings

        s = Settings(api_key="k", api_endpoint="http://localhost:3000", timeout=30)
        client = FlowiseClient(s)
        assert client._client is not None
        assert isinstance(client._client, httpx.AsyncClient)

    def test_base_url_set(self):
        from flowise_dev_agent.client import FlowiseClient, Settings

        s = Settings(api_key="k", api_endpoint="http://myhost:4000")
        client = FlowiseClient(s)
        assert str(client._client.base_url).rstrip("/") == "http://myhost:4000/api/v1"


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------


class TestHttpErrorHandling:
    """HTTP errors return {error, detail} dicts without raising."""

    @pytest.mark.asyncio
    async def test_get_http_error(self):
        from flowise_dev_agent.client import FlowiseClient, Settings

        s = Settings(api_key="")
        client = FlowiseClient(s)

        mock_response = httpx.Response(
            status_code=404,
            request=httpx.Request("GET", "http://test/api/v1/chatflows/bad-id"),
            text="Not Found",
        )
        client._client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "404", request=mock_response.request, response=mock_response,
        ))

        result = await client._get("/chatflows/bad-id")
        assert "error" in result
        assert "404" in result["error"]
        assert "detail" in result

    @pytest.mark.asyncio
    async def test_post_http_error(self):
        from flowise_dev_agent.client import FlowiseClient, Settings

        s = Settings(api_key="")
        client = FlowiseClient(s)

        mock_response = httpx.Response(
            status_code=500,
            request=httpx.Request("POST", "http://test/api/v1/chatflows"),
            text="Internal Server Error",
        )
        client._client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
            "500", request=mock_response.request, response=mock_response,
        ))

        result = await client._post("/chatflows", {"name": "test"})
        assert "error" in result
        assert "500" in result["error"]

    @pytest.mark.asyncio
    async def test_get_connection_error(self):
        """Network errors also return an error dict, not raise."""
        from flowise_dev_agent.client import FlowiseClient, Settings

        s = Settings(api_key="")
        client = FlowiseClient(s)
        client._client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        result = await client._get("/chatflows")
        assert "error" in result


# ---------------------------------------------------------------------------
# API method smoke tests (mocked transport)
# ---------------------------------------------------------------------------


class TestApiMethods:
    """Verify API methods call correct paths with mocked transport."""

    @pytest.mark.asyncio
    async def test_list_chatflows(self):
        from flowise_dev_agent.client import FlowiseClient, Settings

        s = Settings(api_key="")
        client = FlowiseClient(s)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"id": "abc", "name": "Test"}]
        mock_resp.raise_for_status = MagicMock()
        client._client.get = AsyncMock(return_value=mock_resp)

        result = await client.list_chatflows()
        assert isinstance(result, list)
        assert result[0]["id"] == "abc"
        client._client.get.assert_called_once_with("/chatflows", params=None)

    @pytest.mark.asyncio
    async def test_get_chatflow(self):
        from flowise_dev_agent.client import FlowiseClient, Settings

        s = Settings(api_key="")
        client = FlowiseClient(s)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "abc", "flowData": "{}"}
        mock_resp.raise_for_status = MagicMock()
        client._client.get = AsyncMock(return_value=mock_resp)

        result = await client.get_chatflow("abc")
        assert result["id"] == "abc"
        client._client.get.assert_called_once_with("/chatflows/abc", params=None)

    @pytest.mark.asyncio
    async def test_create_chatflow(self):
        from flowise_dev_agent.client import FlowiseClient, Settings

        s = Settings(api_key="")
        client = FlowiseClient(s)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"id": "new-id"}'
        mock_resp.json.return_value = {"id": "new-id"}
        mock_resp.raise_for_status = MagicMock()
        client._client.post = AsyncMock(return_value=mock_resp)

        result = await client.create_chatflow("My Flow", description="test")
        assert result["id"] == "new-id"

    @pytest.mark.asyncio
    async def test_get_node(self):
        from flowise_dev_agent.client import FlowiseClient, Settings

        s = Settings(api_key="")
        client = FlowiseClient(s)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"name": "chatOpenAI", "type": "ChatOpenAI"}
        mock_resp.raise_for_status = MagicMock()
        client._client.get = AsyncMock(return_value=mock_resp)

        result = await client.get_node("chatOpenAI")
        assert result["name"] == "chatOpenAI"

    @pytest.mark.asyncio
    async def test_ping(self):
        from flowise_dev_agent.client import FlowiseClient, Settings

        s = Settings(api_key="")
        client = FlowiseClient(s)

        mock_resp = MagicMock()
        mock_resp.text = "pong"
        client._client.get = AsyncMock(return_value=mock_resp)

        result = await client.ping()
        assert result == {"status": "pong"}


# ---------------------------------------------------------------------------
# parse_json_str helper
# ---------------------------------------------------------------------------


class TestParseJsonStr:
    """_parse_json_str returns {} on bad/empty input."""

    def test_none(self):
        from flowise_dev_agent.client.flowise_client import FlowiseClient

        assert FlowiseClient._parse_json_str(None) == {}

    def test_empty(self):
        from flowise_dev_agent.client.flowise_client import FlowiseClient

        assert FlowiseClient._parse_json_str("") == {}

    def test_valid(self):
        from flowise_dev_agent.client.flowise_client import FlowiseClient

        assert FlowiseClient._parse_json_str('{"a": 1}') == {"a": 1}

    def test_invalid(self):
        from flowise_dev_agent.client.flowise_client import FlowiseClient

        assert FlowiseClient._parse_json_str("not json") == {}


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


class TestImportSmoke:
    """Verify all cursorwise-using modules import successfully."""

    def test_import_client_package(self):
        from flowise_dev_agent.client import FlowiseClient, Settings

        assert FlowiseClient is not None
        assert Settings is not None

    def test_import_graph(self):
        from flowise_dev_agent.agent import graph  # noqa: F401

    def test_import_tools(self):
        from flowise_dev_agent.agent import tools  # noqa: F401

    def test_import_instance_pool(self):
        from flowise_dev_agent import instance_pool  # noqa: F401

    def test_import_cli(self):
        from flowise_dev_agent import cli  # noqa: F401

    def test_import_refresh(self):
        from flowise_dev_agent.knowledge import refresh  # noqa: F401
