"""Async Flowise REST API client using httpx."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from flowise_dev_agent.client.config import Settings

logger = logging.getLogger("flowise_dev_agent.client")


class FlowiseClient:
    """Thin async wrapper around the entire Flowise REST API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            headers=settings.headers,
            timeout=httpx.Timeout(settings.timeout, connect=10.0),
            proxy=None,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            r = await self._client.get(path, params=params)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            logger.error("GET %s -> %s", path, e.response.status_code)
            return {"error": f"HTTP {e.response.status_code}", "detail": e.response.text}
        except Exception as e:
            logger.error("GET %s failed: %s", path, e)
            return {"error": str(e)}

    async def _post(self, path: str, payload: dict | None = None) -> Any:
        try:
            r = await self._client.post(path, json=payload or {})
            r.raise_for_status()
            return r.json() if r.text.strip() else {"success": True}
        except httpx.HTTPStatusError as e:
            logger.error("POST %s -> %s", path, e.response.status_code)
            return {"error": f"HTTP {e.response.status_code}", "detail": e.response.text}
        except Exception as e:
            logger.error("POST %s failed: %s", path, e)
            return {"error": str(e)}

    async def _put(self, path: str, payload: dict | None = None) -> Any:
        try:
            r = await self._client.put(path, json=payload or {})
            r.raise_for_status()
            return r.json() if r.text.strip() else {"success": True}
        except httpx.HTTPStatusError as e:
            logger.error("PUT %s -> %s", path, e.response.status_code)
            return {"error": f"HTTP {e.response.status_code}", "detail": e.response.text}
        except Exception as e:
            logger.error("PUT %s failed: %s", path, e)
            return {"error": str(e)}

    async def _delete(self, path: str) -> Any:
        try:
            r = await self._client.delete(path)
            r.raise_for_status()
            return r.json() if r.text.strip() else {"success": True}
        except httpx.HTTPStatusError as e:
            logger.error("DELETE %s -> %s", path, e.response.status_code)
            return {"error": f"HTTP {e.response.status_code}", "detail": e.response.text}
        except Exception as e:
            logger.error("DELETE %s failed: %s", path, e)
            return {"error": str(e)}

    async def _patch(self, path: str, payload: dict | None = None) -> Any:
        try:
            r = await self._client.patch(path, json=payload or {})
            r.raise_for_status()
            return r.json() if r.text.strip() else {"success": True}
        except httpx.HTTPStatusError as e:
            logger.error("PATCH %s -> %s", path, e.response.status_code)
            return {"error": f"HTTP {e.response.status_code}", "detail": e.response.text}
        except Exception as e:
            logger.error("PATCH %s failed: %s", path, e)
            return {"error": str(e)}

    @staticmethod
    def _parse_json_str(value: str | None) -> Any:
        """Safely parse a JSON string argument, returning {} on failure."""
        if not value:
            return {}
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}

    # ==================================================================
    # SYSTEM
    # ==================================================================

    async def ping(self) -> Any:
        try:
            r = await self._client.get("/ping")
            return {"status": r.text.strip()}
        except Exception as e:
            return {"error": str(e)}

    # ==================================================================
    # NODES (undocumented but essential)
    # ==================================================================

    async def list_nodes(self) -> Any:
        return await self._get("/nodes")

    async def get_node(self, name: str) -> Any:
        return await self._get(f"/nodes/{name}")

    # ==================================================================
    # CHATFLOWS
    # ==================================================================

    async def list_chatflows(self) -> Any:
        return await self._get("/chatflows")

    async def get_chatflow(self, chatflow_id: str) -> Any:
        return await self._get(f"/chatflows/{chatflow_id}")

    async def get_chatflow_by_apikey(self, apikey: str) -> Any:
        return await self._get(f"/chatflows/apikey/{apikey}")

    async def create_chatflow(
        self,
        name: str,
        flow_data: str | None = None,
        description: str | None = None,
        chatflow_type: str = "CHATFLOW",
    ) -> Any:
        payload: dict[str, Any] = {"name": name, "type": chatflow_type}
        if description:
            payload["description"] = description
        if flow_data:
            payload["flowData"] = flow_data
        return await self._post("/chatflows", payload)

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
    ) -> Any:
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if flow_data is not None:
            payload["flowData"] = flow_data
        if description is not None:
            payload["description"] = description
        if deployed is not None:
            payload["deployed"] = deployed
        if is_public is not None:
            payload["isPublic"] = is_public
        if chatbot_config is not None:
            payload["chatbotConfig"] = chatbot_config
        if category is not None:
            payload["category"] = category
        return await self._put(f"/chatflows/{chatflow_id}", payload)

    async def delete_chatflow(self, chatflow_id: str) -> Any:
        return await self._delete(f"/chatflows/{chatflow_id}")

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
    ) -> Any:
        payload: dict[str, Any] = {"question": question, "streaming": streaming}
        if override_config:
            payload["overrideConfig"] = self._parse_json_str(override_config)
        if history:
            payload["history"] = self._parse_json_str(history)
        return await self._post(f"/prediction/{chatflow_id}", payload)

    # ==================================================================
    # ASSISTANTS
    # ==================================================================

    async def list_assistants(self) -> Any:
        return await self._get("/assistants")

    async def get_assistant(self, assistant_id: str) -> Any:
        return await self._get(f"/assistants/{assistant_id}")

    async def create_assistant(
        self,
        name: str,
        description: str = "",
        model: str = "gpt-4",
        instructions: str = "",
        credential: str | None = None,
    ) -> Any:
        details = json.dumps({
            "name": name,
            "description": description,
            "model": model,
            "instructions": instructions,
            "temperature": 0.7,
            "top_p": 1.0,
            "tools": [],
            "tool_resources": {},
        })
        payload: dict[str, Any] = {"details": details}
        if credential:
            payload["credential"] = credential
        return await self._post("/assistants", payload)

    async def update_assistant(self, assistant_id: str, details: str | None = None, credential: str | None = None) -> Any:
        payload: dict[str, Any] = {}
        if details:
            parsed = self._parse_json_str(details)
            payload["details"] = json.dumps(parsed) if isinstance(parsed, dict) else details
        if credential:
            payload["credential"] = credential
        return await self._put(f"/assistants/{assistant_id}", payload)

    async def delete_assistant(self, assistant_id: str) -> Any:
        return await self._delete(f"/assistants/{assistant_id}")

    # ==================================================================
    # TOOLS
    # ==================================================================

    async def list_tools(self) -> Any:
        return await self._get("/tools")

    async def get_tool(self, tool_id: str) -> Any:
        return await self._get(f"/tools/{tool_id}")

    async def create_tool(
        self,
        name: str,
        description: str,
        schema: str | None = None,
        func: str | None = None,
        color: str = "#4CAF50",
    ) -> Any:
        payload: dict[str, Any] = {"name": name, "description": description, "color": color}
        if schema:
            payload["schema"] = schema
        if func:
            payload["func"] = func
        return await self._post("/tools", payload)

    async def update_tool(
        self,
        tool_id: str,
        name: str | None = None,
        description: str | None = None,
        schema: str | None = None,
        func: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if schema is not None:
            payload["schema"] = schema
        if func is not None:
            payload["func"] = func
        return await self._put(f"/tools/{tool_id}", payload)

    async def delete_tool(self, tool_id: str) -> Any:
        return await self._delete(f"/tools/{tool_id}")

    # ==================================================================
    # VARIABLES
    # ==================================================================

    async def list_variables(self) -> Any:
        return await self._get("/variables")

    async def create_variable(self, name: str, value: str = "", var_type: str = "string") -> Any:
        return await self._post("/variables", {"name": name, "value": value, "type": var_type})

    async def update_variable(
        self,
        var_id: str,
        name: str | None = None,
        value: str | None = None,
        var_type: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if value is not None:
            payload["value"] = value
        if var_type is not None:
            payload["type"] = var_type
        return await self._put(f"/variables/{var_id}", payload)

    async def delete_variable(self, var_id: str) -> Any:
        return await self._delete(f"/variables/{var_id}")

    # ==================================================================
    # DOCUMENT STORE
    # ==================================================================

    async def list_document_stores(self) -> Any:
        return await self._get("/document-store/store")

    async def get_document_store(self, store_id: str) -> Any:
        return await self._get(f"/document-store/store/{store_id}")

    async def create_document_store(
        self,
        name: str,
        description: str = "",
        vector_store_config: str | None = None,
        embedding_config: str | None = None,
        record_manager_config: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"name": name, "description": description}
        if vector_store_config:
            payload["vectorStoreConfig"] = vector_store_config
        if embedding_config:
            payload["embeddingConfig"] = embedding_config
        if record_manager_config:
            payload["recordManagerConfig"] = record_manager_config
        return await self._post("/document-store/store", payload)

    async def update_document_store(
        self,
        store_id: str,
        name: str | None = None,
        description: str | None = None,
        vector_store_config: str | None = None,
        embedding_config: str | None = None,
        record_manager_config: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if vector_store_config is not None:
            payload["vectorStoreConfig"] = vector_store_config
        if embedding_config is not None:
            payload["embeddingConfig"] = embedding_config
        if record_manager_config is not None:
            payload["recordManagerConfig"] = record_manager_config
        return await self._put(f"/document-store/store/{store_id}", payload)

    async def delete_document_store(self, store_id: str) -> Any:
        return await self._delete(f"/document-store/store/{store_id}")

    # ==================================================================
    # DOCUMENT STORE - CHUNKS
    # ==================================================================

    async def get_document_chunks(self, store_id: str, loader_id: str, page_no: int = 1) -> Any:
        return await self._get(f"/document-store/chunks/{store_id}/{loader_id}/{page_no}")

    async def update_document_chunk(
        self,
        store_id: str,
        loader_id: str,
        chunk_id: str,
        page_content: str | None = None,
        metadata: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {}
        if page_content is not None:
            payload["pageContent"] = page_content
        if metadata is not None:
            payload["metadata"] = self._parse_json_str(metadata)
        return await self._put(f"/document-store/chunks/{store_id}/{loader_id}/{chunk_id}", payload)

    async def delete_document_chunk(self, store_id: str, loader_id: str, chunk_id: str) -> Any:
        return await self._delete(f"/document-store/chunks/{store_id}/{loader_id}/{chunk_id}")

    # ==================================================================
    # DOCUMENT STORE - OPERATIONS
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
    ) -> Any:
        payload: dict[str, Any] = {"replaceExisting": replace_existing}
        if doc_id:
            payload["docId"] = doc_id
        if loader:
            payload["loader"] = self._parse_json_str(loader)
        if splitter:
            payload["splitter"] = self._parse_json_str(splitter)
        if embedding:
            payload["embedding"] = self._parse_json_str(embedding)
        if vector_store:
            payload["vectorStore"] = self._parse_json_str(vector_store)
        if record_manager:
            payload["recordManager"] = self._parse_json_str(record_manager)
        if metadata:
            payload["metadata"] = self._parse_json_str(metadata)
        return await self._post(f"/document-store/upsert/{store_id}", payload)

    async def refresh_document_store(self, store_id: str, items: str | None = None) -> Any:
        payload: dict[str, Any] = {}
        if items:
            payload["items"] = self._parse_json_str(items)
        return await self._post(f"/document-store/refresh/{store_id}", payload)

    async def query_document_store(self, store_id: str, query: str) -> Any:
        return await self._post("/document-store/vectorstore/query", {"storeId": store_id, "query": query})

    async def delete_document_loader(self, store_id: str, loader_id: str) -> Any:
        return await self._delete(f"/document-store/loader/{store_id}/{loader_id}")

    async def delete_vectorstore_data(self, store_id: str) -> Any:
        return await self._delete(f"/document-store/vectorstore/{store_id}")

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
    ) -> Any:
        params: dict[str, str] = {}
        if chat_type:
            params["chatType"] = chat_type
        if order:
            params["order"] = order
        if chat_id:
            params["chatId"] = chat_id
        if session_id:
            params["sessionId"] = session_id
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        return await self._get(f"/chatmessage/{chatflow_id}", params=params or None)

    async def delete_chat_messages(
        self,
        chatflow_id: str,
        chat_id: str | None = None,
        chat_type: str | None = None,
        session_id: str | None = None,
        hard_delete: bool = False,
    ) -> Any:
        params: dict[str, str] = {}
        if chat_id:
            params["chatId"] = chat_id
        if chat_type:
            params["chatType"] = chat_type
        if session_id:
            params["sessionId"] = session_id
        if hard_delete:
            params["hardDelete"] = "true"
        try:
            r = await self._client.delete(f"/chatmessage/{chatflow_id}", params=params or None)
            r.raise_for_status()
            return {"success": True}
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}", "detail": e.response.text}
        except Exception as e:
            return {"error": str(e)}

    # ==================================================================
    # FEEDBACK
    # ==================================================================

    async def list_feedback(self, chatflow_id: str, chat_id: str | None = None, sort_order: str = "asc") -> Any:
        params: dict[str, str] = {"sortOrder": sort_order}
        if chat_id:
            params["chatId"] = chat_id
        return await self._get(f"/feedback/{chatflow_id}", params=params)

    async def create_feedback(
        self,
        chatflow_id: str,
        chat_id: str,
        message_id: str,
        rating: str,
        content: str = "",
    ) -> Any:
        return await self._post("/feedback", {
            "chatflowid": chatflow_id,
            "chatId": chat_id,
            "messageId": message_id,
            "rating": rating,
            "content": content,
        })

    async def update_feedback(self, feedback_id: str, rating: str | None = None, content: str | None = None) -> Any:
        payload: dict[str, Any] = {}
        if rating is not None:
            payload["rating"] = rating
        if content is not None:
            payload["content"] = content
        return await self._put(f"/feedback/{feedback_id}", payload)

    # ==================================================================
    # LEADS
    # ==================================================================

    async def list_leads(self, chatflow_id: str) -> Any:
        return await self._get(f"/leads/{chatflow_id}")

    async def create_lead(
        self,
        chatflow_id: str,
        chat_id: str,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"chatflowid": chatflow_id, "chatId": chat_id}
        if name:
            payload["name"] = name
        if email:
            payload["email"] = email
        if phone:
            payload["phone"] = phone
        return await self._post("/leads", payload)

    # ==================================================================
    # VECTOR UPSERT (chatflow-level)
    # ==================================================================

    async def upsert_vector(
        self,
        chatflow_id: str,
        stop_node_id: str | None = None,
        override_config: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {}
        if stop_node_id:
            payload["stopNodeId"] = stop_node_id
        if override_config:
            payload["overrideConfig"] = self._parse_json_str(override_config)
        return await self._post(f"/vector/upsert/{chatflow_id}", payload)

    # ==================================================================
    # UPSERT HISTORY
    # ==================================================================

    async def list_upsert_history(
        self,
        chatflow_id: str,
        order: str = "ASC",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Any:
        params: dict[str, str] = {"order": order}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        return await self._get(f"/upsert-history/{chatflow_id}", params=params)

    async def delete_upsert_history(self, chatflow_id: str, ids: str | None = None) -> Any:
        payload: dict[str, Any] = {}
        if ids:
            payload["ids"] = self._parse_json_str(ids)
        return await self._patch(f"/upsert-history/{chatflow_id}", payload)

    # ==================================================================
    # CREDENTIALS (undocumented)
    # ==================================================================

    async def list_credentials(self) -> Any:
        return await self._get("/credentials")

    async def create_credential(
        self,
        name: str,
        credential_name: str,
        encrypted_data: str,
    ) -> Any:
        return await self._post("/credentials", {
            "name": name,
            "credentialName": credential_name,
            "encryptedData": encrypted_data,
        })

    # ==================================================================
    # MARKETPLACE (undocumented)
    # ==================================================================

    async def list_marketplace_templates(self) -> Any:
        return await self._get("/marketplaces/templates")
