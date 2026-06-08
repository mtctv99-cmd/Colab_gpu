"""API routes for TTS task management."""

import asyncio
import re
import aiofiles
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Task, Voice
from app.config import DATA_DIR, RESULTS_DIR
from app.routes.ws import manager, _pending_direct_events

import unicodedata

def _slugify(name: str) -> str:
    """Convert voice name to safe folder name."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[^a-z0-9]+", "_", n).strip("_")
    return n or "default"

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

class CreateTaskRequest(BaseModel):
    text: str
    voice_id: int
    language: str | None = None

class CreateBatchTaskRequest(BaseModel):
    voice_id: int
    texts: list[str]
    language: str | None = None



# ── List tasks ────────────────────────────────────────────────
@router.get("/")
async def list_tasks(limit: int = 20, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Task).order_by(desc(Task.created_at)).limit(limit)
    )
    tasks = result.scalars().all()
    return [
        {
            "id": t.id,
            "text": t.text,
            "voice_id": t.voice_id,
            "language": t.language,
            "status": t.status,
            "worker_id": t.worker_id,
            "result_audio_path": t.result_audio_path,
            "error_message": t.error_message,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
        for t in tasks
    ]


# ── Create a TTS task ─────────────────────────────────────────
@router.post("/")
async def create_task(req: CreateTaskRequest, db: AsyncSession = Depends(get_db)):
    # Validate voice exists
    voice = await db.get(Voice, req.voice_id)
    if not voice:
        raise HTTPException(status_code=400, detail="Voice not found.")

    task = Task(
        id=str(uuid.uuid4()),
        text=req.text,
        voice_id=req.voice_id,
        language=req.language,
        status="PENDING",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Try to dispatch immediately to an idle worker
    idle_email = manager.get_idle_worker()
    if idle_email:
        await _dispatch_task(task, idle_email, db)
    else:
        # Nếu không có worker nào online (đang kết nối)
        if not manager.active:
            from app.routes.ws import _try_auto_rotate
            logger.info("No active workers online. Automatically starting an offline worker...")
            asyncio.create_task(_try_auto_rotate())
        else:
            from app.routes.ws import _maybe_scale_up
            asyncio.create_task(_maybe_scale_up())

    await manager.broadcast_status({"event": "task_created", "task_id": task.id})
    from app.routes.ws import _maybe_scale_up
    asyncio.create_task(_maybe_scale_up())
    return {
        "id": task.id,
        "status": task.status,
        "text": task.text,
        "voice_id": task.voice_id,
        "language": task.language,
    }


# ── Create a synchronous (direct) TTS task ────────────────────
@router.post("/direct")
async def create_task_direct(req: CreateTaskRequest, db: AsyncSession = Depends(get_db)):
    # Validate voice exists
    voice = await db.get(Voice, req.voice_id)
    if not voice:
        raise HTTPException(status_code=400, detail="Voice not found.")

    # Try to dispatch immediately to an idle worker (or auto-start if none active)
    if not manager.get_idle_worker():
        if not manager.active:
            from app.routes.ws import _try_auto_rotate
            logger.info("No active workers online for direct request. Starting one...")
            asyncio.create_task(_try_auto_rotate())
            
        # Chờ worker online và chuyển sang IDLE trong tối đa 75 giây
        logger.info("Waiting up to 75 seconds for worker to start and connect...")
        for _ in range(75):
            await asyncio.sleep(1)
            if manager.get_idle_worker():
                break

    idle_email = manager.get_idle_worker()
    if not idle_email:
        raise HTTPException(
            status_code=503, 
            detail="Không có worker Colab nào đang rảnh và kết nối. Vui lòng bật worker."
        )

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

    # Đăng ký event
    event = asyncio.Event()
    _pending_direct_events[task_id] = event

    # Dispatch task
    await _dispatch_task(task, idle_email, db)
    await manager.broadcast_status({"event": "task_created", "task_id": task.id})

    # Chờ kết quả hoặc timeout (120 giây)
    try:
        await asyncio.wait_for(event.wait(), timeout=120.0)
    except asyncio.TimeoutError:
        _pending_direct_events.pop(task_id, None)
        raise HTTPException(
            status_code=504, 
            detail="Thời gian xử lý vượt quá giới hạn (120 giây)."
        )

    # Lấy lại trạng thái task mới nhất từ DB
    await db.refresh(task)
    if task.status == "COMPLETED":
        if task.result_audio_path and os.path.exists(task.result_audio_path):
            return FileResponse(task.result_audio_path, media_type="audio/wav")
        else:
            raise HTTPException(status_code=500, detail="File kết quả không tồn tại trên server.")
    else:
        err = task.error_message or "Không xác định"
        raise HTTPException(status_code=500, detail=f"Task thất bại trên worker: {err}")


# ── Create a batch of TTS tasks ───────────────────────────────
@router.post("/batch")
async def create_tasks_batch(req: CreateBatchTaskRequest, db: AsyncSession = Depends(get_db)):
    # Validate voice exists
    voice = await db.get(Voice, req.voice_id)
    if not voice:
        raise HTTPException(status_code=400, detail="Voice not found.")

    if not req.texts:
        raise HTTPException(status_code=400, detail="Texts list cannot be empty.")

    created_tasks = []
    for text in req.texts:
        task = Task(
            id=str(uuid.uuid4()),
            text=text,
            voice_id=req.voice_id,
            language=req.language,
            status="PENDING",
        )
        db.add(task)
        created_tasks.append(task)

    await db.commit()
    
    # Check if there are no online workers at all to trigger auto-start
    if not manager.active:
        from app.routes.ws import _try_auto_rotate
        logger.info("No active workers online for batch request. Starting one...")
        asyncio.create_task(_try_auto_rotate())
    else:
        from app.routes.ws import _maybe_scale_up
        asyncio.create_task(_maybe_scale_up())
        
    # Refresh all tasks and attempt dispatch
    for task in created_tasks:
        await db.refresh(task)
        # Try to dispatch immediately to an idle worker if one exists
        idle_email = manager.get_idle_worker()
        if idle_email:
            await _dispatch_task(task, idle_email, db)
        await manager.broadcast_status({"event": "task_created", "task_id": task.id})

    from app.routes.ws import _maybe_scale_up
    asyncio.create_task(_maybe_scale_up())

    return {
        "voice_id": req.voice_id,
        "tasks": [
            {
                "id": t.id,
                "text": t.text,
                "language": t.language,
                "status": t.status
            }
            for t in created_tasks
        ]
    }


# ── Get task detail ───────────────────────────────────────────
@router.get("/{task_id}")
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {
        "id": task.id,
        "text": task.text,
        "voice_id": task.voice_id,
        "language": task.language,
        "status": task.status,
        "worker_id": task.worker_id,
        "result_audio_path": task.result_audio_path,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


# ── Download result audio ─────────────────────────────────────
@router.get("/{task_id}/audio")
async def download_result_audio(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if not task.result_audio_path or not Path(task.result_audio_path).exists():
        raise HTTPException(status_code=404, detail="Result audio not available.")
    return FileResponse(task.result_audio_path, media_type="audio/wav")


# ── Worker: mark task complete (upload result) ────────────────
@router.post("/{task_id}/complete")
async def complete_task(task_id: str, audio: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task.status not in ("PROCESSING", "PENDING"):
        raise HTTPException(status_code=400, detail="Task is not in a processable state.")

    # Save audio file asynchronously to avoid blocking FastAPI's event loop.
    # Save in voice-named folder under DATA_DIR for organized output
    voice = await db.get(Voice, task.voice_id)
    voice_slug = _slugify(voice.name) if voice else "default"
    voice_dir = DATA_DIR / voice_slug / "output"
    voice_dir.mkdir(parents=True, exist_ok=True)
    dest = voice_dir / f"{task_id}.wav"
    async with aiofiles.open(dest, mode="wb") as f:
        await f.write(await audio.read())

    task.status = "COMPLETED"
    task.result_audio_path = str(dest)
    task.completed_at = datetime.now(timezone.utc)
    await db.commit()

    # Giải phóng event nếu đây là direct request
    event = _pending_direct_events.pop(task_id, None)
    if event:
        event.set()

    await manager.broadcast_status({"event": "task_completed", "task_id": task_id})
    if task.batch_id and task.webhook_url:
        asyncio.create_task(_fire_webhook_if_batch_complete(task.batch_id, task.webhook_url))

    return {"status": "COMPLETED"}


async def _fire_webhook_if_batch_complete(batch_id: str, webhook_url: str) -> None:
    """POST batch completion payload when no task in the batch is still running."""
    from app.database import async_session

    async with async_session() as db:
        result = await db.execute(
            select(func.count(Task.id)).where(
                Task.batch_id == batch_id,
                Task.status.in_(["PENDING", "PROCESSING"]),
            )
        )
        pending_count = result.scalar() or 0
        if pending_count > 0:
            return

        result = await db.execute(select(Task).where(Task.batch_id == batch_id))
        tasks = result.scalars().all()

    payload = {
        "batch_id": batch_id,
        "status": "COMPLETED",
        "tasks": [
            {
                "task_id": task.id,
                "text": task.text,
                "status": task.status,
                "audio_url": f"/api/tasks/{task.id}/audio" if task.result_audio_path else None,
                "error_message": task.error_message,
            }
            for task in tasks
        ],
    }

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, timeout=10.0)
            response.raise_for_status()
        logger.info("Webhook fired for batch %s -> %s", batch_id, webhook_url)
    except Exception as exc:
        logger.warning("Webhook failed for batch %s -> %s: %s", batch_id, webhook_url, exc)


# ── Debug endpoint to take screenshot of active Playwright pages ─────
@router.get("/debug/screenshot")
async def debug_screenshot():
    from app.automation.play_runner import _active_pages

    results = {}
    for email, page in _active_pages.items():
        try:
            clean_email = email.replace("@", "_").replace(".", "_")
            path = DATA_DIR / f"colab_debug_{clean_email}.png"
            await page.screenshot(path=str(path))
            results[email] = {
                "screenshot_path": str(path),
                "url": page.url,
                "title": await page.title()
            }
        except Exception as e:
            results[email] = {"error": str(e)}
            
    return {"active_pages": list(_active_pages.keys()), "results": results}


# ── Internal helper ───────────────────────────────────────────
async def _dispatch_task(task: Task, email: str, db: AsyncSession):
    """Send a PENDING task to an idle worker via WebSocket."""
    import app.config as config

    task.status = "PROCESSING"

    # Build the voice download URL (the worker will fetch from this)
    base = config.SERVER_URL
    voice_url = f"{base}/api/voices/{task.voice_id}/audio"

    dispatched = await manager.send_task(email, task.id, task.text, voice_url, task.language)
    if dispatched:
        # Mark worker as BUSY in memory to prevent duplicate dispatches
        manager.worker_info[email]["status"] = "BUSY"
        
        # Find the account id for this email (reuse existing session)
        from app.models import GoogleAccount
        result = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
        account = result.scalar_one_or_none()
        if account:
            task.worker_id = account.id
        await db.commit()
    else:
        task.status = "PENDING"
        await db.commit()
