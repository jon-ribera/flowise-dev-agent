"""LangGraph state machine for the Flowise Builder co-pilot.

Graph topology:
    START
      │
      ▼
    discover ─────── read-only MCP calls across all registered domains
      │
      ▼
    check_credentials ── if credentials missing → INTERRUPT: credential_check
      │                  developer provides credential IDs, graph resumes
      ▼
    plan ─────────── structured plan: Goal/Inputs/Outputs/Constraints/Success criteria
      │
      ▼
    ⏸ human_plan_approval ── INTERRUPT: developer approves or gives feedback
      │              │
      │              └──── back to plan (with feedback)
      ▼
    patch ────────── minimal write: read → Change Summary → update
      │
      ▼
    test ─────────── create_prediction: happy path + edge case
      │
      ▼
    converge ──────── evaluate Definition of Done
      │         │
      │         └──── back to plan (next iteration)
      ▼
    ⏸ human_result_review ── INTERRUPT: developer accepts or iterates
      │                │
      │                └──── back to plan
      ▼
    END

See DESIGN_DECISIONS.md — DD-007 through DD-010.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from flowise_dev_agent.agent.compiler import GraphIR, compile_patch_ops
from flowise_dev_agent.agent.domain import (
    DomainCapability,
    DomainDiscoveryResult,
    DomainPatchResult,
    TestSuite,
    ValidationReport,
    Verdict,
)
from flowise_dev_agent.agent.patch_ir import (
    AddNode,
    BindCredential,
    op_to_dict,
    ops_from_json,
    validate_patch_ops,
)
from flowise_dev_agent.agent.registry import ToolRegistry
from flowise_dev_agent.agent.state import AgentState
from flowise_dev_agent.agent.tools import (
    DomainTools,
    ToolResult,
    WriteGuard,
    _validate_flow_data,
    execute_tool,
    merge_context,
    merge_tools,
    result_to_str,
)
from cursorwise.client import FlowiseClient
from cursorwise.config import Settings
from flowise_dev_agent.reasoning import Message, ReasoningEngine, ReasoningSettings, ToolDef, create_engine
from flowise_dev_agent.knowledge.provider import FlowiseKnowledgeProvider, TemplateStore
from flowise_dev_agent.agent.metrics import MetricsCollector
from flowise_dev_agent.agent.plan_schema import _parse_plan_contract

logger = logging.getLogger("flowise_dev_agent.agent")

# M7.4 (DD-069): Schema drift policy.  Set FLOWISE_SCHEMA_DRIFT_POLICY to:
#   "warn"    (default) — log a warning and continue
#   "fail"              — return an error message and abort the patch phase
#   "refresh"           — log and continue (refresh scheduling is future work)
_SCHEMA_DRIFT_POLICY: str = os.environ.get(
    "FLOWISE_SCHEMA_DRIFT_POLICY", "warn"
).lower()

# ---------------------------------------------------------------------------
# Base system prompts (derived from FLOWISE_BUILDER_ORCHESTRATOR_CHATFLOW_MCP.md)
# Domain-specific additions are injected via DomainTools.{phase}_context
# ---------------------------------------------------------------------------

_DISCOVER_BASE = """\
You are a Flowise co-pilot in the DISCOVER phase.

Your job: gather the context needed to write a correct plan. This phase is READ-ONLY.

WHAT TO GATHER:
1. Existing chatflows relevant to the requirement (list_chatflows → get_chatflow for relevant ones)
2. Which node types will be needed — identify them by name only; do NOT call get_node
   (all 303 node schemas are pre-loaded locally; the patch phase resolves them automatically)
3. Credentials already saved in Flowise (list_credentials)
4. Marketplace templates that might apply (list_marketplace_templates)

NODE SCHEMA CONTRACT (M9.3): All 303 Flowise node schemas are pre-loaded in a local snapshot.
The patch phase automatically resolves schemas for every node in the approved plan via the
local cache — zero API calls for known nodes. Do NOT call get_node during discover. Calling it
here is redundant and wastes tokens without improving accuracy.
Only call get_node during discover if you need to verify a specific unusual parameter that
cannot be inferred from context and is not covered by any documented constraint below.

RAG CONSTRAINT: Vector stores (memoryVectorStore, pinecone, faiss, etc.) require a document
loader node (plainText, textFile, pdfFile, etc.) wired to their "document" input anchor. Without
a document source the retriever fails at Flowise runtime with "Expected a Runnable" (HTTP 500).
Always include a document loader when planning any RAG flow.

When you have enough information, write a concise Discovery Summary:
- What chatflows currently exist (relevant ones)
- Which nodes and credentials are available for the plan
- Whether a marketplace template covers the requirement
Do NOT call any tools in your final summary response.
"""

_PLAN_BASE = """\
You are a Flowise co-pilot in the PLAN phase.

Based on the discovery above, create a structured plan. NO tool calls — just reasoning.

Your plan MUST include ALL of these sections:

1. GOAL
   One sentence describing what the chatflow does.

2. INPUTS
   What the user sends in (text, files, session context, etc.)

3. OUTPUTS
   What the flow returns (text response, structured JSON, etc.)

4. CONSTRAINTS
   - Credential requirements (which credential types are needed and whether they exist)
   - Model restrictions (function-calling required for tool agents)
   - Any size or rate limits

5. SUCCESS CRITERIA
   Specific, testable conditions that define "done":
   - Happy-path test: "<input>" → response must contain/do X
   - Edge-case test: "<unusual input>" → response must handle it by doing Y

6. PATTERN
   Which chatflow pattern to use:
   - Simple Conversation: ChatModel + Memory + ConversationChain
   - Tool Agent: ChatModel + Memory + Tools + ToolAgent (requires function-calling model)
   - RAG: ChatModel + VectorStore + Embeddings + Retriever + ConversationalRetrievalQAChain
   - Custom: describe the pattern

7. ACTION
   - CREATE a new chatflow (name it), OR
   - UPDATE chatflow_id <id> (name the existing chatflow)

8. APPROACHES (optional — only when multiple strategies are genuinely viable)
   If there are two or more meaningfully different implementation paths the developer
   should choose between, list them under this exact heading:
   ## APPROACHES
   1. <short label>: <one-sentence description>
   2. <short label>: <one-sentence description>
   Omit this section entirely if there is only one clear path forward.
   Do NOT list sub-steps of the same approach as separate approaches.

9. MACHINE-READABLE METADATA (REQUIRED — parser reads these verbatim)
   Append EXACTLY these three sections at the end of your plan.
   Follow the format precisely — spacing and header names must match exactly.

   ## DOMAINS
   <comma-separated domain names involved>
   Use "flowise" for Flowise-only.  Use "flowise,workday" when Workday MCP
   nodes are also required.  No extra text on this line.

   ## CREDENTIALS
   <comma-separated Flowise credentialName values required by this chatflow>
   Example: openAIApi, anthropicApi
   Write "(none)" if no credentials are needed.

   ## DATA_CONTRACTS
   <one line per field that crosses a domain boundary, format:>
   <  fieldName: source-domain → target-domain>
   <  fieldName: source-domain → target-domain [PII]   ← add [PII] if personally identifiable>
   Write "(none)" if there are no cross-domain data flows.

Keep the plan concise. The developer will approve it before any writes happen.
"""

_PATCH_BASE = """\
You are a Flowise co-pilot in the PATCH phase.

You have an approved plan. Execute the minimal change now.

NON-NEGOTIABLE RULES:
1. READ BEFORE WRITE
   Call get_chatflow before update_chatflow. Parse flowData. Never overwrite blindly.

2. ONE CHANGE PER ITERATION
   Add one node, edit one prompt, or rewire one edge. Not all at once.

3. CREDENTIAL BINDING (most common runtime error)
   Every credential-bearing node must have the credential ID in TWO places:
     data.credential        = "<credential_id>"
     data.inputs.credential = "<credential_id>"
   Setting only data.inputs.credential causes "API key missing" at runtime.

4. CHANGE SUMMARY (required before every update_chatflow call)
   Format:
   NODES ADDED:    [id] label="..." name="..."
   NODES REMOVED:  [id] label="..." name="..."
   NODES MODIFIED: [id] fields changed: [...]
   EDGES ADDED:    source→target(type)
   EDGES REMOVED:  source→target(type)
   PROMPTS CHANGED: [node_id] field="..." before="<200 chars>" after="<200 chars>"

5. MINIMUM flow_data
   Always use {"nodes":[],"edges":[]} — never bare {}.

6. PRESERVE IDs
   Keep existing node IDs and edge IDs stable across iterations.

8. VALIDATE BEFORE WRITE
   Call validate_flow_data(flow_data) on the complete flowData JSON string before
   create_chatflow or update_chatflow. Fix ALL reported errors before proceeding.
   Never write invalid flowData to Flowise.

After completing the change, your final response MUST include this exact line:
CHATFLOW_ID: <the-exact-uuid-of-the-created-or-updated-chatflow>

Replace <the-exact-uuid...> with the real UUID from the create_chatflow response
or the chatflow_id you used in update_chatflow. Do not omit this line.
"""

_PATCH_IR_SYSTEM = """\
You are a Flowise co-pilot in the PATCH phase.

Your task: output a JSON array of Patch IR operations that implement the approved plan.
DO NOT include any explanation, markdown fences, or text outside the JSON array.

AVAILABLE OPERATIONS:

1. AddNode — add a new Flowise node
   {"op_type":"add_node","node_name":"<flowise_type>","node_id":"<unique_id>","label":"<display>","params":{"modelName":"gpt-4o"}}

2. SetParam — update a configurable parameter on an existing node
   {"op_type":"set_param","node_id":"<id>","param_name":"<key>","value":"<val>"}

3. Connect — connect two nodes by anchor name (NOT handle IDs — the compiler derives them)
   {"op_type":"connect","source_node_id":"<id>","source_anchor":"<output_name>","target_node_id":"<id>","target_anchor":"<input_type>"}

4. BindCredential — bind a credential ID at BOTH data.credential levels
   {"op_type":"bind_credential","node_id":"<id>","credential_id":"<uuid>","credential_type":"<type>"}

RULES:
1. node_id: unique within the flow — use "<node_name>_<index>" e.g. "chatOpenAI_0"
2. source_anchor: output anchor name — usually the node_name itself (e.g. "chatOpenAI")
3. target_anchor: input anchor TYPE — the baseClass it accepts (e.g. "BaseChatModel", "BaseMemory")
4. EVERY credential-bearing node (LLM, embedding, etc.) MUST have a BindCredential op
5. Include ALL required nodes + connections for a working flow — never omit the chain/agent node
6. Do NOT write handle strings, edge IDs, or raw flowData JSON — the compiler derives all of that
7. source_anchor and target_anchor MUST match real anchor names from get_node — all 303 node
   schemas are available locally at zero cost. Never invent anchor names or param keys.

OUTPUT: A single JSON array only, nothing else.
"""

_TEST_BASE = """\
You are a Flowise co-pilot in the TEST phase.

Test the chatflow that was just patched. Run BOTH tests:

TEST 1 — HAPPY PATH
A normal, expected input that should work perfectly.
Use a unique sessionId in override_config to isolate this session.

TEST 2 — EDGE CASE
An unusual, missing, ambiguous, or boundary input.
Use a different unique sessionId.

For each test, report:
- Input sent
- Response received (full text)
- PASS or FAIL with reason

DIAGNOSIS GUIDE:
| Error | Likely cause |
|---|---|
| "Ending node must be either a Chain or Agent" | No terminal chain/agent node in flow |
| "OPENAI_API_KEY environment variable is missing" | Credential not set at data.credential |
| "404 Not Found" on prediction | Wrong chatflow_id — verify with list_chatflows |
| Empty or very short response | Check if deployed=true is required |

Final line of your response must be:
RESULT: HAPPY PATH [PASS/FAIL] | EDGE CASE [PASS/FAIL]
"""

_CONVERGE_BASE = """\
You are evaluating whether this chatflow meets the Definition of Done.

DEFINITION OF DONE (all must be true):
1. The flow exists and is saved in Flowise
2. Happy-path prediction: PASS (all trials if test_trials > 1)
3. At least one edge-case prediction: PASS (all trials if test_trials > 1)
4. Credentials bound at BOTH data.credential AND data.inputs.credential for all credential nodes
5. A Change Summary was printed before each update_chatflow call

Review the test results and conversation history.

Respond with EXACTLY one of these formats:

DONE

or:

ITERATE
Category: CREDENTIAL | STRUCTURE | LOGIC | INCOMPLETE
Reason: <one line describing what failed>
Fix: <specific action the plan node must take>
Fix: <optional second action>

Use CREDENTIAL when a credential is missing or incorrectly bound.
Use STRUCTURE when flowData is missing required keys or has invalid edges.
Use LOGIC when the flow produces wrong or empty responses despite correct structure.
Use INCOMPLETE when tests were not run or produced no results.
"""


# ---------------------------------------------------------------------------
# M9.3 — Knowledge-first schema repair constants and helpers
# ---------------------------------------------------------------------------

_MAX_SCHEMA_REPAIRS: int = 10
"""Maximum targeted API repair calls per patch iteration (M9.3).

When the local NodeSchemaStore snapshot is missing a node type, one API call is
made (repair-only path). This budget caps the number of such calls per iteration
so a malformed plan cannot drive unbounded network activity. Nodes beyond the
budget are skipped with a warning; their AddNode ops will fail at compile time.
"""


async def _repair_schema_for_ops(
    node_names: "set[str]",
    node_store: "Any | None",
    executor: dict,
    prior_flowise_debug: dict,
    max_repairs: int = _MAX_SCHEMA_REPAIRS,
) -> "tuple[dict[str, dict], list[dict], dict]":
    """Resolve node schemas for AddNode ops — local-first, repair-only API calls.

    Knowledge-first contract (M9.3):
      - Local snapshot HIT  → zero API calls (fast path)
      - Local snapshot MISS → ONE targeted ``get_node`` API call per missing type
      - Budget capped at ``max_repairs`` API calls per invocation; additional
        misses are logged and skipped (AddNode for that type will fail to compile)

    This is the canonical schema-resolution path.  It is called from Phase D of
    ``_make_patch_node_v2`` and can be exercised in isolation by tests.

    Args:
        node_names:        Set of node type names extracted from AddNode ops.
        node_store:        ``NodeSchemaStore`` instance (local snapshot).
                           If ``None`` the legacy API-always path is used.
        executor:          Tool executor dict that can dispatch ``get_node`` calls.
        prior_flowise_debug: Current ``debug["flowise"]`` dict (for merging events).
        max_repairs:       Budget — max API calls this invocation (default 10).

    Returns:
        (schema_cache, repair_events, debug_update)

        schema_cache:    ``{node_type: schema_dict}`` for every resolved node.
        repair_events:   List of repair event dicts (empty when all cache hits).
        debug_update:    Partial ``{"flowise": {...}}`` dict to merge into
                         ``state["debug"]``; empty dict when no repairs occurred.
    """
    schema_cache: dict[str, dict] = {}
    repair_events: list[dict] = []

    async def _api_fetcher(node_type: str) -> dict:
        """Single targeted get_node API call — invoked ONLY on cache miss."""
        _result = await execute_tool("get_node", {"name": node_type}, executor)
        if isinstance(_result, ToolResult) and _result.ok and isinstance(_result.data, dict):
            return _result.data
        return {}

    for node_type in node_names:
        if node_store is not None:
            # Enforce repair budget — count repairs so far
            repairs_so_far = len(repair_events)
            if repairs_so_far >= max_repairs:
                logger.warning(
                    "[repair_schema] Budget exhausted (%d/%d) — skipping '%s'; "
                    "AddNode op for this type will fail at compile time",
                    repairs_so_far, max_repairs, node_type,
                )
                continue

            # Fast path: local snapshot hit → zero API calls
            # Slow path: cache miss → ONE targeted get_node call (repair)
            _schema = await node_store.get_or_repair(
                node_type, _api_fetcher, repair_events_out=repair_events,
            )
        else:
            # Legacy path (no local store) — always call API
            _legacy = await execute_tool("get_node", {"name": node_type}, executor)
            _schema = (
                _legacy.data
                if isinstance(_legacy, ToolResult) and _legacy.ok and isinstance(_legacy.data, dict)
                else None
            )

        if _schema:
            schema_cache[node_type] = _schema
        else:
            logger.warning(
                "[repair_schema] Schema unavailable for '%s' — AddNode will fail", node_type
            )

    # Build debug update for repair events
    debug_update: dict = {}
    if repair_events:
        logger.info("[repair_schema] %d repair event(s) recorded", len(repair_events))
        existing_events = prior_flowise_debug.get("knowledge_repair_events", [])
        debug_update = {
            "flowise": {
                **prior_flowise_debug,
                "knowledge_repair_events": existing_events + repair_events,
            }
        }

    return schema_cache, repair_events, debug_update


async def _fire_webhook(url: str, payload: dict) -> None:
    """POST an interrupt payload to a developer-supplied webhook URL (DD-037).

    Retries up to 3 times with exponential back-off (1s, 2s, 4s).
    Failures are logged but never propagate — the webhook is best-effort.
    """
    import httpx
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.post(url, json=payload)
                r.raise_for_status()
            logger.debug("Webhook delivered to %s", url)
            return
        except Exception as exc:
            wait = 2 ** attempt
            logger.warning(
                "Webhook attempt %d failed (%s); retrying in %ds", attempt + 1, exc, wait
            )
            await asyncio.sleep(wait)
    logger.error("Webhook delivery failed after 3 attempts: %s", url)


_CLARIFY_SYSTEM = """
You are a requirements analyst. Read the developer's requirement and decide if it is
specific enough to build a correct Flowise chatflow without further information.

Score ambiguity 0–10 (0 = fully specified, 10 = completely unclear).
If score >= 5, output exactly 2–3 YES/NO or short-answer questions that would resolve
the ambiguity. Focus on: LLM provider, memory requirements, new vs modify, RAG needed.
If score < 5, output: CLEAR

