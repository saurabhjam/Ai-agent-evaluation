from unittest.mock import MagicMock, patch

from app.executor import ScenarioExecutor
from app.interaction_dispatcher import dispatch_interaction
from app.models.connection import AgentConnection
from app.models.conversation import ConversationMessage, NormalizedConversation
from app.schemas import AgentConfig, Persona, TestScenario


class DispatchAdapter:
    def __init__(self):
        self.calls = []
        self.transcript = []

    def _append_action(self, content, attachments=None):
        self.transcript.append(
            ConversationMessage(
                role="simulated_user",
                content=content,
                turn_index=len(self.transcript),
                attachments=attachments,
            )
        )

    def click_button(self, text=None, *, metadata=None):
        self.calls.append(("click_button", text, metadata))
        self._append_action(f"Click Button\n{text}")
        return "clicked"

    def select_dropdown(self, field, value, *, metadata=None):
        self.calls.append(("select_dropdown", field, value, metadata))
        self._append_action(f"Select Dropdown\n{field} = {value}")
        return "selected"

    def select_radio(self, field, value, *, metadata=None):
        self.calls.append(("select_radio", field, value, metadata))
        self._append_action(f"Radio\n{field} = {value}")
        return "radio"

    def select_checkbox(self, field, value=True, *, metadata=None):
        self.calls.append(("select_checkbox", field, value, metadata))
        self._append_action(f"Checkbox\n{field} = {value}")
        return "checkbox"

    def select_multi_select(self, field, values, *, metadata=None):
        self.calls.append(("select_multi_select", field, values, metadata))
        self._append_action(f"Multi Select\n{field} = {','.join(values)}")
        return "multi"

    def upload_file(self, file, *, field=None, metadata=None):
        self.calls.append(("upload_file", file, field, metadata))
        self._append_action(f"Upload File\n{file}", attachments=[file] if isinstance(file, str) else None)
        return "file"

    def upload_image(self, image, *, field=None, metadata=None):
        self.calls.append(("upload_image", image, field, metadata))
        self._append_action(f"Upload Image\n{image}", attachments=[image] if isinstance(image, str) else None)
        return "image"

    def enter_otp(self, value, *, field=None, metadata=None):
        self.calls.append(("enter_otp", value, field, metadata))
        self._append_action("Entered OTP\n******")
        return "otp"

    def pick_date(self, field, value, *, metadata=None):
        self.calls.append(("pick_date", field, value, metadata))
        self._append_action(f"Date\n{field} = {value}")
        return "date"

    def pick_time(self, field, value, *, metadata=None):
        self.calls.append(("pick_time", field, value, metadata))
        self._append_action(f"Time\n{field} = {value}")
        return "time"

    def search(self, query, *, field=None, metadata=None):
        self.calls.append(("search", query, field, metadata))
        self._append_action(f"Search\n{field} = {query}")
        return "search"

    def send_message(self, message, agent_prompt=None, attachments=None):
        self.calls.append(("send_message", message, agent_prompt, attachments))
        self._append_action(message, attachments=attachments)
        return "sent"

    def get_transcript(self):
        return self.transcript


class Manager:
    def __init__(self, adapter):
        self.adapter = adapter

    def create_adapter(self, connection):
        return self.adapter


def _scenario(goal="Book an appointment"):
    return TestScenario(
        scenario_id="dispatcher_test",
        agent=AgentConfig(channel="chatbot", adapter="fake"),
        persona=Persona(name="Ava", goal=goal, tone="polite"),
        max_turns=2,
    )


def _transcript(component):
    return [
        ConversationMessage(
            role="agent",
            content="Please continue.",
            turn_index=0,
            metadata={"components": [component]},
        )
    ]


def _plain_transcript(message, metadata=None):
    return [
        ConversationMessage(
            role="agent",
            content=message,
            turn_index=0,
            metadata=metadata,
        )
    ]


