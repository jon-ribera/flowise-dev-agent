"""Per-phase timing and counter telemetry — Milestone 7.4 (DD-069).

PhaseMetrics  — frozen snapshot of one graph phase's counters + duration.
MetricsCollector — async context manager; call .result / .to_dict() after exit.

Usage::

    async with MetricsCollector("patch_b") as m:
        response = await engine.complete(...)
        m.input_tokens = response.input_tokens
        m.output_tokens = response.output_tokens
    phase_dict = m.to_dict()   # JSON-serialisable dict for state["debug"]

The caller is responsible for merging ``m.to_dict()`` into
``debug["flowise"]["phase_metrics"]`` via the node's return dict.

See DESIGN_DECISIONS.md — DD-069.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any


# ---------------------------------------------------------------------------
# PhaseMetrics dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class PhaseMetrics:
    """Timing and counter snapshot for one graph phase.

    Fields
    ------
    phase:           Node/sub-phase name: "discover", "patch_b", "patch_d",
                     "test", "converge".
    start_ts:        Unix timestamp at phase start (time.time()).
    end_ts:          Unix timestamp at phase end.
    duration_ms:     (end_ts - start_ts) * 1000.
    input_tokens:    LLM prompt tokens consumed (0 when no LLM call in phase).
    output_tokens:   LLM completion tokens produced.
    tool_call_count: Number of tool calls dispatched from this phase.
    cache_hits:      Schema/credential lookups served from snapshot (no API call).
    repair_events:   API fallback count (cache miss → targeted repair call).

    All fields are JSON-serialisable via dataclasses.asdict().

    See DESIGN_DECISIONS.md — DD-069.
    """

    phase: str
    start_ts: float
    end_ts: float
    duration_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    tool_call_count: int = 0
    cache_hits: int = 0
    repair_events: int = 0


# ---------------------------------------------------------------------------
# MetricsCollector async context manager
# ---------------------------------------------------------------------------


class MetricsCollector:
    """Async context manager that records per-phase timing and counters.

    Usage::

        async with MetricsCollector("patch_b") as m:
            response = await engine.complete(...)
            m.input_tokens = response.input_tokens
            m.output_tokens = response.output_tokens

        phase_dict = m.to_dict()   # PhaseMetrics as JSON-serialisable dict

    The collector does NOT write to state automatically — the node code is
    responsible for merging ``m.to_dict()`` into
    ``debug["flowise"]["phase_metrics"]`` in its return dict.

    See DESIGN_DECISIONS.md — DD-069.
    """

    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.tool_call_count: int = 0
        self.cache_hits: int = 0
        self.repair_events: int = 0
        self._start_ts: float = 0.0
        self._result: PhaseMetrics | None = None

    async def __aenter__(self) -> "MetricsCollector":
        self._start_ts = time.time()
        return self

    async def __aexit__(self, *_args: object) -> None:
        end_ts = time.time()
        self._result = PhaseMetrics(
            phase=self.phase,
            start_ts=self._start_ts,
            end_ts=end_ts,
            duration_ms=(end_ts - self._start_ts) * 1000,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            tool_call_count=self.tool_call_count,
            cache_hits=self.cache_hits,
            repair_events=self.repair_events,
        )

    @property
    def result(self) -> PhaseMetrics | None:
        """Finalized PhaseMetrics after the context manager exits, else None."""
        return self._result

    def to_dict(self) -> dict[str, Any]:
        """Return the finalized PhaseMetrics as a JSON-serialisable dict.

        Returns an empty dict if called before the context manager has exited.
        """
        return dataclasses.asdict(self._result) if self._result is not None else {}
