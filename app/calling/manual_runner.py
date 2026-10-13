"""Manual Twilio smoke-test runner for AI Calling Agent Evaluation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from app.calling.conversation_evidence import EvidenceArtifact
from app.calling.conversation_normalizer import ConversationNormalizer
from app.calling.evaluation_bridge import CallingEvaluationBridge
from app.calling.evidence_builder import EvidenceBuilder
from app.calling.execution_result import CallingExecutionResult, CallingExecutionStatus
from app.calling.manual_config import ManualCallingConfig
from app.calling.models import (
    CallArtifactType,
    CallDirection,
    CallRecording,
    CallSession,
    CallStatus,
    RawCallTranscript,
)
from app.calling.provider_factory import ProviderFactory
from app.calling.provider_registry import ProviderRegistry
from app.calling.provider_resolver import ProviderResolver
from app.calling.providers.twilio import TwilioProvider
from app.evaluation_service import EvaluationResult


TERMINAL_STATUSES = {
    CallStatus.completed,
    CallStatus.failed,
    CallStatus.busy,
    CallStatus.no_answer,
    CallStatus.canceled,
    CallStatus.cancelled,
    CallStatus.timed_out,
    CallStatus.error,
}


@dataclass
class ManualCallingRunResult:
    """Output of the manual Twilio smoke runner."""

    call_session: CallSession
    recording: Optional[CallRecording]
    calling_result: CallingExecutionResult
    evaluation_result: EvaluationResult
    duration_seconds: float


@dataclass
class ManualCallingRunner:
    """Runs a real Twilio outbound call through the calling architecture."""

    evaluation_bridge: CallingEvaluationBridge = field(default_factory=CallingEvaluationBridge)

    def run(self, config: ManualCallingConfig) -> ManualCallingRunResult:
        """Execute one manual Twilio smoke test."""
        provider = self._resolve_twilio_provider(config)
        started = time.monotonic()
        session = provider.start_outbound_call(
            to=config.destination_number,
            from_=config.from_number,
            metadata={"scenario_id": config.scenario.scenario_id, "manual_smoke_test": True},
        )
        session = self._wait_for_completion(provider, session, config)
        recording = provider.fetch_recording(session) if config.recording_enabled else None
        events = provider.fetch_events(session)
        transcript = RawCallTranscript(
            session_id=session.session_id,
            run_id=session.run_id,
            turns=config.transcript_turns,
            source="manual_config",
            metadata={
                "provider": "twilio",
                "provider_call_id": session.provider_call_id,
                "transcript_supplied": bool(config.transcript_turns),
            },
        )
        evidence_artifacts = self._artifact_placeholders(session, recording)
        evidence = EvidenceBuilder().build(
            session=session,
            events=events,
            recordings=[recording] if recording else [],
            transcript=transcript,
            artifacts=evidence_artifacts,
            rag_context=config.scenario.rag_context,
        )
        normalized = ConversationNormalizer().normalize(
            evidence,
            scenario_id=config.scenario.scenario_id,
            rag_config=config.rag_config,
        )
        duration = time.monotonic() - started
        calling_result = CallingExecutionResult(
            status=CallingExecutionStatus.completed if session.status == CallStatus.completed else CallingExecutionStatus.failed,
            call_session=session,
            conversation_evidence=evidence,
            normalized_conversation=normalized,
            artifacts=evidence.attachments,
            execution_metadata={
                "manual_smoke_test": True,
                "scenario_id": config.scenario.scenario_id,
                "recording_enabled": config.recording_enabled,
            },
            provider_metadata=session.provider_metadata,
            duration_seconds=duration,
            error=None if session.status == CallStatus.completed else f"Call ended with status {session.status.value}.",
        )
        evaluation_result = self.evaluation_bridge.evaluate(calling_result, config.scenario)
        return ManualCallingRunResult(
            call_session=session,
            recording=recording,
            calling_result=calling_result,
            evaluation_result=evaluation_result,
            duration_seconds=duration,
        )

    def _resolve_twilio_provider(self, config: ManualCallingConfig) -> TwilioProvider:
        registry = ProviderRegistry()
        registry.register("twilio", TwilioProvider)
        resolver = ProviderResolver(registry=registry, factory=ProviderFactory(registry))
        provider = resolver.resolve(config.provider_config())
        if not isinstance(provider, TwilioProvider):
            raise TypeError("Resolved provider is not TwilioProvider.")
        return provider

    def _wait_for_completion(
        self,
        provider: TwilioProvider,
        session: CallSession,
        config: ManualCallingConfig,
    ) -> CallSession:
        deadline = time.monotonic() + config.timeout_seconds
        current = session
        while time.monotonic() < deadline:
            status = provider.get_call_status(current)
            current = current.model_copy(update={"status": status})
            if status in TERMINAL_STATUSES:
                return current
            time.sleep(config.poll_interval_seconds)
        return current.model_copy(update={"status": CallStatus.timed_out})

    @staticmethod
    def _artifact_placeholders(
        session: CallSession,
        recording: Optional[CallRecording],
    ) -> list[EvidenceArtifact]:
        artifacts = [
            EvidenceArtifact(
                session_id=session.session_id,
                name="events.json",
                artifact_type=CallArtifactType.events.value,
                path=f"artifacts/call/events/{session.run_id}.json",
                provider=session.provider,
                provider_name=session.provider_name,
                metadata={"source": "manual_runner", "materialized": False},
            ),
            EvidenceArtifact(
                session_id=session.session_id,
                name="transcript.json",
                artifact_type=CallArtifactType.transcript.value,
                path=f"artifacts/call/transcript/{session.run_id}.json",
                provider=session.provider,
                provider_name=session.provider_name,
                metadata={"source": "manual_runner", "materialized": False},
            ),
        ]
        if recording:
            artifacts.append(
                EvidenceArtifact(
                    session_id=session.session_id,
                    name="recording_url",
                    artifact_type="recording_url",
                    remote_url=recording.remote_url,
                    provider=session.provider,
                    provider_name=session.provider_name,
                    provider_artifact_id=recording.provider_recording_id,
                    metadata=recording.metadata,
                )
            )
        return artifacts
