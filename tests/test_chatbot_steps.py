from app.adapters.chat.base import CapabilityNotSupported, ChatAdapterTimeout, FieldNotFound
from app.executor import ScenarioExecutor
from app.models.connection import AgentConnection, AgentType
from app.models.conversation import ConversationMessage, NormalizedConversation
from app.schemas import AgentConfig, Persona, TestScenario


class StepAdapter:
    def __init__(self):
        self.messages = []
        self.buttons = []
        self.transcript = []

    def connect(self):
        pass

    def send_message(self, message, agent_prompt=None, attachments=None):
        self.messages.append(message)
        self.transcript.append(ConversationMessage(role="simulated_user", content=message, turn_index=len(self.transcript)))
        self.transcript.append(ConversationMessage(role="agent", content="sent", turn_index=len(self.transcript)))
        return "sent"

    def click_button(self, text=None, *, metadata=None):
        metadata = metadata or {}
        self.buttons.append((text, metadata.get("selector")))
        self.transcript.append(
            ConversationMessage(
                role="simulated_user",
                content=f"Click Button\n{text or metadata.get('selector')}",
                turn_index=len(self.transcript),
                metadata={"action": "click_button"},
            )
        )
        self.transcript.append(ConversationMessage(role="agent", content="clicked", turn_index=len(self.transcript)))
        return "clicked"

    def select_dropdown(self, field, value, *, metadata=None):
        metadata = metadata or {}
        self.transcript.append(ConversationMessage(role="simulated_user", content=f"Select Dropdown\n{field or metadata.get('selector')} = {value}", turn_index=len(self.transcript)))
        return "selected"

    def select_radio(self, field, value, *, metadata=None):
        metadata = metadata or {}
        self.transcript.append(ConversationMessage(role="simulated_user", content=f"Radio\n{field or metadata.get('selector')} = {value}", turn_index=len(self.transcript)))
        return "radio"

    def select_checkbox(self, field, value=True, *, metadata=None):
        metadata = metadata or {}
        self.transcript.append(ConversationMessage(role="simulated_user", content=f"Checkbox\n{field or metadata.get('selector')} = {str(bool(value)).lower()}", turn_index=len(self.transcript)))
        return "checkbox"

    def select_multi_select(self, field, values, *, metadata=None):
        metadata = metadata or {}
        self.transcript.append(ConversationMessage(role="simulated_user", content=f"Multi Select\n{field or metadata.get('selector')} = {','.join(values)}", turn_index=len(self.transcript)))
        return "multi"

    def upload_file(self, file, *, field=None, metadata=None):
        self.transcript.append(ConversationMessage(role="simulated_user", content=f"Upload File\n{file}", turn_index=len(self.transcript), attachments=[file]))
        return "Success"

    def upload_image(self, image, *, field=None, metadata=None):
        self.transcript.append(ConversationMessage(role="simulated_user", content=f"Upload Image\n{image}", turn_index=len(self.transcript), attachments=[image]))
        return "Success"

    def enter_otp(self, value, *, field=None, metadata=None):
        metadata = metadata or {}
        self.transcript.append(ConversationMessage(role="simulated_user", content="Entered OTP\n******", turn_index=len(self.transcript), metadata={"action": "enter_otp", "masked": True}))
        return "Success"

    def pick_date(self, field, value, *, metadata=None):
        metadata = metadata or {}
        self.transcript.append(ConversationMessage(role="simulated_user", content=f"Date\n{field or metadata.get('selector')} = {value}", turn_index=len(self.transcript)))
        return "Success"

    def pick_time(self, field, value, *, metadata=None):
        metadata = metadata or {}
        self.transcript.append(ConversationMessage(role="simulated_user", content=f"Time\n{field or metadata.get('selector')} = {value}", turn_index=len(self.transcript)))
        return "Success"

    def search(self, query, *, field=None, metadata=None):
        metadata = metadata or {}
        self.transcript.append(ConversationMessage(role="simulated_user", content=f"Search\n{field or metadata.get('selector')} = {query}", turn_index=len(self.transcript)))
        return "Success"

    def wait_for_text(self, text, *, timeout=None, metadata=None):
        self.transcript.append(ConversationMessage(role="simulated_user", content=f"Wait For\n{text}\nResult\nSuccess\nDuration\n0.10 seconds", turn_index=len(self.transcript), metadata={"action": "wait_for", "text": text}))
        return "Success"

    def get_transcript(self):
        return self.transcript

    def get_conversation(self):
        return NormalizedConversation(run_id="r", session_id="s", channel="chatbot", messages=self.transcript)

    def close(self):
        pass


