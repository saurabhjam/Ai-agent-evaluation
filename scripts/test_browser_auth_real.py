import requests
import time
import os
import subprocess

def test_flow():
    # Start server
    proc = subprocess.Popen([r".\.venv\Scripts\uvicorn.exe", "app.main:app", "--port", "8002"])
    time.sleep(3)
    
    try:
        # 1. Start session
        response = requests.post("http://127.0.0.1:8002/connections/browser-auth/start", json={"url": "https://example.com"})
        print(response.status_code, response.text)
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        session_id = data["session_id"]
        print(f"Session started: {session_id}")
        
        # 2. Save session
        response = requests.post("http://127.0.0.1:8002/connections/browser-auth/save", json={
            "session_id": session_id,
            "connection_name": "Test Connection",
            "expected_url": "https://example.com"
        })
        print(response.status_code, response.text)
        assert response.status_code == 200
        data = response.json()
        assert "storage_state_path" in data
        print(f"Session saved at: {data['storage_state_path']}")
        
        if os.path.exists(data['storage_state_path']):
            print("Storage state file was successfully created.")
        else:
            print("Storage state file missing!")
    finally:
        proc.terminate()
        
if __name__ == "__main__":
    test_flow()