Format:
SCORE: N
QUESTIONS:
1. ...
2. ...
"""


def _make_clarify_node(engine: ReasoningEngine):
    async def clarify(state: AgentState) -> dict:
        """Pre-discover: ask clarifying questions if requirement is ambiguous (DD-033).

        Scores requirement ambiguity 0-10. If score >= 5, issues a HITL interrupt
        with 2-3 targeted questions. Bypassed when SKIP_CLARIFICATION=true.
        """
        import os
        if os.getenv("SKIP_CLARIFICATION", "").lower() in ("true", "1", "yes"):
            return {"clarification": None}

        response = await engine.complete(
            messages=[Message(role="user", content=state["requirement"])],
            system=_CLARIFY_SYSTEM,
            tools=None,
        )
        text = (response.content or "").strip()

        if text.upper().startswith("SCORE"):
            score_line = text.splitlines()[0]
            try:
                score = int(score_line.split(":")[1].strip())
            except (IndexError, ValueError):
                score = 0
        else:
            score = 0

        if score >= 5:
            interrupt_payload = {
                "type": "clarification",
                "prompt": text,
                "requirement": state["requirement"],
                "iteration": 0,
            }
            if state.get("webhook_url"):
                asyncio.create_task(_fire_webhook(state["webhook_url"], interrupt_payload))
            developer_response: str = interrupt(interrupt_payload)
            return {
                "clarification": developer_response,
                "total_input_tokens": response.input_tokens,
                "total_output_tokens": response.output_tokens,
            }

        return {
            "clarification": None,
            "total_input_tokens": response.input_tokens,
            "total_output_tokens": response.output_tokens,
        }

    return clarify


def _build_system_prompt(base: str, domains: list[DomainTools], phase: str) -> str:
    """Combine the base system prompt with all domain-specific context additions."""
    extra = merge_context(domains, phase)
    if extra:
        return f"{base.rstrip()}\n\n{extra}"
    return base.rstrip()


# ---------------------------------------------------------------------------
# Inner ReAct loop
# ---------------------------------------------------------------------------


async def _react(
    engine: ReasoningEngine,
    messages: list[Message],
    system: str,
    tools: list[ToolDef],
    executor: dict[str, Any],
    max_rounds: int = 8,
) -> tuple[str, list[Message], int, int]:
    """Run the LLM in a ReAct loop until it produces a text response.

    Each round:
      1. Call the LLM with current messages + any tool results so far.
      2. If the LLM requests tool calls → execute them, append results, loop.
      3. If the LLM returns text (no tool calls) → done.

    Args:
        engine:     The reasoning engine (LLM provider).
        messages:   Full conversation history to pass to the LLM.
        system:     System prompt for this phase.
        tools:      Available tools (empty list = no tool calling).
        executor:   tool_name → async callable mapping.
        max_rounds: Safety cap to prevent runaway loops.

    Returns:
        (final_text, new_messages_produced_in_this_loop, input_tokens, output_tokens)
        new_messages includes assistant turns and tool result turns.
        input_tokens/output_tokens are the cumulative totals across all rounds.
    """
    new_msgs: list[Message] = []
    total_in = 0
    total_out = 0

    for round_num in range(max_rounds):
        response = await engine.complete(
            messages=messages + new_msgs,
            system=system,
            tools=tools or None,
        )
        total_in += response.input_tokens
        total_out += response.output_tokens

        if not response.has_tool_calls:
            # LLM gave a text answer — loop complete
            final_text = response.content or ""
            new_msgs.append(Message(role="assistant", content=final_text))
            logger.debug("ReAct complete after %d round(s): in=%d out=%d", round_num + 1, total_in, total_out)
            return final_text, new_msgs, total_in, total_out

        # LLM requested tool calls
        logger.debug("ReAct round %d: %d tool call(s)", round_num + 1, len(response.tool_calls))
        new_msgs.append(Message(
            role="assistant",
            content=response.content,       # may be None or partial text
            tool_calls=response.tool_calls,
        ))

        for tc in response.tool_calls:
            # execute_tool now returns a ToolResult envelope (DD-048).
            # result_to_str(ToolResult) returns .summary — the compact, prompt-safe
            # string that enters LLM context. Raw data (.data) is NOT stored here;
            # the discover node routes it to state['debug'] when capabilities are active.
            tool_result = await execute_tool(tc.name, tc.arguments, executor)
            new_msgs.append(Message(
                role="tool_result",
                content=result_to_str(tool_result),
                tool_call_id=tc.id,
                tool_name=tc.name,
            ))

    # Safety: max rounds reached without a text response
    timeout_msg = (
        "[max_rounds reached — the agent did not produce a final text response. "
        "This may indicate a loop in tool calls. Review the tool results above.]"
    )
    new_msgs.append(Message(role="assistant", content=timeout_msg))
    logger.warning("ReAct loop hit max_rounds (%d)", max_rounds)
    return timeout_msg, new_msgs, total_in, total_out


# ---------------------------------------------------------------------------
# Utility: extract chatflow_id from recent tool results
# ---------------------------------------------------------------------------


_CHATFLOW_UUID_RE = re.compile(
    r'CHATFLOW[_\s-]*ID[:\s]+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
    re.IGNORECASE,
)

# Matches a bare UUID (used to detect whether a credential_id is a real Flowise
# UUID or a placeholder/type name written by the LLM, e.g. "openAIApi").
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

# Matches the ToolResult summary format produced by _wrap_result() for chatflow results:
# "Chatflow 'Support Bot' (id=abc12345-1234-1234-1234-abcdef012345)."
_CHATFLOW_SUMMARY_UUID_RE = re.compile(
    r'\(id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\)',
    re.IGNORECASE,
)


def _extract_chatflow_id(messages: list[Message]) -> str | None:
    """Scan recent messages for a chatflow id using three fallback passes.

    Pass 1a (highest confidence): tool_result msg.content is a legacy JSON dict with "id" key.
               Catches create_chatflow / get_chatflow responses in legacy (non-ToolResult) format.
    Pass 1b: tool_result msg.content is a ToolResult summary like "Chatflow 'Name' (id=UUID).".
               Catches create_chatflow / get_chatflow responses in the new ToolResult format
               where msg.content holds result.summary (DD-048).
    Pass 2: assistant tool_call arguments containing "chatflow_id".
               Catches update_chatflow calls where the LLM already knew the id.
    Pass 3: LLM final text containing "CHATFLOW_ID: <uuid>".
               Catches the explicit confirmation line the patch prompt requires.

    The reverse scan means the most recent matching message wins.
    """
    # Pass 1a: tool result content is a JSON dict with "id" field (legacy raw result format)
    for msg in reversed(messages):
        if msg.role == "tool_result" and msg.content:
            try:
                data = json.loads(msg.content)
                if isinstance(data, dict) and "id" in data:
                    return str(data["id"])
            except (json.JSONDecodeError, TypeError):
                pass

    # Pass 1b: tool result content is a ToolResult summary with "(id=UUID)" (DD-048 format)
    for msg in reversed(messages):
        if msg.role == "tool_result" and msg.content:
            m = _CHATFLOW_SUMMARY_UUID_RE.search(msg.content)
            if m:
                return m.group(1)

    # Pass 2: chatflow_id passed as argument to update_chatflow / snapshot_chatflow
    for msg in reversed(messages):
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                cid = tc.arguments.get("chatflow_id")
                if cid and isinstance(cid, str):
                    return cid

    # Pass 3: LLM mentioned "CHATFLOW_ID: <uuid>" in its final text response
    for msg in reversed(messages):
        if msg.role == "assistant" and msg.content:
            m = _CHATFLOW_UUID_RE.search(msg.content)
            if m:
                return m.group(1)

    return None


# ---------------------------------------------------------------------------
# Node factories
# Each node is a closure over the engine + domains list.
# ---------------------------------------------------------------------------


def _make_discover_node(
    engine: ReasoningEngine,
    domains: list[DomainTools],
    capabilities: "list[DomainCapability] | None" = None,
):
    """Discover node factory.

    Two execution paths depending on whether capabilities are provided:

    Legacy path (capabilities=None — default, zero regression risk):
      Runs the existing merge_tools() + _react() loop directly.
      Stores discovery_summary and domain_context. No artifacts/facts/debug writes.
      Identical behavior to the pre-refactor codebase.

    Capability path (capabilities=[...]):
      Runs DomainCapability.discover() for each capability in parallel.
      Populates all state fields: discovery_summary, domain_context, artifacts,
      facts, debug. Raw tool outputs go to debug (NOT messages). Compact
      summaries are what went into LLM context (enforced by ToolResult.summary).

    The two paths are fully independent. Activating capabilities does not
    affect plan/patch/test/converge behavior.

    See DD-046 (DomainCapability as primary abstraction boundary).
    """
    # --- Legacy path setup (pre-computed, captured in closure) ---
    tool_defs, executor = merge_tools(domains, "discover")
    system = _build_system_prompt(_DISCOVER_BASE, domains, "discover")

    async def discover_legacy(state: AgentState) -> dict:
        """Phase 1 (legacy path): Read-only information gathering using merged DomainTools."""
        iteration = state.get("iteration", 0)
        logger.info("[DISCOVER] iteration=%d (legacy DomainTools path)", iteration)

        user_content = f"My requirement:\n{state['requirement']}"
        if state.get("clarification"):
            user_content += f"\n\nClarifications provided:\n{state['clarification']}"
        if state.get("developer_feedback"):
            user_content += f"\n\nDeveloper feedback from previous iteration:\n{state['developer_feedback']}"

        user_msg = Message(role="user", content=user_content)
        # Discover runs with only the current user message — tool call responses
        # from list_nodes / list_marketplace_templates can be 500k+ tokens and must
        # not accumulate in state["messages"] for downstream phases to inherit.
        # max_rounds=20: a 13-node chatflow requires get_node for each type plus
        # list_chatflows / list_credentials / list_marketplace_templates = 10+ calls.
        summary, new_msgs, in_tok, out_tok = await _react(engine, [user_msg], system, tool_defs, executor, max_rounds=20)

        # Build a per-domain context summary (stored for extensibility / debugging)
        domain_context = dict(state.get("domain_context") or {})
        domain_context["flowise"] = summary  # update with latest discovery

        # Parse the CREDENTIALS_STATUS block that the skill instructs the LLM to emit.
        # If the summary ends with "CREDENTIALS_STATUS: MISSING\nMISSING_TYPES: ..."
        # we extract the comma-separated credential type list so check_credentials can
        # issue a HITL interrupt before the plan is written.
        # Only set on the first discover iteration (iteration == 0) to avoid re-checking.
        credentials_missing: list[str] | None = state.get("credentials_missing")
        if state.get("iteration", 0) == 0:
            m = re.search(
                r"CREDENTIALS_STATUS:\s*MISSING\s*\nMISSING_TYPES:\s*(.+)",
                summary,
            )
            credentials_missing = [t.strip() for t in m.group(1).split(",")] if m else []

        return {
            # Do NOT persist discover's raw tool call messages to state["messages"].
            # Downstream phases read discovery_summary (the distilled text) instead.
            "messages": [],
            "discovery_summary": summary,
            "domain_context": domain_context,
            "credentials_missing": credentials_missing,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
        }

    async def discover_capability(state: AgentState) -> dict:
        """Phase 1 (capability path): Discovery via DomainCapability.discover() per domain.

        Runs all capabilities in parallel. Results are distributed to:
          state['discovery_summary']   ← flowise domain summary
          state['domain_context']      ← all domains' summaries
          state['facts'][domain]       ← structured facts per domain
          state['artifacts'][domain]   ← produced references per domain
          state['debug'][domain]       ← raw tool summaries per domain (NOT LLM context)
          state['credentials_missing'] ← parsed from flowise summary (iteration 0 only)
        """
        iteration = state.get("iteration", 0)
        logger.info("[DISCOVER] iteration=%d (DomainCapability path, %d capabilities)", iteration, len(capabilities))  # type: ignore[arg-type]

        context = {
            "requirement": state["requirement"],
            "clarification": state.get("clarification"),
            "developer_feedback": state.get("developer_feedback"),
            "iteration": iteration,
            "domain_context": state.get("domain_context") or {},
        }

        # Run discover for all capabilities in parallel (M7.4: timed via MetricsCollector)
        domain_context = dict(state.get("domain_context") or {})
        new_facts: dict[str, Any] = {}
        new_artifacts: dict[str, Any] = {}
        new_debug: dict[str, Any] = {}
        flowise_summary: str | None = None
        credentials_missing: list[str] | None = state.get("credentials_missing")
        total_in_tok = 0
        total_out_tok = 0

        async with MetricsCollector("discover") as m_disc:
            results = await asyncio.gather(
                *[cap.discover(context) for cap in (capabilities or [])],
                return_exceptions=True,
            )

            for cap, result in zip(capabilities or [], results):
                if isinstance(result, Exception):
                    logger.warning("[DISCOVER] %s.discover() raised: %s", cap.name, result)
                    domain_context[cap.name] = f"ERROR during {cap.name} discovery: {result}"
                    continue

                domain_context[cap.name] = result.summary

                if cap.name == "flowise":
                    flowise_summary = result.summary
                    # Parse credentials from flowise summary (only on first iteration)
                    if iteration == 0:
                        m = re.search(
                            r"CREDENTIALS_STATUS:\s*MISSING\s*\nMISSING_TYPES:\s*(.+)",
                            result.summary,
                        )
                        credentials_missing = [t.strip() for t in m.group(1).split(",")] if m else []

                # Distribute structured outputs to their state fields
                if result.facts:
                    new_facts[cap.name] = result.facts
                if result.artifacts:
                    new_artifacts[cap.name] = result.artifacts
                if result.debug:
                    new_debug[cap.name] = result.debug

            m_disc.tool_call_count = sum(
                1 for r in results if not isinstance(r, Exception)
            )
            m_disc.input_tokens = total_in_tok
            m_disc.output_tokens = total_out_tok

        # M7.4: merge discover phase metrics into new_debug["flowise"]
        _disc_existing = new_debug.get("flowise") or {}
        _disc_prior_phases = (
            (state.get("debug") or {}).get("flowise", {}).get("phase_metrics", [])
        )
        new_debug["flowise"] = {
            **_disc_existing,
            "phase_metrics": _disc_prior_phases + [m_disc.to_dict()],
        }

        return {
            "messages": [],  # tool call msgs NOT in state.messages (raw → debug only)
            "discovery_summary": flowise_summary or domain_context.get("flowise"),
            "domain_context": domain_context,
            "credentials_missing": credentials_missing,
            "facts": new_facts,
            "artifacts": new_artifacts,
            "debug": new_debug,
            "total_input_tokens": total_in_tok,
            "total_output_tokens": total_out_tok,
        }

    # Return the appropriate function based on whether capabilities were provided
    if capabilities:
        return discover_capability
    return discover_legacy


def _make_check_credentials_node():
    async def check_credentials(state: AgentState) -> dict:
        """HITL checkpoint: prompt developer if required credentials are missing.

        Runs between discover and plan. If credentials_missing is non-empty,
        issues a credential_check interrupt so the developer can create the
        missing credentials in Flowise and reply with the credential ID(s)
        before the plan is written. If all credentials are present (or
        credentials_missing is None/[]), passes through silently.

        credential_check is only triggered on iteration 0 (the initial discover).
        ITERATE loops route directly back to plan, skipping this node.
        """
        missing = state.get("credentials_missing") or []
        if missing:
            missing_list = "\n".join(f"  - {c}" for c in missing)
            logger.info("[CHECK_CREDENTIALS] missing=%r — issuing credential_check interrupt", missing)
            interrupt_payload = {
                "type": "credential_check",
                "prompt": (
                    f"The following credential types are required but were not found in Flowise:\n"
                    f"{missing_list}\n\n"
                    "Please create them in Flowise (Settings → Credentials → Add New), "
                    "then reply with the credential ID(s) to use.\n"
                    "Example reply: 'openAIApi credential ID is 513db410-c4c3-4818-a716-6f386aba8a82'\n"
                    "Or reply 'skip' to proceed without credentials "
                    "(you can add them manually before testing)."
                ),
                "missing_credentials": missing,
            }
            if state.get("webhook_url"):
                asyncio.create_task(_fire_webhook(state["webhook_url"], interrupt_payload))
            response: str = interrupt(interrupt_payload)
            # Store the developer's reply as feedback for the plan node.
            return {"developer_feedback": response}

        logger.info("[CHECK_CREDENTIALS] all credentials present — passing through")
        return {}

    return check_credentials


_ERROR_PLAYBOOK: dict[str, str] = {
    "CREDENTIAL": (
        "RECOVERY: The failure is a missing or mis-bound credential. "
        "In the next Patch: verify the credential ID is set at BOTH data.credential "
        "AND data.inputs.credential for every node that requires an API key. "
        "Re-check list_credentials before patching."
    ),
    "STRUCTURE": (
        "RECOVERY: The failure is a structural flowData issue. "
        "In the next Patch: call validate_flow_data and fix ALL reported errors before "
        "calling update_chatflow. Ensure every node has inputAnchors, inputParams, "
        "outputAnchors, and outputs. Ensure minimum flow_data is {'nodes':[],'edges':[]}."
    ),
    "LOGIC": (
        "RECOVERY: The failure is a logic error (wrong prompt, wrong model config, "
        "incorrect chain/agent type). Review the test failure message carefully "
        "and change only the specific node/param that caused it."
    ),
    "INCOMPLETE": (
        "RECOVERY: The chatflow is incomplete or untestable. "
        "Verify the chatflow was deployed (deployed:true) and the correct chatflow_id "
        "was used in predictions. Re-run list_chatflows if unsure."
    ),
}


def _make_plan_node(
    engine: ReasoningEngine,
    domains: list[DomainTools],
    template_store: TemplateStore | None = None,
    pattern_store=None,
):
    system = _build_system_prompt(_PLAN_BASE, domains, "discover")  # plan uses discover context

    # Stop-words filtered out when extracting keywords for template matching.
    _STOP = frozenset({
        "with", "that", "this", "from", "have", "will", "what", "when", "where",
        "which", "about", "into", "also", "some", "over", "then", "than", "your",
        "their", "would", "could", "should", "using", "used", "uses", "make",
        "need", "want", "help", "like", "know", "just", "more", "create", "build",
        "such", "each", "very", "much", "many", "need", "data",
    })

    async def plan(state: AgentState) -> dict:
        """Phase 2: Create a structured plan. No tool calls."""
        iteration = state.get("iteration", 0)
        logger.info("[PLAN] iteration=%d", iteration)

        if state.get("developer_feedback"):
            user_content = (
                f"The developer reviewed the previous plan and gave this feedback:\n"
                f"{state['developer_feedback']}\n\n"
                "Please revise the plan accordingly."
            )
        else:
            user_content = (
                "Based on the discovery above, create the structured plan following all required sections."
            )

        user_msg = Message(role="user", content=user_content)

        # Extract meaningful keywords from the requirement.
        # Used for both template matching and pattern library lookup (M7.3).
        req_keywords = list(dict.fromkeys(
            w for w in re.findall(r"[a-zA-Z]{4,}", state["requirement"])
            if w.lower() not in _STOP
        ))[:15]

        # Narrow template hint (Milestone 2 — knowledge layer).
        # Query the local TemplateStore, inject a note when relevant matches exist.
        # NEVER injects more than 3 entries; description is capped at 120 chars.
        template_hint = ""
        if template_store is not None and template_store.template_count > 0:
            matches = template_store.find(req_keywords, limit=3)
            if matches:
                lines = [
                    "Possibly relevant marketplace templates "
                    "(mention in plan if applicable; developer can import manually):"
                ]
                for m in matches:
                    name = m.get("templateName") or ""
                    desc = (m.get("description") or "")[:120]
                    lines.append(f'  - "{name}": {desc}')
                template_hint = "\n".join(lines)
                logger.debug(
                    "[PLAN] Template hint injected: %d match(es) for requirement",
                    len(matches),
                )

        # M7.3 (DD-068): Pattern base graph seeding.
        # On the first iteration of a CREATE flow, search the pattern library
        # for a matching prior pattern and seed artifacts["flowise"]["base_graph_ir"]
        # so that patch v2 starts from a populated base rather than an empty GraphIR.
        # Only active when pattern_store is provided.
        _pattern_base_ir: dict | None = None
        if pattern_store is not None and iteration == 0 and not state.get("chatflow_id"):
            _kw_str = " ".join(req_keywords) or state.get("requirement", "")[:200]
            try:
                _pat_matches = await pattern_store.search_patterns_filtered(
                    _kw_str, domain="flowise", limit=1
                )
                if _pat_matches:
                    _pat = _pat_matches[0]
                    _base_ir = await pattern_store.apply_as_base_graph(_pat["id"])
                    if _base_ir.nodes:
                        _pattern_base_ir = _base_ir.to_flow_data()
                        logger.info(
                            "[PLAN] Pattern seed: id=%d name=%r nodes=%d",
                            _pat["id"], _pat.get("name", "?"), len(_base_ir.nodes),
                        )
            except Exception as _exc:
                logger.warning("[PLAN] Pattern search failed (non-fatal): %s", _exc)

        # Build a compact context from structured state fields — never use the raw
        # state["messages"] which may contain huge tool call blobs from discover.
        base_content = (
            f"Requirement:\n{state['requirement']}\n\n"
            f"Discovery summary:\n{state.get('discovery_summary') or '(none)'}"
        )
        if template_hint:
            base_content += f"\n\n{template_hint}"

        ctx: list[Message] = [
            Message(role="user", content=base_content),
        ]
        if state.get("plan"):
            # Revision loop: include previous plan so LLM can see what to revise.
            ctx.append(Message(role="assistant", content=state["plan"]))

        # Inject structured converge verdict if this is an ITERATE cycle.
        # The evaluator (converge) provides the optimizer (plan) with specific,
        # categorized fix instructions — closing the evaluator-optimizer feedback loop.
        cv = state.get("converge_verdict")
        if cv and cv.get("verdict") == "ITERATE":
            fixes_text = "\n".join(f"Required fix: {f}" for f in cv.get("fixes", []))
            ctx.append(Message(
                role="user",
                content=(
                    f"CONVERGE VERDICT [{cv.get('category', 'INCOMPLETE')}]: {cv.get('reason', '')}\n"
                    + (fixes_text if fixes_text else "")
                ).strip(),
            ))
            # Inject error recovery playbook hint (DD-038).
            # Maps failure category → targeted repair instructions so the plan node
            # gets concrete, pre-validated fix guidance rather than reasoning from scratch.
            category = cv.get("category", "INCOMPLETE")
            playbook_hint = _ERROR_PLAYBOOK.get(category, "")
            if playbook_hint:
                ctx.append(Message(role="user", content=playbook_hint))

        response = await engine.complete(
            messages=ctx + [user_msg],
            system=system,
            tools=None,  # No tool calls in the plan phase
        )
        plan_text = response.content or ""
        assistant_msg = Message(role="assistant", content=plan_text)

        # M7.2 (DD-067): parse structured plan contract from the LLM output and
        # store it in facts["flowise"]["plan_contract"].  Merges with existing
        # flowise facts so we never clobber other keys (e.g. schema_fingerprint).
        contract = _parse_plan_contract(plan_text, state.get("chatflow_id"))
        existing_flowise_facts: dict = (state.get("facts") or {}).get("flowise") or {}
        logger.debug(
            "[PLAN] PlanContract parsed: action=%s domains=%s criteria=%d",
            contract.action,
            contract.domain_targets,
            len(contract.success_criteria),
        )

        ret: dict[str, Any] = {
            "messages": [user_msg, assistant_msg],
            "plan": plan_text,
            "developer_feedback": None,  # consumed; clear it
            "total_input_tokens": response.input_tokens,
            "total_output_tokens": response.output_tokens,
            "facts": {"flowise": {**existing_flowise_facts, "plan_contract": asdict(contract)}},
        }
        # M7.3: attach pattern-seeded base graph to artifacts if one was found
        if _pattern_base_ir is not None:
            existing_flowise_artifacts: dict = (state.get("artifacts") or {}).get("flowise") or {}
            ret["artifacts"] = {
                "flowise": {**existing_flowise_artifacts, "base_graph_ir": _pattern_base_ir}
            }
        return ret

    return plan


def _parse_plan_options(plan_text: str) -> list[str] | None:
    """Extract selectable approach labels from an ## APPROACHES section in the plan.

    Returns a list of label strings (e.g. ["Update existing chatflow", "Fresh rebuild"])
    or None if the section is absent or empty.
    """
    if not plan_text:
        return None
    match = re.search(
        r"##\s*APPROACHES\s*\n((?:\s*\d+\..+\n?)+)",
        plan_text,
        re.IGNORECASE,
    )
    if not match:
        return None
    options = []
    for line in match.group(1).split("\n"):
        m = re.match(r"\s*\d+\.\s*(.+)", line)
        if m:
            options.append(m.group(1).strip())
    return options or None


def _make_human_plan_approval_node():
    async def human_plan_approval(state: AgentState) -> dict:
        """INTERRUPT: surface plan to developer and wait for approval or feedback.

        The graph pauses here. The calling application receives the interrupt
        value, presents it to the developer, and resumes with their response
        via graph.invoke(Command(resume=<response>), config=...).

        Resume values:
          "approved" (or "yes", "ok", "looks good") → proceed to patch
          Any other string → treat as feedback, loop back to plan
        """
        logger.info("[HUMAN PLAN APPROVAL] waiting for developer input")

        options = _parse_plan_options(state["plan"])
        interrupt_payload = {
            "type": "plan_approval",
            "plan": state["plan"],
            "iteration": state.get("iteration", 0),
            "options": options,
            "prompt": (
                "Review the plan above.\n"
                "Reply 'approved' to proceed with implementation, "
                "or describe what needs to change."
            ),
        }
        if state.get("webhook_url"):
            asyncio.create_task(_fire_webhook(state["webhook_url"], interrupt_payload))
        developer_response: str = interrupt(interrupt_payload)

        approved = developer_response.strip().lower() in (
            "approved", "approve", "yes", "y", "ok", "looks good", "lgtm", "proceed"
        )

        logger.info("[HUMAN PLAN APPROVAL] approved=%s", approved)

        if approved:
            return {"developer_feedback": None}
        else:
            return {"developer_feedback": developer_response, "plan": None}

    return human_plan_approval


def _make_patch_node(engine: ReasoningEngine, domains: list[DomainTools]):
    tool_defs, executor = merge_tools(domains, "patch")
    system = _build_system_prompt(_PATCH_BASE, domains, "patch")

    async def patch(state: AgentState) -> dict:
        """Phase 3: Execute the approved plan with minimal changes."""
        iteration = state.get("iteration", 0)
        logger.info("[PATCH] iteration=%d", iteration)

        # Build context note: tell the LLM about the existing chatflow (if any)
        # and the developer's selected approach (if provided at plan_approval).
        # Without this, the LLM re-reads the original plan ("CREATE…") and blindly
        # calls create_chatflow on every iteration — creating duplicate chatflows.
        chatflow_id = state.get("chatflow_id")
        developer_feedback = state.get("developer_feedback") or ""

        existing_note = ""
        if chatflow_id:
            existing_note = (
                f"\n\nIMPORTANT: Chatflow '{chatflow_id}' already exists for this session. "
                "Use `update_chatflow` to modify it. Do NOT call `create_chatflow` — "
                "that would create a duplicate."
            )
        if developer_feedback:
            existing_note += f"\n\nDeveloper selected approach: {developer_feedback}"

        user_msg = Message(
            role="user",
            content=(
                f"Approved plan:\n{state['plan']}\n\n"
                "Execute the minimal change now. "
                "Read before write. Print the Change Summary before calling update_chatflow."
            ),
        )

        # Compact context: discovery summary + approved plan. Patch's own tool calls
        # (get_chatflow, update_chatflow) will be appended by _react internally.
        ctx: list[Message] = [
            Message(
                role="user",
                content=(
                    f"Requirement:\n{state['requirement']}\n\n"
                    f"Discovery summary:\n{state.get('discovery_summary') or '(none)'}"
                    f"{existing_note}"
                ),
            ),
            Message(role="assistant", content=f"Approved plan:\n{state.get('plan') or ''}"),
        ]
        # max_rounds=15: patch may need list_chatflows + validate_flow_data +
        # create_chatflow + verify round + final text = 4–5 rounds normally,
        # but complex 13-node chatflows may require extra validation loops.
        _, new_msgs, in_tok, out_tok = await _react(
            engine,
            ctx + [user_msg],
            system,
            tool_defs,
            executor,
            max_rounds=15,
        )

        # Try to pick up the chatflow_id from tool results (e.g. after create_chatflow)
        chatflow_id = state.get("chatflow_id") or _extract_chatflow_id(new_msgs)
        logger.info(
            "[PATCH] chatflow_id=%s (from_state=%s, from_messages=%s)",
            chatflow_id,
            state.get("chatflow_id"),
            _extract_chatflow_id(new_msgs),
        )

        return {
            "messages": [user_msg] + new_msgs,
            "chatflow_id": chatflow_id,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
        }

    return patch


# ---------------------------------------------------------------------------
# Patch node v2 — deterministic IR compiler path (DD-051, DD-052)
# ---------------------------------------------------------------------------


_CHATFLOW_NAME_RE = re.compile(
    r'CREATE\s+["\']?([^"\'\\n]+)["\']?',
    re.IGNORECASE,
)


def _extract_chatflow_name_from_plan(plan: str) -> str:
    """Try to extract a chatflow name from the ACTION section of a plan.

    Looks for a line like 'CREATE a new chatflow named "Support Bot"' or
    '- CREATE "Customer Service Flow"'. Falls back to 'New Chatflow'.
    """
    for line in plan.splitlines():
        if "create" in line.lower():
            m = re.search(r'"([^"]+)"', line)
            if not m:
                m = re.search(r"'([^']+)'", line)
            if m:
                return m.group(1).strip()
    return "New Chatflow"


def _make_patch_node_v2(
    engine: ReasoningEngine,
    domains: list[DomainTools],
    capabilities: "list[DomainCapability]",
):
    """Patch node Milestone 2: LLM emits Patch IR ops, compiler builds flowData.

    Workflow per iteration:
      Phase A — Read base graph from Flowise (get_chatflow) or start empty
      Phase B — Single LLM call: outputs Patch IR JSON ops list (no tool loop)
      Phase C — Parse + structural IR validation (no dangling node refs)
      Phase D — Fetch node schemas for all AddNode ops (get_node per type)
      Phase E — Deterministic compile: ops + schemas → flowData + payload_hash
      Phase F — Structural validation: _validate_flow_data (hard gate)
      Phase G — WriteGuard: authorize exact hash, write with guarded executor

    Backwards-compatible: only used when build_graph(capabilities=[...]) is set.
    The original _make_patch_node() still handles the capabilities=None path.

    See DD-051 (Patch IR schema), DD-052 (write guard).
    """
    system = _build_system_prompt(_PATCH_IR_SYSTEM, domains, "patch")
    _, patch_executor = merge_tools(domains, "patch")

    # Find the Flowise capability for schema fetching
    flowise_cap: "DomainCapability | None" = next(
        (cap for cap in capabilities if cap.name == "flowise"), None
    )

    async def patch(state: AgentState) -> dict:
        iteration = state.get("iteration", 0)
        logger.info("[PATCH v2] iteration=%d", iteration)

        plan = state.get("plan") or ""
        discovery_summary = state.get("discovery_summary") or "(none)"
        chatflow_id = state.get("chatflow_id")
        requirement = state.get("requirement", "")
        in_tok = 0
        out_tok = 0
        _v2_phase_metrics: list[dict] = []   # M7.4: phase timing collected by phases B + D

        # If the plan explicitly requests a CREATE (new chatflow) but a chatflow_id
        # already exists from a prior iteration, honour the plan's intent by treating
        # this patch as a fresh creation.  Detection: "**CREATE**" in the ACTION
        # section of the plan text without a matching "**UPDATE**".
        if (
            chatflow_id is not None
            and "**CREATE**" in plan
            and "**UPDATE**" not in plan
        ):
            logger.info(
                "[PATCH v2] Plan requests CREATE; ignoring existing chatflow_id=%s "
                "— will create a new chatflow this iteration.",
                chatflow_id,
            )
            chatflow_id = None

        # ---- Phase A: Read base graph ----------------------------------------
        base_graph = GraphIR()
        _using_pattern_seed = False
        discover_executor = (
            flowise_cap.tools.executor("discover") if flowise_cap else patch_executor
        )
        if chatflow_id:
            cf_result = await execute_tool(
                "get_chatflow", {"chatflow_id": chatflow_id}, discover_executor
            )
            if cf_result.ok and isinstance(cf_result.data, dict):
                fd = cf_result.data.get("flowData") or cf_result.data.get("flow_data")
                if fd:
                    base_graph = GraphIR.from_flow_data(fd)
                    logger.debug(
                        "[PATCH v2] Loaded base graph: %d nodes, %d edges",
                        len(base_graph.nodes), len(base_graph.edges),
                    )
        else:
            # M7.3 (DD-068): No existing chatflow — use pattern-seeded base if present.
            # The plan node populates artifacts["flowise"]["base_graph_ir"] when a
            # matching pattern is found in the library.
            _base_ir_data: dict | None = (
                (state.get("artifacts") or {}).get("flowise", {}).get("base_graph_ir")
            )
            if _base_ir_data:
                _seeded = GraphIR.from_flow_data(_base_ir_data)
                if _seeded.nodes:
                    base_graph = _seeded
                    _using_pattern_seed = True
                    logger.info(
                        "[PATCH v2] Using pattern-seeded base graph: %d nodes, %d edges",
                        len(base_graph.nodes), len(base_graph.edges),
                    )

        # ---- Phase B: LLM generates ops JSON ---------------------------------
        chatflow_summary: str
        if base_graph.nodes:
            node_lines = [
                f"  - {n.id} ({n.node_name}): {n.label}"
                for n in base_graph.nodes
            ]
            chatflow_summary = "Existing nodes:\n" + "\n".join(node_lines)
            if _using_pattern_seed:
                chatflow_summary += (
                    "\nNote: these nodes come from a saved pattern that matched this "
                    "requirement. Do NOT re-add them with AddNode. Instead, only emit "
                    "ops for nodes that are MISSING from this list or params that need "
                    "to be changed (SetParam / BindCredential)."
                )
        else:
            chatflow_summary = "(creating new chatflow)"

        user_msg = Message(
            role="user",
            content=(
                f"Requirement:\n{requirement}\n\n"
                f"Discovery summary:\n{discovery_summary}\n\n"
                f"Approved plan:\n{plan}\n\n"
                f"Current chatflow state:\n{chatflow_summary}\n\n"
                "Output the JSON array of Patch IR operations to implement this plan."
            ),
        )
        # M7.4: time Phase B (LLM ops generation)
        async with MetricsCollector("patch_b") as m_b:
            response = await engine.complete(
                messages=[user_msg],
                system=system,
                tools=None,   # Ops generation — no tool calls
            )
            m_b.input_tokens = response.input_tokens
            m_b.output_tokens = response.output_tokens
        in_tok += response.input_tokens
        out_tok += response.output_tokens
        _v2_phase_metrics.append(m_b.to_dict())
        raw_ops_text = (response.content or "[]").strip()

        new_msgs: list[Message] = [
            user_msg,
            Message(role="assistant", content=raw_ops_text),
        ]

        # ---- Phase C: Parse → resolve credentials → validate IR ops ----------
        ops: list = []
        ir_errors: list[str] = []
        _phase_cred_repair_events: list[dict] = []   # populated on credential repair
        _resolved_credentials: dict[str, str] = {}   # query → credential_id map

        # C.1: Parse
        try:
            ops = ops_from_json(raw_ops_text)
        except Exception as e:
            ir_errors = [f"Failed to parse Patch IR JSON: {e}"]
            logger.warning("[PATCH v2] Ops parse failed: %s", e)

        if not ir_errors:
            # C.2: Credential resolution via CredentialStore (Roadmap 6 M3).
            # Fills in empty credential_ids on BindCredential ops using the local
            # snapshot first; falls back to list_credentials API ONLY on cache miss.
            # This runs BEFORE validate_patch_ops so that auto-resolved credentials
            # pass the "credential_id is required" check in the validator.
            _provider = flowise_cap.knowledge if flowise_cap else None
            _cred_store = _provider.credential_store if _provider else None

            if _cred_store is not None:
                if _cred_store.credential_count > 0:
                    logger.info(
                        "[PATCH v2] Credentials available: %d (from snapshot)",
                        _cred_store.credential_count,
                    )

                async def _cred_api_fetcher() -> list[dict]:
                    """Single list_credentials call — invoked ONLY on cache miss."""
                    _r = await execute_tool(
                        "list_credentials", {}, discover_executor
                    )
                    if (
                        isinstance(_r, ToolResult)
                        and _r.ok
                        and isinstance(_r.data, list)
                    ):
                        return _r.data
                    return []

                for _op in ops:
                    if not isinstance(_op, BindCredential):
                        continue
                    # Resolve when credential_id is empty OR when the LLM put a
                    # type/name (e.g. "openAIApi") instead of a real UUID.
                    # Real UUIDs are 36-char hex strings like xxxxxxxx-xxxx-…
                    _cred_id_is_real_uuid = bool(
                        _op.credential_id and _UUID_RE.match(_op.credential_id)
                    )
                    if _cred_id_is_real_uuid:
                        continue
                    # Use credential_type first; fall back to credential_id as
                    # the type hint when credential_type was left blank.
                    _query = (
                        (_op.credential_type or _op.credential_id or "").strip()
                    )
                    if not _query:
                        continue
                    _resolved = await _cred_store.resolve_or_repair(
                        _query,
                        _cred_api_fetcher,
                        repair_events_out=_phase_cred_repair_events,
                    )
                    if _resolved:
                        _op.credential_id = _resolved
                        _resolved_credentials[_query] = _resolved
                        logger.info(
                            "[PATCH v2] Credential auto-resolved: type=%r → id=%s…",
                            _query,
                            _resolved[:8],
                        )

            # C.3: IR validation (after credential auto-fill)
            ir_errors = validate_patch_ops(ops, base_graph.node_ids())

        if ir_errors:
            logger.warning("[PATCH v2] IR validation errors: %s", ir_errors[:3])
            new_msgs.append(Message(
                role="tool_result",
                content=(
                    "Patch IR validation failed: "
                    + "; ".join(ir_errors[:3])
                ),
            ))
            return {
                "messages": new_msgs,
                "patch_ir": [op_to_dict(op) for op in ops] if ops else None,
                "total_input_tokens": in_tok,
                "total_output_tokens": out_tok,
            }

        # ---- Phase D: Resolve schemas for new node types (local-first) -------
        # M9.3: All schema resolution goes through _repair_schema_for_ops().
        # Fast path: local snapshot HIT  → zero API calls.
        # Slow path: local snapshot MISS → ONE targeted get_node API call (repair).
        # Budget capped at _MAX_SCHEMA_REPAIRS per iteration.
        schema_cache: dict[str, dict] = {}
        _phase_d_repair_events: list[dict] = []
        _phase_d_debug: dict = {}

        new_node_names = {
            op.node_name for op in ops
            if isinstance(op, AddNode) and op.node_name
        }

        # M7.4: time Phase D (schema resolution) — runs even when new_node_names is empty
        async with MetricsCollector("patch_d") as m_d:
            if new_node_names:
                provider = flowise_cap.knowledge if flowise_cap else None
                node_store = provider.node_schemas if provider else None
                _prior_flowise_debug = (state.get("debug") or {}).get("flowise") or {}

                schema_cache, _phase_d_repair_events, _phase_d_debug = (
                    await _repair_schema_for_ops(
                        node_names=new_node_names,
                        node_store=node_store,
                        executor=discover_executor,
                        prior_flowise_debug=_prior_flowise_debug,
                    )
                )

                m_d.cache_hits = len(new_node_names) - len(_phase_d_repair_events)
                m_d.repair_events = len(_phase_d_repair_events)

                # M8.2: record total get_node calls in debug for session telemetry
                if node_store is not None and node_store._call_count > 0:
                    _gn_flowise = _phase_d_debug.get("flowise") or _prior_flowise_debug
                    _prior_calls = _gn_flowise.get("get_node_calls_total", 0)
                    _phase_d_debug["flowise"] = {
                        **_gn_flowise,
                        "get_node_calls_total": _prior_calls + node_store._call_count,
                    }

        _v2_phase_metrics.append(m_d.to_dict())

        # M7.4 (DD-069): Drift detection — compare schema fingerprint against prior iteration.
        # The current fingerprint is always written to facts["flowise"]["schema_fingerprint"]
        # so subsequent iterations can detect snapshot refreshes between iterations.
        _current_schema_fp: str | None = None
        _phase_d_provider = flowise_cap.knowledge if flowise_cap else None
        _phase_d_node_store = _phase_d_provider.node_schemas if _phase_d_provider else None
        if _phase_d_node_store is not None:
            _current_schema_fp = _phase_d_node_store.meta_fingerprint
            _prior_fp: str | None = (
                (state.get("facts") or {}).get("flowise", {}).get("schema_fingerprint")
            )
            if _current_schema_fp and _prior_fp and _current_schema_fp != _prior_fp:
                logger.warning(
                    "[PATCH v2] Schema drift detected: prior=%s… current=%s… policy=%s",
                    _prior_fp[:8], _current_schema_fp[:8], _SCHEMA_DRIFT_POLICY,
                )
                if _SCHEMA_DRIFT_POLICY == "fail":
                    new_msgs.append(Message(
                        role="tool_result",
                        content=(
                            f"Schema drift detected — snapshot fingerprint changed "
                            f"({_prior_fp[:8]}… → {_current_schema_fp[:8]}…). "
                            "Run --nodes refresh before continuing."
                        ),
                    ))
                    return {
                        "messages": new_msgs,
                        "total_input_tokens": in_tok,
                        "total_output_tokens": out_tok,
                    }
                elif _SCHEMA_DRIFT_POLICY == "refresh":
                    logger.info(
                        "[PATCH v2] Drift policy=refresh — recording drift, continuing"
                    )

        # ---- Phase E: Deterministic compile ----------------------------------
        compile_result = compile_patch_ops(base_graph, ops, schema_cache)

        if not compile_result.ok:
            logger.warning("[PATCH v2] Compile errors: %s", compile_result.errors)
            new_msgs.append(Message(
                role="tool_result",
                content=(
                    "Compilation failed: "
                    + "; ".join(compile_result.errors[:3])
                ),
            ))
            return {
                "messages": new_msgs,
                "patch_ir": [op_to_dict(op) for op in ops],
                "total_input_tokens": in_tok,
                "total_output_tokens": out_tok,
            }

        # ---- Phase F: Structural validation (hard gate) ----------------------
        validation_raw = _validate_flow_data(compile_result.flow_data_str)

        if not validation_raw.get("valid"):
            val_errors = validation_raw.get("errors", [])
            logger.warning("[PATCH v2] Flow data invalid after compile: %s", val_errors[:3])
            new_msgs.append(Message(
                role="tool_result",
                content=(
                    "Flow data structurally invalid after compilation: "
                    + "; ".join(val_errors[:3])
                ),
            ))
            return {
                "messages": new_msgs,
                "patch_ir": [op_to_dict(op) for op in ops],
                "total_input_tokens": in_tok,
                "total_output_tokens": out_tok,
            }

        validated_hash = compile_result.payload_hash

        # ---- Phase G: WriteGuard + write -------------------------------------
        guard = WriteGuard()
        guard.authorize(compile_result.flow_data_str)

        # Build a guarded executor that wraps the write tools
        orig_create = patch_executor.get("create_chatflow")
        orig_update = patch_executor.get("update_chatflow")

        async def _guarded_create(**kwargs: Any) -> Any:
            flow_data = kwargs.get("flow_data", "")
            if flow_data:
                guard.check(str(flow_data))
            result = await orig_create(**kwargs) if orig_create else {"error": "create_chatflow not available"}
            if flow_data:
                guard.revoke()
            return result

        async def _guarded_update(**kwargs: Any) -> Any:
            flow_data = kwargs.get("flow_data", "")
            if flow_data:
                guard.check(str(flow_data))
            result = await orig_update(**kwargs) if orig_update else {"error": "update_chatflow not available"}
            if flow_data:
                guard.revoke()
            return result

        guarded_executor = dict(patch_executor)
        guarded_executor["create_chatflow"] = _guarded_create
        guarded_executor["update_chatflow"] = _guarded_update

        write_result: ToolResult
        new_chatflow_id: str | None = chatflow_id

        if chatflow_id:
            # Snapshot before update
            session_id = f"v2-patch-iter{iteration}"
            await execute_tool(
                "snapshot_chatflow",
                {"chatflow_id": chatflow_id, "session_id": session_id},
                guarded_executor,
            )
            # Write update
            write_result = await execute_tool(
                "update_chatflow",
                {"chatflow_id": chatflow_id, "flow_data": compile_result.flow_data_str},
                guarded_executor,
            )
        else:
            # Create new chatflow
            chatflow_name = _extract_chatflow_name_from_plan(plan) or requirement[:50]
            write_result = await execute_tool(
                "create_chatflow",
                {"name": chatflow_name, "flow_data": compile_result.flow_data_str},
                guarded_executor,
            )
            if write_result.ok and write_result.artifacts:
                ids = write_result.artifacts.get("chatflow_ids", [])
                if ids:
                    new_chatflow_id = ids[0]
            elif write_result.ok and isinstance(write_result.data, dict):
                new_chatflow_id = write_result.data.get("id")

        # Capture chatflow_id from write result (handles create case)
        final_chatflow_id = new_chatflow_id or _extract_chatflow_id(new_msgs)

        # Compose a human-readable summary message
        diff_msg = Message(
            role="assistant",
            content=(
                f"Patch IR applied ({len(ops)} op(s)):\n{compile_result.diff_summary}\n\n"
                f"Write result: {result_to_str(write_result)}\n"
                f"CHATFLOW_ID: {final_chatflow_id or '(unknown)'}"
            ),
        )
        new_msgs.append(diff_msg)

        logger.info(
            "[PATCH v2] chatflow_id=%s ok=%s hash=%s...",
            final_chatflow_id, write_result.ok, validated_hash[:12],
        )

        # Roadmap 6 M3: write resolved_credentials to facts["flowise"].
        # Merges with any credentials resolved in earlier patch iterations
        # without overwriting other flowise fact keys (e.g. available_node_types).
        _existing_flowise_facts = (state.get("facts") or {}).get("flowise") or {}
        _phase_c_facts: dict = {}
        if _resolved_credentials:
            _existing_resolved = _existing_flowise_facts.get("resolved_credentials") or {}
            _phase_c_facts = {
                "flowise": {
                    **_existing_flowise_facts,
                    "resolved_credentials": {
                        **_existing_resolved,
                        **_resolved_credentials,
                    },
                }
            }

        # M7.4 (DD-069): persist current schema fingerprint to facts so next iteration
        # can detect drift.  Merged on top of any resolved_credentials fact already set.
        if _current_schema_fp:
            _fc_base = _phase_c_facts.get("flowise") or {**_existing_flowise_facts}
            _phase_c_facts["flowise"] = {**_fc_base, "schema_fingerprint": _current_schema_fp}

        # Combine credential repair events with node-schema repair events in debug
        if _phase_cred_repair_events:
            _existing_cred_events = (
                (state.get("debug") or {})
                .get("flowise", {})
                .get("credential_repair_events", [])
            )
            _cred_debug: dict = {
                "flowise": {
                    **((state.get("debug") or {}).get("flowise") or {}),
                    "credential_repair_events": (
                        _existing_cred_events + _phase_cred_repair_events
                    ),
                }
            }
            # Merge cred_debug into _phase_d_debug (node repair events may also exist)
            if _phase_d_debug:
                _phase_d_debug["flowise"] = {
                    **_phase_d_debug.get("flowise", {}),
                    **_cred_debug["flowise"],
                }
            else:
                _phase_d_debug = _cred_debug

        # M7.4: append patch phase metrics to debug["flowise"]["phase_metrics"]
        if _v2_phase_metrics:
            _pm_flowise = _phase_d_debug.get("flowise") or (
                (state.get("debug") or {}).get("flowise") or {}
            )
            _pm_prior = _pm_flowise.get("phase_metrics", [])
            _phase_d_debug["flowise"] = {
                **_pm_flowise,
                "phase_metrics": list(_pm_prior) + _v2_phase_metrics,
            }

        return {
            "messages": new_msgs,
            "chatflow_id": final_chatflow_id,
            "patch_ir": [op_to_dict(op) for op in ops],
            "validated_payload_hash": validated_hash,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
            # Roadmap 6 M1: node schema repair events
            # Roadmap 6 M3: credential repair events (merged into same debug key)
            # M7.4:         phase_metrics appended to debug["flowise"]
            # _phase_d_debug is {} when no repairs occurred — reducer ignores empty dict
            "debug": _phase_d_debug,
            # Roadmap 6 M3: resolved_credentials written to facts (empty dict = no-op)
            # M7.4:         schema_fingerprint written to facts["flowise"]
            "facts": _phase_c_facts,
        }

    return patch


def _make_test_node(engine: ReasoningEngine, domains: list[DomainTools]):
    _, executor = merge_tools(domains, "test")
    system = _build_system_prompt(_TEST_BASE, domains, "test")

    async def test(state: AgentState) -> dict:
        """Phase 4: Run happy-path and edge-case predictions in parallel (DD-040).

        Predictions are dispatched concurrently via asyncio.gather() — the LLM
        is not used to invoke tools; it is called once at the end to evaluate
        the raw API responses.  This removes one full ReAct round-trip and
        eliminates the risk of the LLM choosing the wrong sessionId format.

        When test_trials > 1 all (happy × trials) + (edge × trials) tasks are
        gathered in a single batch, giving maximum parallelism.
        """
        iteration = state.get("iteration", 0)
        chatflow_id = state.get("chatflow_id")
        trials = state.get("test_trials", 1)
        logger.info("[TEST] iteration=%d chatflow_id=%s trials=%d", iteration, chatflow_id, trials)

        # Guard: cannot run predictions without a valid chatflow ID.
        # Return a clear failure string so converge is forced to ITERATE.
        if not chatflow_id:
            logger.warning("[TEST] chatflow_id is not set — skipping predictions")
            no_id_msg = (
                "Chatflow: (not created)\n\n"
                "TEST: HAPPY PATH\n"
                "  Trial 1: SKIPPED — chatflow_id is None; the patch phase did not create or "
                "capture the chatflow ID. create_chatflow must be called and its returned id "
                "stored before predictions can run.\n\n"
                "TEST: EDGE CASE\n"
                "  Trial 1: SKIPPED — same reason as above.\n\n"
                "RESULT: HAPPY PATH [FAIL] | EDGE CASE [FAIL]"
            )
            return {
                "messages": [],
                "test_results": no_id_msg,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
            }

        async def _run_trial(label: str, question: str, trial_num: int) -> str:
            session_id = f"test-{chatflow_id}-{label}-t{trial_num}"
            result = await execute_tool(
                "create_prediction",
                {
                    "chatflow_id": chatflow_id,
                    "question": question,
                    "override_config": json.dumps({"sessionId": session_id}),
                },
                executor,
            )
            # For test evaluation the LLM needs the full chatbot response, not the
            # compact summary.  Use raw data on success; fall back to summary on error.
            if isinstance(result, ToolResult):
                return result_to_str(result.data) if result.ok else result.summary
            return result_to_str(result)

        happy_question = state["requirement"][:100]
        edge_question = ""  # empty input is the boundary / edge case

        happy_tasks = [_run_trial("happy", happy_question, i + 1) for i in range(trials)]
        edge_tasks  = [_run_trial("edge",  edge_question,  i + 1) for i in range(trials)]

        # Dispatch all predictions in parallel; exceptions are captured, not raised.
        all_results = await asyncio.gather(*happy_tasks, *edge_tasks, return_exceptions=True)
        happy_results: list = list(all_results[:trials])
        edge_results:  list = list(all_results[trials:])

        def _format_trials(label: str, results: list) -> str:
            lines = [f"TEST: {label.upper()} PATH"]
            for i, r in enumerate(results):
                prefix = f"  Trial {i + 1}: "
                if isinstance(r, Exception):
                    lines.append(f"{prefix}ERROR — {r}")
                else:
                    lines.append(f"{prefix}{str(r)[:500]}")
            return "\n".join(lines)

        raw_results = (
            f"Chatflow: {chatflow_id}\n\n"
            f"{_format_trials('happy', happy_results)}\n\n"
            f"{_format_trials('edge', edge_results)}"
        )

        # LLM used only for evaluation — no tool access (tools=None).
        eval_msg = Message(
            role="user",
            content=(
                f"Evaluate these test results for requirement:\n{state['requirement']}\n\n"
                f"{raw_results}\n\n"
                f"Trials per test: {trials}. "
                f"A test PASSES only if ALL {trials} trial(s) pass (pass^{trials} reliability).\n"
                "Report PASS/FAIL for each test with brief reasoning.\n"
                "Final line must be: RESULT: HAPPY PATH [PASS/FAIL] | EDGE CASE [PASS/FAIL]"
            ),
        )
        # M7.4: time the test evaluation LLM call
        async with MetricsCollector("test") as m_test:
            response = await engine.complete(
                messages=[eval_msg],
                system=system,
                tools=None,
            )
            m_test.input_tokens = response.input_tokens
            m_test.output_tokens = response.output_tokens
        eval_text = response.content or ""

        user_msg   = Message(role="user",      content=raw_results)
        asst_msg   = Message(role="assistant", content=eval_text)

        # M7.4: write test phase metrics to debug["flowise"]["phase_metrics"]
        _test_existing_fd = (state.get("debug") or {}).get("flowise") or {}
        _test_prior_phases = _test_existing_fd.get("phase_metrics", [])
        _test_debug = {
            "flowise": {
                **_test_existing_fd,
                "phase_metrics": _test_prior_phases + [m_test.to_dict()],
            }
        }

        return {
            "messages": [user_msg, asst_msg],
            "test_results": eval_text,
            "total_input_tokens":  response.input_tokens,
            "total_output_tokens": response.output_tokens,
            "debug": _test_debug,
        }

    return test


def _parse_converge_verdict(text: str) -> dict:
    """Parse the structured DONE / ITERATE verdict from the converge LLM response.

    Expected formats:
      "DONE"
      "ITERATE\nCategory: CREDENTIAL\nReason: ...\nFix: ...\nFix: ..."

    Returns a dict with keys: verdict, category, reason, fixes.
    """
    if text.strip().upper().startswith("DONE"):
        return {"verdict": "DONE", "category": None, "reason": "All tests passed", "fixes": []}
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    v: dict = {"verdict": "ITERATE", "category": "INCOMPLETE", "reason": "", "fixes": []}
    for line in lines[1:]:
        if line.startswith("Category:"):
            v["category"] = line.split(":", 1)[1].strip()
        elif line.startswith("Reason:"):
            v["reason"] = line.split(":", 1)[1].strip()
        elif line.startswith("Fix:"):
            v["fixes"].append(line.split(":", 1)[1].strip())
    return v



# ---------------------------------------------------------------------------
# FlowiseCapability — DomainCapability implementation for the Flowise domain
#
# Co-located with _react() and _parse_converge_verdict() to avoid circular
# imports. (If placed in agent/domains/flowise.py it would need to import
# _react from graph.py while graph.py imports from that file.)
#
# See DD-046 and roadmap3_architecture_optimization.md — Milestone 1.
# ---------------------------------------------------------------------------


class FlowiseCapability(DomainCapability):
    """DomainCapability wrapping the existing FloviseDomain.

    discover() uses the existing _react() loop — the LLM still controls tool
    selection. The behavioral change vs the legacy discover node:
      - Tool result message content is now result.summary (compact, DD-048)
      - DomainDiscoveryResult.debug holds the tool summary strings per iteration
      - DomainDiscoveryResult.facts is populated from structured ToolResult.facts
        when registry.call() is used directly; otherwise empty dict from _react()
      - DomainDiscoveryResult.summary is set to the LLM's final text output

    evaluate() wraps _parse_converge_verdict() from this module for Verdict output.
    generate_tests() wraps existing test logic (happy=plan[:100], edge="").

    Usage:
        flowise_domain = FloviseDomain(client)
        capability = FlowiseCapability(flowise_domain, engine, system)
        graph = build_graph(engine, domains=[flowise_domain],
                            capabilities=[capability], ...)
    """

    def __init__(
        self,
        flowise_domain: "DomainTools",
        engine: ReasoningEngine,
        system: str,
    ) -> None:
        self._flowise_domain = flowise_domain
        self._engine = engine
        self._system = system
        self._registry = ToolRegistry()
        self._registry.register_domain(flowise_domain)
        self._registry.register_context("flowise", "discover", flowise_domain.discover_context)
        self._registry.register_context("flowise", "patch", flowise_domain.patch_context)
        self._registry.register_context("flowise", "test", flowise_domain.test_context)
        # Roadmap 6 M1: local-first node schema provider (no parallel orchestrator fork)
        self._knowledge = FlowiseKnowledgeProvider()

    @property
    def name(self) -> str:
        return "flowise"

    @property
    def tools(self) -> ToolRegistry:
        return self._registry

    @property
    def domain_tools(self) -> "DomainTools":
        return self._flowise_domain

    @property
    def knowledge(self) -> FlowiseKnowledgeProvider:
        """Local-first platform knowledge provider (Roadmap 6 M1)."""
        return self._knowledge

    async def discover(self, context: dict) -> DomainDiscoveryResult:
        """Run the Flowise discover ReAct loop and return structured results.

        The LLM still controls which tools are called and in what order.
        This method is a thin wrapper that:
          1. Builds the initial user message from context fields.
          2. Calls _react() with namespaced discover tool defs + executor.
          3. Post-processes the produced messages to extract debug summaries.
          4. Returns a DomainDiscoveryResult.

        The discover node in graph.py calls this and distributes the outputs
        to the correct state fields (discovery_summary, domain_context,
        facts, artifacts, debug).
        """
        iteration = context.get("iteration", 0)
        requirement = context.get("requirement", "")
        clarification = context.get("clarification")
        developer_feedback = context.get("developer_feedback")

        user_content = f"My requirement:\n{requirement}"
        if clarification:
            user_content += f"\n\nClarifications provided:\n{clarification}"
        if developer_feedback:
            user_content += f"\n\nDeveloper feedback from previous iteration:\n{developer_feedback}"

        user_msg = Message(role="user", content=user_content)
        tool_defs = self._registry.tool_defs("discover")
        executor = self._registry.executor("discover")

        summary, new_msgs, in_tok, out_tok = await _react(
            self._engine,
            [user_msg],
            self._system,
            tool_defs,
            executor,
            max_rounds=20,
        )

        # Extract debug: tool_result message contents (summaries, not raw data)
        # keyed by tool name within this iteration.
        debug_by_tool: dict[str, Any] = {}
        for msg in new_msgs:
            if msg.role == "tool_result" and msg.tool_name and msg.content:
                debug_by_tool[msg.tool_name] = msg.content

        return DomainDiscoveryResult(
            summary=summary,
            facts={},           # facts populated via registry.call() in future; _react() loop
                                # doesn't expose per-ToolResult data to callers
            artifacts={},
            debug={iteration: debug_by_tool} if debug_by_tool else {},
            tool_results=[],
        )

    async def compile_ops(self, plan: str) -> DomainPatchResult:
        """Call the LLM with the ops-only prompt to produce Patch IR from plan text.

        Uses the _PATCH_IR_SYSTEM prompt so the LLM outputs only a JSON array.
        Returns a DomainPatchResult with the parsed ops list.

        Note: The caller is responsible for schema fetching and compilation.
        _make_patch_node_v2() uses this via direct orchestration.
        """
        user_msg = Message(role="user", content=plan)
        response = await self._engine.complete(
            messages=[user_msg],
            system=_PATCH_IR_SYSTEM,
            tools=None,
        )
        raw_text = (response.content or "[]").strip()
        try:
            ops = ops_from_json(raw_text)
            errors = validate_patch_ops(ops)
            return DomainPatchResult(
                stub=False,
                ops=ops,
                message=(
                    f"{len(ops)} op(s) parsed"
                    + (f"; {len(errors)} IR validation error(s)" if errors else "")
                ),
            )
        except Exception as e:
            return DomainPatchResult(
                stub=False,
                ops=[],
                message=f"Failed to parse Patch IR from LLM output: {e}",
            )

    async def validate(self, artifacts: dict) -> ValidationReport:
        """Run structural validation on a compiled flowData payload.

        artifacts must contain "flow_data_str" (the exact JSON string to validate).
        Returns a ValidationReport with valid, validated_payload_hash, and errors.
        """
        import hashlib as _hashlib

        flow_data_str = artifacts.get("flow_data_str", "")
        if not flow_data_str:
            return ValidationReport(
                stub=False,
                valid=False,
                message="No flow_data_str provided to validate()",
            )

        raw = _validate_flow_data(flow_data_str)

        if raw.get("valid"):
            h = _hashlib.sha256(flow_data_str.encode("utf-8")).hexdigest()
            return ValidationReport(
                stub=False,
                valid=True,
                validated_payload_hash=h,
                node_count=raw.get("node_count", 0),
                edge_count=raw.get("edge_count", 0),
                message=(
                    f"Valid: {raw.get('node_count', 0)} nodes, "
                    f"{raw.get('edge_count', 0)} edges."
                ),
            )
        else:
            errors = raw.get("errors", [])
            return ValidationReport(
                stub=False,
                valid=False,
                errors=errors,
                message=(
                    f"Invalid: {len(errors)} error(s). "
                    f"First: {errors[0] if errors else '(none)'}"
                ),
            )

    async def generate_tests(self, plan: str) -> TestSuite:
        """Return test configuration matching existing test node logic."""
        return TestSuite(
            happy_question=plan[:100] if plan else "",
            edge_question="",
            domain_name="flowise",
        )

    async def evaluate(self, results: dict) -> Verdict:
        """Wrap _parse_converge_verdict() as a typed Verdict."""
        test_results = results.get("test_results", "")
        verdict_dict = _parse_converge_verdict(test_results)
        return Verdict.from_dict(verdict_dict)


def _make_converge_node(
    engine: ReasoningEngine,
    client: "FlowiseClient | None" = None,
    pattern_store=None,
    capabilities: "list[DomainCapability] | None" = None,
):
    async def converge(state: AgentState) -> dict:
        """Phase 5: Evaluate Definition of Done. Returns done=True or loops.

        Produces a structured verdict dict stored in state["converge_verdict"]:
          {"verdict": "DONE"|"ITERATE", "category": ..., "reason": ..., "fixes": [...]}
        The plan node reads converge_verdict to inject specific repair instructions
        into the next planning context (evaluator-optimizer feedback loop).

        When the verdict is DONE and a pattern_store is provided, the agent
        auto-saves the successful chatflow pattern for future reuse (DD-031).
        """
        iteration = state.get("iteration", 0)
        logger.info("[CONVERGE] iteration=%d", iteration)

        user_msg = Message(
            role="user",
            content=(
                f"Test results from iteration {iteration}:\n"
                f"{state.get('test_results', 'No test results recorded.')}\n\n"
                "Evaluate against the Definition of Done. "
                "Reply using the structured format: DONE or ITERATE with Category/Reason/Fix lines."
            ),
        )

        # Converge only needs the test results (already in user_msg) and the plan
        # to judge against Definition of Done. No raw tool call history needed.
        ctx: list[Message] = []
        if state.get("plan"):
            ctx.append(Message(role="user", content=f"Approved plan:\n{state['plan']}"))

        # M7.2 (DD-067): if a PlanContract was parsed, inject its success_criteria
        # so the verdict is grounded in the exact testable conditions the developer
        # approved rather than the LLM re-deriving them.
        plan_contract: dict | None = (state.get("facts") or {}).get("flowise", {}).get("plan_contract")
        if plan_contract:
            criteria: list[str] = plan_contract.get("success_criteria") or []
            if criteria:
                criteria_text = "\n".join(f"- {c}" for c in criteria)
                ctx.append(Message(
                    role="user",
                    content=(
                        "REQUIRED SUCCESS CRITERIA (from plan contract — approved by developer):\n"
                        f"{criteria_text}\n\n"
                        "Your verdict MUST explicitly reference each criterion above: "
                        "state whether it passed or failed based on the test results."
                    ),
                ))
                logger.debug(
                    "[CONVERGE] Injecting %d plan_contract success_criteria into prompt",
                    len(criteria),
                )

        # M7.4: time the converge LLM evaluation
        async with MetricsCollector("converge") as m_conv:
            response = await engine.complete(
                messages=ctx + [user_msg],
                system=_CONVERGE_BASE,
                tools=None,
            )
            m_conv.input_tokens = response.input_tokens
            m_conv.output_tokens = response.output_tokens

        raw_verdict = (response.content or "ITERATE\nCategory: INCOMPLETE\nReason: no response from LLM").strip()
        verdict_dict = _parse_converge_verdict(raw_verdict)
        is_done = verdict_dict["verdict"] == "DONE"

        # Safety net 1: no chatflow → cannot be DONE
        if is_done and not state.get("chatflow_id"):
            logger.warning("[CONVERGE] LLM said DONE but chatflow_id is missing — forcing ITERATE")
            is_done = False
            verdict_dict = {
                "verdict": "ITERATE",
                "category": "INCOMPLETE",
                "reason": "chatflow_id is not set — patch phase did not create/capture the chatflow",
                "fixes": [
                    "Call create_chatflow with the full node graph from the plan",
                    "Extract the id field from the API response and use it in all predict calls",
                ],
            }

        # Safety net 2: explicit [FAIL] markers in test results → cannot be DONE
        if is_done and state.get("test_results"):
            tr_upper = state["test_results"].upper()
            if "[FAIL]" in tr_upper or "SKIPPED" in tr_upper:
                logger.warning("[CONVERGE] LLM said DONE but test_results contain [FAIL] — forcing ITERATE")
                is_done = False
                verdict_dict = {
                    "verdict": "ITERATE",
                    "category": "LOGIC",
                    "reason": "Test results contain explicit [FAIL] — DoD not met",
                    "fixes": [
                        "Verify the chatflow ID is correct and the chatflow is deployed",
                        "Re-run predictions using the captured chatflow ID",
                    ],
                }

        assistant_msg = Message(role="assistant", content=raw_verdict)
        logger.info("[CONVERGE] verdict=%r done=%s", verdict_dict, is_done)

        # M7.4: write converge phase metrics to debug["flowise"]["phase_metrics"]
        _conv_existing_fd = (state.get("debug") or {}).get("flowise") or {}
        _conv_prior_phases = _conv_existing_fd.get("phase_metrics", [])
        _conv_debug = {
            "flowise": {
                **_conv_existing_fd,
                "phase_metrics": _conv_prior_phases + [m_conv.to_dict()],
            }
        }

        # Auto-save pattern when DONE (DD-031, enriched in M7.3 DD-068)
        if is_done and pattern_store and client:
            chatflow_id = state.get("chatflow_id")
            requirement = state.get("requirement", "")
            if chatflow_id and requirement:
                try:
                    chatflow = await client.get_chatflow(chatflow_id)
                    flow_data = chatflow.get("flowData", "") if isinstance(chatflow, dict) else ""
                    name = (
                        chatflow.get("name") if isinstance(chatflow, dict) else None
                    ) or requirement[:60]

                    # M7.3 (DD-068): derive structured metadata for pattern save
                    _node_types_json = ""
                    _category = ""
                    _schema_fp = ""

                    # node_types: extract from saved flow_data
                    if flow_data:
                        try:
                            _fd_parsed = (
                                json.loads(flow_data)
                                if isinstance(flow_data, str)
                                else flow_data
                            )
                            _names = [
                                n.get("data", {}).get("name") or ""
                                for n in (_fd_parsed.get("nodes") or [])
                            ]
                            _node_types_json = json.dumps([n for n in _names if n])
                        except Exception:
                            pass

                    # category: parse "6. PATTERN" section from approved plan
                    _plan_text = state.get("plan") or ""
                    _pm = re.search(
                        r"6\.\s+PATTERN\s*\n(.*?)(?=\n\d+\.|\n##|\Z)",
                        _plan_text,
                        re.DOTALL | re.IGNORECASE,
                    )
                    if _pm:
                        for _line in _pm.group(1).splitlines():
                            _line = _line.strip().lstrip("-* ")
                            if _line and not _line.lower().startswith("which"):
                                _category = _line.split(":")[0].strip()
                                break

                    # schema_fingerprint: from FlowiseCapability.knowledge.node_schemas
                    if capabilities:
                        _flowise_cap = next(
                            (c for c in capabilities if c.name == "flowise"), None
                        )
                        if _flowise_cap and hasattr(_flowise_cap, "knowledge"):
                            _ns = getattr(_flowise_cap.knowledge, "node_schemas", None)
                            if _ns and hasattr(_ns, "meta_fingerprint"):
                                _schema_fp = _ns.meta_fingerprint or ""

                    await pattern_store.save_pattern(
                        name=name,
                        requirement_text=requirement,
                        flow_data=flow_data,
                        chatflow_id=chatflow_id,
                        domain="flowise",
                        node_types=_node_types_json,
                        category=_category,
                        schema_fingerprint=_schema_fp,
                    )
                    logger.info("[CONVERGE] Pattern saved for chatflow %s", chatflow_id)
                except Exception as exc:
                    logger.warning("[CONVERGE] Pattern save failed (non-fatal): %s", exc)

        return {
            "messages": [user_msg, assistant_msg],
            "done": is_done,
            "iteration": iteration + 1,
            "converge_verdict": verdict_dict if not is_done else None,
            "total_input_tokens": response.input_tokens,
            "total_output_tokens": response.output_tokens,
            "debug": _conv_debug,
        }

    return converge


def _make_human_result_review_node():
    async def human_result_review(state: AgentState) -> dict:
        """INTERRUPT: surface test results to developer. Accept or iterate.

        Resume values:
          "accepted" (or "done", "yes", "looks good") → END
          Any other string → treat as feedback for next iteration, loop to plan
        """
        logger.info("[HUMAN RESULT REVIEW] waiting for developer input")

        interrupt_payload = {
            "type": "result_review",
            "test_results": state.get("test_results"),
            "chatflow_id": state.get("chatflow_id"),
            "iteration": state.get("iteration", 0),
            "prompt": (
                "The agent believes the chatflow is ready (Definition of Done met).\n"
                "Review the test results above.\n"
                "Reply 'accepted' to finish, or describe what to change for another iteration."
            ),
        }
        if state.get("webhook_url"):
            asyncio.create_task(_fire_webhook(state["webhook_url"], interrupt_payload))
        developer_response: str = interrupt(interrupt_payload)

        response_lower = developer_response.strip().lower()

        rollback = response_lower in ("rollback", "revert")
        accepted = response_lower in (
            "accepted", "accept", "done", "yes", "y", "looks good", "lgtm", "ship it"
        )

        logger.info(
            "[HUMAN RESULT REVIEW] accepted=%s rollback=%s", accepted, rollback
        )

        if rollback:
            # Developer wants to revert to the previous chatflow snapshot.
            # Mark session complete so the graph exits; the API caller can then
            # POST /sessions/{id}/rollback to restore a prior version in Flowise.
            return {
                "done": True,
                "developer_feedback": "[rollback requested by developer]",
            }
        elif accepted:
            return {"done": True, "developer_feedback": None}
        else:
            return {
                "done": False,
                "developer_feedback": developer_response,
                "plan": None,          # force a new plan with the feedback
                "test_results": None,  # clear stale results
            }

    return human_result_review


# ---------------------------------------------------------------------------
# Routing functions (conditional edges)
# ---------------------------------------------------------------------------


def _route_after_plan_approval(state: AgentState) -> str:
    """If developer gave feedback → back to plan. If approved → patch."""
    if state.get("developer_feedback"):
        return "plan"
    return "patch"


def _route_after_converge(state: AgentState) -> str:
    """If DoD met → show results to developer. If not → another iteration."""
    if state.get("done"):
        return "human_result_review"
    return "plan"


def _route_after_result_review(state: AgentState) -> str:
    """If developer accepted → END. If iterating → back to plan."""
    if state.get("done"):
        return END
    return "plan"


# ===========================================================================
# M9.6 — Production-Grade LangGraph Topology v2 (CREATE + UPDATE modes)
#
# 18-node topology with:
#   Phase A: classify_intent, hydrate_context
#   Phase B: resolve_target, HITL_select_target  (UPDATE only)
#   Phase C: load_current_flow, summarize_current_flow  (UPDATE only)
#   Phase D: plan, HITL_plan, define_patch_scope, compile_patch_ir, compile_flow_data
#   Phase E: validate, repair_schema
#   Phase F: preflight_validate_patch, apply_patch, test, evaluate, HITL_review
#
# See roadmap9_production_graph_runtime_hardening.md — Milestone 9.6
# ===========================================================================


# ---------------------------------------------------------------------------
# M9.6: Classify intent prompt
# ---------------------------------------------------------------------------

_CLASSIFY_INTENT_SYSTEM = """\
You are an intent classifier for a Flowise chatflow assistant.