class UnsupportedButtonAdapter(StepAdapter):
    def click_button(self, text=None, *, metadata=None):
        raise CapabilityNotSupported("UnsupportedButtonAdapter does not support click_button.")


class MissingFieldAdapter(StepAdapter):
    def select_dropdown(self, field, value, *, metadata=None):
        raise FieldNotFound(f"Control not found for {field}.")


class UnsupportedDropdownAdapter(StepAdapter):
    def select_dropdown(self, field, value, *, metadata=None):
        raise CapabilityNotSupported("Dropdown is not supported.")


class UnsupportedWaitAdapter(StepAdapter):
    def wait_for_text(self, text, *, timeout=None, metadata=None):
        raise CapabilityNotSupported("wait_for_text is not supported.")


class TimeoutWaitAdapter(StepAdapter):
    def wait_for_text(self, text, *, timeout=None, metadata=None):
        raise ChatAdapterTimeout(f"Expected text not found before timeout: {text}")


class Manager:
    def __init__(self, adapter):
        self.adapter = adapter

    def create_adapter(self, connection):
        return self.adapter


def _connection():
    return AgentConnection(id="c1", name="Chat", type=AgentType.chatbot, adapter="fake", config={})


def _scenario(steps):
    return TestScenario(
        scenario_id="button_steps",
        agent=AgentConfig(channel="chatbot", adapter="fake", config={}),
        persona=Persona(name="Ava", goal="Book an appointment", tone="polite"),
        steps=steps,
    )


def test_scenario_executor_runs_click_button_step_by_text():
    adapter = StepAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"click_button": {"text": "Book Appointment"}}]),
    )

    assert result.success is True
    assert adapter.buttons == [("Book Appointment", None)]
    assert result.transcript[0].content == "Click Button\nBook Appointment"


def test_scenario_executor_runs_click_button_step_by_selector():
    adapter = StepAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"click_button": {"selector": "#book"}}]),
    )

    assert result.success is True
    assert adapter.buttons == [(None, "#book")]


def test_scenario_executor_returns_structured_error_for_unsupported_button():
    adapter = UnsupportedButtonAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"click_button": {"text": "Book Appointment"}}]),
    )

    assert result.success is False
    assert "CapabilityNotSupported" in result.error
    assert "Traceback" not in result.error


def test_scenario_executor_runs_dropdown_radio_checkbox_and_multi_select_steps():
    adapter = StepAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([
            {"select": {"field": "City", "value": "Pune"}},
            {"radio": {"field": "Insurance Type", "value": "Health"}},
            {"checkbox": {"field": "Accept Terms", "value": True}},
            {"multi_select": {"field": "Languages", "values": ["English", "Hindi"]}},
        ]),
    )

    assert result.success is True
    assert result.transcript[0].content == "Select Dropdown\nCity = Pune"
    assert result.transcript[1].content == "Radio\nInsurance Type = Health"
    assert result.transcript[2].content == "Checkbox\nAccept Terms = true"
    assert result.transcript[3].content == "Multi Select\nLanguages = English,Hindi"


def test_scenario_executor_runs_simple_form_step():
    adapter = StepAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"form": {"first_name": "Avi", "last_name": "Lokhande", "email": "avi@test.com"}}]),
    )

    assert result.success is True
    assert result.transcript[0].content == "Form\nFirst Name = Avi"
    assert result.transcript[2].content == "Form\nLast Name = Lokhande"
    assert result.transcript[4].content == "Form\nEmail = avi@test.com"


def test_scenario_executor_runs_mixed_form_step():
    adapter = StepAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{
            "form": {
                "first_name": "Avi",
                "city": "Pune",
                "insurance_type": "Health",
                "accept_terms": True,
                "languages": ["English", "Hindi"],
            }
        }]),
    )

    assert result.success is True
    contents = [turn.content for turn in result.transcript]
    assert "Form\nFirst Name = Avi" in contents
    assert "Select Dropdown\nCity = Pune" in contents
    assert "Radio\nInsurance Type = Health" in contents
    assert "Checkbox\nAccept Terms = true" in contents
    assert "Multi Select\nLanguages = English,Hindi" in contents


