"""API routes for managing Google accounts and Colab workers."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.config as config
from app.database import get_db
from app.models import GoogleAccount
from app.automation import play_runner


router = APIRouter(prefix="/api/accounts", tags=["accounts"])


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

    try:
        await play_runner.start_colab_worker(account.email, server_url)
    except Exception as exc:
        account.status = "OFFLINE"
        await db.commit()
        raise HTTPException(status_code=500, detail=str(exc))

    return {"id": account.id, "status": account.status}



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
