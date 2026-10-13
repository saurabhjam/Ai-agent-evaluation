from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_browser_auth_flow():
    # 1. Start session
    response = client.post("/connections/browser-auth/start", json={"url": "https://example.com"})
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    session_id = data["session_id"]
    print(f"Session started: {session_id}")
    
    # 2. Save session
    response = client.post("/connections/browser-auth/save", json={
        "session_id": session_id,
        "connection_name": "Test Connection",
        "expected_url": "https://example.com"
    })
    assert response.status_code == 200
    data = response.json()
    assert "storage_state_path" in data
    print(f"Session saved at: {data['storage_state_path']}")
    
    import os
    if os.path.exists(data['storage_state_path']):
        print("Storage state file was successfully created.")
    else:
        print("Storage state file missing!")
        
if __name__ == "__main__":
    test_browser_auth_flow()
