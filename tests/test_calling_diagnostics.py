import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.calling import diagnostics as d
from app.calling.models import CallDirection, CallStatus, CallTranscriptTurn, RawCallTranscript, TranscriptSpeaker
from app.calling.scenario import CallingPersona
from app.calling.voice_conversation_runner import VoiceConversationRunner
from app.calling.voice_transport import VoiceTransportSession
from app.config import Settings, settings


@pytest.fixture
def capture(monkeypatch):
    events = []
    monkeypatch.setattr(settings, "calling_diagnostics_enabled", True)
    monkeypatch.setattr(settings, "calling_diagnostics_encrypted_text", False)
    monkeypatch.setattr(d.log_manager, "add_log", lambda eid, entry: events.append((eid, json.loads(entry["message"]))))
    token = d._trace.set(None)
    yield events
    d._trace.reset(token)


def test_disabled_by_default_and_does_not_call_sink(capture, monkeypatch):
    assert Settings.model_fields["calling_diagnostics_enabled"].default is False
    assert Settings.model_fields["calling_diagnostics_encrypted_text"].default is False
    monkeypatch.setattr(settings, "calling_diagnostics_enabled", False)
    token = d._trace.set(d.Trace("eval_disabled"))
    try:
        with d.stage("test", "test", {"text": "Rahul Sharma 9876543210"}):
            d.emit("test", "test", {"text": "private"})
    finally:
        d._trace.reset(token)
    assert capture == []


def test_masking_and_opt_in_key_control(capture, monkeypatch):
    token = d._trace.set(d.Trace("eval_private"))
    payload = {"name": "Rahul Sharma", "phone": "9876543210", "address": "12 Private Street",
               "api_key": "never-show-this", "headers": {"Authorization": "Bearer private"}}
    try:
        d.emit("test", "test", payload)
        assert "encrypted_data" not in capture[-1][1]
        key = Fernet.generate_key()
        monkeypatch.setattr(settings, "calling_diagnostics_encrypted_text", True)
        monkeypatch.setattr(settings, "calling_diagnostics_encryption_key", SecretStr(key.decode()))
        d.emit("test", "test", payload)
    finally:
        d._trace.reset(token)
    ordinary = json.dumps(capture)
    for secret in ("Rahul Sharma", "9876543210", "12 Private Street", "never-show-this", "Bearer private", key.decode()):
        assert secret not in ordinary
    encrypted = capture[-1][1]["encrypted_data"].encode()
    decoded = json.loads(Fernet(key).decrypt(encrypted))
    assert decoded["phone"] == "9876543210"
    assert decoded["api_key"] == "[SECRET OMITTED]"
    assert decoded["headers"] == "[SECRET OMITTED]"
    with pytest.raises(InvalidToken):
        Fernet(Fernet.generate_key()).decrypt(encrypted)


def test_invalid_encryption_key_fails_closed(capture, monkeypatch):
    monkeypatch.setattr(settings, "calling_diagnostics_encrypted_text", True)
    monkeypatch.setattr(settings, "calling_diagnostics_encryption_key", SecretStr("bad-key"))
    token = d._trace.set(d.Trace("eval_bad_key"))
    try:
        d.emit("test", "test", {"text": "9876543210"})
    finally:
        d._trace.reset(token)
    assert capture[-1][1]["encrypted_capture_failed"] is True
    assert "9876543210" not in json.dumps(capture)


def test_sink_failure_and_exception_messages_do_not_escape(capture, monkeypatch):
    token = d._trace.set(d.Trace("eval_failure"))
    try:
        with pytest.raises(ValueError, match="private exception"):
            with d.stage("groq", "test"):
                raise ValueError("private exception 9876543210")
        assert "private exception" not in json.dumps(capture)
        assert any(event["stage"] == "groq.error" for _, event in capture)
        monkeypatch.setattr(d.log_manager, "add_log", Mock(side_effect=RuntimeError("sink unavailable")))
        d.emit("test", "test", {"text": "private"})
    finally:
        d._trace.reset(token)


def _conversation():
    transport = Mock(spec=["connect", "receive_audio", "send_audio", "hang_up", "control_messages", "last_utterance_complete"])
    transport.control_messages = []
    transport.last_utterance_complete.return_value = True

    def receive(**kwargs):
        transport.control_messages.append({"type": "speech-update", "status": "stopped", "role": "assistant"})
        return b"audio"

    transport.receive_audio.side_effect = receive
    stt = Mock()
    stt.transcribe.return_value = "Please clarify your phone number."
    tts = Mock()
    tts.synthesize.return_value = b"customer audio"
    persona = CallingPersona(name="Rahul Sharma", goal="Arrange an appointment. Answer only requested details.",
                             tone="polite", edge_case="Do not volunteer unrelated details.", phone_number="9876543210")
    response = Mock()
    response.choices = [Mock(message=Mock(content=" {{fact:phone_number}}. "))]
    session = VoiceTransportSession(transport_name="test", transport_call_id="provider_call_test",
                                   direction=CallDirection.inbound, status=CallStatus.in_progress)
    return transport, stt, tts, persona, response, session


