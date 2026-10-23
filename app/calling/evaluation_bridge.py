"""Bridge from calling runtime results to the existing evaluation pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.calling.calling_result_converter import CallingResultConverter
from app.calling.evaluation_adapter import CallingEvaluationAdapter
from app.calling.evaluation_context import CallingEvaluationContext
from app.calling.execution_result import CallingExecutionResult
from app.calling.failure_analysis import CallingFailureAnalyzer
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
    failure_analyzer: CallingFailureAnalyzer = field(default_factory=CallingFailureAnalyzer)

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
        if calling_result.normalized_conversation is not None:
            self.build_context(calling_result, scenario)
        execution_result = self.converter.to_execution_result(calling_result)
        evaluation = self.adapter.evaluate(execution_result, scenario)
        if not evaluation.success:
            return evaluation
        source_messages = {
            message.turn_index: message
            for message in (calling_result.normalized_conversation.messages if calling_result.normalized_conversation else [])
        }
        conversation = []
        for turn in evaluation.conversation:
            if str((turn.metadata or {}).get("speaker") or "").lower() == "system":
                continue
            source = source_messages.get(turn.turn_index)
            metadata = dict(turn.metadata or {})
            if source is not None and source.timestamp is not None:
                metadata["timestamp"] = source.timestamp
            conversation.append(turn.model_copy(update={"metadata": metadata or None}))
        evaluation = evaluation.model_copy(update={"conversation": conversation})
        return evaluation.model_copy(update={
            "failure_analysis": self.failure_analyzer.analyze(evaluation, calling_result) or None,
        })
