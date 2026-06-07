import logging
from typing import Dict, List, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {} # email -> ws
        self.worker_status: Dict[str, str] = {} # email -> status (IDLE/BUSY)
        self._round_robin_index = 0

    async def connect(self, email: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[email] = websocket
        self.worker_status[email] = "IDLE"

    def disconnect(self, email: str):
        self.active_connections.pop(email, None)
        self.worker_status.pop(email, None)

    def get_idle_worker(self) -> Optional[str]:
        idle_workers = sorted([e for e, s in self.worker_status.items() if s == "IDLE"])
        if not idle_workers:
            return None

        # Simple Round Robin
        if self._round_robin_index >= len(idle_workers):
            self._round_robin_index = 0

        worker = idle_workers[self._round_robin_index]
        self._round_robin_index = (self._round_robin_index + 1) % len(idle_workers)
        return worker

    async def send_task(self, email: str, task_data: dict):
        ws = self.active_connections.get(email)
        if ws:
            try:
                await ws.send_json(task_data)
                self.worker_status[email] = "BUSY"
                return True
            except Exception as e:
                logger.error(f"Error sending task to {email}: {e}")
                self.disconnect(email)
                return False
        return False

manager = ConnectionManager()
