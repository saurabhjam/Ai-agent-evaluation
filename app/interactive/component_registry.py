"""
Registry for supported chatbot UI component types.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.interactive.component_types import ComponentType, SUPPORTED_COMPONENT_TYPES


@dataclass(frozen=True)
class ComponentDefinition:
    type: ComponentType
    description: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


class ComponentRegistry:
    def __init__(self) -> None:
        self._definitions: dict[ComponentType, ComponentDefinition] = {}

    def register(self, definition: ComponentDefinition, *, overwrite: bool = False) -> None:
        component_type = definition.type if isinstance(definition.type, ComponentType) else ComponentType(definition.type)
        if component_type in self._definitions and not overwrite:
            raise ValueError(f"Component type '{component_type.value}' is already registered.")
        if component_type is not definition.type:
            definition = ComponentDefinition(
                type=component_type,
                description=definition.description,
                metadata=definition.metadata,
            )
        self._definitions[component_type] = definition

    def get(self, component_type: ComponentType | str) -> ComponentDefinition:
        normalized = component_type if isinstance(component_type, ComponentType) else ComponentType(component_type)
        if normalized not in self._definitions:
            raise KeyError(f"Component type '{normalized.value}' is not registered.")
        return self._definitions[normalized]

    def has(self, component_type: ComponentType | str) -> bool:
        try:
            normalized = component_type if isinstance(component_type, ComponentType) else ComponentType(component_type)
        except ValueError:
            return False
        return normalized in self._definitions

    def list_types(self) -> list[ComponentType]:
        return sorted(self._definitions.keys(), key=lambda item: item.value)


def default_component_registry() -> ComponentRegistry:
    registry = ComponentRegistry()
    for component_type in SUPPORTED_COMPONENT_TYPES:
        registry.register(
            ComponentDefinition(
                type=component_type,
                description=f"Universal {component_type.value} chatbot UI component.",
            )
        )
    return registry