def test_boundaries_correlation_timing_and_provider_copy(capture, monkeypatch):
    from app.calling.execution_pipeline import _fetch_provider_transcript
    from app.calling.ui_api import CallingRunResponse, _persist_calling_response

    monkeypatch.setattr("app.evaluation_store.new_evaluation_id", lambda: "eval_trace_test")
    transport, stt, tts, persona, response, session = _conversation()
    persisted = []

    def save(payload):
        persisted.append(payload)
        return payload

    monkeypatch.setattr("app.calling.ui_api.save_evaluation_report", save)
    provider = Mock()
    provider.fetch_transcript.return_value = RawCallTranscript(
        session_id="session_test", run_id="run_test", source="provider",
        turns=[CallTranscriptTurn(speaker=TranscriptSpeaker.customer, text="9876543210.", turn_index=0)],
    )

    @d.traced_evaluation
    def execute():
        with patch("app.calling.simulator.Groq") as groq:
            groq.return_value.chat.completions.create.return_value = response
            transcript = VoiceConversationRunner(max_turns=1, stt_provider=stt, tts_provider=tts).run(
                persona=persona, transport=transport, session=session, session_id="session_test", run_id="run_test",
            )
            assert transcript.turns[-1].text == "9876543210."
            request = groq.return_value.chat.completions.create.call_args.kwargs["messages"]
            assert f"Latest complete agent utterance: {stt.transcribe.return_value}" in request[0]["content"]
            assert "9876543210" not in request[0]["content"]
        _fetch_provider_transcript(provider, Mock())
        return _persist_calling_response(
            response=CallingRunResponse(success=True, status="completed", connection_id="test", provider="test", created_at="now"),
            scenario=None,
        )

    result = execute()
    assert result.evaluation_id == persisted[0]["evaluation_id"] == "eval_trace_test"
    assert d.evaluation_id() is None
    assert all(eid == event["evaluation_id"] == "eval_trace_test" for eid, event in capture)
    events = [event for _, event in capture]
    stages = {event["stage"] for event in events}
    assert {"stt.result", "agent.simulator_input", "groq.request", "groq.response", "customer.selected",
            "tts.start", "tts.end", "customer.send.end", "provider.transcript", "utterance.control_observed"} <= stages
    turn_events = [e for e in events if e["stage"] in {"stt.result", "agent.simulator_input", "groq.request", "groq.response", "tts.start", "provider.transcript"}]
    assert {e["turn_id"] for e in turn_events} == {"session_test:0"}
    assert all(e["timestamp"].endswith("+00:00") and e["monotonic_ns"] > 0 for e in events)
    assert all(e["duration_ms"] >= 0 for e in events if e["stage"].endswith(".end"))
    tts.synthesize.assert_called_once_with("9876543210.")
    by_stage = {e["stage"]: e for e in events}
    assert by_stage["groq.response"]["data"]["text"]["fingerprint"] == d.fingerprint("{{fact:phone_number}}.")
    assert by_stage["tts.start"]["data"]["text"]["fingerprint"] == d.fingerprint("9876543210.")
    assert by_stage["provider.transcript"]["exact_text_match"] is True
    assert by_stage["provider.transcript"]["correlation"] == "ordinal_candidate"
    assert by_stage["provider.transcript"]["evalforge_copy_is_independent"] is False
    assert by_stage["utterance.control_observed"]["event_time_known"] is False
    assert "9876543210" not in json.dumps(events)


def test_thread_contexts_are_isolated(capture):
    def work(index):
        token = d._trace.set(d.Trace(f"eval_{index}", f"session_{index}"))
        try:
            d.begin_turn(0)
            d.emit("test", "test")
        finally:
            d._trace.reset(token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(work, range(2)))
    assert {(eid, event["turn_id"]) for eid, event in capture} == {
        ("eval_0", "session_0:0"), ("eval_1", "session_1:0"),
    }


