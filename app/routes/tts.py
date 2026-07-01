import logging
import os
import uuid
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, field_validator, Field, HttpUrl
from typing import Literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session
from app.models import Voice, Task
from app.models.user import User
from app.routes.ws import manager
from app.orchestrator.utils import _safe_create_task
from app.orchestrator.tts_state import _pending_direct_events
from app.routes.auth import require_user
from app.services.auth import count_tts_characters, deduct_balance

_tts_concurrent = 0  # sync TTS concurrent request counter

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

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        import ipaddress
        from urllib.parse import urlparse
        parsed = urlparse(v)
        if parsed.scheme not in ("https",):
            raise ValueError("webhook_url must use HTTPS")
        host = parsed.hostname
        if not host:
            raise ValueError("webhook_url must have a valid hostname")
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise ValueError("webhook_url must point to a public IP address")
        except ValueError as e:
            if "must point to a public IP" in str(e) or "must use HTTPS" in str(e) or "must have a valid" in str(e):
                raise
            # hostname is a domain name, not an IP — check for localhost patterns
            if host in ("localhost", "127.0.0.1", "0.0.0.0", "metadata.google.internal"):
                raise ValueError("webhook_url must not point to localhost or internal services")
        return v


# ── POST /api/tts/text ────────────────────────────────────────

