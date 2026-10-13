import asyncio
import json
from app.executor import ScenarioExecutor
from app.models.connection import AgentConnection, AgentType
from app.schemas import TestScenario, Persona, AgentConfig
import os

async def run_smoke_test():
    # Load Sophia configuration
    conn = AgentConnection(
        id="sophia-rest",
        name="Sophia AI (REST)",
        type=AgentType.chatbot,
        adapter="rest",
        enabled=True,
        config={
            "endpoint": "https://tribe-gateway.archietech.co/owners/api/v1/admin/sophia/ask",
            "method": "POST",
            "storage_state": "auth-state-Sophia_AI.json",
            "auth": {
                "type": "browser_token",
                "url": "https://dev.pms.jointribex.com/sophia",
                "intercept_pattern": "*/owners/api/v1/admin/*",
                "token_path": "header:authorization",
                "header_name": "Authorization",
                "header_format": "Bearer {token}"
            },
            "request_mapping": {
                "message_field": "question",
                "session_id_field": "conversation_id",
                "static_fields": {
                    "scope": "portfolio",
                    "module_context": "portfolio"
                }
            },
            "response_mapping": {
                "reply_field": "answer"
            }
        }
    )
    
    scenario = TestScenario(
        scenario_id="smoke_test",
        agent=AgentConfig(channel="chatbot", adapter="rest", config=conn.config),
        persona=Persona(name="tester", system_prompt="Just say 'Hello Sophia'.", goal="Greet Sophia", tone="neutral"),
        max_turns=2
    )
    
    print("Running smoke test execution...")
    try:
        executor = ScenarioExecutor()
        result = executor.execute(conn, scenario)
        print("SUCCESS:", result.success)
        print("TRANSCRIPT:")
        if result.transcript:
            for t in result.transcript:
                print(f"[{t.role}]: {t.content}")
        else:
            print("No transcript generated.")
    except Exception as e:
        print("ERROR:", e)

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(run_smoke_test())