def test_text_only_evaluation_is_unchanged_when_no_components():
    adapter = MagicMock()
    adapter.get_transcript.return_value = []
    adapter.get_conversation.return_value = NormalizedConversation(
        run_id="r",
        session_id="s",
        channel="chatbot",
        messages=[],
    )
    adapter.send_message.return_value = "ok"

    with patch("app.executor.generate_next_user_turn", return_value={"message": "Hello"}):
        result = ScenarioExecutor(Manager(adapter)).execute(
            AgentConnection(id="c1", name="Chat", type="chatbot", adapter="fake", config={}),
            _scenario(),
        )

    assert result.success
    adapter.send_message.assert_called()


def test_plain_text_image_request_uses_fallback_and_pauses_for_frontend(monkeypatch):
    adapter = DispatchAdapter()

    class FakeInteractionManager:
        def request_interaction(self, **kwargs):
            assert kwargs["interaction_type"] == "image_upload"
            assert kwargs["component"]["generated_by"] == "fallback"
            assert kwargs["component"]["type"] == "image_upload"
            return {
                "source": "device",
                "file": {
                    "name": "damage.png",
                    "type": "image/png",
                    "content": "ZmFrZQ==",
                },
            }

    from app import interaction_dispatcher

    token = interaction_dispatcher.current_eval_id.set("eval-fallback-image")
    monkeypatch.setattr(interaction_dispatcher, "interaction_manager", FakeInteractionManager())
    try:
        handled = dispatch_interaction(
            adapter=adapter,
            scenario=_scenario(),
            transcript=_plain_transcript("Please upload a damage photo."),
        )
    finally:
        interaction_dispatcher.current_eval_id.reset(token)

    assert handled is True
    assert adapter.calls[0][0] == "upload_image"
    assert adapter.calls[0][1]["filename"] == "damage.png"
    evidence = adapter.transcript[-1].metadata["interaction_evidence"]
    assert evidence["interaction_type"] == "image_upload"
    assert evidence["requested_by_agent"] == "Upload damage photo"
    assert evidence["source"] == "device"


def test_fallback_detector_does_not_run_when_structured_components_exist(monkeypatch):
    adapter = DispatchAdapter()

    def fail_if_called(_text):
        raise AssertionError("fallback detector should not run when components exist")

    monkeypatch.setattr("app.interaction_dispatcher.detect_fallback_interactions", fail_if_called)
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario(),
        transcript=_plain_transcript(
            "Please upload a damage photo.",
            metadata={"components": [{"type": "button", "label": "Continue", "message": "Continue"}]},
        ),
    )

    assert handled is True
    assert adapter.calls[0][0:2] == ("click_button", "Continue")


def test_plain_text_without_fallback_match_remains_unhandled():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario(),
        transcript=_plain_transcript("Thanks, I can help with that."),
    )

    assert handled is False
    assert adapter.calls == []


def test_button_routing_uses_adapter_click_button():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario("Open maintenance tickets"),
        transcript=_transcript({"type": "button", "label": "Open maintenance tickets", "message": "Open tickets"}),
    )
    assert handled is True
    assert adapter.calls[0][0:2] == ("click_button", "Open tickets")
    evidence = adapter.transcript[-1].metadata["interaction_evidence"]
    assert evidence["interaction_type"] == "button_click"
    assert evidence["requested_by_agent"] == "Open maintenance tickets"
    assert evidence["selected_value"] == "Open tickets"
    assert evidence["success"] is True
    assert evidence["adapter"] == "DispatchAdapter"
    assert evidence["provider"] == "DispatchAdapter"
    assert evidence["status"] == "SUCCESS"
    assert "requested_at" in evidence
    assert "responded_at" in evidence
    assert evidence["duration_ms"] >= 0


def test_dropdown_routing_uses_adapter_select_dropdown():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario("Select Pune"),
        transcript=_transcript({"type": "dropdown", "field": "City", "options": ["Mumbai", "Pune"]}),
    )
    assert handled is True
    assert adapter.calls[0][0:3] == ("select_dropdown", "City", "Pune")


def test_checkbox_routing_uses_adapter_select_checkbox():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario(),
        transcript=_transcript({"type": "checkbox", "field": "Accept Terms", "value": True}),
    )
    assert handled is True
    assert adapter.calls[0][0:3] == ("select_checkbox", "Accept Terms", True)


