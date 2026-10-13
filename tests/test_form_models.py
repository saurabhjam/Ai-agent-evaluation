import pytest

from app.interactive.field_models import Field
from app.interactive.field_types import FieldType
from app.interactive.form_models import UniversalForm
from app.interactive.form_result import FormResult
from app.interactive.form_state import FormSubmissionState


def test_form_tracks_required_optional_completed_and_pending_fields():
    form = UniversalForm(
        id="contact",
        title="Contact",
        fields=[
            Field(id="name", type=FieldType.text, label="Name", required=True, current_value="Ava"),
            Field(id="phone", type=FieldType.phone, label="Phone", required=False),
        ],
    )

    assert [field.id for field in form.required_fields] == ["name"]
    assert [field.id for field in form.optional_fields] == ["phone"]
    assert form.completed_fields == ["name"]
    assert [field.id for field in form.pending_fields] == ["phone"]
    assert form.current_field == "phone"
    assert form.submission_state == FormSubmissionState.ready


def test_form_not_ready_when_required_field_is_pending():
    form = UniversalForm(
        title="Contact",
        fields=[Field(id="email", type=FieldType.email, label="Email", required=True)],
    )

    assert form.is_ready_to_submit is False
    assert form.submission_state == FormSubmissionState.not_ready


def test_form_requires_id_and_title():
    with pytest.raises(ValueError, match="id"):
        UniversalForm(id="", title="Contact")

    with pytest.raises(ValueError, match="title"):
        UniversalForm(title="")


def test_form_result_counts_forms():
    result = FormResult(success=True, forms=[UniversalForm(title="Contact")])

    assert result.form_count == 1
