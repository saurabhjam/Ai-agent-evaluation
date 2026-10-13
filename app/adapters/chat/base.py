from abc import ABC
from typing import Any

from app.adapters.base import AgentAdapter, AgentAdapterCapabilities


class ChatAdapterError(Exception):
    """Base error for provider-neutral chatbot adapter interactions."""


class CapabilityNotSupported(ChatAdapterError):
    """Raised when an adapter does not support a requested capability."""


class ButtonNotFound(ChatAdapterError):
    """Raised when a requested button cannot be found."""


class MultipleButtonsFound(ChatAdapterError):
    """Raised when a button lookup matches more than one candidate."""


class ButtonDisabled(ChatAdapterError):
    """Raised when a requested button exists but is disabled."""


class ButtonHidden(ChatAdapterError):
    """Raised when a requested button exists but is not visible."""


class BrowserClosed(ChatAdapterError):
    """Raised when a browser-backed action cannot run because the browser is closed."""


class ChatAdapterTimeout(ChatAdapterError):
    """Raised when an adapter action times out."""


class ExpectedTextNotFound(ChatAdapterError):
    """Raised when expected synchronized text does not appear."""


class FieldNotFound(ChatAdapterError):
    """Raised when a requested field/control cannot be found."""


class OptionNotFound(ChatAdapterError):
    """Raised when a requested field option cannot be found."""


class MultipleControlsFound(ChatAdapterError):
    """Raised when a field/control lookup matches more than one candidate."""


class ControlDisabled(ChatAdapterError):
    """Raised when a field/control exists but is disabled."""


class ControlHidden(ChatAdapterError):
    """Raised when a field/control exists but is hidden."""


class UploadFileNotFound(ChatAdapterError):
    """Raised when an upload file path does not exist or is not readable."""


class UploadFieldNotFound(ChatAdapterError):
    """Raised when an upload field cannot be found."""


class ChatAdapterCapabilities(AgentAdapterCapabilities):
    supports_browser: bool = False
    supports_session_history: bool = True
    supports_click_button: bool = False
    supports_select_dropdown: bool = False
    supports_select_radio: bool = False
    supports_select_checkbox: bool = False
    supports_select_multi_select: bool = False
    supports_upload_file: bool = False
    supports_upload_image: bool = False
    supports_enter_otp: bool = False
    supports_pick_date: bool = False
    supports_pick_time: bool = False
    supports_search: bool = False
    supports_wait_for_text: bool = False
    supports_confirm: bool = False
    supports_cancel: bool = False

class ChatAdapter(AgentAdapter, ABC):
    """
    Base interface for all Chat-based adapters (REST, WebSocket, Botpress, etc.).
    """
    @property
    def capabilities(self) -> ChatAdapterCapabilities:
        return ChatAdapterCapabilities()

    def click_button(self, text: str, *, metadata: dict[str, Any] | None = None) -> str:
        """Click or activate a provider-neutral button by visible text/label."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support click_button.")

    def select_dropdown(self, field: str, value: str, *, metadata: dict[str, Any] | None = None) -> str:
        """Select a single value in a provider-neutral dropdown field."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support select_dropdown.")

    def select_radio(self, field: str, value: str, *, metadata: dict[str, Any] | None = None) -> str:
        """Select one radio option in a provider-neutral radio group."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support select_radio.")

    def select_checkbox(self, field: str, value: bool = True, *, metadata: dict[str, Any] | None = None) -> str:
        """Set a provider-neutral checkbox field to checked/unchecked."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support select_checkbox.")

    def select_multi_select(self, field: str, values: list[str], *, metadata: dict[str, Any] | None = None) -> str:
        """Select multiple values in a provider-neutral multi-select field."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support select_multi_select.")

    def upload_file(self, file: str, *, field: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        """Upload a file through a provider-neutral upload field."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support upload_file.")

    def upload_image(self, image: str, *, field: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        """Upload an image through a provider-neutral image upload field."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support upload_image.")

    def enter_otp(self, value: str, *, field: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        """Enter a one-time password or verification code."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support enter_otp.")

    def pick_date(self, field: str, value: str, *, metadata: dict[str, Any] | None = None) -> str:
        """Pick or enter a date value for a provider-neutral date field."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support pick_date.")

    def pick_time(self, field: str, value: str, *, metadata: dict[str, Any] | None = None) -> str:
        """Pick or enter a time value for a provider-neutral time field."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support pick_time.")

    def search(self, query: str, *, field: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        """Run a provider-neutral search interaction."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support search.")

    def wait_for_text(self, text: str, *, timeout: float | None = None, metadata: dict[str, Any] | None = None) -> str:
        """Wait for expected text to appear before continuing scenario execution."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support wait_for_text.")

    def confirm(self, *, label: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        """Confirm the current chatbot prompt or dialog."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support confirm.")

    def cancel(self, *, label: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        """Cancel the current chatbot prompt or dialog."""
        raise CapabilityNotSupported(f"{self.__class__.__name__} does not support cancel.")
