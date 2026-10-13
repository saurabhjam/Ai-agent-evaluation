"""Public Phase 5 runner for AI Calling Agent Evaluation runtime execution."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.calling.config import CallingProviderConfig, default_mock_provider_config
from app.calling.execution_context import CallingExecutionContext
from app.calling.execution_pipeline import CallingExecutionPipeline
from app.calling.execution_result import CallingExecutionResult
from app.calling.models import CallDirection
from app.calling.voice_transport import VoiceTransportConfig
from app.calling.provider_resolver import ProviderResolver
from app.schemas import TestScenario


@dataclass
class CallingEvaluationRuntimeRunner:
    """
    Executes the calling runtime pipeline.

    This runner intentionally stops after normalized evidence. It does not call
    DeepEval or the existing EvaluationService.
    """

    provider_resolver: ProviderResolver = field(default_factory=ProviderResolver)

    def run(
        self,
        scenario: TestScenario,
        *,
        provider_config: CallingProviderConfig | None = None,
        voice_transport_config: VoiceTransportConfig | None = None,
        direction: CallDirection = CallDirection.outbound,
        to: str = "+15550000002",
        from_: str = "+15550000001",
        test_transport_config: VoiceTransportConfig | None = None,
    ) -> CallingExecutionResult:
        """Execute one calling scenario through the configured provider pipeline."""
        config = provider_config or default_mock_provider_config()
        context = CallingExecutionContext(
            scenario=scenario,
            provider_config=config,
            voice_transport_config=voice_transport_config or test_transport_config,
            provider=config.provider_name,
        )
        pipeline = CallingExecutionPipeline(provider_resolver=self.provider_resolver)
        return pipeline.execute(context, direction=direction, to=to, from_=from_)