def test_optional_form_field_not_found_continues():
    adapter = MissingFieldAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{
            "form": {
                "company": {"type": "dropdown", "value": "OpenAI", "required": False},
                "first_name": "Avi",
            }
        }]),
    )

    assert result.success is True
    assert result.transcript[0].content == "Form\nFirst Name = Avi"


def test_required_form_field_not_found_fails_cleanly():
    adapter = MissingFieldAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"form": {"city": {"type": "dropdown", "value": "Pune", "required": True}}}]),
    )

    assert result.success is False
    assert "Required field missing" in result.error
    assert "Traceback" not in result.error


def test_form_capability_not_supported_fails_cleanly():
    adapter = UnsupportedDropdownAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"form": {"city": {"type": "dropdown", "value": "Pune"}}}]),
    )

    assert result.success is False
    assert "CapabilityNotSupported" in result.error
    assert "Traceback" not in result.error


def test_scenario_executor_runs_upload_image_step():
    adapter = StepAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"upload": {"field": "Damage Photo", "file": "test-data/damage.jpg"}}]),
    )

    assert result.success is True
    assert result.transcript[0].content == "Upload Image\ntest-data/damage.jpg"
    assert result.transcript[0].attachments == ["test-data/damage.jpg"]


def test_scenario_executor_runs_upload_pdf_step():
    adapter = StepAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"upload": {"field": "Insurance Document", "file": "test-data/policy.pdf"}}]),
    )

    assert result.success is True
    assert result.transcript[0].content == "Upload File\ntest-data/policy.pdf"


def test_scenario_executor_runs_otp_date_time_and_search_steps():
    adapter = StepAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([
            {"otp": {"field": "OTP", "value": "123456"}},
            {"date": {"field": "Appointment Date", "value": "2026-10-15"}},
            {"time": {"field": "Appointment Time", "value": "14:30"}},
            {"search": {"field": "City", "value": "Pune"}},
        ]),
    )

    assert result.success is True
    assert result.transcript[0].content == "Entered OTP\n******"
    assert "123456" not in result.transcript[0].content
    assert result.transcript[1].content == "Date\nAppointment Date = 2026-10-15"
    assert result.transcript[2].content == "Time\nAppointment Time = 14:30"
    assert result.transcript[3].content == "Search\nCity = Pune"


def test_scenario_executor_runs_otp_step_by_selector():
    adapter = StepAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"otp": {"selector": "#otp", "value": "123456"}}]),
    )

    assert result.success is True
    assert result.transcript[0].content == "Entered OTP\n******"


def test_scenario_executor_runs_wait_for_after_button_step():
    adapter = StepAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"click_button": {"text": "Book Appointment", "wait_for": {"text": "Appointment Booked", "timeout": 30}}}]),
    )

    assert result.success is True
    assert result.transcript[0].content == "Click Button\nBook Appointment"
    assert result.transcript[2].content == "Wait For\nAppointment Booked\nResult\nSuccess\nDuration\n0.10 seconds"


def test_scenario_executor_ignores_form_wait_for_as_form_field():
    adapter = StepAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"form": {"first_name": "Avi", "wait_for": {"text": "Claim Submitted"}}}]),
    )

    assert result.success is True
    contents = [turn.content for turn in result.transcript]
    assert "Form\nFirst Name = Avi" in contents
    assert "Wait For\nClaim Submitted\nResult\nSuccess\nDuration\n0.10 seconds" in contents
    assert all("Wait For = {'text': 'Claim Submitted'}" not in content for content in contents)


def test_scenario_executor_wait_for_capability_not_supported_fails_cleanly():
    adapter = UnsupportedWaitAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"search": {"field": "City", "value": "Pune", "wait_for": {"text": "Pune"}}}]),
    )

    assert result.success is False
    assert "CapabilityNotSupported" in result.error
    assert "Traceback" not in result.error


def test_scenario_executor_wait_for_timeout_fails_cleanly():
    adapter = TimeoutWaitAdapter()
    result = ScenarioExecutor(Manager(adapter)).execute(
        _connection(),
        _scenario([{"upload": {"field": "Damage Photo", "file": "test-data/damage.jpg", "wait_for": {"text": "Uploaded", "timeout": 1}}}]),
    )

    assert result.success is False
    assert "ChatAdapterTimeout" in result.error
    assert "Traceback" not in result.error