def test_radio_routing_uses_adapter_select_radio():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario("Health insurance"),
        transcript=_transcript({"type": "radio", "field": "Insurance Type", "options": ["Auto", "Health"]}),
    )
    assert handled is True
    assert adapter.calls[0][0:3] == ("select_radio", "Insurance Type", "Health")


def test_multi_select_routing_uses_adapter_select_multi_select():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario("English and Hindi languages"),
        transcript=_transcript({"type": "multi_select", "field": "Languages", "values": ["English", "Hindi"]}),
    )
    assert handled is True
    assert adapter.calls[0][0:3] == ("select_multi_select", "Languages", ["English", "Hindi"])


def test_otp_routing_uses_adapter_enter_otp():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario(),
        transcript=_transcript({"type": "otp", "field": "OTP", "value": "123456"}),
    )
    assert handled is True
    assert adapter.calls[0][0:3] == ("enter_otp", "123456", "OTP")
    evidence = adapter.transcript[-1].metadata["interaction_evidence"]
    assert evidence["interaction_type"] == "otp"
    assert evidence["action"] == "OTP entered"
    assert evidence["status"] == "SUCCESS"
    assert evidence["selected_value"] == "******"
    assert "timestamp" in evidence
    assert "123456" not in str(evidence)


def test_otp_pause_resume_uses_frontend_response_and_masks_evidence(monkeypatch):
    adapter = DispatchAdapter()

    class FakeInteractionManager:
        def request_interaction(self, **kwargs):
            assert kwargs["interaction_type"] == "otp"
            assert kwargs["prompt"] == "Enter OTP"
            return {
                "otp": "123456",
                "requested_at": "2026-10-09T00:00:00+00:00",
                "responded_at": "2026-10-09T00:00:04.500000+00:00",
                "duration_ms": 4500,
                "status": "SUCCESS",
            }

    from app import interaction_dispatcher

    token = interaction_dispatcher.current_eval_id.set("eval-otp")
    monkeypatch.setattr(interaction_dispatcher, "interaction_manager", FakeInteractionManager())
    try:
        handled = dispatch_interaction(
            adapter=adapter,
            scenario=_scenario(),
            transcript=_transcript({"type": "otp", "field": "OTP", "label": "Enter OTP", "length": 6}),
        )
    finally:
        interaction_dispatcher.current_eval_id.reset(token)

    assert handled is True
    assert adapter.calls[0][0:3] == ("enter_otp", "123456", "OTP")
    evidence = adapter.transcript[-1].metadata["interaction_evidence"]
    assert evidence["interaction_type"] == "otp"
    assert evidence["selected_value"] == "******"
    assert evidence["action"] == "OTP entered"
    assert evidence["status"] == "SUCCESS"
    assert evidence["duration_ms"] == 4500
    assert "123456" not in str(evidence)


def test_otp_pause_resume_cancel_records_masked_failed_evidence(monkeypatch):
    adapter = DispatchAdapter()
    latest_agent = _transcript({"type": "otp", "field": "OTP", "label": "Enter OTP"})

    class FakeInteractionManager:
        def request_interaction(self, **kwargs):
            assert kwargs["interaction_type"] == "otp"
            return {
                "cancelled": True,
                "error": "User cancelled",
                "requested_at": "2026-10-09T00:00:00+00:00",
                "responded_at": "2026-10-09T00:00:02+00:00",
                "duration_ms": 2000,
                "status": "CANCELLED",
            }

    from app import interaction_dispatcher

    token = interaction_dispatcher.current_eval_id.set("eval-otp-cancel")
    monkeypatch.setattr(interaction_dispatcher, "interaction_manager", FakeInteractionManager())
    try:
        handled = dispatch_interaction(
            adapter=adapter,
            scenario=_scenario(),
            transcript=latest_agent,
        )
    finally:
        interaction_dispatcher.current_eval_id.reset(token)

    assert handled is False
    evidence = latest_agent[0].metadata["interaction_evidence"]
    assert evidence["interaction_type"] == "otp"
    assert evidence["selected_value"] == "******"
    assert evidence["success"] is False
    assert evidence["status"] == "CANCELLED"
    assert evidence["error"] == "User cancelled"
    assert "123456" not in str(evidence)


