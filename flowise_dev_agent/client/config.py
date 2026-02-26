"""Configuration for the Flowise HTTP client."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    """Immutable settings loaded from environment variables."""

    api_key: str = field(repr=False)
    api_endpoint: str = "http://localhost:3000"
    timeout: int = 120
    log_level: str = "WARNING"

    @classmethod
    def from_env(cls) -> Settings:
        api_key = os.getenv("FLOWISE_API_KEY", "")
        api_endpoint = os.getenv("FLOWISE_API_ENDPOINT", "http://localhost:3000").rstrip("/")
        timeout = int(os.getenv("FLOWISE_TIMEOUT", "120"))
        log_level = os.getenv("CURSORWISE_LOG_LEVEL", "WARNING").upper()
        return cls(
            api_key=api_key,
            api_endpoint=api_endpoint,
            timeout=timeout,
            log_level=log_level,
        )

    @property
    def base_url(self) -> str:
        return f"{self.api_endpoint}/api/v1"

    @property
    def headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h
