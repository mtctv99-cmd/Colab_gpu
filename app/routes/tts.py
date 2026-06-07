from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from app.services.connection import manager
import uuid
import asyncio

router = APIRouter()

class TTSRequest(BaseModel):
    text: str
    language: str = "vi"
    speed: float = 1.0

@router.post("/tts")
async def create_tts_task(request: TTSRequest):
    worker_email = manager.get_idle_worker()
    if not worker_email:
        raise HTTPException(status_code=503, detail="No idle workers available")

    task_id = str(uuid.uuid4())
    task_data = {
        "task_id": task_id,
        "type": "tts",
        "payload": request.model_dump()
    }

    success = await manager.send_task(worker_email, task_data)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send task to worker")

    return {"task_id": task_id, "status": "sent", "worker": worker_email}
