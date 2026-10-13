import logging
import mimetypes
import time
import uuid
import requests
import base64
import json
from urllib.parse import quote
from typing import Any, Optional
from datetime import datetime, timezone

from app.adapters.chat.base import ChatAdapter
from app.adapters.chat.base import CapabilityNotSupported, UploadFileNotFound
from app.connections.browser_token import resolve_browser_token_strategy
from app.models.conversation import ConversationMessage, NormalizedConversation, RAGEvidence
from app.rag import extract_rag_evidence, get_values_by_path

logger = logging.getLogger(__name__)

import os

import re


def _upload_bytes(upload: dict[str, Any]) -> bytes:
    data = upload.get("buffer", upload.get("data", upload.get("content", b"")))
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, str):
        try:
            return base64.b64decode(data)
        except Exception:
            return data.encode("utf-8")
    return b""


def _upload_filename(upload: Any) -> str:
    if isinstance(upload, dict):
        return os.path.basename(str(upload.get("filename") or upload.get("name") or "image"))
    return os.path.basename(str(upload))


def _transcript_attachment_name(upload: Any) -> str:
    if isinstance(upload, dict):
        return os.path.basename(str(upload.get("filename") or upload.get("name") or upload.get("file_name") or "upload"))
    return str(upload)


def _transcript_attachment_names(attachments: Optional[list[Any]]) -> list[str] | None:
    if not attachments:
        return None
    return [_transcript_attachment_name(attachment) for attachment in attachments]


def _requests_file_tuple(upload: Any) -> tuple[str, Any, str] | tuple[str, Any]:
    if isinstance(upload, dict):
        name = _upload_filename(upload)
        mime_type = upload.get("mime_type") or upload.get("mimeType") or upload.get("type") or mimetypes.guess_type(name)[0]
        return name, _upload_bytes(upload), mime_type or "application/octet-stream"
    return os.path.basename(str(upload)), open(upload, "rb")


def _parse_path(path: str) -> list:
    path = re.sub(r'\[(\d+)\]', r'.\1', path)
    return [int(k) if isinstance(k, str) and k.isdigit() else k for k in path.split('.') if k]

def set_by_path(d: dict, path: str, value: Any):
    keys = _parse_path(path)
    if not keys:
        return
    current = d
    for i, key in enumerate(keys[:-1]):
        next_key = keys[i+1]
        is_next_list = isinstance(next_key, int)
        
        if isinstance(current, dict):
            if key not in current:
                current[key] = [] if is_next_list else {}
            current = current[key]
        elif isinstance(current, list):
            while len(current) <= key:
                current.append(None)
            if current[key] is None:
                current[key] = [] if is_next_list else {}
            current = current[key]
            
    last_key = keys[-1]
    if isinstance(current, dict):
        current[last_key] = value
    elif isinstance(current, list):
        while len(current) <= last_key:
            current.append(None)
        current[last_key] = value

def get_by_path(d: Any, path: str, default: Any = None) -> Any:
    if not path:
        return default
    keys = _parse_path(path)
    current = d
    for i, key in enumerate(keys):
        if isinstance(current, dict):
            if isinstance(key, str) and key.endswith("[]"):
                actual_key = key[:-2]
                if actual_key in current and isinstance(current[actual_key], list):
                    remaining_path = ".".join(str(k) for k in keys[i+1:]) if i + 1 < len(keys) else ""
                    if not remaining_path:
                        return current[actual_key]
                    for item in current[actual_key]:
                        val = get_by_path(item, remaining_path, default=None)
                        if val is not None and val != "":
                            return val
                    return default
                else:
                    return default
            elif key in current:
                current = current[key]
            else:
                return default
        elif isinstance(current, list):
            if isinstance(key, int) and 0 <= key < len(current):
                current = current[key]
            else:
                return default
        else:
            return default
    return current


class RestAdapterTimeoutError(Exception):
    pass


def _log_raw_response_before_parsing(label: str, response: requests.Response) -> None:
    """
    Safe response-boundary diagnostics.

    Do not log full provider response bodies by default. Client responses can
    contain customer data, retrieved documents, credentials, or internal
    provider metadata.
    """
    content_type = response.headers.get("content-type", "")
    response_size = len(response.content or b"")
    logger.warning(
        "[PROVIDER RESPONSE BEFORE PARSING] %s status=%s content_type=%s size_bytes=%s",
        label,
        response.status_code,
        content_type,
        response_size,
    )