def test_otp_routing_accepts_4_digit_and_6_digit_values():
    for value in ("1234", "123456"):
        adapter = DispatchAdapter()
        handled = dispatch_interaction(
            adapter=adapter,
            scenario=_scenario(),
            transcript=_transcript({"type": "otp", "field": "OTP", "value": value}),
        )
        assert handled is True
        assert adapter.calls[0][0:3] == ("enter_otp", value, "OTP")


def test_file_upload_routing_uses_adapter_upload_file():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario(),
        transcript=_transcript({"type": "file_upload", "field": "Document", "file": "test-data/doc.pdf"}),
    )
    assert handled is True
    assert adapter.calls[0][0:3] == ("upload_file", "test-data/doc.pdf", "Document")
    evidence = adapter.transcript[-1].metadata["interaction_evidence"]
    assert evidence["interaction_type"] == "file_upload"
    assert evidence["artifact_path"] == "test-data/doc.pdf"


def test_image_upload_with_predefined_path_pauses_instead_of_auto_upload():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario(),
        transcript=_transcript({"type": "image_upload", "field": "Photo", "image": "test-data/photo.jpg"}),
    )
    assert handled is False
    assert adapter.calls == []
    assert adapter.transcript == []


def test_device_image_upload_requires_frontend_pause_before_upload():
    adapter = DispatchAdapter()
    device_file = {
        "name": "gallery.png",
        "mime_type": "image/png",
        "content": b"fake-image",
    }
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario(),
        transcript=_transcript(
            {
                "type": "image_upload",
                "source": "device",
                "field": "Damage Photo",
                "file": device_file,
            }
        ),
    )
    assert handled is False
    assert adapter.calls == []
    assert adapter.transcript == []


def test_camera_image_upload_requires_frontend_pause_before_upload():
    adapter = DispatchAdapter()
    camera_file = {
        "name": "capture.jpg",
        "mime_type": "image/jpeg",
        "content": b"camera-image",
    }
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario(),
        transcript=_transcript(
            {
                "type": "image_upload",
                "source": "camera",
                "field": "Live Photo",
                "file": camera_file,
                "retakes": 1,
                "camera_used": True,
            }
        ),
    )
    assert handled is False
    assert adapter.calls == []
    assert adapter.transcript == []


def test_image_upload_can_pause_for_frontend_response(monkeypatch, tmp_path):
    adapter = DispatchAdapter()
    monkeypatch.chdir(tmp_path)

    class FakeInteractionManager:
        def request_interaction(self, **kwargs):
            assert kwargs["evaluation_id"] == "eval-interactive"
            assert kwargs["interaction_type"] == "image_upload"
            return {
                "source": "device",
                "file": {
                    "name": "selected.png",
                    "type": "image/png",
                    "content": "ZmFrZQ==",
                },
            }

    token = None
    from app import interaction_dispatcher

    token = interaction_dispatcher.current_eval_id.set("eval-interactive")
    monkeypatch.setattr(interaction_dispatcher, "interaction_manager", FakeInteractionManager())
    try:
        handled = dispatch_interaction(
            adapter=adapter,
            scenario=_scenario(),
            transcript=_transcript({"type": "image_upload", "label": "Damage Photo", "source": "device"}),
        )
    finally:
        interaction_dispatcher.current_eval_id.reset(token)

    assert handled is True
    assert adapter.calls[0][0] == "upload_image"
    assert adapter.calls[0][1]["filename"] == "selected.png"
    evidence = adapter.transcript[-1].metadata["interaction_evidence"]
    assert evidence["source"] == "device"
    assert evidence["filename"] == "selected.png"
    assert evidence["artifact_path"] == "artifacts/eval-interactive/uploaded/selected.png"
    assert evidence["mime_type"] == "image/png"
    assert evidence["size_bytes"] == 4
    assert (tmp_path / evidence["artifact_path"]).read_bytes() == b"fake"
    assert "ZmFrZQ==" not in str(evidence)


