"""Multi-instance Flowise client pool.

Allows routing different sessions to different Flowise instances
(e.g. dev / staging / prod, or separate customer tenants).

Configuration via FLOWISE_INSTANCES environment variable (JSON array):

    FLOWISE_INSTANCES='[
        {"id": "dev",  "endpoint": "http://localhost:3000", "api_key": "key1"},
        {"id": "prod", "endpoint": "https://flowise.example.com", "api_key": "key2"}
    ]'

If FLOWISE_INSTANCES is not set, the pool falls back to a single default
instance built from the standard FLOWISE_* env vars.

Usage:
    pool = FlowiseClientPool.from_env()
    client = pool.get("dev")   # returns FlowiseClient for the "dev" instance
    client = pool.get(None)    # returns the default (first) client

See DESIGN_DECISIONS.md — DD-032.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from flowise_dev_agent.client import FlowiseClient, Settings

logger = logging.getLogger("flowise_dev_agent.instance_pool")


class FlowiseClientPool:
    """Pool of FlowiseClient instances keyed by instance ID.

    Lifecycle:
        pool = FlowiseClientPool.from_env()
        client = pool.get("prod")
        ...
        await pool.close_all()
    """

    def __init__(self, clients: dict[str, FlowiseClient], default_id: str) -> None:
        self._clients = clients
        self._default_id = default_id

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "FlowiseClientPool":
        """Build the pool from environment variables.

        Reads FLOWISE_INSTANCES (JSON array) if present; otherwise falls
        back to a single "default" instance from FLOWISE_* env vars.
        """
        raw = os.getenv("FLOWISE_INSTANCES", "").strip()
        if raw:
            try:
                specs: list[dict[str, Any]] = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"FLOWISE_INSTANCES must be a valid JSON array: {e}"
                ) from e
            return cls._from_specs(specs)

        # Single-instance fallback
        settings = Settings.from_env()
        client = FlowiseClient(settings)
        logger.info(
            "FlowiseClientPool: single default instance at %s", settings.api_endpoint
        )
        return cls({"default": client}, default_id="default")

    @classmethod
    def _from_specs(cls, specs: list[dict[str, Any]]) -> "FlowiseClientPool":
        """Build pool from a list of instance spec dicts.

        Each spec must have:
            id:        str  — unique instance identifier
            endpoint:  str  — Flowise API URL
            api_key:   str  — Flowise API key (optional if Flowise has no auth)

        Optional per-spec overrides (same as Settings fields):
            timeout:   int   — request timeout in seconds
            username:  str
            password:  str
        """
        if not specs:
            raise ValueError("FLOWISE_INSTANCES must contain at least one entry")

        clients: dict[str, FlowiseClient] = {}
        default_id = specs[0]["id"]

        for spec in specs:
            instance_id = spec.get("id")
            if not instance_id:
                raise ValueError(f"Each FLOWISE_INSTANCES entry must have an 'id': {spec!r}")
            if instance_id in clients:
                raise ValueError(f"Duplicate FLOWISE_INSTANCES id: {instance_id!r}")

            settings = Settings(
                api_key=spec.get("api_key", ""),
                api_endpoint=spec["endpoint"],
                timeout=int(spec.get("timeout", 120)),
                username=spec.get("username", ""),
                password=spec.get("password", ""),
            )
            clients[instance_id] = FlowiseClient(settings)
            logger.info(
                "FlowiseClientPool: registered instance %r → %s",
                instance_id,
                settings.api_endpoint,
            )

        return cls(clients, default_id=default_id)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, instance_id: str | None) -> FlowiseClient:
        """Return the FlowiseClient for the given instance_id.

        If instance_id is None or empty, returns the default client.
        Raises KeyError if the id is not registered.
        """
        if not instance_id:
            return self._clients[self._default_id]
        if instance_id not in self._clients:
            raise KeyError(
                f"Unknown Flowise instance: {instance_id!r}. "
                f"Registered: {list(self._clients)}"
            )
        return self._clients[instance_id]

    @property
    def instance_ids(self) -> list[str]:
        """List all registered instance IDs."""
        return list(self._clients.keys())

    @property
    def default_id(self) -> str:
        return self._default_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close_all(self) -> None:
        """Close all client connections in the pool."""
        for instance_id, client in self._clients.items():
            try:
                await client.close()
            except Exception as e:
                logger.warning("Error closing client %r: %s", instance_id, e)
