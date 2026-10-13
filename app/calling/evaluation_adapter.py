"""Adapter isolating calling runtime from the existing EvaluationService."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.evaluation_service import EvaluationResult, EvaluationService
from app.executor import ExecutionResult
from app.schemas import TestScenario


@dataclass
class CallingEvaluationAdapter:
    """Invokes the existing evaluation service for calling results."""

    evaluation_service: EvaluationService = field(default_factory=EvaluationService)

    def evaluate(self, execution_result: ExecutionResult, scenario: TestScenario) -> EvaluationResult:
        """Delegate evaluation to the existing service."""
        return self.evaluation_service.evaluate(execution_result, scenario)
