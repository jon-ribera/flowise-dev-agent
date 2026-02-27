---
name: flowise_builder
description: |
  Build and update Flowise chatflows using deterministic Patch IR ops compiled by the agent
  graph. Use when the user wants to create a chatbot, add memory to a flow, build a RAG pipeline,
  connect custom tools, fix a credential error, or modify any Flowise node composition — even if
  they don't say "Flowise" or "chatflow" directly. Triggers on: build a chatbot, add GPT-4o,
  update the flow, wire up memory, create a RAG pipeline, or fix API key errors.
version: 2.0.0
---

# Flowise Builder Skill

**Domain**: flowise
**MCP Source**: native — 51 tools via `flowise_dev_agent.mcp`, full Flowise REST API

> v2.0.0: Patch Context fully rewritten for Patch IR ops. The LLM no longer writes raw flowData.
> The deterministic compiler (`compile_patch_ir` node) builds flowData from the ops you emit.

---

## Discover Context

Your goal: gather enough state to produce a correct PlanContract. Missing information here causes
failures in Patch. Work through these steps in order.

### Step 1 — Classify intent and mode

Determine `operation_mode` before anything else:

- **CREATE**: user wants a new chatflow. No `target_chatflow_id` needed.
- **UPDATE**: user wants to modify an existing flow. Identify `target_chatflow_id`.

If UPDATE: call `get_chatflow(chatflow_id)` immediately. Parse `flowData` as JSON to read
current nodes and edges. You need the existing state to plan safe ops — you cannot plan
updates without knowing what's already there.

### Step 2 — Search patterns first (CREATE mode only)

Before listing nodes or calling get_node, call `search_patterns` with 3–5 key terms from
the requirement. Pattern reuse skips the node-schema discovery cycle entirely and produces
higher-confidence results.

- Match found with `success_count ≥ 2` → use as the base; note it in the plan; call `use_pattern(id)`.
- No match → proceed with Steps 3–5.

Patterns are NOT seeded in UPDATE mode — they only apply to new flow creation.

### Step 3 — Read node schemas

For every node type you plan to add, call `get_node(name)`. Never guess anchor names or param keys.

What to extract from `get_node`:
- `inputAnchors`: connection points that accept other nodes — use for Connect ops.
- `inputParams`: configurable parameters — use for SetParam ops; check `credentialNames` here.
- `outputAnchors`: what the node produces downstream.
- `baseClasses`: the types this node satisfies (used in anchor matching).
- `version`: must match the version field in the compiled node.

### Step 4 — Resolve credentials

Call `list_credentials`. For every node with a `credentialNames` entry in its `inputParams`,
verify a matching credential exists. Unresolved credentials cause runtime auth failures — the
compile step succeeds but the flow fails silently at prediction time.

Common credential types:
- `openAIApi` — ChatOpenAI, OpenAI Embeddings
- `anthropicApi` — ChatAnthropic
- `pineconeApi` — Pinecone Vector Store

At the end of discovery, output exactly one of these two blocks (the graph interrupt reads this):

```
CREDENTIALS_STATUS: OK
```

or:

```
CREDENTIALS_STATUS: MISSING
MISSING_TYPES: openAIApi, pineconeApi
```

`MISSING_TYPES` must be the credential type names from `get_node`, not credential display names or IDs.

### Step 5 — Check node category restrictions

- Sequential Agents / Multi Agents / Agent Flows categories → AGENTFLOW type only.
  Do not mix these into CHATFLOW. Check `chatflow_type` on existing flows.
- Tool-calling agents (`toolAgent`, `conversationalAgent`) require function-calling models:
  ChatOpenAI, ChatAnthropic, ChatMistral only.

<output_format>
Return a plan summary (2–4 sentences) followed by a JSON PlanContract code block labeled "plan_v2".

```plan_v2
{
  "intent": "<one sentence — what will be built or changed>",
  "operation_mode": "create" | "update",
  "target_chatflow_id": "<chatflow ID for UPDATE, null for CREATE>",
  "pattern_id": <int or null>,
  "nodes": [
    {"type": "<node_name>", "role": "<what it does in this flow>"}
  ],
  "credentials": [
    {"name": "<display name>", "type": "<credentialName>", "status": "resolved" | "needed"}
  ],
  "success_criteria": [
    "<testable criterion 1>",
    "<testable criterion 2>"
  ]
}
```

End with:
CREDENTIALS_STATUS: OK
(or CREDENTIALS_STATUS: MISSING block)
</output_format>

---

## Patch Context

The compiler (`compile_patch_ir`) builds `flowData` deterministically from the ops you emit.
**You do not write flowData JSON.** You emit a list of Patch IR ops; the compiler handles
all node data construction, anchor ID formatting, and edge wiring.

<constraints>
Always:
- Read the PlanContract from Discover before emitting any ops — it specifies operation_mode,
  target_chatflow_id, and which nodes and credentials are needed.
