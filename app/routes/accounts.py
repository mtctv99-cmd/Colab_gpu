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
            "last_active": a.last_active.isoformat() if a.last_active else None,
            "quota_reset_at": a.quota_reset_at.isoformat() if a.quota_reset_at else None,
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
        raise HTTPException(status_code=500, detail=str(exc))

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
    if account.status not in ("OFFLINE",):
        raise HTTPException(status_code=400, detail=f"Account is {account.status}, cannot start.")

    account.status = "ACTIVE"
    account.last_active = datetime.now(timezone.utc)
    await db.commit()

    # Determine server URL: config.SERVER_URL is preferred if it has been updated from default localhost,
    # otherwise fallback to the current request's base URL.
    server_url = config.SERVER_URL
    if "localhost" in server_url or "127.0.0.1" in server_url:
        server_url = str(request.base_url).rstrip("/")

    async def _bg_start():
        try:
            await play_runner.start_colab_worker(account.email, server_url)
        except Exception as exc:
            logger.error("Background start failed for %s: %s", account.email, exc)
            # Re-fetch database session to update status
            from app.database import async_session
            async with async_session() as bdb:
                acc = await bdb.get(GoogleAccount, account_id)
                if acc:
                    acc.status = "OFFLINE"
                    await bdb.commit()

    asyncio.create_task(_bg_start())
    return {"id": account.id, "status": "STARTING_BACKGROUND"}



# ── Stop worker ───────────────────────────────────────────────
@router.post("/{account_id}/stop")
async def stop_worker(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    await play_runner.stop_colab_worker(account.email)
    account.status = "OFFLINE"
    await db.commit()
    return {"id": account.id, "status": account.status}


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


# ── Debug screenshot ──────────────────────────────────────────
@router.get("/{account_id}/screenshot")
async def get_worker_screenshot(account_id: int, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import FileResponse
    account = await db.get(GoogleAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    
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
