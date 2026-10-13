import zipfile
import copy
import base64
from io import BytesIO

import pytest

from app.report_engine import (
    build_enterprise_report,
    build_enterprise_report_docx,
    build_enterprise_report_html,
    build_enterprise_report_pdf,
    build_executive_report,
    build_executive_report_docx,
    build_executive_report_html,
    build_executive_report_pdf,
    build_technical_report,
    build_technical_report_docx,
    build_technical_report_html,
    build_technical_report_pdf,
    _pdf_cell_value,
)


def _report():
    return {
        "evaluation_id": "eval_123",
        "agent_id": "conn-1",
        "agent_type": "chatbot",
        "adapter": "rest",
        "scenario_id": "scenario-a",
        "created_at": "2026-10-08T10:00:00Z",
        "duration_seconds": 12.5,
        "success": True,
        "overall_score": 0.82,
        "passed": True,
        "pass_threshold": 70,
        "metrics": [
            {
                "name": "Goal Completion",
                "score": 90,
                "reason": "The goal was satisfied.",
            },
            {
                "metric": "Persona & Tone",
                "score": 20,
                "reason": "Tone drifted.",
            },
            {
                "metric": "Conversational Quality",
                "score": 30,
                "reason": "The conversation was incomplete.",
            }
        ],
        "conversation": [
            {"speaker": "user", "message": "Hello"},
            {
                "speaker": "agent",
                "message": "Choose one",
                "components": [
                    {"type": "button", "label": "Continue", "message": "Continue"},
                    {"type": "quick_reply", "label": "Show results"},
                    {"type": "table", "title": "Units", "headers": ["Status", "Property", "Unit", "Priority"], "rows": [["OPEN", "Mason & Main", "B507", "High"]]},
                    {"type": "form", "title": "Maintenance Request Form", "fields": [{"label": "Name", "value": "Rahul"}]},
                ],
                "attachments": [
                    {"type": "application/pdf", "name": "Maintenance_Report.pdf", "url": "https://example.com/report.pdf"},
                    {"mime_type": "image/png", "name": "damage-photo.png", "preview_url": "https://example.com/damage-photo.png"},
                ],
            },
            {
                "speaker": "user",
                "message": "Entered OTP\n******",
                "metadata": {
                    "interaction_evidence": {
                        "interaction_type": "otp",
                        "action": "OTP entered",
                        "selected_value": "******",
                        "success": True,
                        "status": "SUCCESS",
                        "duration_ms": 4500,
                    }
                },
            },
            {
                "speaker": "user",
                "message": "Submitted form",
                "metadata": {
                    "interaction_evidence": {
                        "interaction_type": "form_fill",
                        "action": "Completed maintenance form",
                        "selected_value": {"Name": "Rahul", "OTP": "123456"},
                        "success": True,
                        "status": "SUCCESS",
                        "fields_completed": 2,
                    }
                },
            },
            {
                "speaker": "user",
                "message": "Uploaded image",
                "metadata": {
                    "interaction_evidence": {
                        "interaction_type": "camera_capture",
                        "action": "Captured live photo",
                        "filename": "camera-capture.jpg",
                        "artifact_path": "artifacts/eval_123/uploaded/camera-capture.jpg",
                        "mime_type": "image/jpeg",
                        "source": "camera",
                        "camera_used": True,
                        "retakes": 1,
                        "success": True,
                        "status": "SUCCESS",
                    }
                },
            },
        ],
        "rag_evaluation": {"status": "not_evaluated"},
        "backend_validation": {
            "status": "validated",
            "passed": True,
            "reason": "Backend checks passed.",
            "checks": [
                {
                    "name": "Expected phrase",
                    "passed": True,
                    "reason": "Expected phrase was found.",
                    "expected": "Submitted",
                    "actual": "found",
                    "evidence": {
                        "method": "GET",
                        "endpoint": "https://api.example.test/tickets/MT-10234",
                        "status_code": 200,
                        "response_time_ms": 182,
                        "response_body": '{"status":"OPEN"}',
                        "extracted_variables": {"ticket_id": "MT-10234"},
                        "assertion": {
                            "status": "PASS",
                            "jsonpath": "$.status",
                            "operator": "equals",
                            "expected": "OPEN",
                            "actual": "OPEN",
                        },
                    },
                }
            ],
        },
    }


