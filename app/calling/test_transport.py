"""Backward-compatible aliases for the renamed evaluator voice transport module."""

from app.calling.voice_transport import (
    TwilioVoiceTransport as TwilioTestCallTransport,
    UnconfiguredVoiceTransport as UnconfiguredTestCallTransport,
    VapiVoiceTransport as VapiTestCallTransport,
    VoiceTransport as TestCallTransport,
    VoiceTransportCapabilities as TestCallTransportCapabilities,
    VoiceTransportConfig as TestCallTransportConfig,
    VoiceTransportError as TestCallTransportError,
    VoiceTransportSession as TestCallTransportSession,
    transport_session_to_call_session,
)

__all__ = [
    "TestCallTransport",
    "TestCallTransportCapabilities",
    "TestCallTransportConfig",
    "TestCallTransportError",
    "TestCallTransportSession",
    "TwilioTestCallTransport",
    "UnconfiguredTestCallTransport",
    "VapiTestCallTransport",
    "transport_session_to_call_session",
]