def test_camera_image_upload_can_pause_for_frontend_response(monkeypatch, tmp_path):
    adapter = DispatchAdapter()
    monkeypatch.chdir(tmp_path)

    class FakeInteractionManager:
        def request_interaction(self, **kwargs):
            assert kwargs["evaluation_id"] == "eval-camera"
            assert kwargs["interaction_type"] == "image_upload"
            return {
                "source": "camera",
                "camera_used": True,
                "retakes": 2,
                "file": {
                    "name": "camera-capture.jpg",
                    "type": "image/jpeg",
                    "content": "Y2FtZXJh",
                },
                "requested_at": "2026-10-09T00:00:00+00:00",
                "responded_at": "2026-10-09T00:00:18+00:00",
                "duration_ms": 18000,
                "status": "SUCCESS",
            }

    from app import interaction_dispatcher

    token = interaction_dispatcher.current_eval_id.set("eval-camera")
    monkeypatch.setattr(interaction_dispatcher, "interaction_manager", FakeInteractionManager())
    try:
        handled = dispatch_interaction(
            adapter=adapter,
            scenario=_scenario(),
            transcript=_transcript({"type": "image_upload", "label": "Damage Photo", "source": "camera"}),
        )
    finally:
        interaction_dispatcher.current_eval_id.reset(token)

    assert handled is True
    assert adapter.calls[0][0] == "upload_image"
    assert adapter.calls[0][1]["filename"] == "camera-capture.jpg"
    evidence = adapter.transcript[-1].metadata["interaction_evidence"]
    assert evidence["interaction_type"] == "camera_capture"
    assert evidence["source"] == "camera"
    assert evidence["action"] == "Captured live photo"
    assert evidence["camera_used"] is True
    assert evidence["retakes"] == 2
    assert evidence["duration_ms"] == 18000
    assert evidence["artifact_path"] == "artifacts/eval-camera/uploaded/camera-capture.jpg"
    assert evidence["mime_type"] == "image/jpeg"
    assert (tmp_path / evidence["artifact_path"]).read_bytes() == b"camera"
    assert "Y2FtZXJh" not in str(evidence)


def test_frontend_interaction_timeout_records_evidence(monkeypatch):
    adapter = DispatchAdapter()
    latest_agent = _transcript({"type": "image_upload", "label": "Damage Photo", "source": "device"})

    class FakeInteractionManager:
        def request_interaction(self, **kwargs):
            return {
                "cancelled": True,
                "status": "TIMED_OUT",
                "reason": "User did not respond",
                "requested_at": "2026-10-09T00:00:00+00:00",
                "responded_at": "2026-10-09T00:05:00+00:00",
                "duration_ms": 300000,
            }

    from app import interaction_dispatcher

    token = interaction_dispatcher.current_eval_id.set("eval-timeout")
    monkeypatch.setattr(interaction_dispatcher, "interaction_manager", FakeInteractionManager())
    try:
        handled = dispatch_interaction(
            adapter=adapter,
            scenario=_scenario(),
            transcript=latest_agent,
        )
    finally:
        interaction_dispatcher.current_eval_id.reset(token)

    assert handled is False
    evidence = latest_agent[0].metadata["interaction_evidence"]
    assert evidence["interaction_type"] == "image_upload"
    assert evidence["status"] == "TIMED_OUT"
    assert evidence["reason"] == "User did not respond"
    assert evidence["duration_ms"] == 300000


def test_date_picker_routing_uses_adapter_pick_date():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario(),
        transcript=_transcript({"type": "date", "field": "Appointment Date", "value": "2026-10-15"}),
    )
    assert handled is True
    assert adapter.calls[0][0:3] == ("pick_date", "Appointment Date", "2026-10-15")


def test_search_routing_uses_adapter_search():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario(),
        transcript=_transcript({"type": "search", "field": "City", "query": "Pune"}),
    )
    assert handled is True
    assert adapter.calls[0][0:3] == ("search", "Pune", "City")


def test_form_field_entry_records_interaction_evidence():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario(),
        transcript=_transcript(
            {
                "type": "form",
                "label": "Contact form",
                "fields": [{"type": "text", "label": "Name", "value": "Rahul Sharma"}],
            }
        ),
    )
    assert handled is True
    evidence = adapter.transcript[-1].metadata["interaction_evidence"]
    assert evidence["interaction_type"] == "form_fill"
    assert evidence["fields_completed"] == 1
    assert evidence["selected_value"]["Name"] == "Rahul Sharma"


