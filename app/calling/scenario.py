"""Calling-only scenario models preserving client-defined persona facts."""

from pydantic import ConfigDict

from app.schemas import Persona, TestScenario


class CallingPersona(Persona):
    model_config = ConfigDict(extra="allow")


class CallingScenario(TestScenario):
    persona: CallingPersona
