from abc import ABC, abstractmethod
from typing import Any, Optional

from app.models.conversation import NormalizedConversation

class AgentAdapterCapabilities:
    supports_tool_calls: bool = False
    supports_retrieval_context: bool = False
    supports_screenshots: bool = False
    supports_audio: bool = False
    supports_interruptions: bool = False
    supports_file_upload: bool = False
    supports_live_image: bool = False
    supports_browser: bool = False
    supports_session_history: bool = False


class AgentAdapter(ABC):
    """
    Universal adapter interface for connecting to any agent (chat or voice).
    """
    
    @property
    def capabilities(self) -> AgentAdapterCapabilities:
        return AgentAdapterCapabilities()
        
    @abstractmethod
    def connect(self) -> None:
        """Initialize the connection to the agent."""
        pass

    @abstractmethod
    def send_message(self, message: str, agent_prompt: Optional[str] = None, attachments: Optional[list[str]] = None) -> str:
        """
        Send a message/turn and return the text reply (or wait for it).
        In async environments, this would be async.
        """
        pass
        
    @abstractmethod
    def get_transcript(self) -> list[Any]:
        """
        Return the raw or normalized transcript so far.
        """
        pass
        
    @abstractmethod
    def get_conversation(self) -> NormalizedConversation:
        """
        Return the fully normalized conversation record.
        """
        pass

    def get_tool_calls(self) -> list[Any]:
        """Return tool calls made in this session, if supported."""
        return []

    def get_retrieval_context(self) -> list[str]:
        """Return RAG context retrieved in this session, if supported."""
        return []

    def get_metadata(self) -> dict[str, Any]:
        """Return any specific adapter/session metadata."""
        return {}

    @abstractmethod
    def close(self) -> None:
        """Close connections and clean up resources."""
        pass
