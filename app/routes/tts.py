"""New dedicated TTS API routes for text and batch processing."""

import uuid
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Task, Voice
from app.routes.ws import manager, _pending_direct_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["tts"])


class TTSTextRequest(BaseModel):
    text: str
    voice_id: int
    language: str = "vi"

    @field_validator("text")
    @classmethod
    def validate_text_length(cls, v: str):
        word_count = len(v.split())
        if word_count > 2000:
            raise ValueError(f"Text too long: {word_count} words. Max is 2000 words.")
        return v


class TTSBatchRequest(BaseModel):
    voice_id: int
    texts: List[str]
    language: str = "vi"
    batch: bool = True


@router.post("/text")
async def tts_text_direct(req: TTSTextRequest, db: AsyncSession = Depends(get_db)):
    """Convert single text to audio and return file directly (synchronous)."""
    # 1. Validate voice exists
    voice = await db.get(Voice, req.voice_id)
    if not voice:
        raise HTTPException(status_code=400, detail="Voice not found.")

    # 2. Check for active workers
    if not manager.get_idle_worker():
        if not manager.active:
            from app.routes.ws import _try_auto_rotate
            asyncio.create_task(_try_auto_rotate())
        
        # Wait for worker in direct mode
        for _ in range(75):
            await asyncio.sleep(1)
            if manager.get_idle_worker():
                break

    idle_email = manager.get_idle_worker()
    if not idle_email:
        raise HTTPException(status_code=503, detail="No idle worker available.")

    # 3. Create task
    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        text=req.text,
        voice_id=req.voice_id,
        language=req.language,
        status="PENDING",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # 4. Register event and dispatch
    event = asyncio.Event()
    _pending_direct_events[task_id] = event
    
    from app.routes.tasks import _dispatch_task
    await _dispatch_task(task, idle_email, db)
    await manager.broadcast_status({"event": "task_created", "task_id": task_id})

    # 5. Wait for result
    try:
        await asyncio.wait_for(event.wait(), timeout=120.0)
    except asyncio.TimeoutError:
        _pending_direct_events.pop(task_id, None)
        raise HTTPException(status_code=504, detail="Processing timeout.")

    await db.refresh(task)
    if task.status == "COMPLETED":
        if task.result_audio_path and os.path.exists(task.result_audio_path):
            return FileResponse(task.result_audio_path, media_type="audio/wav")
        raise HTTPException(status_code=500, detail="Audio file missing on server.")
    else:
        raise HTTPException(status_code=500, detail=f"Task failed: {task.error_message}")


@router.post("/batch")
async def tts_batch(req: TTSBatchRequest, db: AsyncSession = Depends(get_db)):
    """Create multiple TTS tasks in one request with clear mapping."""
    # 1. Validate voice exists
    voice = await db.get(Voice, req.voice_id)
    if not voice:
        raise HTTPException(status_code=400, detail="Voice not found.")
    
    if not req.texts:
        raise HTTPException(status_code=400, detail="Texts list is empty.")

    # 2. Create tasks
    created_tasks = []
    for text in req.texts:
        task_id = str(uuid.uuid4())
        task = Task(
            id=task_id,
            text=text,
            voice_id=req.voice_id,
            language=req.language,
            status="PENDING",
        )
        db.add(task)
        created_tasks.append(task)
    
    await db.commit()

    # 3. Trigger auto-rotate / scale
    if not manager.active:
        from app.routes.ws import _try_auto_rotate
        asyncio.create_task(_try_auto_rotate())
    else:
        from app.routes.ws import _maybe_scale_up
        asyncio.create_task(_maybe_scale_up())

    # 4. Attempt immediate dispatch and build response mapping
    from app.routes.tasks import _dispatch_task
    response_tasks = []
    
    for i, task in enumerate(created_tasks):
        await db.refresh(task)
        idle_email = manager.get_idle_worker()
        if idle_email:
            await _dispatch_task(task, idle_email, db)
        
        await manager.broadcast_status({"event": "task_created", "task_id": task.id})
        
        response_tasks.append({
            "text": req.texts[i],
            "task_id": task.id,
            "status": task.status
        })

    # Trigger scale-up again after batch insertion
    from app.routes.ws import _maybe_scale_up
    asyncio.create_task(_maybe_scale_up())

    return {
        "batch": True,
        "tasks": response_tasks
    }