def _report_with_failure():
    payload = copy.deepcopy(_report())
    payload["failure_analysis"] = [
        {
            "failure_id": "failure-1",
            "metric_name": "Backend Validation",
            "status": "FAILED",
            "severity": "HIGH",
            "category": "Backend Validation",
            "source": "BackendValidator",
            "reason": "The backend ticket status did not match.",
            "expected": {"$.status": "OPEN"},
            "actual": {"$.status": "CLOSED"},
            "root_cause": "The backend API returned a closed ticket after the agent claimed the ticket was open.",
            "recommendation": "Verify the backend status update before confirming the request.",
            "conversation_turn": 2,
            "conversation_message_id": "msg-2",
            "conversation_snippet": [
                {"label": "Previous Turn", "turn": 1, "speaker": "user", "message": "Hello"},
                {"label": "Failure Turn", "turn": 2, "speaker": "agent", "message": "Your ticket is open."},
                {"label": "Next Turn", "turn": 3, "speaker": "user", "message": "Thanks"},
            ],
            "evidence": [
                {
                    "type": "api_response",
                    "endpoint": "GET /tickets/MT-10234",
                    "status_code": 200,
                    "response": {"status": "CLOSED"},
                }
            ],
            "technical_details": {"assertion": "$.status equals OPEN"},
        },
        {
            "failure_id": "failure-2",
            "metric_name": "Intent Detection",
            "status": "FAILED",
            "severity": "MEDIUM",
            "category": "Intent",
            "reason": "The detected intent did not match the requested workflow.",
        },
    ]
    return payload


def test_enterprise_report_contains_assessment_sections():
    report = build_enterprise_report(_report())

    assert report["schema"] == "evalforge.enterprise_report.v1"
    assert report["title"] == "AI Agent Assessment Report"
    assert report["header"]["evaluation_id"] == "eval_123"
    assert report["executive_summary"]["narrative"]
    assert report["scorecard"]["passed_metrics"] == 1
    assert report["scorecard"]["failed_metrics"] == 2
    assert report["scorecard"]["pass_threshold_display"] == "70.0%"
    assert len(report["capability_matrix"]) >= 4
    assert len(report["conversation_timeline"]) == 5
    assert report["conversation_timeline"][1]["component_count"] == 4
    assert report["conversation_timeline"][1]["attachment_count"] == 2
    assert report["conversation_timeline"][2]["interaction_evidence"]["interaction_type"] == "otp"
    assert len(report["artifacts"]["buttons"]) == 2
    assert len(report["artifacts"]["tables"]) == 1
    assert len(report["artifacts"]["forms"]) == 1
    assert report["artifacts"]["interaction_summary"]["otp_verifications"] == 1
    assert report["artifacts"]["interaction_summary"]["forms_submitted"] == 1
    assert report["artifacts"]["interaction_summary"]["camera_captures"] == 1
    assert "ui_validations" in report["artifacts"]["interaction_summary"]
    assert report["backend_validation"]["status"] == "validated"
    assert report["executive_summary"]["overall_risk"] in {"Low", "Medium", "High"}
    assert report["report_metadata"]["client_report_version"]
    assert report["report_metadata"]["generated_by"] == "EvalForge"
    assert report["report_metadata"]["evalforge_version"]
    assert report["report_metadata"]["evaluation_id"] == "eval_123"
    assert report["report_metadata"]["generated_at"] == report["generated_at"]
    assert report["executive_summary"]["total_metrics"] == 3
    assert report["evaluation_summary"][0]["metric"] == "Goal Completion"
    assert report["overall_findings"]
    assert report["priority_recommendations"][0]["priority"] == 1
    assert "raw_json" in report["appendix"]
    assert report["failure_analysis"] == []


def test_phase_7_builds_distinct_executive_and_technical_reports():
    payload = _report_with_failure()

    executive = build_executive_report(payload)
    technical = build_technical_report(payload)

    assert executive["schema"] == "evalforge.executive_report.v1"
    assert executive["report_type"] == "executive"
    assert executive["title"] == "Executive AI Agent Assessment Report"
    assert "raw_report" not in executive
    assert "raw_json" not in executive["appendix"]
    assert executive["report_metadata"]["report_type"] == "Executive Report"
    assert technical["schema"] == "evalforge.technical_report.v1"
    assert technical["report_type"] == "technical"
    assert technical["title"] == "Technical AI Agent Assessment Report"
    assert "raw_report" in technical
    assert "raw_json" in technical["appendix"]


def test_phase_7_executive_html_omits_raw_json_and_technical_html_keeps_appendix():
    payload = _report_with_failure()

    executive_html = build_executive_report_html(payload)
    technical_html = build_technical_report_html(payload)

    assert "Executive AI Agent Assessment Report" in executive_html
    assert "KPI Dashboard" in executive_html
    assert "Final Recommendation" in executive_html
    assert "Raw JSON" not in executive_html
    assert "Technical AI Agent Assessment Report" in technical_html
    assert "Appendix" in technical_html
    assert "raw_json" not in technical_html
    assert "saved evaluation JSON" in technical_html


