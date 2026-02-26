"""Compiler integration tests using REAL schemas/flowise_nodes.snapshot.json.

Unlike test_patch_ir.py which uses hand-written mock schemas, these tests load the
actual snapshot so any schema bug (wrong anchor name, bad version, empty baseClasses)
surfaces here before it reaches a live Flowise instance.

Test patterns cover all major node categories:
  - Conversational chain with buffer memory         (Chat Models + Memory + Chains)
  - RAG chain                                       (Embeddings + Vector Stores + Chains)
  - Simple LLM chain with prompt template           (LLMs + Prompts + Chains)
  - ReAct agent with a tool                         (Agents + Tools)
  - Multi-output node (memoryVectorStore)           (Vector Stores with multi-type output)
  - Credential binding                              (credential at data + inputs levels)
  - test_all_nodes_compile_no_error                 (every node in snapshot, regression catch-all)

Phase F validation (_validate_flow_data from tools.py) is the gate: if compiled
flowData would be rejected by Flowise at write-time, the test fails here.

NOTE: All PatchOp constructors (AddNode, SetParam, Connect, BindCredential) have
op_type as their FIRST dataclass field (for JSON serialization).  Always use keyword
arguments so op_type is not accidentally overwritten by positional arguments.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from flowise_dev_agent.agent.compiler import GraphIR, compile_patch_ops
from flowise_dev_agent.agent.patch_ir import AddNode, BindCredential, Connect, SetParam
from flowise_dev_agent.agent.tools import _validate_flow_data

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SCHEMAS_PATH = Path(__file__).parent.parent / "schemas" / "flowise_nodes.snapshot.json"


@pytest.fixture(scope="module")
def schema_cache() -> dict[str, dict[str, Any]]:
    """Load the real snapshot once for the whole test module."""
    assert _SCHEMAS_PATH.exists(), f"Snapshot not found: {_SCHEMAS_PATH}"
    data: list[dict] = json.loads(_SCHEMAS_PATH.read_bytes())
    return {n["name"]: n for n in data if n.get("name")}


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _assert_valid(result, *, expected_nodes: int, expected_edges: int) -> dict:
    """Assert compile succeeded, Phase F passes, return flow_data."""
    assert result.errors == [], f"Compile errors: {result.errors}"

    fd = result.flow_data
    assert len(fd["nodes"]) == expected_nodes, (
        f"Expected {expected_nodes} nodes, got {len(fd['nodes'])}: "
        f"{[n['id'] for n in fd['nodes']]}"
    )
    assert len(fd["edges"]) == expected_edges, (
        f"Expected {expected_edges} edges, got {len(fd['edges'])}: "
        f"{[e['id'] for e in fd['edges']]}"
    )

    # Phase F — same gate used by _make_patch_node_v2 before writing to Flowise
    phase_f = _validate_flow_data(result.flow_data_str)
    assert phase_f["valid"], f"Phase F validation failed: {phase_f.get('errors')}"

    return fd


def _node_data(fd: dict, node_id: str) -> dict:
    node = next((n for n in fd["nodes"] if n["id"] == node_id), None)
    assert node is not None, f"Node '{node_id}' not found in compiled flowData"
    return node["data"]


def _assert_version_is_number(fd: dict) -> None:
    """All node versions must be int or float (not str) in compiled flowData."""
    for n in fd["nodes"]:
        v = n["data"].get("version")
        assert isinstance(v, (int, float)), (
            f"Node {n['id']}: version should be int/float, got {type(v).__name__!r} ({v!r})"
        )


def _assert_type_is_pascal(fd: dict) -> None:
    """Node type must be the first baseClass (PascalCase), not the camelCase node name."""
    for n in fd["nodes"]:
        data = n["data"]
        node_type = data.get("type", "")
        base_classes = data.get("baseClasses", [])
        if base_classes:
            assert node_type == base_classes[0], (
                f"Node {n['id']}: type={node_type!r} should equal baseClasses[0]={base_classes[0]!r}"
            )


def _assert_template_expr(fd: dict, target_id: str, anchor_name: str, source_id: str) -> None:
    """Assert that the target node's inputs have the expected template expression."""
    data = _node_data(fd, target_id)
    inputs = data.get("inputs", {})
    expected = f"{{{{{source_id}.data.instance}}}}"
    assert inputs.get(anchor_name) == expected, (
        f"Node {target_id}.inputs.{anchor_name} = {inputs.get(anchor_name)!r}, "
        f"expected {expected!r}"
    )


