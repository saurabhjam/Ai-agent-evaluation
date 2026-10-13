"""Artifact helpers for calling-agent evaluation evidence."""

from __future__ import annotations

from typing import Any, Optional

from app.calling.models import CallArtifact, CallArtifactType, CallRecording


EXPECTED_ARTIFACT_FILENAMES: dict[CallArtifactType, str] = {
    CallArtifactType.audio: "audio.wav",
    CallArtifactType.agent_audio: "agent.wav",
    CallArtifactType.customer_audio: "customer.wav",
    CallArtifactType.transcript: "transcript.json",
    CallArtifactType.events: "events.json",
    CallArtifactType.metrics: "metrics.json",
    CallArtifactType.backend: "backend.json",
    CallArtifactType.rag: "rag.json",
    CallArtifactType.deepeval: "deepeval.json",
    CallArtifactType.report: "report.html",
}

ARTIFACT_LOCATION_PREFIXES: dict[str, str] = {
    "root": "artifacts/",
    "call": "artifacts/call/",
    "audio": "artifacts/call/audio/",
    "transcript": "artifacts/call/transcript/",
    "events": "artifacts/call/events/",
    "metrics": "artifacts/call/metrics/",
    "backend": "artifacts/call/backend/",
    "rag": "artifacts/call/rag/",
    "logs": "artifacts/call/logs/",
}


def expected_artifact_filename(artifact_type: CallArtifactType) -> str:
    """Return the conventional filename for a calling artifact type."""
    return EXPECTED_ARTIFACT_FILENAMES[artifact_type]


def artifact_location_prefix(name: str) -> str:
    """Return the future artifact location prefix for a calling artifact group."""
    return ARTIFACT_LOCATION_PREFIXES[name]


def create_artifact(
    *,
    session_id: str,
    artifact_type: CallArtifactType,
    path: Optional[str] = None,
    remote_url: Optional[str] = None,
    content_type: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> CallArtifact:
    """Create artifact metadata without reading or writing files."""
    return CallArtifact(
        session_id=session_id,
        artifact_type=artifact_type,
        path=path,
        remote_url=remote_url,
        content_type=content_type,
        metadata=metadata or {},
    )


def create_recording(
    *,
    session_id: str,
    path: Optional[str] = None,
    remote_url: Optional[str] = None,
    recording_id: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    channels: int = 1,
    format: str = "wav",
    metadata: Optional[dict[str, Any]] = None,
) -> CallRecording:
    """Create call recording metadata without downloading audio."""
    return CallRecording(
        session_id=session_id,
        path=path,
        remote_url=remote_url,
        recording_id=recording_id,
        duration_seconds=duration_seconds,
        channels=channels,
        format=format,
        metadata=metadata or {},
    )
