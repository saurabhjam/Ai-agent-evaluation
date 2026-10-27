from app.calling.semantic_values import calling_evidence_instructions, compare_structured_value


def test_calling_structured_equivalences():
    assert compare_structured_value("phone_number", "9876543210", "9. 876543210").semantic_match is True
    assert compare_structured_value("preferred_time", "400 PM", "4:00 PM").semantic_match is True
    assert compare_structured_value("preferred_date", "October 20. 2026", "October 20, 2026").semantic_match is True


def test_calling_structured_real_mismatches():
    assert compare_structured_value("phone_number", "9876543210", "9876543211").semantic_match is False
    assert compare_structured_value("preferred_time", "4:00 PM", "5:00 PM").semantic_match is False
    assert compare_structured_value("preferred_date", "October 20", "October 21").semantic_match is False


def test_calling_evidence_constrains_workflow_and_equivalent_values():
    persona = {
        "name": "Rahul Sharma", "goal": "Book an appointment", "tone": "brief",
        "phone_number": "9876543210", "preferred_time": "400 PM",
    }
    transcript = [
        {"content": "9. 876543210"},
        {"content": "Thank you. What date would you prefer?"},
        {"content": "Your appointment is at 4:00 PM."},
    ]
    instructions, evidence = calling_evidence_instructions(persona, transcript)

    assert "valid progression" in instructions
    assert any(item["field"] == "phone_number" and item["semantic_match"] is True for item in evidence)
    assert any(item["field"] == "preferred_time" and item["semantic_match"] is True for item in evidence)
