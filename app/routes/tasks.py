"""API routes for TTS task management."""

import asyncio
import re
import aiofiles
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Task, Voice
from app.config import DATA_DIR
from app.routes.ws import manager, _pending_direct_events, _safe_create_task
from app.routes.auth import require_admin

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



# ── List tasks ────────────────────────────────────────────────
@router.get("")
@router.get("/")
async def list_tasks(limit: int = 20, _admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
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
async def create_task(req: CreateTaskRequest, _admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
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
            from app.routes.ws import _try_auto_rotate, _rotate_lock, _has_starting_or_active_account
            if not _rotate_lock.locked() and not await _has_starting_or_active_account():
                logger.info("No active workers online. Starting one eligible worker...")
                _safe_create_task(_try_auto_rotate())
            else:
                logger.info("Worker/browser already starting; skip opening another browser.")
        else:
            from app.routes.ws import _maybe_scale_up
            _safe_create_task(_maybe_scale_up())

    await manager.broadcast_status({"event": "task_created", "task_id": task.id})
    from app.routes.ws import _maybe_scale_up
    _safe_create_task(_maybe_scale_up())
    return {
        "id": task.id,
        "status": task.status,
        "text": task.text,
        "voice_id": task.voice_id,
        "language": task.language,
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
        _safe_create_task(_fire_webhook_if_batch_complete(task.batch_id, task.webhook_url))

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


@router.post("/{task_id}/retry")
async def retry_task(task_id: str, _admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    if task.status != "FAILED":
        raise HTTPException(status_code=400, detail="Only failed tasks can be retried.")

    task.status = "PENDING"
    task.error_message = None
    task.completed_at = None
    task.worker_id = None
    await db.commit()

    # Try to dispatch immediately if there is an idle worker
    from app.routes.ws import _maybe_scale_up
    idle_email = manager.get_idle_worker()
    if idle_email:
        await _dispatch_task(task, idle_email, db)
    else:
        _safe_create_task(_maybe_scale_up())

    await manager.broadcast_status({"event": "task_created", "task_id": task.id})
    return {"id": task.id, "status": "PENDING"}


# ── Internal helper ───────────────────────────────────────────
async def _dispatch_task(task: Task, email: str, db: AsyncSession):
    """Send a PENDING task to an idle worker via WebSocket."""
    import app.config as config
    import os

    task.status = "PROCESSING"

    # Build the voice download URL (the worker will fetch from this)
    base = config.SERVER_URL
    voice = await db.get(Voice, task.voice_id)
    voice_url = f"{base}/api/voices/{task.voice_id}/audio"
    voice_ref_text = voice.transcript if voice else None

    num_step = int(os.getenv("OMNIVOICE_NUM_STEP", "24"))
    guidance_scale = float(os.getenv("OMNIVOICE_GUIDANCE_SCALE", "3.0"))
    dispatched = await manager.send_task(email, task.id, task.text, voice_url, task.language, voice_ref_text, num_step, guidance_scale)
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