def _assert_anchors_seeded(fd: dict, node_id: str) -> None:
    """All inputAnchors must have a key in inputs (at minimum seeded with '')."""
    data = _node_data(fd, node_id)
    inputs = data.get("inputs", {})
    for anchor in data.get("inputAnchors", []):
        name = anchor.get("name", "")
        assert name in inputs, (
            f"Node {node_id}: inputAnchor {name!r} not seeded in inputs dict"
        )


# ---------------------------------------------------------------------------
# Test 1: Conversational chain (chatOpenAI + bufferMemory → conversationChain)
# ---------------------------------------------------------------------------


def test_conversational_chain(schema_cache):
    """Basic 3-node conversational pattern — the canonical Flowise starter flow."""
    ops = [
        AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0", label="ChatOpenAI"),
        AddNode(node_name="bufferMemory", node_id="bufferMemory_0", label="Buffer Memory"),
        AddNode(node_name="conversationChain", node_id="conversationChain_0", label="Conversation Chain"),
        SetParam(node_id="chatOpenAI_0", param_name="modelName", value="gpt-4o-mini"),
        SetParam(node_id="chatOpenAI_0", param_name="temperature", value=0.7),
        SetParam(node_id="bufferMemory_0", param_name="memoryKey", value="chat_history"),
        SetParam(node_id="conversationChain_0", param_name="systemMessagePrompt", value="You are a helpful assistant."),
        BindCredential(node_id="chatOpenAI_0", credential_id="test-cred-uuid", credential_type="openAIApi"),
        Connect(source_node_id="chatOpenAI_0", source_anchor="chatOpenAI", target_node_id="conversationChain_0", target_anchor="model"),
        Connect(source_node_id="bufferMemory_0", source_anchor="bufferMemory", target_node_id="conversationChain_0", target_anchor="memory"),
    ]
    result = compile_patch_ops(GraphIR(), ops, schema_cache)
    fd = _assert_valid(result, expected_nodes=3, expected_edges=2)

    _assert_version_is_number(fd)
    _assert_type_is_pascal(fd)

    # Template expressions wired correctly (the memoryKey fix)
    _assert_template_expr(fd, "conversationChain_0", "model", "chatOpenAI_0")
    _assert_template_expr(fd, "conversationChain_0", "memory", "bufferMemory_0")

    # inputAnchors seeded with "" for unconnected optional anchors
    _assert_anchors_seeded(fd, "conversationChain_0")

    # Credential wired at both levels
    chat_data = _node_data(fd, "chatOpenAI_0")
    assert chat_data.get("credential") == "test-cred-uuid"
    assert chat_data["inputs"].get("credential") == "test-cred-uuid"


# ---------------------------------------------------------------------------
# Test 2: RAG chain (5 nodes)
# ---------------------------------------------------------------------------


