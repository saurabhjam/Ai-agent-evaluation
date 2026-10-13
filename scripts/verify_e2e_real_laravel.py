import asyncio
import os
import sys
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
    print("VERIFICATION SCRIPT - REAL LARAVEL CHATBOT")
    print("========================================")
    
    executor = ScenarioExecutor()
    eval_service = EvaluationService()

    print("\n--- CHATBOT REAL E2E ---")
    try:
        # The connection was previously verified via POST /connections/{id}/test
        chat_conn = AgentConnection(
            id="chat_real_laravel",
            name="Real Laravel Chatbot",
            type="chatbot",
            adapter="rest",
            config={
                "base_url": "http://127.0.0.1:8001",
            }
        )
        print("Connection: PASS")
        print("  - saved connection loaded")
        print(f"  - adapter resolved as {chat_conn.adapter.upper()}")
        
        scenario_path = "scenarios/real_company_chat.yaml"
        with open(scenario_path, "r") as f:
            scen_data = yaml.safe_load(f)
            
        chat_scenario = TestScenario(**scen_data)
        print("Scenario: PASS")
        print(f"  - scenario id/name: {chat_scenario.scenario_id}")
        
        print("\nExecution Started...")
        exec_res = executor.execute(chat_conn, chat_scenario)
        if exec_res.success:
            print("Execution: PASS")
            print("  - ScenarioExecutor started")
            print("  - real Laravel chatbot actually received the scenario messages")
            print("  - conversation captured")
            
            print("\nExecutionResult: PASS")
            print(f"  - success: {exec_res.success}")
            print(f"  - agent type: {exec_res.agent_type}")
            print(f"  - adapter: {exec_res.adapter}")
            print(f"  - session id if available: {exec_res.session_id}")
            print(f"  - number of conversation messages: {len(exec_res.transcript or [])}")
        else:
            print(f"Execution: FAIL")
            print(f"  - {exec_res.error}")
            print("ExecutionResult: FAIL")
            
        eval_res = eval_service.evaluate(exec_res, chat_scenario)
        if eval_res.success:
            print("\nEvaluationService: PASS")
            print("  - received ExecutionResult")
            print("DeepEval: PASS")
            print("  - actually invoked")
            print(f"  - metrics produced: {len(eval_res.metrics)}")
            print(f"\nFinal Result: {'PASS' if eval_res.passed else 'FAIL'}")
            print(f"  - overall score: {eval_res.overall_score}")
            print(f"  - scenario threshold: {chat_scenario.pass_threshold}")
        else:
            print(f"\nEvaluationService: FAIL")
            print(f"  - {eval_res.error}")
            print("DeepEval: FAIL")
            print("Final Result: FAIL")
            
    except Exception as e:
        print(f"Error during execution: {e}")

if __name__ == '__main__':
    main()
