from app.interactive.component_detector import ComponentDetector
from app.interactive.component_models import Component
from app.interactive.component_parser import ExplicitComponentParser
from app.interactive.component_types import ComponentType


class CustomParser:
    provider = "custom"

    def can_parse(self, payload, *, provider=None):
        return provider == "custom" and payload == "custom-payload"

    def parse(self, payload, *, provider=None):
        return [Component(type=ComponentType.button, label="Continue")]


def test_explicit_component_parser_converts_generic_payload():
    parser = ExplicitComponentParser()
    payload = {
        "components": [
            {
                "id": "reply-1",
                "type": "QUICK_REPLY",
                "label": "Show properties",
                "value": "show_properties",
                "options": [{"label": "A"}, {"label": "B"}],
            }
        ]
    }

    components = parser.parse(payload, provider="rest")

    assert len(components) == 1
    assert components[0].type == ComponentType.quick_reply
    assert components[0].options[0].label == "A"


def test_component_detector_returns_result_for_explicit_payload():
    payload = {"components": [{"type": "TEXT", "label": "Greeting", "text": "Hello"}]}

    result = ComponentDetector().detect(payload, provider="rest", metadata={"turn": 1})

    assert result.success is True
    assert result.provider == "rest"
    assert result.metadata == {"turn": 1}
    assert result.component_count == 1
    assert result.components[0].text == "Hello"


def test_component_detector_uses_injected_parser():
    result = ComponentDetector(parsers=[CustomParser()]).detect("custom-payload", provider="custom")

    assert result.success is True
    assert result.components[0].type == ComponentType.button


def test_component_detector_reports_unhandled_payload():
    result = ComponentDetector(parsers=[]).detect({"message": "Hello"}, provider="unknown")

    assert result.success is False
    assert "No component parser" in result.error
