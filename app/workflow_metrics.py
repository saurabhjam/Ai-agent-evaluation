from typing import Any
from app.schemas import MetricResult

def run_workflow_metrics(transcript: list[Any]) -> list[MetricResult]:
    interactions = []
    for turn_index, msg in enumerate(transcript):
        metadata = None
        t_idx = turn_index
        if hasattr(msg, "metadata") and msg.metadata:
            metadata = msg.metadata
            if hasattr(msg, "turn_index"):
                t_idx = msg.turn_index
        elif isinstance(msg, dict) and msg.get("metadata"):
            metadata = msg.get("metadata")
            t_idx = msg.get("turn_index", turn_index)
            
        if metadata and isinstance(metadata, dict):
            evidence = metadata.get("interaction_evidence")
            if evidence:
                evidence["_turn_index"] = t_idx
                evidence["_conversation_message_id"] = (
                    metadata.get("conversation_message_id")
                    or metadata.get("message_id")
                    or metadata.get("id")
                    or (msg.get("conversation_message_id") if isinstance(msg, dict) else getattr(msg, "conversation_message_id", None))
                    or (msg.get("message_id") if isinstance(msg, dict) else getattr(msg, "message_id", None))
                )
                interactions.append(evidence)

    type_to_metric = {
        "form": {
            "name": "Form Completion",
            "desc": "Did the chatbot successfully collect all required form information?",
        },
        "otp": {
            "name": "OTP Verification",
            "desc": "Did the chatbot successfully verify the OTP?",
        },
        "image_upload": {
            "name": "Image Upload",
            "desc": "Did the requested image upload complete successfully?",
        },
        "camera_capture": {
            "name": "Live Camera Capture",
            "desc": "Did the evaluator capture and upload a live photo?",
        },
        "document_upload": {
            "name": "Document Upload",
            "desc": "Did the requested document upload complete successfully?",
        },
        "video_upload": {
            "name": "Video Upload",
            "desc": "Did the requested video upload complete successfully?",
        },
        "human_handoff": {
            "name": "Human Handoff",
            "desc": "Did the chatbot request handoff and evaluation complete it correctly?",
        },
        "ui_validation": {
            "name": "UI Validation",
            "desc": "Did the chatbot render the expected browser UI controls after its response?",
        }
    }
    
    metrics = []
    for i_type, config in type_to_metric.items():
        type_evidences = [ev for ev in interactions if ev.get("interaction_type") == i_type]
        if type_evidences:
            passed = all(ev.get("success", False) for ev in type_evidences)
            metrics.append(MetricResult(
                name=config["name"],
                description=config["desc"],
                score=1.0 if passed else 0.0,
                reason="Interaction succeeded." if passed else "Interaction failed or timed out.",
                passed=passed,
                threshold=1.0,
                category="Workflow",
                turn_index=type_evidences[-1].get("_turn_index"),
                conversation_message_id=type_evidences[-1].get("_conversation_message_id"),
            ))

    return metrics