def test_enterprise_html_contains_branded_sections():
    html = build_enterprise_report_html(_report())

    assert "AI Agent Assessment Report" in html
    assert "Section 1 · Executive Summary" in html
    assert "Client Report Version" in html
    assert "Generated By" in html
    assert "EvalForge Version" in html
    assert "Evaluation ID" in html
    assert "Generated At" in html
    assert "Section 2 · Evaluation Summary" in html
    assert "Executive Scorecard" in html
    assert "Capability Matrix" in html
    assert "Conversation Timeline" in html
    assert "Available Options" in html
    assert "Continue" in html
    assert "Show results" in html
    assert "Mason &amp; Main" in html
    assert "B507" in html
    assert "Maintenance Request Form" in html
    assert "Maintenance_Report.pdf" in html
    assert "damage-photo.png" in html
    assert 'class="rich-image"' in html
    assert "EvalForge Action" in html
    assert "Submitted form" in html
    assert "Submitted" in html
    assert "OTP Verified" in html
    assert "Verified" in html
    assert "Live Camera" in html
    assert "artifacts/eval_123/uploaded/camera-capture.jpg" in html
    assert "123456" not in html
    assert "Recommendations" in html
    assert "Backend Validation" in html
    assert "Section 5 · Backend Validation" in html
    assert "Section 6 · Workflow Validation" in html
    assert "Section 8 · Overall Findings" in html
    assert "Section 9 · Priority Recommendations" in html
    assert "Appendix" in html
    assert "Backend Validation Timeline" in html
    assert "Backend Explorer" in html
    assert "Variable extraction" in html
    assert "REST validator execution" in html
    assert "Assertion execution" in html
    assert "Backend checks passed." in html
    assert "Failure Analysis" not in html


def test_enterprise_report_preserves_failure_analysis_objects():
    report = build_enterprise_report(_report_with_failure())

    assert len(report["failure_analysis"]) == 2
    assert len(report["detailed_failure_analysis"]) == 2
    assert report["failure_analysis"][0]["failure_id"] == "failure-1"
    assert report["failure_analysis"][0]["metric_name"] == "Backend Validation"
    assert report["failure_analysis"][1]["metric_name"] == "Intent Detection"
    assert report["detailed_failure_analysis"][0]["business_summary"]
    assert report["detailed_failure_analysis"][0]["developer_notes"]["technical_details"]


def test_enterprise_html_renders_failure_analysis_cards():
    html = build_enterprise_report_html(_report_with_failure())

    assert "Failure Analysis" in html
    assert "Detailed Failure Analysis" in html
    assert "Business Summary" in html
    assert "Expected Behaviour" in html
    assert "Actual Behaviour" in html
    assert "Business Impact" in html
    assert "Technical Details" in html
    assert "Developer Notes" not in html
    assert "Backend Validation" in html
    assert "Intent Detection" in html
    assert "Failure occurred here" in html
    assert "GET /tickets/MT-10234" in html
    assert "$.status equals OPEN" not in html
    assert "The backend ticket status did not match." in html


def test_technical_html_renders_readable_failure_details_without_internal_json():
    payload = _report_with_failure()
    payload["failure_analysis"][0]["technical_details"] = {
        "category": "Response Validation",
        "score": 0.7,
        "threshold": 0.75,
        "evidence_source": None,
        "conversation_message_refs": {"failure_turn": {"message_id": "ef-message-9"}},
        "raw_metric_evidence": [
            {
                "message_id": "ef-message-9",
                "turn_index": 9,
                "components": [
                    {"type": "button", "label": "Rent arrears (whole portfolio)"},
                    {"type": "quick_reply", "label": "Who is overdue on rent across my portfolio?"},
                ],
            }
        ],
        "raw_conversation_snippet": [{"message_id": "ef-message-9"}],
        "raw_evaluator_reason": "The assistant requested additional information even though sufficient context already existed.",
    }
    payload["failure_analysis"][0]["evidence"] = [
        {
            "type": "conversation_card",
            "previous_turn": "Turn 8 - User: What is the average overdue rent amount?",
            "failed_turn": "Turn 9 - Agent: I need more detail before I query your portfolio.",
            "next_turn": "N/A",
            "why_this_proves_failure": "The assistant ignored previously established context.",
        }
    ]

    html = build_technical_report_html(payload)

    assert "Conversation Evidence" in html
    assert "Previous Turn" in html
    assert "Failed Turn" in html
    assert "Why this proves the failure" in html
    assert "Metric Category" in html
    assert "Response Validation" in html
    assert "Score" in html
    assert "0.70 / 1.00" in html
    assert "Conversation Analysis" in html
    assert "UI Components Observed" in html
    assert "Rent arrears (whole portfolio)" in html
    assert "Quick Reply Buttons" in html
    assert "Who is overdue on rent across my portfolio?" in html
    assert "conversation_card" not in html
    assert "technical_details" not in html
    assert "raw_metric_evidence" not in html
    assert "raw_conversation_snippet" not in html
    assert "conversation_message_refs" not in html
    assert "ef-message-9" not in html
    assert "message_id" not in html


