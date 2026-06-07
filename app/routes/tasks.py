import os
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from app.config import RESULTS_DIR, VOICES_DIR
from app.database import async_session
from app.models import Task, Voice
from datetime import datetime, timezone
from app.services.connection import manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Tasks & Voices"])

@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: str, audio: UploadFile = File(...)):
    """Worker upload file audio kết quả."""
    file_path = RESULTS_DIR / f"{task_id}.wav"

    try:
        content = await audio.read()
        with open(file_path, "wb") as f:
            f.write(content)

        async with async_session() as db:
            task = await db.get(Task, task_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")

            task.status = "COMPLETED"
            task.result_path = f"/results/{task_id}.wav"
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()

        logger.info(f"Task {task_id} completed and audio saved.")
        return {"status": "ok", "url": task.result_path}
    except Exception as e:
        logger.error(f"Failed to complete task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/voices/{voice_id}/audio")
async def get_voice_audio(voice_id: int):
    """Worker download reference audio để chạy TTS."""
    async with async_session() as db:
        voice = await db.get(Voice, voice_id)
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")

        if not os.path.exists(voice.audio_path):
            raise HTTPException(status_code=404, detail="Audio file not found on server")

        return FileResponse(voice.audio_path, media_type="audio/wav")