Read the developer's requirement and classify the intent.

Respond with EXACTLY this format:
INTENT: create | update
CONFIDENCE: <0.0-1.0>
TARGET_NAME: <name of existing chatflow if update, else (none)>

Rules:
- "create" = building a new chatflow from scratch
- "update" = modifying/changing/fixing/extending an existing chatflow
- TARGET_NAME = the chatflow name mentioned (e.g. "Support Bot"); use (none) for create intent
- CONFIDENCE = how certain you are (0.0 = no idea, 1.0 = certain)

Examples:
  Requirement: "Build a new customer service chatbot"
  INTENT: create
  CONFIDENCE: 0.95
  TARGET_NAME: (none)

  Requirement: "Update the Support Bot chatflow to use GPT-4"
  INTENT: update
  CONFIDENCE: 0.9
  TARGET_NAME: Support Bot

  Requirement: "Add memory to my Sales Agent flow"
  INTENT: update
  CONFIDENCE: 0.8
  TARGET_NAME: Sales Agent
"""

_DEFINE_PATCH_SCOPE_SYSTEM = """\
You are scoping the patch phase for a Flowise chatflow builder.

Given the approved plan, output EXACTLY this format:
MAX_OPS: <integer>
FOCUS_AREA: <optional short description or (none)>
PROTECTED_NODES: <comma-separated node IDs or (none)>