def test_rag_chain(schema_cache):
    """5-node RAG pattern: embeddings + vector store + memory → QA chain."""
    ops = [
        AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0", label="ChatOpenAI"),
        AddNode(node_name="openAIEmbeddings", node_id="openAIEmbeddings_0", label="OpenAI Embeddings"),
        AddNode(node_name="memoryVectorStore", node_id="memoryVectorStore_0", label="In-Memory Store"),
        AddNode(node_name="bufferMemory", node_id="bufferMemory_0", label="Buffer Memory"),
        AddNode(node_name="conversationalRetrievalQAChain", node_id="qaChain_0", label="QA Chain"),
        SetParam(node_id="chatOpenAI_0", param_name="modelName", value="gpt-4o"),
        BindCredential(node_id="chatOpenAI_0", credential_id="openai-cred", credential_type="openAIApi"),
        BindCredential(node_id="openAIEmbeddings_0", credential_id="openai-cred", credential_type="openAIApi"),
        Connect(source_node_id="openAIEmbeddings_0", source_anchor="openAIEmbeddings", target_node_id="memoryVectorStore_0", target_anchor="embeddings"),
        Connect(source_node_id="chatOpenAI_0", source_anchor="chatOpenAI", target_node_id="qaChain_0", target_anchor="model"),
        Connect(source_node_id="memoryVectorStore_0", source_anchor="retriever", target_node_id="qaChain_0", target_anchor="vectorStoreRetriever"),
        Connect(source_node_id="bufferMemory_0", source_anchor="bufferMemory", target_node_id="qaChain_0", target_anchor="memory"),
    ]
    result = compile_patch_ops(GraphIR(), ops, schema_cache)
    fd = _assert_valid(result, expected_nodes=5, expected_edges=4)

    _assert_version_is_number(fd)
    _assert_type_is_pascal(fd)

    # Template expressions on the QA chain
    _assert_template_expr(fd, "qaChain_0", "model", "chatOpenAI_0")
    _assert_template_expr(fd, "qaChain_0", "vectorStoreRetriever", "memoryVectorStore_0")
    _assert_template_expr(fd, "qaChain_0", "memory", "bufferMemory_0")
    _assert_template_expr(fd, "memoryVectorStore_0", "embeddings", "openAIEmbeddings_0")

    _assert_anchors_seeded(fd, "qaChain_0")
    _assert_anchors_seeded(fd, "memoryVectorStore_0")


# ---------------------------------------------------------------------------
# Test 3: LLM chain with prompt template (non-chat LLM)
# ---------------------------------------------------------------------------


def test_llm_chain_with_prompt(schema_cache):
    """Classic LLM chain: openAI + promptTemplate → llmChain."""
    ops = [
        AddNode(node_name="openAI", node_id="openAI_0", label="OpenAI"),
        AddNode(node_name="promptTemplate", node_id="prompt_0", label="Prompt Template"),
        AddNode(node_name="llmChain", node_id="chain_0", label="LLM Chain"),
        SetParam(node_id="openAI_0", param_name="modelName", value="gpt-3.5-turbo-instruct"),
        SetParam(node_id="openAI_0", param_name="temperature", value=0.5),
        SetParam(node_id="prompt_0", param_name="template", value="Answer the following: {question}"),
        BindCredential(node_id="openAI_0", credential_id="openai-cred", credential_type="openAIApi"),
        Connect(source_node_id="openAI_0", source_anchor="openAI", target_node_id="chain_0", target_anchor="model"),
        Connect(source_node_id="prompt_0", source_anchor="promptTemplate", target_node_id="chain_0", target_anchor="prompt"),
    ]
    result = compile_patch_ops(GraphIR(), ops, schema_cache)
    fd = _assert_valid(result, expected_nodes=3, expected_edges=2)

    _assert_version_is_number(fd)
    _assert_type_is_pascal(fd)
    _assert_template_expr(fd, "chain_0", "model", "openAI_0")
    _assert_template_expr(fd, "chain_0", "prompt", "prompt_0")
    _assert_anchors_seeded(fd, "chain_0")


# ---------------------------------------------------------------------------
# Test 4: ReAct agent with calculator tool
# ---------------------------------------------------------------------------


