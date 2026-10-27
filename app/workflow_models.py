"""Provider-neutral workflow definitions and executable-case metadata."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CaseType = Literal["positive", "negative", "edge"]


class TestCaseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    type: CaseType
    version: str | None = Field(default=None, max_length=80)


class RequiredCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    positive: int = Field(default=3, ge=3)
    negative: int = Field(default=3, ge=3)
    edge: int = Field(default=2, ge=2)


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1200)
    coverage: RequiredCoverage = Field(default_factory=RequiredCoverage)
    # Only explicit canonical keys associate unrun authored cases with an agent.
    agent_keys: list[str] = Field(default_factory=list)


class ScenarioMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: str | None = None
    workflow_name: str | None = None
    test_case_id: str
    test_case_type: CaseType | None = None
    test_case_version: str | None = None
    scenario_hash: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
