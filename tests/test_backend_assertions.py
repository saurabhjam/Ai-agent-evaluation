from app.backend_validation.assertions import AssertionEngine


def _result(expectations, data=None):
    data = data or {
        "status": "OPEN",
        "priority": "HIGH",
        "customer": {"id": "C-1", "email": "rahul@example.com"},
        "items": [{"price": 42}, {"price": 8}],
        "amount": 50,
        "tags": ["urgent", "maintenance"],
        "metadata": {"completed": True},
    }
    return AssertionEngine().evaluate(data, expectations)[0]


def test_assertion_equals_backward_compatible():
    result = _result({"status": "OPEN"})

    assert result.status == "PASS"
    assert result.operator == "equals"
    assert result.jsonpath == "$.status"


def test_assertion_not_equals():
    assert _result({"status": {"not_equals": "CLOSED"}}).status == "PASS"


def test_assertion_contains():
    assert _result({"customer.email": {"contains": "@"}}).status == "PASS"
    assert _result({"tags": {"contains": "urgent"}}).status == "PASS"


def test_assertion_starts_and_ends_with():
    assert _result({"customer.id": {"starts_with": "C-"}}).status == "PASS"
    assert _result({"customer.email": {"ends_with": ".com"}}).status == "PASS"


def test_assertion_exists_and_not_exists():
    assert _result({"metadata.completed": {"exists": True}}).status == "PASS"
    assert _result({"metadata.cancelled": {"not_exists": True}}).status == "PASS"


def test_assertion_comparison_operators():
    assert _result({"amount": {"greater_than": 0}}).status == "PASS"
    assert _result({"amount": {"greater_than_or_equal": 50}}).status == "PASS"
    assert _result({"amount": {"less_than": 100}}).status == "PASS"
    assert _result({"amount": {"less_than_or_equal": 50}}).status == "PASS"


def test_assertion_in_and_not_in():
    assert _result({"priority": {"in": ["HIGH", "CRITICAL"]}}).status == "PASS"
    assert _result({"priority": {"not_in": ["LOW", "MEDIUM"]}}).status == "PASS"


def test_assertion_length():
    assert _result({"items": {"length": 2}}).status == "PASS"


def test_assertion_regex():
    assert _result({"customer.email": {"regex": r"^[^@]+@[^@]+$"}}).status == "PASS"


def test_assertion_nested_json_and_arrays():
    result = _result({"$.items[0].price": {"equals": 42}})

    assert result.status == "PASS"
    assert result.actual == 42


def test_assertion_missing_field_fails_except_not_exists():
    result = _result({"missing.value": {"equals": "x"}})

    assert result.status == "FAIL"
    assert result.actual is None


def test_assertion_invalid_jsonpath_is_skipped():
    result = _result({"$..bad": {"equals": "x"}})

    assert result.status == "SKIPPED"
    assert result.passed is None
