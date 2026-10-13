import logging
import json
from typing import Any, Optional
from datetime import datetime, timezone

from app.adapters.chat.base import ChatAdapter
from app.models.conversation import ConversationMessage, NormalizedConversation
from app.rag import extract_rag_evidence

logger = logging.getLogger(__name__)

class WebSocketChatAdapter(ChatAdapter):
    """
    Generic WebSocket Adapter interface.
    """
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.endpoint = self.config.get("endpoint")
        self.transcript: list[ConversationMessage] = []
        self.run_id = "ws-run"
        self.session_id = "ws-session"
        self.response_mapping = self.config.get("response_mapping", {})
        self.res_reply_field = self.response_mapping.get(
            "text_path",
            self.response_mapping.get("reply_field", "reply"),
        )
        self._scripted_responses = list(self.config.get("responses", []))

    def connect(self) -> None:
        logger.info(f"WebSocketChatAdapter connecting to {self.endpoint}...")
        # Implementation omitted for POC

    def send_message(self, message: str, agent_prompt: Optional[str] = None, attachments: Optional[list[str]] = None) -> str:
        if attachments:
            raise NotImplementedError("WebSocketAdapter does not currently support attachments")
        logger.info("Sending message via WebSocket")
        if self._scripted_responses:
            response = self._scripted_responses.pop(0)
            self.transcript.append(
                ConversationMessage(
                    role="simulated_user",
                    content=message,
                    turn_index=len(self.transcript),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )
            return self.record_agent_response(response)
        return "WebSocket response"

    def record_agent_response(self, response: Any) -> str:
        """
        Normalize one final WebSocket agent response.

        This method intentionally handles only a response that can be safely
        associated with the current final answer. It does not correlate
        separate retrieval/token/final events.
        """
        answer, rag_evidence = self._normalise_final_response(response)
        self.transcript.append(
            ConversationMessage(
                role="agent",
                content=answer,
                turn_index=len(self.transcript),
                timestamp=datetime.now(timezone.utc).isoformat(),
                rag_evidence=rag_evidence,
            )
        )
        return answer

    def _normalise_final_response(self, response: Any) -> tuple[str, Any]:
        data = self._parse_response(response)
        if isinstance(data, dict):
            reply = _get_by_path(data, self.res_reply_field)
            if reply is None:
                for fallback in ("message", "answer", "text", "response"):
                    reply = _get_by_path(data, fallback)
                    if reply is not None:
                        break
            if reply is None:
                reply = ""
            try:
                rag_evidence = extract_rag_evidence(data, self.config)
            except Exception as exc:
                logger.warning(
                    "WebSocket RAG evidence extraction failed type=%s",
                    type(exc).__name__,
                )
                rag_evidence = None
            return str(reply), rag_evidence
        return str(data), None

    def _parse_response(self, response: Any) -> Any:
        if isinstance(response, bytes):
            response = response.decode("utf-8", errors="replace")
        if isinstance(response, str):
            stripped = response.strip()
            if not stripped:
                return ""
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return response
        return response


    def get_transcript(self) -> list[ConversationMessage]:
        return self.transcript

    def get_conversation(self) -> NormalizedConversation:
        return NormalizedConversation(
            run_id=self.run_id,
            session_id=self.session_id,
            channel="chatbot",
            messages=self.transcript
        )

    def close(self) -> None:
        logger.info("WebSocketChatAdapter closed")


def _get_by_path(data: Any, path: str, default: Any = None) -> Any:
    if not path:
        return default
    current = data
    for part in path.split("."):
        if not part:
            continue
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current
