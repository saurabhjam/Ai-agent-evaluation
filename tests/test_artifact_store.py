from __future__ import annotations

from app.calling.artifact_store import ArtifactStore
from app.calling.conversation_evidence import EvidenceArtifact


def test_artifact_store_stores_retrieves_and_enumerates():
    store = ArtifactStore(base_path="artifacts/call")
    artifact = EvidenceArtifact(
        session_id="session-1",
        name="transcript.json",
        artifact_type="transcript",
        path="artifacts/call/transcript/run-1.json",
    )

    stored = store.store(artifact)

    assert store.retrieve(stored.artifact_id) is artifact
    assert store.enumerate() == [artifact]
    assert store.enumerate(session_id="session-1") == [artifact]
    assert store.enumerate(session_id="other") == []


def test_artifact_store_resolves_local_paths_without_io():
    store = ArtifactStore(base_path="artifacts/call")

    assert store.resolve_path("audio", "run-1.wav") == "artifacts/call/audio/run-1.wav"
