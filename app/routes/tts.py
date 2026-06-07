from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import Task, Voice
from app.services.connection import manager
import uuid
import asyncio

router = APIRouter()

class TTSRequest(BaseModel):
    text: str
    voice_id: int
    language: str = "vi"

@router.post("/tts")
async def create_tts_task(request: TTSRequest, db: AsyncSession = Depends(get_db)):
    # 1. Check voice
    voice = await db.get(Voice, request.voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found")

    # 2. Get idle worker
    worker_email = manager.get_idle_worker()
    if not worker_email:
        raise HTTPException(status_code=503, detail="No idle workers available")

    # 3. Create task in DB
    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        text=request.text,
        voice_id=request.voice_id,
        status="PROCESSING",
        worker_email=worker_email
    )
    db.add(task)
    await db.commit()

    # 4. Dispatch to worker via WebSocket
    task_data = {
        "action": "run_tts",
        "task_id": task_id,
        "text": request.text,
        "voice_api_url": f"/api/voices/{request.voice_id}/audio",
        "language": request.language
    }

    success = await manager.send_task(worker_email, task_data)
    if not success:
        task.status = "FAILED"
        task.error = "Worker disconnected during dispatch"
        await db.commit()
        raise HTTPException(status_code=500, detail="Failed to send task to worker")

    return {"task_id": task_id, "status": "sent", "worker": worker_email}
