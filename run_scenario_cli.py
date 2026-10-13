"""
Usage:
    python run_scenario_cli.py scenarios/refund_request.yaml

Loads a YAML scenario file, POSTs it to the running FastAPI instance
(validated by TestRunRequest), and pretty-prints the transcript + scores.
"""

import argparse
import json
import sys
import requests
import yaml

API_URL = "http://localhost:8001/test-runs"

def main(path: str, adapter: str | None = None, connection_id: str | None = None):
    with open(path) as f:
        scenario = yaml.safe_load(f)

    if connection_id:
        url = f"http://localhost:8001/connections/{connection_id}/evaluate"
        payload = {"scenario_path": path}
    else:
        url = "http://localhost:8001/test-runs"
        payload = {"scenario": scenario}
        if adapter:
            payload["agent_override"] = {"adapter": adapter}

    response = requests.post(url, json=payload, timeout=600)

    if response.status_code != 200:
        print(f"Request failed [{response.status_code}]:")
        print(json.dumps(response.json(), indent=2))
        sys.exit(1)

    result = response.json()

    print(f"\n=== Run {result.get('run_id')} — {result.get('scenario_id')} ===\n")
    
    if not result.get("success") and result.get("error"):
        print(f"ERROR: {result.get('error')}\n")
    for turn in result.get("transcript", []):
        speaker = "USER " if turn.get("role") == "simulated_user" else "AGENT"
        content = turn.get("content", "").encode('cp1252', errors='replace').decode('cp1252')
        print(f"[{speaker}] {content}")

    print("\n--- Metrics ---")
    for m in result["metrics"]:
        status = "PASS" if m["passed"] else "FAIL"
        print(f"{m['name']}: {m['score']} [{status}] — {m['reason']}")

    print(f"\nOverall score: {result['overall_score']}  ->  {'PASS' if result['passed'] else 'FAIL'}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a scenario against the chatbot")
    parser.add_argument("scenario", help="Path to scenario.yaml")
    parser.add_argument("--adapter", help="Legacy: Adapter to use (e.g. 'fake', 'rest')", default=None)
    parser.add_argument("--connection-id", help="Execute against a saved AgentConnection ID", default=None)
    args = parser.parse_args()
    
    main(args.scenario, adapter=args.adapter, connection_id=args.connection_id)

