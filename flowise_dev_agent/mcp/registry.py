"""Registry wiring for the 51 native Flowise MCP tools (M10.2 + M10.2b, DD-094/DD-096).

``TOOL_CATALOG`` is the single source of truth for tool metadata (name,
description, JSON schema).  Both the internal ``ToolRegistry`` and the
external MCP server (M10.4) consume it — no duplication.

Adding a tool: append to ``TOOL_CATALOG`` and add the method to
``FlowiseMCPTools``.  Two files, nothing else.
"""

from __future__ import annotations

from typing import Any

from flowise_dev_agent.agent.registry import ToolRegistry
from flowise_dev_agent.mcp.tools import FlowiseMCPTools
from flowise_dev_agent.reasoning import ToolDef

_NAMESPACE = "flowise"


def _td(name: str, desc: str, props: dict[str, Any] | None = None, req: list[str] | None = None) -> ToolDef:
    return ToolDef(
        name=name,
        description=desc,
        parameters={"type": "object", "properties": props or {}, "required": req or []},
    )


def _str(description: str) -> dict:
    return {"type": "string", "description": description}


def _bool(description: str) -> dict:
    return {"type": "boolean", "description": description}


def _int(description: str) -> dict:
    return {"type": "integer", "description": description}


# All phases where MCP tools should be available.
_ALL_PHASES: set[str] = {"discover", "patch", "test"}


# ==================================================================
# TOOL_CATALOG — single source of truth for all 51 tools.
# Each entry: (method_name_on_FlowiseMCPTools, ToolDef)
# ==================================================================