def test_dynamic_form_pause_resume_records_form_fill_evidence(monkeypatch):
    adapter = DispatchAdapter()

    class FakeInteractionManager:
        def request_interaction(self, **kwargs):
            assert kwargs["interaction_type"] == "form"
            return {
                "fields": {
                    "name": "Rahul Sharma",
                    "email": "rahul@example.com",
                    "issue_type": "Maintenance",
                    "urgent": True,
                    "languages": ["English", "Hindi"],
                    "preferred_date": "2026-10-15",
                    "preferred_time": "14:30",
                },
                "requested_at": "2026-10-09T00:00:00+00:00",
                "responded_at": "2026-10-09T00:01:00+00:00",
                "duration_ms": 60000,
                "status": "SUCCESS",
            }

    from app import interaction_dispatcher

    token = interaction_dispatcher.current_eval_id.set("eval-form")
    monkeypatch.setattr(interaction_dispatcher, "interaction_manager", FakeInteractionManager())
    try:
        handled = dispatch_interaction(
            adapter=adapter,
            scenario=_scenario("Submit maintenance request"),
            transcript=_transcript(
                {
                    "type": "form",
                    "label": "Maintenance request",
                    "fields": [
                        {"type": "text", "name": "name", "label": "Name", "required": True},
                        {"type": "email", "name": "email", "label": "Email", "required": True},
                        {"type": "dropdown", "name": "issue_type", "label": "Issue Type", "options": ["Maintenance"], "required": True},
                        {"type": "checkbox", "name": "urgent", "label": "Urgent"},
                        {"type": "multi_select", "name": "languages", "label": "Languages", "options": ["English", "Hindi"]},
                        {"type": "date", "name": "preferred_date", "label": "Preferred Date", "required": True},
                        {"type": "time", "name": "preferred_time", "label": "Preferred Time", "required": True},
                    ],
                }
            ),
        )
    finally:
        interaction_dispatcher.current_eval_id.reset(token)

    assert handled is True
    evidence = next(
        msg.metadata["interaction_evidence"]
        for msg in adapter.transcript
        if msg.metadata and msg.metadata.get("interaction_evidence", {}).get("interaction_type") == "form_fill"
    )
    assert evidence["interaction_type"] == "form_fill"
    assert evidence["fields_completed"] == 7
    assert evidence["required_fields"] == 5
    assert evidence["optional_fields"] == 2
    assert evidence["status"] == "SUCCESS"
    assert evidence["duration_ms"] == 60000
    assert any(call[0:3] == ("select_dropdown", "Issue Type", "Maintenance") for call in adapter.calls)
    assert any(call[0] == "select_checkbox" for call in adapter.calls)
    assert any(call[0] == "select_multi_select" for call in adapter.calls)
    assert any(call[0] == "pick_date" for call in adapter.calls)
    assert any(call[0] == "pick_time" for call in adapter.calls)


def test_plain_text_conversation_produces_no_interaction_evidence():
    adapter = DispatchAdapter()
    handled = dispatch_interaction(
        adapter=adapter,
        scenario=_scenario(),
        transcript=[
            ConversationMessage(
                role="agent",
                content="How can I help?",
                turn_index=0,
            )
        ],
    )
    assert handled is False
    assert adapter.transcript == []


def test_document_upload_can_pause_for_frontend_response(monkeypatch, tmp_path):
    adapter = DispatchAdapter()
    monkeypatch.chdir(tmp_path)

    class FakeInteractionManager:
        def request_interaction(self, **kwargs):
            assert kwargs["evaluation_id"] == "eval-interactive"
            assert kwargs["interaction_type"] == "document_upload"
            return {
                "source": "device",
                "file": {
                    "name": "lease_agreement.pdf",
                    "type": "application/pdf",
                    "content": "ZmFrZQ==",
                },
            }

    token = None
    from app import interaction_dispatcher

    token = interaction_dispatcher.current_eval_id.set("eval-interactive")
    monkeypatch.setattr(interaction_dispatcher, "interaction_manager", FakeInteractionManager())
    try:
        handled = dispatch_interaction(
            adapter=adapter,
            scenario=_scenario(),
            transcript=_transcript({"type": "document_upload", "label": "Upload lease agreement", "source": "device"}),
        )
    finally:
        interaction_dispatcher.current_eval_id.reset(token)

    assert handled is True
    assert adapter.calls[0][0] == "upload_file"
    assert adapter.calls[0][1]["filename"] == "lease_agreement.pdf"
    evidence = adapter.transcript[-1].metadata["interaction_evidence"]
    assert evidence["source"] == "device"
    assert evidence["filename"] == "lease_agreement.pdf"
    assert evidence["action"] == "Uploaded document"
    assert evidence["interaction_type"] == "document_upload"
    assert evidence["artifact_path"] == "artifacts/eval-interactive/uploaded/lease_agreement.pdf"
    assert evidence["mime_type"] == "application/pdf"
    assert evidence["size_bytes"] == 4
    assert (tmp_path / evidence["artifact_path"]).read_bytes() == b"fake"