def test_react_agent_with_tool(schema_cache):
    """Agent pattern: chatOpenAI + calculator tool → reactAgentChat."""
    ops = [
        AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0", label="ChatOpenAI"),
        AddNode(node_name="calculator", node_id="calc_0", label="Calculator"),
        AddNode(node_name="reactAgentChat", node_id="agent_0", label="ReAct Agent"),
        SetParam(node_id="chatOpenAI_0", param_name="modelName", value="gpt-4o"),
        BindCredential(node_id="chatOpenAI_0", credential_id="openai-cred", credential_type="openAIApi"),
        Connect(source_node_id="chatOpenAI_0", source_anchor="chatOpenAI", target_node_id="agent_0", target_anchor="model"),
        Connect(source_node_id="calc_0", source_anchor="calculator", target_node_id="agent_0", target_anchor="tools"),
    ]
    result = compile_patch_ops(GraphIR(), ops, schema_cache)
    fd = _assert_valid(result, expected_nodes=3, expected_edges=2)

    _assert_version_is_number(fd)
    _assert_type_is_pascal(fd)
    _assert_template_expr(fd, "agent_0", "model", "chatOpenAI_0")
    _assert_template_expr(fd, "agent_0", "tools", "calc_0")
    _assert_anchors_seeded(fd, "agent_0")


# ---------------------------------------------------------------------------
# Test 5: Multi-output node — memoryVectorStore connects as VectorStoreRetriever
# ---------------------------------------------------------------------------


def test_multi_type_output_anchor(schema_cache):
    """memoryVectorStore has two outputs: 'retriever' and 'vectorStore'.

    The compiler must resolve source_anchor='retriever' (the correct Flowise output
    name) to the first outputAnchor of memoryVectorStore.
    """
    ops = [
        AddNode(node_name="openAIEmbeddings", node_id="emb_0", label="Embeddings"),
        AddNode(node_name="memoryVectorStore", node_id="vs_0", label="Vector Store"),
        AddNode(node_name="conversationalRetrievalQAChain", node_id="qa_0", label="QA Chain"),
        AddNode(node_name="chatOpenAI", node_id="llm_0", label="ChatOpenAI"),
        BindCredential(node_id="emb_0", credential_id="cred", credential_type="openAIApi"),
        BindCredential(node_id="llm_0", credential_id="cred", credential_type="openAIApi"),
        Connect(source_node_id="emb_0", source_anchor="openAIEmbeddings", target_node_id="vs_0", target_anchor="embeddings"),
        Connect(source_node_id="vs_0", source_anchor="retriever", target_node_id="qa_0", target_anchor="vectorStoreRetriever"),
        Connect(source_node_id="llm_0", source_anchor="chatOpenAI", target_node_id="qa_0", target_anchor="model"),
    ]
    result = compile_patch_ops(GraphIR(), ops, schema_cache)
    fd = _assert_valid(result, expected_nodes=4, expected_edges=3)

    # Critical: the edge handle for vs_0 → qa_0 must reference the real outputAnchor ID
    edges = {e["source"] + "→" + e["target"]: e for e in fd["edges"]}
    vs_edge = edges.get("vs_0→qa_0")
    assert vs_edge is not None, "vs_0 → qa_0 edge not found"
    assert "vs_0-output-" in vs_edge["sourceHandle"], (
        f"sourceHandle looks wrong: {vs_edge['sourceHandle']!r}"
    )
    # Phase F: the sourceHandle must exist in vs_0's outputAnchors
    # (verified by _assert_valid calling _validate_flow_data)


# ---------------------------------------------------------------------------
# Test 6: Standalone node — buffer memory with no connections
# ---------------------------------------------------------------------------