def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first_present(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _component(type_name: str, value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"type": value.get("type", type_name), **value}
    if type_name == "button":
        return {"type": "button", "label": str(value)}
    if type_name == "image":
        return {"type": "image", "url": str(value), "name": os.path.basename(str(value))}
    if type_name == "attachment":
        return {"type": "attachment", "url": str(value), "name": os.path.basename(str(value))}
    return {"type": type_name, "value": value}


def _attachment_ref(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("url", "path", "href", "src", "file", "file_url", "download_url", "name", "filename"):
            ref = value.get(key)
            if ref:
                return str(ref)
    return None


def _resolve_env_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("env:"):
        return os.environ.get(value[4:])
    return value


def _substitute_correlation(value: Any, correlation_id: str) -> Any:
    if isinstance(value, str):
        return value.replace("{correlation_id}", correlation_id)
    if isinstance(value, dict):
        return {key: _substitute_correlation(item, correlation_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute_correlation(item, correlation_id) for item in value]
    return value



def _extract_response_components(data: dict[str, Any], response_mapping: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Preserve provider-returned UI metadata without changing execution behavior.

    This intentionally supports only common/configured response fields and stores
    them as universal presentation metadata for EvaluationService/ConversationTurn.
    """
    components: list[dict[str, Any]] = []
    attachments: list[str] = []

    def _table_component(source: dict[str, Any]) -> dict[str, Any] | None:
        columns = source.get("columns")
        rows = source.get("rows")
        if not isinstance(columns, list) or not isinstance(rows, list) or not columns:
            return None
        headers = [str(column) for column in columns]
        normalized_rows = [
            [row.get(column) for column in columns] if isinstance(row, dict) else row
            for row in rows
        ]
        component = {
            "type": "table",
            "headers": headers,
            "rows": normalized_rows,
        }
        for key in ("title", "body", "display_mode", "row_count", "has_more"):
            if key in source:
                component[key] = source[key]
        return component

    mapping_specs = [
        ("components_field", "component"),
        ("buttons_field", "button"),
        ("button_field", "button"),
        ("tables_field", "table"),
        ("table_field", "table"),
        ("forms_field", "form"),
        ("cards_field", "card"),
        ("card_field", "card"),
        ("attachments_field", "attachment"),
        ("images_field", "image"),
    ]
    for field_name, type_name in mapping_specs:
        path = response_mapping.get(field_name)
        if not path:
            continue
        for item in _as_list(get_by_path(data, path)):
            if item is None:
                continue
            components.append(_component(type_name, item))
            if type_name in {"attachment", "image"}:
                ref = _attachment_ref(item)
                if ref:
                    attachments.append(ref)

    component_values = _first_present(data, ["components", "rich_components", "ui_components", "blocks"])
    for item in _as_list(component_values):
        if item is not None:
            components.append(_component("component", item))

    for key, type_name in [
        ("buttons", "button"),
        ("quick_replies", "button"),
        ("options", "button"),
        ("tables", "table"),
        ("forms", "form"),
        ("cards", "card"),
    ]:
        for item in _as_list(data.get(key)):
            if item is not None:
                components.append(_component(type_name, item))

    table = _table_component(data)
    if table:
        components.append(table)

    for section in _as_list(data.get("sections")):
        if isinstance(section, dict):
            section_table = _table_component(section)
            if section_table:
                components.append(section_table)

    clarification = data.get("clarification")
    if isinstance(clarification, dict):
        for option in _as_list(clarification.get("options")):
            if option is not None:
                components.append(_component("button", option))

    for prompt in _as_list(data.get("suggested_prompts")):
        if prompt is not None:
            components.append({
                "type": "button",
                "subtype": "quick_reply",
                "label": str(prompt),
                "message": str(prompt),
            })

    for key, type_name in [
        ("attachments", "attachment"),
        ("files", "attachment"),
        ("images", "image"),
    ]:
        for item in _as_list(data.get(key)):
            if item is None:
                continue
            components.append(_component(type_name, item))
            ref = _attachment_ref(item)
            if ref:
                attachments.append(ref)

    block = data.get("block")
    if isinstance(block, dict) and block.get("type") not in (None, "text"):
        components.append(_component(block.get("type", "component"), block))

    deduped_attachments: list[str] = []
    seen: set[str] = set()
    for attachment in attachments:
        if attachment not in seen:
            seen.add(attachment)
            deduped_attachments.append(attachment)

    return components, deduped_attachments


def _first_by_paths(data: dict[str, Any], paths: list[str]) -> Any:
    for path in paths:
        value = get_by_path(data, path)
        if value is not None:
            return value
    return None


def _response_mapping_paths(
    response_mapping: dict[str, Any],
    mapping_key: str,
    aliases: list[str],
) -> list[str]:
    configured = response_mapping.get(mapping_key)
    paths: list[str] = []
    if isinstance(configured, list):
        paths.extend(str(path) for path in configured if path)
    elif configured:
        paths.append(str(configured))
    for alias in aliases:
        if alias not in paths:
            paths.append(alias)
    return paths


def _normalize_rest_response(data: dict[str, Any], response_mapping: dict[str, Any]) -> dict[str, Any]:
    reply_paths = _response_mapping_paths(
        response_mapping,
        "reply_field",
        [
            response_mapping.get("text_path") or "",
            "reply",
            "answer",
            "text",
            "response",
            "message",
        ],
    )
    conversation_id_paths = _response_mapping_paths(
        response_mapping,
        "conversation_id_field",
        ["conversation_id", "session_id"],
    )
    components, attachments = _extract_response_components(data, response_mapping)
    return {
        "reply": _first_by_paths(data, reply_paths),
        "conversation_id": _first_by_paths(data, conversation_id_paths),
        "buttons": [
            component for component in components
            if component.get("type") == "button" and component.get("subtype") != "quick_reply"
        ],
        "table": next((component for component in components if component.get("type") == "table"), None),
        "cards": [component for component in components if component.get("type") == "card"],
        "attachments": attachments,
        "components": components,
        "raw_response": data,
    }


class RestChatAdapter(ChatAdapter):
    """
    Generic REST Adapter.
    Configurable request and response mapping.
    """
    def __init__(self, config: dict[str, Any], evaluation_session: Any | None = None):
        self.config = config
        self.evaluation_session = evaluation_session
        self.session_id = str(uuid.uuid4())
        self._remote_session_id = None
        self.run_id = str(uuid.uuid4())
        self.transcript: list[ConversationMessage] = []
        self._turn_index = 0
        self._http_request_count = 0
        self._browser_token_auth: Optional[dict[str, Any]] = None
        self._browser_token_header_name: Optional[str] = None
        self._browser_token_header_format: str = "Bearer {token}"
        self._browser_token_exp: Optional[int] = None
        self._browser_token_iat: Optional[int] = None
        self._owned_browser_session: Optional[Any] = None
        
        # Determine mode
        self.base_url = self.config.get("base_url")
        self.session_config = self.config.get("session")
        self.send_config = self.config.get("send")
        self.receive_config = self.config.get("receive")
        
        self.is_multi_step = bool(self.send_config and self.receive_config)
        
        self.endpoint = self.config.get("endpoint")
        if self.endpoint and self.endpoint.startswith("env:"):
            self.endpoint = os.environ.get(self.endpoint[4:])
            
        if not self.is_multi_step and not self.endpoint:
            raise ValueError("RestChatAdapter requires either 'endpoint' or multi-step ('send' and 'receive') configuration.")

        self.method = self.config.get("method", "POST")
        
        # Resolve headers
        raw_headers = self.config.get("headers", {})
        self.headers = {}
        for k, v in raw_headers.items():
            if isinstance(v, str) and v.startswith("env:"):
                env_val = os.environ.get(v[4:])
                if env_val:
                    self.headers[k] = env_val
                else:
                    logger.warning(f"Environment variable {v[4:]} for header {k} not found.")
            else:
                self.headers[k] = v
                
        # Process generic auth
        from app.adapters.auth import create_auth_provider
        from app.session import BrowserSession
        auth = self.config.get("auth", {})
        browser_session = (
            self.evaluation_session.browser_session
            if self.evaluation_session is not None
            else None
        )
        if browser_session is None and auth.get("type") == "browser_token":
            effective_storage_state = auth.get("storage_state") or self.config.get("storage_state")
            browser_session = BrowserSession(
                storage_state=effective_storage_state,
                connection_config=self.config,
            )
            self._owned_browser_session = browser_session
        self.auth_provider = create_auth_provider(
            self.config,
            browser_session=browser_session,
        )
        if self.evaluation_session is not None:
            self.evaluation_session.auth_provider = self.auth_provider
        
        print("[REST AUTH DEBUG]")
        print(f"auth configured: {'YES' if auth else 'NO'}")
        print(f"api_key_header: {self.config.get('api_key_header', 'NOT SET')}")
        
        if self.auth_provider:
            auth_headers = self.auth_provider.get_headers()
            self.headers.update(auth_headers)
            print(f"x-goog-api-key: {'PRESENT' if 'x-goog-api-key' in auth_headers else 'ABSENT'}")
        else:
            print("x-goog-api-key: ABSENT")


        # Mapping config
        self.has_explicit_mapping = "request_mapping" in self.config
        self.request_mapping = self.config.get("request_mapping", {})
        if self.has_explicit_mapping:
            self.req_msg_field = self.request_mapping.get("message_field")
            self.req_session_field = self.request_mapping.get("session_id_field")
        else:
            self.req_msg_field = "message"
            self.req_session_field = None
        self.req_user_id_field = self.request_mapping.get("user_id_field")
        self.req_conversation_id_field = self.request_mapping.get("conversation_id_field")
            
        self.req_static_fields = self.request_mapping.get("static_fields", {})
        
        self.response_mapping = self.config.get("response_mapping", {})
        self.res_reply_field = self.response_mapping.get("text_path", self.response_mapping.get("reply_field", "reply"))
        self.res_conversation_id_field = self.response_mapping.get("conversation_id_field")
        self.res_tool_calls_field = self.response_mapping.get("tool_calls_field", None)

    def _resolve_url(self, path: str) -> str:
        if self.base_url:
            url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        else:
            url = path
        if self._remote_session_id:
            url = url.replace("{session_token}", self._remote_session_id)
        return url

    def _request(self, request_label: str, **kwargs) -> requests.Response:
        if self.auth_provider:
            self.auth_provider.refresh_if_needed()
            if "headers" in kwargs and kwargs["headers"] is not None:
                kwargs["headers"].update(self.auth_provider.get_headers())
            else:
                self.headers.update(self.auth_provider.get_headers())
                kwargs["headers"] = self.headers
                
        import json
        print('=== REQUEST AUDIT ===')
        print(f'Final URL: {kwargs.get("url")}')
        print(f'Final method: {kwargs.get("method")}')
        print(f'Final headers: {kwargs.get("headers")}')
        print(f'Final JSON body: {json.dumps(kwargs.get("json")) if kwargs.get("json") else None}')
        print(f'Final data body: {kwargs.get("data")}')
        print(f'params: {kwargs.get("params")}')
        print('=====================')
        return requests.request(**kwargs)

    def _extract_rag_evidence_for_response(self, response_data: dict[str, Any]) -> Optional[RAGEvidence]:
        rag_config = self.config.get("rag_config") or self.config.get("rag") or {}
        if not rag_config:
            return extract_rag_evidence(response_data, self.config)
        if rag_config.get("enabled") is False:
            return None

        mode = rag_config.get("mode")
        if mode == "separate_api":
            return self._fetch_rag_evidence_from_api(response_data, rag_config)

        return extract_rag_evidence(response_data, self.config)

    def _fetch_rag_evidence_from_api(self, response_data: dict[str, Any], rag_config: dict[str, Any]) -> Optional[RAGEvidence]:
        correlation_path = rag_config.get("correlation_path")
        evidence_request = rag_config.get("evidence_request") or {}
        evidence_url = evidence_request.get("url")
        if not correlation_path or not evidence_url:
            return None

        correlation_values = get_values_by_path(response_data, correlation_path)
        if not correlation_values:
            return None

        correlation_id = str(correlation_values[0])
        if not correlation_id:
            return None

        method = str(evidence_request.get("method", "GET")).upper()
        if method not in {"GET", "POST"}:
            logger.warning("RAG evidence request skipped: unsupported method %s", method)
            return None

        url = _substitute_correlation(str(evidence_url), quote(correlation_id, safe=""))
        headers = self._build_rag_evidence_headers(evidence_request)
        params = _substitute_correlation(evidence_request.get("params"), correlation_id)
        json_payload = _substitute_correlation(
            evidence_request.get("json", evidence_request.get("body")),
            correlation_id,
        )
        timeout = evidence_request.get("timeout", evidence_request.get("timeout_seconds", self.config.get("timeout", 30)))

        try:
            request_kwargs: dict[str, Any] = {
                "method": method,
                "url": url,
                "headers": headers,
                "timeout": timeout,
            }
            if params is not None:
                request_kwargs["params"] = params
            if method == "POST" and json_payload is not None:
                request_kwargs["json"] = json_payload

            response = self._request(request_label="rag_evidence", **request_kwargs)
            response.raise_for_status()
            evidence_data = response.json()
            if not isinstance(evidence_data, dict):
                return None
            return extract_rag_evidence(evidence_data, {"rag_config": rag_config})
        except requests.exceptions.Timeout:
            logger.warning("RAG evidence request timed out.")
        except requests.exceptions.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
            logger.warning("RAG evidence request failed with HTTP status %s.", status_code)
        except ValueError:
            logger.warning("RAG evidence request returned malformed JSON.")
        except requests.exceptions.RequestException:
            logger.warning("RAG evidence request failed.")
        except Exception:
            logger.warning("RAG evidence extraction failed.")
        return None

    def _build_rag_evidence_headers(self, evidence_request: dict[str, Any]) -> dict[str, Any]:
        use_same_auth = evidence_request.get("use_same_auth", True)
        headers = dict(self.headers) if use_same_auth else {}

        custom_headers = evidence_request.get("headers") or {}
        for key, value in custom_headers.items():
            resolved = _resolve_env_value(value)
            if resolved is not None:
                headers[key] = resolved

        auth = evidence_request.get("auth") or {}
        if not auth:
            return headers

        auth_type = auth.get("type")
        auth_value = _resolve_env_value(auth.get("value"))
        if not auth_value:
            return headers

        if auth_type == "bearer":
            header_name = auth.get("header_name", "Authorization")
            header_format = auth.get("header_format", "Bearer {token}")
            headers[header_name] = header_format.replace("{token}", str(auth_value))
        elif auth_type == "api_key":
            header_name = auth.get("header_name") or auth.get("api_key_header") or evidence_request.get("api_key_header") or "Authorization"
            headers[header_name] = auth_value

        return headers

    def connect(self) -> None:
        if self.is_multi_step and self.session_config:
            logger.info("Initializing remote REST session...")
            method = self.session_config.get("method", "POST")
            url = self._resolve_url(self.session_config["path"])
            payload = self.session_config.get("body", self.session_config.get("request", {}))
            try:
                response = self._request(request_label="session_init", method=method, url=url, json=payload, headers=self.headers, timeout=self.config.get("timeout", 30))
                response.raise_for_status()
                data = response.json()
                token_path = self.session_config.get("response", {}).get("session_token")
                if token_path:
                    token = get_by_path(data, token_path)
                    if not token:
                        raise ValueError(f"Session token not found at path '{token_path}' in response: {data}")
                    self._remote_session_id = token
                    logger.info(f"Initialized remote session: {self._remote_session_id}")
            except Exception as e:
                logger.error(f"Failed to initialize remote session: {e}")
                raise
        else:
            logger.info(f"RestChatAdapter connected (Legacy/endpoint: {self.endpoint})")

    def _get_remote_ai_messages(self) -> list[dict]:
        """Fetch messages from receive endpoint and filter for AI sender."""
        if not self.is_multi_step or not self.receive_config:
            return []
            
        method = self.receive_config.get("method", "GET")
        url = self._resolve_url(self.receive_config["path"])
        response = self._request(request_label="multi_step_receive", method=method, url=url, headers=self.headers, timeout=self.config.get("timeout", 30))
        response.raise_for_status()
        _log_raw_response_before_parsing("multi_step_receive", response)
        data = response.json()
        
        messages_list = get_by_path(data, self.receive_config.get("messages_path", ""), default=[])
        if not isinstance(messages_list, list):
            raise ValueError(f"Expected a list at messages_path '{self.receive_config.get('messages_path')}', got {type(messages_list)}")
            
        logger.info(f"[DIAGNOSTIC] Polling status code: {response.status_code}")
        logger.info(f"[DIAGNOSTIC] Number of messages returned: {len(messages_list)}")
            
        sender_field = self.receive_config.get("sender_field")
        sender_value = self.receive_config.get("sender_value")
        
        ai_messages = [
            m for m in messages_list 
            if get_by_path(m, sender_field) == sender_value
        ]
        
        logger.info(f"[DIAGNOSTIC] Number of AI messages found: {len(ai_messages)}")
        
        return ai_messages

    def send_message(self, message: str, agent_prompt: Optional[str] = None, attachments: Optional[list[Any]] = None, wait_mode: str = "WAIT_ALWAYS") -> str:
        start = time.perf_counter()
        transcript_attachments = _transcript_attachment_names(attachments)
        self.transcript.append(
            ConversationMessage(
                role="simulated_user",
                content=message,
                turn_index=self._turn_index,
                attachments=transcript_attachments,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        )

        if self.is_multi_step:
            try:
                return self._send_message_multi_step(message, attachments=attachments, wait_mode=wait_mode)
            except requests.exceptions.Timeout:
                logger.error(f"REST Adapter Request Timed Out")
                raise
            except requests.exceptions.HTTPError as e:
                logger.error(f"REST Adapter HTTP Error: {e.response.status_code} - {e.response.text}")
                raise
            except RestAdapterTimeoutError as e:
                logger.error(f"REST Adapter Polling Timeout: {e}")
                raise
            except Exception as e:
                logger.error(f"REST Adapter Request FAILED: {e}")
                raise
        elif "endpoint" in self.config:
            if attachments:
                raise ValueError("Legacy REST adapter config does not support attachments.")
            return self._send_message_legacy(message)
        else:
            raise ValueError("Invalid REST adapter configuration: missing both multi-step config and legacy endpoint.")

    def _send_message_multi_step(self, message: str, attachments: Optional[list[Any]] = None, wait_mode: str = "WAIT_ALWAYS") -> str:
        if self.session_config and not self._remote_session_id:
            raise ValueError("No remote session token found. Session initialization may have failed.")
            
        # 1. Capture baseline of AI messages
        baseline_ai_msgs = self._get_remote_ai_messages()
        baseline_count = len(baseline_ai_msgs)
        
        logger.info(f"[DIAGNOSTIC] Session token present: {bool(self._remote_session_id)}")
        logger.info(f"[DIAGNOSTIC] Baseline AI message count: {baseline_count}")
        
        # 2. Send the message
        url = self._resolve_url(self.send_config["path"])
        method = self.send_config.get("method", "POST")
        
        # Determine content_type based on attachments
        content_type_config = self.send_config.get("content_type", "application/json")
        if isinstance(content_type_config, dict):
            content_type = content_type_config.get("attachments", "multipart/form-data") if attachments else content_type_config.get("text", "application/x-www-form-urlencoded")
        else:
            content_type = content_type_config
            
        msg_field = self.send_config.get("request", {}).get("message_field", "body")
        msg_template = self.send_config.get("request", {}).get("message_template")
        attachments_field = self.send_config.get("request", {}).get("attachments_field", "attachments[]")
        
        payload = {}
        for k, v in self.req_static_fields.items():
            set_by_path(payload, k, v)
            
        if msg_template and isinstance(msg_template, str):
            import json
            escaped_msg = json.dumps(message)[1:-1]
            formatted_msg = msg_template.replace("{{message}}", escaped_msg)
            set_by_path(payload, msg_field, formatted_msg)
        else:
            set_by_path(payload, msg_field, message)
        
        if self.req_session_field:
            set_by_path(payload, self.req_session_field, self.session_id)
        if self.req_user_id_field:
            set_by_path(payload, self.req_user_id_field, self.config.get("user_id", self.session_id))
        if self.req_conversation_id_field and self._remote_session_id is not None:
            set_by_path(payload, self.req_conversation_id_field, self._remote_session_id)
        
        headers = dict(self.headers)
        
        if attachments:
            import os
            # Build files dict for multipart/form-data
            files = []
            for path in attachments:
                if isinstance(path, dict):
                    files.append((attachments_field, _requests_file_tuple(path)))
                    continue
                if not os.path.exists(path) or not os.access(path, os.R_OK):
                    raise ValueError(f"Attachment file not found or not readable: {os.path.basename(path)}")
                files.append((attachments_field, _requests_file_tuple(path)))
                
            # Do NOT set Content-Type header for multipart/form-data, let requests generate boundary
            if "Content-Type" in headers:
                del headers["Content-Type"]
                
            # For multipart, data is flattened payload
            flat_payload = {msg_field: message}
            response = self._request(request_label="multi_step_send_multipart", method=method, url=url, data=flat_payload, files=files, headers=headers, timeout=self.config.get("timeout", 30))
            
            # Close files
            for _, item in files:
                file_obj = item[1] if len(item) >= 2 else None
                if hasattr(file_obj, "close"):
                    file_obj.close()
        else:
            if content_type:
                headers["Content-Type"] = content_type
        
            if content_type == "application/x-www-form-urlencoded":
                response = self._request(request_label="multi_step_send_form", method=method, url=url, data=payload, headers=headers, timeout=self.config.get("timeout", 30))
            else:
                print("\n--- REST ADAPTER REQUEST PAYLOAD ---")
                print("URL:", url)
                print("Method:", method)
                print("Headers:", {k: v for k, v in headers.items() if k.lower() != "authorization"})
                if "Authorization" in headers:
                    print("Authorization: PRESENT")
                else:
                    print("Authorization: ABSENT")
                import json
                print("JSON Payload:", json.dumps(payload, indent=2))
                print("------------------------------------\n")
                response = self._request(request_label="multi_step_send_json", method=method, url=url, json=payload, headers=headers, timeout=self.config.get("timeout", 30))
                
        logger.info(f"[DIAGNOSTIC] Send request status code: {response.status_code}")
        logger.info(f"[DIAGNOSTIC] Send request response status: {response.text[:200]}")
        _log_raw_response_before_parsing("multi_step_send", response)
                
        try:
            response.raise_for_status()
        except Exception as e:
            err_msg = response.text
            for k, v in self.headers.items():
                if v and len(str(v)) > 5 and str(v) in err_msg:
                    err_msg = err_msg.replace(str(v), "***REDACTED***")
            error_text = f"[System Error: The agent API returned HTTP {response.status_code}. Message: {err_msg}]"
            self.transcript.append(
                ConversationMessage(
                    role="agent",
                    content=error_text,
                    turn_index=self._turn_index,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )
            self._turn_index += 1
            return error_text
        
        # 3. Poll for the new AI message
        polling = self.receive_config.get("polling", {})
        interval_ms = polling.get("interval_ms")
        if interval_ms is None:
            interval_ms = polling.get("interval_seconds", 1) * 1000
        timeout_seconds = polling.get("timeout_seconds", 30)
        
        start_poll = time.time()
        logger.info(f"[DIAGNOSTIC] Starting polling... timeout: {timeout_seconds}s")
        while time.time() - start_poll < timeout_seconds:
            current_ai_msgs = self._get_remote_ai_messages()
            logger.info(f"[DIAGNOSTIC] Polling URL/path: {self._resolve_url(self.receive_config['path'])}")
            logger.info(f"[DIAGNOSTIC] Current AI message count: {len(current_ai_msgs)}")
            if len(current_ai_msgs) > baseline_count:
                logger.info(f"[DIAGNOSTIC] New AI message detected! Elapsed: {time.time() - start_poll:.2f}s")
                new_msg = current_ai_msgs[-1]
                receive_response_mapping = {
                    **self.response_mapping,
                    "reply_field": self.receive_config.get(
                        "text_field",
                        self.response_mapping.get("reply_field", "body"),
                    ),
                }
                normalized = _normalize_rest_response(new_msg, receive_response_mapping)
                reply_text = normalized["reply"]
                ui_components = normalized["components"]
                ui_attachments = normalized["attachments"]
                rag_evidence = self._extract_rag_evidence_for_response(new_msg)
                
                self.transcript.append(
                    ConversationMessage(
                        role="agent",
                        content=str(reply_text),
                        turn_index=self._turn_index,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        attachments=ui_attachments or None,
                        metadata={"components": ui_components} if ui_components else None,
                        rag_evidence=rag_evidence,
                    )
                )
                self._turn_index += 1
                return str(reply_text)
                
            time.sleep(interval_ms / 1000.0)

        raise RestAdapterTimeoutError(f"Polling timed out after {timeout_seconds} seconds waiting for a new AI message.")

    def _send_message_legacy(self, message: str) -> str:
        payload = {}
        # Apply static fields
        for k, v in self.req_static_fields.items():
            set_by_path(payload, k, v)
            
        # History mapping (e.g. for Gemini which requires full conversation history)
        history_field = self.request_mapping.get("history_field")
        if history_field:
            history = []
            item_template = self.request_mapping.get("history_item_template", {"role": "{{role}}", "content": "{{content}}"})
            role_map = self.request_mapping.get("history_role_map", {"user": "user", "agent": "model", "simulated_user": "user"})
            
            for msg in self.transcript:
                role = role_map.get(msg.role, msg.role)
                import copy
                item = copy.deepcopy(item_template)
                def replace_vars(node):
                    if isinstance(node, dict):
                        return {k: replace_vars(v) for k, v in node.items()}
                    elif isinstance(node, list):
                        return [replace_vars(x) for x in node]
                    elif isinstance(node, str):
                        val = node.replace("{{role}}", role).replace("{{content}}", msg.content).replace("{{message}}", msg.content)
                        if getattr(self, 'session_id', None):
                            val = val.replace("{{session_id}}", self.session_id)
                        return val
                    return node
                history.append(replace_vars(item))
            
            set_by_path(payload, history_field, history)
        else:
            # Single message field mapping
            if self.req_msg_field:
                msg_template = self.request_mapping.get("message_template")
                if msg_template and isinstance(msg_template, str):
                    import json
                    escaped_msg = json.dumps(message)[1:-1]
                    formatted_msg = msg_template.replace("{{message}}", escaped_msg)
                    set_by_path(payload, self.req_msg_field, formatted_msg)
                else:
                    set_by_path(payload, self.req_msg_field, message)
                
            if self.req_session_field:
                set_by_path(payload, self.req_session_field, self.session_id)
            if self.req_user_id_field:
                set_by_path(payload, self.req_user_id_field, self.config.get("user_id", self.session_id))
            if self.req_conversation_id_field and self._remote_session_id is not None:
                set_by_path(payload, self.req_conversation_id_field, self._remote_session_id)

        # Sanitized debug logging
        import copy
        import urllib.parse
        safe_headers = copy.deepcopy(self.headers)
        for k, v in safe_headers.items():
            if re.search(r'(?i)(key|secret|token|password|authorization)', k):
                safe_headers[k] = "***REDACTED***"
                
        parsed = urllib.parse.urlparse(self.endpoint)
        query = urllib.parse.parse_qs(parsed.query)
        for k in query:
            if re.search(r'(?i)(key|secret|token)', k):
                query[k] = ['***REDACTED***']
        safe_query = urllib.parse.urlencode(query, doseq=True)
        safe_url = urllib.parse.urlunparse(parsed._replace(query=safe_query))

        logger.debug(f"[REST Adapter] OUTGOING REQUEST:")
        logger.debug(f"  Method: {self.method}")
        logger.debug(f"  URL: {safe_url}")
        logger.debug(f"  Headers: {safe_headers}")
        import json
        logger.debug(f"  Body: {json.dumps(payload)}")
        
        print("[REST AUTH DEBUG]")
        print(f"auth configured: {'YES' if self.config.get('auth') else 'NO'}")
        print(f"api_key_header: {self.config.get('api_key_header', 'NOT SET')}")
        print(f"x-goog-api-key: {'PRESENT' if 'x-goog-api-key' in self.headers else 'ABSENT'}")
        print(f"request URL: {self.endpoint}")
        print(f"HTTP method: {self.method}")
        print(f"payload keys: {list(payload.keys())}")

        response = self._request(
            request_label="legacy_send",
            method=self.method,
            url=self.endpoint,
            json=payload,
            headers=self.headers,
            timeout=self.config.get("timeout", 180),
        )
        _log_raw_response_before_parsing("legacy_send", response)
        
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            print("=== ERROR AUDIT ===")
            print(f"1. URL: {response.request.url}")
            print(f"2. Method: {response.request.method}")
            print(f"3. Final headers: {response.request.headers}")
            print(f"4. Final JSON body: {response.request.body}")
            print(f"5. Raw response.text: {response.text}")
            try:
                err_data = response.json()
                print(f"6. Parsed response.json(): {err_data}")
                err_msg = err_data.get("error", {}).get("message", response.text)
            except Exception:
                print("6. Parsed response.json(): COULD NOT PARSE")
                err_msg = response.text
            print("===================")
            # Sanitize error message to prevent exposing API keys if they somehow end up there
            for k, v in self.headers.items():
                if v and len(str(v)) > 5 and str(v) in err_msg:
                    err_msg = err_msg.replace(str(v), "***REDACTED***")
            
            error_text = f"[System Error: The agent API returned HTTP {response.status_code}. Message: {err_msg}]"
            self.transcript.append(
                ConversationMessage(
                    role="agent",
                    content=error_text,
                    turn_index=self._turn_index,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )
            self._turn_index += 1
            return error_text
            
        data = response.json()
        normalized = _normalize_rest_response(data, self.response_mapping)

        reply = normalized["reply"]
        if reply is None:
             raise ValueError(f"REST endpoint response missing reply field. Checked mapping/defaults for '{self.res_reply_field}'. Response: {data}")
        if normalized["conversation_id"]:
            self._remote_session_id = str(normalized["conversation_id"])
        ui_components = normalized["components"]
        ui_attachments = normalized["attachments"]
        rag_evidence = self._extract_rag_evidence_for_response(data)

        # Extract tool calls if configured
        tool_calls = None
        if self.res_tool_calls_field:
            raw_tools = get_by_path(data, self.res_tool_calls_field)
            if raw_tools and isinstance(raw_tools, list):
                from app.models.conversation import ToolCallInfo
                tool_calls = []
                for t in raw_tools:
                    tool_calls.append(
                        ToolCallInfo(
                            tool_name=t.get("name", "unknown"),
                            tool_input=t.get("input", {}),
                            tool_output=t.get("output")
                        )
                    )

        self.transcript.append(
            ConversationMessage(
                role="agent",
                content=str(reply),
                turn_index=self._turn_index,
                timestamp=datetime.now(timezone.utc).isoformat(),
                tool_calls=tool_calls,
                attachments=ui_attachments or None,
                metadata={"components": ui_components} if ui_components else None,
                rag_evidence=rag_evidence,
            )
        )
        self._turn_index += 1
        return str(reply)



    def get_transcript(self) -> list[ConversationMessage]:
        return self.transcript

    def get_conversation(self) -> NormalizedConversation:
        return NormalizedConversation(
            run_id=self.run_id,
            session_id=self.session_id,
            channel="chatbot",
            messages=self.transcript
        )

    def _upload_metadata(self, path: Any) -> dict[str, Any]:
        if isinstance(path, dict):
            data = _upload_bytes(path)
            name = path.get("filename") or path.get("name") or "image"
            mime_type = path.get("mime_type") or path.get("mimeType") or path.get("type") or mimetypes.guess_type(str(name))[0]
            return {
                "file_name": os.path.basename(str(name)),
                "mime_type": mime_type or "application/octet-stream",
                "size": len(data),
            }
        if not os.path.exists(path) or not os.access(path, os.R_OK):
            raise UploadFileNotFound(f"Upload file not found or not readable: {os.path.basename(path)}")
        mime_type, _ = mimetypes.guess_type(path)
        return {
            "file_name": os.path.basename(path),
            "mime_type": mime_type or "application/octet-stream",
            "size": os.path.getsize(path),
        }

    def upload_file(self, file: Any, *, field: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        if not self.is_multi_step:
            raise CapabilityNotSupported("RestChatAdapter upload_file requires multi-step multipart attachment configuration.")
        upload_meta = self._upload_metadata(file)
        message = f"Upload File\n{upload_meta['file_name']}\nResult\nSuccess\nMime Type\n{upload_meta['mime_type']}\nSize\n{upload_meta['size']}"
        return self.send_message(message, attachments=[file], wait_mode="AUTO")

    def upload_image(self, image: Any, *, field: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        if not self.is_multi_step:
            raise CapabilityNotSupported("RestChatAdapter upload_image requires multi-step multipart attachment configuration.")
        upload_meta = self._upload_metadata(image)
        message = f"Upload Image\n{upload_meta['file_name']}\nResult\nSuccess\nMime Type\n{upload_meta['mime_type']}\nSize\n{upload_meta['size']}"
        return self.send_message(message, attachments=[image], wait_mode="AUTO")
        
    def click_button(self, text: str | None = None, *, metadata: dict[str, Any] | None = None) -> str:
        if not self.is_multi_step:
            raise CapabilityNotSupported("RestChatAdapter click_button requires multi-step configuration.")
        return self.send_message(f"Click Button\n{text or 'None'}", wait_mode="AUTO")

    def select_dropdown(self, field: str, value: str, *, metadata: dict[str, Any] | None = None) -> str:
        if not self.is_multi_step:
            raise CapabilityNotSupported("RestChatAdapter select_dropdown requires multi-step configuration.")
        return self.send_message(f"Select Dropdown\nField: {field}\nValue: {value}", wait_mode="AUTO")

    def select_radio(self, field: str, value: str, *, metadata: dict[str, Any] | None = None) -> str:
        if not self.is_multi_step:
            raise CapabilityNotSupported("RestChatAdapter select_radio requires multi-step configuration.")
        return self.send_message(f"Select Radio\nField: {field}\nValue: {value}", wait_mode="AUTO")

    def select_checkbox(self, field: str, value: bool = True, *, metadata: dict[str, Any] | None = None) -> str:
        if not self.is_multi_step:
            raise CapabilityNotSupported("RestChatAdapter select_checkbox requires multi-step configuration.")
        return self.send_message(f"Select Checkbox\nField: {field}\nValue: {value}", wait_mode="AUTO")

    def enter_otp(self, value: str, *, field: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        if not self.is_multi_step:
            raise CapabilityNotSupported("RestChatAdapter enter_otp requires multi-step configuration.")
        return self.send_message(f"Enter OTP\nField: {field}\nValue: {value}", wait_mode="AUTO")

    def search(self, query: str, *, field: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        if not self.is_multi_step:
            raise CapabilityNotSupported("RestChatAdapter search requires multi-step configuration.")
        return self.send_message(f"Search\nField: {field}\nQuery: {query}", wait_mode="AUTO")


    def pick_date(self, field: str, value: str, *, metadata: dict[str, Any] | None = None) -> str:
        if not self.is_multi_step:
            raise CapabilityNotSupported("RestChatAdapter pick_date requires multi-step configuration.")
        return self.send_message(f"Pick Date\nField: {field}\nValue: {value}", wait_mode="AUTO")

    def pick_time(self, field: str, value: str, *, metadata: dict[str, Any] | None = None) -> str:
        if not self.is_multi_step:
            raise CapabilityNotSupported("RestChatAdapter pick_time requires multi-step configuration.")
        return self.send_message(f"Pick Time\nField: {field}\nValue: {value}", wait_mode="AUTO")

    def select_multi_select(self, field: str, values: list[str], *, metadata: dict[str, Any] | None = None) -> str:
        if not self.is_multi_step:
            raise CapabilityNotSupported("RestChatAdapter select_multi_select requires multi-step configuration.")
        return self.send_message(f"Select Multi-Select\nField: {field}\nValues: {', '.join(values)}", wait_mode="AUTO")

    def close(self) -> None:
        if self._owned_browser_session is not None:
            self._owned_browser_session.close()
            self._owned_browser_session = None
