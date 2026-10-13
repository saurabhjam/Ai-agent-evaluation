from app.interactive.runtime_context import RuntimeContext


def test_runtime_context_defaults_are_safe():
    context = RuntimeContext()

    assert context.variables == {}
    assert context.metadata == {}
    assert context.provider is None


def test_runtime_context_accepts_provider_payload_and_variables():
    payload = {"components": []}
    context = RuntimeContext(provider_response=payload, provider="rest", variables={"email": "a@example.com"})

    assert context.provider_response == payload
    assert context.provider == "rest"
    assert context.variables["email"] == "a@example.com"
