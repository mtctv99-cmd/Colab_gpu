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
from app.automation import play_runner
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
            "browser_session_id": a.browser_session_id,
            "current_task_id": a.current_task_id,
            "last_active": a.last_active.isoformat() if a.last_active else None,
            "started_at": a.started_at.isoformat() if a.started_at else None,
            "last_heartbeat_at": a.last_heartbeat_at.isoformat() if a.last_heartbeat_at else None,
            "quota_reset_at": a.quota_reset_at.isoformat() if a.quota_reset_at else None,
            "idle_since": a.idle_since.isoformat() if a.idle_since else None,
        }
        for a in accounts
    ]


# ── Add account (opens login window) ──────────────────────────
@router.post("/add")
async def add_account(req: AddAccountRequest, db: AsyncSession = Depends(get_db)):
    # Check duplicate
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

    # Launch headed browser for login
    try:
        await play_runner.add_google_account_session(req.email)
    except Exception as exc:
        account.status = "OFFLINE"
        await db.commit()
        logger.error("Failed to add account %s: %s", req.email, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"id": account.id, "email": account.email, "status": account.status}


# ── Finish login ──────────────────────────────────────────────
@router.post("/{account_id}/finish-login")
async def finish_login(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

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

    from app.lifecycle.sessions import reserve_account_for_browser_launch
    res = await reserve_account_for_browser_launch(db, email=account.email)
    if not res:
        raise HTTPException(
            status_code=400,
            detail=f"Account {account.email} is not READY or already has active session."
        )
    email, browser_sid = res

    # Determine server URL
    server_url = config.SERVER_URL
    if "localhost" in server_url or "127.0.0.1" in server_url:
        server_url = str(request.base_url).rstrip("/")

    async def _bg_start():
        try:
            await play_runner.start_colab_worker(email, server_url, browser_sid)
        except Exception as exc:
            logger.error("Background start failed for %s: %s", email, exc)
            # Cleanup DB state on launch error
            from app.database import async_session
            async with async_session() as bdb:
                acc = await bdb.get(GoogleAccount, account_id)
                if acc:
                    acc.worker_session_id = None
                    acc.browser_session_id = None
                    acc.runtime_status = None
                    # Set COOLDOWN backoff
                    acc.status = "COOLDOWN"
                    acc.quota_reset_at = datetime.now(timezone.utc) + timedelta(minutes=5)
                    await bdb.commit()

    asyncio.create_task(_bg_start())
    return {"id": account.id, "status": "STARTING_BACKGROUND", "browser_session_id": browser_sid}


# ── Stop worker ───────────────────────────────────────────────
@router.post("/{account_id}/stop")
async def stop_worker(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    await play_runner.stop_colab_worker(account.email)
    return {"id": account.id, "status": "STOPPING_BACKGROUND"}


# ── Delete account ────────────────────────────────────────────
@router.delete("/{account_id}")
async def delete_account(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    await play_runner.stop_colab_worker(account.email)
    await db.delete(account)
    await db.commit()
    return {"detail": "Deleted"}


# ── Re-login (open browser for NEEDS_LOGIN) ────────────────────
@router.post("/{account_id}/relogin")
async def relogin_account(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    account.status = "CONNECTING"
    await db.commit()

    try:
        await play_runner.add_google_account_session(account.email)
    except Exception as exc:
        account.status = "NEEDS_LOGIN"
        await db.commit()
        logger.error("Relogin failed for account %s: %s", account.email, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"id": account.id, "email": account.email, "status": "CONNECTING"}


# ── Debug screenshot ──────────────────────────────────────────
@router.get("/{account_id}/screenshot")
async def get_worker_screenshot(account_id: int, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import FileResponse
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    
    entry = play_runner._registry.get(account.email)
    page = entry.page if entry else None
    if not page:
        raise HTTPException(status_code=400, detail=f"No active browser session for {account.email}")
    
    safe_email = account.email.replace("@", "_").replace(".", "_")
    path = config.DATA_DIR / f"colab_current_{safe_email}.png"
    try:
        await page.screenshot(path=str(path))
        return FileResponse(str(path))
    except Exception as exc:
        logger.error("Failed to capture screenshot for %s: %s", account.email, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Capacity info ─────────────────────────────────────────────
@router.get("/capacity")
@router.get("/capacity/")
async def get_system_capacity_info(db: AsyncSession = Depends(get_db)):
    from app.lifecycle.capacity import (
        get_active_capacity,
        get_warm_capacity,
        get_idle_capacity,
        get_busy_capacity,
        get_pending_tasks_count,
        get_processing_tasks_count,
        get_ready_accounts_count,
    )
    from app.config import MAX_CONCURRENT_WORKERS, KEEP_WARM_WORKERS

    active_cap = await get_active_capacity(db)
    warm_cap = await get_warm_capacity(db)
    idle_cap = await get_idle_capacity(db)
    busy_cap = await get_busy_capacity(db)
    pending_tasks = await get_pending_tasks_count(db)
    processing_tasks = await get_processing_tasks_count(db)
    ready_accounts = await get_ready_accounts_count(db)

    return {
        "max_concurrent_workers": MAX_CONCURRENT_WORKERS,
        "keep_warm_workers": KEEP_WARM_WORKERS,
        "active_capacity": active_cap,
        "warm_capacity": warm_cap,
        "idle_capacity": idle_cap,
        "busy_capacity": busy_cap,
        "pending_tasks": pending_tasks,
        "processing_tasks": processing_tasks,
        "ready_accounts": ready_accounts,
    }

