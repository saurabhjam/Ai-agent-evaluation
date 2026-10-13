import pytest

from app.adapters.chat.base import CapabilityNotSupported, ChatAdapter, ChatAdapterCapabilities
from app.adapters.chat.rest import RestChatAdapter


class MinimalChatAdapter(ChatAdapter):
    def connect(self) -> None:
        pass

    def send_message(self, message, agent_prompt=None, attachments=None):
        return "ok"

    def get_transcript(self):
        return []

    def get_conversation(self):
        return None

    def close(self) -> None:
        pass


def test_chat_adapter_capabilities_default_to_backward_compatible_false():
    capabilities = MinimalChatAdapter().capabilities

    assert isinstance(capabilities, ChatAdapterCapabilities)
    assert capabilities.supports_session_history is True
    assert capabilities.supports_click_button is False
    assert capabilities.supports_select_dropdown is False
    assert capabilities.supports_select_radio is False
    assert capabilities.supports_select_checkbox is False
    assert capabilities.supports_select_multi_select is False
    assert capabilities.supports_upload_file is False
    assert capabilities.supports_upload_image is False
    assert capabilities.supports_enter_otp is False
    assert capabilities.supports_pick_date is False
    assert capabilities.supports_pick_time is False
    assert capabilities.supports_search is False
    assert capabilities.supports_wait_for_text is False
    assert capabilities.supports_confirm is False
    assert capabilities.supports_cancel is False


@pytest.mark.parametrize(
    ("method_name", "args", "kwargs"),
    [
        ("click_button", ("Book Appointment",), {}),
        ("select_dropdown", ("City", "Pune"), {}),
        ("select_radio", ("Insurance", "Health"), {}),
        ("select_checkbox", ("Terms", True), {}),
        ("select_multi_select", ("Services", ["Dental", "Vision"]), {}),
        ("upload_file", ("test-data/damage.jpg",), {}),
        ("upload_image", ("test-data/damage.jpg",), {}),
        ("enter_otp", ("123456",), {}),
        ("pick_date", ("Appointment Date", "2026-10-03"), {}),
        ("pick_time", ("Appointment Time", "10:30"), {}),
        ("search", ("Pune clinic",), {}),
        ("wait_for_text", ("Appointment Confirmed",), {}),
        ("confirm", (), {}),
        ("cancel", (), {}),
    ],
)
def test_new_optional_interaction_methods_fail_explicitly_when_unsupported(method_name, args, kwargs):
    adapter = MinimalChatAdapter()

    with pytest.raises(CapabilityNotSupported, match=method_name):
        getattr(adapter, method_name)(*args, **kwargs)


def test_existing_send_message_contract_remains_unchanged():
    adapter = MinimalChatAdapter()

    assert adapter.send_message("Hello") == "ok"


def test_rest_adapter_reports_button_click_as_unsupported_by_default():
    adapter = RestChatAdapter({"endpoint": "https://example.test/chat"})

    with pytest.raises(CapabilityNotSupported, match="click_button"):
        adapter.click_button("Book Appointment")


def test_rest_adapter_reports_form_controls_as_unsupported_by_default():
    adapter = RestChatAdapter({"endpoint": "https://example.test/chat"})

    with pytest.raises(CapabilityNotSupported, match="select_dropdown"):
        adapter.select_dropdown("City", "Pune")
    with pytest.raises(CapabilityNotSupported, match="select_radio"):
        adapter.select_radio("Insurance Type", "Health")
    with pytest.raises(CapabilityNotSupported, match="select_checkbox"):
        adapter.select_checkbox("Accept Terms", True)
    with pytest.raises(CapabilityNotSupported, match="select_multi_select"):
        adapter.select_multi_select("Languages", ["English", "Hindi"])


def test_rest_adapter_reports_upload_as_unsupported_without_multipart(tmp_path):
    file_path = tmp_path / "policy.pdf"
    file_path.write_bytes(b"pdf")
    adapter = RestChatAdapter({"endpoint": "https://example.test/chat"})

    with pytest.raises(CapabilityNotSupported, match="upload_file"):
        adapter.upload_file(str(file_path))


def test_rest_adapter_reports_phase_6_actions_as_unsupported_by_default():
    adapter = RestChatAdapter({"endpoint": "https://example.test/chat"})

    with pytest.raises(CapabilityNotSupported, match="enter_otp"):
        adapter.enter_otp("123456", field="OTP")
    with pytest.raises(CapabilityNotSupported, match="pick_date"):
        adapter.pick_date("Appointment Date", "2026-10-15")
    with pytest.raises(CapabilityNotSupported, match="pick_time"):
        adapter.pick_time("Appointment Time", "14:30")
    with pytest.raises(CapabilityNotSupported, match="search"):
        adapter.search("Pune", field="City")
