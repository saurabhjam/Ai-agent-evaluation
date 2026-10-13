from __future__ import annotations

from app.calling.ui_api import CallingConnectionInput, _safe_connection


def test_calling_connection_input_ignores_eval_transport_payload():
    payload = CallingConnectionInput(
        name="Sophia Calling",
        provider="vapi",
        config={"assistant_id": "assistant-id", "phone_number_id": "phone-id"},
        credentials={"api_key": "env:VAPI_API_KEY"},
        eval_transport={
            "provider": "twilio",
            "credentials": {"api_key": "env:TWILIO_AUTH_TOKEN"},
            "settings": {"phone_number_id": "env:TWILIO_ACCOUNT_SID"},
        },
    )

    assert "eval_transport" not in payload.model_dump()


def test_safe_calling_connection_omits_legacy_eval_transport():
    safe = _safe_connection(
        {
            "id": "calling_legacy",
            "name": "Legacy Calling",
            "provider": "vapi",
            "enabled": True,
            "config": {"assistant_id": "assistant-id", "phone_number_id": "phone-id"},
            "credentials": {"api_key": "env:VAPI_API_KEY"},
            "eval_transport": {
                "provider": "twilio",
                "credentials": {"api_key": "env:TWILIO_AUTH_TOKEN"},
                "settings": {"phone_number_id": "env:TWILIO_ACCOUNT_SID"},
            },
            "created_at": "2026-10-06T00:00:00+00:00",
            "updated_at": "2026-10-06T00:00:00+00:00",
        }
    )

    dumped = safe.model_dump()
    assert dumped["credentials"] == {"api_key": "configured"}
    assert "eval_transport" not in dumped
