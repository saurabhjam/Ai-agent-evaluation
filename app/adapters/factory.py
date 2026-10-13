from typing import Any
import logging

from app.adapters.base import AgentAdapter

logger = logging.getLogger(__name__)

class AdapterFactory:
    @staticmethod
    def create(agent_config: dict[str, Any], evaluation_session: Any | None = None) -> AgentAdapter:
        channel = agent_config.get("channel", "chatbot").lower()
        adapter_type = agent_config.get("adapter", "fake").lower()
        config = agent_config.get("config", {})

        if channel == "chatbot":
            if adapter_type == "rest":
                from app.adapters.chat.rest import RestChatAdapter
                return RestChatAdapter(config, evaluation_session=evaluation_session)
            elif adapter_type == "websocket":
                from app.adapters.chat.websocket import WebSocketChatAdapter
                return WebSocketChatAdapter(config)
            elif adapter_type == "browser":
                from app.adapters.chat.browser import BrowserChatAdapter
                return BrowserChatAdapter(config)
            elif adapter_type == "fake":
                from app.adapters.chat.fake import FakeChatAdapter
                return FakeChatAdapter(config)
            else:
                raise ValueError(f"Unknown chat adapter type: {adapter_type}")
        elif channel == "voice":
            # Implementation omitted for POC, would have similar mapping
            raise NotImplementedError("Voice channel adapters not fully implemented.")
        else:
            raise ValueError(f"Unknown channel: {channel}")
