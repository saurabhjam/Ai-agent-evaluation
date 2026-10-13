"""
Vendor-neutral response normalization for interactive agent output.

Phase 1 provides conservative parsing only. Runtime integration and
adapter-native metadata are intentionally deferred.
"""

from __future__ import annotations

import re
from typing import Any

from app.interactive.models import (
    InteractiveElement,
    InteractiveElementType,
    NormalizedAgentResponse,
)


_BULLET_OPTION_RE = re.compile(r"^\s*(?:[-*•]|\d+[\.)])\s+(.+?)\s*$")
_UPLOAD_RE = re.compile(r"\b(upload|attach|send).{0,40}\b(file|document|photo|image|pdf)\b", re.IGNORECASE)
_CONFIRM_RE = re.compile(r"\b(confirm|cancel|yes|no)\b", re.IGNORECASE)


class ResponseUnderstanding:
    """Normalize adapter metadata or plain transcript text into one shape."""

    def normalize(
        self,
        *,
        text: str = "",
        metadata: dict[str, Any] | None = None,
        raw: dict[str, Any] | None = None,
    ) -> NormalizedAgentResponse:
        metadata = metadata or {}
        raw_payload = raw or metadata

        interactive = self._from_metadata(metadata)
        if not interactive:
            interactive = TranscriptHeuristicParser().parse(text)

        return NormalizedAgentResponse(
            text=text or "",
            interactive=interactive,
            raw=raw_payload or {},
        )

    def _from_metadata(self, metadata: dict[str, Any]) -> list[InteractiveElement]:
        elements: list[InteractiveElement] = []
        candidates = metadata.get("interactive") or metadata.get("actions") or metadata.get("options") or []
        if not isinstance(candidates, list):
            return []

        for item in candidates:
            if isinstance(item, str):
                elements.append(
                    InteractiveElement(
                        type=InteractiveElementType.quick_reply,
                        label=item,
                        value=item,
                    )
                )
                continue

            if not isinstance(item, dict):
                continue

            label = item.get("label") or item.get("title") or item.get("text") or item.get("name")
            if not label:
                continue

            element_type = self._element_type(item.get("type"))
            elements.append(
                InteractiveElement(
                    type=element_type,
                    label=str(label),
                    value=str(item.get("value") or label),
                    group=item.get("group"),
                    required=bool(item.get("required", False)),
                    metadata={k: v for k, v in item.items() if k not in {"type", "label", "title", "text", "name", "value", "group", "required"}},
                )
            )
        return elements

    def _element_type(self, raw_type: Any) -> InteractiveElementType:
        if not raw_type:
            return InteractiveElementType.quick_reply
        normalized = str(raw_type).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "button": InteractiveElementType.button,
            "buttons": InteractiveElementType.button,
            "quickreply": InteractiveElementType.quick_reply,
            "quick_reply": InteractiveElementType.quick_reply,
            "suggestion": InteractiveElementType.suggestion_chip,
            "suggested_reply": InteractiveElementType.suggestion_chip,
            "chip": InteractiveElementType.suggestion_chip,
            "card": InteractiveElementType.card,
            "dropdown": InteractiveElementType.dropdown_option,
            "dropdown_option": InteractiveElementType.dropdown_option,
            "menu": InteractiveElementType.menu_item,
            "menu_item": InteractiveElementType.menu_item,
            "form": InteractiveElementType.form,
            "upload": InteractiveElementType.upload_request,
            "upload_request": InteractiveElementType.upload_request,
            "confirmation": InteractiveElementType.confirmation,
            "date": InteractiveElementType.date_picker,
            "date_picker": InteractiveElementType.date_picker,
            "time": InteractiveElementType.time_picker,
            "time_picker": InteractiveElementType.time_picker,
            "link": InteractiveElementType.link,
        }
        return aliases.get(normalized, InteractiveElementType.unknown)


class TranscriptHeuristicParser:
    """
    Conservative parser for plain text responses.

    It only extracts bullet/numbered options when at least two plausible
    options exist.
    """

    def parse(self, text: str) -> list[InteractiveElement]:
        if not text:
            return []

        options = self._parse_bullet_options(text)
        if len(options) >= 2:
            return options

        if _UPLOAD_RE.search(text):
            return [
                InteractiveElement(
                    type=InteractiveElementType.upload_request,
                    label="Upload file",
                    value="upload_file",
                )
            ]

        if self._looks_like_confirmation(text):
            return [
                InteractiveElement(type=InteractiveElementType.confirmation, label="Confirm", value="confirm"),
                InteractiveElement(type=InteractiveElementType.confirmation, label="Cancel", value="cancel"),
            ]

        return []

    def _parse_bullet_options(self, text: str) -> list[InteractiveElement]:
        elements: list[InteractiveElement] = []
        for line in text.splitlines():
            match = _BULLET_OPTION_RE.match(line)
            if not match:
                continue
            label = match.group(1).strip()
            if len(label) < 2:
                continue
            elements.append(
                InteractiveElement(
                    type=InteractiveElementType.quick_reply,
                    label=label,
                    value=label,
                )
            )
        return elements

    def _looks_like_confirmation(self, text: str) -> bool:
        lowered = text.lower()
        return "?" in text and bool(_CONFIRM_RE.search(lowered)) and ("confirm" in lowered or "cancel" in lowered)
