"""LLM abstraction layer — model-agnostic reasoning engine.

This module defines a provider-agnostic interface for any LLM.
New providers (Azure OpenAI, Workday internal LLM, etc.) implement
ReasoningEngine and plug in without touching orchestration logic.

Also owns ReasoningSettings (agent-only config) so that pydantic-settings
stays out of the base MCP server install. See DESIGN_DECISIONS.md — DD-016.

See DESIGN_DECISIONS.md — DD-003, DD-005, DD-006, DD-016.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("flowise_dev_agent.reasoning")


# ---------------------------------------------------------------------------
# Shared data types
# ---------------------------------------------------------------------------


@dataclass
class Message:
    """A single message in a conversation.

    role values:
      "user"        — developer turn
      "assistant"   — LLM turn (may include tool_calls)
      "tool_result" — result of a tool call, sent back to the LLM
    """

    role: str  # "user" | "assistant" | "tool_result"
    content: str | None = None

    # Set on role="assistant" when the LLM requested tool calls:
    tool_calls: list[ToolCall] | None = None

    # Set on role="tool_result":
    tool_call_id: str | None = None  # matches the ToolCall.id that was requested
    tool_name: str | None = None     # Anthropic requires the tool name in results


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""

    id: str                   # opaque ID used to pair requests with results
    name: str                 # tool function name
    arguments: dict[str, Any] # parsed JSON arguments


@dataclass
class ToolDef:
    """Definition of a tool the LLM may call.

    parameters follows JSON Schema format:
        {"type": "object", "properties": {...}, "required": [...]}
    """

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class EngineResponse:
    """Response from the reasoning engine.

    Either content is set (text reply) or tool_calls is non-empty (tool use),
    or both (Anthropic sometimes returns text alongside tool calls).
    """

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use" | "max_tokens"

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class ReasoningEngine(ABC):
    """Abstract base class for any LLM provider.

    Implement this to add a new provider. The orchestration layer (LangGraph)
    calls complete() without knowing which provider is underneath.
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        system: str | None = None,
        tools: list[ToolDef] | None = None,
        temperature: float = 0.2,
    ) -> EngineResponse:
        """Send a conversation to the LLM and return its response.

        Args:
            messages:    Conversation history (user/assistant/tool_result turns).
            system:      Optional system prompt injected before the conversation.
            tools:       Tools the LLM may call. Pass None if no tool use needed.
            temperature: Sampling temperature (0.0–1.0). Lower = more focused.

        Returns:
            EngineResponse with either content text, tool_calls, or both.
        """
        ...

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Human-readable provider/model string for logging, e.g. 'anthropic/claude-sonnet-4-6'."""
        ...


# ---------------------------------------------------------------------------
# Claude (Anthropic) implementation
# ---------------------------------------------------------------------------


class ClaudeEngine(ReasoningEngine):
    """Reasoning engine backed by Anthropic's Claude API.

    Requires: pip install 'flowise-dev-agent[claude]'
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        try:
            import anthropic as _anthropic
            self._anthropic = _anthropic
        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required for ClaudeEngine. "
                "Install it with: pip install 'flowise-dev-agent[claude]'"
            )
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required for ClaudeEngine. "
                "Set it in your environment or .env file."
            )
        self._client = self._anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        logger.info("ClaudeEngine initialized: %s", model)

    @property
    def model_id(self) -> str:
        return f"anthropic/{self._model}"

    async def complete(
        self,
        messages: list[Message],
        system: str | None = None,
        tools: list[ToolDef] | None = None,
        temperature: float = 0.2,
    ) -> EngineResponse:
        anthropic_messages = _to_anthropic_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": anthropic_messages,
            "max_tokens": 8192,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]

        import json as _json
        _payload_chars = len(_json.dumps(kwargs, default=str))
        logger.info(
            "ClaudeEngine.complete: %d messages, %d tools, ~%d payload chars (~%d tokens)",
            len(messages), len(tools or []), _payload_chars, _payload_chars // 4,
        )
        response = await self._client.messages.create(**kwargs)

        tool_calls: list[ToolCall] = []
        content_text: str | None = None

        for block in response.content:
            if block.type == "text":
                content_text = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))

        return EngineResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason or "end_turn",
        )


