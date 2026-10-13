from __future__ import annotations

import pytest

from app.calling.models import CallDirection, CallProvider, CallRecording, CallSession, CallStatus
from app.calling.provider_adapter import CallProviderAdapter, ProviderCapabilities


def test_provider_adapter_is_abstract():
    with pytest.raises(TypeError):
        CallProviderAdapter()


class FakeProvider(CallProviderAdapter):
    def start_outbound_call(self, *, to, from_=None, metadata=None):
        return CallSession(
            direction=CallDirection.outbound,
            provider=CallProvider.custom,
            to_number=to,
            from_number=from_,
            status=CallStatus.dialing,
            metadata=metadata or {},
        )

    def prepare_inbound_call(self, *, expected_from=None, metadata=None):
        return CallSession(
            direction=CallDirection.inbound,
            provider=CallProvider.custom,
            from_number=expected_from,
            status=CallStatus.prepared,
            metadata=metadata or {},
        )

    def get_call_status(self, session):
        return session.status

    def end_call(self, session):
        return session.mark_completed("2026-10-01T10:10:00+00:00")

    def fetch_recording(self, session):
        return CallRecording(session_id=session.session_id, recording_id="rec-1")

    def fetch_events(self, session):
        return []

    def download_recording(self, recording, destination_dir):
        return recording.model_copy(update={"path": f"{destination_dir}/audio.wav"})


def test_provider_adapter_contract_can_be_implemented_without_vendor_logic():
    provider = FakeProvider()

    outbound = provider.start_outbound_call(to="+15550000002", from_="+15550000001")
    inbound = provider.prepare_inbound_call(expected_from="+15550000003")
    ended = provider.end_call(outbound)
    recording = provider.fetch_recording(outbound)
    downloaded = provider.download_recording(recording, "artifacts/calling/run-1")

    assert outbound.direction == CallDirection.outbound
    assert outbound.status == CallStatus.dialing
    assert inbound.direction == CallDirection.inbound
    assert inbound.status == CallStatus.prepared
    assert ended.status == CallStatus.completed
    assert provider.get_call_status(outbound) == CallStatus.dialing
    assert downloaded.path.endswith("audio.wav")


def test_default_provider_capabilities_are_provider_neutral_and_conservative():
    provider = FakeProvider()

    capabilities = provider.get_capabilities()

    assert isinstance(capabilities, ProviderCapabilities)
    assert capabilities.supported_connection_methods() == []
    assert capabilities.supports_direct_sessions is False
    assert capabilities.requires_external_transport is False
