"""Adapter isolating calling runtime from the existing EvaluationService."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.evaluation_service import EvaluationResult, EvaluationService
from app.executor import ExecutionResult
from app.schemas import TestScenario
from app.calling.semantic_values import calling_evidence_instructions
from app.calling.workflow_evidence import build_workflow_evidence, workflow_instructions


@dataclass
class CallingEvaluationAdapter:
    """Invokes the existing evaluation service for calling results."""

    evaluation_service: EvaluationService = field(default_factory=EvaluationService)

    def evaluate(self, execution_result: ExecutionResult, scenario: TestScenario) -> EvaluationResult:
        """Delegate with calling-only deterministic evidence added to judge context."""
        if not execution_result.transcript:
            return self.evaluation_service.evaluate(execution_result, scenario)
        if scenario.rag_context or any(
            (message.get("rag_evidence") if isinstance(message, dict) else getattr(message, "rag_evidence", None))
            for message in execution_result.transcript
        ):
            # RAG evidence and prompts keep their existing evaluation path.
            return self.evaluation_service.evaluate(execution_result, scenario)
        instructions, evidence = calling_evidence_instructions(
            scenario.persona, execution_result.transcript or []
        )
        workflow = build_workflow_evidence(scenario, execution_result.transcript)
        role_instructions = workflow_instructions(workflow)
        persona = scenario.persona.model_copy(
            update={"goal": f"{scenario.persona.goal}{instructions}\n{role_instructions}"}
        )
        calling_scenario = scenario.model_copy(update={"persona": persona})
        annotated = []
        originals = {}
        for index, message in enumerate(execution_result.transcript or []):
            metadata = dict((message.get("metadata") if isinstance(message, dict) else getattr(message, "metadata", None)) or {})
            metadata["calling_structured_evidence"] = evidence
            metadata["calling_workflow_evidence"] = workflow
            content = message.get("content", "") if isinstance(message, dict) else message.content
            originals[index] = content
            # Shared pairwise evaluation omits the scenario goal after turn one.
            # Supply provenance-labeled context on evaluation-only copies instead.
            turn_instructions = workflow_instructions([row for row in workflow if row["turn_index"] <= index])
            turn_instructions += " Original configured scenario goal: " + scenario.persona.goal
            updates = {"metadata": metadata, "content": content + "\n[" + turn_instructions + instructions + "]"}
            annotated.append({**message, **updates} if isinstance(message, dict) else message.model_copy(update=updates))
        result = self.evaluation_service.evaluate(
            execution_result.model_copy(update={"transcript": annotated}), calling_scenario
        )
        return result.model_copy(update={"conversation": [
            turn.model_copy(update={"message": originals.get(index, turn.message)})
            for index, turn in enumerate(result.conversation)
        ]})
