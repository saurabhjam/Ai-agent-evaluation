"""Calling-only scenario models preserving client-defined persona facts."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import Persona, TestScenario


class CallingPersona(Persona):
    model_config = ConfigDict(extra="allow")


class CallingFactConfig(BaseModel):
    """Optional voice and matching metadata for an arbitrary persona fact."""

    aliases: list[str] = Field(default_factory=list)
    spoken: str | None = None
    speak_as: Literal["natural", "digits", "characters", "email"] = "natural"
    initial_value: Any | None = None
    corrected_value: Any | None = None


class CallingSimulatorConfig(BaseModel):
    """Scenario-owned behavior policy for the simulated caller."""

    mode: Literal[
        "normal",
        "context_retention",
        "correction",
        "clarification",
        "interruption",
        "refusal",
    ] = "normal"
    opening_message: str | None = None
    opening_fields: list[str] = Field(default_factory=list)
    volunteer_fields: list[str] = Field(default_factory=list)
    refuse_fields: list[str] = Field(default_factory=list)
    fields: dict[str, CallingFactConfig] = Field(default_factory=dict)


class CallingScenario(TestScenario):
    persona: CallingPersona
    calling_simulator: CallingSimulatorConfig = Field(default_factory=CallingSimulatorConfig)
