"""
Adapter capability declarations for native interactive actions.

Adapters may expose these capabilities through an optional get_capabilities()
method. Existing adapters are not required to implement anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.interactive.models import ActionType


@dataclass(frozen=True)
class AdapterCapabilities:
    supports_send_text: bool = True
    supports_click_option: bool = False
    supports_click_button: bool = False
    supports_dropdown: bool = False
    supports_upload: bool = False
    supports_dom_click: bool = False
    supports_date_picker: bool = False
    supports_time_picker: bool = False
    supports_wait: bool = False
    supports_confirm: bool = False
    supports_cancel: bool = False
    supports_dtmf: bool = False
    supports_voice_interrupt: bool = False
    supports_transfer: bool = False

    def supports_action(self, action_type: ActionType) -> bool:
        return action_type in self.supported_action_types()

    def supported_action_types(self) -> set[ActionType]:
        supported: set[ActionType] = set()
        if self.supports_send_text:
            supported.add(ActionType.send_text)
        if self.supports_click_option:
            supported.add(ActionType.click_option)
        if self.supports_click_button or self.supports_dom_click:
            supported.add(ActionType.click_button)
        if self.supports_dropdown:
            supported.add(ActionType.select_dropdown)
        if self.supports_upload:
            supported.update({ActionType.upload_file, ActionType.upload_document})
        if self.supports_date_picker:
            supported.add(ActionType.select_date)
        if self.supports_time_picker:
            supported.add(ActionType.select_time)
        if self.supports_wait:
            supported.add(ActionType.wait)
        if self.supports_confirm:
            supported.add(ActionType.confirm)
        if self.supports_cancel:
            supported.add(ActionType.cancel)
        if self.supports_dtmf:
            supported.add(ActionType.dtmf)
        return supported


def default_capabilities() -> AdapterCapabilities:
    return AdapterCapabilities()


def rest_adapter_capabilities() -> AdapterCapabilities:
    return AdapterCapabilities(
        supports_send_text=True,
        supports_click_option=True,
        supports_click_button=True,
    )


def browser_placeholder_capabilities() -> AdapterCapabilities:
    return AdapterCapabilities(
        supports_send_text=True,
        supports_click_option=True,
        supports_click_button=True,
        supports_dropdown=True,
        supports_upload=True,
        supports_dom_click=True,
        supports_date_picker=True,
        supports_time_picker=True,
        supports_confirm=True,
        supports_cancel=True,
    )


def voice_placeholder_capabilities() -> AdapterCapabilities:
    return AdapterCapabilities(
        supports_send_text=True,
        supports_wait=True,
        supports_dtmf=True,
        supports_voice_interrupt=True,
        supports_transfer=True,
    )
