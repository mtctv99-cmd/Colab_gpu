import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.connection import manager
from unittest.mock import AsyncMock, patch

client = TestClient(app)

def test_read_main():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "TTS Server is running"}

def test_tts_no_workers():
    # Clear active workers
    manager.active_connections = {}
    manager.worker_status = {}

    response = client.post("/tts", json={"text": "hello"})
    assert response.status_code == 503
    assert response.json()["detail"] == "No idle workers available"

@patch("app.routes.tts.manager.send_task", new_callable=AsyncMock)
def test_tts_success(mock_send_task):
    mock_send_task.return_value = True

    # Fake a worker
    manager.worker_status["worker@test.com"] = "IDLE"
    manager.active_connections["worker@test.com"] = AsyncMock()

    response = client.post("/tts", json={"text": "hello", "language": "vi", "speed": 1.0})

    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data
    assert data["status"] == "sent"
    assert data["worker"] == "worker@test.com"

    mock_send_task.assert_called_once()

def test_websocket_connect():
    # TestClient doesn't support full WebSocket lifecycle easily without extra libs,
    # but we can test if the endpoint exists and handles basic connection.
    with client.websocket_connect("/ws/worker@test.com") as websocket:
        # Check if worker registered
        assert "worker@test.com" in manager.active_connections
        assert manager.worker_status["worker@test.com"] == "IDLE"

        # Test heartbeat
        websocket.send_json({"type": "heartbeat"})
        data = websocket.receive_json()
        assert data == {"type": "heartbeat_ack"}

    # Check if disconnected
    assert "worker@test.com" not in manager.active_connections
