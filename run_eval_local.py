import sys
import logging
import time
from app.executor import ScenarioExecutor
from app.schemas import TestScenario
from app.connections.storage import repository
from app.models.connection import AgentConnection
import yaml

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

conn = AgentConnection(
    id="test-123",
    name="Test",
    type="chatbot",
    adapter="rest",
    config={}
)
repository.save(conn)

with open("scenarios/real_company_chat.yaml", "r") as f:
    scenario_data = yaml.safe_load(f)
scenario = TestScenario(**scenario_data)

executor = ScenarioExecutor()
res = executor.execute(conn, scenario)
print("Result:", res)
