"""Bridge from calling runtime results to the existing evaluation pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.calling.calling_result_converter import CallingResultConverter
from app.calling.evaluation_adapter import CallingEvaluationAdapter
from app.calling.evaluation_context import CallingEvaluationContext
from app.calling.execution_result import CallingExecutionResult
from app.evaluation_service import EvaluationResult
from app.schemas import TestScenario


@dataclass
class CallingEvaluationBridge:
    """
    Connects calling execution results to the existing EvaluationService.

    This bridge performs no metric calculation and imports no DeepEval logic.
    """

    converter: CallingResultConverter = field(default_factory=CallingResultConverter)
    adapter: CallingEvaluationAdapter = field(default_factory=CallingEvaluationAdapter)

    def build_context(
        self,
        calling_result: CallingExecutionResult,
        scenario: TestScenario,
    ) -> CallingEvaluationContext:
        """Build the bridge context for inspection, logging, or future reporting."""
        return self.converter.to_evaluation_context(
            calling_result,
            scenario_id=scenario.scenario_id,
        )

    def evaluate(
        self,
        calling_result: CallingExecutionResult,
        scenario: TestScenario,
    ) -> EvaluationResult:
        """Convert a calling result and invoke the existing evaluation service."""
        if calling_result.normalized_conversation is None:
            execution_result = self.converter.to_execution_result(calling_result)
            return self.adapter.evaluate(execution_result, scenario)
        self.build_context(calling_result, scenario)
        execution_result = self.converter.to_execution_result(calling_result)
        return self.adapter.evaluate(execution_result, scenario)
