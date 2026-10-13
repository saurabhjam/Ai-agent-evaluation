from app.schemas import MetricResult
from app.orchestrator import _normalize_score
import logging

logging.basicConfig(level=logging.INFO)

metrics = [
    MetricResult(name="Goal Completion", score=0.6, reason="", passed=True),
    MetricResult(name="Persona and Tone Adherence", score=1.0, reason="", passed=True),
    MetricResult(name="Conversational Quality", score=0.8, reason="", passed=True),
    MetricResult(name="Hallucination", score=1.0, reason="", passed=True),
]

overall_score = round(sum(_normalize_score(m) for m in metrics) / len(metrics), 3)
print("Calculated overall:", overall_score)
