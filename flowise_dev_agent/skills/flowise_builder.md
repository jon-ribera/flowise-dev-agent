# Flowise Builder Skill

**Domain**: flowise
**Version**: 1.0.0
**MCP Source**: [jon-ribera/cursorwise](https://github.com/jon-ribera/cursorwise) — 50 tools, full Flowise REST API

---

## Overview

This skill provides domain-specific knowledge for the Flowise Builder co-pilot.
It covers chatflow discovery, construction, testing, and the non-negotiable rules
for building chatflows programmatically via the Cursorwise MCP.

The agent uses this skill to inject phase-specific context into its system prompts.

---

## Discover Context

FLOWISE DISCOVERY RULES:

Your goal is to gather everything needed to write a correct, working plan.
Do not skip steps — missing information here causes failures in Patch.

### What to gather (in order)

1. EXISTING CHATFLOWS
   Call `list_chatflows` to see all flows. For any flow relevant to the requirement,
   call `get_chatflow(chatflow_id)` and parse its `flowData` (nodes, edges, prompts).
   Note: `flowData` is a JSON string — parse it to inspect nodes and edges.

2. NODE SCHEMAS
   For every node type you plan to use, call `get_node(name)`.
   Do NOT assume input parameter names or baseClasses from the node label.
   The schemas differ significantly between node types. Key fields to check:
   - `inputAnchors`: what the node accepts as inputs (name + accepted baseClass)
   - `outputAnchors`: what the node produces (name + baseClasses)
   - `inputs`: configurable parameters (including credential requirements)
   - `baseClasses`: what this node produces downstream

3. CREDENTIALS
   Call `list_credentials`. For every credential-bearing node in your plan,
   verify a matching credential exists. The `credentialName` field must match:
   - `openAIApi` for ChatOpenAI, OpenAI Embeddings
   - `anthropicApi` for ChatAnthropic
   - `pineconeApi` for Pinecone Vector Store
   - (use get_node to verify exact credential type required)

4. MARKETPLACE TEMPLATES
   Call `list_marketplace_templates`. If a template covers the requirement,
   use its `flowData` as a starting point rather than building from scratch.

### Required: Credential Status Block
At the very end of your discovery summary, always output EXACTLY one of these two blocks
(the system reads this to decide whether to pause and ask the developer):

If all required credentials exist:
```
CREDENTIALS_STATUS: OK
```

If any required credentials are missing:
```
CREDENTIALS_STATUS: MISSING
MISSING_TYPES: openAIApi, anthropicApi
```

`MISSING_TYPES` must be a comma-separated list of the credential type names needed
(e.g., `openAIApi`, `anthropicApi`, `pineconeApi`). Do NOT include credential names
or IDs — only the type names from `get_node(name).inputs[].credentialNames`.

### Node category restrictions
- Sequential Agents / Agent Flows / Multi Agents categories → AGENTFLOW ONLY.
  Do not use these in Chatflows. Check `get_chatflow` to verify the flow type.
- Tool-calling agents (toolAgent, conversationalAgent) require function-calling
  models ONLY: ChatOpenAI, ChatAnthropic, ChatMistral.

---

## Patch Context

FLOWISE PATCH RULES — ALL NON-NEGOTIABLE:

### Rule 1: Read Before Write
Always call `get_chatflow(chatflow_id)` and parse the `flowData` JSON
before calling `update_chatflow`. Never overwrite blindly.

### Rule 2: One Change Per Iteration
Choose exactly ONE of:
- Add one node (+ its connecting edges)
- Edit one prompt field
- Rewire one edge
Do not combine changes. If the plan requires multiple changes, execute them
in separate iterations.

### Rule 3: Credential Binding (most common failure)
Every credential-bearing node MUST have the credential ID in TWO places:
```json
{
  "data": {
    "inputs": { "credential": "<credential_id>" },
    "credential": "<credential_id>"
  }
}
```
Setting ONLY `data.inputs.credential` causes "API key missing" at runtime.
Setting ONLY `data.credential` also fails. BOTH are required.

### Rule 4: Change Summary (required before every update_chatflow)
Print this summary before calling update_chatflow:

```
NODES ADDED:    [nodeId] label="..." name="..."
NODES REMOVED:  [nodeId] label="..." name="..."
NODES MODIFIED: [nodeId] fields changed: [fieldName, ...]
EDGES ADDED:    sourceNodeId → targetNodeId (inputName)
EDGES REMOVED:  sourceNodeId → targetNodeId (inputName)
PROMPTS:        [nodeId] field="fieldName"
                BEFORE: "<first 200 chars>"
                AFTER:  "<first 200 chars>"
```

### Rule 5: flow_data Minimums
- Minimum valid flow_data: `{"nodes":[],"edges":[]}`  — never bare `{}`
- All node IDs in edges must match node IDs in nodes array
- Preserve existing node IDs across iterations

### Rule 6: Edge Handle Format
Source handle: `{nodeId}-output-{nodeName}-{baseClasses joined by |}`
Target handle: `{nodeId}-input-{inputName}-{acceptedBaseClass}`

Use `get_node` to get exact baseClasses and input names. Do not construct
these handles by guessing — they must match exactly.

### Rule 7: Chatflow Patterns (choose one)
- Simple Conversation: ChatModel + BufferMemory + ConversationChain
- Tool Agent: ChatModel + BufferMemory + CustomTool(s) + ToolAgent
  (requires function-calling model)
- RAG: ChatModel + VectorStore + Embeddings + **DocumentLoader** + Retriever + ConversationalRetrievalQAChain

**RAG RUNTIME CONSTRAINT**: Every VectorStore node (`memoryVectorStore`, `pinecone`, `faiss`,
etc.) MUST have a DocumentLoader node (e.g. `plainText`, `textFile`, `pdfFile`, `cheerioWebScraper`)
wired to its `document` input anchor. Without a document source the VectorStore cannot initialize
and Flowise returns "Expected a Runnable" (HTTP 500) on every prediction. Always include a
DocumentLoader when planning any RAG flow.

### Rule 8: Node Data Structure — CRITICAL (missing fields cause HTTP 500)

Every node in `flowData.nodes[].data` MUST include ALL of these keys:

| Key | What it is | How to populate |
|---|---|---|
| `inputAnchors` | Node-to-node connection points | Inputs from `get_node` where `type` is a class name (BaseChatModel, BaseMemory, BaseCache, Moderation, etc.) |
| `inputParams` | Configurable parameters | Inputs from `get_node` where `type` is a primitive (string, number, boolean, credential, asyncOptions, options, json) |
| `outputs` | Output routing (usually empty) | Always `{}` for single-output nodes |
| `inputs` | Configured values | Dict with ALL param names as keys, connected anchors use `"{{nodeId.data.instance}}"`, unset optional fields use `""` |

**Splitting rule**: An input is an `inputAnchor` if its `type` starts with uppercase (class name). It is an `inputParam` if its `type` is lowercase.

**ID field**: Each entry in `inputAnchors` and `inputParams` must have:
`"id": "{nodeId}-input-{name}-{type}"`

**Missing `inputAnchors` causes**: `TypeError: Cannot read properties of undefined (reading 'find')` — HTTP 500 on every prediction call.

**Node version**: Use the `version` returned by `get_node`. Use the `baseClasses` from `get_node` verbatim for `outputAnchors[i].id` (joined by `|`).

**Before every write**: Call `validate_flow_data(flow_data_str)` with the complete flowData JSON string. Fix ALL reported errors before calling `create_chatflow` or `update_chatflow`. Never write invalid flowData to Flowise.

Example correct node data (conversationChain_0):
```json
{
  "id": "conversationChain_0",
  "name": "conversationChain",
  "version": 3,
  "inputAnchors": [
    {"label": "Chat Model", "name": "model", "type": "BaseChatModel",
     "id": "conversationChain_0-input-model-BaseChatModel"},
    {"label": "Memory", "name": "memory", "type": "BaseMemory",
     "id": "conversationChain_0-input-memory-BaseMemory"}
  ],
  "inputParams": [
    {"label": "System Message", "name": "systemMessagePrompt", "type": "string",
     "optional": true, "additionalParams": true,
     "id": "conversationChain_0-input-systemMessagePrompt-string"}
  ],
  "inputs": {
    "model": "{{chatOpenAI_0.data.instance}}",
    "memory": "{{bufferMemory_0.data.instance}}",
    "chatPromptTemplate": "",
    "inputModeration": "",
    "systemMessagePrompt": "You are a helpful assistant."
  },
  "outputAnchors": [
    {"id": "conversationChain_0-output-conversationChain-ConversationChain|LLMChain|BaseChain|Runnable",
     "name": "conversationChain", "label": "ConversationChain",
     "type": "ConversationChain | LLMChain | BaseChain | Runnable"}
  ],
  "outputs": {}
}
```

### Rule 9: Text Splitters (RAG flows only)

Text splitters are **only needed** in flows that load external documents (URLs, PDFs, files) into a vector store. **Never add a text splitter to a simple conversation chain.**

**When to use**: Any flow with a DocumentLoader (Cheerio, Spider, PDF Loader, etc.) that feeds a VectorStore.

**Available types** — always call `get_node(name)` to verify the exact inputAnchors before connecting:

| Node name | Best for |
|---|---|
| `recursiveCharacterTextSplitter` | Default choice — general text, HTML, plain text, code |
| `htmlToMarkdownTextSplitter` | Web content from Cheerio or Spider web scrapers |
| `characterTextSplitter` | Simple splits with a known separator |
| `markdownTextSplitter` | Markdown documents |
| `tokenTextSplitter` | Token-exact splits when context window size matters |

**Connection pattern** — text splitters typically connect to the Document Loader, not directly to the vector store:
```
[TextSplitter] → [DocumentLoader].textSplitter (inputAnchor)
[DocumentLoader] → [VectorStore].document (inputAnchor)
```
Always verify with `get_node` which inputAnchors on the loader and vector store accept `TextSplitter`.

**Key parameters**:
- `chunkSize`: 1000–2000 for most content (default 1000)
- `chunkOverlap`: 10–20% of chunkSize (default 200)
- Web content (Cheerio/Spider): use `chunkSize: 2000`, `chunkOverlap: 200`
- Code: use `codeTextSplitter` and set `language` to the source language

### Rule 10: AGENTFLOW Pattern (Sequential / Multi-Agent)

Use AGENTFLOW **only** when the requirement explicitly needs agent-to-agent orchestration
(supervisor directing workers, sequential hand-offs between specialized agents, etc.).
**Do not use for single-agent chatflows** — ConversationChain or ToolAgent is simpler and preferred.

Key differences from CHATFLOW:
- Set `chatflow_type: "AGENTFLOW"` in `create_chatflow`
- Use nodes from **"Sequential Agents"** and **"Multi Agents"** categories ONLY
- These node categories **cannot** be mixed into CHATFLOW flows
- Call `list_nodes` and filter by `category` to see available AGENTFLOW nodes

Common AGENTFLOW nodes:

| Node | Category | Role |
|---|---|---|
| `seqStart` | Sequential Agents | Entry point — starts the agent chain |
| `seqEnd` | Sequential Agents | Terminal node — ends the chain |
| `supervisor` | Multi Agents | Orchestrates multiple worker agents |
| `worker` | Multi Agents | Individual agent with its own tools |

Typical pattern:
```
seqStart → supervisor → worker_1
                      → worker_2
                      → seqEnd
```

Always call `get_node` on each AGENTFLOW node type before building — their inputAnchors
and outputAnchors differ from standard Chatflow nodes.

### Rule 11: RAG — Upsert Before Query

For any RAG flow with a VectorStore, always upsert documents BEFORE testing predictions.
A new VectorStore is empty — queries return empty results until data is loaded.

**Upsert pattern**:
1. After creating or modifying the chatflow, call `upsert_vector(chatflow_id)` to load documents
2. Verify upsert succeeded (check response for document count or success status)
3. Then run `create_prediction` to test retrieval

**When to upsert**:
- After creating a new RAG chatflow
- After changing the DocumentLoader source URL/file
- After changing chunk size or embeddings model
- Any time you suspect the vector store is stale

**Error patterns**:
- `"No vector node found"` → the chatflow has no VectorStore node (wrong flow type, skip upsert)
- Empty prediction response after upsert → check embeddings model credential binding

### Rule 12: OpenAI Assistant Node

The `openAIAssistant` node wraps the OpenAI Assistants API. It requires:

- `details` field MUST be a JSON string, not a nested object:
  ```json
  {"details": "{\"assistantId\": \"asst_...\"}"}
  ```
  Sending `details` as a dict causes `"[object Object]" is not valid JSON`.
- The assistant must already exist in your OpenAI account.
  Use `get_node("openAIAssistant")` to verify the exact `inputs` schema before building.
- Credential: `openAIApi` — bind at BOTH `data.credential` AND `data.inputs.credential`.

**When to use**: The requirement explicitly asks for OpenAI Assistants (file search,
code interpreter, or a pre-configured assistant personality). For general conversation,
use `conversationChain` + `chatOpenAI` instead (simpler, cheaper).

### Rule 13: Custom Tool Node

Custom tools let agents call external APIs. Required fields:

- `color`: MUST be a hex color string (e.g. `"#4CAF50"`).
  Missing color causes `NOT NULL constraint failed: tool.color` (HTTP 500).
- `schema`: JSON Schema string describing the tool's input parameters.
- `func`: JavaScript function body that calls the external API.

**Example node data**:
```json
{
  "name": "getWeather",
  "description": "Get current weather for a city",
  "color": "#4CAF50",
  "schema": "{\"type\":\"object\",\"properties\":{\"city\":{\"type\":\"string\"}},\"required\":[\"city\"]}",
  "func": "const resp = await fetch(`https://api.weather.com/v1/${city}`); return resp.json();"
}
```

Call `get_node("customTool")` to verify exact schema before building.

### Rule 14: Pattern Library — Reuse Before Building

At the start of every Discover phase, call `search_patterns(keywords)` with
3–5 key terms from the requirement before doing any other discovery.

**Why**: Patterns are proven working flowData from past successful sessions.
Reusing a pattern skips the list_nodes/get_node/validate cycle and produces
a higher-confidence result on the first iteration.

**Decision tree**:
1. `search_patterns("customer support GPT-4o memory")` → returns match
2. If `success_count ≥ 2`: strongly prefer this pattern; note it in the plan
3. Call `use_pattern(id)` to record reuse
4. In Patch: use the pattern's `flow_data` as the base; modify only what differs
5. If no match: proceed with normal discovery

**When NOT to reuse**:
- The requirement explicitly asks for a different model, memory type, or architecture
- The pattern's requirement_text differs significantly (different domain/purpose)
- The pattern has no `flow_data` (legacy record)

**Pattern save**: After every DONE verdict the agent automatically saves the
new pattern. You do not need to call any tool to save it.

### After patching
Confirm:
- The chatflow_id of the created/updated flow
- What specifically changed (1-2 sentences)

---

## Test Context

FLOWISE TEST RULES:

### Run two tests for every patch

TEST 1 — Happy Path
A normal, expected input that the chatflow is designed to handle.
Use `create_prediction` with `override_config='{"sessionId": "test-happy-<timestamp>"}'`
to isolate this session from production history.

TEST 2 — Edge Case
Choose one of:
- Missing expected field or context
- Ambiguous input that could be misinterpreted
- Boundary condition (very short, very long, off-topic)
Use a different sessionId: `override_config='{"sessionId": "test-edge-<timestamp>"}'`

### Report format (required)
For each test:
- Input sent: `"<the question>"`
- Response received: `"<full response text or summary>"`
- Status: PASS or FAIL
- If FAIL: which node likely failed and why

Final line must be:
`RESULT: HAPPY PATH [PASS/FAIL] | EDGE CASE [PASS/FAIL]`

### Multi-turn conversation testing
To simulate a real conversation, use the same sessionId across multiple
`create_prediction` calls sequentially. Verify the chatflow remembers context.

### Rule 15: Your Role in the Test Phase Is Evaluation Only (DD-040)

The agent does **not** invoke `create_prediction` itself in the Test phase.
Predictions are dispatched in parallel by the framework before you receive this context.
You will be given the raw API responses for:

- **Happy-path trial(s)**: requirement-driven input, sessionId `test-<id>-happy-t<N>`
- **Edge-case trial(s)**: empty/boundary input, sessionId `test-<id>-edge-t<N>`

Your job is to **evaluate** these responses, not to call any tools.

Evaluation criteria:
1. Did the response address the input meaningfully? (not empty, not an error trace)
2. Does the response satisfy the SUCCESS CRITERIA from the approved plan?
3. If `test_trials > 1`, ALL trials must pass for the test to count as PASS.

Do **not** call `create_prediction`, `get_chatflow`, or any other tool.
Produce only your evaluation report ending with the required RESULT line.

---

## Error Reference

Common errors encountered when building chatflows programmatically:

| Error | Root Cause | Fix |
|---|---|---|
| `nodes is not iterable` (HTTP 500) | `flowData` sent as `{}` | Always use `{"nodes":[],"edges":[]}` as minimum |
| `Cannot read properties of undefined (reading 'find')` (HTTP 500) | Node data missing `inputAnchors` key | Add `inputAnchors`, `inputParams`, and `outputs` to every node's data (see Rule 8) |
| `NOT NULL constraint failed: tool.color` | Custom tool missing `color` field | Add `"color": "#4CAF50"` to tool node data |
| `"[object Object]" is not valid JSON` | OpenAI assistant `details` sent as dict | `details` must be a JSON string, not a nested object |
| `OPENAI_API_KEY environment variable is missing` | Credential set only at `data.inputs.credential` | Set at BOTH `data.inputs.credential` AND `data.credential` |
| `Ending node must be either a Chain or Agent` | No terminal node in the flow | Ensure a Chain or Agent node is the last node with no outgoing edges |
| `404 Not Found` on create_prediction | Wrong chatflow_id | Verify with `list_chatflows` |
| `Message with ID ... not found` | Invalid messageId for feedback | Use real ID from `list_chat_messages` |
| `No vector node found` | `upsert_vector` called on non-vector chatflow | Chatflow must have a vector store node |
| Empty/short response | Structured output still active on a node | Remove structured output schema from any writer/output node |

---

## Node Quick Reference

Key nodes and their connection patterns:

| Pattern | Nodes | Connection |
|---|---|---|
| Simple chat | ChatOpenAI → ConversationChain ← BufferMemory | ChatOpenAI.BaseChatModel → model; BufferMemory.BaseMemory → memory |
| Tool agent | ChatOpenAI + CustomTool → ToolAgent ← BufferMemory | ChatOpenAI → model; CustomTool → tools; BufferMemory → memory |
| RAG | ChatOpenAI + PineconeVS + Embeddings → ConversationalRetrievalQAChain | PineconeVS → vectorStoreRetriever; Embeddings → embeddings; ChatOpenAI → model |

Prompt field names by node type:
- `conversationChain`: `systemMessagePrompt`
- `toolAgent` / `conversationalAgent`: `systemMessage`
- `llmChain`: via connected `chatPromptTemplate` node
- General: `prompt`, `template`, `instructions`, `humanMessage`, `systemPrompt`
