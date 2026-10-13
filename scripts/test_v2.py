import sys
from app.report_engine import build_enterprise_report_pdf, build_enterprise_report_docx, build_enterprise_report_html

mock_payload = {
    "header": {
        "evaluation_id": "test-123",
        "agent_name": "Test Agent",
        "scenario": "Test Scenario",
        "adapter": "REST",
        "date_time": "2026-10-09T00:00:00Z",
        "duration": "10s",
        "status": "PASS",
        "overall_score": 0.95
    },
    "passed": True,
    "overall_score": 0.95,
    "metrics": [
        {"name": "Form Completion", "score": 1.0, "passed": True, "category": "Workflow", "threshold": 1.0, "reason": "OK"},
        {"name": "RAG Answer Relevancy", "score": 0.9, "passed": True, "category": "rag", "threshold": 0.8, "reason": "OK"}
    ],
    "conversation": [
        {"speaker": "user", "message": "Hi"},
        {"speaker": "agent", "message": "Hello"}
    ],
    "rag_evaluation": {"status": "evaluated"},
    "recording_metadata": [],
    "artifacts": {}
}

print("Testing PDF...")
build_enterprise_report_pdf(mock_payload)
print("Testing DOCX...")
build_enterprise_report_docx(mock_payload)
print("Testing HTML...")
build_enterprise_report_html(mock_payload)
print("ALL RENDER OK")
