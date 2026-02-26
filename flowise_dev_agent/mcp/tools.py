"""Native Flowise MCP tool surface — 51 tools (M10.2 + M10.2b, DD-079/DD-094).

Each method wraps the corresponding ``FlowiseClient`` method and returns a
``ToolResult`` envelope.  No business logic beyond packaging the result.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from flowise_dev_agent.agent.tools import ToolResult
from flowise_dev_agent.client import FlowiseClient

logger = logging.getLogger("flowise_dev_agent.mcp.tools")

# Credential allowlist — must stay in sync with _CRED_ALLOWLIST in provider.py.
_CRED_ALLOWLIST: frozenset[str] = frozenset({
    "credential_id", "name", "type", "tags", "created_at", "updated_at",
    # Also keep Flowise API-native key names (pre-normalization).
    "id", "credentialName", "createdDate", "updatedDate",
})


def _ok(summary: str, data: Any, **facts: Any) -> ToolResult:
    return ToolResult(ok=True, summary=summary, facts=facts, data=data, error=None, artifacts=None)


def _fail(raw: dict) -> ToolResult:
    msg = str(raw.get("error", "Unknown error"))
    detail = raw.get("detail", "")
    return ToolResult(
        ok=False,
        summary=f"Failed: {msg}",
        facts={},
        data=raw,
        error={"type": "FlowiseAPIError", "message": msg, "detail": detail},
        artifacts=None,
    )


def _is_error(raw: Any) -> bool:
    return isinstance(raw, dict) and "error" in raw


class FlowiseMCPTools:
    """51 native Flowise MCP tools returning ``ToolResult`` envelopes."""

    def __init__(
        self,
        client: FlowiseClient,
        anchor_dict_getter: Optional[Callable[[str], dict | None]] = None,
    ) -> None:
        self._client = client
        self._anchor_dict_getter = anchor_dict_getter

    # ==================================================================
    # SYSTEM
    # ==================================================================

    async def ping(self) -> ToolResult:
        raw = await self._client.ping()
        if _is_error(raw):
            return _fail(raw)
        status = raw.get("status", "unknown")
        return _ok(f"Flowise is reachable (status: {status})", raw)

    # ==================================================================
    # NODES
    # ==================================================================

    async def list_nodes(self) -> ToolResult:
        raw = await self._client.list_nodes()
        if _is_error(raw):
            return _fail(raw)
        count = len(raw) if isinstance(raw, list) else "?"
        return _ok(f"Listed {count} node types", raw)

    async def get_node(self, name: str) -> ToolResult:
        raw = await self._client.get_node(name)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Fetched node schema for '{name}'", raw)

    # ==================================================================
    # CHATFLOWS
    # ==================================================================

    async def list_chatflows(self) -> ToolResult:
        raw = await self._client.list_chatflows()
        if _is_error(raw):
            return _fail(raw)
        count = len(raw) if isinstance(raw, list) else "?"
        return _ok(f"Listed {count} chatflows", raw)

    async def get_chatflow(self, chatflow_id: str) -> ToolResult:
        raw = await self._client.get_chatflow(chatflow_id)
        if _is_error(raw):
            return _fail(raw)
        name = raw.get("name", "?") if isinstance(raw, dict) else "?"
        return _ok(f"Fetched chatflow {chatflow_id} ({name})", raw)

    async def get_chatflow_by_apikey(self, apikey: str) -> ToolResult:
        raw = await self._client.get_chatflow_by_apikey(apikey)
        if _is_error(raw):
            return _fail(raw)
        cid = raw.get("id", "?") if isinstance(raw, dict) else "?"
        return _ok(f"Resolved chatflow {cid} by API key", raw)

    async def create_chatflow(
        self,
        name: str,
        flow_data: str | None = None,
        description: str | None = None,
        chatflow_type: str = "CHATFLOW",
    ) -> ToolResult:
        raw = await self._client.create_chatflow(name, flow_data, description, chatflow_type)
        if _is_error(raw):
            return _fail(raw)
        cid = raw.get("id", "?") if isinstance(raw, dict) else "?"
        return _ok(f"Created chatflow {cid} ({name})", raw, chatflow_id=cid)

    async def update_chatflow(
        self,
        chatflow_id: str,
        name: str | None = None,
        flow_data: str | None = None,
        description: str | None = None,
        deployed: bool | None = None,
        is_public: bool | None = None,
        chatbot_config: str | None = None,
        category: str | None = None,
    ) -> ToolResult:
        raw = await self._client.update_chatflow(
            chatflow_id, name, flow_data, description, deployed, is_public, chatbot_config, category,
        )
        if _is_error(raw):
            return _fail(raw)
        label = raw.get("name", "?") if isinstance(raw, dict) else "?"
        return _ok(f"Updated chatflow {chatflow_id} ({label})", raw)

    async def delete_chatflow(self, chatflow_id: str) -> ToolResult:
        raw = await self._client.delete_chatflow(chatflow_id)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Deleted chatflow {chatflow_id}", raw)

    # ==================================================================
    # PREDICTION
    # ==================================================================

    async def create_prediction(
        self,
        chatflow_id: str,
        question: str,
        override_config: str | None = None,
        history: str | None = None,
        streaming: bool = False,
    ) -> ToolResult:
        raw = await self._client.create_prediction(chatflow_id, question, override_config, history, streaming)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Ran prediction for {chatflow_id} (streaming={streaming})", raw)

    # ==================================================================
    # ASSISTANTS
    # ==================================================================

    async def list_assistants(self) -> ToolResult:
        raw = await self._client.list_assistants()
        if _is_error(raw):
            return _fail(raw)
        count = len(raw) if isinstance(raw, list) else "?"
        return _ok(f"Listed {count} assistants", raw)

    async def get_assistant(self, assistant_id: str) -> ToolResult:
        raw = await self._client.get_assistant(assistant_id)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Fetched assistant {assistant_id}", raw)

    async def create_assistant(
        self,
        name: str,
        description: str = "",
        model: str = "gpt-4",
        instructions: str = "",
        credential: str | None = None,
    ) -> ToolResult:
        raw = await self._client.create_assistant(name, description, model, instructions, credential)
        if _is_error(raw):
            return _fail(raw)
        aid = raw.get("id", "?") if isinstance(raw, dict) else "?"
        return _ok(f"Created assistant {aid} ({name})", raw)

    async def update_assistant(
        self, assistant_id: str, details: str | None = None, credential: str | None = None,
    ) -> ToolResult:
        raw = await self._client.update_assistant(assistant_id, details, credential)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Updated assistant {assistant_id}", raw)

    async def delete_assistant(self, assistant_id: str) -> ToolResult:
        raw = await self._client.delete_assistant(assistant_id)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Deleted assistant {assistant_id}", raw)

    # ==================================================================
    # TOOLS
    # ==================================================================

    async def list_tools(self) -> ToolResult:
        raw = await self._client.list_tools()
        if _is_error(raw):
            return _fail(raw)
        count = len(raw) if isinstance(raw, list) else "?"
        return _ok(f"Listed {count} custom tools", raw)

    async def get_tool(self, tool_id: str) -> ToolResult:
        raw = await self._client.get_tool(tool_id)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Fetched tool {tool_id}", raw)

    async def create_tool(
        self,
        name: str,
        description: str,
        schema: str | None = None,
        func: str | None = None,
        color: str = "#4CAF50",
    ) -> ToolResult:
        raw = await self._client.create_tool(name, description, schema, func, color)
        if _is_error(raw):
            return _fail(raw)
        tid = raw.get("id", "?") if isinstance(raw, dict) else "?"
        return _ok(f"Created tool {tid} ({name})", raw)

    async def update_tool(
        self,
        tool_id: str,
        name: str | None = None,
        description: str | None = None,
        schema: str | None = None,
        func: str | None = None,
    ) -> ToolResult:
        raw = await self._client.update_tool(tool_id, name, description, schema, func)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Updated tool {tool_id}", raw)

    async def delete_tool(self, tool_id: str) -> ToolResult:
        raw = await self._client.delete_tool(tool_id)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Deleted tool {tool_id}", raw)

    # ==================================================================
    # VARIABLES
    # ==================================================================

    async def list_variables(self) -> ToolResult:
        raw = await self._client.list_variables()
        if _is_error(raw):
            return _fail(raw)
        count = len(raw) if isinstance(raw, list) else "?"
        return _ok(f"Listed {count} variables", raw)

    async def create_variable(self, name: str, value: str = "", var_type: str = "string") -> ToolResult:
        raw = await self._client.create_variable(name, value, var_type)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Created variable '{name}'", raw)

    async def update_variable(
        self, var_id: str, name: str | None = None, value: str | None = None, var_type: str | None = None,
    ) -> ToolResult:
        raw = await self._client.update_variable(var_id, name, value, var_type)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Updated variable {var_id}", raw)

    async def delete_variable(self, var_id: str) -> ToolResult:
        raw = await self._client.delete_variable(var_id)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Deleted variable {var_id}", raw)

    # ==================================================================
    # DOCUMENT STORE — management
    # ==================================================================

    async def list_document_stores(self) -> ToolResult:
        raw = await self._client.list_document_stores()
        if _is_error(raw):
            return _fail(raw)
        count = len(raw) if isinstance(raw, list) else "?"
        return _ok(f"Listed {count} document stores", raw)

    async def get_document_store(self, store_id: str) -> ToolResult:
        raw = await self._client.get_document_store(store_id)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Fetched document store {store_id}", raw)

    async def create_document_store(
        self,
        name: str,
        description: str = "",
        vector_store_config: str | None = None,
        embedding_config: str | None = None,
        record_manager_config: str | None = None,
    ) -> ToolResult:
        raw = await self._client.create_document_store(
            name, description, vector_store_config, embedding_config, record_manager_config,
        )
        if _is_error(raw):
            return _fail(raw)
        sid = raw.get("id", "?") if isinstance(raw, dict) else "?"
        return _ok(f"Created document store {sid} ({name})", raw)

    async def update_document_store(
        self,
        store_id: str,
        name: str | None = None,
        description: str | None = None,
        vector_store_config: str | None = None,
        embedding_config: str | None = None,
        record_manager_config: str | None = None,
    ) -> ToolResult:
        raw = await self._client.update_document_store(
            store_id, name, description, vector_store_config, embedding_config, record_manager_config,
        )
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Updated document store {store_id}", raw)

    async def delete_document_store(self, store_id: str) -> ToolResult:
        raw = await self._client.delete_document_store(store_id)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Deleted document store {store_id}", raw)

    # ==================================================================
    # DOCUMENT STORE — chunks
    # ==================================================================

    async def get_document_chunks(self, store_id: str, loader_id: str, page_no: int = 1) -> ToolResult:
        raw = await self._client.get_document_chunks(store_id, loader_id, page_no)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Fetched chunks for store {store_id}, loader {loader_id}, page {page_no}", raw)

    async def update_document_chunk(
        self,
        store_id: str,
        loader_id: str,
        chunk_id: str,
        page_content: str | None = None,
        metadata: str | None = None,
    ) -> ToolResult:
        raw = await self._client.update_document_chunk(store_id, loader_id, chunk_id, page_content, metadata)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Updated chunk {chunk_id} in store {store_id}", raw)

    async def delete_document_chunk(self, store_id: str, loader_id: str, chunk_id: str) -> ToolResult:
        raw = await self._client.delete_document_chunk(store_id, loader_id, chunk_id)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Deleted chunk {chunk_id} from store {store_id}", raw)

    # ==================================================================
    # DOCUMENT STORE — operations
    # ==================================================================

    async def upsert_document(
        self,
        store_id: str,
        loader: str | None = None,
        splitter: str | None = None,
        embedding: str | None = None,
        vector_store: str | None = None,
        record_manager: str | None = None,
        metadata: str | None = None,
        replace_existing: bool = False,
        doc_id: str | None = None,
    ) -> ToolResult:
        raw = await self._client.upsert_document(
            store_id, loader, splitter, embedding, vector_store, record_manager, metadata, replace_existing, doc_id,
        )
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Upserted document into store {store_id}", raw)

    async def refresh_document_store(self, store_id: str, items: str | None = None) -> ToolResult:
        raw = await self._client.refresh_document_store(store_id, items)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Refreshed document store {store_id}", raw)

    async def query_document_store(self, store_id: str, query: str) -> ToolResult:
        raw = await self._client.query_document_store(store_id, query)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Queried document store {store_id}", raw)

    async def delete_document_loader(self, store_id: str, loader_id: str) -> ToolResult:
        raw = await self._client.delete_document_loader(store_id, loader_id)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Deleted loader {loader_id} from store {store_id}", raw)

    async def delete_vectorstore_data(self, store_id: str) -> ToolResult:
        raw = await self._client.delete_vectorstore_data(store_id)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Deleted vector store data for store {store_id}", raw)

    # ==================================================================
    # CHAT MESSAGES
    # ==================================================================

    async def list_chat_messages(
        self,
        chatflow_id: str,
        chat_type: str | None = None,
        order: str | None = None,
        chat_id: str | None = None,
        session_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> ToolResult:
        raw = await self._client.list_chat_messages(
            chatflow_id, chat_type, order, chat_id, session_id, start_date, end_date,
        )
        if _is_error(raw):
            return _fail(raw)
        count = len(raw) if isinstance(raw, list) else "?"
        return _ok(f"Listed {count} chat messages for chatflow {chatflow_id}", raw)

    async def delete_chat_messages(
        self,
        chatflow_id: str,
        chat_id: str | None = None,
        chat_type: str | None = None,
        session_id: str | None = None,
        hard_delete: bool = False,
    ) -> ToolResult:
        raw = await self._client.delete_chat_messages(chatflow_id, chat_id, chat_type, session_id, hard_delete)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Deleted chat messages for chatflow {chatflow_id}", raw)

    # ==================================================================
    # FEEDBACK
    # ==================================================================

    async def list_feedback(
        self, chatflow_id: str, chat_id: str | None = None, sort_order: str = "asc",
    ) -> ToolResult:
        raw = await self._client.list_feedback(chatflow_id, chat_id, sort_order)
        if _is_error(raw):
            return _fail(raw)
        count = len(raw) if isinstance(raw, list) else "?"
        return _ok(f"Listed {count} feedback entries for chatflow {chatflow_id}", raw)

    async def create_feedback(
        self,
        chatflow_id: str,
        chat_id: str,
        message_id: str,
        rating: str,
        content: str = "",
    ) -> ToolResult:
        raw = await self._client.create_feedback(chatflow_id, chat_id, message_id, rating, content)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Created feedback for chatflow {chatflow_id}", raw)

    async def update_feedback(
        self, feedback_id: str, rating: str | None = None, content: str | None = None,
    ) -> ToolResult:
        raw = await self._client.update_feedback(feedback_id, rating, content)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Updated feedback {feedback_id}", raw)

    # ==================================================================
    # LEADS
    # ==================================================================

    async def list_leads(self, chatflow_id: str) -> ToolResult:
        raw = await self._client.list_leads(chatflow_id)
        if _is_error(raw):
            return _fail(raw)
        count = len(raw) if isinstance(raw, list) else "?"
        return _ok(f"Listed {count} leads for chatflow {chatflow_id}", raw)

    async def create_lead(
        self,
        chatflow_id: str,
        chat_id: str,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> ToolResult:
        raw = await self._client.create_lead(chatflow_id, chat_id, name, email, phone)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Created lead for chatflow {chatflow_id}", raw)

    # ==================================================================
    # VECTOR UPSERT
    # ==================================================================

    async def upsert_vector(
        self,
        chatflow_id: str,
        stop_node_id: str | None = None,
        override_config: str | None = None,
    ) -> ToolResult:
        raw = await self._client.upsert_vector(chatflow_id, stop_node_id, override_config)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Upserted vector for chatflow {chatflow_id}", raw)

    # ==================================================================
    # UPSERT HISTORY
    # ==================================================================

    async def list_upsert_history(
        self,
        chatflow_id: str,
        order: str = "ASC",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> ToolResult:
        raw = await self._client.list_upsert_history(chatflow_id, order, start_date, end_date)
        if _is_error(raw):
            return _fail(raw)
        count = len(raw) if isinstance(raw, list) else "?"
        return _ok(f"Listed {count} upsert history entries for chatflow {chatflow_id}", raw)

    async def delete_upsert_history(self, chatflow_id: str, ids: str | None = None) -> ToolResult:
        raw = await self._client.delete_upsert_history(chatflow_id, ids)
        if _is_error(raw):
            return _fail(raw)
        return _ok(f"Deleted upsert history for chatflow {chatflow_id}", raw)

    # ==================================================================
    # CREDENTIALS
    # ==================================================================

    async def list_credentials(self) -> ToolResult:
        raw = await self._client.list_credentials()
        if _is_error(raw):
            return _fail(raw)
        # Apply allowlist — strip any key not in _CRED_ALLOWLIST.
        if isinstance(raw, list):
            raw = [{k: v for k, v in entry.items() if k in _CRED_ALLOWLIST} for entry in raw if isinstance(entry, dict)]
        count = len(raw) if isinstance(raw, list) else "?"
        return _ok(f"Listed {count} credentials (allowlisted)", raw)

    async def create_credential(self, name: str, credential_name: str, encrypted_data: str) -> ToolResult:
        raw = await self._client.create_credential(name, credential_name, encrypted_data)
        if _is_error(raw):
            return _fail(raw)
        cid = raw.get("id", "?") if isinstance(raw, dict) else "?"
        return _ok(f"Created credential {cid} ({name})", raw)

    # ==================================================================
    # MARKETPLACE
    # ==================================================================

    async def list_marketplace_templates(self) -> ToolResult:
        raw = await self._client.list_marketplace_templates()
        if _is_error(raw):
            return _fail(raw)
        count = len(raw) if isinstance(raw, list) else "?"
        return _ok(f"Listed {count} marketplace templates", raw)

    # ==================================================================
    # ANCHOR DICTIONARY (M10.2b — tool #51)
    # ==================================================================

    async def get_anchor_dictionary(self, node_type: str) -> ToolResult:
        """Return canonical anchor dictionary for a node type.

        Delegates to the injected ``anchor_dict_getter`` callable (backed by
        ``AnchorDictionaryStore.get()``).  Returns input/output anchors with
        exact names, types, and compatibility lists.
        """
        if self._anchor_dict_getter is None:
            return ToolResult(
                ok=False,
                summary=f"Anchor dictionary unavailable (no getter configured)",
                facts={},
                data=None,
                error={
                    "type": "ConfigurationError",
                    "message": "No anchor_dict_getter provided to FlowiseMCPTools",
                    "detail": "Wire AnchorDictionaryStore via FlowiseKnowledgeProvider",
                },
                artifacts=None,
            )

        entry = self._anchor_dict_getter(node_type)
        if entry is None:
            return ToolResult(
                ok=False,
                summary=f"No anchor dictionary for '{node_type}'",
                facts={},
                data=None,
                error={
                    "type": "NotFound",
                    "message": f"Node type '{node_type}' not found in anchor dictionary",
                    "detail": "Check spelling or run: python -m flowise_dev_agent.knowledge.refresh --nodes",
                },
                artifacts=None,
            )

        inputs = entry.get("input_anchors", [])
        outputs = entry.get("output_anchors", [])
        input_names = ", ".join(a["name"] for a in inputs)
        output_names = ", ".join(a["name"] for a in outputs)
        summary = (
            f"{node_type}: {len(inputs)} input{'s' if len(inputs) != 1 else ''} "
            f"({input_names}), "
            f"{len(outputs)} output{'s' if len(outputs) != 1 else ''} "
            f"({output_names})"
        )

        return _ok(summary, entry)
