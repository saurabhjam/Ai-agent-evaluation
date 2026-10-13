import pytest

from app.adapters.chat.browser import _ui_validation_result


def test_ui_validation_detects_expected_form_controls():
    scan = {
        "forms": [{"title": "Maintenance Request", "fields": [{"label": "Description", "type": "textarea"}]}],
        "inputs": [{"label": "Description", "type": "textarea"}],
        "buttons": [{"text": "Submit"}],
        "summary": {
            "form_detected": True,
            "fields_detected": 3,
            "submit_button_detected": True,
            "upload_control_detected": True,
            "accept": "image/*",
            "camera_available": True,
            "otp_field_detected": False,
            "date_field_detected": False,
            "time_field_detected": False,
            "search_field_detected": False,
            "buttons_detected": 1,
        },
    }

    result = _ui_validation_result(scan, "Please complete the form and upload a photo.")
    evidence = result["interaction_evidence"]

    assert evidence["interaction_type"] == "ui_validation"
    assert evidence["success"] is True
    assert evidence["form_detected"] is True
    assert evidence["form_name"] == "Maintenance Request"
    assert evidence["fields_detected"] == 3
    assert evidence["upload_control_detected"] is True
    assert evidence["accept"] == "image/*"


def test_ui_validation_fails_when_requested_form_is_missing():
    result = _ui_validation_result(
        {"forms": [], "inputs": [], "buttons": [], "summary": {"fields_detected": 0, "buttons_detected": 0}},
        "Please fill out the claim form.",
    )
    evidence = result["interaction_evidence"]

    assert evidence["success"] is False
    assert evidence["status"] == "FAILED"
    assert "form" in evidence["error"]


def test_ui_validation_does_not_emit_evidence_for_plain_text_response():
    result = _ui_validation_result(
        {"forms": [], "inputs": [], "buttons": [], "summary": {"fields_detected": 0, "buttons_detected": 0}},
        "Thanks, I can help with that.",
    )

    assert result["interaction_evidence"] is None
    assert result["ui_validation"]["summary"]["fields_detected"] == 0
