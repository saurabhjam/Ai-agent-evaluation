"""Convert calling runtime results into existing evaluation inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.calling.evaluation_context import CallingEvaluationContext
from app.calling.execution_result import CallingExecutionResult
from app.executor import ExecutionResult


@dataclass(frozen=True)
class CallingResultConverter:
    """Converts calling execution results without changing EvaluationService."""

    agent_type: str = "calling"
    adapter: str = "calling"

    def to_evaluation_context(
        self,
        calling_result: CallingExecutionResult,
        *,
        scenario_id: str,
    ) -> CallingEvaluationContext:
        """Build a calling-specific evaluation context."""
        conversation = calling_result.normalized_conversation
        if conversation is None:
            raise ValueError("Calling result is missing normalized conversation.")
        call_session = calling_result.call_session
        provider = call_session.provider_name if call_session else None
        call_id = call_session.provider_call_id if call_session else None
        return CallingEvaluationContext(
            run_id=conversation.run_id,
            scenario_id=scenario_id,
            provider=provider,
            call_id=call_id,
            conversation=conversation,
            artifacts=calling_result.artifacts,
            metadata={
                **calling_result.execution_metadata,
                "duration_seconds": calling_result.duration_seconds,
                "status": calling_result.status.value,
            },
            rag_context=conversation.retrieval_context,
        )

    def to_execution_result(self, calling_result: CallingExecutionResult) -> ExecutionResult:
        """Convert to the existing app.executor.ExecutionResult model."""
        completed_at = datetime.now(timezone.utc).isoformat()
        call_session = calling_result.call_session
        conversation = calling_result.normalized_conversation
        transcript = [
            message for message in conversation.messages
            if message.role != "system"
        ] if conversation else []
        session_id = call_session.session_id if call_session else None
        provider_name = call_session.provider_name if call_session else self.adapter
        connection_id = (
            call_session.provider_call_id
            if call_session and call_session.provider_call_id
            else (session_id or "calling")
        )
        return ExecutionResult(
            success=calling_result.success,
            connection_id=connection_id,
            agent_type=self.agent_type,
            adapter=provider_name or self.adapter,
            session_id=session_id,
            transcript=transcript,
            error=calling_result.error,
            started_at=call_session.started_at if call_session and call_session.started_at else completed_at,
            completed_at=call_session.ended_at if call_session and call_session.ended_at else completed_at,
        )
