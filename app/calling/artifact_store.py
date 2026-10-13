"""Local artifact metadata store for calling conversation evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Iterable, Optional

from app.calling.conversation_evidence import EvidenceArtifact


@dataclass
class ArtifactStore:
    """
    In-memory local artifact abstraction.

    This stores metadata only. It does not write files, download recordings, or
    talk to cloud storage.
    """

    base_path: str = "artifacts/call"
    _artifacts: dict[str, EvidenceArtifact] = field(default_factory=dict)

    def store(self, artifact: EvidenceArtifact) -> EvidenceArtifact:
        """Store artifact metadata and return it."""
        self._artifacts[artifact.artifact_id] = artifact
        return artifact

    def retrieve(self, artifact_id: str) -> EvidenceArtifact:
        """Retrieve artifact metadata by id."""
        return self._artifacts[artifact_id]

    def enumerate(self, *, session_id: Optional[str] = None) -> list[EvidenceArtifact]:
        """List stored artifact metadata, optionally for a session."""
        artifacts: Iterable[EvidenceArtifact] = self._artifacts.values()
        if session_id is not None:
            artifacts = [artifact for artifact in artifacts if artifact.session_id == session_id]
        return list(artifacts)

    def resolve_path(self, *parts: str) -> str:
        """Resolve a local artifact path under the store base path."""
        path = PurePosixPath(self.base_path)
        for part in parts:
            path = path / part
        return str(path)
