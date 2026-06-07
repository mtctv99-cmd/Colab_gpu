import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.connection import ConnectionManager

@pytest.mark.asyncio
async def test_connect_worker():
    manager = ConnectionManager()
    ws = AsyncMock()
    email = "worker1@gmail.com"

    await manager.connect(email, ws)

    assert email in manager.active_connections
    assert manager.worker_status[email] == "IDLE"
    ws.accept.assert_called_once()

def test_disconnect_worker():
    manager = ConnectionManager()
    email = "worker1@gmail.com"
    manager.active_connections[email] = MagicMock()
    manager.worker_status[email] = "IDLE"

    manager.disconnect(email)

    assert email not in manager.active_connections
    assert email not in manager.worker_status

def test_get_idle_worker_none():
    manager = ConnectionManager()
    assert manager.get_idle_worker() is None

def test_get_idle_worker_round_robin():
    manager = ConnectionManager()
    manager.worker_status = {
        "w1@gmail.com": "IDLE",
        "w2@gmail.com": "IDLE",
        "w3@gmail.com": "BUSY"
    }

    # First call
    worker1 = manager.get_idle_worker()
    assert worker1 == "w1@gmail.com"

    # Second call
    worker2 = manager.get_idle_worker()
    assert worker2 == "w2@gmail.com"

    # Third call (wraps back to start of idle list)
    worker3 = manager.get_idle_worker()
    assert worker3 == "w1@gmail.com"

@pytest.mark.asyncio
async def test_send_task():
    manager = ConnectionManager()
    ws = AsyncMock()
    email = "worker1@gmail.com"
    manager.active_connections[email] = ws
    manager.worker_status[email] = "IDLE"

    task_data = {"task_id": "123", "text": "hello"}
    success = await manager.send_task(email, task_data)

    assert success is True
    assert manager.worker_status[email] == "BUSY"
    ws.send_json.assert_called_once_with(task_data)

@pytest.mark.asyncio
async def test_send_task_no_connection():
    manager = ConnectionManager()
    email = "worker1@gmail.com"

    success = await manager.send_task(email, {"foo": "bar"})
    assert success is False
