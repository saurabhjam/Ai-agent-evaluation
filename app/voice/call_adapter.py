"""
Abstract CallAdapter — future telephony abstraction.

This module defines the interface for adapters that manage a REAL phone call
to the voice agent under test.  It is NOT implemented yet; it exists to
define the contract that future phone adapters will follow.

Supported transports (future):
  - PSTN / SIP (e.g. Twilio, Telnyx, Vonage)
  - WebRTC (e.g. Vapi, LiveKit)
  - WebSocket (e.g. custom voice agent servers)
  - Vendor-specific telephony APIs (e.g. Vapi, Twilio, ElevenLabs)

To add a new phone provider:
  1. Sub-class CallAdapter.
  2. Implement all abstract methods.
  3. Return vendor-neutral types only.
  4. Register the new type in VoiceAdapterFactory (app/voice/factory.py).

This file contains no vendor imports, no credentials, and no paid-API calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional


class CallStatus(str, Enum):
    """Lifecycle state of a phone call."""
    idle = "idle"
    dialing = "dialing"
    ringing = "ringing"
    connected = "connected"
    ended = "ended"
    failed = "failed"


class CallAdapter(ABC):
    """
    Abstract interface for telephony-backed voice adapters.

    A CallAdapter manages the phone call layer; the associated VoiceAdapter
    handles conversation logic (turns, events, transcription).

    Future architecture:

        Scenario
           |
           v
        Test Orchestrator
           |
           v
        VoiceAdapter            <- conversation logic (this repo)
           |
           v
        CallAdapter             <- call management (this class)
           |
           +---- WebSocket
           |
           +---- WebRTC
           |
           +---- SIP / PSTN
           |
           +---- Vendor-specific (Twilio, Vapi, ...)
                      |
                      v
                CLIENT VOICE AGENT
    """

    @abstractmethod
    def start_call(
        self,
        to: str,
        from_: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Initiate a phone call to the voice agent.

        Parameters
        ----------
        to:
            Destination address (phone number, SIP URI, WebRTC room, etc.)
        from_:
            Originating address (caller ID, SIP URI, etc.)
        metadata:
            Optional vendor-specific call parameters.

        Returns
        -------
        str
            A call_id string that uniquely identifies this call.
        """
        ...

    @abstractmethod
    def get_call_status(self, call_id: str) -> CallStatus:
        """
        Return the current lifecycle status of a call.
        """
        ...

    @abstractmethod
    def end_call(self, call_id: str) -> None:
        """
        Terminate an active call cleanly.
        """
        ...

    def connect(self, call_id: str) -> None:
        """
        Optional: perform any post-dial setup once the call is connected
        (e.g. mute hold music, join audio bridge, start recording).
        """

    def get_call_metadata(self, call_id: str) -> dict[str, Any]:
        """
        Return vendor-neutral metadata about a call (duration, cost, etc.).
        Implementations should translate vendor-specific fields.
        """
        return {}