Rules:
- For CREATE: default MAX_OPS is 20 (can increase for complex flows, max 30)
- For UPDATE: default MAX_OPS is 12 (changes are targeted, fewer ops needed)
- FOCUS_AREA: brief label for what area the patch targets (e.g. "LLM configuration")
- PROTECTED_NODES: node IDs that must NOT be removed in UPDATE mode (use (none) for CREATE)
"""

_COMPILE_PATCH_IR_V2_SYSTEM = """\
You are a Flowise co-pilot in the COMPILE PATCH IR phase (Topology v2).

Your task: output a JSON array of Patch IR operations that implement the approved plan.
DO NOT include any explanation, markdown fences, or text outside the JSON array.

AVAILABLE OPERATIONS:

1. AddNode — add a new Flowise node
   {"op_type":"add_node","node_name":"<flowise_type>","node_id":"<unique_id>","label":"<display>","params":{"modelName":"gpt-4o"}}

2. SetParam — update a configurable parameter on an existing node
   {"op_type":"set_param","node_id":"<id>","param_name":"<key>","value":"<val>"}

3. Connect — connect two nodes by anchor name (NOT handle IDs — the compiler derives them)
   {"op_type":"connect","source_node_id":"<id>","source_anchor":"<output_name>","target_node_id":"<id>","target_anchor":"<input_type>"}