@router.post(
    "/text",
    summary="TTS một text (đồng bộ)",
    response_description="Trả về file audio WAV trực tiếp khi xử lý xong.",
)
async def tts_text(req: TextTTSRequest, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    """
    Chuyển đổi text thành giọng nói (tối đa 2000 từ).
    - Gọi đồng bộ: chờ đến khi có audio rồi trả về file WAV.
    - Lỗi 400: voice không tồn tại hoặc text vượt giới hạn từ.
    - Lỗi 402: không đủ ký tự trong tài khoản.
    - Lỗi 503: không có worker rảnh.
    - Lỗi 504: worker xử lý quá thời gian (120 giây).
    """
    global _tts_concurrent
    if _tts_concurrent >= 10:
        raise HTTPException(status_code=429, detail="Too many concurrent TTS requests. Try again later.")
    _tts_concurrent += 1
    try:
        voice = await db.get(Voice, req.voice_id)
        if not voice:
            raise HTTPException(status_code=400, detail={"error": "voice_not_found", "message": f"Voice ID {req.voice_id} không tồn tại."})

        chars = count_tts_characters(req.text)
        if user.role != "admin" and user.balance < chars:
            raise HTTPException(status_code=402, detail=f"Insufficient balance. Need {chars}, have {user.balance}")

        task = Task(
            id=str(uuid.uuid4()),
            text=req.text,
            voice_id=req.voice_id,
            language=req.language,
            status="PENDING",
            batch_id=None,
            user_id=user.id,
        )
        db.add(task)
        ok = await deduct_balance(user, chars, "dashboard", db, task_id=task.id)
        if not ok:
            raise HTTPException(status_code=402, detail="Insufficient balance")
        await db.commit()
        await db.refresh(task)

        # 1. Dispatch nếu có worker rảnh
        idle_email = manager.get_idle_worker()
        if idle_email:
            from app.routes.tasks import _dispatch_task
            event = asyncio.Event()
            _pending_direct_events[task.id] = event
            ok = await _dispatch_task(task, idle_email, db)
            if not ok:
                _pending_direct_events.pop(task.id, None)
                raise HTTPException(status_code=503, detail="No worker available to take the task.")
            await manager.broadcast_status({"event": "task_created", "task_id": task.id})
            try:
                await asyncio.wait_for(event.wait(), timeout=120.0)
            except asyncio.TimeoutError:
                async with async_session() as db_to:
                    task_to = await db_to.get(Task, task.id)
                    if task_to and task_to.status == "PROCESSING":
                        task_to.status = "FAILED"
                        task_to.error_message = "Processing timeout"
                        await db_to.commit()
                raise HTTPException(status_code=504, detail="Processing timeout.")
            finally:
                _pending_direct_events.pop(task.id, None)
            await db.refresh(task)
            if task.status == "COMPLETED":
                if task.result_audio_path and os.path.exists(task.result_audio_path):
                    return FileResponse(task.result_audio_path, media_type="audio/wav")
                raise HTTPException(status_code=500, detail="Audio file missing on server.")
            raise HTTPException(status_code=500, detail=f"Task failed: {task.error_message}")

        # 2. Không có worker rảnh → scale + event-driven wait
        from app.routes.ws import _maybe_scale_up
        _safe_create_task(_maybe_scale_up())
        await manager.broadcast_status({"event": "task_created", "task_id": task.id})

        event = asyncio.Event()
        _pending_direct_events[task.id] = event

        try:
            await asyncio.wait_for(event.wait(), timeout=120.0)
        except asyncio.TimeoutError:
            _pending_direct_events.pop(task.id, None)
            async with async_session() as to_db:
                task_to = await to_db.get(Task, task.id)
                if task_to and task_to.status == "PROCESSING":
                    task_to.status = "FAILED"
                    task_to.error_message = "Processing timeout (no worker picked up)"
                    await to_db.commit()
                if user.role != "admin":
                    from app.services.auth import add_balance
                    await add_balance(user, chars, to_db)
            raise HTTPException(status_code=504, detail="Processing timeout.")
        finally:
            _pending_direct_events.pop(task.id, None)

        async with async_session() as ref_db:
            task_ref = await ref_db.get(Task, task.id)
            if not task_ref:
                raise HTTPException(status_code=500, detail="Task vanished from database.")
            if task_ref.status == "COMPLETED":
                if task_ref.result_audio_path and os.path.exists(task_ref.result_audio_path):
                    return FileResponse(task_ref.result_audio_path, media_type="audio/wav")
                raise HTTPException(status_code=500, detail="Audio file missing on server.")
            raise HTTPException(status_code=500, detail=f"Task failed: {task_ref.error_message}")
    finally:
        _tts_concurrent -= 1


# ── POST /api/tts/batch ───────────────────────────────────────

@router.post(
    "/batch",
    summary="TTS nhiều text (bất đồng bộ + webhook tuỳ chọn)",
    response_description="Mapping text → task_id cho toàn bộ batch.",
)
async def tts_batch(req: BatchTTSRequest, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
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

    total_chars = sum(count_tts_characters(t) for t in req.texts)
    if user.role != "admin" and user.balance < total_chars:
        raise HTTPException(status_code=402, detail=f"Insufficient balance. Need {total_chars}, have {user.balance}")

    created_tasks = []
    batch_id = str(uuid.uuid4())
    for text in req.texts:
        task = Task(
            id=str(uuid.uuid4()),
            text=text,
            voice_id=req.voice_id,
            language=req.language,
            status="PENDING",
            batch_id=batch_id,
            webhook_url=req.webhook_url,
            user_id=user.id,
        )
        db.add(task)
        created_tasks.append(task)

    for task in created_tasks:
        chars = count_tts_characters(task.text)
        if user.role != "admin":
            ok = await deduct_balance(user, chars, "api" if req.webhook_url else "dashboard", db, task_id=task.id)
            if not ok:
                raise HTTPException(status_code=402, detail="Insufficient balance")
        else:
            # For admin, still record usage but don't check/deduct balance
            from app.models.user import UsageRecord
            record = UsageRecord(user_id=user.id, task_id=task.id, characters=chars, cost=0, source="api" if req.webhook_url else "dashboard")
            db.add(record)

    await db.commit()
    # We do NOT call db.refresh(task) here to save database round-trips.

    # 3. Find connected idle workers and immediately dispatch tasks to them
    idle_emails = []
    for email in manager.workers_by_type.get("tts", []):
        info = manager.worker_info.get(email)
        if info and info.get("status") == "IDLE":
            idle_emails.append((email, info.get("worker_session_id", ""), info.get("expiring", False)))
    
    # Prioritize non-expiring workers
    idle_emails.sort(key=lambda x: x[2])
    
    # Dispatch immediately to idle workers
    from app.routes.tasks import _dispatch_task
    dispatched_count = 0
    for i, email_info in enumerate(idle_emails[:len(created_tasks)]):
        email, wsid, _ = email_info
        task = created_tasks[i]
        
        # Mark worker as busy in-memory immediately to prevent double-leasing
        if email in manager.worker_info:
            manager.worker_info[email]["status"] = "BUSY"
            
        # Dispatch task asynchronously
        _safe_create_task(_dispatch_task(task, email, db))
        dispatched_count += 1

    # 4. Trigger scale-up only if there are remaining pending tasks
    if len(created_tasks) > dispatched_count:
        from app.routes.ws import _maybe_scale_up
        _safe_create_task(_maybe_scale_up())

    # 5. Broadcast status only for tasks that are pending (not immediately dispatched)
    for task in created_tasks[dispatched_count:]:
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
                "status": "PROCESSING" if i < dispatched_count else "PENDING",
            }
            for i, task in enumerate(created_tasks)
        ],
    }