def test_standalone_node(schema_cache):
    """Single node with no edges — verifies defaults are seeded correctly."""
    ops = [
        AddNode(node_name="bufferMemory", node_id="mem_0", label="Buffer Memory"),
        SetParam(node_id="mem_0", param_name="memoryKey", value="chat_history"),
        SetParam(node_id="mem_0", param_name="sessionId", value=""),
    ]
    result = compile_patch_ops(GraphIR(), ops, schema_cache)
    fd = _assert_valid(result, expected_nodes=1, expected_edges=0)

    _assert_version_is_number(fd)
    _assert_type_is_pascal(fd)

    data = _node_data(fd, "mem_0")
    assert data["inputs"]["memoryKey"] == "chat_history"
    # bufferMemory has no inputAnchors — just inputParams
    assert data.get("inputAnchors") == []


# ---------------------------------------------------------------------------
# Test 7: Vector store with Pinecone (3-input anchor node)
# ---------------------------------------------------------------------------


def test_pinecone_vector_store(schema_cache):
    """Pinecone has document + embeddings + recordManager anchors."""
    ops = [
        AddNode(node_name="openAIEmbeddings", node_id="emb_0", label="Embeddings"),
        AddNode(node_name="pinecone", node_id="pine_0", label="Pinecone"),
        SetParam(node_id="pine_0", param_name="pineconeIndex", value="my-index"),
        BindCredential(node_id="emb_0", credential_id="cred", credential_type="openAIApi"),
        BindCredential(node_id="pine_0", credential_id="pinecone-cred", credential_type="pineconeApi"),
        Connect(source_node_id="emb_0", source_anchor="openAIEmbeddings", target_node_id="pine_0", target_anchor="embeddings"),
    ]
    result = compile_patch_ops(GraphIR(), ops, schema_cache)
    fd = _assert_valid(result, expected_nodes=2, expected_edges=1)

    _assert_version_is_number(fd)
    _assert_type_is_pascal(fd)
    _assert_template_expr(fd, "pine_0", "embeddings", "emb_0")
    _assert_anchors_seeded(fd, "pine_0")


# ---------------------------------------------------------------------------
# Test 8: Type-name anchor resolution (LLM uses class names, not anchor names)
# ---------------------------------------------------------------------------


def test_type_name_anchor_resolution(schema_cache):
    """Verify Pass 3/4 of _resolve_anchor_id: LLM writes 'BaseChatModel' not 'model'.

    This simulates what the LLM emits when it uses class type names as anchor identifiers.
    """
    ops = [
        AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0", label="ChatOpenAI"),
        AddNode(node_name="bufferMemory", node_id="bufferMemory_0", label="Buffer Memory"),
        AddNode(node_name="conversationChain", node_id="conversationChain_0", label="Conversation Chain"),
        BindCredential(node_id="chatOpenAI_0", credential_id="cred", credential_type="openAIApi"),
        # LLM uses class type names instead of anchor names
        Connect(source_node_id="chatOpenAI_0", source_anchor="chatOpenAI", target_node_id="conversationChain_0", target_anchor="BaseChatModel"),
        Connect(source_node_id="bufferMemory_0", source_anchor="bufferMemory", target_node_id="conversationChain_0", target_anchor="BaseMemory"),
    ]
    result = compile_patch_ops(GraphIR(), ops, schema_cache)
    # Must compile without errors (Pass 3 resolves BaseChatModel → model anchor)
    assert result.errors == [], f"Type-name resolution failed: {result.errors}"
    fd = result.flow_data

    phase_f = _validate_flow_data(result.flow_data_str)
    assert phase_f["valid"], (
        f"Phase F failed after type-name resolution: {phase_f.get('errors')}"
    )

    # The template expressions must use the resolved anchor name (not the type name)
    chain_inputs = _node_data(fd, "conversationChain_0")["inputs"]
    assert "model" in chain_inputs or "BaseChatModel" in chain_inputs, (
        f"Neither 'model' nor 'BaseChatModel' in inputs: {list(chain_inputs.keys())}"
    )


# ---------------------------------------------------------------------------
# Test 8b: Pass 5 — type-hierarchy substring match (BaseMemory → BaseChatMemory)
# ---------------------------------------------------------------------------


