"""Rule-based fallback interaction detection for plain-text chatbot replies.

This module intentionally uses deterministic keyword matching only. It
does not parse provider payloads, call models, or create a new interaction
pipeline; it only produces the same normalized component dictionaries already
consumed by ``app.interaction_dispatcher``.
"""

from __future__ import annotations

import re
from typing import Any


_MARKDOWN_RE = re.compile(r"[*_`>#\[\]()]")
_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")


UPLOAD_VERBS = {"upload", "attach", "share", "send", "provide", "include", "add", "browse", "choose", "select"}
CAPTURE_VERBS = {"take", "capture"}
INPUT_VERBS = {"enter", "verify", "provide", "input", "submit", "type", "choose", "select", "pick", "send", "share"}

IMAGE_WORDS = {"photo", "photos", "image", "images", "picture", "pictures", "screenshot", "screenshots"}
DOCUMENT_WORDS = {"document", "documents", "invoice", "invoices", "pdf", "pdfs", "receipt", "receipts", "file", "files"}
VIDEO_WORDS = {"video", "videos"}
OTP_WORDS = {"otp", "code", "passcode", "password"}
OTP_CONTEXT_WORDS = {"verification", "one", "time"}
DATE_WORDS = {"date"}
TIME_WORDS = {"time"}
LOCATION_WORDS = {"location"}
DATE_TIME_CONTEXT_WORDS = {"appointment", "preferred", "schedule", "booking"}


def detect_fallback_interactions(text: Any) -> list[dict[str, Any]]:
    """Return normalized dispatcher components inferred from plain text.

    The detector is conservative: it returns one component per supported
    interaction type in rule order and returns an empty list when no rule
    matches. Callers are responsible for invoking this only when no structured
    components already exist.
    """

    normalized, tokens = _normalize_text(text)
    if not normalized:
        return []

    components: list[dict[str, Any]] = []
    if _has_any(tokens, IMAGE_WORDS) and (_has_any(tokens, UPLOAD_VERBS) or _has_any(tokens, CAPTURE_VERBS)):
        components.append(_component("image_upload", _specific_label("image_upload", tokens) or "Upload image", text))
    if _has_any(tokens, VIDEO_WORDS) and _has_any(tokens, UPLOAD_VERBS):
        components.append(_component("video_upload", _specific_label("video_upload", tokens) or "Upload video", text))
    if _has_any(tokens, DOCUMENT_WORDS) and _has_any(tokens, UPLOAD_VERBS) and not (_has_any(tokens, IMAGE_WORDS) and "receipt" in tokens):
        components.append(_component("document_upload", _specific_label("document_upload", tokens) or "Upload document", text))
    if _has_any(tokens, OTP_WORDS) and (_has_any(tokens, INPUT_VERBS) or _has_any(tokens, OTP_CONTEXT_WORDS)):
        components.append(_component("otp", "OTP verification required", text))
    otp_detected = any(component["type"] == "otp" for component in components)
    if not otp_detected and _has_any(tokens, DATE_WORDS) and (_has_any(tokens, INPUT_VERBS) or _has_any(tokens, DATE_TIME_CONTEXT_WORDS)):
        components.append(_component("date", "Select date", text))
    if not otp_detected and _has_any(tokens, TIME_WORDS) and (_has_any(tokens, INPUT_VERBS) or _has_any(tokens, DATE_TIME_CONTEXT_WORDS)):
        components.append(_component("time", "Select time", text))
    if _has_any(tokens, LOCATION_WORDS) and _has_any(tokens, INPUT_VERBS):
        components.append(_component("location", "Share location", text))

    return components


def _normalize_text(text: Any) -> tuple[str, set[str]]:
    value = str(text or "").lower()
    value = _MARKDOWN_RE.sub(" ", value)
    value = _PUNCT_RE.sub(" ", value)
    normalized = _SPACE_RE.sub(" ", value).strip()
    return normalized, set(normalized.split()) if normalized else set()


def _component(component_type: str, label: str, text: Any) -> dict[str, Any]:
    return {
        "type": component_type,
        "label": label,
        "text": str(text or ""),
        "generated_by": "fallback",
    }


def _specific_label(component_type: str, tokens: set[str]) -> str:
    if component_type == "image_upload":
        if "damage" in tokens and _has_any(tokens, IMAGE_WORDS):
            return "Upload damage photo"
        if "receipt" in tokens and _has_any(tokens, IMAGE_WORDS):
            return "Upload receipt photo"
        if _has_any(tokens, {"screenshot", "screenshots"}):
            return "Upload screenshot"
    if component_type == "document_upload":
        if _has_any(tokens, {"invoice", "invoices"}):
            return "Upload invoice"
        if _has_any(tokens, {"receipt", "receipts"}):
            return "Upload receipt"
        if _has_any(tokens, {"pdf", "pdfs"}):
            return "Upload PDF"
        if _has_any(tokens, {"file", "files"}):
            return "Upload file"
    if component_type == "video_upload" and "damage" in tokens:
        return "Upload damage video"
    return ""


def _has_any(tokens: set[str], keywords: set[str]) -> bool:
    return bool(tokens & keywords)
