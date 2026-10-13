from app.interactive.models import InteractiveElementType
from app.interactive.response_understanding import ResponseUnderstanding, TranscriptHeuristicParser


def test_metadata_options_are_normalized_vendor_neutrally():
    response = ResponseUnderstanding().normalize(
        text="Choose one",
        metadata={
            "interactive": [
                {"type": "button", "title": "Confirm", "value": "yes"},
                {"type": "suggested_reply", "label": "Cancel"},
            ]
        },
    )

    assert response.text == "Choose one"
    assert [item.label for item in response.interactive] == ["Confirm", "Cancel"]
    assert response.interactive[0].type == InteractiveElementType.button
    assert response.interactive[1].type == InteractiveElementType.suggestion_chip


def test_bullet_list_with_multiple_options_becomes_quick_replies():
    text = "Choose one\n\n• Charlie Parker\n• Harris Park\n• Show all results"

    elements = TranscriptHeuristicParser().parse(text)

    assert [item.label for item in elements] == [
        "Charlie Parker",
        "Harris Park",
        "Show all results",
    ]
    assert all(item.type == InteractiveElementType.quick_reply for item in elements)


def test_single_bullet_is_not_treated_as_interactive():
    assert TranscriptHeuristicParser().parse("Note:\n- bring an ID") == []


def test_upload_request_is_detected_conservatively():
    elements = TranscriptHeuristicParser().parse("Please upload a photo of the damage.")

    assert len(elements) == 1
    assert elements[0].type == InteractiveElementType.upload_request
