# Roadmap 6: Platform Knowledge Layer — Local-First Schema, Templates & Credentials

**Status:** Planning — not yet started
**Created:** 2026-02-23
**Branch:** `feat/platform-knowledge-layer`

---

## A. Executive Summary

### The Problem

Every session that runs the Flowise Dev Agent today makes repeated, redundant API calls to
the Flowise server:

- `get_node` is called during *every* discover and patch phase to retrieve node schemas that
  do not change between sessions.
- `list_marketplace_templates` is called each session even though the marketplace catalogue
  changes infrequently.
- `list_credentials` is called to resolve credential names to IDs, even though credential
  metadata changes only when a user adds or removes a credential in Flowise Settings.

The cumulative effect is **token burn** (raw API responses can be hundreds of KB injected into
tool result messages) and **latency** (sequential HTTP calls add seconds per phase).

### How the Local-First Approach Works

A `FlowiseKnowledgeProvider` sits between the agent and the Flowise API. It exposes three
read-through sub-stores:

| Sub-store | What it holds | Refresh cadence |
|---|---|---|
| `NodeSchemaStore` | Node type definitions from `FLOWISE_NODE_REFERENCE.md` converted to JSON | Manual / CI trigger |
| `TemplateStore` | Marketplace template catalogue | Daily or on-demand |
| `CredentialStore` | Credential *metadata only* (id, name, type) — no secrets | Per-session startup |

On every read the provider checks the local JSON snapshot first. A targeted API call is made
**only** when the snapshot is missing, fingerprint-mismatched, or the requested item is not
present (i.e., repair mode, not discovery mode).

### Why This Is Production-Grade

1. **Fingerprinting**: Each snapshot ships with a `.meta.json` file containing a SHA-256 hash
   of its content, a `generated_at` timestamp, and the source Flowise hostname. Stale detection
   is O(1) — compare hashes, not content.
2. **Scheduled refresh job**: A CLI command (`python -m flowise_dev_agent.tools.refresh_knowledge`)
   regenerates snapshots from live data and writes new meta files. It can be run in CI or as a
   cron task.
3. **Repair-only fallback**: If the local snapshot is missing a node type or credential,
   *exactly that item* is fetched from the API and the snapshot is patched in-place. The next
   session will find it locally.
