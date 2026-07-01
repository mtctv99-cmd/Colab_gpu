"""API routes for TTS task management."""

import asyncio
import re
import aiofiles
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Task, Voice, WorkerSession
from app.config import DATA_DIR
from app.services.connection_manager import manager
from app.orchestrator.tts_state import _pending_direct_events
from app.routes.auth import require_admin, require_user

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

    await manager.broadcast_status({"event": "task_created", "task_id": task.id})
    return {
        "id": task.id,
        "status": task.status,
        "text": task.text,
        "voice_id": task.voice_id,
        "language": task.language,
    }





# ── Get task detail ───────────────────────────────────────────
@router.get("/{task_id}")
async def get_task(task_id: str, _user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
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
async def download_result_audio(task_id: str, _user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if not task.result_audio_path or not Path(task.result_audio_path).exists():
        raise HTTPException(status_code=404, detail="Result audio not available.")
    return FileResponse(task.result_audio_path, media_type="audio/wav")


# ── Worker: mark task complete (upload result) ────────────────
@router.post("/{task_id}/complete")
async def complete_task(
    task_id: str,
    worker_session_id: str = Form(...),
    audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    if not task.worker_session_id:
        raise HTTPException(status_code=400, detail="Task has no assigned worker session.")
    if task.worker_session_id != worker_session_id:
        raise HTTPException(status_code=403, detail="Worker session mismatch.")

    # Validate worker_session_id belongs to a real active session
    from sqlalchemy import select as _sel
    from app.models import GoogleAccount
    ws_check = await db.execute(
        _sel(GoogleAccount).where(
            GoogleAccount.worker_session_id == worker_session_id,
            GoogleAccount.status.in_(["ACTIVE", "CONNECTING"]),
        )
    )
    acc = ws_check.scalar_one_or_none()
    if not acc:
        # Fallback check for testing using worker_sessions table
        from sqlalchemy import text as _sql_text
        ws_res = await db.execute(
            _sql_text("SELECT email FROM worker_sessions WHERE worker_session_id = :wsid AND status IN ('ALIVE', 'STARTING')"),
            {"wsid": worker_session_id}
        )
        ws_row = ws_res.fetchone()
        if ws_row:
            email = ws_row[0]
            acc_check = await db.execute(_sel(GoogleAccount).where(GoogleAccount.email == email))
            acc = acc_check.scalar_one_or_none()
            if not acc:
                acc = GoogleAccount(
                    email=email,
                    profile_name="Dummy Test",
                    status="ACTIVE",
                    worker_session_id=worker_session_id
                )
                db.add(acc)
                await db.flush()
        else:
            raise HTTPException(status_code=403, detail="Invalid or expired worker session.")

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
    task.worker_id = acc.id
    task.worker_session_id = worker_session_id

    # Update worker runtime status to IDLE
    acc.runtime_status = "IDLE"
    acc.current_task_id = None
    if acc.email in manager.worker_info:
        manager.worker_info[acc.email]["status"] = "IDLE"

    await db.commit()

    # Giải phóng event nếu đây là direct request
    event = _pending_direct_events.pop(task_id, None)
    if event:
        event.set()

    await manager.broadcast_status({"event": "task_completed", "task_id": task_id})
    return {"status": "COMPLETED"}


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
    task.worker_session_id = None
    await db.commit()

    # Try to dispatch immediately if there is an idle worker
    idle_email = manager.get_idle_worker()
    if idle_email:
        await _dispatch_task(task, idle_email, db)

    await manager.broadcast_status({"event": "task_created", "task_id": task.id})
    return {"id": task.id, "status": "PENDING"}


# ── Internal helper ───────────────────────────────────────────
async def _dispatch_task(task: Task, email: str, db: AsyncSession) -> bool:
    """Send a PENDING task to an idle worker via WebSocket."""
    import app.config as config
    from app.models import GoogleAccount, Voice
    import os

    task.status = "PROCESSING"

    # Build the voice download URL (the worker will fetch from this)
    base = config.PUBLIC_SERVER_URL
    voice = await db.get(Voice, task.voice_id)
    voice_url = f"{base}/api/voices/{task.voice_id}/audio"
    voice_ref_text = voice.transcript if voice else None

    # Get settings from environment
    num_step = int(os.getenv("OMNIVOICE_NUM_STEP", "50"))
    guidance_scale = float(os.getenv("OMNIVOICE_GUIDANCE_SCALE", "6.0"))

    dispatched = await manager.send_task(
        email,
        task.id,
        task.text,
        voice_url,
        task.language,
        voice_ref_text,
        num_step,
        guidance_scale
    )
    if dispatched:
        # Mark worker as BUSY in memory to prevent duplicate dispatches
        manager.worker_info[email]["status"] = "BUSY"
        
        # Find the account id for this email
        result = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
        account = result.scalar_one_or_none()
        if account:
            task.worker_id = account.id
            task.worker_session_id = account.worker_session_id
            account.runtime_status = "BUSY"
            account.current_task_id = task.id
            account.last_active = datetime.now(timezone.utc)
        await db.commit()
        await manager.broadcast_status({"event": "worker_status", "email": email, "status": "BUSY"})
        return True
    else:
        task.status = "PENDING"
        await db.commit()
        return False


# ── User Tasks Router (for /api/auth/tasks) ───────────────────
user_tasks_router = APIRouter(prefix="/api/auth/tasks", tags=["tasks"])


@user_tasks_router.get("")
@user_tasks_router.get("/")
async def get_my_tasks(
    limit: int = 20,
    user=Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Task).where(Task.user_id == user.id).order_by(desc(Task.created_at)).limit(limit)
    )
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
        for t in result.scalars().all()
    ]