4. BindCredential — bind a credential ID at BOTH data.credential levels
   {"op_type":"bind_credential","node_id":"<id>","credential_id":"<uuid>","credential_type":"<type>"}

RULES:
1. node_id: unique within the flow — use "<node_name>_<index>" e.g. "chatOpenAI_0"
2. source_anchor: output anchor name — usually the node_name itself (e.g. "chatOpenAI")
3. target_anchor: input anchor TYPE — the baseClass it accepts (e.g. "BaseChatModel", "BaseMemory")
4. EVERY credential-bearing node (LLM, embedding, etc.) MUST have a BindCredential op
5. Include ALL required nodes + connections for a working flow — never omit the chain/agent node
6. Do NOT write handle strings, edge IDs, or raw flowData JSON — the compiler derives all of that
7. For UPDATE: only emit ops for what CHANGES — do NOT re-add nodes already present

OUTPUT: A single JSON array only, nothing else.
"""

_EVALUATE_SYSTEM = """\
You are evaluating the result of a Flowise chatflow patch.

Given a diff summary of what changed, produce a verdict.

Respond with EXACTLY one of:
VERDICT: done
VERDICT: iterate
REASON: <one sentence>

Use "done" when all required changes from the plan were applied correctly.
Use "iterate" when the diff shows missing or incorrect changes.
"""


# ---------------------------------------------------------------------------
# M9.6: Utility — deterministic flow summarizer (NO LLM)
# ---------------------------------------------------------------------------


def _summarize_flow_data(flow_data: dict | str) -> dict:
    """Compute a compact structured summary of a Flowise flowData dict.

    This function is DETERMINISTIC — no LLM call. It reads the raw flowData
    and extracts only the structural metadata needed for planning.

    NEVER puts the full flowData into any LLM prompt. Only the returned
    summary dict may appear in LLM context.

    Returns a dict with:
        node_count: int
        edge_count: int
        node_types: dict[str, int]  — histogram of node type names
        top_labels: list[str]       — first 10 node display labels
        key_tool_nodes: list[str]   — node IDs of tool/agent/chain nodes
    """
    if isinstance(flow_data, str):
        try:
            flow_data = json.loads(flow_data)
        except (json.JSONDecodeError, TypeError):
            return {
                "node_count": 0,
                "edge_count": 0,
                "node_types": {},
                "top_labels": [],
                "key_tool_nodes": [],
            }

    if not isinstance(flow_data, dict):
        return {
            "node_count": 0,
            "edge_count": 0,
            "node_types": {},
            "top_labels": [],
            "key_tool_nodes": [],
        }

    nodes = flow_data.get("nodes") or []
    edges = flow_data.get("edges") or []

    node_types: dict[str, int] = {}
    top_labels: list[str] = []
    key_tool_nodes: list[str] = []

    # Keywords that identify "key" tool/agent/chain nodes
    _key_keywords = frozenset({
        "agent", "chain", "tool", "retriever", "memory", "llm",
        "chatmodel", "embedding", "vectorstore",
    })

    for node in nodes[:50]:  # cap at 50 to avoid huge summaries
        data = node.get("data") or {}
        node_name = data.get("name") or ""
        label = data.get("label") or node_name
        node_id = node.get("id") or ""

        # histogram
        if node_name:
            node_types[node_name] = node_types.get(node_name, 0) + 1

        # top labels (limit 10)
        if label and len(top_labels) < 10:
            top_labels.append(label)

        # key tool nodes — match by name/label keywords
        combined = (node_name + " " + label).lower()
        if any(kw in combined for kw in _key_keywords):
            key_tool_nodes.append(node_id)

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_types": node_types,
        "top_labels": top_labels,
        "key_tool_nodes": key_tool_nodes,
    }


def _repair_schema_for_ops(
    ops: list,
    missing_node_types: list[str],
    node_store,
) -> list[str]:
    """Attempt to repair missing node schemas for the given node types.

    Checks the local NodeSchemaStore for each missing type. Returns the list
    of node types that were successfully found (or already cached). Types that
    are truly absent from the store cannot be repaired here.

    This is a SYNCHRONOUS helper called from the repair_schema node (which
    itself is deterministic/sync). Callers that need async repair should use
    node_store.get_or_repair() directly.

    Args:
        ops:               The current list of PatchOp objects (used for type checking).
        missing_node_types: Node type names that failed AddNode during compile.
        node_store:         NodeSchemaStore instance. May be None (graceful skip).

    Returns:
        List of node_type strings that are now available in the store.
    """
    if node_store is None or not missing_node_types:
        return []

    repaired: list[str] = []
    for node_type in missing_node_types:
        # Check if the store already has this type in its index
        schema = node_store._index.get(node_type) if hasattr(node_store, "_index") else None
        if schema:
            repaired.append(node_type)
            logger.debug("[repair_schema] '%s' found in local index — no API call needed", node_type)
        else:
            logger.warning(
                "[repair_schema] '%s' not in local schema index — cannot repair without API call",
                node_type,
            )

    return repaired


# ---------------------------------------------------------------------------
# M9.6: Phase A nodes — classify_intent, hydrate_context
# ---------------------------------------------------------------------------


def _make_classify_intent_node(engine: ReasoningEngine):
    """Factory: classify_intent node (LLM-lite, no tools).

    Classifies the developer's requirement as "create" or "update" intent.
    For "update" intent, also extracts the target chatflow name if mentioned.
    Initializes budget state in facts["budgets"].
    """
    async def classify_intent(state: AgentState) -> dict:
        logger.info("[CLASSIFY_INTENT] classifying requirement intent")

        response = await engine.complete(
            messages=[Message(role="user", content=state["requirement"])],
            system=_CLASSIFY_INTENT_SYSTEM,
            tools=None,
        )
        text = (response.content or "").strip()

        # Parse intent
        intent = "create"
        confidence = 0.5
        target_name: str | None = None

        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("INTENT:"):
                val = line.split(":", 1)[1].strip().lower()
                if val in ("create", "update"):
                    intent = val
            elif line.upper().startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass
            elif line.upper().startswith("TARGET_NAME:"):
                raw = line.split(":", 1)[1].strip()
                if raw.lower() not in ("(none)", "none", ""):
                    target_name = raw

        logger.info(
            "[CLASSIFY_INTENT] intent=%s confidence=%.2f target_name=%r",
            intent, confidence, target_name,
        )

        # Initialize budget state
        existing_facts = state.get("facts") or {}
        existing_flowise = existing_facts.get("flowise") or {}

        new_facts: dict[str, Any] = {
            "flowise": {
                **existing_flowise,
                "intent": intent,
                "target_name": target_name,
            },
            "budgets": {
                "max_patch_ops_per_iter": 20 if intent == "create" else 12,
                "max_schema_repairs_per_iter": 2,
                "max_total_retries_per_iter": 1,
                "retries_used": 0,
            },
            "repair": {"count": 0, "repaired_node_types": []},
        }

        return {
            "operation_mode": intent,
            "target_chatflow_id": None,
            "intent_confidence": confidence,
            "facts": new_facts,
            "total_input_tokens": response.input_tokens,
            "total_output_tokens": response.output_tokens,
        }

    return classify_intent


def _make_hydrate_context_node(capabilities: "list[DomainCapability] | None" = None):
    """Factory: hydrate_context node (deterministic, no LLM, no tools).

    Loads local snapshot metadata from NodeSchemaStore (if available).
    Outputs facts["flowise"]["schema_fingerprint"] and facts["flowise"]["node_count"].
    Never makes network calls — skips gracefully if knowledge provider is absent.
    """
    async def hydrate_context(state: AgentState) -> dict:
        logger.info("[HYDRATE_CONTEXT] loading local snapshot metadata")

        schema_fingerprint: str | None = None
        node_count: int = 0

        if capabilities:
            flowise_cap = next(
                (c for c in capabilities if c.name == "flowise"), None
            )
            if flowise_cap and hasattr(flowise_cap, "knowledge"):
                provider = flowise_cap.knowledge
                node_store = getattr(provider, "node_schemas", None)
                if node_store is not None:
                    schema_fingerprint = getattr(node_store, "meta_fingerprint", None)
                    # node_count from the store's index
                    _index = getattr(node_store, "_index", {})
                    node_count = len(_index)
                    logger.debug(
                        "[HYDRATE_CONTEXT] node_count=%d fingerprint=%s",
                        node_count,
                        (schema_fingerprint or "")[:12] if schema_fingerprint else "none",
                    )

        existing_facts = state.get("facts") or {}
        existing_flowise = existing_facts.get("flowise") or {}

        updated_flowise = {
            **existing_flowise,
            "schema_fingerprint": schema_fingerprint,
            "node_count": node_count,
        }

        return {
            "facts": {"flowise": updated_flowise},
        }

    return hydrate_context


# ---------------------------------------------------------------------------
# M9.6: Phase B nodes — resolve_target, HITL_select_target  (UPDATE only)
# ---------------------------------------------------------------------------


def _make_resolve_target_node(domains: list[DomainTools]):
    """Factory: resolve_target node (tool call allowed, bounded max_rounds=5).

    Calls list_chatflows, optionally filters by target_name substring match,
    and stores the top 10 matches sorted by recency.

    Only runs for UPDATE intent. For CREATE, this node is skipped by routing.
    """
    _, executor = merge_tools(domains, "discover")

    async def resolve_target(state: AgentState) -> dict:
        logger.info("[RESOLVE_TARGET] listing chatflows for target resolution")

        target_name: str | None = (state.get("facts") or {}).get("flowise", {}).get("target_name")

        # Fetch chatflows list
        cf_result = await execute_tool("list_chatflows", {}, executor)

        chatflows: list[dict] = []
        if cf_result.ok:
            raw = cf_result.data
            if isinstance(raw, list):
                chatflows = raw
            elif isinstance(raw, dict) and "chatflows" in raw:
                chatflows = raw["chatflows"]

        # Filter by target_name (case-insensitive substring match)
        if target_name:
            tn_lower = target_name.lower()
            chatflows = [
                cf for cf in chatflows
                if tn_lower in (cf.get("name") or "").lower()
            ]
            logger.debug(
                "[RESOLVE_TARGET] filtered to %d match(es) for target_name=%r",
                len(chatflows), target_name,
            )

        # Sort by recency (updated_at or created_at descending)
        def _sort_key(cf: dict) -> str:
            return cf.get("updatedDate") or cf.get("createdDate") or ""

        chatflows.sort(key=_sort_key, reverse=True)

        # Limit to top 10
        top_matches = [
            {
                "id": cf.get("id") or "",
                "name": cf.get("name") or "",
                "updated_at": cf.get("updatedDate") or cf.get("createdDate") or "",
            }
            for cf in chatflows[:10]
        ]

        logger.info("[RESOLVE_TARGET] top_matches count=%d", len(top_matches))

        existing_facts = state.get("facts") or {}
        existing_flowise = existing_facts.get("flowise") or {}

        return {
            "facts": {
                "flowise": {
                    **existing_flowise,
                    "top_matches": top_matches,
                }
            }
        }

    return resolve_target


def _make_hitl_select_target_node():
    """Factory: HITL_select_target node (interrupt).

    Presents top_matches to the developer. Developer selects a chatflow to
    update OR replies "create new" to switch to CREATE mode.
    """
    async def hitl_select_target(state: AgentState) -> dict:
        logger.info("[HITL_SELECT_TARGET] waiting for developer target selection")

        top_matches = (state.get("facts") or {}).get("flowise", {}).get("top_matches", [])

        interrupt_payload = {
            "type": "select_target",
            "top_matches": top_matches,
            "prompt": (
                "Select which chatflow to update by replying with the chatflow ID or name.\n"
                "Or reply 'create new' to build a new chatflow instead.\n\n"
                "Available chatflows:\n"
                + "\n".join(
                    f"  - {m['name']} (id={m['id']}, updated={m['updated_at']})"
                    for m in top_matches
                )
                if top_matches else
                "No matching chatflows found. Reply 'create new' to build a new chatflow."
            ),
        }
        if state.get("webhook_url"):
            asyncio.create_task(_fire_webhook(state["webhook_url"], interrupt_payload))

        developer_response: str = interrupt(interrupt_payload)
        response_stripped = developer_response.strip()

        existing_facts = state.get("facts") or {}
        existing_flowise = existing_facts.get("flowise") or {}

        # Parse response
        if response_stripped.lower() in ("create new", "create", "new"):
            logger.info("[HITL_SELECT_TARGET] developer chose 'create new'")
            return {
                "operation_mode": "create",
                "target_chatflow_id": None,
                "facts": {
                    "flowise": {
                        **existing_flowise,
                        "operation_mode": "create",
                    }
                },
            }

        # Try to match by ID first (UUID pattern)
        matched_id: str | None = None
        matched_name: str | None = None
        for match in top_matches:
            if response_stripped == match["id"] or response_stripped.lower() == match["name"].lower():
                matched_id = match["id"]
                matched_name = match["name"]
                break

        # Fallback: substring name match
        if not matched_id:
            response_lower = response_stripped.lower()
            for match in top_matches:
                if response_lower in (match["name"] or "").lower():
                    matched_id = match["id"]
                    matched_name = match["name"]
                    break

        if matched_id:
            logger.info(
                "[HITL_SELECT_TARGET] selected chatflow id=%s name=%r",
                matched_id, matched_name,
            )
            return {
                "operation_mode": "update",
                "target_chatflow_id": matched_id,
                "facts": {
                    "flowise": {
                        **existing_flowise,
                        "operation_mode": "update",
                        "target_chatflow_id": matched_id,
                    }
                },
            }

        # Unknown response — treat as "create new"
        logger.warning(
            "[HITL_SELECT_TARGET] could not match response %r — defaulting to create new",
            response_stripped,
        )
        return {
            "operation_mode": "create",
            "target_chatflow_id": None,
            "facts": {
                "flowise": {
                    **existing_flowise,
                    "operation_mode": "create",
                }
            },
        }

    return hitl_select_target


# ---------------------------------------------------------------------------
# M9.6: Phase C nodes — load_current_flow, summarize_current_flow  (UPDATE only)
# ---------------------------------------------------------------------------


def _make_load_current_flow_node(domains: list[DomainTools]):
    """Factory: load_current_flow node (tool allowed, exactly once).

    Fetches full flowData via get_chatflow(chatflow_id). CRITICAL: stores
    the full JSON in artifacts["flowise"]["current_flow_data"] — NOT in LLM
    context (messages). Also computes a SHA-256 hash for integrity tracking.
    """
    _, executor = merge_tools(domains, "discover")

    async def load_current_flow(state: AgentState) -> dict:
        target_id = state.get("target_chatflow_id")
        logger.info("[LOAD_CURRENT_FLOW] fetching chatflow id=%s", target_id)

        if not target_id:
            logger.warning("[LOAD_CURRENT_FLOW] no target_chatflow_id — skipping")
            return {}

        cf_result = await execute_tool(
            "get_chatflow", {"chatflow_id": target_id}, executor
        )

        if not cf_result.ok or not isinstance(cf_result.data, dict):
            logger.warning(
                "[LOAD_CURRENT_FLOW] get_chatflow failed or returned non-dict: %s",
                cf_result.summary,
            )
            return {}

        raw_flow_data = (
            cf_result.data.get("flowData")
            or cf_result.data.get("flow_data")
            or {}
        )

        # Parse if string
        if isinstance(raw_flow_data, str):
            try:
                flow_data_dict = json.loads(raw_flow_data)
            except json.JSONDecodeError:
                flow_data_dict = {}
            flow_data_str = raw_flow_data
        else:
            flow_data_dict = raw_flow_data
            flow_data_str = json.dumps(raw_flow_data, separators=(",", ":"))

        # Compute hash
        current_hash = hashlib.sha256(flow_data_str.encode("utf-8")).hexdigest()

        node_count = len((flow_data_dict.get("nodes") or []))
        edge_count = len((flow_data_dict.get("edges") or []))
        logger.info(
            "[LOAD_CURRENT_FLOW] loaded flow: nodes=%d edges=%d hash=%s...",
            node_count, edge_count, current_hash[:12],
        )

        # CRITICAL: store full JSON in artifacts, NOT in messages
        existing_artifacts = state.get("artifacts") or {}
        existing_flowise_artifacts = existing_artifacts.get("flowise") or {}
        existing_facts = state.get("facts") or {}
        existing_flowise_facts = existing_facts.get("flowise") or {}

        return {
            "artifacts": {
                "flowise": {
                    **existing_flowise_artifacts,
                    "current_flow_data": flow_data_dict,
                }
            },
            "facts": {
                "flowise": {
                    **existing_flowise_facts,
                    "current_flow_hash": current_hash,
                }
            },
        }

    return load_current_flow


def _make_summarize_current_flow_node():
    """Factory: summarize_current_flow node (deterministic, NO LLM call).

    Reads artifacts["flowise"]["current_flow_data"] and computes a compact
    structured summary. NEVER puts full flowData into any prompt.
    """
    async def summarize_current_flow(state: AgentState) -> dict:
        logger.info("[SUMMARIZE_CURRENT_FLOW] computing flow summary (deterministic)")

        current_flow_data = (
            (state.get("artifacts") or {})
            .get("flowise", {})
            .get("current_flow_data")
        )

        if not current_flow_data:
            logger.warning("[SUMMARIZE_CURRENT_FLOW] no current_flow_data in artifacts")
            flow_summary = {
                "node_count": 0,
                "edge_count": 0,
                "node_types": {},
                "top_labels": [],
                "key_tool_nodes": [],
            }
        else:
            flow_summary = _summarize_flow_data(current_flow_data)

        logger.debug(
            "[SUMMARIZE_CURRENT_FLOW] summary: node_count=%d edge_count=%d types=%d",
            flow_summary["node_count"],
            flow_summary["edge_count"],
            len(flow_summary["node_types"]),
        )

        existing_facts = state.get("facts") or {}
        existing_flowise_facts = existing_facts.get("flowise") or {}

        return {
            "facts": {
                "flowise": {
                    **existing_flowise_facts,
                    "flow_summary": flow_summary,
                }
            }
        }

    return summarize_current_flow


# ---------------------------------------------------------------------------
# M9.6: Phase D nodes — define_patch_scope, compile_patch_ir, compile_flow_data
# ---------------------------------------------------------------------------


def _make_define_patch_scope_node(engine: ReasoningEngine):
    """Factory: define_patch_scope node (LLM-lite, no tools).

    Single LLM call: given the plan, determine max_ops, focus_area,
    and protected_nodes. Overrides the budget initialized by classify_intent.
    """
    async def define_patch_scope(state: AgentState) -> dict:
        logger.info("[DEFINE_PATCH_SCOPE] scoping the patch phase")

        plan = state.get("plan") or ""
        operation_mode = state.get("operation_mode") or "create"

        prompt = (
            f"Operation mode: {operation_mode}\n\n"
            f"Approved plan:\n{plan[:2000]}\n\n"
            "Based on the plan, define the patch scope."
        )

        response = await engine.complete(
            messages=[Message(role="user", content=prompt)],
            system=_DEFINE_PATCH_SCOPE_SYSTEM,
            tools=None,
        )
        text = (response.content or "").strip()

        # Parse response
        max_ops = 20 if operation_mode == "create" else 12
        focus_area: str | None = None
        protected_nodes: list[str] = []

        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("MAX_OPS:"):
                try:
                    max_ops = int(line.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass
            elif line.upper().startswith("FOCUS_AREA:"):
                raw = line.split(":", 1)[1].strip()
                if raw.lower() not in ("(none)", "none", ""):
                    focus_area = raw
            elif line.upper().startswith("PROTECTED_NODES:"):
                raw = line.split(":", 1)[1].strip()
                if raw.lower() not in ("(none)", "none", ""):
                    protected_nodes = [n.strip() for n in raw.split(",") if n.strip()]

        logger.info(
            "[DEFINE_PATCH_SCOPE] max_ops=%d focus_area=%r protected_nodes=%r",
            max_ops, focus_area, protected_nodes,
        )

        existing_facts = state.get("facts") or {}
        existing_budgets = existing_facts.get("budgets") or {}

        return {
            "facts": {
                "patch": {
                    "max_ops": max_ops,
                    "focus_area": focus_area,
                    "protected_nodes": protected_nodes,
                },
                "budgets": {
                    **existing_budgets,
                    "max_patch_ops_per_iter": max_ops,
                },
            },
            "total_input_tokens": response.input_tokens,
            "total_output_tokens": response.output_tokens,
        }

    return define_patch_scope


def _make_compile_patch_ir_node(
    engine: ReasoningEngine,
    capabilities: "list[DomainCapability] | None" = None,
):
    """Factory: compile_patch_ir node (LLM, no tools).

    Similar to the existing patch node's IR phase but decoupled from the
    write step. For UPDATE: uses flow_summary in context (NOT full flowData).
    Emits a JSON array of Patch IR ops.
    """
    flowise_cap: "DomainCapability | None" = next(
        (cap for cap in (capabilities or []) if cap.name == "flowise"), None
    )

    async def compile_patch_ir(state: AgentState) -> dict:
        logger.info("[COMPILE_PATCH_IR] generating patch IR ops")

        plan = state.get("plan") or ""
        requirement = state.get("requirement", "")
        operation_mode = state.get("operation_mode") or "create"
        facts = state.get("facts") or {}
        flow_summary = facts.get("flowise", {}).get("flow_summary")
        focus_area = facts.get("patch", {}).get("focus_area")
        protected_nodes = facts.get("patch", {}).get("protected_nodes") or []

        # Build context — NEVER include full flowData; only use flow_summary
        context_parts = [
            f"Requirement:\n{requirement}",
            f"Operation mode: {operation_mode}",
            f"Approved plan:\n{plan}",
        ]

        if operation_mode == "update" and flow_summary:
            # Compact structural context from summary (NOT full flowData)
            summary_str = (
                f"Current flow summary:\n"
                f"  node_count: {flow_summary.get('node_count', 0)}\n"
                f"  edge_count: {flow_summary.get('edge_count', 0)}\n"
                f"  node_types: {json.dumps(flow_summary.get('node_types', {}))}\n"
                f"  top_labels: {flow_summary.get('top_labels', [])}\n"
                f"  key_tool_nodes: {flow_summary.get('key_tool_nodes', [])}"
            )
            context_parts.append(summary_str)

        if focus_area:
            context_parts.append(f"Focus area: {focus_area}")

        if protected_nodes:
            context_parts.append(
                f"Protected nodes (do NOT remove): {', '.join(protected_nodes)}"
            )

        # Check if there is a pattern-seeded base graph (for CREATE mode)
        if operation_mode == "create":
            base_ir_data = (state.get("artifacts") or {}).get("flowise", {}).get("base_graph_ir")
            if base_ir_data:
                base_graph = GraphIR.from_flow_data(base_ir_data)
                if base_graph.nodes:
                    existing_lines = [
                        f"  - {n.id} ({n.node_name}): {n.label}"
                        for n in base_graph.nodes
                    ]
                    context_parts.append(
                        "Pattern-seeded base nodes already present:\n"
                        + "\n".join(existing_lines)
                        + "\nDo NOT re-add these nodes."
                    )

        user_msg = Message(
            role="user",
            content="\n\n".join(context_parts)
            + "\n\nOutput the JSON array of Patch IR operations.",
        )

        response = await engine.complete(
            messages=[user_msg],
            system=_COMPILE_PATCH_IR_V2_SYSTEM,
            tools=None,
        )
        raw_ops_text = (response.content or "[]").strip()

        # Parse ops
        ops = []
        ir_errors: list[str] = []
        try:
            ops = ops_from_json(raw_ops_text)
        except Exception as e:
            ir_errors = [f"Failed to parse Patch IR JSON: {e}"]
            logger.warning("[COMPILE_PATCH_IR] ops parse failed: %s", e)

        if not ir_errors:
            # Validate (without a base graph context here; full validation in compile_flow_data)
            ir_errors = validate_patch_ops(ops)

        logger.info(
            "[COMPILE_PATCH_IR] ops=%d ir_errors=%d",
            len(ops), len(ir_errors),
        )

        patch_ir_dicts = [op_to_dict(op) for op in ops]

        return {
            "patch_ir": patch_ir_dicts,
            "total_input_tokens": response.input_tokens,
            "total_output_tokens": response.output_tokens,
        }

    return compile_patch_ir


def _make_compile_flow_data_node(
    capabilities: "list[DomainCapability] | None" = None,
    domains: "list[DomainTools] | None" = None,
):
    """Factory: compile_flow_data node (deterministic compiler).

    CREATE: base = empty GraphIR or pattern skeleton from artifacts["flowise"]["base_graph_ir"]
    UPDATE: base = normalized GraphIR from artifacts["flowise"]["current_flow_data"]
    Applies patch_ir ops via compile_patch_ops().
    """
    flowise_cap: "DomainCapability | None" = next(
        (cap for cap in (capabilities or []) if cap.name == "flowise"), None
    )
    # Build a discover executor for schema fetching
    _domains = domains or []
    _, discover_executor = merge_tools(_domains, "discover")

    async def compile_flow_data(state: AgentState) -> dict:
        logger.info("[COMPILE_FLOW_DATA] running deterministic compiler")

        operation_mode = state.get("operation_mode") or "create"
        patch_ir_dicts = state.get("patch_ir") or []
        artifacts = state.get("artifacts") or {}
        flowise_artifacts = artifacts.get("flowise") or {}

        # Reconstruct ops from IR dicts
        try:
            ops = ops_from_json(json.dumps(patch_ir_dicts))
        except Exception as e:
            logger.warning("[COMPILE_FLOW_DATA] failed to reconstruct ops: %s", e)
            ops = []

        # Determine base graph
        if operation_mode == "update":
            current_flow_data = flowise_artifacts.get("current_flow_data") or {}
            base_graph = GraphIR.from_flow_data(current_flow_data)
            logger.debug(
                "[COMPILE_FLOW_DATA] UPDATE base: %d nodes, %d edges",
                len(base_graph.nodes), len(base_graph.edges),
            )
        else:
            # CREATE: use pattern-seeded base or empty
            base_ir_data = flowise_artifacts.get("base_graph_ir")
            if base_ir_data:
                base_graph = GraphIR.from_flow_data(base_ir_data)
                logger.debug(
                    "[COMPILE_FLOW_DATA] CREATE with pattern seed: %d nodes",
                    len(base_graph.nodes),
                )
            else:
                base_graph = GraphIR()
                logger.debug("[COMPILE_FLOW_DATA] CREATE from empty GraphIR")

        # Build schema cache for AddNode ops
        schema_cache: dict[str, dict] = {}
        new_node_names = {
            op.node_name for op in ops
            if isinstance(op, AddNode) and op.node_name
        }

        if new_node_names:
            provider = flowise_cap.knowledge if flowise_cap else None
            node_store = provider.node_schemas if provider else None

            for node_name in new_node_names:
                if node_store is not None:
                    # Local-first: use snapshot
                    schema = node_store._index.get(node_name) if hasattr(node_store, "_index") else None
                    if schema:
                        schema_cache[node_name] = schema
                    else:
                        # Fallback to API
                        _result = await execute_tool(
                            "get_node", {"name": node_name}, discover_executor
                        )
                        if isinstance(_result, ToolResult) and _result.ok and isinstance(_result.data, dict):
                            schema_cache[node_name] = _result.data
                else:
                    # No knowledge provider — try API directly
                    _result = await execute_tool(
                        "get_node", {"name": node_name}, discover_executor
                    )
                    if isinstance(_result, ToolResult) and _result.ok and isinstance(_result.data, dict):
                        schema_cache[node_name] = _result.data

        # Deterministic compilation
        compile_result = compile_patch_ops(base_graph, ops, schema_cache)

        if not compile_result.ok:
            logger.warning("[COMPILE_FLOW_DATA] compile errors: %s", compile_result.errors[:3])

        # Compute proposed flow hash
        proposed_hash = compile_result.payload_hash
        logger.info(
            "[COMPILE_FLOW_DATA] ok=%s ops=%d hash=%s...",
            compile_result.ok, len(ops), proposed_hash[:12],
        )

        existing_flowise_artifacts = flowise_artifacts.copy()
        existing_flowise_facts = (state.get("facts") or {}).get("flowise") or {}

        return {
            "artifacts": {
                "flowise": {
                    **existing_flowise_artifacts,
                    "proposed_flow_data": compile_result.flow_data,
                    "compile_errors": compile_result.errors,
                    "diff_summary": compile_result.diff_summary,
                }
            },
            "facts": {
                "flowise": {
                    **existing_flowise_facts,
                    "proposed_flow_hash": proposed_hash,
                }
            },
        }

    return compile_flow_data


# ---------------------------------------------------------------------------
# M9.6: Phase E nodes — validate, repair_schema
# ---------------------------------------------------------------------------


def _make_validate_node():
    """Factory: validate node (deterministic).

    Validates artifacts["flowise"]["proposed_flow_data"] using _validate_flow_data.
    Classifies failure type for routing decisions.
    """
    async def validate(state: AgentState) -> dict:
        logger.info("[VALIDATE] running structural validation on proposed flow")

        proposed_flow_data = (
            (state.get("artifacts") or {})
            .get("flowise", {})
            .get("proposed_flow_data")
        )

        if not proposed_flow_data:
            logger.warning("[VALIDATE] no proposed_flow_data in artifacts")
            existing_facts = state.get("facts") or {}
            return {
                "facts": {
                    "validation": {
                        "ok": False,
                        "failure_type": "other",
                        "missing_node_types": [],
                    }
                },
                "artifacts": {
                    "validation_report": "No proposed_flow_data available to validate.",
                },
            }

        # Run structural validation
        flow_data_str = json.dumps(proposed_flow_data, separators=(",", ":"))
        # Check for compile errors first
        compile_errors = (
            (state.get("artifacts") or {})
            .get("flowise", {})
            .get("compile_errors") or []
        )

        if compile_errors:
            # Classify: compile errors often mean missing schemas → schema_mismatch
            missing_types = []
            for err in compile_errors:
                if "no schema for" in err.lower():
                    # Extract node type from error like "AddNode 'id': no schema for 'type'"
                    import re as _re
                    m = _re.search(r"no schema for '([^']+)'", err)
                    if m:
                        missing_types.append(m.group(1))

            failure_type = "schema_mismatch" if missing_types else "structural"
            report = "Compilation errors:\n" + "\n".join(compile_errors)

            logger.info(
                "[VALIDATE] compile_errors=%d failure_type=%s missing=%r",
                len(compile_errors), failure_type, missing_types,
            )

            existing_facts = state.get("facts") or {}
            return {
                "facts": {
                    "validation": {
                        "ok": False,
                        "failure_type": failure_type,
                        "missing_node_types": missing_types,
                    }
                },
                "artifacts": {
                    "validation_report": report,
                },
            }

        # Structural validation of the flow data
        validation_raw = _validate_flow_data(flow_data_str)

        if validation_raw.get("valid"):
            logger.info(
                "[VALIDATE] valid: nodes=%d edges=%d",
                validation_raw.get("node_count", 0),
                validation_raw.get("edge_count", 0),
            )
            report = (
                f"Valid: {validation_raw.get('node_count', 0)} nodes, "
                f"{validation_raw.get('edge_count', 0)} edges."
            )
            existing_facts = state.get("facts") or {}
            return {
                "facts": {
                    "validation": {
                        "ok": True,
                        "failure_type": None,
                        "missing_node_types": [],
                    }
                },
                "artifacts": {
                    "validation_report": report,
                },
            }
        else:
            errors = validation_raw.get("errors", [])
            # Classify failure type
            missing_types = []
            failure_type = "structural"
            for err in errors:
                if "no schema" in err.lower() or "unknown node type" in err.lower():
                    failure_type = "schema_mismatch"
                    import re as _re
                    m = _re.search(r"'([^']+)'", err)
                    if m:
                        missing_types.append(m.group(1))

            report = "Validation errors:\n" + "\n".join(errors[:10])
            logger.info(
                "[VALIDATE] invalid: errors=%d failure_type=%s",
                len(errors), failure_type,
            )

            existing_facts = state.get("facts") or {}
            return {
                "facts": {
                    "validation": {
                        "ok": False,
                        "failure_type": failure_type,
                        "missing_node_types": missing_types,
                    }
                },
                "artifacts": {
                    "validation_report": report,
                },
            }

    return validate


def _make_repair_schema_node(
    capabilities: "list[DomainCapability] | None" = None,
    domains: "list[DomainTools] | None" = None,
):
    """Factory: repair_schema node (deterministic, targeted).

    Only triggered when failure_type == "schema_mismatch". Attempts to re-fetch
    the missing node schemas using NodeSchemaStore or API fallback.
    Increments facts["repair"]["count"] and enforces budget.
    """
    flowise_cap: "DomainCapability | None" = next(
        (cap for cap in (capabilities or []) if cap.name == "flowise"), None
    )
    _domains = domains or []
    _, discover_executor = merge_tools(_domains, "discover")

    async def repair_schema(state: AgentState) -> dict:
        logger.info("[REPAIR_SCHEMA] attempting schema repair")

        facts = state.get("facts") or {}
        validation_facts = facts.get("validation") or {}
        missing_node_types = validation_facts.get("missing_node_types") or []
        repair_facts = facts.get("repair") or {"count": 0, "repaired_node_types": []}
        budget_facts = facts.get("budgets") or {}

        repair_count = repair_facts.get("count", 0)
        max_repairs = budget_facts.get("max_schema_repairs_per_iter", 2)

        if repair_count >= max_repairs:
            logger.warning(
                "[REPAIR_SCHEMA] budget exceeded: count=%d max=%d",
                repair_count, max_repairs,
            )
            # Budget exceeded — signal via facts but don't loop
            return {
                "facts": {
                    "repair": {
                        **repair_facts,
                        "count": repair_count,
                        "budget_exceeded": True,
                    }
                }
            }

        # Attempt repair for each missing type
        provider = flowise_cap.knowledge if flowise_cap else None
        node_store = provider.node_schemas if provider else None

        # Use synchronous helper to check local store
        locally_found = _repair_schema_for_ops([], missing_node_types, node_store)

        # For types NOT found locally, try API
        api_fetched: list[str] = []
        for node_type in missing_node_types:
            if node_type in locally_found:
                continue
            _result = await execute_tool(
                "get_node", {"name": node_type}, discover_executor
            )
            if isinstance(_result, ToolResult) and _result.ok and isinstance(_result.data, dict):
                # Update the store's index if possible
                if node_store and hasattr(node_store, "_index"):
                    node_store._index[node_type] = _result.data
                    api_fetched.append(node_type)
                    logger.info("[REPAIR_SCHEMA] fetched '%s' via API", node_type)

        all_repaired = locally_found + api_fetched
        new_count = repair_count + 1

        logger.info(
            "[REPAIR_SCHEMA] repaired=%r count=%d",
            all_repaired, new_count,
        )

        existing_repaired = repair_facts.get("repaired_node_types") or []
        return {
            "facts": {
                "repair": {
                    "count": new_count,
                    "repaired_node_types": existing_repaired + all_repaired,
                    "budget_exceeded": False,
                }
            }
        }

    return repair_schema


# ---------------------------------------------------------------------------
# M9.6: Phase F nodes — preflight_validate_patch, apply_patch, evaluate, HITL_review
# ---------------------------------------------------------------------------


def _make_preflight_validate_patch_node():
    """Factory: preflight_validate_patch node (deterministic).

    Checks all budget constraints before authorizing the write.
    If any budget is exceeded, sets facts["preflight"]["ok"] = False.
    """
    async def preflight_validate_patch(state: AgentState) -> dict:
        logger.info("[PREFLIGHT_VALIDATE_PATCH] checking budgets")

        facts = state.get("facts") or {}
        budget_facts = facts.get("budgets") or {}
        repair_facts = facts.get("repair") or {}
        patch_ir_dicts = state.get("patch_ir") or []
        patch_facts = facts.get("patch") or {}

        max_ops = patch_facts.get("max_ops") or budget_facts.get("max_patch_ops_per_iter", 20)
        max_repairs = budget_facts.get("max_schema_repairs_per_iter", 2)
        max_retries = budget_facts.get("max_total_retries_per_iter", 1)
        retries_used = budget_facts.get("retries_used", 0)
        repair_count = repair_facts.get("count", 0)
        repair_budget_exceeded = repair_facts.get("budget_exceeded", False)

        checks_failed: list[str] = []

        # Check 1: patch_ir length
        if len(patch_ir_dicts) > max_ops:
            checks_failed.append(
                f"patch_ir length {len(patch_ir_dicts)} exceeds max_ops {max_ops}"
            )

        # Check 2: schema repair count
        if repair_count > max_repairs or repair_budget_exceeded:
            checks_failed.append(
                f"repair_count {repair_count} exceeds max_schema_repairs_per_iter {max_repairs}"
            )

        # Check 3: total retries
        if retries_used > max_retries:
            checks_failed.append(
                f"retries_used {retries_used} exceeds max_total_retries_per_iter {max_retries}"
            )

        ok = len(checks_failed) == 0
        reason = "; ".join(checks_failed) if checks_failed else None

        logger.info(
            "[PREFLIGHT_VALIDATE_PATCH] ok=%s reason=%r",
            ok, reason,
        )

        return {
            "facts": {
                "preflight": {
                    "ok": ok,
                    "reason": reason,
                }
            }
        }

    return preflight_validate_patch


def _make_apply_patch_node(
    domains: list[DomainTools],
    capabilities: "list[DomainCapability] | None" = None,
):
    """Factory: apply_patch node (write-guarded, single write).

    CREATE: calls create_chatflow
    UPDATE: calls update_chatflow(target_chatflow_id)
    Uses WriteGuard to enforce hash match before writing.
    """
    _, patch_executor = merge_tools(domains, "patch")

    async def apply_patch(state: AgentState) -> dict:
        logger.info("[APPLY_PATCH] applying patch to Flowise")

        facts = state.get("facts") or {}
        flowise_facts = facts.get("flowise") or {}
        operation_mode = state.get("operation_mode") or "create"
        target_chatflow_id = state.get("target_chatflow_id")

        proposed_flow_data = (
            (state.get("artifacts") or {})
            .get("flowise", {})
            .get("proposed_flow_data") or {}
        )
        proposed_hash = flowise_facts.get("proposed_flow_hash")

        if not proposed_flow_data:
            logger.warning("[APPLY_PATCH] no proposed_flow_data — skipping write")
            return {
                "facts": {
                    "apply": {
                        "ok": False,
                        "chatflow_id": None,
                        "error": "no proposed_flow_data",
                    }
                }
            }

        flow_data_str = json.dumps(proposed_flow_data, separators=(",", ":"))

        # WriteGuard: authorize then check on write
        guard = WriteGuard()
        guard.authorize(flow_data_str)

        orig_create = patch_executor.get("create_chatflow")
        orig_update = patch_executor.get("update_chatflow")

        async def _guarded_create(**kwargs: Any) -> Any:
            fd = kwargs.get("flow_data", "")
            if fd:
                guard.check(str(fd))
            result = await orig_create(**kwargs) if orig_create else {"error": "create_chatflow not available"}
            if fd:
                guard.revoke()
            return result

        async def _guarded_update(**kwargs: Any) -> Any:
            fd = kwargs.get("flow_data", "")
            if fd:
                guard.check(str(fd))
            result = await orig_update(**kwargs) if orig_update else {"error": "update_chatflow not available"}
            if fd:
                guard.revoke()
            return result

        guarded_executor = dict(patch_executor)
        guarded_executor["create_chatflow"] = _guarded_create
        guarded_executor["update_chatflow"] = _guarded_update

        new_chatflow_id: str | None = None
        apply_ok = False

        if operation_mode == "update" and target_chatflow_id:
            # Store rollback anchor (pre-patch hash)
            pre_patch_hash = flowise_facts.get("current_flow_hash")

            # Snapshot before update
            iteration = state.get("iteration", 0)
            await execute_tool(
                "snapshot_chatflow",
                {"chatflow_id": target_chatflow_id, "session_id": f"v2-apply-iter{iteration}"},
                guarded_executor,
            )

            write_result = await execute_tool(
                "update_chatflow",
                {"chatflow_id": target_chatflow_id, "flow_data": flow_data_str},
                guarded_executor,
            )
            apply_ok = write_result.ok
            new_chatflow_id = target_chatflow_id

            apply_facts: dict = {
                "ok": apply_ok,
                "chatflow_id": new_chatflow_id,
                "pre_patch_flow_hash": pre_patch_hash,
            }
        else:
            # CREATE mode
            plan = state.get("plan") or ""
            chatflow_name = _extract_chatflow_name_from_plan(plan) or state.get("requirement", "")[:50]

            write_result = await execute_tool(
                "create_chatflow",
                {"name": chatflow_name, "flow_data": flow_data_str},
                guarded_executor,
            )
            apply_ok = write_result.ok

            if apply_ok:
                if write_result.artifacts:
                    ids = write_result.artifacts.get("chatflow_ids", [])
                    if ids:
                        new_chatflow_id = ids[0]
                if not new_chatflow_id and isinstance(write_result.data, dict):
                    new_chatflow_id = write_result.data.get("id")

            apply_facts = {
                "ok": apply_ok,
                "chatflow_id": new_chatflow_id,
            }

        logger.info(
            "[APPLY_PATCH] ok=%s chatflow_id=%s",
            apply_ok, new_chatflow_id,
        )

        return {
            "chatflow_id": new_chatflow_id,
            "facts": {"apply": apply_facts},
        }

    return apply_patch


def _make_evaluate_node(engine: ReasoningEngine):
    """Factory: evaluate node (deterministic diff + small LLM).

    Computes diff from the diff_summary in artifacts. Produces a verdict:
    done | iterate. Writes artifacts["diff_summary"] and facts["verdict"].
    """
    async def evaluate(state: AgentState) -> dict:
        logger.info("[EVALUATE] evaluating patch result")

        artifacts = state.get("artifacts") or {}
        flowise_artifacts = artifacts.get("flowise") or {}
        diff_summary = flowise_artifacts.get("diff_summary") or "(no diff available)"
        plan = state.get("plan") or ""
        test_results = state.get("test_results") or "(no test results)"

        user_content = (
            f"Plan:\n{plan[:500]}\n\n"
            f"Diff of changes applied:\n{diff_summary}\n\n"
            f"Test results:\n{test_results[:500]}\n\n"
            "Did the patch implement the plan correctly?"
        )

        response = await engine.complete(
            messages=[Message(role="user", content=user_content)],
            system=_EVALUATE_SYSTEM,
            tools=None,
        )
        text = (response.content or "").strip()

        # Parse verdict
        verdict = "iterate"
        reason = ""
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("VERDICT:"):
                raw = line.split(":", 1)[1].strip().lower()
                if raw in ("done", "iterate"):
                    verdict = raw
            elif line.upper().startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()

        logger.info("[EVALUATE] verdict=%s reason=%r", verdict, reason)

        existing_facts = state.get("facts") or {}
        return {
            "artifacts": {
                "diff_summary": diff_summary,
            },
            "facts": {
                "verdict": {"verdict": verdict, "reason": reason},
            },
            "done": verdict == "done",
            "total_input_tokens": response.input_tokens,
            "total_output_tokens": response.output_tokens,
        }

    return evaluate


def _make_hitl_review_node():
    """Factory: HITL_review node (interrupt).

    Shows diff_summary to the user. Same as current human_result_review
    but uses the v2 diff_summary from artifacts.
    """
    async def hitl_review(state: AgentState) -> dict:
        logger.info("[HITL_REVIEW] waiting for developer review")

        diff_summary = (
            (state.get("artifacts") or {}).get("diff_summary")
            or state.get("test_results")
            or "(no summary available)"
        )

        interrupt_payload = {
            "type": "result_review",
            "diff_summary": diff_summary,
            "test_results": state.get("test_results"),
            "chatflow_id": state.get("chatflow_id"),
            "iteration": state.get("iteration", 0),
            "prompt": (
                "Review the changes applied to the chatflow.\n"
                f"Diff summary:\n{str(diff_summary)[:500]}\n\n"
                "Reply 'accepted' to finish, or describe what to change for another iteration."
            ),
        }
        if state.get("webhook_url"):
            asyncio.create_task(_fire_webhook(state["webhook_url"], interrupt_payload))

        developer_response: str = interrupt(interrupt_payload)
        response_lower = developer_response.strip().lower()

        accepted = response_lower in (
            "accepted", "accept", "done", "yes", "y", "looks good", "lgtm", "ship it"
        )

        logger.info("[HITL_REVIEW] accepted=%s", accepted)

        if accepted:
            return {"done": True, "developer_feedback": None}
        else:
            return {
                "done": False,
                "developer_feedback": developer_response,
                "plan": None,
                "test_results": None,
            }

    return hitl_review


# ---------------------------------------------------------------------------
# M9.6: Routing functions for Topology v2
# ---------------------------------------------------------------------------


def _route_after_hydrate_context_v2(state: AgentState) -> str:
    """After hydrate_context: route to resolve_target (update) or plan (create)."""
    if state.get("operation_mode") == "update":
        return "resolve_target"
    return "plan_v2"


def _route_after_hitl_select_target(state: AgentState) -> str:
    """After HITL_select_target: route to load_current_flow (update) or plan (create)."""
    if state.get("operation_mode") == "update":
        return "load_current_flow"
    return "plan_v2"


def _route_after_plan_approval_v2(state: AgentState) -> str:
    """If developer gave feedback → back to plan. If approved → define_patch_scope."""
    if state.get("developer_feedback"):
        return "plan_v2"
    return "define_patch_scope"


def _route_after_validate(state: AgentState) -> str:
    """Route based on validation result.

    ok              → preflight_validate_patch
    schema_mismatch → repair_schema (if budget allows)
    other/structural → hitl_review (escalate)
    """
    facts = state.get("facts") or {}
    validation = facts.get("validation") or {}
    repair = facts.get("repair") or {}
    budgets = facts.get("budgets") or {}

    if validation.get("ok"):
        return "preflight_validate_patch"

    failure_type = validation.get("failure_type") or "other"
    repair_count = repair.get("count", 0)
    max_repairs = budgets.get("max_schema_repairs_per_iter", 2)

    if failure_type == "schema_mismatch" and repair_count < max_repairs:
        return "repair_schema"

    # Other failure or budget exceeded → escalate to HITL
    return "hitl_review_v2"


def _route_after_repair_schema(state: AgentState) -> str:
    """After repair_schema: always retry compile_patch_ir exactly once."""
    return "compile_patch_ir"


def _route_after_preflight(state: AgentState) -> str:
    """Route based on preflight check result."""
    facts = state.get("facts") or {}
    preflight = facts.get("preflight") or {}
    if preflight.get("ok"):
        return "apply_patch"
    return "hitl_review_v2"


def _route_after_evaluate_v2(state: AgentState) -> str:
    """Route based on evaluate verdict."""
    facts = state.get("facts") or {}
    verdict_facts = facts.get("verdict") or {}
    if verdict_facts.get("verdict") == "done":
        return "hitl_review_v2"
    return "plan_v2"


def _route_after_hitl_review_v2(state: AgentState) -> str:
    """Route after HITL_review: accepted → END, iterate → plan."""
    if state.get("done"):
        return END
    return "plan_v2"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def make_default_capabilities(
    engine: ReasoningEngine,
    domains: list[DomainTools],
) -> list[DomainCapability]:
    """Build the default capability list for capability-first mode (M7.1, DD-066).

    Constructs a FlowiseCapability with the pre-built discover system prompt so
    callers (api.py lifespan) don't need to import private helpers.

    Returns:
        list containing one FlowiseCapability instance wrapping the first
        FloviseDomain found in domains (or domains[0] as fallback).
    """
    from flowise_dev_agent.agent.tools import FloviseDomain as _FloviseDomain

    flowise_domain = next(
        (d for d in domains if isinstance(d, _FloviseDomain)),
        domains[0],
    )
    system = _build_system_prompt(_DISCOVER_BASE, domains, "discover")
    return [FlowiseCapability(flowise_domain, engine, system)]


def build_graph(
    engine: ReasoningEngine,
    domains: list[DomainTools],
    checkpointer=None,
    client: "FlowiseClient | None" = None,
    pattern_store=None,
    capabilities: "list[DomainCapability] | None" = None,
    emit_event=None,
    topology_version: str = "v1",
):
    """Construct and compile the Flowise Builder co-pilot LangGraph.

    Args:
        engine:           Reasoning engine (LLM provider). Use create_engine(settings).
        domains:          List of DomainTools plugins. v1: [FloviseDomain(client)].
                          v2 (Workday): [FloviseDomain(client), WorkdayDomain(workday_client)].
        checkpointer:     LangGraph checkpointer for persistence + HITL support.
                          Defaults to MemorySaver (in-memory, suitable for development).
                          For production: use SqliteSaver or PostgresSaver.
                          See DESIGN_DECISIONS.md — DD-010.
        client:           Optional FlowiseClient passed to converge for pattern auto-save.
                          Required when pattern_store is provided (DD-031).
        pattern_store:    Optional PatternStore for pattern library (DD-031).
                          When provided, PatternDomain is auto-appended to domains,
                          and converge auto-saves patterns after DONE verdicts.
        capabilities:     Optional list of DomainCapability instances (DD-046).
                          When provided:
                            - discover node uses DomainCapability.discover() for structured
                              result routing (artifacts, facts, debug state fields).
                            - patch node switches to the M2 deterministic IR compiler path
                              (DD-051, DD-052): LLM emits Patch IR ops; compiler builds
                              flowData deterministically; WriteGuard enforces hash match.
                          When None (default), all behavior is identical to pre-refactor:
                            - discover uses legacy DomainTools merge path
                            - patch uses legacy LLM-driven full flowData generation
        emit_event:       Optional async callable. When provided, every node is wrapped
                          to emit lifecycle events (started/completed/failed/interrupted)
                          to the session_events table via EventLog.insert_event.
                          Pass None (default) to disable. See M9.2.
        topology_version: "v1" (default, 9-node legacy topology) or "v2" (M9.6
                          18-node CREATE+UPDATE topology with budgets and bounded retries).
                          Passing "v2" activates the new topology. All callers that do not
                          pass this parameter continue to use the v1 topology unchanged.

    Returns:
        Compiled LangGraph graph ready for ainvoke() / invoke().
    """
    if checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
        logger.info("Using MemorySaver checkpointer (in-memory, dev mode)")

    # Auto-inject PatternDomain when a pattern_store is provided (DD-031)
    if pattern_store is not None:
        from flowise_dev_agent.agent.tools import PatternDomain
        domains = list(domains) + [PatternDomain(pattern_store)]
        logger.info("PatternDomain injected into domains list")

    # -----------------------------------------------------------------------
    # M9.6: Topology v2 (18-node CREATE+UPDATE with budgets)
    # -----------------------------------------------------------------------
    if topology_version == "v2":
        return _build_graph_v2(
            engine=engine,
            domains=domains,
            checkpointer=checkpointer,
            client=client,
            pattern_store=pattern_store,
            capabilities=capabilities,
            emit_event=emit_event,
        )

    # -----------------------------------------------------------------------
    # Topology v1: original 9-node topology (unchanged — backward compatible)
    # -----------------------------------------------------------------------
    builder = StateGraph(AgentState)

    # Register all nodes
    # Select patch node implementation:
    #   capabilities=None → legacy LLM-driven full flowData path (unchanged)
    #   capabilities=[...] → M2 deterministic IR compiler path (DD-051, DD-052)
    if capabilities:
        patch_node = _make_patch_node_v2(engine, domains, capabilities)
    else:
        patch_node = _make_patch_node(engine, domains)

    # Extract TemplateStore from capabilities for planning hints (Milestone 2).
    _template_store: TemplateStore | None = None
    if capabilities:
        for _cap in capabilities:
            if hasattr(_cap, "knowledge") and hasattr(_cap.knowledge, "template_store"):
                _template_store = _cap.knowledge.template_store
                break

    # M9.2: wrap every node with lifecycle event emission when emit_event is provided.
    def _w(name: str, fn):
        if emit_event is None:
            return fn
        from flowise_dev_agent.persistence.hooks import wrap_node
        return wrap_node(name, fn, emit_event)

    builder.add_node("clarify",             _w("clarify",             _make_clarify_node(engine)))
    builder.add_node("discover",            _w("discover",            _make_discover_node(engine, domains, capabilities)))
    builder.add_node("check_credentials",   _w("check_credentials",   _make_check_credentials_node()))
    builder.add_node("plan",                _w("plan",                _make_plan_node(engine, domains, _template_store, pattern_store=pattern_store)))
    builder.add_node("human_plan_approval", _w("human_plan_approval", _make_human_plan_approval_node()))
    builder.add_node("patch",               _w("patch",               patch_node))
    builder.add_node("test",                _w("test",                _make_test_node(engine, domains)))
    builder.add_node("converge",            _w("converge",            _make_converge_node(engine, client=client, pattern_store=pattern_store, capabilities=capabilities)))
    builder.add_node("human_result_review", _w("human_result_review", _make_human_result_review_node()))

    # Fixed edges (always taken)
    builder.add_edge(START, "clarify")
    builder.add_edge("clarify", "discover")
    builder.add_edge("discover", "check_credentials")  # credential gate before plan
    builder.add_edge("check_credentials", "plan")
    builder.add_edge("plan", "human_plan_approval")
    builder.add_edge("patch", "test")
    builder.add_edge("test", "converge")

    # Conditional edges (routing decisions)
    builder.add_conditional_edges(
        "human_plan_approval",
        _route_after_plan_approval,
        {"patch": "patch", "plan": "plan"},
    )
    builder.add_conditional_edges(
        "converge",
        _route_after_converge,
        {"human_result_review": "human_result_review", "plan": "plan"},
    )
    builder.add_conditional_edges(
        "human_result_review",
        _route_after_result_review,
        {END: END, "plan": "plan"},
    )

    return builder.compile(checkpointer=checkpointer)


def _build_graph_v2(
    engine: ReasoningEngine,
    domains: list[DomainTools],
    checkpointer,
    client: "FlowiseClient | None" = None,
    pattern_store=None,
    capabilities: "list[DomainCapability] | None" = None,
):
    """Build the M9.6 18-node topology (CREATE + UPDATE modes, budgets, bounded retries).

    Node inventory (18 nodes):
      Phase A: classify_intent, hydrate_context
      Phase B: resolve_target, hitl_select_target   (UPDATE path)
      Phase C: load_current_flow, summarize_current_flow   (UPDATE path)
      Phase D: plan_v2, hitl_plan_v2, define_patch_scope, compile_patch_ir, compile_flow_data
      Phase E: validate, repair_schema
      Phase F: preflight_validate_patch, apply_patch, test_v2, evaluate, hitl_review_v2

    Routing:
      START → classify_intent → hydrate_context
        → (update) resolve_target → hitl_select_target
            → (update) load_current_flow → summarize_current_flow → plan_v2
            → (create) plan_v2
        → (create) plan_v2
      plan_v2 → hitl_plan_v2 → define_patch_scope → compile_patch_ir
        → compile_flow_data → validate
          → (ok) preflight_validate_patch
              → (ok) apply_patch → test_v2 → evaluate
                  → (done) hitl_review_v2 → (accepted) END
                                          → (iterate) plan_v2
                  → (iterate) plan_v2
              → (budget exceeded) hitl_review_v2
          → (schema_mismatch, budget ok) repair_schema → compile_patch_ir
          → (other/budget exceeded) hitl_review_v2

    See roadmap9_production_graph_runtime_hardening.md — Milestone 9.6.
    """
    logger.info("[BUILD_GRAPH_V2] building M9.6 18-node topology")

    # Extract TemplateStore from capabilities for planning hints
    _template_store: TemplateStore | None = None
    if capabilities:
        for _cap in capabilities:
            if hasattr(_cap, "knowledge") and hasattr(_cap.knowledge, "template_store"):
                _template_store = _cap.knowledge.template_store
                break

    builder = StateGraph(AgentState)

    # ---- Phase A ----
    builder.add_node("classify_intent",   _make_classify_intent_node(engine))
    builder.add_node("hydrate_context",   _make_hydrate_context_node(capabilities))

    # ---- Phase B (UPDATE only, skipped for CREATE) ----
    builder.add_node("resolve_target",     _make_resolve_target_node(domains))
    builder.add_node("hitl_select_target", _make_hitl_select_target_node())

    # ---- Phase C (UPDATE only) ----
    builder.add_node("load_current_flow",      _make_load_current_flow_node(domains))
    builder.add_node("summarize_current_flow", _make_summarize_current_flow_node())

    # ---- Phase D ----
    builder.add_node("plan_v2",            _make_plan_node(engine, domains, _template_store, pattern_store=pattern_store))
    builder.add_node("hitl_plan_v2",       _make_human_plan_approval_node())
    builder.add_node("define_patch_scope", _make_define_patch_scope_node(engine))
    builder.add_node("compile_patch_ir",   _make_compile_patch_ir_node(engine, capabilities))
    builder.add_node("compile_flow_data",  _make_compile_flow_data_node(capabilities, domains))

    # ---- Phase E ----
    builder.add_node("validate",      _make_validate_node())
    builder.add_node("repair_schema", _make_repair_schema_node(capabilities, domains))

    # ---- Phase F ----
    builder.add_node("preflight_validate_patch", _make_preflight_validate_patch_node())
    builder.add_node("apply_patch",    _make_apply_patch_node(domains, capabilities))
    builder.add_node("test_v2",        _make_test_node(engine, domains))
    builder.add_node("evaluate",       _make_evaluate_node(engine))
    builder.add_node("hitl_review_v2", _make_hitl_review_node())

    # ---- Fixed edges ----
    builder.add_edge(START, "classify_intent")
    builder.add_edge("classify_intent", "hydrate_context")

    # Phase B chain (UPDATE path enters from hydrate_context conditional)
    builder.add_edge("resolve_target", "hitl_select_target")

    # Phase C chain
    builder.add_edge("load_current_flow", "summarize_current_flow")
    builder.add_edge("summarize_current_flow", "plan_v2")

    # Phase D chain
    builder.add_edge("plan_v2", "hitl_plan_v2")
    builder.add_edge("define_patch_scope", "compile_patch_ir")
    builder.add_edge("compile_patch_ir", "compile_flow_data")
    builder.add_edge("compile_flow_data", "validate")

    # Phase F chain
    builder.add_edge("apply_patch", "test_v2")
    builder.add_edge("test_v2", "evaluate")

    # ---- Conditional edges ----

    # After hydrate_context: route by intent
    builder.add_conditional_edges(
        "hydrate_context",
        _route_after_hydrate_context_v2,
        {"resolve_target": "resolve_target", "plan_v2": "plan_v2"},
    )

    # After HITL_select_target: route by operation_mode
    builder.add_conditional_edges(
        "hitl_select_target",
        _route_after_hitl_select_target,
        {"load_current_flow": "load_current_flow", "plan_v2": "plan_v2"},
    )

    # After hitl_plan_v2: approved → define_patch_scope, feedback → plan_v2
    builder.add_conditional_edges(
        "hitl_plan_v2",
        _route_after_plan_approval_v2,
        {"define_patch_scope": "define_patch_scope", "plan_v2": "plan_v2"},
    )

    # After validate: ok → preflight, schema_mismatch (budget) → repair, other → hitl
    builder.add_conditional_edges(
        "validate",
        _route_after_validate,
        {
            "preflight_validate_patch": "preflight_validate_patch",
            "repair_schema": "repair_schema",
            "hitl_review_v2": "hitl_review_v2",
        },
    )

    # After repair_schema: retry compile_patch_ir once
    builder.add_conditional_edges(
        "repair_schema",
        _route_after_repair_schema,
        {"compile_patch_ir": "compile_patch_ir"},
    )

    # After preflight: ok → apply_patch, budget exceeded → hitl
    builder.add_conditional_edges(
        "preflight_validate_patch",
        _route_after_preflight,
        {"apply_patch": "apply_patch", "hitl_review_v2": "hitl_review_v2"},
    )

    # After evaluate: done → hitl_review_v2, iterate → plan_v2
    builder.add_conditional_edges(
        "evaluate",
        _route_after_evaluate_v2,
        {"hitl_review_v2": "hitl_review_v2", "plan_v2": "plan_v2"},
    )

    # After hitl_review_v2: accepted → END, iterate → plan_v2
    builder.add_conditional_edges(
        "hitl_review_v2",
        _route_after_hitl_review_v2,
        {END: END, "plan_v2": "plan_v2"},
    )

    return builder.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def create_agent(flowise_settings: Settings, reasoning_settings: ReasoningSettings):
    """Create the full agent from settings objects.

    Reads config from environment (via Settings.from_env() and
    ReasoningSettings.from_env()), creates the engine and client,
    and returns a compiled graph.

    Returns:
        (graph, flowise_client)
        The client is returned separately so it can be closed on shutdown.

    Example:
        from cursorwise.config import Settings
        from flowise_dev_agent.reasoning import ReasoningSettings
        from flowise_dev_agent.agent import create_agent

        graph, client = create_agent(
            Settings.from_env(),
            ReasoningSettings.from_env(),
        )
        try:
            result = await graph.ainvoke(
                {"requirement": "Build a customer support chatbot", ...},
                config={"configurable": {"thread_id": "session-001"}},
            )
        finally:
            await client.close()
    """
    from flowise_dev_agent.agent.tools import FloviseDomain

    engine = create_engine(reasoning_settings)
    client = FlowiseClient(flowise_settings)
    domains: list[DomainTools] = [FloviseDomain(client)]

    graph = build_graph(engine, domains)
    return graph, client
