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
        
        with open("scenarios/simple_greeting.yaml", "r") as f:
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

    # 2. VOICE E2E
    print("\n--- 2. VOICE E2E ---")
    try:
        voice_conn = AgentConnection(
            id="voice_01",
            name="Test Voice",
            type="voice",
            adapter="livekit",
            config={
                "server_url": os.getenv("LIVEKIT_URL", "wss://fake"),
                "api_key": os.getenv("LIVEKIT_API_KEY", "key"),
                "api_secret": os.getenv("LIVEKIT_API_SECRET", "secret")
            }
        )
        print("Connection: PASS")
        
        with open("scenarios/voice/refund_request_local.yaml", "r") as f:
            v_scen_data = yaml.safe_load(f)
        
        v_scen_data["scenario_id"] = v_scen_data.get("scenario", {}).get("name", "test_voice")
        v_scen_data["agent"] = AgentConfig(channel="voice", adapter="livekit", config=voice_conn.config)
        
        voice_scenario = TestScenario(**v_scen_data)
        print("Scenario: PASS")
        
        voice_exec_res = executor.execute(voice_conn, voice_scenario)
        if voice_exec_res.success:
            print("Execution: PASS")
            print("ExecutionResult: PASS")
        else:
            print(f"Execution: FAIL - {voice_exec_res.error}")
            
        voice_eval_res = eval_service.evaluate(voice_exec_res, voice_scenario)
        if voice_eval_res.success:
            print("EvaluationService: PASS")
            print("DeepEval: PASS")
            if voice_eval_res.voice_metrics:
                print("Voice Metrics: PASS")
            else:
                print("Voice Metrics: FAIL (Missing)")
            print(f"Final Result: {'PASS' if voice_eval_res.passed else 'FAIL'} (Score: {voice_eval_res.overall_score})")
        else:
            print(f"EvaluationService: FAIL - {voice_eval_res.error}")

    except Exception as e:
        print(f"Voice failed: {e}")

if __name__ == '__main__':
    main()