def test_prompts_parameters_and_responses_identical_with_debug_on_or_off(capture, monkeypatch):
    from app.calling.simulator import generate_next_user_turn

    _, _, _, persona, response, _ = _conversation()
    turns = [CallTranscriptTurn(speaker=TranscriptSpeaker.agent, text="What is your phone number?", turn_index=0)]
    requests, outputs = [], []
    for enabled in (False, True):
        monkeypatch.setattr(settings, "calling_diagnostics_enabled", enabled)
        token = d._trace.set(d.Trace("eval_equivalence"))
        try:
            with patch("app.calling.simulator.Groq") as groq:
                groq.return_value.chat.completions.create.return_value = response
                outputs.append(generate_next_user_turn(persona, turns))
                requests.append(groq.return_value.chat.completions.create.call_args.kwargs)
        finally:
            d._trace.reset(token)
    assert requests[0] == requests[1]
    assert outputs[0] == outputs[1] == {"message": "9876543210.", "attachments": None}
    assert len([event for _, event in capture if event["stage"] == "groq.request"]) == 1


def test_control_events_are_captured_even_when_receive_raises(capture):
    transport, stt, tts, persona, response, session = _conversation()

    def fail_receive(**kwargs):
        transport.control_messages.append({"type": "ended", "reason": "private reason"})
        raise RuntimeError("private error")

    transport.receive_audio.side_effect = fail_receive
    with pytest.raises(RuntimeError, match="private error"):
        VoiceConversationRunner(max_turns=1, stt_provider=stt, tts_provider=tts).run(
            persona=persona, transport=transport, session=session, session_id="session_test", run_id="run_test",
        )
    stages = {event["stage"] for _, event in capture}
    assert {"utterance.control_observed", "audio.receive.error", "conversation.error"} <= stages
    assert "private reason" not in json.dumps(capture)
    transport.hang_up.assert_called_once_with(session)


def test_disabled_diagnostics_does_not_inspect_control_buffer(capture, monkeypatch):
    monkeypatch.setattr(settings, "calling_diagnostics_enabled", False)

    class NoInspection:
        @property
        def control_messages(self):
            raise AssertionError("diagnostics must not access this")

    assert d.control_snapshot(NoInspection()) is None


def test_encrypted_request_contains_only_content_actually_passed_to_groq(capture, monkeypatch):
    from app.calling.simulator import generate_next_user_turn

    key = Fernet.generate_key()
    monkeypatch.setattr(settings, "calling_diagnostics_encrypted_text", True)
    monkeypatch.setattr(settings, "calling_diagnostics_encryption_key", SecretStr(key.decode()))
    _, _, _, persona, response, _ = _conversation()
    persona.__pydantic_extra__["api_key"] = "credential-never-capture"
    token = d._trace.set(d.Trace("eval_exact"))
    try:
        with patch("app.calling.simulator.Groq") as groq:
            groq.return_value.chat.completions.create.return_value = response
            generate_next_user_turn(
                persona,
                [CallTranscriptTurn(speaker=TranscriptSpeaker.agent, text="What is your phone number?", turn_index=0)],
            )
    finally:
        d._trace.reset(token)
    request = next(event for _, event in capture if event["stage"] == "groq.request")
    private = json.loads(Fernet(key).decrypt(request["encrypted_data"].encode()))
    assert private["action"] == "facts"
    assert private["allowed_fields"] == ["phone_number"]
    assert private["latest_agent"] == "What is your phone number?"
    assert "9876543210" not in json.dumps(private)
    assert "credential-never-capture" not in json.dumps(private)
    assert "credential-never-capture" not in json.dumps(capture)


def test_trace_reader_requires_explicit_decrypt(capture, monkeypatch, tmp_path, capsys):
    from scripts.read_calling_trace import main

    key = Fernet.generate_key()
    monkeypatch.setattr(settings, "calling_diagnostics_encrypted_text", True)
    monkeypatch.setattr(settings, "calling_diagnostics_encryption_key", SecretStr(key.decode()))
    token = d._trace.set(d.Trace("eval_reader"))
    try:
        d.emit("test", "test", {"text": "Rahul Sharma 9876543210"})
    finally:
        d._trace.reset(token)
    path = tmp_path / "trace.txt"
    path.write_text("[timestamp] DEBUG - " + json.dumps(capture[-1][1]), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["read_calling_trace", str(path)])
    main()
    assert "9876543210" not in capsys.readouterr().out
    monkeypatch.setenv("CALLING_DIAGNOSTICS_ENCRYPTION_KEY", key.decode())
    monkeypatch.setattr("sys.argv", ["read_calling_trace", str(path), "--decrypt"])
    main()
    assert "Rahul Sharma 9876543210" in capsys.readouterr().out
