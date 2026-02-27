"""Schema refresh service with bounded concurrency and Postgres coordination.

Roadmap 11, Milestone 3 (DD-108, DD-109).

Orchestrates a bulk refresh of Flowise node/credential/template schemas from the
live API into the Postgres schema cache. Key properties:

- Single refresh per (base_url, scope) enforced via Postgres advisory lock.
- Bounded concurrency (semaphore) for individual get_node() calls.
- Batch persistence via SchemaCache.put_batch() with chunk_size 50.
- Progress tracked incrementally in schema_refresh_jobs.summary_json.
- Never persists secrets (credential safety enforced by SchemaCache).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# Tuning knobs
_FETCH_CONCURRENCY = 5
_BATCH_CHUNK_SIZE = 50
_PROGRESS_UPDATE_EVERY = 10  # update job progress every N fetches


class RefreshService:
    """Orchestrates schema refresh from Flowise API to Postgres cache.

    Constructed once at app startup with a SchemaCache and FlowiseClient.
    """

    def __init__(self, cache: Any, client: Any) -> None:
        self._cache = cache
        self._client = client

    async def start_refresh(
        self, scope: str, force: bool = False,
    ) -> dict[str, str]:
        """Start a refresh job. Returns {job_id, status, message?}.

        If a refresh is already running for this (base_url, scope), returns
        the existing job_id with status='already_running'.
        """
        # Try advisory lock
        locked = await self._cache.try_advisory_lock(scope)
        if not locked:
            existing = await self._cache.get_latest_running_job(scope)
            if existing:
                return {
                    "job_id": existing["job_id"],
                    "status": "already_running",
                    "message": f"Refresh already running for scope={scope}",
                }
            # Lock held but no running job — stale lock, try to proceed anyway
            # by creating a new job (the lock holder may have crashed)
            locked = True

        job_id = str(uuid4())
        initial_summary = {
            "scope": scope,
            "force": force,
            "nodes_total": 0,
            "nodes_fetched": 0,
            "nodes_failed": 0,
            "credentials_fetched": 0,
            "templates_fetched": 0,
        }
        await self._cache.create_job(job_id, scope, initial_summary)

        # Fire and forget — run executor in background
        asyncio.create_task(
            self._execute(job_id, scope, force),
            name=f"refresh-{job_id[:8]}",
        )

        return {"job_id": job_id, "status": "running"}

    async def get_job_status(self, job_id: str) -> dict | None:
        """Get current job status. Returns None if not found."""
        return await self._cache.get_job(job_id)

    async def _execute(
        self, job_id: str, scope: str, force: bool,
    ) -> None:
        """Run the actual refresh. Updates job row on progress and completion."""
        summary: dict[str, Any] = {
            "scope": scope,
            "force": force,
            "nodes_total": 0,
            "nodes_fetched": 0,
            "nodes_failed": 0,
            "credentials_fetched": 0,
            "templates_fetched": 0,
            "errors": [],
        }
        try:
            if scope in ("all", "nodes"):
                await self._refresh_nodes(job_id, summary, force)
            if scope in ("all", "credentials"):
                await self._refresh_credentials(job_id, summary)
            if scope in ("all", "marketplace"):
                await self._refresh_marketplace(job_id, summary)

            await self._cache.update_job(
                job_id, "success", summary, set_ended=True,
            )
            logger.info(
                "[RefreshService] job=%s completed: %d nodes, %d creds, %d templates",
                job_id[:8],
                summary["nodes_fetched"],
                summary["credentials_fetched"],
                summary["templates_fetched"],
            )
        except Exception as exc:
            summary["errors"].append(str(exc))
            await self._cache.update_job(
                job_id, "failed", summary, set_ended=True,
            )
            logger.error("[RefreshService] job=%s failed: %s", job_id[:8], exc)
        finally:
            try:
                await self._cache.release_advisory_lock(scope)
            except Exception:
                pass

    async def _refresh_nodes(
        self, job_id: str, summary: dict, force: bool,
    ) -> None:
        """Fetch all node schemas with bounded concurrency."""
        from flowise_dev_agent.knowledge.provider import _normalize_api_schema

        # Step 1: list node types
        node_list = await self._client.list_nodes()
        if not isinstance(node_list, list):
            summary["errors"].append("list_nodes returned non-list")
            return

        node_names: list[str] = []
        for item in node_list:
            if isinstance(item, dict):
                name = item.get("name") or item.get("label")
                if name:
                    node_names.append(name)
            elif isinstance(item, str):
                node_names.append(item)

        summary["nodes_total"] = len(node_names)
        await self._cache.update_job(job_id, "running", summary)

        # Step 2: fetch each with bounded concurrency
        sem = asyncio.Semaphore(_FETCH_CONCURRENCY)
        entries: list[tuple[str, dict]] = []
        fetch_count = 0

        async def _fetch_one(name: str) -> None:
            nonlocal fetch_count
            async with sem:
                try:
                    raw = await self._client.get_node(name)
                    if not isinstance(raw, dict) or "error" in raw:
                        summary["nodes_failed"] += 1
                        return
                    normalized = _normalize_api_schema(raw)
                    entries.append((name, normalized))
                    summary["nodes_fetched"] += 1
                except Exception as exc:
                    summary["nodes_failed"] += 1
                    summary["errors"].append(f"{name}: {exc}")

                fetch_count += 1
                if fetch_count % _PROGRESS_UPDATE_EVERY == 0:
                    await self._cache.update_job(job_id, "running", summary)

        await asyncio.gather(*[_fetch_one(n) for n in node_names])

        # Step 3: batch persist
        if entries:
            await self._cache.put_batch(
                "node", entries, ttl_seconds=86400, chunk_size=_BATCH_CHUNK_SIZE,
            )

    async def _refresh_credentials(
        self, job_id: str, summary: dict,
    ) -> None:
        """Fetch credential metadata (no secrets)."""
        try:
            creds = await self._client.list_credentials()
            if isinstance(creds, list):
                entries = []
                for cred in creds:
                    if isinstance(cred, dict):
                        cred_id = cred.get("id") or cred.get("credential_id") or ""
                        entries.append((cred_id, cred))
                if entries:
                    await self._cache.put_batch(
                        "credential", entries, ttl_seconds=3600,
                        chunk_size=_BATCH_CHUNK_SIZE,
                    )
                summary["credentials_fetched"] = len(entries)
        except Exception as exc:
            summary["errors"].append(f"credentials: {exc}")

    async def _refresh_marketplace(
        self, job_id: str, summary: dict,
    ) -> None:
        """Fetch marketplace template metadata."""
        try:
            templates = await self._client.list_marketplace_templates()
            if isinstance(templates, list):
                entries = []
                for tpl in templates:
                    if isinstance(tpl, dict):
                        name = tpl.get("templateName") or tpl.get("name") or ""
                        entries.append((name, tpl))
                if entries:
                    await self._cache.put_batch(
                        "template", entries, ttl_seconds=86400,
                        chunk_size=_BATCH_CHUNK_SIZE,
                    )
                summary["templates_fetched"] = len(entries)
        except Exception as exc:
            summary["errors"].append(f"marketplace: {exc}")