4. **No prompt injection of raw snapshots**: Only small, targeted slices (a node's
   `input_params` summary, a credential's `id`) are injected into LLM context. The full
   snapshot is never serialised into a prompt.

---

## B. System Design

### Guardrails — Non-Negotiable

> **Do not create a parallel capability fork.**
> **Do not add a second orchestrator.**
> **Do not inject entire snapshots into prompts.**

These three constraints govern every design decision below. Violations are a hard blocker for
any PR implementing this roadmap.

### Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                   LangGraph Orchestrator (graph.py)              │
│          (unchanged — no new node types, no new edges)           │
└──────────┬───────────────────────────────────────────────────────┘
           │  ToolRegistry (namespaced, unchanged call path)
           │
┌──────────▼───────────────────────────────────────────────────────┐
│               FlowiseDomainCapability  (graph.py)                │
│                                                                   │
│  discover()  plan()  compile_ops()  validate()                   │
│      │           │         │                                      │
│      │     ┌─────▼─────────▼──────────────────────────────────┐ │
│      │     │        FlowiseKnowledgeProvider                   │ │
│      │     │  ┌──────────────────────────────────────────────┐ │ │
│      │     │  │  NodeSchemaStore   (schemas/flowise_nodes.*)  │ │ │
│      │     │  │  TemplateStore     (schemas/flowise_templates.*)│ │
│      │     │  │  CredentialStore   (schemas/flowise_credentials.*)│ │
│      │     │  └──────────────┬───────────────────────────────┘ │ │
│      │     │                 │ fallback (repair only)           │ │
│      │     │  ┌──────────────▼───────────────────────────────┐ │ │
│      │     │  │          Flowise REST API                     │ │ │
│      │     │  └──────────────────────────────────────────────┘ │ │
│      │     └───────────────────────────────────────────────────┘ │
│      │                                                            │
│      │  (direct — unchanged for non-schema tool calls)           │
│      └──► FlowiseClient / ToolRegistry / execute_tool()          │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│              WorkdayKnowledgeProvider  [STUB]                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  WorkdayMcpStore    (schemas/workday_mcp.*)     [STUB]   │   │
│  │  WorkdayApiStore    (schemas/workday_api.*)     [STUB]   │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### B.1 FlowiseKnowledgeProvider

Single class that owns the three Flowise sub-stores. It MUST NOT be a `DomainCapability`
subclass — it is a read-only data provider, not an orchestration unit.

**Responsibilities:**
- Load JSON snapshots from `schemas/` at startup (lazy, cached).
- Expose typed lookup methods: `get_node_schema(node_type)`, `find_templates(tags)`,
  `resolve_credential(name_or_type)`.
- Detect stale snapshots via fingerprint comparison.
- Trigger targeted API repair calls and patch snapshots in-place when items are missing.

**Narrow integration points** (the ONLY places this touches the existing code):

| Integration point | File | Change type |
|---|---|---|
| `FlowiseDomainCapability.__init__` | `agent/graph.py` | Instantiate and hold `FlowiseKnowledgeProvider` |
| `FlowiseDomainCapability.discover()` | `agent/graph.py` | Replace `get_node` calls with `provider.get_node_schema()` |
| `PatchIRCompiler.validate()` | `agent/patch_ir.py` | Replace `get_node` schema lookup with `provider.get_node_schema()` |
| `BindCredential` compiler op | `agent/patch_ir.py` | Replace `list_credentials` scan with `provider.resolve_credential()` |

No other files are touched in Milestones 1–3.

### B.2 NodeSchemaStore

- **Source of truth**: `FLOWISE_NODE_REFERENCE.md` (human-readable, manually maintained).
- **Runtime format**: `schemas/flowise_nodes.snapshot.json` (machine-readable, generated).
- **Lookup key**: `node_type` string (e.g. `"chatOpenAI"`, `"pineconeUpsert"`).
- **Local-first**: Always read snapshot. Fall back to `GET /api/v1/nodes/{node_type}` ONLY
  when a requested `node_type` is absent from the snapshot.
- **Repair behaviour**: Fetched node is appended to the snapshot; meta fingerprint updated.

### B.3 TemplateStore

- **Source of truth**: Flowise marketplace API (`GET /api/v1/marketplaces/templates`).
- **Runtime format**: `schemas/flowise_templates.snapshot.json`.
- **Lookup key**: `template_id`, or tag-based search.
- **Local-first**: Always read snapshot. Fall back ONLY when the requested template is not
  present or the snapshot is older than the configured TTL (default: 24 hours).
- **Alignment**: PatternStore (the existing in-process pattern library) remains the primary
  pattern source for agent-generated patterns. TemplateStore is for Flowise marketplace
  templates only — the two are complementary, not merged.

### B.4 CredentialStore

- **Source of truth**: Flowise credentials API (`GET /api/v1/credentials`).
- **Runtime format**: `schemas/flowise_credentials.snapshot.json`.
- **Security**: The snapshot MUST contain ONLY: `credential_id`, `name`, `type`, `tags`,
  `created_at`, `updated_at`. No `encryptedData`, no API tokens, no secrets.
- **Redaction rule**: The refresh job MUST explicitly strip any key not in the allowlist above
  before writing to disk.
- **Local-first**: Snapshot loaded at `FlowiseKnowledgeProvider` startup. Fall back ONLY
  when a specific credential name is not found locally.
- **Per-session refresh**: `CredentialStore` MAY perform a lightweight re-fetch at session
  start (single API call, O(n) credentials) since credentials change more frequently than node
  schemas.

### B.5 WorkdayKnowledgeProvider (Stub)

Scaffold ONLY. No implementation in this roadmap.

`WorkdayMcpStore` and `WorkdayApiStore` are empty JSON files (`[]`) with valid `.meta.json`
files marking them as `"status": "stub"`. The `WorkdayKnowledgeProvider` class (if created)
MUST raise `NotImplementedError` on all lookup methods.

The stubs exist so that:
- File paths are reserved and don't conflict with future population.
- CI can validate the schema format before real data arrives.
- `WorkdayDomainCapability` can reference the provider without code changes when Milestone 4
  is implemented.

---

## C. File Tree and Artifact Definitions

```
flowise-dev-agent/
├── schemas/
│   ├── flowise_nodes.snapshot.json       # Node schema objects (array)
│   ├── flowise_nodes.meta.json           # Fingerprint + generated_at + source
│   ├── flowise_templates.snapshot.json   # Template objects (array)
│   ├── flowise_templates.meta.json
│   ├── flowise_credentials.snapshot.json # Credential metadata objects (array, no secrets)
│   ├── flowise_credentials.meta.json
│   ├── workday_mcp.snapshot.json         # [] — stub
│   ├── workday_mcp.meta.json             # status: stub
│   ├── workday_api.snapshot.json         # [] — stub
│   └── workday_api.meta.json             # status: stub
│
├── FLOWISE_NODE_REFERENCE.md             # Human-maintained node reference (source for node snapshots)
│
├── flowise_dev_agent/
│   ├── knowledge/                        # NEW package — knowledge provider layer
│   │   ├── __init__.py
│   │   ├── provider.py                   # FlowiseKnowledgeProvider + sub-stores
│   │   ├── workday_provider.py           # WorkdayKnowledgeProvider stub
│   │   └── refresh.py                    # CLI refresh job
│   │
│   ├── agent/
│   │   ├── graph.py                      # NARROW EDIT: instantiate + use FlowiseKnowledgeProvider
│   │   └── patch_ir.py                   # NARROW EDIT: compiler uses provider for schema lookup
│   │
│   └── ...                               # All other files: unchanged
│
└── scripts/
    └── refresh_knowledge.sh              # Thin wrapper: python -m flowise_dev_agent.knowledge.refresh
```

**Key note**: `FLOWISE_NODE_REFERENCE.md` is the human-authored source. The refresh job
reads it, parses it, and writes `flowise_nodes.snapshot.json`. The markdown file is never
loaded at runtime.

---

## D. Data Contracts

### D.1 Node Schema Object (`flowise_nodes.snapshot.json`)

```json
[
  {
    "node_type": "chatOpenAI",
    "label": "ChatOpenAI",
    "category": "Chat Models",
    "version": 6,
    "description": "Wrapper around OpenAI large language models that use the Chat endpoint.",
    "credential_required": "openAIApi",
    "input_anchors": [
      { "id": "cache", "label": "Cache", "type": "BaseCache", "optional": true }
    ],
    "output_anchors": [
      { "id": "chatOpenAI", "label": "ChatOpenAI", "type": "ChatOpenAI" }
    ],
    "input_params": [
      { "name": "modelName",    "label": "Model Name",    "type": "options",  "options": ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"] },
      { "name": "temperature",  "label": "Temperature",   "type": "number",   "default": 0.9 },
      { "name": "maxTokens",    "label": "Max Tokens",    "type": "number",   "optional": true },
      { "name": "streaming",    "label": "Streaming",     "type": "boolean",  "default": true }
    ]
  }
]
```

**Required fields**: `node_type`, `input_anchors`, `output_anchors`, `input_params`.
**Optional but included when available**: `credential_required`, `version`, `description`, `category`.

### D.2 Template Object (`flowise_templates.snapshot.json`)

```json
[
  {
    "template_id": "marketplace-uuid-1234",
    "name": "PDF QA Chatbot",
    "description": "Retrieval-augmented chatbot that answers questions from uploaded PDFs.",
    "tags": ["rag", "pdf", "openai", "pinecone"],
    "badge": "POPULAR",
    "framework": ["Langchain"],
    "usecases": ["Q&A"],
    "flow_reference": "flowData field omitted from snapshot — fetch on demand via GET /api/v1/chatflows/{id}",
    "version_label": "snapshot-2026-02-23",
    "snapshot_at": "2026-02-23T00:00:00Z"
  }
]
```

**Required fields**: `template_id`, `name`, `tags`.
**Note**: `flowData` (potentially large) is NOT stored in the snapshot. Only metadata is
stored; `flowData` is fetched on demand when a template is actually used.

### D.3 Credential Metadata Object (`flowise_credentials.snapshot.json`)

```json
[
  {
    "credential_id": "513db410-c4c3-4818-a716-6f386aba8a82",
    "name": "My OpenAI Key",
    "type": "openAIApi",
    "tags": [],
    "created_at": "2026-01-15T10:23:00Z",
    "updated_at": "2026-02-01T08:00:00Z"
  }
]
```

**Allowlist** (only these fields may appear in the snapshot):
`credential_id`, `name`, `type`, `tags`, `created_at`, `updated_at`.

**MUST NOT appear**: `encryptedData`, `plainDataObj`, `password`, `apiKey`, `token`, or any
field whose name contains `secret`, `key`, `password`, `token`, or `credential` (substring
match, case-insensitive), except for `type` and `credential_id`.

### D.4 Meta File Format (all `.meta.json` files)

```json
{
  "snapshot_file": "schemas/flowise_nodes.snapshot.json",
  "generated_at": "2026-02-23T12:00:00Z",
  "source_host": "http://localhost:3000",
  "flowise_version": "2.1.4",
  "item_count": 142,
  "sha256": "a3f8c2d1e7b09f4c6e2d1a8b3f9c4d7e2b1a8f3c9e4d7b2a1f8c3e9d4b7a2f1",
  "status": "ok"
}
```

For stub files: `"status": "stub"`, `"item_count": 0`, `"sha256": null`.

---

## E. Runtime Policies

### E.1 When to Use Local Snapshot (DEFAULT)

The provider MUST read from the local snapshot when ALL of the following hold:

- [ ] The snapshot file exists on disk.
- [ ] The `.meta.json` fingerprint matches `sha256(snapshot_file_contents)`.
- [ ] For `CredentialStore`: snapshot age is within the configured TTL (default: `CREDENTIAL_SNAPSHOT_TTL_SECONDS`, default 3600).
- [ ] For `NodeSchemaStore`: the requested `node_type` is present in the snapshot.
- [ ] For `TemplateStore`: the snapshot age is within `TEMPLATE_SNAPSHOT_TTL_SECONDS` (default: 86400).

### E.2 When to Trigger Fallback Repair (FALLBACK — not default)

A targeted API call is triggered ONLY WHEN one or more of the following is true:

- [ ] Snapshot file does not exist (cold start).
- [ ] Fingerprint mismatch detected (snapshot file was externally modified or corrupted).
- [ ] Specific item is not found in snapshot (`node_type` unknown, credential name unresolvable).
- [ ] Snapshot TTL has expired (TemplateStore or CredentialStore age check fails).

The fallback MUST fetch ONLY the missing item (or the minimum batch). It MUST NOT re-fetch
the entire catalogue when a single item is missing.

After a successful repair fetch, the provider MUST:
1. Append the fetched item to the snapshot.
2. Recompute `sha256` and update `.meta.json`.
3. Log: `"[knowledge] repaired snapshot: added <node_type> from API"`.

### E.3 Stale Detection via Fingerprint

Fingerprint check is performed at:
- `FlowiseKnowledgeProvider` startup (once per session).
- After each repair write (to confirm the write was clean).

Algorithm:
```
stored_hash  = meta["sha256"]
actual_hash  = sha256(read_bytes(snapshot_file))
stale        = (stored_hash != actual_hash)
```

If `stale` is `True`, the provider MUST log a warning and trigger a full refresh for that
sub-store before returning any data.

### E.4 What Gets Injected into LLM Context (SMALL SLICES ONLY)

> **MUST NOT**: inject the full snapshot, full node schema list, or full credential list
> into any system prompt or user message.

What MAY be injected (per-call, targeted):

| Scenario | What to inject |
|---|---|
| Plan node building a chatflow | Node type names + categories only (no params): `"Available nodes: chatOpenAI (Chat Models), pineconeUpsert (Vector Stores), …"` |
| Patch node: compiler needs a node's params | Only `input_params` for the **specific node being added** (1–5 fields, no anchors) |
| Credential check HITL | Only `name` + `type` pairs for missing credentials |
| Template suggestion | Only `name` + `tags` + `description` for up to 3 matching templates |

### E.5 What Goes into AgentState Stores

| Store | Field | What is written |
|---|---|---|
| `facts["flowise"]` | `available_node_types` | List of node type strings (not schemas) |
| `facts["flowise"]` | `resolved_credentials` | `{credential_name: credential_id}` map for this session |
| `artifacts["flowise"]` | `template_used` | `template_id` if a marketplace template was used as a base |
| `debug["flowise"]` | `knowledge_repair_events` | List of repair fetch events (node_type + timestamp) |

---

## F. Refresh Strategy

### F.1 CLI Command

```bash
# Refresh all Flowise snapshots (nodes + templates + credentials):
python -m flowise_dev_agent.knowledge.refresh --all

# Refresh individual stores:
python -m flowise_dev_agent.knowledge.refresh --nodes
python -m flowise_dev_agent.knowledge.refresh --templates
python -m flowise_dev_agent.knowledge.refresh --credentials

# Dry-run: print what would change, write nothing:
python -m flowise_dev_agent.knowledge.refresh --all --dry-run

# Thin shell wrapper (for cron / CI):
bash scripts/refresh_knowledge.sh
```

The refresh script authenticates using the same `FLOWISE_API_URL` and `FLOWISE_API_KEY`
environment variables used by the main agent.

### F.2 Node Snapshot Generation

Node schemas are NOT fetched from the Flowise API at refresh time by default. Instead:
1. The refresh job parses `FLOWISE_NODE_REFERENCE.md` (markdown → JSON).
2. It produces `flowise_nodes.snapshot.json` from the parsed content.
3. If `--nodes --from-api` flag is passed, it also calls `GET /api/v1/nodes` to supplement
   any node types present in the API but absent from the markdown reference.

This two-path approach ensures the markdown remains the canonical human-maintained source,
while the API serves as a supplement for newly released node types.

### F.3 Fingerprinting

After each write the refresh job MUST:
```python
import hashlib, json
content = snapshot_path.read_bytes()
digest  = hashlib.sha256(content).hexdigest()
meta    = {
    "snapshot_file": str(snapshot_path),
    "generated_at":  datetime.utcnow().isoformat() + "Z",
    "source_host":   FLOWISE_API_URL,
    "flowise_version": fetched_version_or_null,
    "item_count":    len(snapshot_data),
    "sha256":        digest,
    "status":        "ok",
}
meta_path.write_text(json.dumps(meta, indent=2))
```

### F.4 Diff Detection

The refresh job MUST report a diff when run with `--all`:

```
[nodes]       142 items in snapshot, 145 in API — 3 new: simpleSequentialChain, sqlDatabaseChain, zapierNLA
[templates]   38 items — no change (fingerprint match)
[credentials] 5 items — 1 changed: "My OpenAI Key" updated_at changed
```

Diff algorithm:
- **New item**: `id` present in API response but absent from snapshot.
- **Changed item**: Any allowlisted field value differs between API and snapshot.
- **Removed item**: `id` present in snapshot but absent from API response (warn only, do not auto-delete).

---

## G. Implementation Plan

### Milestone 1 — Node Snapshots + Compiler Integration

**Goal**: Eliminate `get_node` calls during discover and patch phases. Compiler uses
local schema instead of API.

**Tasks**:
- [ ] Create `FLOWISE_NODE_REFERENCE.md` — document all known Flowise node types with
      their `input_params`, `input_anchors`, `output_anchors`, and `credential_required`.
- [ ] Create `flowise_dev_agent/knowledge/__init__.py` and `provider.py` with
      `NodeSchemaStore` class.
- [ ] Implement `NodeSchemaStore.get(node_type)` with local-first + repair-fallback logic.
- [ ] Write the refresh job (`knowledge/refresh.py`) — markdown parser + `--nodes` path.
- [ ] Generate initial `schemas/flowise_nodes.snapshot.json` and `.meta.json`.
- [ ] Narrow edit in `FlowiseDomainCapability.__init__` to instantiate `FlowiseKnowledgeProvider`.
- [ ] Narrow edit in `FlowiseDomainCapability.discover()` to call `provider.get_node_schema()`
      instead of `get_node` tool.
- [ ] Narrow edit in `PatchIRCompiler` schema lookup to use `provider.get_node_schema()`.
- [ ] Add `debug["flowise"]["knowledge_repair_events"]` logging.
- [ ] Update `.gitignore`: do NOT ignore `schemas/*.snapshot.json` (they are checked in).

**Acceptance criteria**:
- [ ] `pytest tests/` — 28/28 pass.
- [ ] Starting a session with a chatflow that uses `chatOpenAI` + `pinecone` produces
      zero `get_node` API calls in the Flowise server access log.
- [ ] A node type not in the snapshot (e.g. a newly released node) triggers exactly one
      repair fetch, is appended to the snapshot, and subsequent calls read locally.
- [ ] `python -m flowise_dev_agent.knowledge.refresh --nodes --dry-run` exits 0 and prints
      item count.

---

### Milestone 2 — Template Snapshots + PatternStore Alignment

**Goal**: Replace `list_marketplace_templates` calls with local snapshot lookups.
Clarify the relationship between PatternStore (agent patterns) and TemplateStore (Flowise marketplace).

**Tasks**:
- [ ] Add `TemplateStore` class to `knowledge/provider.py`.
- [ ] Implement `TemplateStore.find(tags, limit=3)` — tag-based local search.
- [ ] Add `--templates` path to the refresh job. Fetch `GET /api/v1/marketplaces/templates`,
      strip `flowData` from snapshot (metadata only), write to `schemas/flowise_templates.*`.
- [ ] Generate initial `schemas/flowise_templates.snapshot.json` and `.meta.json`.
- [ ] Narrow edit in plan node context building: replace live template fetch with
      `provider.find_templates(tags)` returning name + description slices only.
- [ ] Add `artifacts["flowise"]["template_used"]` when a template is referenced in a plan.
- [ ] Document the PatternStore / TemplateStore distinction in `DESIGN_DECISIONS.md` (new DD).
- [ ] Implement TTL check (`TEMPLATE_SNAPSHOT_TTL_SECONDS`, default 86400).

**Acceptance criteria**:
- [ ] `pytest tests/` — all pass.
- [ ] Plan phase for a "RAG chatbot" prompt produces zero `list_marketplace_templates` API
      calls.
- [ ] `python -m flowise_dev_agent.knowledge.refresh --templates` updates snapshot and
      fingerprint in under 10 seconds on a live Flowise instance.
- [ ] Diff output correctly identifies new templates added since last refresh.

---

### Milestone 3 — Credential Snapshots + BindCredential Integration

**Goal**: Replace `list_credentials` scan in the `BindCredential` compiler op with a
local lookup. Enforce the metadata-only security contract at the snapshot level.

**Tasks**:
- [ ] Add `CredentialStore` class to `knowledge/provider.py`.
- [ ] Implement `CredentialStore.resolve(name_or_type)` — returns `credential_id` or `None`.
- [ ] Add `--credentials` path to the refresh job with explicit allowlist redaction:
      strip any key not in `{credential_id, name, type, tags, created_at, updated_at}`.
- [ ] Add a CI lint step that asserts no banned keys appear in `flowise_credentials.snapshot.json`
      (run via `python -m flowise_dev_agent.knowledge.refresh --credentials --validate`).
- [ ] Generate initial `schemas/flowise_credentials.snapshot.json` and `.meta.json`.
- [ ] Narrow edit in `BindCredential` compiler op: call `provider.resolve_credential(name)`
      before falling back to `list_credentials` API.
- [ ] Add `facts["flowise"]["resolved_credentials"]` map populated at session start.
- [ ] Implement per-session refresh: `CredentialStore` re-fetches if snapshot age > TTL.
- [ ] Credential snapshot MUST NOT be committed to git if it contains real credentials.
      Add `schemas/flowise_credentials.snapshot.json` to `.gitignore` with a comment
      explaining why (contains live instance metadata, machine-specific).

**Acceptance criteria**:
- [ ] `pytest tests/` — all pass.
- [ ] `BindCredential` op resolves `openAIApi` to a credential ID with zero API calls
      when the credential exists in snapshot.
- [ ] CI lint step fails if `encryptedData` or any banned key is present in the credential
      snapshot.
- [ ] Session start logs `"[knowledge] credentials loaded: 5 items (from snapshot)"`.
- [ ] When a credential is not found locally, exactly one `list_credentials` API call is made,
      the result is filtered to the allowlist, appended to snapshot, and logged as a repair event.

---

### Milestone 4 — Workday Knowledge Placeholders

**Goal**: Reserve file paths and class interfaces for future Workday MCP and API knowledge.
No functional implementation.

**Tasks**:
- [ ] Create `schemas/workday_mcp.snapshot.json` → `[]`
- [ ] Create `schemas/workday_mcp.meta.json` → `{"status": "stub", "item_count": 0, "sha256": null}`
- [ ] Create `schemas/workday_api.snapshot.json` → `[]`
- [ ] Create `schemas/workday_api.meta.json` → `{"status": "stub", "item_count": 0, "sha256": null}`
- [ ] Create `flowise_dev_agent/knowledge/workday_provider.py` with:
  - `WorkdayMcpStore` class — `get()` raises `NotImplementedError("WorkdayMcpStore not yet populated")`
  - `WorkdayApiStore` class — `get()` raises `NotImplementedError("WorkdayApiStore not yet populated")`
  - `WorkdayKnowledgeProvider` class — holds both stores
- [ ] Document future populate plan in this file (see section below).
- [ ] Add `--workday-mcp` and `--workday-api` flags to the refresh job — both are no-ops
      that print `"Workday knowledge refresh not yet implemented"` and exit 0.

**Future populate plan** (not in scope for this roadmap — written here for the next engineer):
- `WorkdayMcpStore`: populated from MCP server tool manifest once Workday MCP integration
  is live (Roadmap 3, Milestone 3). Refresh by calling `tools/list` on the MCP server.
- `WorkdayApiStore`: populated from Workday REST API OpenAPI spec. Refresh by fetching
  the spec and converting operations to the snapshot format.

**Acceptance criteria**:
- [ ] `pytest tests/` — all pass.
- [ ] Both stub snapshot files parse as valid JSON (`json.loads`).
- [ ] `WorkdayKnowledgeProvider().workday_mcp.get("anything")` raises `NotImplementedError`.
- [ ] `python -m flowise_dev_agent.knowledge.refresh --workday-mcp` exits 0 without error.
- [ ] `WorkdayDomainCapability` (when it exists) can instantiate `WorkdayKnowledgeProvider`
      with no import changes.

---

## H. Guardrails Against Design Drift

The following constraints are repeated here as an explicit checklist for every PR that
implements this roadmap. All must be true before merge.

### H.1 Single Execution Path

> **Do not create a parallel capability fork.**

- [ ] `FlowiseKnowledgeProvider` is a data provider, not a `DomainCapability` subclass.
- [ ] No new graph nodes are added.
- [ ] No new edges are added to the LangGraph graph.
- [ ] `build_graph()` signature is unchanged.
- [ ] `capabilities=None` path continues to behave identically to pre-roadmap behaviour.

### H.2 Single Orchestrator

> **Do not add a second orchestrator.**

- [ ] `FlowiseKnowledgeProvider` has no async event loop, no background task, no thread.
- [ ] Snapshot reads are synchronous file I/O (fast, no network).
- [ ] Repair fetches use the existing `FlowiseClient` instance, not a new HTTP client.
- [ ] No new FastAPI background tasks or lifespan hooks related to knowledge loading.

### H.3 No Full Snapshot Injection

> **Do not inject entire snapshots into prompts.**

- [ ] No system prompt contains a raw JSON snapshot.
- [ ] No user message contains more than 5 node schema entries.
- [ ] The plan node's context building injects node type names only (no params).
- [ ] The patch compiler injects `input_params` for one node at a time, maximum 10 fields.
- [ ] A PR review checklist item MUST verify this constraint for any message construction
      that touches `FlowiseKnowledgeProvider` data.

---

## Appendix: Environment Variables

| Variable | Default | Description |
|---|---|---|
| `KNOWLEDGE_SCHEMAS_DIR` | `./schemas` | Directory containing all snapshot files |
| `NODE_SNAPSHOT_FROM_API` | `false` | If `true`, refresh job supplements markdown parse with API data |
| `CREDENTIAL_SNAPSHOT_TTL_SECONDS` | `3600` | Max age of credential snapshot before per-session refresh |
| `TEMPLATE_SNAPSHOT_TTL_SECONDS` | `86400` | Max age of template snapshot before refresh |
| `KNOWLEDGE_REPAIR_LOG` | `true` | Log repair events to stdout |

---

*This is a plan-only document. No code has been modified. Implementation begins at Milestone 1.*
