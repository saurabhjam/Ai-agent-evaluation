"""Vapi connection validation for direct WebSocket calling."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import logging

import requests

from app.calling.config import CallingProviderConfig
from app.calling.provider_adapter import ProviderCapabilities

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VapiConnectionValidationResult:
    success: bool
    capabilities: ProviderCapabilities
    checks: list[str] = field(default_factory=list)
    message: str = ""
    assistant: Optional[dict[str, Any]] = None


class VapiConnectionValidator:
    """Validates Vapi credentials and WebSocket-call readiness."""

    def __init__(self, config: CallingProviderConfig):
        self.config = config
        self.base_url = str(config.settings.get("base_url") or "https://api.vapi.ai").rstrip("/")

    def validate(self) -> VapiConnectionValidationResult:
        logger.info("=== VAPI CONNECTION VALIDATION START ===")
        api_key = self._api_key()
        assistant_id = self.config.settings.get("assistant_id")
        logger.info("Validating API key...")
        logger.info("Vapi API key present: %s", bool(api_key))
        logger.info("Assistant ID: %s", assistant_id)
        checks: list[str] = []
        missing: list[str] = []
        if not api_key:
            missing.append("api_key")
        else:
            checks.append("credential:api_key")
        if not assistant_id:
            missing.append("assistant_id")
        else:
            checks.append("config:assistant_id")
        if missing:
            logger.error("Vapi validation missing fields: %s", missing)
            return VapiConnectionValidationResult(
                success=False,
                capabilities=self.capabilities(),
                checks=checks,
                message="Missing required fields: " + ", ".join(missing),
            )

        url = f"{self.base_url}/assistant/{assistant_id}"
        logger.info("Validating Vapi assistant exists...")
        logger.info("GET assistant URL: %s", url)
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=self.config.timeouts.get("request") or self.config.settings.get("timeout_seconds") or 30,
        )
        logger.info("Vapi assistant HTTP Status: %s", getattr(response, "status_code", "unknown"))
        logger.info("Vapi assistant HTTP Body: %s", getattr(response, "text", ""))
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            logger.exception("Vapi assistant validation failed")
            raise RuntimeError(f"Vapi assistant validation failed: {response.text}") from exc
        assistant = response.json()
        if not isinstance(assistant, dict) or not assistant.get("id"):
            logger.error("Vapi assistant validation returned invalid payload: %s", assistant)
            raise RuntimeError("Vapi assistant validation returned an invalid assistant payload.")

        checks.append("assistant:exists")
        checks.append("transport:vapi.websocket")
        logger.info("Vapi assistant validation succeeded")
        logger.info("WebSocket transport supported by integration: YES")
        logger.info("=== VAPI CONNECTION VALIDATION SUCCESS ===")
        return VapiConnectionValidationResult(
            success=True,
            capabilities=self.capabilities(),
            checks=checks,
            message="Vapi connection supports direct WebSocket calls.",
            assistant=assistant,
        )

    @staticmethod
    def capabilities() -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_direct_sessions=True,
            supports_inbound_sessions=True,
            supports_outbound_sessions=True,
            supports_webrtc=True,
            supports_sip=False,
            supports_pstn=False,
            requires_external_transport=False,
            supports_post_call_transcripts=True,
            supports_provider_transcript=True,
            preferred_transcript_source="provider",
            supports_live_transcripts=True,
            supports_recordings=True,
            metadata={
                "transport_provider": "vapi.websocket",
                "audio_format": "pcm_s16le",
                "container": "raw",
                "sample_rate": 24000,
            },
        )

    def _api_key(self) -> Optional[str]:
        from app.calling.providers.vapi import VapiProvider

        return VapiProvider._resolve_secret(self.config.credentials.get("api_key"))
