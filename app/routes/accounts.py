"""API routes for managing Google accounts and Colab workers."""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.config as config
from app.database import get_db
from app.models import GoogleAccount
from app.routes.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/accounts", tags=["accounts"], dependencies=[Depends(require_admin)])


class AddAccountRequest(BaseModel):
    email: str


# ── List accounts ──────────────────────────────────────────────
@router.get("")
@router.get("/")
async def list_accounts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GoogleAccount))
    accounts = result.scalars().all()
    
    return [
        {
            "id": a.id,
            "email": a.email,
            "profile_name": a.profile_name,
            "status": a.status,
            "runtime_status": a.runtime_status,
            "worker_session_id": a.worker_session_id,
            "current_task_id": a.current_task_id,
            "last_active": a.last_active.isoformat() if a.last_active else None,
            "started_at": a.started_at.isoformat() if a.started_at else None,
            "last_heartbeat_at": a.last_heartbeat_at.isoformat() if a.last_heartbeat_at else None,
            "quota_reset_at": a.quota_reset_at.isoformat() if a.quota_reset_at else None,
            "idle_since": a.idle_since.isoformat() if a.idle_since else None,
            "token_ok": True,
            "token_expiry": None,
            "assigned_node_id": None,
        }
        for a in accounts
    ]


# ── Add account ────────────────────────────────────────────
@router.post("/add")
async def add_account(req: AddAccountRequest, db: AsyncSession = Depends(get_db)):
    exists = await db.execute(select(GoogleAccount).where(GoogleAccount.email == req.email))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Account already exists.")

    account = GoogleAccount(
        email=req.email,
        profile_name=req.email.replace("@", "_at_").replace(".", "_"),
        status="CONNECTING",
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    try:
        from app.automation import play_runner
        await play_runner.add_google_account_session(req.email)
    except Exception as exc:
        account.status = "OFFLINE"
        await db.commit()
        raise HTTPException(status_code=500, detail=str(exc))

    return {"id": account.id, "email": account.email, "status": account.status}


# ── Finish login ──────────────────────────────────────────────
@router.post("/{account_id}/finish-login")
async def finish_login(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    from app.automation import play_runner
    await play_runner.finish_google_account_session(account.email)
    account.status = "OFFLINE"
    account.last_active = datetime.now(timezone.utc)
    await db.commit()
    return {"id": account.id, "status": account.status}


# ── Start worker ──────────────────────────────────────────────
@router.post("/{account_id}/start")
async def start_worker(account_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    if account.status not in ("OFFLINE", "READY", "NEEDS_LOGIN"):
        raise HTTPException(status_code=400, detail=f"Account is {account.status}, cannot start.")

    import uuid
    worker_session_id = str(uuid.uuid4())
    account.status = "CONNECTING"
    account.worker_session_id = worker_session_id
    account.started_at = datetime.now(timezone.utc)
    account.last_active = datetime.now(timezone.utc)
    await db.commit()

    server_url = config.SERVER_URL
    if "localhost" in server_url or "127.0.0.1" in server_url:
        server_url = str(request.base_url).rstrip("/")

    async def _bg_start():
        try:
            from app.automation import play_runner
            await play_runner.start_colab_worker(account.email, server_url, worker_session_id)
        except Exception as exc:
            logger.error("Background start failed for %s: %s", account.email, exc)
            from app.database import async_session
            async with async_session() as bdb:
                acc = await bdb.get(GoogleAccount, account_id)
                if acc:
                    acc.status = "OFFLINE"
                    acc.worker_session_id = None
                    await bdb.commit()

    asyncio.create_task(_bg_start())
    return {"id": account.id, "status": "STARTING_BACKGROUND"}


# ── Stop worker ───────────────────────────────────────────────
@router.post("/{account_id}/stop")
async def stop_worker(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    from app.automation import play_runner
    await play_runner.stop_colab_worker(account.email)
    account.status = "OFFLINE"
    account.worker_session_id = None
    account.runtime_status = None
    await db.commit()
    return {"id": account.id, "status": account.status}


# ── Delete account ────────────────────────────────────────────
@router.delete("/{account_id}")
async def delete_account(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    from app.automation import play_runner
    try:
        await play_runner.stop_colab_worker(account.email)
    except Exception:
        pass

    # Clear FK references before deleting
    from app.models import Task
    await db.execute(
        __import__("sqlalchemy").update(Task).where(Task.worker_id == account_id).values(worker_id=None)
    )
    await db.delete(account)
    await db.commit()
    return {"detail": "Deleted"}


# ── Re-login ──────────────────────────────────────────────────
@router.post("/{account_id}/relogin")
async def relogin_account(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    account.status = "CONNECTING"
    await db.commit()

    try:
        from app.automation import play_runner
        await play_runner.add_google_account_session(account.email)
    except Exception as exc:
        account.status = "OFFLINE"
        await db.commit()
        raise HTTPException(status_code=500, detail=str(exc))

    return {"id": account.id, "email": account.email, "status": "CONNECTING"}


# ── Debug screenshot ──────────────────────────────────────────
@router.get("/{account_id}/screenshot")
async def get_worker_screenshot(account_id: int, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import FileResponse
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    
    from app.automation import play_runner
    page = play_runner._active_pages.get(account.email)
    if not page:
        raise HTTPException(status_code=400, detail=f"No active browser session for {account.email}")
    
    safe_email = account.email.replace("@", "_").replace(".", "_")
    path = config.DATA_DIR / f"colab_current_{safe_email}.png"
    try:
        await page.screenshot(path=str(path))
        return FileResponse(str(path))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to capture screenshot: {exc}")


# ── Capacity info ─────────────────────────────────────────────
@router.get("/capacity")
@router.get("/capacity/")
async def get_system_capacity_info(db: AsyncSession = Depends(get_db)):
    from app.config import MAX_CONCURRENT_WORKERS, KEEP_WARM_WORKERS
    from app.routes.ws import manager as ws_manager
    from app.models import Task
    from sqlalchemy import func

    idle = busy = warm = 0
    for info in ws_manager.worker_info.values():
        st = info.get("status", "")
        if st == "IDLE":
            idle += 1
        elif st == "BUSY":
            busy += 1
        elif st in ("LOADING", "WARMING", "STARTING", "CONNECTING"):
            warm += 1

    proc_res = await db.execute(select(func.count(Task.id)).where(Task.status == "PROCESSING"))
    processing_tasks = proc_res.scalar() or 0

    pending_res = await db.execute(select(func.count(Task.id)).where(Task.status == "PENDING"))
    pending_tasks = pending_res.scalar() or 0

    ready_acc_res = await db.execute(select(func.count(GoogleAccount.id)).where(GoogleAccount.status == "OFFLINE"))
    ready_accounts = ready_acc_res.scalar() or 0

    return {
        "max_concurrent_workers": MAX_CONCURRENT_WORKERS,
        "keep_warm_workers": KEEP_WARM_WORKERS,
        "active_capacity": len(ws_manager.active),
        "warm_capacity": warm,
        "idle_capacity": idle,
        "busy_capacity": busy,
        "pending_tasks": pending_tasks,
        "processing_tasks": processing_tasks,
        "ready_accounts": ready_accounts,
    }