- Emit ops in dependency order: AddNode before SetParam, SetParam before Connect,
  Connect before BindCredential. The compiler executes ops sequentially — a Connect op
  that references a node_id not yet created will fail with a dangling reference error.
- Read `inputAnchors` and `outputAnchors` from `get_node` for every Connect op.
  The `target_anchor` must match an `inputAnchor.name` exactly — do not guess it.

Never:
- Emit raw flowData JSON. The compiler owns flowData construction — injecting partial or
  full flowData alongside Patch IR ops produces undefined behavior.
- Reuse node IDs across separate Patch phases — IDs are scoped to the current compilation.
- Emit a Connect op whose source_id or target_id was not created by a preceding AddNode op
  (or already exists in the flow for UPDATE mode).
</constraints>

### Patch IR op reference

<output_format>
Emit a JSON array of Patch IR ops. The array is the entire output — no prose, no explanation.

Op schemas:

```json
[
  {"op_type": "AddNode",        "node_name": "<flowise node type>", "node_id": "<unique id>"},
  {"op_type": "SetParam",       "node_id": "<id>", "param": "<inputParam.name>", "value": <any>},
  {"op_type": "Connect",        "source_id": "<id>", "target_id": "<id>", "target_anchor": "<inputAnchor.name>"},
  {"op_type": "BindCredential", "node_id": "<id>", "credential_id": "<resolved credential id>"}
]
```

Example — simple conversation flow (CREATE):

```json
[
  {"op_type": "AddNode",        "node_name": "chatOpenAI",        "node_id": "chatOpenAI_0"},
  {"op_type": "AddNode",        "node_name": "bufferMemory",      "node_id": "bufferMemory_0"},
  {"op_type": "AddNode",        "node_name": "conversationChain", "node_id": "conversationChain_0"},
  {"op_type": "SetParam",       "node_id": "chatOpenAI_0",        "param": "modelName",   "value": "gpt-4o"},
  {"op_type": "SetParam",       "node_id": "bufferMemory_0",      "param": "sessionId",   "value": ""},
  {"op_type": "Connect",        "source_id": "chatOpenAI_0",      "target_id": "conversationChain_0", "target_anchor": "model"},
  {"op_type": "Connect",        "source_id": "bufferMemory_0",    "target_id": "conversationChain_0", "target_anchor": "memory"},
  {"op_type": "BindCredential", "node_id": "chatOpenAI_0",        "credential_id": "<openai-cred-id>"}
]
```

Why this order matters: `Connect` references `chatOpenAI_0` and `bufferMemory_0` — both must be
created by prior `AddNode` ops. `BindCredential` is last because it depends on the node existing.
</output_format>

### Flow patterns (ops summary)

**Simple conversation** (CREATE):
```
AddNode(chatOpenAI_0) + AddNode(bufferMemory_0) + AddNode(conversationChain_0)
→ SetParam(chatOpenAI_0, modelName, "gpt-4o")
→ Connect(chatOpenAI_0 → conversationChain_0.model)
→ Connect(bufferMemory_0 → conversationChain_0.memory)
→ BindCredential(chatOpenAI_0, <cred_id>)
```

**RAG pipeline** (CREATE):
```
AddNode(chatOpenAI_0) + AddNode(openAIEmbeddings_0) + AddNode(memoryVectorStore_0)
  + AddNode(plainText_0) + AddNode(conversationalRetrievalQAChain_0)
→ SetParam(plainText_0, text, "<content>")
→ Connect(openAIEmbeddings_0 → memoryVectorStore_0.embeddings)
→ Connect(plainText_0 → memoryVectorStore_0.document)
→ Connect(chatOpenAI_0 → conversationalRetrievalQAChain_0.model)
→ Connect(memoryVectorStore_0 → conversationalRetrievalQAChain_0.vectorStoreRetriever)
→ BindCredential(chatOpenAI_0, <cred_id>) + BindCredential(openAIEmbeddings_0, <cred_id>)
```

RAG constraint: every VectorStore MUST have a DocumentLoader connected to its `document` anchor.
Without a document source, Flowise returns "Expected a Runnable" (HTTP 500) on every prediction.

**Tool agent** (CREATE):
```
AddNode(chatOpenAI_0) + AddNode(bufferMemory_0) + AddNode(toolAgent_0)
  + AddNode(customTool_0)
→ SetParam(chatOpenAI_0, modelName, "gpt-4o")
→ Connect(chatOpenAI_0 → toolAgent_0.model)
→ Connect(bufferMemory_0 → toolAgent_0.memory)
→ Connect(customTool_0 → toolAgent_0.tools)
→ BindCredential(chatOpenAI_0, <cred_id>)
```

Tool agents require function-calling models (ChatOpenAI, ChatAnthropic, ChatMistral).