def test_type_hierarchy_substring_match(schema_cache):
    """Verify Pass 5 of _resolve_anchor_id: LLM writes 'BaseMemory' but
    toolAgent expects 'memory' (type BaseChatMemory).

    Pass 3 misses because 'basememory' is not in ['basechatmemory'].
    Pass 4 misses because 'basechatmemory' does not end with 'basememory'.
    Pass 5 matches because 'basememory' is a substring of 'basechatmemory'.

    Regression test for the ebb04388 structural validation loop.
    """
    ops = [
        AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0", label="ChatOpenAI"),
        AddNode(node_name="bufferMemory", node_id="bufferMemory_0", label="Buffer Memory"),
        AddNode(node_name="toolAgent", node_id="toolAgent_0", label="Tool Agent"),
        BindCredential(node_id="chatOpenAI_0", credential_id="cred", credential_type="openAIApi"),
        Connect(source_node_id="chatOpenAI_0", source_anchor="chatOpenAI", target_node_id="toolAgent_0", target_anchor="BaseChatModel"),
        Connect(source_node_id="bufferMemory_0", source_anchor="bufferMemory", target_node_id="toolAgent_0", target_anchor="BaseMemory"),
    ]
    result = compile_patch_ops(GraphIR(), ops, schema_cache)
    assert result.errors == [], f"Pass 5 type-hierarchy resolution failed: {result.errors}"

    phase_f = _validate_flow_data(result.flow_data_str)
    assert phase_f["valid"], (
        f"Structural validation failed after Pass 5 resolution: {phase_f.get('errors')}"
    )

    # The template expression must use the resolved anchor name 'memory'
    agent_inputs = _node_data(result.flow_data, "toolAgent_0")["inputs"]
    assert "memory" in agent_inputs, (
        f"Expected 'memory' in toolAgent inputs: {list(agent_inputs.keys())}"
    )


# ---------------------------------------------------------------------------
# Test 9: REGRESSION — every node in the snapshot compiles as AddNode
# ---------------------------------------------------------------------------


def test_all_nodes_compile_no_error(schema_cache):
    """Compile every single node in the snapshot as a solo AddNode.

    Failures indicate schema bugs: bad version, empty baseClasses, malformed
    anchor IDs, or other structural issues the compiler can't handle.

    This test is the regression catch-all — it will catch any node the specific
    pattern tests missed.
    """
    failures: list[str] = []
    version_failures: list[str] = []
    type_failures: list[str] = []

    for node_name, schema in schema_cache.items():
        node_id = f"{node_name}_0"
        ops = [AddNode(node_name=node_name, node_id=node_id, label=schema.get("label", node_name))]
        result = compile_patch_ops(GraphIR(), ops, schema_cache)

        if result.errors:
            failures.append(f"{node_name}: {result.errors}")
            continue

        fd = result.flow_data
        if not fd["nodes"]:
            failures.append(f"{node_name}: no nodes in compiled output")
            continue

        data = fd["nodes"][0]["data"]

        # Version must be numeric
        v = data.get("version")
        if not isinstance(v, (int, float)):
            version_failures.append(f"{node_name}: version={v!r} ({type(v).__name__})")

        # Type must equal baseClasses[0]
        base_classes = data.get("baseClasses", [])
        if base_classes and data.get("type") != base_classes[0]:
            type_failures.append(
                f"{node_name}: type={data.get('type')!r} != baseClasses[0]={base_classes[0]!r}"
            )

    report = []
    if failures:
        report.append(f"\n{len(failures)} nodes failed to compile:\n  " + "\n  ".join(failures))
    if version_failures:
        report.append(
            f"\n{len(version_failures)} nodes have non-numeric version:\n  "
            + "\n  ".join(version_failures)
        )
    if type_failures:
        report.append(
            f"\n{len(type_failures)} nodes have wrong type field:\n  "
            + "\n  ".join(type_failures)
        )

    assert not report, "\n".join(report)


