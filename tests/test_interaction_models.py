import pytest

from app.interactive.interaction_models import Interaction
from app.interactive.interaction_result import InteractionResult
from app.interactive.interaction_types import InteractionType


def test_interaction_model_normalizes_type_and_selector():
    interaction = Interaction(
        id=" search ",
        type="SEARCH_BOX",
        label=" Search listings ",
        selector="  ",
        value="apartments",
        timeout=3,
    )

    assert interaction.id == "search"
    assert interaction.type == InteractionType.search_box
    assert interaction.label == "Search listings"
    assert interaction.selector is None
    assert interaction.dispatch_value() == "apartments"


def test_interaction_requires_label_and_id():
    with pytest.raises(ValueError, match="label"):
        Interaction(type=InteractionType.button, label="")

    with pytest.raises(ValueError, match="id"):
        Interaction(id="", type=InteractionType.button, label="Continue")


def test_interaction_rejects_negative_timeout():
    with pytest.raises(ValueError, match="timeout"):
        Interaction(type=InteractionType.wait, label="Wait", timeout=-1)


def test_interaction_result_normalizes_type_and_latency():
    result = InteractionResult(success=True, interaction_type="TEXT", latency=-2)

    assert result.interaction_type == InteractionType.text
    assert result.latency == 0.0