def _to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert internal Message list to Anthropic API format.

    Key differences from OpenAI:
    - Tool results are sent as user messages with content type "tool_result"
    - Multiple consecutive tool results are batched into one user message
    - Assistant tool calls are content blocks of type "tool_use"
    """
    result: list[dict[str, Any]] = []
    i = 0

    while i < len(messages):
        m = messages[i]

        if m.role == "tool_result":
            # Batch all consecutive tool_result messages into one user message
            tool_result_blocks: list[dict[str, Any]] = []
            while i < len(messages) and messages[i].role == "tool_result":
                tr = messages[i]
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tr.tool_call_id,
                    "content": tr.content or "",
                })
                i += 1
            result.append({"role": "user", "content": tool_result_blocks})

        elif m.role == "assistant" and m.tool_calls:
            content_blocks: list[dict[str, Any]] = []
            if m.content:
                content_blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            result.append({"role": "assistant", "content": content_blocks})
            i += 1

        else:
            result.append({"role": m.role, "content": m.content or ""})
            i += 1

    return result


# ---------------------------------------------------------------------------
# OpenAI implementation
# ---------------------------------------------------------------------------


class OpenAIEngine(ReasoningEngine):
    """Reasoning engine backed by the OpenAI API (GPT-4o, etc.).

    Requires: pip install 'flowise-dev-agent[openai]'
    """

    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        try:
            import openai as _openai
            self._openai = _openai
        except ImportError:
            raise ImportError(
                "The 'openai' package is required for OpenAIEngine. "
                "Install it with: pip install 'flowise-dev-agent[openai]'"
            )
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is required for OpenAIEngine. "
                "Set it in your environment or .env file."
            )
        self._client = self._openai.AsyncOpenAI(api_key=api_key)
        self._model = model
        logger.info("OpenAIEngine initialized: %s", model)

    @property
    def model_id(self) -> str:
        return f"openai/{self._model}"

    async def complete(
        self,
        messages: list[Message],
        system: str | None = None,
        tools: list[ToolDef] | None = None,
        temperature: float = 0.2,
    ) -> EngineResponse:
        oai_messages = _to_openai_messages(messages, system)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": oai_messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            kwargs["tool_choice"] = "auto"

        logger.debug("OpenAIEngine.complete: %d messages, %d tools", len(messages), len(tools or []))
        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                ))

        return EngineResponse(
            content=msg.content,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
        )


def _to_openai_messages(messages: list[Message], system: str | None) -> list[dict[str, Any]]:
    """Convert internal Message list to OpenAI API format."""
    result: list[dict[str, Any]] = []

    if system:
        result.append({"role": "system", "content": system})

    for m in messages:
        if m.role == "tool_result":
            result.append({
                "role": "tool",
                "tool_call_id": m.tool_call_id,
                "content": m.content or "",
            })
        elif m.role == "assistant" and m.tool_calls:
            oai_tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in m.tool_calls
            ]
            result.append({
                "role": "assistant",
                "content": m.content,
                "tool_calls": oai_tool_calls,
            })
        else:
            result.append({"role": m.role, "content": m.content or ""})

    return result


# ---------------------------------------------------------------------------
# Reasoning engine settings  (agent-only — requires pydantic-settings)
# ---------------------------------------------------------------------------


class ReasoningSettings(BaseSettings):
    """Settings for the swappable reasoning engine.

    Automatically reads from environment variables (or a .env file).
    No explicit from_env() call needed — just instantiate: ReasoningSettings()

    Environment variables:
      REASONING_ENGINE      — LLM provider: "claude" | "openai" (default: "claude")
      REASONING_MODEL       — Model name override; leave unset for provider default
      ANTHROPIC_API_KEY     — Required when provider is "claude"
      OPENAI_API_KEY        — Required when provider is "openai"
      REASONING_TEMPERATURE — Sampling temperature 0.0–1.0 (default: 0.2)

    See DESIGN_DECISIONS.md — DD-005, DD-016.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    provider: str = Field(default="claude", validation_alias="REASONING_ENGINE")
    model: str | None = Field(default=None, validation_alias="REASONING_MODEL")
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="ANTHROPIC_API_KEY",
        repr=False,
    )
    openai_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="OPENAI_API_KEY",
        repr=False,
    )
    temperature: float = Field(default=0.2, validation_alias="REASONING_TEMPERATURE")

    @field_validator("provider", mode="before")
    @classmethod
    def lowercase_provider(cls, v: object) -> str:
        return str(v).lower()

    @field_validator("model", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> str | None:
        """Treat empty string REASONING_MODEL as unset (use provider default)."""
        if not v:
            return None
        return str(v)

    @field_validator("temperature")
    @classmethod
    def clamp_temperature(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    # Keep from_env() as a convenience alias for call-sites that use it explicitly.
    @classmethod
    def from_env(cls) -> ReasoningSettings:
        return cls()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_engine(settings: ReasoningSettings) -> ReasoningEngine:
    """Instantiate the configured reasoning engine from ReasoningSettings.

    Reads provider, model, and API keys from settings (which are loaded
    from environment variables). See config.py — ReasoningSettings.
    """
    match settings.provider:
        case "claude" | "anthropic":
            return ClaudeEngine(
                api_key=settings.anthropic_api_key.get_secret_value(),
                model=settings.model or "claude-sonnet-4-6",
            )
        case "openai" | "gpt":
            return OpenAIEngine(
                api_key=settings.openai_api_key.get_secret_value(),
                model=settings.model or "gpt-4o",
            )
        case _:
            raise ValueError(
                f"Unknown reasoning engine provider: {settings.provider!r}. "
                f"Valid options: 'claude', 'openai'"
            )
