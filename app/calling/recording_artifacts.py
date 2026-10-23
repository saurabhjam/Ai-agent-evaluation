"""Provider-neutral persistence and HTTP serving helpers for call recordings."""

from __future__ import annotations

import mimetypes
from pathlib import Path
import re
import wave
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse


_ROOT = (Path(__file__).resolve().parents[2] / "artifacts").resolve()
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def persist_recordings(
    recordings: list[dict[str, Any]], evaluation_id: str
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Materialize provider-resolved recording references under one evaluation."""
    prepared: list[dict[str, Any]] = []
    evalforge_recording_available = False
    for index, original in enumerate(recordings):
        recording = dict(original)
        artifact_id = str(recording.get("artifact_id") or f"recording-{index + 1}")
        metadata = dict(recording.get("metadata") or {})
        source = str(metadata.get("source") or recording.get("provider_name") or "").lower()
        try:
            if evalforge_recording_available and source != "evalforge":
                recording.update({"path": None, "status": "fallback_not_needed"})
            else:
                path = _materialize(recording, evaluation_id, artifact_id)
                content_type = recording.get("content_type") or _content_type(path)
                duration = recording.get("duration_seconds") or _wav_duration(path)
                recording.update({
                    "path": str(path.relative_to(_ROOT.resolve())),
                    "content_type": content_type,
                    "duration_seconds": duration,
                    "status": "available",
                    "playback_url": f"/evaluations/{evaluation_id}/recordings/{artifact_id}/playback",
                    "download_url": f"/evaluations/{evaluation_id}/recordings/{artifact_id}/download",
                })
                if source == "evalforge":
                    evalforge_recording_available = True
        except Exception as exc:
            recording.update({
                "path": None,
                "status": "unavailable",
                "unavailable_reason": f"{type(exc).__name__}: {exc}",
            })
        # A resolved provider URL is server-side acquisition data, not a browser source.
        recording.pop("remote_url", None)
        metadata.pop("provider_json", None)
        metadata.pop("alternate_remote_urls", None)
        recording["metadata"] = metadata
        prepared.append(recording)

    available = [item for item in prepared if item.get("status") == "available"]
    status = "available" if available else "unavailable"
    audio = {"full": None, "agent": None, "customer": None, "metadata": {}}
    for index, item in enumerate(available):
        channel = _channel(item, index)
        audio[channel] = item["playback_url"]
        audio["metadata"][channel] = {
            "duration": item.get("duration_seconds"),
            "format": item.get("format"),
            "channels": item.get("channels"),
            "content_type": item.get("content_type"),
        }
    return prepared, status, audio


def recording_response(
    report: dict[str, Any], artifact_id: str, request: Request, *, download: bool
) -> Response:
    recording = next(
        (
            item for item in report.get("recording_metadata") or []
            if str(item.get("artifact_id")) == artifact_id
        ),
        None,
    )
    if not recording or recording.get("status") != "available" or not recording.get("path"):
        raise HTTPException(status_code=404, detail="Recording is unavailable")
    path = _resolve_artifact_path(str(recording["path"]), str(report.get("evaluation_id") or ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Recording file is unavailable")
    media_type = str(recording.get("content_type") or _content_type(path))
    filename = f"{report.get('evaluation_id', 'evaluation')}-{artifact_id}{path.suffix}"
    if download:
        return FileResponse(path, media_type=media_type, filename=filename)
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})
    start, end = _parse_range(range_header, path.stat().st_size)
    length = end - start + 1
    return StreamingResponse(
        _read_range(path, start, length),
        status_code=206,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Range": f"bytes {start}-{end}/{path.stat().st_size}",
        },
    )


def _materialize(recording: dict[str, Any], evaluation_id: str, artifact_id: str) -> Path:
    if not _ID.fullmatch(artifact_id):
        raise ValueError("Invalid recording artifact ID")
    target_dir = _evaluation_dir(evaluation_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    existing = recording.get("path")
    if existing:
        source = Path(str(existing)).resolve()
        if source.is_file():
            suffix = source.suffix or _suffix(recording)
            target = target_dir / f"{artifact_id}{suffix}"
            if source != target:
                target.write_bytes(source.read_bytes())
            return target
    urls = [recording.get("remote_url"), *(recording.get("metadata") or {}).get("alternate_remote_urls", [])]
    last_error: Exception | None = None
    for remote_url in dict.fromkeys(str(value) for value in urls if value):
        parsed = urlparse(remote_url)
        if parsed.scheme != "https" or not parsed.netloc:
            last_error = ValueError("Recording reference is not a valid HTTPS URL")
            continue
        target = target_dir / f"{artifact_id}{_suffix(recording, parsed.path)}"
        response = requests.get(remote_url, stream=True, timeout=(5, 30))
        try:
            response.raise_for_status()
            content_type = str(response.headers.get("content-type") or "").split(";", 1)[0].lower()
            if content_type in {"text/html", "application/json", "text/plain"}:
                raise ValueError(f"Provider recording returned {content_type}, not audio")
            with target.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        handle.write(chunk)
            if not target.is_file() or target.stat().st_size == 0:
                raise ValueError("Provider recording returned zero bytes")
            return target
        except Exception as exc:
            last_error = exc
            if target.exists():
                target.unlink()
        finally:
            response.close()
    raise last_error or ValueError("Recording reference is not a valid HTTPS URL")


def _evaluation_dir(evaluation_id: str) -> Path:
    if not _ID.fullmatch(evaluation_id):
        raise ValueError("Invalid evaluation ID")
    root = _ROOT.resolve()
    target = (root / evaluation_id).resolve()
    if target.parent != root:
        raise ValueError("Invalid evaluation artifact directory")
    return target


def _resolve_artifact_path(relative_path: str, evaluation_id: str) -> Path:
    root = _evaluation_dir(evaluation_id)
    candidate = (_ROOT.resolve() / relative_path).resolve()
    if root not in candidate.parents:
        raise HTTPException(status_code=404, detail="Invalid recording path")
    return candidate


def _parse_range(value: str, size: int) -> tuple[int, int]:
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match or size <= 0:
        raise HTTPException(status_code=416, detail="Invalid byte range", headers={"Content-Range": f"bytes */{size}"})
    first, last = match.groups()
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    elif last:
        length = min(int(last), size)
        start, end = size - length, size - 1
    else:
        raise HTTPException(status_code=416, detail="Invalid byte range", headers={"Content-Range": f"bytes */{size}"})
    if start < 0 or start >= size or end < start:
        raise HTTPException(status_code=416, detail="Invalid byte range", headers={"Content-Range": f"bytes */{size}"})
    return start, end


def _read_range(path: Path, start: int, length: int):
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining:
            chunk = handle.read(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _wav_duration(path: Path) -> float | None:
    if path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes() / float(audio.getframerate())
    except (wave.Error, OSError, ZeroDivisionError):
        return None


def _content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _suffix(recording: dict[str, Any], source_path: str = "") -> str:
    suffix = Path(source_path).suffix.lower()
    if suffix in {".wav", ".mp3", ".m4a", ".ogg", ".webm"}:
        return suffix
    value = str(recording.get("format") or "wav").lower().lstrip(".")
    return f".{value}" if value in {"wav", "mp3", "m4a", "ogg", "webm"} else ".bin"


def _channel(recording: dict[str, Any], index: int) -> str:
    metadata = recording.get("metadata") or {}
    source = " ".join(
        str(value or "")
        for value in (
            *(recording.get(key) for key in ("name", "channel", "type", "artifact_type")),
            metadata.get("channel"),
            metadata.get("source"),
        )
    ).lower()
    if "assistant" in source or "agent" in source:
        return "agent"
    if any(value in source for value in ("customer", "caller", "user")):
        return "customer"
    return "full" if index == 0 else f"full_{index + 1}"
