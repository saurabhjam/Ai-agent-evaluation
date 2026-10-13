"""Backend validator registry."""

from __future__ import annotations

from typing import Type

from app.backend_validation.validators.base import BackendValidator
from app.backend_validation.validators.rest import RestValidator
from app.backend_validation.validators.sql import SqlValidator


class BackendValidatorRegistry:
    def __init__(self) -> None:
        self._validators: dict[str, Type[BackendValidator]] = {}

    def register(self, validator_type: str, validator_cls: Type[BackendValidator]) -> None:
        self._validators[str(validator_type).lower()] = validator_cls

    def build(self, validator_type: str, config: dict) -> BackendValidator:
        validator_cls = self._validators.get(str(validator_type or "rest").lower())
        if validator_cls is None:
            validator_cls = RestValidator
        return validator_cls(config)


backend_validator_registry = BackendValidatorRegistry()
backend_validator_registry.register("rest", RestValidator)
backend_validator_registry.register("sql", SqlValidator)
