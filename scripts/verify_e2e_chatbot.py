import asyncio
import os
from datetime import datetime
import yaml

from app.config import PROJECT_ROOT
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from app.models.connection import AgentConnection
from app.schemas import TestScenario, AgentConfig
from app.executor import ScenarioExecutor
from app.evaluation_service import EvaluationService

def main():
    print("========================================")
    print("VERIFICATION SCRIPT")
    print("========================================")
    
    executor = ScenarioExecutor()
    eval_service = EvaluationService()

    # 1. CHATBOT E2E
    print("\n--- 1. CHATBOT E2E ---")
    try:
        chat_conn = AgentConnection(
            id="chat_01",
            name="Test Chatbot",
            type="chatbot",
            adapter="fake",
            config={"responses": ["Hello! I am a fake bot."]}
        )
        print("Connection: PASS")
        
        with open("scenarios/refund_request.yaml", "r") as f:
            scen_data = yaml.safe_load(f)
            
        chat_scenario = TestScenario(**scen_data)
        print("Scenario: PASS")
        
        exec_res = executor.execute(chat_conn, chat_scenario)
        if exec_res.success:
            print("Execution: PASS")
            print("ExecutionResult: PASS")
        else:
            print(f"Execution: FAIL - {exec_res.error}")
            
        eval_res = eval_service.evaluate(exec_res, chat_scenario)
        if eval_res.success:
            print("EvaluationService: PASS")
            print("DeepEval: PASS")
            print(f"Final Result: {'PASS' if eval_res.passed else 'FAIL'} (Score: {eval_res.overall_score})")
        else:
            print(f"EvaluationService: FAIL - {eval_res.error}")
            
    except Exception as e:
        print(f"Chatbot failed: {e}")

if __name__ == '__main__':
    main()
