"""Runtime execution pipeline for AI Calling Agent Evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging

from app.calling.conversation_evidence import EvidenceArtifact
from app.calling.execution_context import CallingExecutionContext
from app.calling.execution_events import CallingExecutionEvent, CallingExecutionEventType
from app.calling.execution_result import CallingExecutionResult, CallingExecutionStatus
from app.calling.models import CallArtifactType, CallDirection, CallStatus, RawCallTranscript, utc_now_iso
from app.calling.provider_resolver import ProviderResolver
from app.calling.runner import CallSessionRunner
from app.calling.provider_adapter import ProviderCapabilities
from app.calling.voice_transport import (
    VoiceTransportError,
    TwilioVoiceTransport,
    VapiVoiceTransport,
    UnconfiguredVoiceTransport,
    transport_session_to_call_session,
)
from app.calling.voice_conversation_runner import VoiceConversationRunner

logger = logging.getLogger(__name__)


@dataclass
class CallingExecutionPipeline:
    """Connects provider resolution, session running, evidence, and normalization."""

    provider_resolver: ProviderResolver = field(default_factory=ProviderResolver)

    def execute(
        self,
        context: CallingExecutionContext,
        *,
        direction: CallDirection = CallDirection.outbound,
        to: str = "+15550000002",
        from_: str = "+15550000001",
    ) -> CallingExecutionResult:
        """Execute a configured-provider calling evaluation run without DeepEval."""
        started_at = utc_now_iso()
        events: list[CallingExecutionEvent] = [
            CallingExecutionEvent(
                event_type=CallingExecutionEventType.started,
                session_id=context.session_id,
                run_id=context.run_id,
                metadata={"provider": context.provider_config.provider_name},
            )
        ]

        try:
            provider = self.provider_resolver.resolve(context.provider_config)
            provider_capabilities = provider.get_capabilities()
            configured_provider = context.provider_config.provider_name
            provider_runtime = provider.__class__.__name__
            if configured_provider == "vapi":
                logger.info("=== VAPI EVALUATION START ===")
                logger.info("Scenario ID: %s", context.scenario.scenario_id)
                logger.info("Run ID: %s", context.run_id)
                logger.info("Direction: %s", direction.value)
                logger.info("Provider runtime: %s", provider_runtime)
                logger.info("Provider capabilities: %s", provider_capabilities)

            if configured_provider != "mock" and provider_runtime == "MockCallProvider":
                raise RuntimeError(
                    f"Provider invariant violated: configured_provider '{configured_provider}' resolved to mock runtime."
                )

            if configured_provider == "mock":
                runner = CallSessionRunner(provider_adapter=provider)
                runner_result = runner.run_mock_call(
                    to=to,
                    from_=from_,
                    scenario_id=context.scenario.scenario_id,
                    direction=direction,
                    retrieval_context=context.scenario.rag_context,
                    rag_config=context.provider_config.metadata.get("rag_config"),
                )
                session = runner_result.execution_result.session
                evidence = runner_result.conversation_evidence
                normalized = runner_result.normalized_conversation
                artifacts = list(runner_result.conversation_evidence.attachments)
            else:
                # Real execution path
                transport_transcript = None
                provider_voice_transport = provider.create_voice_transport()
                if configured_provider == "vapi":
                    logger.info("Provider voice transport available: %s", provider_voice_transport is not None)
                if provider_voice_transport is not None:
                    if configured_provider == "vapi":
                        logger.info("Creating provider-native voice transport session...")
                    transport_session = provider_voice_transport.originate_call(
                        to=to,
                        from_=from_,
                        metadata={
                            "scenario_id": context.scenario.scenario_id,
                            "configured_provider": configured_provider,
                            "evalforge_direction": direction.value,
                        },
                    )
                    session = transport_session_to_call_session(
                        transport_session,
                        provider_name=configured_provider,
                        provider_call_id=transport_session.metadata.get("provider_call_id"),
                        provider_metadata={
                            "configured_provider": configured_provider,
                            **transport_session.metadata,
                        },
                    )
                    if configured_provider == "vapi":
                        logger.info("Provider-native call session created: session_id=%s provider_call_id=%s", session.session_id, session.provider_call_id)
                        logger.info("Starting VoiceConversationRunner...")
                    transport_transcript = _voice_conversation_runner(context).run(
                        persona=context.scenario.persona,
                        transport=provider_voice_transport,
                        session=transport_session,
                        session_id=session.session_id,
                        run_id=session.run_id,
                    )
                    if configured_provider == "vapi":
                        logger.info("Conversation finished")
                        logger.info("RawCallTranscript turns: %d", len(transport_transcript.turns))
                elif direction == CallDirection.outbound:
                    session = provider.start_outbound_call(to=to, from_=from_, metadata={"scenario_id": context.scenario.scenario_id})
                else:
                    if _provider_supports_direct_inbound(provider_capabilities):
                        session = provider.prepare_inbound_call(
                            expected_from=from_,
                            metadata={"scenario_id": context.scenario.scenario_id},
                        )
                    elif provider_capabilities.requires_external_transport:
                        target_number = _client_agent_phone_number(context, fallback=to)
                        transport = _resolve_voice_transport(context, mode="inbound")
                        transport_session = transport.originate_call(
                            to=target_number,
                            from_=from_,
                            metadata={
                                "scenario_id": context.scenario.scenario_id,
                                "configured_provider": configured_provider,
                                "evalforge_direction": direction.value,
                            },
                        )
                        session = transport_session_to_call_session(
                            transport_session,
                            provider_name=configured_provider,
                            provider_call_id=transport_session.metadata.get("provider_call_id"),
                            provider_metadata={
                                "configured_provider": configured_provider,
                                "provider_correlation_required": True,
                                **transport_session.metadata,
                            },
                        )
                        if _transport_supports_conversation(transport):
                            transport_transcript = _voice_conversation_runner(context).run(
                                persona=context.scenario.persona,
                                transport=transport,
                                session=transport_session,
                                session_id=session.session_id,
                                run_id=session.run_id,
                            )
                    else:
                        raise RuntimeError(_unsupported_inbound_message(configured_provider, provider_capabilities))

                _assert_real_provider_session(configured_provider, session)
                if configured_provider == "vapi":
                    logger.info("Real provider session assertion passed")
                
                # Simple synchronous poll (in a real system, webhooks would handle this async)
                import time
                deadline = time.monotonic() + 10  # 10 second timeout for POC
                while time.monotonic() < deadline:
                    status = provider.get_call_status(session)
                    if configured_provider == "vapi":
                        logger.info("Polled Vapi status: %s", status.value)
                    session = session.model_copy(update={"status": status})
                    if status in {CallStatus.completed, CallStatus.failed, CallStatus.timed_out}:
                        break
                    time.sleep(1)
                
                provider_events = provider.fetch_events(session)
                recording = provider.fetch_recording(session)
                if configured_provider == "vapi":
                    logger.info("Vapi provider events: %d", len(provider_events))
                    logger.info("Vapi recording metadata available: %s", recording is not None)
                if recording:
                    _assert_real_provider_artifact(configured_provider, recording)
                
                from app.calling.evidence_builder import EvidenceBuilder
                from app.calling.conversation_normalizer import ConversationNormalizer
                
                transcript_obj = _select_transcript(
                    provider=provider,
                    capabilities=provider_capabilities,
                    session=session,
                    transport_transcript=transport_transcript,
                )
                if not transcript_obj or not transcript_obj.turns:
                    if configured_provider == "vapi":
                        logger.error("Vapi transcript unavailable or empty")
                    raise RuntimeError(
                        f"Transcript unavailable for real provider '{configured_provider}' and call '{session.provider_call_id}'."
                    )
                    
                evidence = EvidenceBuilder().build(
                    session=session,
                    events=provider_events,
                    recordings=[recording] if recording else [],
                    transcript=transcript_obj,
                    artifacts=[],
                    rag_context=context.scenario.rag_context,
                )
                normalized = ConversationNormalizer().normalize(
                    evidence,
                    scenario_id=context.scenario.scenario_id,
                    rag_config=context.provider_config.metadata.get("rag_config"),
                )
                artifacts = list(evidence.attachments)
                if configured_provider == "vapi":
                    logger.info("ConversationEvidence created: evidence_id=%s", evidence.evidence_id)
                    logger.info("NormalizedConversation messages: %d", len(normalized.messages))
                for artifact in artifacts:
                    _assert_real_provider_artifact(configured_provider, artifact)

            events.extend(
                [
                    CallingExecutionEvent(
                        event_type=CallingExecutionEventType.connected,
                        session_id=session.session_id,
                        run_id=session.run_id,
                    ),
                    CallingExecutionEvent(
                        event_type=CallingExecutionEventType.in_progress,
                        session_id=session.session_id,
                        run_id=session.run_id,
                    ),
                ]
            )
            if session.status != CallStatus.completed:
                events.append(
                    CallingExecutionEvent(
                        event_type=CallingExecutionEventType.failed,
                        session_id=session.session_id,
                        run_id=session.run_id,
                        metadata={"status": session.status.value},
                    )
                )
                return CallingExecutionResult(
                    status=CallingExecutionStatus.failed,
                    call_session=session,
                    conversation_evidence=evidence,
                    normalized_conversation=normalized,
                    artifacts=artifacts,
                    execution_events=events,
                    execution_metadata={
                        "scenario_id": context.scenario.scenario_id,
                        "provider": context.provider_config.provider_name,
                    },
                    provider_metadata=session.provider_metadata,
                    duration_seconds=_duration_seconds(started_at, utc_now_iso()),
                    error=f"Call session ended with status {session.status.value}.",
                )

            events.append(
                CallingExecutionEvent(
                    event_type=CallingExecutionEventType.completed,
                    session_id=session.session_id,
                    run_id=session.run_id,
                )
            )
            if context.provider_config.provider_name == "vapi":
                logger.info("=== VAPI EVALUATION COMPLETED ===")
            return CallingExecutionResult(
                status=CallingExecutionStatus.completed,
                call_session=session,
                conversation_evidence=evidence,
                normalized_conversation=normalized,
                artifacts=artifacts,
                execution_events=events,
                execution_metadata={
                    "scenario_id": context.scenario.scenario_id,
                    "provider": context.provider_config.provider_name,
                    "context_run_id": context.run_id,
                    "context_session_id": context.session_id,
                },
                provider_metadata=session.provider_metadata,
                duration_seconds=_duration_seconds(started_at, utc_now_iso()),
            )
        except TimeoutError as exc:
            if context.provider_config.provider_name == "vapi":
                logger.exception("Vapi evaluation timed out")
            events.append(
                CallingExecutionEvent(
                    event_type=CallingExecutionEventType.timed_out,
                    session_id=context.session_id,
                    run_id=context.run_id,
                    metadata={"error": str(exc)},
                )
            )
            return _failed_result(context, events, CallingExecutionStatus.timed_out, started_at, exc)
        except Exception as exc:
            if context.provider_config.provider_name == "vapi":
                logger.exception("Vapi evaluation failed")
            events.append(
                CallingExecutionEvent(
                    event_type=CallingExecutionEventType.failed,
                    session_id=context.session_id,
                    run_id=context.run_id,
                    metadata={"error": str(exc)},
                )
            )
            return _failed_result(context, events, CallingExecutionStatus.failed, started_at, exc)


def _failed_result(
    context: CallingExecutionContext,
    events: list[CallingExecutionEvent],
    status: CallingExecutionStatus,
    started_at: str,
    exc: Exception,
) -> CallingExecutionResult:
    return CallingExecutionResult(
        status=status,
        artifacts=list(context.artifacts),
        execution_events=events,
        execution_metadata={
            "scenario_id": context.scenario.scenario_id,
            "provider": context.provider_config.provider_name,
        },
        duration_seconds=_duration_seconds(started_at, utc_now_iso()),
        error=str(exc),
    )


def _select_transcript(
    *,
    provider,
    capabilities: ProviderCapabilities,
    session,
    transport_transcript: RawCallTranscript | None,
) -> RawCallTranscript | None:
    """Choose the best transcript source without provider-specific checks."""
    transport_turns = _transcript_turn_count(transport_transcript)
    if _prefers_provider_transcript(capabilities):
        provider_transcript = _fetch_provider_transcript(provider, session)
        provider_turns = _transcript_turn_count(provider_transcript)
        if _has_transcript_turns(provider_transcript):
            _log_transcript_selection(
                session=session,
                selected_source="provider",
                selected_turns=provider_turns,
                discarded_source="transport",
                discarded_turns=transport_turns,
                reason="provider preference",
            )
            return provider_transcript
        logger.info(
            "Provider transcript unavailable for call session %s; provider_turns=%d transport_turns=%d reason=fallback",
            session.session_id,
            provider_turns,
            transport_turns,
        )

    if _has_transcript_turns(transport_transcript):
        _log_transcript_selection(
            session=session,
            selected_source="transport",
            selected_turns=transport_turns,
            discarded_source="provider" if _prefers_provider_transcript(capabilities) else None,
            discarded_turns=provider_turns if _prefers_provider_transcript(capabilities) else None,
            reason="provider unavailable fallback"
            if _prefers_provider_transcript(capabilities)
            else "transport transcript available",
        )
        return transport_transcript

    provider_transcript = _fetch_provider_transcript(provider, session)
    provider_turns = _transcript_turn_count(provider_transcript)
    _log_transcript_selection(
        session=session,
        selected_source="provider" if _has_transcript_turns(provider_transcript) else "none",
        selected_turns=provider_turns,
        discarded_source="transport",
        discarded_turns=transport_turns,
        reason="transport unavailable; provider transcript checked",
    )
    return provider_transcript


def _prefers_provider_transcript(capabilities: ProviderCapabilities) -> bool:
    preferred_source = (capabilities.preferred_transcript_source or "").strip().lower()
    return preferred_source == "provider" or capabilities.supports_provider_transcript


def _fetch_provider_transcript(provider, session) -> RawCallTranscript | None:
    fetch_transcript = getattr(provider, "fetch_transcript", None)
    if not callable(fetch_transcript):
        return None
    try:
        return fetch_transcript(session)
    except Exception:
        logger.exception(
            "Provider transcript fetch failed for provider=%s call_id=%s",
            getattr(session, "provider_name", None),
            getattr(session, "provider_call_id", None),
        )
        return None


def _has_transcript_turns(transcript: RawCallTranscript | None) -> bool:
    return bool(transcript and transcript.turns)


def _transcript_turn_count(transcript: RawCallTranscript | None) -> int:
    return len(transcript.turns) if transcript and transcript.turns else 0


def _log_transcript_selection(
    *,
    session,
    selected_source: str,
    selected_turns: int,
    discarded_source: str | None,
    discarded_turns: int | None,
    reason: str,
) -> None:
    logger.info(
        "Transcript selected for call session %s: selected_source=%s selected_turns=%d discarded_source=%s discarded_turns=%s reason=%s",
        session.session_id,
        selected_source,
        selected_turns,
        discarded_source or "none",
        discarded_turns if discarded_turns is not None else "n/a",
        reason,
    )


def _assert_real_provider_session(configured_provider: str, session) -> None:
    if configured_provider == "mock":
        return
    runtime_name = (session.provider_name or "").strip().lower()
    call_id = (session.provider_call_id or "").strip().lower()
    if runtime_name == "mock" or call_id.startswith("mock-"):
        raise RuntimeError(
            f"Provider invariant violated: configured_provider '{configured_provider}' produced mock session data."
        )


def _assert_real_provider_artifact(configured_provider: str, artifact) -> None:
    if configured_provider == "mock":
        return
    provider_name = (artifact.provider_name or "").strip().lower()
    metadata = artifact.metadata or {}
    recording_id = (getattr(artifact, "recording_id", None) or "").strip().lower()
    provider_recording_id = (getattr(artifact, "provider_recording_id", None) or "").strip().lower()
    if (
        provider_name == "mock"
        or metadata.get("placeholder") is True
        or recording_id.startswith("mock-rec-")
        or provider_recording_id.startswith("mock-rec-")
        or artifact.artifact_type in {CallArtifactType.audio, CallArtifactType.transcript, CallArtifactType.events}
        and (artifact.path or "").startswith("artifacts/call/")
    ):
        raise RuntimeError(
            f"Provider invariant violated: configured_provider '{configured_provider}' produced mock artifact data."
        )


def _client_agent_phone_number(context: CallingExecutionContext, *, fallback: str) -> str:
    settings = context.provider_config.settings or {}
    candidate = (
        settings.get("agent_phone_number")
        or settings.get("phone_number")
        or settings.get("from_number")
        or fallback
    )
    if not candidate:
        raise RuntimeError("Inbound calling evaluation requires the client agent phone number.")
    return str(candidate)


def _resolve_voice_transport(context: CallingExecutionContext, *, mode: str):
    config = context.voice_transport_config or context.test_transport_config
    if not config or not config.transport_name:
        return UnconfiguredVoiceTransport(
            f"{mode.capitalize()} calling evaluation requires a configured EvalForge VoiceTransport. "
            "Configure a real PSTN/SIP transport such as Twilio or LiveKit SIP in the EvalForge runtime; mock transport is not allowed for real providers."
        )
    if config.transport_name == "twilio":
        return TwilioVoiceTransport(config)
    if config.transport_name == "vapi":
        return VapiVoiceTransport(config)
    raise VoiceTransportError(
        f"VoiceTransport '{config.transport_name or 'unknown'}' is configured but no production transport adapter is registered yet."
    )


def _provider_supports_direct_inbound(capabilities: ProviderCapabilities) -> bool:
    return capabilities.supports_direct_sessions and capabilities.supports_inbound_sessions


def _unsupported_inbound_message(provider_name: str, capabilities: ProviderCapabilities) -> str:
    supported = capabilities.supported_connection_methods()
    supported_text = ", ".join(supported) if supported else "none advertised"
    missing: list[str] = []
    if not capabilities.supports_direct_sessions or not capabilities.supports_inbound_sessions:
        missing.append("direct inbound session")
    if not capabilities.requires_external_transport:
        missing.append("external VoiceTransport requirement")
    missing_text = ", ".join(missing) if missing else "compatible inbound connection method"
    return (
        f"Provider '{provider_name}' cannot start an inbound calling evaluation with the current configuration. "
        f"Advertised connection methods: {supported_text}. Missing: {missing_text}."
    )


def _transport_supports_conversation(transport) -> bool:
    capabilities = getattr(transport, "capabilities", None)
    supports_audio = bool(
        getattr(capabilities, "supports_audio_send", False)
        and getattr(capabilities, "supports_audio_receive", False)
    )
    supports_text = hasattr(transport, "send_text") and hasattr(transport, "receive_text")
    return supports_audio or supports_text


def _voice_conversation_runner(context: CallingExecutionContext) -> VoiceConversationRunner:
    settings = context.provider_config.settings or {}
    stt_config = settings.get("stt") or {}
    tts_config = settings.get("tts") or {}
    try:
        from app.adapters.voice.local import FasterWhisperSTT, PiperTTS
    except ImportError as exc:
        raise RuntimeError("Voice conversation runner requires the existing voice STT/TTS providers.") from exc
    return VoiceConversationRunner(
        max_turns=context.scenario.max_turns,
        receive_timeout_seconds=float(settings.get("receive_timeout_seconds") or 30.0),
        stt_provider=FasterWhisperSTT(
            model_size=stt_config.get("model_size", "small"),
            device=stt_config.get("device", "cpu"),
            compute_type=stt_config.get("compute_type", "int8"),
            language=stt_config.get("language"),
        ),
        tts_provider=PiperTTS(
            voice=tts_config.get("voice", "en_US-lessac-medium"),
            model_path=tts_config.get("model_path"),
            piper_binary=tts_config.get("piper_binary", "piper"),
        ),
    )


def _duration_seconds(started_at: str, ended_at: str) -> float:
    start = datetime.fromisoformat(started_at)
    end = datetime.fromisoformat(ended_at)
    return max((end - start).total_seconds(), 0.0)
