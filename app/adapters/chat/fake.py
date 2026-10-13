import logging
import time
import uuid
import requests
from typing import Any, Optional
from datetime import datetime, timezone

from app.adapters.chat.base import ChatAdapter
from app.models.conversation import ConversationMessage, NormalizedConversation
from app.config import settings

logger = logging.getLogger(__name__)


class FakeChatAdapter(ChatAdapter):
    """
    Mock/Reference agent adapter.
    Uses the local mock endpoint.
    """
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.session_id = str(uuid.uuid4())
        self.run_id = str(uuid.uuid4())
        self.transcript: list[ConversationMessage] = []
        self._turn_index = 0
        self.endpoint = self.config.get("endpoint", "http://localhost:8000/mock-chat")

    def connect(self) -> None:
        logger.info("FakeChatAdapter connected.")

    def send_message(self, message: str, agent_prompt: Optional[str] = None, attachments: Optional[list[str]] = None) -> str:
        start = time.perf_counter()
        try:
            self.transcript.append(
                ConversationMessage(
                    role="simulated_user",
                    content=message,
                    turn_index=self._turn_index,
                    attachments=attachments,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
            )

            payload = {"session_id": self.session_id, "message": message}
            if agent_prompt:
                payload["agent_prompt"] = agent_prompt

            response = requests.post(
                self.endpoint,
                json=payload,
                timeout=180,
            )
            response.raise_for_status()
            data = response.json()
            if "reply" not in data:
                raise ValueError(f"Chatbot endpoint response missing 'reply' field: {data}")
                
            reply = data["reply"]
            self.transcript.append(
                ConversationMessage(
                    role="agent",
                    content=reply,
                    turn_index=self._turn_index,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
            )
            self._turn_index += 1
            elapsed = time.perf_counter() - start
            logger.info(f"[STAGE: Fake Agent Request] elapsed={elapsed:.3f}s")
            return reply
        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.error(f"[STAGE: Fake Agent Request FAILED] elapsed={elapsed:.3f}s exception={type(e).__name__}: {e}")
            raise

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
        logger.info("FakeChatAdapter closed.")
