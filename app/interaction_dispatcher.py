"""
Production interaction dispatcher for chatbot evaluations.

This module is intentionally small: it inspects normalized conversation
components and delegates to the existing ChatAdapter capabilities. It does not
parse provider-specific payloads or create a second execution pipeline.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
import shutil
from typing import Any
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.chat.base import CapabilityNotSupported, ChatAdapter
from app.fallback_interactions import detect_fallback_interactions
from app.interaction_protocol import interaction_manager
from app.log_stream import current_eval_id
from app.schemas import TestScenario

logger = logging.getLogger(__name__)


def dispatch_interaction(
    *,
    adapter: Any,
    scenario: TestScenario,
    transcript: list[Any],
    allow_selectable: bool = True,
    selected_component: dict[str, Any] | None = None,
) -> bool:
    """Handle the latest normalized UI component if the adapter supports it."""
    latest_agent = _latest_agent_message(transcript)
    if latest_agent is None:
        return False

    components = [selected_component] if selected_component is not None else _message_components(latest_agent)
    if not components and not _message_has_structured_components(latest_agent):
        components = detect_fallback_interactions(_message_attr(latest_agent, "content", ""))
    if not components:
        return False

    if not allow_selectable and selected_component is None:
        components = [
            component
            for component in components
            if _component_type(component) not in {"button", "quick_reply", "option"}
        ]
        if not components:
            return False

    ordered_components = components if selected_component is not None else _rank_selectable_components(components, scenario, latest_agent)
    for component in ordered_components:
        if not isinstance(component, dict):
            continue

        try:
            if _dispatch_component(
                adapter=adapter,
                component=component,
                scenario=scenario,
                latest_agent=latest_agent,
            ):
                return True
        except CapabilityNotSupported:
            logger.info("Adapter does not support interaction component type=%s", component.get("type"))
            continue

    return False


def _dispatch_component(
    *,
    adapter: Any,
    component: dict[str, Any],
    scenario: TestScenario,
    latest_agent: Any,
) -> bool:
    component_type = _component_type(component)

    if component_type in {"button", "quick_reply", "option"}:
        if not _adapter_overrides(adapter, "click_button"):
            return False
        label = _first_text(component, "message", "value", "payload", "text", "label", "title", "id")
        selector = _first_text(component, "selector")
        if not label and not selector:
            return False
        _call_with_evidence(
            adapter=adapter,
            interaction_type="button_click",
            component=component,
            latest_agent=latest_agent,
            selected_value=label or selector,
            action=lambda: adapter.click_button(
                label or None,
                metadata={"selector": selector or None, "component": component},
            ),
        )
        return True

    if component_type == "dropdown":
        field, value = _field_and_value(component, scenario)
        if not field or value is None or not _adapter_overrides(adapter, "select_dropdown"):
            return False
        _call_with_evidence(
            adapter=adapter,
            interaction_type="dropdown_selection",
            component=component,
            latest_agent=latest_agent,
            selected_value=str(value),
            action=lambda: adapter.select_dropdown(field=field, value=str(value), metadata=_metadata(component)),
        )
        return True

    if component_type == "radio":
        field, value = _field_and_value(component, scenario)
        if not field or value is None or not _adapter_overrides(adapter, "select_radio"):
            return False
        _call_with_evidence(
            adapter=adapter,
            interaction_type="radio_selection",
            component=component,
            latest_agent=latest_agent,
            selected_value=str(value),
            action=lambda: adapter.select_radio(field=field, value=str(value), metadata=_metadata(component)),
        )
        return True

    if component_type == "checkbox":
        field = _field_name(component)
        if not field or not _adapter_overrides(adapter, "select_checkbox"):
            return False
        value = _bool_value(component)
        _call_with_evidence(
            adapter=adapter,
            interaction_type="checkbox_selection",
            component=component,
            latest_agent=latest_agent,
            selected_value=str(value).lower(),
            action=lambda: adapter.select_checkbox(field=field, value=value, metadata=_metadata(component)),
        )
        return True

    if component_type in {"multi_select", "multiselect"}:
        field = _field_name(component)
        values = _values(component, scenario)
        if not field or not values or not _adapter_overrides(adapter, "select_multi_select"):
            return False
        selected_values = [str(value) for value in values]
        _call_with_evidence(
            adapter=adapter,
            interaction_type="multi_select",
            component=component,
            latest_agent=latest_agent,
            selected_value=selected_values,
            action=lambda: adapter.select_multi_select(
                field=field,
                values=selected_values,
                metadata=_metadata(component),
            ),
        )
        return True

    if component_type in {"otp", "otp_input"}:
        field = _field_name(component)
        value = _first_text(component, "value", "code", "otp")
        response: dict[str, Any] | None = None
        if not value:
            response = _request_frontend_interaction(
                interaction_type="otp",
                prompt=_first_text(component, "label", "text", "title", "field", "name") or "OTP verification required",
                component=component,
            )
            if not response:
                return False
            if response.get("status") == "TIMED_OUT" or response.get("cancelled"):
                _attach_interaction_evidence_to_message(
                    message=latest_agent,
                    adapter=adapter,
                    interaction_type="otp",
                    component=component,
                    latest_agent=latest_agent,
                    selected_value="******",
                    success=False,
                    error=response.get("reason") or response.get("error"),
                    extra_evidence=_timing_evidence(response),
                )
                return False
            component = {**component, **_component_from_interaction_response(response)}
            value = _first_text(component, "value", "code", "otp")
        if not field or not value or not _adapter_overrides(adapter, "enter_otp"):
            return False
        _call_with_evidence(
            adapter=adapter,
            interaction_type="otp",
            component=component,
            latest_agent=latest_agent,
            selected_value="******",
            extra_evidence={**_timing_evidence(response or {}), "action": "OTP entered"},
            action=lambda: adapter.enter_otp(str(value), field=field, metadata=_metadata(component)),
        )
        return True

    if component_type in {"document_upload", "document", "file_upload", "upload_file", "upload", "video_upload", "video"}:
        file_value = _first_present(component, "file_object", "file", "path", "value")
        response = None
        
        normalized_type = "file_upload"
        if component_type in {"document_upload", "document"}:
            normalized_type = "document_upload"
        elif component_type in {"video_upload", "video"}:
            normalized_type = "video_upload"
            
        if file_value is None:
            prompt_text = _first_text(component, "label", "text", "title", "field", "name")
            if not prompt_text:
                if normalized_type == "document_upload":
                    prompt_text = "Select the requested document."
                elif normalized_type == "video_upload":
                    prompt_text = "Select the requested video."
                else:
                    prompt_text = "File required"
            
            response = _request_frontend_interaction(
                interaction_type=normalized_type,
                prompt=prompt_text,
                component=component,
            )
            if not response:
                return False
            if response.get("status") == "TIMED_OUT" or response.get("cancelled"):
                _attach_interaction_evidence_to_message(
                    message=latest_agent,
                    adapter=adapter,
                    interaction_type=normalized_type,
                    component=component,
                    latest_agent=latest_agent,
                    selected_value=None,
                    success=False,
                    artifact_path=None,
                    error=response.get("reason") or response.get("error"),
                    extra_evidence=_timing_evidence(response),
                )
                return False
            component = {**component, **_component_from_interaction_response(response)}
            file_value = _first_present(component, "file_object", "file", "path", "value")
            
        if file_value is None or not _adapter_overrides(adapter, "upload_file"):
            return False
            
        filename = _upload_filename(file_value)
        evidence_fields = {
            "action": f"Uploaded {normalized_type.split('_')[0]}",
            "source": component.get("source", "device"),
            "filename": filename,
        }
        evidence_fields = {**_timing_evidence(response or {}), **evidence_fields}

        def _upload_file_action() -> Any:
            result = adapter.upload_file(file_value, field=_optional_field_name(component), metadata=_metadata(component))
            evidence_fields.update(_persist_upload_artifact(file_value, filename=filename))
            return result
        
        _call_with_evidence(
            adapter=adapter,
            interaction_type=normalized_type,
            component=component,
            latest_agent=latest_agent,
            selected_value=filename,
            extra_evidence=evidence_fields,
            action=_upload_file_action,
        )
        return True

    if component_type in {"image_upload", "upload_image"}:
        response = _request_frontend_interaction(
            interaction_type="image_upload",
            prompt=_first_text(component, "label", "text", "title", "field", "name") or "Image required",
            component=component,
        )
        if not response:
            return False
        if response.get("status") == "TIMED_OUT" or response.get("cancelled"):
            _attach_interaction_evidence_to_message(
                message=latest_agent,
                adapter=adapter,
                interaction_type="image_upload",
                component=component,
                latest_agent=latest_agent,
                selected_value=None,
                success=False,
                artifact_path=None,
                error=response.get("reason") or response.get("error"),
                extra_evidence=_timing_evidence(response),
            )
            return False
        component = {**component, **_component_from_interaction_response(response)}
        image_value = _image_upload_value(component)
        if image_value is None or not _adapter_overrides(adapter, "upload_image"):
            return False
        image_mode = _image_upload_mode(component)
        filename = _upload_filename(image_value)
        interaction_type = "camera_capture" if image_mode == "camera" else "image_upload"
        evidence_fields = _image_evidence_fields(
            mode=image_mode,
            filename=filename,
            component=component,
        )
        evidence_fields = {**_timing_evidence(response or {}), **evidence_fields}

        def _upload_image_action() -> Any:
            result = adapter.upload_image(image_value, field=_optional_field_name(component), metadata=_metadata(component))
            evidence_fields.update(_persist_upload_artifact(image_value, filename=filename))
            return result

        _call_with_evidence(
            adapter=adapter,
            interaction_type=interaction_type,
            component=component,
            latest_agent=latest_agent,
            selected_value=filename,
            extra_evidence=evidence_fields,
            action=_upload_image_action,
        )
        return True

    if component_type in {"date", "date_picker"}:
        field, value = _field_and_value(component, scenario)
        if not field or value is None or not _adapter_overrides(adapter, "pick_date"):
            return False
        _call_with_evidence(
            adapter=adapter,
            interaction_type="date_picker",
            component=component,
            latest_agent=latest_agent,
            selected_value=str(value),
            action=lambda: adapter.pick_date(field=field, value=str(value), metadata=_metadata(component)),
        )
        return True

    if component_type in {"time", "time_picker"}:
        field, value = _field_and_value(component, scenario)
        if not field or value is None or not _adapter_overrides(adapter, "pick_time"):
            return False
        _call_with_evidence(
            adapter=adapter,
            interaction_type="time_picker",
            component=component,
            latest_agent=latest_agent,
            selected_value=str(value),
            action=lambda: adapter.pick_time(field=field, value=str(value), metadata=_metadata(component)),
        )
        return True

    if component_type in {"search", "search_box"}:
        field = _optional_field_name(component)
        query = _first_text(component, "query", "value", "text")
        if not query or not _adapter_overrides(adapter, "search"):
            return False
        _call_with_evidence(
            adapter=adapter,
            interaction_type="search",
            component=component,
            latest_agent=latest_agent,
            selected_value=str(query),
            action=lambda: adapter.search(str(query), field=field, metadata=_metadata(component)),
        )
        return True

    if component_type == "form":
        return _dispatch_form(adapter=adapter, component=component, scenario=scenario, latest_agent=latest_agent)

    return False


def _dispatch_form(*, adapter: Any, component: dict[str, Any], scenario: TestScenario, latest_agent: Any) -> bool:
    fields = _form_fields(component)
    if not fields:
        return False
    response = _request_frontend_interaction(
        interaction_type="form",
        prompt=_first_text(component, "label", "title", "text", "name") or "Form required",
        component=component,
    )
    if response:
        if response.get("status") == "TIMED_OUT" or response.get("cancelled"):
            _attach_interaction_evidence_to_message(
                message=latest_agent,
                adapter=adapter,
                interaction_type="form_fill",
                component=component,
                latest_agent=latest_agent,
                selected_value=None,
                success=False,
                error=response.get("reason") or response.get("error"),
                extra_evidence=_timing_evidence(response),
            )
            return False
        fields = _merge_form_response_fields(fields, response)

    handled = False
    start_transcript = _adapter_transcript(adapter) or []
    start_index = len(start_transcript)
    for field_component in fields:
        if _dispatch_component(
            adapter=adapter,
            component=field_component,
            scenario=scenario,
            latest_agent=latest_agent,
        ):
            handled = True
            continue

        field_type = _component_type(field_component)
        value = _first_text(field_component, "value", "text")
        field = _field_name(field_component)
        if field_type in {"text", "textarea", "email", "phone", "number", "password", "url"} and value:
            _call_with_evidence(
                adapter=adapter,
                interaction_type="form_field_entry",
                component=field_component,
                latest_agent=latest_agent,
                selected_value=str(value),
                action=lambda: adapter.send_message(f"Form\n{field or 'Field'} = {value}"),
            )
            handled = True

    if handled:
        transcript = _adapter_transcript(adapter) or []
        target = _first_new_user_message(transcript, start_index) or (transcript[-1] if transcript else latest_agent)
        required_count = sum(1 for field in fields if _field_required(field))
        completed_count = sum(1 for field in fields if _field_completed(field))
        optional_count = max(len(fields) - required_count, 0)
        timing = _timing_evidence(response or {})
        if not timing:
            now = datetime.now(timezone.utc).isoformat()
            timing = {
                "requested_at": now,
                "responded_at": now,
                "duration_ms": 0,
                "status": "SUCCESS",
            }
        else:
            timing["status"] = "SUCCESS"
        timing.update(
            {
                "action": f"Completed {_first_text(component, 'label', 'title', 'name') or 'requested'} form",
                "fields_completed": completed_count,
                "required_fields": required_count,
                "optional_fields": optional_count,
            }
        )
        _attach_interaction_evidence_to_message(
            message=target,
            adapter=adapter,
            interaction_type="form_fill",
            component=component,
            latest_agent=latest_agent,
            selected_value={_field_name(field): _safe_field_value(field) for field in fields if _field_name(field)},
            success=True,
            extra_evidence=timing,
        )

    return handled


def _latest_agent_message(transcript: list[Any]) -> Any | None:
    for message in reversed(transcript):
        if _message_attr(message, "role") == "agent":
            return message
    return None


def _message_attr(message: Any, name: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(name, default)
    return getattr(message, name, default)


def _message_components(message: Any) -> list[dict[str, Any]]:
    metadata = _message_attr(message, "metadata") or {}
    if not isinstance(metadata, dict):
        return []
    components = metadata.get("components") or metadata.get("rich_components") or []
    if not isinstance(components, list):
        return []
    return [component for component in components if isinstance(component, dict)]


def _message_has_structured_components(message: Any) -> bool:
    metadata = _message_attr(message, "metadata") or {}
    if not isinstance(metadata, dict):
        return False
    for key in ("components", "rich_components"):
        value = metadata.get(key)
        if isinstance(value, list) and any(isinstance(item, dict) for item in value):
            return True
    return False


def _component_type(component: dict[str, Any]) -> str:
    component_type = str(component.get("type") or "").strip().lower().replace("-", "_")
    subtype = str(component.get("subtype") or "").strip().lower().replace("-", "_")
    if subtype == "quick_reply":
        return "quick_reply"
    aliases = {
        "quickreply": "quick_reply",
        "select": "dropdown",
        "textarea": "textarea",
        "text_area": "textarea",
        "email_input": "email",
        "phone_input": "phone",
        "number_input": "number",
        "password_input": "password",
        "dropdown_select": "dropdown",
        "checkbox_group": "checkbox",
        "radio_group": "radio",
        "multi_select": "multi_select",
        "multiselect": "multi_select",
        "otp_input": "otp",
        "file": "file_upload",
        "attachment": "file_upload",
        "image": "image_upload",
        "date_picker": "date",
        "time_picker": "time",
        "datetime": "datetime",
        "datetime_picker": "datetime",
        "datetime_local": "datetime",
        "search_box": "search",
    }
    return aliases.get(component_type, component_type)


def _rank_selectable_components(
    components: list[dict[str, Any]],
    scenario: TestScenario,
    latest_agent: Any,
) -> list[dict[str, Any]]:
    selectable = {"button", "quick_reply", "option"}
    if not any(_component_type(component) in selectable for component in components):
        return components

    # Semantic selection is owned by app.simulator. This legacy/default path
    # preserves provider order for callers that have not supplied a decision.
    return components


def _tokens(text: str) -> set[str]:
    import re

    stop_words = {
        "a", "an", "and", "are", "as", "at", "be", "for", "from", "how",
        "i", "in", "is", "it", "me", "my", "of", "on", "or", "please",
        "the", "this", "to", "what", "which", "with", "you", "your",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in stop_words
    }


def _adapter_overrides(adapter: Any, method_name: str) -> bool:
    method = getattr(adapter, method_name, None)
    if not callable(method):
        return False

    adapter_method = getattr(type(adapter), method_name, None)
    base_method = getattr(ChatAdapter, method_name, None)
    if adapter_method is None or adapter_method is base_method:
        return False

    return True


def _call_with_evidence(
    *,
    adapter: Any,
    interaction_type: str,
    component: dict[str, Any],
    latest_agent: Any,
    selected_value: Any,
    action: Any,
    artifact_path: str | None = None,
    extra_evidence: dict[str, Any] | None = None,
) -> Any:
    transcript = _adapter_transcript(adapter)
    start_index = len(transcript) if isinstance(transcript, list) else 0
    requested_at = datetime.now(timezone.utc)
    result = action()
    responded_at = datetime.now(timezone.utc)
    timing = {
        "requested_at": requested_at.isoformat(),
        "responded_at": responded_at.isoformat(),
        "duration_ms": int((responded_at - requested_at).total_seconds() * 1000),
        "status": "SUCCESS",
    }
    if extra_evidence:
        timing.update(extra_evidence)
    _attach_interaction_evidence(
        adapter=adapter,
        interaction_type=interaction_type,
        component=component,
        latest_agent=latest_agent,
        selected_value=selected_value,
        success=True,
        start_index=start_index,
        artifact_path=artifact_path,
        extra_evidence=timing,
    )
    return result


def _attach_interaction_evidence(
    *,
    adapter: Any,
    interaction_type: str,
    component: dict[str, Any],
    latest_agent: Any,
    selected_value: Any,
    success: bool,
    start_index: int,
    artifact_path: str | None = None,
    error: str | None = None,
    extra_evidence: dict[str, Any] | None = None,
) -> None:
    transcript = _adapter_transcript(adapter)
    if not isinstance(transcript, list):
        return

    target = _first_new_user_message(transcript, start_index)
    if target is None:
        return

    _attach_interaction_evidence_to_message(
        message=target,
        adapter=adapter,
        interaction_type=interaction_type,
        component=component,
        latest_agent=latest_agent,
        selected_value=selected_value,
        success=success,
        artifact_path=artifact_path,
        error=error,
        extra_evidence=extra_evidence,
    )


def _attach_interaction_evidence_to_message(
    *,
    message: Any,
    adapter: Any,
    interaction_type: str,
    component: dict[str, Any],
    latest_agent: Any,
    selected_value: Any,
    success: bool,
    artifact_path: str | None = None,
    error: str | None = None,
    extra_evidence: dict[str, Any] | None = None,
) -> None:
    target = message

    metadata = _message_attr(target, "metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    evidence = {
        "interaction_type": interaction_type,
        "requested_by_agent": _requested_by_agent(component, latest_agent),
        "selected_value": selected_value,
        "success": success,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "adapter": type(adapter).__name__,
        "provider": _provider_name(adapter),
        "turn_number": _message_attr(target, "turn_index", 0),
    }
    if artifact_path:
        evidence["artifact_path"] = artifact_path
    if error:
        evidence["error"] = error
    if extra_evidence:
        evidence.update(extra_evidence)

    metadata["interaction_evidence"] = evidence
    _set_message_metadata(target, metadata)


def _adapter_transcript(adapter: Any) -> list[Any] | None:
    get_transcript = getattr(adapter, "get_transcript", None)
    if callable(get_transcript):
        try:
            transcript = get_transcript()
            if isinstance(transcript, list):
                return transcript
        except Exception:  # noqa: BLE001
            return None
    transcript = getattr(adapter, "transcript", None)
    return transcript if isinstance(transcript, list) else None


def _first_new_user_message(transcript: list[Any], start_index: int) -> Any | None:
    new_messages = transcript[start_index:]
    for message in new_messages:
        if _message_attr(message, "role") == "simulated_user":
            return message
    return new_messages[0] if new_messages else None


def _set_message_metadata(message: Any, metadata: dict[str, Any]) -> None:
    if isinstance(message, dict):
        message["metadata"] = metadata
        return
    setattr(message, "metadata", metadata)


def _requested_by_agent(component: dict[str, Any], latest_agent: Any) -> str:
    return (
        _first_text(component, "label", "text", "title", "field", "name")
        or str(_message_attr(latest_agent, "content", "") or "")
    )


def _provider_name(adapter: Any) -> str:
    config = getattr(adapter, "config", None)
    if isinstance(config, dict):
        provider = config.get("provider") or config.get("provider_name") or config.get("adapter")
        if provider:
            return str(provider)
    provider = getattr(adapter, "provider", None) or getattr(adapter, "provider_name", None)
    return str(provider) if provider else type(adapter).__name__


def _first_text(component: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = component.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _image_upload_mode(component: dict[str, Any]) -> str:
    raw_mode = (
        component.get("source")
        or component.get("mode")
        or component.get("image_source")
        or component.get("upload_mode")
        or "test_image"
    )
    mode = str(raw_mode).strip().lower().replace("-", "_")
    aliases = {
        "test": "test_image",
        "predefined": "test_image",
        "predefined_test_image": "test_image",
        "fixture": "test_image",
        "device_file": "device",
        "from_device": "device",
        "upload_from_device": "device",
        "camera_capture": "camera",
        "live_camera": "camera",
        "capture_live_photo": "camera",
    }
    return aliases.get(mode, mode)


def _request_frontend_interaction(
    *,
    interaction_type: str,
    prompt: str,
    component: dict[str, Any],
) -> dict[str, Any] | None:
    evaluation_id = current_eval_id.get()
    if not evaluation_id:
        return None
    return interaction_manager.request_interaction(
        evaluation_id=evaluation_id,
        interaction_type=interaction_type,
        prompt=prompt,
        component=component,
    )


def _component_from_interaction_response(response: dict[str, Any]) -> dict[str, Any]:
    source = response.get("source") or response.get("mode")
    file_payload = response.get("file")
    merged: dict[str, Any] = {}
    if source:
        merged["source"] = source
    if isinstance(file_payload, dict):
        merged["file"] = {
            "name": file_payload.get("name") or file_payload.get("filename") or "image",
            "filename": file_payload.get("filename") or file_payload.get("name") or "image",
            "mime_type": file_payload.get("mime_type") or file_payload.get("type") or file_payload.get("mimeType") or "image/jpeg",
            "content": file_payload.get("content") or file_payload.get("data") or "",
        }
    elif file_payload:
        merged["file"] = file_payload
    otp_value = response.get("otp") or response.get("value") or response.get("code")
    if otp_value not in (None, ""):
        merged["value"] = str(otp_value)
    if response.get("camera_used") is not None:
        merged["camera_used"] = bool(response.get("camera_used"))
    if response.get("retakes") is not None:
        try:
            merged["retakes"] = int(response.get("retakes") or 0)
        except (TypeError, ValueError):
            merged["retakes"] = 0
    return merged


def _merge_form_response_fields(fields: list[dict[str, Any]], response: dict[str, Any]) -> list[dict[str, Any]]:
    values = response.get("fields")
    if not isinstance(values, dict):
        return fields
    merged = []
    for field in fields:
        field_name = _field_name(field)
        key = str(field.get("name") or field.get("id") or field_name)
        next_field = dict(field)
        if key in values:
            _apply_form_value(next_field, values[key])
        elif field_name in values:
            _apply_form_value(next_field, values[field_name])
        merged.append(next_field)
    return merged


def _apply_form_value(field: dict[str, Any], value: Any) -> None:
    field_type = _component_type(field)
    if field_type in {"file_upload", "upload_file", "upload", "document_upload", "document", "video_upload", "video"}:
        field["file"] = value
        return
    if field_type in {"image_upload", "upload_image"}:
        field["file"] = value
        field.setdefault("source", "device")
        return
    if field_type in {"multi_select", "multiselect"}:
        field["values"] = value if isinstance(value, list) else [value]
        return
    if field_type == "search":
        field["query"] = value
        return
    field["value"] = value


def _field_required(field: dict[str, Any]) -> bool:
    return bool(field.get("required", False))


def _field_completed(field: dict[str, Any]) -> bool:
    field_type = _component_type(field)
    if field_type in {"file_upload", "upload_file", "upload", "image_upload", "upload_image", "document_upload", "document", "video_upload", "video"}:
        return _first_present(field, "file", "image", "path", "value") not in (None, "")
    if field_type in {"multi_select", "multiselect"}:
        return bool(_first_present(field, "values", "value"))
    return _first_present(field, "value", "selected", "default", "text", "query") not in (None, "")


def _safe_field_value(field: dict[str, Any]) -> Any:
    field_type = _component_type(field)
    if field_type in {"otp", "otp_input", "password"}:
        return "******"
    if field_type in {"file_upload", "upload_file", "upload", "image_upload", "upload_image", "document_upload", "document", "video_upload", "video"}:
        value = _first_present(field, "file", "image", "path", "value")
        return _upload_filename(value) if value is not None else None
    if field_type in {"multi_select", "multiselect"}:
        return _first_present(field, "values", "value")
    return _first_present(field, "value", "selected", "default", "text", "query")


def _timing_evidence(response: dict[str, Any]) -> dict[str, Any]:
    evidence = {}
    for key in ("requested_at", "responded_at", "duration_ms", "status", "reason"):
        if key in response:
            evidence[key] = response[key]
    return evidence


def _image_upload_value(component: dict[str, Any]) -> Any:
    mode = _image_upload_mode(component)
    if mode == "device":
        return _first_present(component, "file_object", "file", "image", "blob", "value")
    if mode == "camera":
        return _first_present(component, "file_object", "file", "image", "blob", "value")
    return _first_present(component, "image", "file", "path", "value")


def _first_present(component: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = component.get(key)
        if value not in (None, ""):
            return value
    return None


def _upload_filename(value: Any) -> str:
    if isinstance(value, dict):
        name = value.get("filename") or value.get("name") or value.get("file_name")
        if name:
            return str(name)
    name = getattr(value, "name", None) or getattr(value, "filename", None)
    if name:
        return str(name)
    if isinstance(value, str):
        import os

        return os.path.basename(value)
    return "image"


def _persist_upload_artifact(value: Any, *, filename: str) -> dict[str, Any]:
    evaluation_id = current_eval_id.get()
    if not evaluation_id:
        return {"artifact_path": value} if isinstance(value, str) else {}
    safe_eval_id = _safe_path_segment(evaluation_id)
    safe_filename = _safe_filename(filename)
    artifact_dir = Path("artifacts") / safe_eval_id / "uploaded"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = _unique_artifact_path(artifact_dir / safe_filename)
    metadata: dict[str, Any] = {
        "artifact_path": artifact_path.as_posix(),
        "mime_type": _upload_mime_type(value, safe_filename),
    }
    if isinstance(value, str) and os.path.exists(value):
        source_path = Path(value)
        if source_path.resolve() != artifact_path.resolve():
            shutil.copyfile(source_path, artifact_path)
    else:
        data = _upload_bytes(value)
        if not data:
            return metadata
        artifact_path.write_bytes(data)
    try:
        metadata["size_bytes"] = artifact_path.stat().st_size
    except OSError:
        pass
    metadata.update(_image_dimensions(artifact_path, metadata["mime_type"]))
    return metadata


def _upload_bytes(value: Any) -> bytes:
    if isinstance(value, dict):
        data = value.get("buffer", value.get("data", value.get("content", b"")))
    else:
        data = getattr(value, "buffer", getattr(value, "data", getattr(value, "content", b"")))
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, str):
        try:
            return base64.b64decode(data)
        except Exception:
            return data.encode("utf-8")
    return b""


def _upload_mime_type(value: Any, filename: str) -> str:
    if isinstance(value, dict):
        mime_type = value.get("mime_type") or value.get("mimeType") or value.get("type")
        if mime_type:
            return str(mime_type)
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _image_dimensions(path: Path, mime_type: str) -> dict[str, int]:
    if not str(mime_type or "").lower().startswith("image/"):
        return {}
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
        return {"width": int(width), "height": int(height)}
    except Exception:
        return {}


def _safe_filename(filename: str) -> str:
    name = os.path.basename(str(filename or "upload"))
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return name or "upload"


def _unique_artifact_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem or "upload"
    suffix = path.suffix
    parent = path.parent
    index = 1
    while True:
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _safe_path_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "evaluation")).strip("._")
    return safe or "evaluation"


def _image_evidence_fields(*, mode: str, filename: str, component: dict[str, Any]) -> dict[str, Any]:
    if mode == "device":
        return {
            "action": "Uploaded image from device",
            "source": "device",
            "filename": filename,
        }
    if mode == "camera":
        return {
            "action": "Captured live photo",
            "source": "camera",
            "camera_used": True,
            "retakes": int(component.get("retakes") or 0),
            "filename": filename,
        }
    return {
        "action": "Uploaded predefined test image",
        "source": "test_image",
        "filename": filename,
    }


def _metadata(component: dict[str, Any]) -> dict[str, Any]:
    return {
        "selector": component.get("selector"),
        "placeholder": component.get("placeholder"),
        "name": component.get("name"),
        "component": component,
    }


def _field_name(component: dict[str, Any]) -> str:
    return _first_text(component, "field", "label", "name", "id", "selector")


def _optional_field_name(component: dict[str, Any]) -> str | None:
    field = _field_name(component)
    return field or None


def _field_and_value(component: dict[str, Any], scenario: TestScenario) -> tuple[str, Any | None]:
    field = _field_name(component)
    value = _first_text(component, "value", "selected", "default", "text")
    if value:
        return field, value

    values = _values(component, scenario)
    if values:
        return field, values[0]

    return field, None


def _values(component: dict[str, Any], scenario: TestScenario) -> list[Any]:
    raw_values = component.get("values")
    if isinstance(raw_values, list):
        return [value for value in raw_values if value not in (None, "")]

    options = component.get("options")
    if not isinstance(options, list):
        return []

    scenario_tokens = _tokens(" ".join([scenario.persona.goal, scenario.persona.tone, scenario.persona.edge_case or ""]))
    scored: list[tuple[int, Any]] = []
    for option in options:
        if isinstance(option, dict):
            value = _first_text(option, "value", "message", "text", "label", "title", "id")
            selected = bool(option.get("selected") or option.get("checked"))
        else:
            value = str(option)
            selected = False
        if not value:
            continue
        option_score = 100 if selected else len(scenario_tokens & _tokens(value))
        scored.append((option_score, value))

    if not scored:
        return []

    scored.sort(key=lambda item: item[0], reverse=True)
    if scored[0][0] <= 0:
        return [scored[0][1]]
    return [value for score, value in scored if score == scored[0][0]]


def _bool_value(component: dict[str, Any]) -> bool:
    value = component.get("value", component.get("checked", component.get("selected", True)))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "checked"}
    return bool(value)


def _form_fields(component: dict[str, Any]) -> list[dict[str, Any]]:
    fields = component.get("fields") or component.get("components") or component.get("inputs")
    if isinstance(fields, dict):
        normalized = []
        for key, value in fields.items():
            if isinstance(value, dict):
                normalized.append({"name": key, "label": value.get("label") or key, **value})
            else:
                normalized.append({"type": "text", "name": key, "label": key, "value": value})
        return normalized
    if isinstance(fields, list):
        return [field for field in fields if isinstance(field, dict)]
    return []
