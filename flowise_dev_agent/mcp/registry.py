"""Registry wiring for the 51 native Flowise MCP tools (M10.2 + M10.2b, DD-079/DD-094).

Registers all ``FlowiseMCPTools`` methods under the ``flowise`` namespace
in the ``ToolRegistry`` so they are callable via
``execute_tool("flowise__list_chatflows", {...}, executor)`` (namespaced) or
``execute_tool("list_chatflows", {...}, executor)`` (simple — backwards compat).
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


def register_flowise_mcp_tools(registry: ToolRegistry, tools: FlowiseMCPTools) -> None:
    """Register all 51 Flowise MCP tools under the ``flowise`` namespace."""

    # ------------------------------------------------------------------
    # Helper: register a single tool in all phases.
    # ------------------------------------------------------------------
    def _reg(td: ToolDef, fn: Any, phases: set[str] | None = None) -> None:
        registry.register(namespace=_NAMESPACE, tool_def=td, phases=phases or _ALL_PHASES, fn=fn)

    # ==================================================================
    # SYSTEM (1)
    # ==================================================================
    _reg(_td("ping", "Check Flowise connectivity"), tools.ping)

    # ==================================================================
    # NODES (2)
    # ==================================================================
    _reg(_td("list_nodes", "List all available Flowise node types"), tools.list_nodes)
    _reg(
        _td("get_node", "Get full schema for a Flowise node type", {"name": _str("Node type name")}, ["name"]),
        tools.get_node,
    )

    # ==================================================================
    # CHATFLOWS (6)
    # ==================================================================
    _reg(_td("list_chatflows", "List all chatflows with id, name, deployed, type"), tools.list_chatflows)
    _reg(
        _td("get_chatflow", "Get full chatflow JSON including flowData", {"chatflow_id": _str("Chatflow ID")}, ["chatflow_id"]),
        tools.get_chatflow,
    )
    _reg(
        _td("get_chatflow_by_apikey", "Resolve chatflow by API key", {"apikey": _str("API key")}, ["apikey"]),
        tools.get_chatflow_by_apikey,
    )
    _reg(
        _td(
            "create_chatflow", "Create a new chatflow",
            {
                "name": _str("Chatflow name"),
                "flow_data": _str("Flow data JSON string"),
                "description": _str("Description"),
                "chatflow_type": _str("Type: CHATFLOW or MULTIAGENT"),
            },
            ["name"],
        ),
        tools.create_chatflow,
    )
    _reg(
        _td(
            "update_chatflow", "Update an existing chatflow",
            {
                "chatflow_id": _str("Chatflow ID"),
                "name": _str("New name"),
                "flow_data": _str("New flow data JSON"),
                "description": _str("New description"),
                "deployed": _bool("Deploy status"),
                "is_public": _bool("Public flag"),
                "chatbot_config": _str("Chatbot config JSON"),
                "category": _str("Category"),
            },
            ["chatflow_id"],
        ),
        tools.update_chatflow,
    )
    _reg(
        _td("delete_chatflow", "Delete a chatflow", {"chatflow_id": _str("Chatflow ID")}, ["chatflow_id"]),
        tools.delete_chatflow,
    )

    # ==================================================================
    # PREDICTION (1)
    # ==================================================================
    _reg(
        _td(
            "create_prediction", "Run a chatflow prediction",
            {
                "chatflow_id": _str("Chatflow ID"),
                "question": _str("User question"),
                "override_config": _str("Override config JSON"),
                "history": _str("Chat history JSON"),
                "streaming": _bool("Enable streaming"),
            },
            ["chatflow_id", "question"],
        ),
        tools.create_prediction,
    )

    # ==================================================================
    # ASSISTANTS (5)
    # ==================================================================
    _reg(_td("list_assistants", "List all assistants"), tools.list_assistants)
    _reg(
        _td("get_assistant", "Get assistant details", {"assistant_id": _str("Assistant ID")}, ["assistant_id"]),
        tools.get_assistant,
    )
    _reg(
        _td(
            "create_assistant", "Create an assistant",
            {
                "name": _str("Name"),
                "description": _str("Description"),
                "model": _str("Model name"),
                "instructions": _str("Instructions"),
                "credential": _str("Credential ID"),
            },
            ["name"],
        ),
        tools.create_assistant,
    )
    _reg(
        _td(
            "update_assistant", "Update an assistant",
            {"assistant_id": _str("Assistant ID"), "details": _str("Details JSON"), "credential": _str("Credential ID")},
            ["assistant_id"],
        ),
        tools.update_assistant,
    )
    _reg(
        _td("delete_assistant", "Delete an assistant", {"assistant_id": _str("Assistant ID")}, ["assistant_id"]),
        tools.delete_assistant,
    )

    # ==================================================================
    # TOOLS (5)
    # ==================================================================
    _reg(_td("list_tools", "List all custom tools"), tools.list_tools)
    _reg(
        _td("get_tool", "Get a custom tool", {"tool_id": _str("Tool ID")}, ["tool_id"]),
        tools.get_tool,
    )
    _reg(
        _td(
            "create_tool", "Create a custom tool",
            {
                "name": _str("Name"),
                "description": _str("Description"),
                "schema": _str("JSON schema"),
                "func": _str("Function code"),
                "color": _str("Display color"),
            },
            ["name", "description"],
        ),
        tools.create_tool,
    )
    _reg(
        _td(
            "update_tool", "Update a custom tool",
            {
                "tool_id": _str("Tool ID"),
                "name": _str("Name"),
                "description": _str("Description"),
                "schema": _str("JSON schema"),
                "func": _str("Function code"),
            },
            ["tool_id"],
        ),
        tools.update_tool,
    )
    _reg(
        _td("delete_tool", "Delete a custom tool", {"tool_id": _str("Tool ID")}, ["tool_id"]),
        tools.delete_tool,
    )

    # ==================================================================
    # VARIABLES (4)
    # ==================================================================
    _reg(_td("list_variables", "List all variables"), tools.list_variables)
    _reg(
        _td(
            "create_variable", "Create a variable",
            {"name": _str("Name"), "value": _str("Value"), "var_type": _str("Type (string/number/etc)")},
            ["name"],
        ),
        tools.create_variable,
    )
    _reg(
        _td(
            "update_variable", "Update a variable",
            {"var_id": _str("Variable ID"), "name": _str("Name"), "value": _str("Value"), "var_type": _str("Type")},
            ["var_id"],
        ),
        tools.update_variable,
    )
    _reg(
        _td("delete_variable", "Delete a variable", {"var_id": _str("Variable ID")}, ["var_id"]),
        tools.delete_variable,
    )

    # ==================================================================
    # DOCUMENT STORES — management (5)
    # ==================================================================
    _reg(_td("list_document_stores", "List all document stores"), tools.list_document_stores)
    _reg(
        _td("get_document_store", "Get document store details", {"store_id": _str("Store ID")}, ["store_id"]),
        tools.get_document_store,
    )
    _reg(
        _td(
            "create_document_store", "Create a document store",
            {
                "name": _str("Name"),
                "description": _str("Description"),
                "vector_store_config": _str("Vector store config JSON"),
                "embedding_config": _str("Embedding config JSON"),
                "record_manager_config": _str("Record manager config JSON"),
            },
            ["name"],
        ),
        tools.create_document_store,
    )
    _reg(
        _td(
            "update_document_store", "Update a document store",
            {
                "store_id": _str("Store ID"),
                "name": _str("Name"),
                "description": _str("Description"),
                "vector_store_config": _str("Vector store config JSON"),
                "embedding_config": _str("Embedding config JSON"),
                "record_manager_config": _str("Record manager config JSON"),
            },
            ["store_id"],
        ),
        tools.update_document_store,
    )
    _reg(
        _td("delete_document_store", "Delete a document store", {"store_id": _str("Store ID")}, ["store_id"]),
        tools.delete_document_store,
    )

    # ==================================================================
    # DOCUMENT STORES — chunks (3)
    # ==================================================================
    _reg(
        _td(
            "get_document_chunks", "Get document chunks",
            {"store_id": _str("Store ID"), "loader_id": _str("Loader ID"), "page_no": _int("Page number")},
            ["store_id", "loader_id"],
        ),
        tools.get_document_chunks,
    )
    _reg(
        _td(
            "update_document_chunk", "Update a document chunk",
            {
                "store_id": _str("Store ID"),
                "loader_id": _str("Loader ID"),
                "chunk_id": _str("Chunk ID"),
                "page_content": _str("New page content"),
                "metadata": _str("Metadata JSON"),
            },
            ["store_id", "loader_id", "chunk_id"],
        ),
        tools.update_document_chunk,
    )
    _reg(
        _td(
            "delete_document_chunk", "Delete a document chunk",
            {"store_id": _str("Store ID"), "loader_id": _str("Loader ID"), "chunk_id": _str("Chunk ID")},
            ["store_id", "loader_id", "chunk_id"],
        ),
        tools.delete_document_chunk,
    )

    # ==================================================================
    # DOCUMENT STORES — operations (3 + 2 deletes = 5)
    # ==================================================================
    _reg(
        _td(
            "upsert_document", "Upsert a document into a store",
            {
                "store_id": _str("Store ID"),
                "loader": _str("Loader config JSON"),
                "splitter": _str("Splitter config JSON"),
                "embedding": _str("Embedding config JSON"),
                "vector_store": _str("Vector store config JSON"),
                "record_manager": _str("Record manager config JSON"),
                "metadata": _str("Metadata JSON"),
                "replace_existing": _bool("Replace existing documents"),
                "doc_id": _str("Document ID"),
            },
            ["store_id"],
        ),
        tools.upsert_document,
    )
    _reg(
        _td(
            "refresh_document_store", "Refresh a document store",
            {"store_id": _str("Store ID"), "items": _str("Items JSON")},
            ["store_id"],
        ),
        tools.refresh_document_store,
    )
    _reg(
        _td(
            "query_document_store", "Query a document store",
            {"store_id": _str("Store ID"), "query": _str("Search query")},
            ["store_id", "query"],
        ),
        tools.query_document_store,
    )
    _reg(
        _td(
            "delete_document_loader", "Delete a document loader from a store",
            {"store_id": _str("Store ID"), "loader_id": _str("Loader ID")},
            ["store_id", "loader_id"],
        ),
        tools.delete_document_loader,
    )
    _reg(
        _td(
            "delete_vectorstore_data", "Delete all vector store data for a store",
            {"store_id": _str("Store ID")},
            ["store_id"],
        ),
        tools.delete_vectorstore_data,
    )

    # ==================================================================
    # CHAT MESSAGES (2)
    # ==================================================================
    _reg(
        _td(
            "list_chat_messages", "List chat messages for a chatflow",
            {
                "chatflow_id": _str("Chatflow ID"),
                "chat_type": _str("Chat type filter"),
                "order": _str("Sort order"),
                "chat_id": _str("Chat ID filter"),
                "session_id": _str("Session ID filter"),
                "start_date": _str("Start date filter"),
                "end_date": _str("End date filter"),
            },
            ["chatflow_id"],
        ),
        tools.list_chat_messages,
    )
    _reg(
        _td(
            "delete_chat_messages", "Delete chat messages for a chatflow",
            {
                "chatflow_id": _str("Chatflow ID"),
                "chat_id": _str("Chat ID"),
                "chat_type": _str("Chat type"),
                "session_id": _str("Session ID"),
                "hard_delete": _bool("Hard delete"),
            },
            ["chatflow_id"],
        ),
        tools.delete_chat_messages,
    )

    # ==================================================================
    # FEEDBACK (3)
    # ==================================================================
    _reg(
        _td(
            "list_feedback", "List feedback for a chatflow",
            {"chatflow_id": _str("Chatflow ID"), "chat_id": _str("Chat ID"), "sort_order": _str("Sort order (asc/desc)")},
            ["chatflow_id"],
        ),
        tools.list_feedback,
    )
    _reg(
        _td(
            "create_feedback", "Create feedback",
            {
                "chatflow_id": _str("Chatflow ID"),
                "chat_id": _str("Chat ID"),
                "message_id": _str("Message ID"),
                "rating": _str("Rating"),
                "content": _str("Content"),
            },
            ["chatflow_id", "chat_id", "message_id", "rating"],
        ),
        tools.create_feedback,
    )
    _reg(
        _td(
            "update_feedback", "Update feedback",
            {"feedback_id": _str("Feedback ID"), "rating": _str("Rating"), "content": _str("Content")},
            ["feedback_id"],
        ),
        tools.update_feedback,
    )

    # ==================================================================
    # LEADS (2)
    # ==================================================================
    _reg(
        _td("list_leads", "List leads for a chatflow", {"chatflow_id": _str("Chatflow ID")}, ["chatflow_id"]),
        tools.list_leads,
    )
    _reg(
        _td(
            "create_lead", "Create a lead",
            {
                "chatflow_id": _str("Chatflow ID"),
                "chat_id": _str("Chat ID"),
                "name": _str("Name"),
                "email": _str("Email"),
                "phone": _str("Phone"),
            },
            ["chatflow_id", "chat_id"],
        ),
        tools.create_lead,
    )

    # ==================================================================
    # VECTOR UPSERT (1)
    # ==================================================================
    _reg(
        _td(
            "upsert_vector", "Trigger vector upsert for a chatflow",
            {
                "chatflow_id": _str("Chatflow ID"),
                "stop_node_id": _str("Stop node ID"),
                "override_config": _str("Override config JSON"),
            },
            ["chatflow_id"],
        ),
        tools.upsert_vector,
    )

    # ==================================================================
    # UPSERT HISTORY (2)
    # ==================================================================
    _reg(
        _td(
            "list_upsert_history", "List upsert history for a chatflow",
            {
                "chatflow_id": _str("Chatflow ID"),
                "order": _str("Sort order (ASC/DESC)"),
                "start_date": _str("Start date"),
                "end_date": _str("End date"),
            },
            ["chatflow_id"],
        ),
        tools.list_upsert_history,
    )
    _reg(
        _td(
            "delete_upsert_history", "Delete upsert history",
            {"chatflow_id": _str("Chatflow ID"), "ids": _str("IDs JSON array")},
            ["chatflow_id"],
        ),
        tools.delete_upsert_history,
    )

    # ==================================================================
    # CREDENTIALS (2)
    # ==================================================================
    _reg(_td("list_credentials", "List credentials (allowlisted fields only)"), tools.list_credentials)
    _reg(
        _td(
            "create_credential", "Create a credential",
            {
                "name": _str("Name"),
                "credential_name": _str("Credential type name"),
                "encrypted_data": _str("Encrypted credential data"),
            },
            ["name", "credential_name", "encrypted_data"],
        ),
        tools.create_credential,
    )

    # ==================================================================
    # MARKETPLACE (1)
    # ==================================================================
    _reg(_td("list_marketplace_templates", "List marketplace templates"), tools.list_marketplace_templates)

    # ==================================================================
    # ANCHOR DICTIONARY (1 — M10.2b, tool #51)
    # ==================================================================
    _reg(
        _td(
            "get_anchor_dictionary",
            "Get canonical anchor dictionary for a node type (input/output anchors with exact names and types)",
            {"node_type": _str("Flowise node type name (e.g. 'toolAgent', 'chatOpenAI')")},
            ["node_type"],
        ),
        tools.get_anchor_dictionary,
    )