def test_enterprise_html_handles_failure_without_evidence_or_snippet():
    payload = _report_with_failure()
    payload["failure_analysis"] = [payload["failure_analysis"][1]]

    html = build_enterprise_report_html(payload)

    assert "Failure Analysis" in html
    assert "Intent Detection" in html
    assert "Evidence 1" not in html
    assert "Conversation Evidence" not in html


def test_enterprise_pdf_returns_pdf_bytes():
    pytest.importorskip("reportlab")
    pdf = build_enterprise_report_pdf(_report())

    assert pdf.startswith(b"%PDF-1.4")
    assert b"%%EOF" in pdf


def test_enterprise_pdf_renders_failure_analysis():
    pytest.importorskip("reportlab")
    pdf = build_enterprise_report_pdf(_report_with_failure())

    assert pdf.startswith(b"%PDF-1.4")
    assert b"%%EOF" in pdf


def test_phase_7_executive_and_technical_pdf_exports():
    pytest.importorskip("reportlab")
    payload = _report_with_failure()

    executive_pdf = build_executive_report_pdf(payload)
    technical_pdf = build_technical_report_pdf(payload)

    assert executive_pdf.startswith(b"%PDF-1.4")
    assert b"%%EOF" in executive_pdf
    assert technical_pdf.startswith(b"%PDF-1.4")
    assert b"%%EOF" in technical_pdf


def test_enterprise_pdf_handles_long_failure_json_without_layout_error():
    pytest.importorskip("reportlab")
    payload = _report_with_failure()
    long_value = "x" * 5000
    payload["failure_analysis"][0]["technical_details"] = {
        "api_response": {"body": long_value},
        "stack_trace": long_value,
    }
    payload["failure_analysis"][0]["evidence"] = [
        {
            "type": "api_response",
            "endpoint": "GET /tickets/MT-10234",
            "response_body": long_value,
        }
    ]

    pdf = build_enterprise_report_pdf(payload)

    assert pdf.startswith(b"%PDF-1.4")
    assert b"%%EOF" in pdf


def test_enterprise_pdf_handles_long_conversation_without_layout_error():
    pytest.importorskip("reportlab")
    payload = _report_with_failure()
    long_message = "The agent provided a very long response. " * 180
    payload["conversation"] = [
        {"speaker": "user", "message": "Please help me."},
        {"speaker": "agent", "message": long_message},
        {"speaker": "user", "message": "Thank you."},
    ]
    payload["failure_analysis"][0]["conversation_snippet"] = [
        {"label": "Previous Turn", "turn": 1, "speaker": "user", "message": "Please help me."},
        {"label": "Failure Turn", "turn": 2, "speaker": "agent", "message": long_message},
        {"label": "Next Turn", "turn": 3, "speaker": "user", "message": "Thank you."},
    ]

    pdf = build_enterprise_report_pdf(payload)

    assert pdf.startswith(b"%PDF-1.4")
    assert b"%%EOF" in pdf


def test_enterprise_pdf_handles_multiple_long_failures_without_layout_error():
    pytest.importorskip("reportlab")
    payload = _report_with_failure()
    long_json = {"response": "y" * 5000}
    payload["failure_analysis"] = [
        {
            **payload["failure_analysis"][0],
            "failure_id": f"failure-{index}",
            "metric_name": f"Metric {index}",
            "actual": long_json,
            "technical_details": {"raw_metric_evidence": long_json},
        }
        for index in range(1, 5)
    ]

    pdf = build_enterprise_report_pdf(payload)

    assert pdf.startswith(b"%PDF-1.4")
    assert b"%%EOF" in pdf


def test_pdf_table_cells_are_capped_for_reportlab_safety():
    value = _pdf_cell_value({"response": "z" * 5000})

    assert len(value) <= 300
    assert "[truncated]" in value