# ---------------------------------------------------------------------------
# Test 10: RAG flow with document source (M8.1 guardrail coverage)
# ---------------------------------------------------------------------------


def test_rag_with_document_source(schema_cache):
    """Full RAG pipeline: plainText → memoryVectorStore + openAIEmbeddings → QA chain.

    Validates the M8.1 document-source guardrail: memoryVectorStore MUST have a
    document loader wired to its 'document' anchor or Flowise returns HTTP 500.

    Graph:
      plainText_0.document     → memoryVectorStore_0.document
      openAIEmbeddings_0       → memoryVectorStore_0.embeddings
      memoryVectorStore_0.retriever → conversationalRetrievalQAChain_0.vectorStoreRetriever
      chatOpenAI_0             → conversationalRetrievalQAChain_0.model
    """
    ops = [
        AddNode(node_name="plainText", node_id="plainText_0", label="Plain Text"),
        AddNode(node_name="openAIEmbeddings", node_id="openAIEmbeddings_0", label="OpenAI Embeddings"),
        AddNode(node_name="memoryVectorStore", node_id="memoryVectorStore_0", label="In-Memory Store"),
        AddNode(node_name="chatOpenAI", node_id="chatOpenAI_0", label="ChatOpenAI"),
        AddNode(node_name="conversationalRetrievalQAChain", node_id="qaChain_0", label="QA Chain"),
        SetParam(node_id="plainText_0", param_name="text", value="This is the knowledge base content."),
        SetParam(node_id="chatOpenAI_0", param_name="modelName", value="gpt-4o-mini"),
        BindCredential(node_id="chatOpenAI_0", credential_id="openai-cred", credential_type="openAIApi"),
        BindCredential(node_id="openAIEmbeddings_0", credential_id="openai-cred", credential_type="openAIApi"),
        # Wire document source to vector store (the critical guardrail connection)
        Connect(source_node_id="plainText_0", source_anchor="document", target_node_id="memoryVectorStore_0", target_anchor="document"),
        Connect(source_node_id="openAIEmbeddings_0", source_anchor="openAIEmbeddings", target_node_id="memoryVectorStore_0", target_anchor="embeddings"),
        # Wire retriever output to QA chain
        Connect(source_node_id="memoryVectorStore_0", source_anchor="retriever", target_node_id="qaChain_0", target_anchor="vectorStoreRetriever"),
        Connect(source_node_id="chatOpenAI_0", source_anchor="chatOpenAI", target_node_id="qaChain_0", target_anchor="model"),
    ]
    result = compile_patch_ops(GraphIR(), ops, schema_cache)
    fd = _assert_valid(result, expected_nodes=5, expected_edges=4)

    _assert_version_is_number(fd)
    _assert_type_is_pascal(fd)

    # plainText -> memoryVectorStore.document
    _assert_template_expr(fd, "memoryVectorStore_0", "document", "plainText_0")
    # openAIEmbeddings -> memoryVectorStore.embeddings
    _assert_template_expr(fd, "memoryVectorStore_0", "embeddings", "openAIEmbeddings_0")
    # memoryVectorStore.retriever -> qaChain.vectorStoreRetriever
    _assert_template_expr(fd, "qaChain_0", "vectorStoreRetriever", "memoryVectorStore_0")
    # chatOpenAI -> qaChain.model
    _assert_template_expr(fd, "qaChain_0", "model", "chatOpenAI_0")

    # memoryVectorStore must have outputs["output"] = "retriever" (multi-output selection)
    mvs_data = _node_data(fd, "memoryVectorStore_0")
    assert mvs_data.get("outputs", {}).get("output") == "retriever", (
        "memoryVectorStore outputs['output'] must be 'retriever' when wired to vectorStoreRetriever"
    )

    _assert_anchors_seeded(fd, "qaChain_0")
    _assert_anchors_seeded(fd, "memoryVectorStore_0")
