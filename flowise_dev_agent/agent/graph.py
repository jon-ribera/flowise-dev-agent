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

import json
import logging
import re
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from flowise_dev_agent.agent.state import AgentState
from flowise_dev_agent.agent.tools import DomainTools, execute_tool, merge_context, merge_tools, result_to_str
from cursorwise.client import FlowiseClient
from cursorwise.config import Settings
from flowise_dev_agent.reasoning import Message, ReasoningEngine, ReasoningSettings, ToolDef, create_engine

logger = logging.getLogger("flowise_dev_agent.agent")

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

After completing the change, confirm:
- What was changed (brief)
- The chatflow_id of the updated/created flow
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
            developer_response: str = interrupt({
                "type": "clarification",
                "prompt": text,
                "requirement": state["requirement"],
                "iteration": 0,
            })
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
            raw_result = await execute_tool(tc.name, tc.arguments, executor)
            new_msgs.append(Message(
                role="tool_result",
                content=result_to_str(raw_result),
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


def _extract_chatflow_id(messages: list[Message]) -> str | None:
    """Scan recent tool results for a chatflow 'id' field.

    Used by the patch node to capture the chatflow_id when a new chatflow
    is created or when the existing id needs to be confirmed.
    """
    for msg in reversed(messages):
        if msg.role == "tool_result" and msg.content:
            try:
                data = json.loads(msg.content)
                if isinstance(data, dict) and "id" in data:
                    return str(data["id"])
            except (json.JSONDecodeError, TypeError):
                pass
    return None


# ---------------------------------------------------------------------------
# Node factories
# Each node is a closure over the engine + domains list.
# ---------------------------------------------------------------------------


def _make_discover_node(engine: ReasoningEngine, domains: list[DomainTools]):
    tool_defs, executor = merge_tools(domains, "discover")
    system = _build_system_prompt(_DISCOVER_BASE, domains, "discover")

    async def discover(state: AgentState) -> dict:
        """Phase 1: Read-only information gathering across all tool domains."""
        iteration = state.get("iteration", 0)
        logger.info("[DISCOVER] iteration=%d", iteration)

        user_content = f"My requirement:\n{state['requirement']}"
        if state.get("clarification"):
            user_content += f"\n\nClarifications provided:\n{state['clarification']}"
        if state.get("developer_feedback"):
            user_content += f"\n\nDeveloper feedback from previous iteration:\n{state['developer_feedback']}"

        user_msg = Message(role="user", content=user_content)
        # Discover runs with only the current user message — tool call responses
        # from list_nodes / list_marketplace_templates can be 500k+ tokens and must
        # not accumulate in state["messages"] for downstream phases to inherit.
        summary, new_msgs, in_tok, out_tok = await _react(engine, [user_msg], system, tool_defs, executor)

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

    return discover


def _make_check_credentials_node():
    def check_credentials(state: AgentState) -> dict:
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
            response: str = interrupt(
                {
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
            )
            # Store the developer's reply as feedback for the plan node.
            return {"developer_feedback": response}

        logger.info("[CHECK_CREDENTIALS] all credentials present — passing through")
        return {}

    return check_credentials


def _make_plan_node(engine: ReasoningEngine, domains: list[DomainTools]):
    system = _build_system_prompt(_PLAN_BASE, domains, "discover")  # plan uses discover context

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
        # Build a compact context from structured state fields — never use the raw
        # state["messages"] which may contain huge tool call blobs from discover.
        ctx: list[Message] = [
            Message(
                role="user",
                content=(
                    f"Requirement:\n{state['requirement']}\n\n"
                    f"Discovery summary:\n{state.get('discovery_summary') or '(none)'}"
                ),
            ),
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

        response = await engine.complete(
            messages=ctx + [user_msg],
            system=system,
            tools=None,  # No tool calls in the plan phase
        )
        plan_text = response.content or ""
        assistant_msg = Message(role="assistant", content=plan_text)

        return {
            "messages": [user_msg, assistant_msg],
            "plan": plan_text,
            "developer_feedback": None,  # consumed; clear it
            "total_input_tokens": response.input_tokens,
            "total_output_tokens": response.output_tokens,
        }

    return plan


def _make_human_plan_approval_node():
    def human_plan_approval(state: AgentState) -> dict:
        """INTERRUPT: surface plan to developer and wait for approval or feedback.

        The graph pauses here. The calling application receives the interrupt
        value, presents it to the developer, and resumes with their response
        via graph.invoke(Command(resume=<response>), config=...).

        Resume values:
          "approved" (or "yes", "ok", "looks good") → proceed to patch
          Any other string → treat as feedback, loop back to plan
        """
        logger.info("[HUMAN PLAN APPROVAL] waiting for developer input")

        developer_response: str = interrupt({
            "type": "plan_approval",
            "plan": state["plan"],
            "iteration": state.get("iteration", 0),
            "prompt": (
                "Review the plan above.\n"
                "Reply 'approved' to proceed with implementation, "
                "or describe what needs to change."
            ),
        })

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
                ),
            ),
            Message(role="assistant", content=f"Approved plan:\n{state.get('plan') or ''}"),
        ]
        _, new_msgs, in_tok, out_tok = await _react(
            engine,
            ctx + [user_msg],
            system,
            tool_defs,
            executor,
        )

        # Try to pick up the chatflow_id from tool results (e.g. after create_chatflow)
        chatflow_id = state.get("chatflow_id") or _extract_chatflow_id(new_msgs)

        return {
            "messages": [user_msg] + new_msgs,
            "chatflow_id": chatflow_id,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
        }

    return patch


def _make_test_node(engine: ReasoningEngine, domains: list[DomainTools]):
    tool_defs, executor = merge_tools(domains, "test")
    system = _build_system_prompt(_TEST_BASE, domains, "test")

    async def test(state: AgentState) -> dict:
        """Phase 4: Run happy-path and edge-case predictions."""
        iteration = state.get("iteration", 0)
        logger.info("[TEST] iteration=%d chatflow_id=%s", iteration, state.get("chatflow_id"))

        chatflow_id = state.get("chatflow_id", "unknown — extract from recent tool results")
        trials = state.get("test_trials", 1)
        trials_instruction = (
            f"Run each test {trials} time(s) with different sessionIds. "
            f"A test PASSES only if ALL {trials} trial(s) pass (pass^{trials} reliability). "
            "Report each trial result separately."
            if trials > 1
            else "Run each test once."
        )
        user_msg = Message(
            role="user",
            content=(
                f"Chatflow to test: {chatflow_id}\n\n"
                "Run the happy-path test and the edge-case test. "
                "Use unique sessionIds in override_config for both. "
                f"{trials_instruction} "
                "Report PASS/FAIL for each."
            ),
        )

        # Test only needs the chatflow_id (already in user_msg). No prior tool
        # call history required — _react will make its own create_prediction calls.
        text, new_msgs, in_tok, out_tok = await _react(
            engine,
            [user_msg],
            system,
            tool_defs,
            executor,
        )

        return {
            "messages": [user_msg] + new_msgs,
            "test_results": text,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
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


def _make_converge_node(
    engine: ReasoningEngine,
    client: "FlowiseClient | None" = None,
    pattern_store=None,
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
        response = await engine.complete(
            messages=ctx + [user_msg],
            system=_CONVERGE_BASE,
            tools=None,
        )

        raw_verdict = (response.content or "ITERATE\nCategory: INCOMPLETE\nReason: no response from LLM").strip()
        verdict_dict = _parse_converge_verdict(raw_verdict)
        is_done = verdict_dict["verdict"] == "DONE"

        assistant_msg = Message(role="assistant", content=raw_verdict)
        logger.info("[CONVERGE] verdict=%r done=%s", verdict_dict, is_done)

        # Auto-save pattern when DONE (DD-031)
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
                    await pattern_store.save_pattern(
                        name=name,
                        requirement_text=requirement,
                        flow_data=flow_data,
                        chatflow_id=chatflow_id,
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
        }

    return converge


def _make_human_result_review_node():
    def human_result_review(state: AgentState) -> dict:
        """INTERRUPT: surface test results to developer. Accept or iterate.

        Resume values:
          "accepted" (or "done", "yes", "looks good") → END
          Any other string → treat as feedback for next iteration, loop to plan
        """
        logger.info("[HUMAN RESULT REVIEW] waiting for developer input")

        developer_response: str = interrupt({
            "type": "result_review",
            "test_results": state.get("test_results"),
            "chatflow_id": state.get("chatflow_id"),
            "iteration": state.get("iteration", 0),
            "prompt": (
                "The agent believes the chatflow is ready (Definition of Done met).\n"
                "Review the test results above.\n"
                "Reply 'accepted' to finish, or describe what to change for another iteration."
            ),
        })

        accepted = developer_response.strip().lower() in (
            "accepted", "accept", "done", "yes", "y", "looks good", "lgtm", "ship it"
        )

        logger.info("[HUMAN RESULT REVIEW] accepted=%s", accepted)

        if accepted:
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


def build_graph(
    engine: ReasoningEngine,
    domains: list[DomainTools],
    checkpointer=None,
    client: "FlowiseClient | None" = None,
    pattern_store=None,
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
    builder.add_node("clarify",             _make_clarify_node(engine))
    builder.add_node("discover",            _make_discover_node(engine, domains))
    builder.add_node("check_credentials",   _make_check_credentials_node())
    builder.add_node("plan",                _make_plan_node(engine, domains))
    builder.add_node("human_plan_approval", _make_human_plan_approval_node())
    builder.add_node("patch",               _make_patch_node(engine, domains))
    builder.add_node("test",                _make_test_node(engine, domains))
    builder.add_node("converge",            _make_converge_node(engine, client=client, pattern_store=pattern_store))
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