TOOL_CATALOG: list[tuple[str, ToolDef]] = [
    # ── SYSTEM (1) ────────────────────────────────────────────────
    ("ping", _td("ping", "Check Flowise connectivity")),

    # ── NODES (2) ─────────────────────────────────────────────────
    ("list_nodes", _td("list_nodes", "List all available Flowise node types")),
    ("get_node", _td("get_node", "Get full schema for a Flowise node type",
                      {"name": _str("Node type name")}, ["name"])),

    # ── CHATFLOWS (6) ─────────────────────────────────────────────
    ("list_chatflows", _td("list_chatflows", "List all chatflows with id, name, deployed, type")),
    ("get_chatflow", _td("get_chatflow", "Get full chatflow JSON including flowData",
                          {"chatflow_id": _str("Chatflow ID")}, ["chatflow_id"])),
    ("get_chatflow_by_apikey", _td("get_chatflow_by_apikey", "Resolve chatflow by API key",
                                    {"apikey": _str("API key")}, ["apikey"])),
    ("create_chatflow", _td("create_chatflow", "Create a new chatflow", {
        "name": _str("Chatflow name"),
        "flow_data": _str("Flow data JSON string"),
        "description": _str("Description"),
        "chatflow_type": _str("Type: CHATFLOW or MULTIAGENT"),
    }, ["name"])),
    ("update_chatflow", _td("update_chatflow", "Update an existing chatflow", {
        "chatflow_id": _str("Chatflow ID"),
        "name": _str("New name"),
        "flow_data": _str("New flow data JSON"),
        "description": _str("New description"),
        "deployed": _bool("Deploy status"),
        "is_public": _bool("Public flag"),
        "chatbot_config": _str("Chatbot config JSON"),
        "category": _str("Category"),
    }, ["chatflow_id"])),
    ("delete_chatflow", _td("delete_chatflow", "Delete a chatflow",
                             {"chatflow_id": _str("Chatflow ID")}, ["chatflow_id"])),

    # ── PREDICTION (1) ────────────────────────────────────────────
    ("create_prediction", _td("create_prediction", "Run a chatflow prediction", {
        "chatflow_id": _str("Chatflow ID"),
        "question": _str("User question"),
        "override_config": _str("Override config JSON"),
        "history": _str("Chat history JSON"),
        "streaming": _bool("Enable streaming"),
    }, ["chatflow_id", "question"])),

    # ── ASSISTANTS (5) ────────────────────────────────────────────
    ("list_assistants", _td("list_assistants", "List all assistants")),
    ("get_assistant", _td("get_assistant", "Get assistant details",
                           {"assistant_id": _str("Assistant ID")}, ["assistant_id"])),
    ("create_assistant", _td("create_assistant", "Create an assistant", {
        "name": _str("Name"),
        "description": _str("Description"),
        "model": _str("Model name"),
        "instructions": _str("Instructions"),
        "credential": _str("Credential ID"),
    }, ["name"])),
    ("update_assistant", _td("update_assistant", "Update an assistant", {
        "assistant_id": _str("Assistant ID"),
        "details": _str("Details JSON"),
        "credential": _str("Credential ID"),
    }, ["assistant_id"])),
    ("delete_assistant", _td("delete_assistant", "Delete an assistant",
                              {"assistant_id": _str("Assistant ID")}, ["assistant_id"])),

    # ── TOOLS (5) ─────────────────────────────────────────────────
    ("list_tools", _td("list_tools", "List all custom tools")),
    ("get_tool", _td("get_tool", "Get a custom tool",
                      {"tool_id": _str("Tool ID")}, ["tool_id"])),
    ("create_tool", _td("create_tool", "Create a custom tool", {
        "name": _str("Name"),
        "description": _str("Description"),
        "schema": _str("JSON schema"),
        "func": _str("Function code"),
        "color": _str("Display color"),
    }, ["name", "description"])),
    ("update_tool", _td("update_tool", "Update a custom tool", {
        "tool_id": _str("Tool ID"),
        "name": _str("Name"),
        "description": _str("Description"),
        "schema": _str("JSON schema"),
        "func": _str("Function code"),
    }, ["tool_id"])),
    ("delete_tool", _td("delete_tool", "Delete a custom tool",
                         {"tool_id": _str("Tool ID")}, ["tool_id"])),

    # ── VARIABLES (4) ─────────────────────────────────────────────
    ("list_variables", _td("list_variables", "List all variables")),
    ("create_variable", _td("create_variable", "Create a variable", {
        "name": _str("Name"),
        "value": _str("Value"),
        "var_type": _str("Type (string/number/etc)"),
    }, ["name"])),
    ("update_variable", _td("update_variable", "Update a variable", {
        "var_id": _str("Variable ID"),
        "name": _str("Name"),
        "value": _str("Value"),
        "var_type": _str("Type"),
    }, ["var_id"])),
    ("delete_variable", _td("delete_variable", "Delete a variable",
                             {"var_id": _str("Variable ID")}, ["var_id"])),

    # ── DOCUMENT STORES — management (5) ──────────────────────────
    ("list_document_stores", _td("list_document_stores", "List all document stores")),
    ("get_document_store", _td("get_document_store", "Get document store details",
                                {"store_id": _str("Store ID")}, ["store_id"])),
    ("create_document_store", _td("create_document_store", "Create a document store", {
        "name": _str("Name"),
        "description": _str("Description"),
        "vector_store_config": _str("Vector store config JSON"),
        "embedding_config": _str("Embedding config JSON"),
        "record_manager_config": _str("Record manager config JSON"),
    }, ["name"])),
    ("update_document_store", _td("update_document_store", "Update a document store", {
        "store_id": _str("Store ID"),
        "name": _str("Name"),
        "description": _str("Description"),
        "vector_store_config": _str("Vector store config JSON"),
        "embedding_config": _str("Embedding config JSON"),
        "record_manager_config": _str("Record manager config JSON"),
    }, ["store_id"])),
    ("delete_document_store", _td("delete_document_store", "Delete a document store",
                                   {"store_id": _str("Store ID")}, ["store_id"])),

    # ── DOCUMENT STORES — chunks (3) ──────────────────────────────
    ("get_document_chunks", _td("get_document_chunks", "Get document chunks", {
        "store_id": _str("Store ID"),
        "loader_id": _str("Loader ID"),
        "page_no": _int("Page number"),
    }, ["store_id", "loader_id"])),
    ("update_document_chunk", _td("update_document_chunk", "Update a document chunk", {
        "store_id": _str("Store ID"),
        "loader_id": _str("Loader ID"),
        "chunk_id": _str("Chunk ID"),
        "page_content": _str("New page content"),
        "metadata": _str("Metadata JSON"),
    }, ["store_id", "loader_id", "chunk_id"])),
    ("delete_document_chunk", _td("delete_document_chunk", "Delete a document chunk", {
        "store_id": _str("Store ID"),
        "loader_id": _str("Loader ID"),
        "chunk_id": _str("Chunk ID"),
    }, ["store_id", "loader_id", "chunk_id"])),

    # ── DOCUMENT STORES — operations (5) ──────────────────────────
    ("upsert_document", _td("upsert_document", "Upsert a document into a store", {
        "store_id": _str("Store ID"),
        "loader": _str("Loader config JSON"),
        "splitter": _str("Splitter config JSON"),
        "embedding": _str("Embedding config JSON"),
        "vector_store": _str("Vector store config JSON"),
        "record_manager": _str("Record manager config JSON"),
        "metadata": _str("Metadata JSON"),
        "replace_existing": _bool("Replace existing documents"),
        "doc_id": _str("Document ID"),
    }, ["store_id"])),
    ("refresh_document_store", _td("refresh_document_store", "Refresh a document store", {
        "store_id": _str("Store ID"),
        "items": _str("Items JSON"),
    }, ["store_id"])),
    ("query_document_store", _td("query_document_store", "Query a document store", {
        "store_id": _str("Store ID"),
        "query": _str("Search query"),
    }, ["store_id", "query"])),
    ("delete_document_loader", _td("delete_document_loader", "Delete a document loader from a store", {
        "store_id": _str("Store ID"),
        "loader_id": _str("Loader ID"),
    }, ["store_id", "loader_id"])),
    ("delete_vectorstore_data", _td("delete_vectorstore_data", "Delete all vector store data for a store", {
        "store_id": _str("Store ID"),
    }, ["store_id"])),

    # ── CHAT MESSAGES (2) ─────────────────────────────────────────
    ("list_chat_messages", _td("list_chat_messages", "List chat messages for a chatflow", {
        "chatflow_id": _str("Chatflow ID"),
        "chat_type": _str("Chat type filter"),
        "order": _str("Sort order"),
        "chat_id": _str("Chat ID filter"),
        "session_id": _str("Session ID filter"),
        "start_date": _str("Start date filter"),
        "end_date": _str("End date filter"),
    }, ["chatflow_id"])),
    ("delete_chat_messages", _td("delete_chat_messages", "Delete chat messages for a chatflow", {
        "chatflow_id": _str("Chatflow ID"),
        "chat_id": _str("Chat ID"),
        "chat_type": _str("Chat type"),
        "session_id": _str("Session ID"),
        "hard_delete": _bool("Hard delete"),
    }, ["chatflow_id"])),

    # ── FEEDBACK (3) ──────────────────────────────────────────────
    ("list_feedback", _td("list_feedback", "List feedback for a chatflow", {
        "chatflow_id": _str("Chatflow ID"),
        "chat_id": _str("Chat ID"),
        "sort_order": _str("Sort order (asc/desc)"),
    }, ["chatflow_id"])),
    ("create_feedback", _td("create_feedback", "Create feedback", {
        "chatflow_id": _str("Chatflow ID"),
        "chat_id": _str("Chat ID"),
        "message_id": _str("Message ID"),
        "rating": _str("Rating"),
        "content": _str("Content"),
    }, ["chatflow_id", "chat_id", "message_id", "rating"])),
    ("update_feedback", _td("update_feedback", "Update feedback", {
        "feedback_id": _str("Feedback ID"),
        "rating": _str("Rating"),
        "content": _str("Content"),
    }, ["feedback_id"])),

    # ── LEADS (2) ─────────────────────────────────────────────────
    ("list_leads", _td("list_leads", "List leads for a chatflow",
                        {"chatflow_id": _str("Chatflow ID")}, ["chatflow_id"])),
    ("create_lead", _td("create_lead", "Create a lead", {
        "chatflow_id": _str("Chatflow ID"),
        "chat_id": _str("Chat ID"),
        "name": _str("Name"),
        "email": _str("Email"),
        "phone": _str("Phone"),
    }, ["chatflow_id", "chat_id"])),

    # ── VECTOR UPSERT (1) ─────────────────────────────────────────
    ("upsert_vector", _td("upsert_vector", "Trigger vector upsert for a chatflow", {
        "chatflow_id": _str("Chatflow ID"),
        "stop_node_id": _str("Stop node ID"),
        "override_config": _str("Override config JSON"),
    }, ["chatflow_id"])),

    # ── UPSERT HISTORY (2) ────────────────────────────────────────
    ("list_upsert_history", _td("list_upsert_history", "List upsert history for a chatflow", {
        "chatflow_id": _str("Chatflow ID"),
        "order": _str("Sort order (ASC/DESC)"),
        "start_date": _str("Start date"),
        "end_date": _str("End date"),
    }, ["chatflow_id"])),
    ("delete_upsert_history", _td("delete_upsert_history", "Delete upsert history", {
        "chatflow_id": _str("Chatflow ID"),
        "ids": _str("IDs JSON array"),
    }, ["chatflow_id"])),

    # ── CREDENTIALS (2) ──────────────────────────────────────────
    ("list_credentials", _td("list_credentials", "List credentials (allowlisted fields only)")),
    ("create_credential", _td("create_credential", "Create a credential", {
        "name": _str("Name"),
        "credential_name": _str("Credential type name"),
        "encrypted_data": _str("Encrypted credential data"),
    }, ["name", "credential_name", "encrypted_data"])),

    # ── MARKETPLACE (1) ──────────────────────────────────────────
    ("list_marketplace_templates", _td("list_marketplace_templates", "List marketplace templates")),

    # ── ANCHOR DICTIONARY (1 — M10.2b, tool #51) ─────────────────
    ("get_anchor_dictionary", _td(
        "get_anchor_dictionary",
        "Get canonical anchor dictionary for a node type (input/output anchors with exact names and types)",
        {"node_type": _str("Flowise node type name (e.g. 'toolAgent', 'chatOpenAI')")},
        ["node_type"],
    )),
]


def register_flowise_mcp_tools(registry: ToolRegistry, tools: FlowiseMCPTools) -> None:
    """Register all 51 Flowise MCP tools under the ``flowise`` namespace."""
    for method_name, td in TOOL_CATALOG:
        fn = getattr(tools, method_name)
        registry.register(namespace=_NAMESPACE, tool_def=td, phases=_ALL_PHASES, fn=fn)
