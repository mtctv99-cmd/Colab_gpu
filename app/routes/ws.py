import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.connection import manager

logger = logging.getLogger(__name__)
router = APIRouter()

@router.websocket("/ws/{email}")
async def websocket_endpoint(websocket: WebSocket, email: str):
    await manager.connect(email, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")

            if msg_type == "heartbeat":
                await websocket.send_json({"type": "heartbeat_ack"})
            elif msg_type == "task_result":
                task_id = msg.get("task_id")
                status = msg.get("status")
                payload = msg.get("payload", {})
                logger.info(f"Task {task_id} completed with status {status}")
                manager.worker_status[email] = "IDLE"
                # TODO: store result in DB
            else:
                await websocket.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})
    except WebSocketDisconnect:
        manager.disconnect(email)
        logger.info(f"Worker {email} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error for {email}: {e}")
        manager.disconnect(email)
