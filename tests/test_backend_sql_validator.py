from sqlalchemy import create_engine, text

from app.backend_validation import BackendValidationEngine
from app.schemas import AgentConfig, Persona, TestScenario


def _scenario(config=None):
    return TestScenario(
        scenario_id="backend-validation-sql",
        agent=AgentConfig(channel="chatbot", adapter="rest", config=config or {}),
        persona=Persona(name="Rahul", goal="Complete a support request", tone="polite"),
    )


def _sqlite_db(tmp_path):
    db_path = tmp_path / "validation.db"
    connection_string = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(connection_string)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE appointments ("
                "id TEXT PRIMARY KEY, status TEXT, customer TEXT, amount INTEGER)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO appointments (id, status, customer, amount) "
                "VALUES ('A-4421', 'CONFIRMED', 'Rahul Sharma', 150)"
            )
        )
    return connection_string


def test_sql_validator_executes_query_and_reuses_assertion_engine(tmp_path):
    connection_string = _sqlite_db(tmp_path)
    scenario = _scenario(
        {
            "backend_validation": [
                {
                    "name": "Verify Appointment",
                    "type": "sql",
                    "connection": {
                        "driver": "sqlite",
                        "connection_string": connection_string,
                    },
                    "query": "SELECT * FROM appointments WHERE id='A-4421'",
                    "expect": {
                        "$.status": {"equals": "CONFIRMED"},
                        "$.amount": {"greater_than": 0},
                    },
                }
            ]
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "PASS"
    assert result.passed is True
    assert result.checks[0].evidence["driver"] == "sqlite"
    assert result.checks[0].evidence["row_count"] == 1
    assert result.checks[-1].evidence["assertion"]["operator"] == "greater_than"


def test_sql_validator_reuses_variable_extraction_for_query_and_expect(tmp_path):
    connection_string = _sqlite_db(tmp_path)
    transcript = [
        {"role": "agent", "content": "Appointment ID: A-4421"},
        {"role": "user", "content": "My name is Rahul Sharma."},
    ]
    scenario = _scenario(
        {
            "backend_validation": [
                {
                    "name": "Verify Appointment",
                    "type": "sql",
                    "variables": {
                        "appointment_id": {"regex": r"Appointment ID:\s*(A-\d+)"},
                        "customer_name": {
                            "speaker": "user",
                            "regex": r"My name is ([A-Za-z ]+)\.",
                        },
                    },
                    "connection": {
                        "driver": "sqlite",
                        "connection_string": connection_string,
                    },
                    "query": "SELECT * FROM appointments WHERE id='{{appointment_id}}'",
                    "expect": {
                        "$.status": {"equals": "CONFIRMED"},
                        "$.customer": {"equals": "{{customer_name}}"},
                    },
                }
            ]
        }
    )

    result = BackendValidationEngine().validate(transcript, scenario)

    assert result.status == "PASS"
    assert result.checks[0].evidence["extracted_variables"] == {
        "appointment_id": "A-4421",
        "customer_name": "Rahul Sharma",
    }


def test_sql_validator_reports_failed_assertion(tmp_path):
    connection_string = _sqlite_db(tmp_path)
    scenario = _scenario(
        {
            "backend_validation": {
                "name": "Verify Appointment",
                "type": "sql",
                "connection": {
                    "driver": "sqlite",
                    "connection_string": connection_string,
                },
                "query": "SELECT * FROM appointments WHERE id='A-4421'",
                "expect": {"$.status": {"equals": "CANCELLED"}},
            }
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "FAIL"
    assert result.passed is False
    assert result.checks[-1].expected == "CANCELLED"
    assert result.checks[-1].actual == "CONFIRMED"


def test_sql_validator_handles_database_errors(tmp_path):
    connection_string = f"sqlite:///{(tmp_path / 'missing.db').as_posix()}"
    scenario = _scenario(
        {
            "backend_validation": {
                "name": "Broken SQL",
                "type": "sql",
                "connection": {
                    "driver": "sqlite",
                    "connection_string": connection_string,
                },
                "query": "SELECT * FROM missing_table",
            }
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "ERROR"
    assert result.passed is False
    assert result.checks[0].evidence["driver"] == "sqlite"


def test_sql_validator_skips_missing_configuration():
    scenario = _scenario(
        {
            "backend_validation": {
                "name": "Incomplete SQL",
                "type": "sql",
                "connection": {"driver": "sqlite"},
            }
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "SKIPPED"
    assert result.passed is None


def test_sql_validator_uses_connection_level_sql_config(tmp_path):
    connection_string = _sqlite_db(tmp_path)
    scenario = _scenario(
        {
            "backend_validation": [
                {
                    "name": "Verify Appointment",
                    "backend": "sqlite-prod",
                    "type": "sql",
                    "query": "SELECT * FROM appointments WHERE id='A-4421'",
                    "expect": {"$.status": {"equals": "CONFIRMED"}},
                }
            ],
            "backend_validation_connections": {
                "enabled": True,
                "connections": [
                    {
                        "id": "sqlite-prod",
                        "name": "Production SQLite",
                        "type": "sql",
                        "driver": "sqlite",
                        "connection_string": connection_string,
                    }
                ],
            },
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "PASS"
    assert result.checks[0].evidence["backend_connection"]["name"] == "Production SQLite"