def test_enterprise_docx_returns_valid_docx_package():
    pytest.importorskip("docx")
    docx = build_enterprise_report_docx(_report())

    with zipfile.ZipFile(BytesIO(docx)) as package:
        names = set(package.namelist())
        assert "[Content_Types].xml" in names
        assert "word/document.xml" in names
        document = package.read("word/document.xml").decode("utf-8")
    assert "EVALFORGE" in document
    assert "AI Agent Assessment Report" in document
    assert "Available Options" in document
    assert "Mason &amp; Main" in document
    assert "Maintenance_Report.pdf" in document
    assert "EvalForge Action" in document
    assert "OTP Verified" in document
    assert "123456" not in document


def test_enterprise_docx_renders_failure_analysis():
    pytest.importorskip("docx")
    docx = build_enterprise_report_docx(_report_with_failure())

    with zipfile.ZipFile(BytesIO(docx)) as package:
        document = package.read("word/document.xml").decode("utf-8")
    assert "Failure Analysis" in document
    assert "Backend Validation" in document
    assert "FAILURE OCCURRED HERE" in document
    assert "GET /tickets/MT-10234" in document


def test_phase_7_executive_and_technical_docx_exports():
    pytest.importorskip("docx")
    payload = _report_with_failure()

    executive_docx = build_executive_report_docx(payload)
    technical_docx = build_technical_report_docx(payload)

    with zipfile.ZipFile(BytesIO(executive_docx)) as package:
        executive_document = package.read("word/document.xml").decode("utf-8")
    with zipfile.ZipFile(BytesIO(technical_docx)) as package:
        technical_document = package.read("word/document.xml").decode("utf-8")
    assert "Executive AI Agent Assessment Report" in executive_document
    assert "KPI Dashboard" in executive_document
    assert "Final Recommendation" in executive_document
    assert "Technical AI Agent Assessment Report" in technical_document
    assert "Technical Details" in technical_document


def test_technical_docx_omits_internal_failure_json_fields():
    pytest.importorskip("docx")
    payload = _report_with_failure()
    payload["failure_analysis"][0]["technical_details"] = {
        "category": "Response Validation",
        "score": 0.7,
        "threshold": 0.75,
        "conversation_message_refs": {"failure_turn": {"message_id": "ef-message-9"}},
        "raw_metric_evidence": [
            {
                "message_id": "ef-message-9",
                "turn_index": 9,
                "components": [
                    {"type": "button", "label": "Rent arrears (whole portfolio)"},
                    {"type": "quick_reply", "label": "Who is overdue on rent across my portfolio?"},
                ],
            }
        ],
        "raw_conversation_snippet": [{"message_id": "ef-message-9"}],
    }
    payload["failure_analysis"][0]["evidence"] = [
        {
            "type": "conversation_card",
            "previous_turn": "Turn 8 - User: What is the average overdue rent amount?",
            "failed_turn": "Turn 9 - Agent: I need more detail before I query your portfolio.",
            "next_turn": "N/A",
            "why_this_proves_failure": "The assistant ignored previously established context.",
        }
    ]

    docx = build_technical_report_docx(payload)

    with zipfile.ZipFile(BytesIO(docx)) as package:
        document = package.read("word/document.xml").decode("utf-8")
    assert "Technical Details" in document
    assert "Metric Category" in document
    assert "0.70 / 1.00" in document
    assert "Rent arrears (whole portfolio)" in document
    assert "conversation_message_refs" not in document
    assert "raw_metric_evidence" not in document
    assert "raw_conversation_snippet" not in document
    assert "ef-message-9" not in document
    assert "message_id" not in document


def test_pdf_and_docx_embed_existing_evidence_image(tmp_path, monkeypatch):
    pytest.importorskip("reportlab")
    pytest.importorskip("docx")
    monkeypatch.chdir(tmp_path)
    image_path = tmp_path / "artifacts" / "eval_123" / "uploaded" / "camera-capture.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))

    payload = copy.deepcopy(_report())
    payload["conversation"][4]["metadata"]["interaction_evidence"]["filename"] = "camera-capture.png"
    payload["conversation"][4]["metadata"]["interaction_evidence"]["artifact_path"] = "artifacts/eval_123/uploaded/camera-capture.png"
    payload["conversation"][4]["metadata"]["interaction_evidence"]["mime_type"] = "image/png"

    pdf = build_enterprise_report_pdf(payload)
    docx = build_enterprise_report_docx(payload)

    assert pdf.startswith(b"%PDF")
    with zipfile.ZipFile(BytesIO(docx)) as package:
        assert any(name.startswith("word/media/") for name in package.namelist())
