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

Your job: use the available tools to gather EVERYTHING you need before planning.
This is read-only — no creates or updates.

WHAT TO GATHER:
1. Existing chatflows relevant to the requirement (list_chatflows → get_chatflow for relevant ones)
2. Node types for the planned flow pattern (get_node for every candidate node — never guess schemas)
3. Credentials already saved in Flowise (list_credentials)
4. Marketplace templates that might apply (list_marketplace_templates)

RULE: Call get_node for EVERY node type you plan to use. Input parameter names and baseClasses
vary significantly between nodes and cannot be assumed from the node's label.

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
                    if isinstance(_op, BindCredential) and not _op.credential_id:
                        _query = (_op.credential_type or "").strip()
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
        # Roadmap 6 M1: check FlowiseKnowledgeProvider snapshot first.
        # A targeted get_node API call is made ONLY for node types absent from
        # the local snapshot (repair-only — never fetched when snapshot has the node).
        # Repair events are accumulated and written to debug["flowise"]["knowledge_repair_events"].
        schema_cache: dict[str, dict] = {}
        _phase_d_repair_events: list[dict] = []   # populated only on cache miss
        _phase_d_debug: dict = {}                  # merged into final return's "debug" key

        new_node_names = {
            op.node_name for op in ops
            if isinstance(op, AddNode) and op.node_name
        }

        # M7.4: time Phase D (schema resolution) — runs even when new_node_names is empty
        async with MetricsCollector("patch_d") as m_d:
            if new_node_names:
                provider = flowise_cap.knowledge if flowise_cap else None
                node_store = provider.node_schemas if provider else None

                async def _api_fetcher(node_type: str) -> dict:
                    """Single targeted get_node API call — invoked ONLY on cache miss."""
                    _result = await execute_tool(
                        "get_node", {"name": node_type}, discover_executor
                    )
                    if isinstance(_result, ToolResult) and _result.ok and isinstance(_result.data, dict):
                        return _result.data
                    return {}

                for _name in new_node_names:
                    if node_store is not None:
                        # Fast path: local snapshot hit → zero API calls
                        # Slow path: cache miss → ONE targeted get_node call (repair)
                        _schema = await node_store.get_or_repair(
                            _name, _api_fetcher, repair_events_out=_phase_d_repair_events
                        )
                    else:
                        # capabilities=None legacy path — always calls API (unchanged behaviour)
                        _legacy = await execute_tool(
                            "get_node", {"name": _name}, discover_executor
                        )
                        _schema = (
                            _legacy.data
                            if isinstance(_legacy, ToolResult) and _legacy.ok and isinstance(_legacy.data, dict)
                            else None
                        )

                    if _schema:
                        schema_cache[_name] = _schema
                    else:
                        logger.warning("[PATCH v2] Schema unavailable for '%s' — AddNode will fail", _name)

                # Build debug update for repair events (written to state via return dict)
                if _phase_d_repair_events:
                    logger.info("[PATCH v2] Knowledge repair events: %d", len(_phase_d_repair_events))
                    _existing_events = state.get("debug", {}).get("flowise", {}).get(
                        "knowledge_repair_events", []
                    )
                    _phase_d_debug = {
                        "flowise": {
                            **state.get("debug", {}).get("flowise", {}),
                            "knowledge_repair_events": _existing_events + _phase_d_repair_events,
                        }
                    }

                m_d.cache_hits = len(new_node_names) - len(_phase_d_repair_events)
                m_d.repair_events = len(_phase_d_repair_events)

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
):
    """Construct and compile the Flowise Builder co-pilot LangGraph.

    Args:
        engine:        Reasoning engine (LLM provider). Use create_engine(settings).
        domains:       List of DomainTools plugins. v1: [FloviseDomain(client)].
                       v2 (Workday): [FloviseDomain(client), WorkdayDomain(workday_client)].
        checkpointer:  LangGraph checkpointer for persistence + HITL support.
                       Defaults to MemorySaver (in-memory, suitable for development).
                       For production: use SqliteSaver or PostgresSaver.
                       See DESIGN_DECISIONS.md — DD-010.
        client:        Optional FlowiseClient passed to converge for pattern auto-save.
                       Required when pattern_store is provided (DD-031).
        pattern_store: Optional PatternStore for pattern library (DD-031).
                       When provided, PatternDomain is auto-appended to domains,
                       and converge auto-saves patterns after DONE verdicts.
        capabilities:  Optional list of DomainCapability instances (DD-046).
                       When provided:
                         - discover node uses DomainCapability.discover() for structured
                           result routing (artifacts, facts, debug state fields).
                         - patch node switches to the M2 deterministic IR compiler path
                           (DD-051, DD-052): LLM emits Patch IR ops; compiler builds
                           flowData deterministically; WriteGuard enforces hash match.
                       When None (default), all behavior is identical to pre-refactor:
                         - discover uses legacy DomainTools merge path
                         - patch uses legacy LLM-driven full flowData generation

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

    builder.add_node("clarify",             _make_clarify_node(engine))
    builder.add_node("discover",            _make_discover_node(engine, domains, capabilities))
    builder.add_node("check_credentials",   _make_check_credentials_node())
    builder.add_node("plan",                _make_plan_node(engine, domains, _template_store, pattern_store=pattern_store))
    builder.add_node("human_plan_approval", _make_human_plan_approval_node())
    builder.add_node("patch",               patch_node)
    builder.add_node("test",                _make_test_node(engine, domains))
    builder.add_node("converge",            _make_converge_node(engine, client=client, pattern_store=pattern_store, capabilities=capabilities))
    builder.add_node("human_result_review", _make_human_result_review_node())

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
