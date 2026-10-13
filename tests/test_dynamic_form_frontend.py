from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "frontend" / "static" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_dynamic_form_renderer_is_present():
    assert "renderInteractionForm" in APP_JS
    assert "_renderInteractionField" in APP_JS
    assert "interaction-form-panel" in INDEX


def test_dynamic_form_supports_required_field_types():
    for field_type in [
        "textarea",
        "email",
        "phone",
        "number",
        "password",
        "dropdown",
        "radio",
        "checkbox",
        "multi_select",
        "date",
        "time",
        "datetime-local",
        "search",
        "file_upload",
        "image_upload",
    ]:
        assert field_type in APP_JS


def test_dynamic_form_validation_is_present():
    assert "This field is required." in APP_JS
    assert "Enter a valid email address." in APP_JS
    assert "Enter a valid phone number." in APP_JS
    assert "Enter a valid number." in APP_JS
    assert "submitInteractionForm" in APP_JS


def test_realtime_otp_modal_is_present():
    assert "interaction-otp-panel" in INDEX
    assert "interaction-otp-input" in INDEX
    assert "btn-interaction-submit-otp" in INDEX
    assert "OTP Verification Required" in APP_JS
    assert "renderInteractionOtp" in APP_JS
    assert "submitInteractionOtp" in APP_JS


def test_realtime_otp_validation_and_masking_are_present():
    assert "OTP is required." in APP_JS
    assert "Enter a \" + constraints.length + \"-character OTP." in APP_JS
    assert "OTP must contain only numbers." in APP_JS
    assert "autocomplete=\"one-time-code\"" in INDEX
    assert "type=\"password\"" in INDEX


def test_live_camera_capture_ui_is_present():
    assert "btn-interaction-camera" in INDEX
    assert "Capture Live Photo" in INDEX
    assert "interaction-camera-video" in INDEX
    assert "interaction-camera-canvas" in INDEX
    assert "interaction-camera-preview" in INDEX
    assert "btn-camera-capture" in INDEX
    assert "btn-camera-retake" in INDEX
    assert "btn-camera-use" in INDEX


def test_live_camera_frontend_flow_is_present():
    assert "navigator.mediaDevices.getUserMedia" in APP_JS
    assert "openCameraCapture" in APP_JS
    assert "captureCameraPhoto" in APP_JS
    assert "retakeCameraPhoto" in APP_JS
    assert "useCameraPhoto" in APP_JS
    assert "State.cameraRetakes += 1" in APP_JS
    assert "camera_used: true" in APP_JS
    assert "source: \"camera\"" in APP_JS
    assert "_stopInteractionCamera" in APP_JS
    assert "_clearInteractionCanvas" in APP_JS
    assert "track.stop()" in APP_JS


def test_live_camera_permission_denied_keeps_device_upload_available():
    assert "Camera unavailable or permission denied. You can upload from your device instead." in APP_JS
    assert "Camera not available" in APP_JS
    assert "_refreshCameraAvailability" in APP_JS


def test_interaction_evidence_renders_inside_conversation_timeline():
    assert "_interactionEvidence" in APP_JS
    assert "_renderInteractionEvidenceCard" in APP_JS
    assert 'App._renderInteractionEvidenceCard(evidence, turn, "inline")' in APP_JS
    assert "EVALFORGE ACTION" in APP_JS
    assert "Form Submitted" in APP_JS
    assert "Image Uploaded" in APP_JS
    assert "Live Camera" in APP_JS
    assert "OTP Verified" in APP_JS
    assert "Button Clicked" in APP_JS
    assert "Selected Option" in APP_JS
    assert "media-preview-body" in INDEX


def test_rich_conversation_replay_renderers_are_present():
    assert "_renderInteractionReplay" in APP_JS
    assert "_renderReplayRows" in APP_JS
    assert "_renderReplaySelection" in APP_JS
    assert "_renderChoiceComponent" in APP_JS
    assert "Submitted" in APP_JS
    assert "Verified" in APP_JS
    assert "Selected" in APP_JS
    assert "Checked" in APP_JS
    assert "Captured Live" in APP_JS
    assert "componentHtml + attachmentHtml + evidenceHtml + toolHtml" in APP_JS


def test_image_attachments_render_as_clickable_previews():
    assert "_isImageAttachment" in APP_JS
    assert "preview_url" in APP_JS
    assert "thumbnail_url" in APP_JS
    assert "artifact_path" in APP_JS
    assert "size_bytes" in APP_JS
    assert "blob_url" in APP_JS
    assert "rich-image-preview" in APP_JS
    assert "App.openMediaPreview" in APP_JS
    assert 'typeof item === "object"' in APP_JS
    for extension in ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"]:
        assert extension in APP_JS


def test_artifact_summary_uses_interaction_evidence_counts():
    assert "_interactionSummary" in APP_JS
    assert "Forms Submitted" in APP_JS
    assert "Images Uploaded" in APP_JS
    assert "Camera Captures" in APP_JS
    assert "OTP Verifications" in APP_JS
    assert "Buttons Clicked" in APP_JS
    assert "Dropdown Selections" in APP_JS


def test_professional_report_renders_backend_validation_section():
    assert "Backend Validation" in APP_JS
    assert "_professionalBackendValidation" in APP_JS
    assert "_backendValidationTimeline" in APP_JS
    assert "_backendValidationExplorer" in APP_JS
    assert "Backend Validation Timeline" in APP_JS
    assert "Backend Explorer" in APP_JS
    assert "backend_validation" in APP_JS


def test_connection_ui_supports_backend_validation_connections():
    assert "conn-backend-validation-enabled" in INDEX
    assert "conn-backend-list" in INDEX
    assert "conn-backend-form" in INDEX
    assert "conn-backend-name" in INDEX
    assert "conn-backend-type" in INDEX
    assert "conn-backend-auth-type" in INDEX
    assert "conn-backend-sql-fields" in INDEX
    assert "MongoDB (Coming Soon)" in INDEX
    assert "showBackendConnectionForm" in APP_JS
    assert "saveBackendConnectionForm" in APP_JS
    assert "renderBackendConnections" in APP_JS
    assert "Connection testing coming soon." in APP_JS
    assert "_buildBackendValidationConfig" in APP_JS
    assert "_restoreBackendValidationConfig" in APP_JS
    assert "backend_validation: backendValidationConfig" in APP_JS
