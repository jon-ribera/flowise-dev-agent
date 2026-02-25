"""Persistence layer — Postgres-backed checkpointer and event log.

Exports:
  make_checkpointer(dsn) — async context manager, yields CheckpointerAdapter
  CheckpointerAdapter    — wraps AsyncPostgresSaver with list/exist helpers
  EventLog(dsn)          — session_events insert/query helper

See roadmap9_production_graph_runtime_hardening.md — Milestone 9.1.
"""

from flowise_dev_agent.persistence.checkpointer import (
    CheckpointerAdapter,
    make_checkpointer,
)
from flowise_dev_agent.persistence.event_log import EventLog
from flowise_dev_agent.persistence.hooks import wrap_node

__all__ = [
    "CheckpointerAdapter",
    "make_checkpointer",
    "EventLog",
    "wrap_node",
]
