"""Agent state definition for the Flowise Builder co-pilot.

The AgentState TypedDict is the shared memory that flows through every node
in the LangGraph graph. Each node receives the full state and returns a
partial dict — only the keys it wants to update.

Fields annotated with a reducer function use append semantics (messages).
All other fields use overwrite semantics (last-writer-wins).

See DESIGN_DECISIONS.md — DD-007.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from flowise_dev_agent.reasoning import Message


# ---------------------------------------------------------------------------
# Reducer for the message list
# ---------------------------------------------------------------------------


def _append_messages(existing: list[Message], incoming: list[Message] | None) -> list[Message]:
    """Append new messages to the existing message history.

    LangGraph calls this reducer when a node returns {"messages": [...]}.
    The reducer receives (current_state_value, node_return_value) and must
    return the new state value.
    """
    return existing + (incoming or [])


def _sum_int(existing: int, incoming: int) -> int:
    """Accumulate an integer counter across node updates (used for token totals)."""
    return (existing or 0) + (incoming or 0)


def _merge_domain_dict(existing: dict, incoming: dict | None) -> dict:
    """Merge domain-keyed dicts. Last-writer-wins per domain key.

    LangGraph calls this reducer when a node returns {"artifacts": {...}},
    {"facts": {...}}, or {"debug": {...}}. Each node returns only its own
    domain key (e.g. {"flowise": {...}}), which is merged without overwriting
    other domains' entries.

    Examples:
        _merge_domain_dict({"flowise": 1}, {"workday": 2})
        → {"flowise": 1, "workday": 2}

        _merge_domain_dict({"flowise": {"old": 1}}, {"flowise": {"new": 2}})
        → {"flowise": {"new": 2}}     # flowise key replaced by latest update

    The None guard handles two cases:
      - A node that returns {} for these fields (no update)
      - Old checkpointed sessions that predate these fields (existing=None)

    See DD-050 (State trifurcation: transcript / artifacts / debug).
    """
    if not incoming:
        return existing or {}
    merged = dict(existing or {})
    merged.update(incoming)
    return merged


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    """Full state of a co-development session.

    Lifecycle:
        1. Initialized at session start with requirement + empty fields.
        2. Each node reads the full state and returns a partial update dict.
        3. LangGraph merges updates: reducer fields (messages) are appended,
           all other fields are overwritten.
        4. Human interrupt nodes surface state to the developer and resume
           with their input.
    """

    # -----------------------------------------------------------------------
    # Session identity
    # -----------------------------------------------------------------------

    # The developer's original requirement, set at start and never changed.
    requirement: str

    # -----------------------------------------------------------------------
    # Conversation + tool history (append-only)
    # -----------------------------------------------------------------------

    # Full message history: user turns, assistant turns, tool calls, tool results.
    # Uses the _append_messages reducer — nodes return new messages to add,
    # not the full list.
    messages: Annotated[list[Message], _append_messages]

    # -----------------------------------------------------------------------
    # Working context
    # -----------------------------------------------------------------------

    # The Flowise chatflow being built or modified.
    # Set during discover/patch; carried across iterations.
    chatflow_id: str | None

    # Summary of what was discovered (set by discover node, used by plan node).
    discovery_summary: str | None

    # -----------------------------------------------------------------------
    # Plan
    # -----------------------------------------------------------------------

    # The structured plan text produced by the plan node.
    # Cleared when developer requests changes (set to None).
    plan: str | None

    # -----------------------------------------------------------------------
    # Test results
    # -----------------------------------------------------------------------

    # Output from the test node: happy-path and edge-case results.
    # Overwritten each iteration.
    test_results: str | None

    # -----------------------------------------------------------------------
    # Iteration tracking
    # -----------------------------------------------------------------------

    # Number of complete iterations (discover → patch → test → converge) run so far.
    iteration: int

    # -----------------------------------------------------------------------
    # Completion signals
    # -----------------------------------------------------------------------

    # True when the Definition of Done is met and the developer has accepted.
    done: bool

    # -----------------------------------------------------------------------
    # Human-in-the-loop
    # -----------------------------------------------------------------------

    # Feedback from a human interrupt node.
    # Set by the interrupt node when developer provides feedback.
    # Cleared (set to None) after the downstream node consumes it.
    developer_feedback: str | None

    # -----------------------------------------------------------------------
    # Webhook callbacks (DD-037)
    # -----------------------------------------------------------------------

    # Optional URL to POST interrupt payloads to.
    # None = no webhook. Set via StartSessionRequest.webhook_url.
    webhook_url: str | None

    # -----------------------------------------------------------------------
    # Requirement clarification (DD-033)
    # -----------------------------------------------------------------------

    # Clarifying answers provided by developer before discover.
    # None = no clarification needed or SKIP_CLARIFICATION=true.
    clarification: str | None

    # -----------------------------------------------------------------------
    # Credential status (set once during discover, persists across iterations)
    # -----------------------------------------------------------------------

    # Credential types required by the planned nodes but not found in Flowise.
    # Populated by the discover node from the structured CREDENTIALS_STATUS block
    # in the discovery summary. Triggers the credential_check HITL interrupt.
    # Examples: ["openAIApi", "anthropicApi"]
    credentials_missing: list[str] | None

    # -----------------------------------------------------------------------
    # Converge evaluation (structured evaluator-optimizer feedback)
    # -----------------------------------------------------------------------

    # Structured verdict from the converge node. Set every ITERATE cycle.
    # Keys: verdict ("DONE"|"ITERATE"), category (None|"CREDENTIAL"|"STRUCTURE"|
    #        "LOGIC"|"INCOMPLETE"), reason (str), fixes (list[str]).
    # Consumed by the plan node to produce targeted repair instructions.
    # Cleared (set to None) when verdict is DONE.
    converge_verdict: dict | None

    # -----------------------------------------------------------------------
    # Reliability testing (pass^k)
    # -----------------------------------------------------------------------

    # Number of times to run each test case. Default 1 (pass@1).
    # Set to 2+ to require pass^k reliability across all trials.
    # Each trial uses a unique sessionId.
    test_trials: int

    # -----------------------------------------------------------------------
    # Multi-instance routing (DD-032)
    # -----------------------------------------------------------------------

    # ID of the Flowise instance this session targets (from FlowiseClientPool).
    # None = use the default instance. Set at session start; never changed.
    flowise_instance_id: str | None

    # -----------------------------------------------------------------------
    # Multi-domain context (extensibility for Workday v2)
    # -----------------------------------------------------------------------

    # JSON-serializable context collected per domain during discover.
    # Keys: domain name ("flowise", "workday"). Values: domain-specific summary.
    # Each discover iteration merges into this dict.
    domain_context: dict[str, str]

    # -----------------------------------------------------------------------
    # Structured domain outputs (v2 DomainCapability results — DD-050)
    # -----------------------------------------------------------------------

    # Persistent references produced by tools during discover/patch, per domain.
    # Domain-keyed: {"flowise": {"chatflow_ids": ["abc123"], "snapshot_labels": ["v1.0"]}}
    # Uses _merge_domain_dict: writing {"flowise": ...} preserves "workday" entries.
    artifacts: Annotated[dict[str, Any], _merge_domain_dict]

    # Extracted structured facts per domain (latest iteration wins per domain key).
    # Domain-keyed: {"flowise": {"chatflow_id": "abc123", "node_count": 5}}
    # Read by orchestrator nodes for structured reasoning; avoids re-parsing summaries.
    facts: Annotated[dict[str, Any], _merge_domain_dict]

    # Raw tool outputs per domain, organized by iteration. NOT LLM context — debug only.
    # Domain-keyed: {"flowise": {0: {"list_chatflows": "...", "get_node": "..."}}}
    # Written by discover node when DomainCapability path is active.
    debug: Annotated[dict[str, Any], _merge_domain_dict]

    # -----------------------------------------------------------------------
    # Token usage (accumulated across all LLM calls in this session)
    # -----------------------------------------------------------------------

    # Uses _sum_int reducer — each node adds its delta; LangGraph accumulates.
    total_input_tokens: Annotated[int, _sum_int]
    total_output_tokens: Annotated[int, _sum_int]