def test_video_upload_can_pause_for_frontend_response(monkeypatch, tmp_path):
    adapter = DispatchAdapter()
    monkeypatch.chdir(tmp_path)

    class FakeInteractionManager:
        def request_interaction(self, **kwargs):
            assert kwargs["evaluation_id"] == "eval-interactive"
            assert kwargs["interaction_type"] == "video_upload"
            return {
                "source": "device",
                "file": {
                    "name": "damage_video.mp4",
                    "type": "video/mp4",
                    "content": "ZmFrZQ==",
                },
            }

    token = None
    from app import interaction_dispatcher

    token = interaction_dispatcher.current_eval_id.set("eval-interactive")
    monkeypatch.setattr(interaction_dispatcher, "interaction_manager", FakeInteractionManager())
    try:
        handled = dispatch_interaction(
            adapter=adapter,
            scenario=_scenario(),
            transcript=_transcript({"type": "video_upload", "label": "Upload damage video", "source": "device"}),
        )
    finally:
        interaction_dispatcher.current_eval_id.reset(token)

    assert handled is True
    assert adapter.calls[0][0] == "upload_file"
    assert adapter.calls[0][1]["filename"] == "damage_video.mp4"
    evidence = adapter.transcript[-1].metadata["interaction_evidence"]
    assert evidence["source"] == "device"
    assert evidence["filename"] == "damage_video.mp4"
    assert evidence["action"] == "Uploaded video"
    assert evidence["interaction_type"] == "video_upload"
    assert evidence["artifact_path"] == "artifacts/eval-interactive/uploaded/damage_video.mp4"
    assert evidence["mime_type"] == "video/mp4"
    assert evidence["size_bytes"] == 4
    assert (tmp_path / evidence["artifact_path"]).read_bytes() == b"fake"


def test_upload_artifacts_never_overwrite_duplicate_filenames(monkeypatch, tmp_path):
    adapter = DispatchAdapter()
    monkeypatch.chdir(tmp_path)
    responses = iter([
        {"source": "device", "file": {"name": "damage.png", "type": "image/png", "content": "Zmlyc3Q="}},
        {"source": "device", "file": {"name": "damage.png", "type": "image/png", "content": "c2Vjb25k"}},
    ])

    class FakeInteractionManager:
        def request_interaction(self, **kwargs):
            return next(responses)

    from app import interaction_dispatcher

    token = interaction_dispatcher.current_eval_id.set("eval-duplicates")
    monkeypatch.setattr(interaction_dispatcher, "interaction_manager", FakeInteractionManager())
    try:
        for _ in range(2):
            assert dispatch_interaction(
                adapter=adapter,
                scenario=_scenario(),
                transcript=_transcript({"type": "image_upload", "label": "Damage Photo", "source": "device"}),
            )
    finally:
        interaction_dispatcher.current_eval_id.reset(token)

    evidences = [msg.metadata["interaction_evidence"] for msg in adapter.transcript if msg.metadata]
    assert evidences[0]["artifact_path"] == "artifacts/eval-duplicates/uploaded/damage.png"
    assert evidences[1]["artifact_path"] == "artifacts/eval-duplicates/uploaded/damage-1.png"
    assert (tmp_path / evidences[0]["artifact_path"]).read_bytes() == b"first"
    assert (tmp_path / evidences[1]["artifact_path"]).read_bytes() == b"second"
