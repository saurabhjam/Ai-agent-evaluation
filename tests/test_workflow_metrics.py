import pytest
from app.workflow_metrics import run_workflow_metrics
from app.schemas import MetricResult
from unittest.mock import MagicMock

def _msg(turn_index, interaction_type, action, success):
    return MagicMock(
        turn_index=turn_index,
        metadata={
            "interaction_evidence": {
                "interaction_type": interaction_type,
                "action": action,
                "success": success,
                "duration_ms": 3500,
                "source": "device",
            }
        }
    )

def test_workflow_metrics_generated():
    transcript = [
        _msg(1, "form", "Form completed", True),
        _msg(2, "otp", "OTP entered", True),
        _msg(3, "image_upload", "Uploaded image", True),
        _msg(4, "camera_capture", "Captured live photo", True),
        _msg(5, "document_upload", "Uploaded document", True),
        _msg(6, "video_upload", "Uploaded video", True),
        _msg(7, "ui_validation", "Browser UI validation", True),
    ]
    
    metrics = run_workflow_metrics(transcript)
    assert len(metrics) == 7
    names = [m.name for m in metrics]
    assert "Form Completion" in names
    assert "OTP Verification" in names
    assert "Image Upload" in names
    assert "Live Camera Capture" in names
    assert "Document Upload" in names
    assert "Video Upload" in names
    assert "UI Validation" in names

    for m in metrics:
        assert m.category == "Workflow"
        assert m.score == 1.0
        assert m.passed is True

def test_workflow_metric_failed():
    transcript = [
        _msg(1, "form", "Form completed", False),
    ]
    metrics = run_workflow_metrics(transcript)
    assert len(metrics) == 1
    assert metrics[0].passed is False
    assert metrics[0].score == 0.0

def test_human_handoff_skipped_correctly():
    transcript = [
        _msg(1, "form", "Form completed", True),
    ]
    metrics = run_workflow_metrics(transcript)
    names = [m.name for m in metrics]
    assert "Human Handoff" not in names

def test_timeline_generated():
    from app.report_engine import _workflow_timeline
    
    transcript = [
        {"metadata": {"interaction_evidence": {"interaction_type": "form", "action": "Form completed", "success": True, "duration_ms": 3500, "source": "device"}}}
    ]
    
    timeline = _workflow_timeline(transcript)
    assert len(timeline) == 1
    assert timeline[0]["action"] == "Form completed"
    assert timeline[0]["status"] == "Completed"
    assert timeline[0]["duration"] == "3 sec"
    assert timeline[0]["interaction"] == "form"
