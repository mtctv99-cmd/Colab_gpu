import logging
import uuid
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, field_validator, Field, HttpUrl
from typing import Literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Voice, Task
from app.routes.ws import manager, _pending_direct_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["tts"])


# ── Request models ────────────────────────────────────────────

class TextTTSRequest(BaseModel):
    text: str
    voice_id: int
    language: str | None = None

    @field_validator("text")
    @classmethod
    def validate_word_count(cls, v: str) -> str:
        word_count = len(v.split())
        if word_count > 2000:
            raise ValueError(f"Text vượt quá giới hạn 2000 từ (hiện tại {word_count} từ).")
        return v


class BatchTTSRequest(BaseModel):
    voice_id: int
    language: str | None = None
    batch: Literal[True] = True
    texts: list[str] = Field(min_length=1, description="Danh sách text cần TTS, tối thiểu 1 phần tử.")
    webhook_url: str | None = Field(
        default=None,
        description="URL callback khi toàn bộ batch hoàn thành. Server sẽ POST kết quả về URL này."
    )


# ── POST /api/tts/text ────────────────────────────────────────

@router.post(
    "/text",
    summary="TTS một text (đồng bộ)",
    response_description="Trả về file audio WAV trực tiếp khi xử lý xong.",
)
async def tts_text(req: TextTTSRequest, db: AsyncSession = Depends(get_db)):
    """
    Chuyển đổi text thành giọng nói (tối đa 2000 từ).
    - Gọi đồng bộ: chờ đến khi có audio rồi trả về file WAV.
    - Lỗi 400: voice không tồn tại hoặc text vượt giới hạn từ.
    - Lỗi 503: không có worker rảnh.
    - Lỗi 504: worker xử lý quá thời gian (120 giây).
    """
    voice = await db.get(Voice, req.voice_id)
    if not voice:
        raise HTTPException(
            status_code=400,
            detail={"error": "voice_not_found", "message": f"Voice ID {req.voice_id} không tồn tại."}
        )

    task = Task(
        id=str(uuid.uuid4()),
        text=req.text,
        voice_id=req.voice_id,
        language=req.language,
        status="PENDING",
            batch_id=None,
            webhook_url=req.webhook_url,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # 2. Check for active workers
    if not manager.get_idle_worker():
        if not manager.active:
            from app.routes.ws import _try_auto_rotate
            asyncio.create_task(_try_auto_rotate())
        else:
            from app.routes.ws import _maybe_scale_up
            asyncio.create_task(_maybe_scale_up())
        
        # Wait for worker in direct mode
        for _ in range(75):
            await asyncio.sleep(1)
            if manager.get_idle_worker():
                break

    idle_email = manager.get_idle_worker()
    if not idle_email:
        raise HTTPException(status_code=503, detail="No idle worker available.")

    # 3. Register event and dispatch
    event = asyncio.Event()
    _pending_direct_events[task.id] = event
    
    from app.routes.tasks import _dispatch_task
    await _dispatch_task(task, idle_email, db)
    await manager.broadcast_status({"event": "task_created", "task_id": task.id})

    # 4. Wait for result
    try:
        await asyncio.wait_for(event.wait(), timeout=120.0)
    except asyncio.TimeoutError:
        _pending_direct_events.pop(task.id, None)
        raise HTTPException(status_code=504, detail="Processing timeout.")

    await db.refresh(task)
    if task.status == "COMPLETED":
        import os
        if task.result_audio_path and os.path.exists(task.result_audio_path):
            from fastapi.responses import FileResponse
            return FileResponse(task.result_audio_path, media_type="audio/wav")
        raise HTTPException(status_code=500, detail="Audio file missing on server.")
    else:
        raise HTTPException(status_code=500, detail=f"Task failed: {task.error_message}")


# ── POST /api/tts/batch ───────────────────────────────────────

@router.post(
    "/batch",
    summary="TTS nhiều text (bất đồng bộ + webhook tuỳ chọn)",
    response_description="Mapping text → task_id cho toàn bộ batch.",
)
async def tts_batch(req: BatchTTSRequest, db: AsyncSession = Depends(get_db)):
    """
    Tạo task TTS cho nhiều text cùng lúc.
    - Trả về ngay mapping text → task_id với status PENDING.
    - App thứ 3 polling từng task_id qua GET /api/tasks/{task_id}.
    - Nếu truyền webhook_url, server sẽ POST kết quả về URL đó khi toàn batch xong.
    """
    if not req.texts:
        raise HTTPException(
            status_code=400,
            detail={"error": "texts_empty", "message": "Danh sách texts không được rỗng."}
        )

    voice = await db.get(Voice, req.voice_id)
    if not voice:
        raise HTTPException(
            status_code=400,
            detail={"error": "voice_not_found", "message": f"Voice ID {req.voice_id} không tồn tại."}
        )

    created_tasks = []
    batch_id = str(uuid.uuid4())
    for text in req.texts:
        task = Task(
            id=str(uuid.uuid4()),
            text=text,
            voice_id=req.voice_id,
            language=req.language,
            status="PENDING",
            batch_id=None,
            webhook_url=req.webhook_url,
        )
        db.add(task)
        created_tasks.append(task)

    await db.commit()
    for task in created_tasks:
        await db.refresh(task)

    # 3. Trigger auto-rotate / scale for batch
    if not manager.active:
        from app.routes.ws import _try_auto_rotate
        asyncio.create_task(_try_auto_rotate())
    else:
        from app.routes.ws import _on_batch_request
        asyncio.create_task(_on_batch_request())

    # 4. Attempt immediate dispatch
    from app.routes.tasks import _dispatch_task
    for task in created_tasks:
        idle_email = manager.get_idle_worker()
        if idle_email:
            await _dispatch_task(task, idle_email, db)
        await manager.broadcast_status({"event": "task_created", "task_id": task.id})

    return {
        "batch": True,
        "voice_id": req.voice_id,
        "language": req.language,
        "webhook_url": req.webhook_url,
        "tasks": [
            {
                "text": task.text,
                "task_id": task.id,
                "status": task.status,
            }
            for task in created_tasks
        ],
    }