**UPDATE mode** — emit only the delta ops:
```
AddNode(bufferMemory_0)                         ← new node only
→ Connect(bufferMemory_0 → conversationChain_0.memory)  ← wire to existing node
```
Do not re-emit AddNode for nodes already in the flow.

**AGENTFLOW** — use when requirement needs agent-to-agent orchestration:
- Set chatflow_type AGENTFLOW in the plan
- Use Sequential Agents / Multi Agents category nodes only (seqStart, seqEnd, supervisor, worker)
- Cannot mix AGENTFLOW and CHATFLOW node categories

---

## Test Context

The graph dispatches predictions before you receive this context. You will be given raw API
responses for happy-path and edge-case trials. **Your role is evaluation only — do not call
any tools.**

### Evaluation criteria

For each trial response, assess:
1. Did the response address the input meaningfully? (not empty, not an error trace)
2. Does the response satisfy the SUCCESS_CRITERIA from the PlanContract?
3. Is the response free of Flowise runtime error strings (HTTP 500, "Expected a Runnable",
   "API key missing", etc.)?

### Verdict rules

- **DONE**: All trials PASS and all SUCCESS_CRITERIA are met → emit DONE verdict.
- **ITERATE**: Any trial FAILS or a SUCCESS_CRITERION is not met → emit ITERATE verdict
  with a 1–2 sentence diagnosis of the likely root cause.

<output_format>
Report format (one block per trial, then final verdict):

Trial 1 (happy-path):
  Input: "<the question>"
  Response: "<full response or first 300 chars>"
  Status: PASS | FAIL
  Notes: "<optional — what specifically failed or succeeded>"

Trial 2 (edge-case):
  Input: "<the question>"
  Response: "<full response or first 300 chars>"
  Status: PASS | FAIL
  Notes: "<optional>"

RESULT: HAPPY PATH [PASS/FAIL] | EDGE CASE [PASS/FAIL]
VERDICT: DONE | ITERATE
DIAGNOSIS: <if ITERATE — one sentence on the most likely root cause>
</output_format>

### RAG post-patch reminder

For RAG flows: the graph calls `upsert_vector` automatically after patching. If the happy-path
trial returns empty results, the likely cause is a credential binding failure on the embeddings
node (not an upsert issue).

---

## Error Reference

| Error | Root Cause | Fix in Patch IR terms |
|---|---|---|
| `nodes is not iterable` (HTTP 500) | Compiler received empty flowData | Internal compiler error — check AddNode ops have valid `node_name` |
| `Cannot read properties of undefined (reading 'find')` | Missing `inputAnchors` in compiled node | `node_name` in AddNode does not match a valid Flowise node type — verify with `get_node` |
| `NOT NULL constraint failed: tool.color` | customTool missing color | Add `SetParam(customTool_0, color, "#4CAF50")` |
| `"[object Object]" is not valid JSON` | openAIAssistant `details` as dict | SetParam value must be a JSON string: `"{\"assistantId\": \"asst_...\"}"` |
| `OPENAI_API_KEY environment variable is missing` | Credential not bound | Emit `BindCredential` op — the compiler sets both required credential fields |
| `Ending node must be either a Chain or Agent` | No terminal node in flow | Ensure ConversationChain, ToolAgent, or equivalent is the last node |
| `Expected a Runnable` (RAG, HTTP 500) | VectorStore has no DocumentLoader | Add `AddNode(plainText_0)` + `Connect(plainText_0 → vectorStore.document)` |
| Empty prediction response | Embeddings credential unbound | Add `BindCredential` op for the embeddings node |
| `No vector node found` on upsert | Flow has no VectorStore | Only call upsert on flows with a VectorStore node |
| Dangling reference in Connect | node_id in Connect not in AddNode | Check op ordering — AddNode must precede all Connect ops referencing that node |

---

## Changelog

### 2.0.0 (2026-02-24)
- Complete rewrite of Patch Context for Patch IR ops (AddNode/SetParam/Connect/BindCredential)
- Added PlanContract `<output_format>` spec to Discover Context
- Added CREATE vs UPDATE mode guidance throughout
- Removed raw flowData construction rules (Rules 1–8) — compiler handles this now
- Removed Change Summary requirement (Rule 4) — compiler owns the patch transaction
- Added pattern search step (Step 2) with UPDATE mode guard (M9.9)
- Added op ordering explanation with WHY reasoning
- Applied WHY-based rewrites throughout; removed ALL-CAPS mandates
- Extracted Node Quick Reference into Error Reference section
- Added YAML frontmatter with triggering description
- Rewrote Test Context RESULT/VERDICT format to include DONE/ITERATE

### 1.0.0 (initial)
- Original 15-rule LLM-driven patch rules (raw flowData construction)
- Rules 1–15 covering read-before-write, credential binding, change summary
