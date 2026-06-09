from fastapi import APIRouter
from sqlalchemy import select, func
from datetime import datetime, timezone
from app.database import async_session
from app.models import Task, GoogleAccount
from app.routes.ws import manager

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/")
async def health_check():
    active_workers = len(manager.active)
    async with async_session() as db:
        pending_result = await db.execute(select(func.count()).select_from(Task).where(Task.status == "PENDING"))
        pending_tasks = pending_result.scalar() or 0
        workers_result = await db.execute(select(GoogleAccount.status, func.count()).group_by(GoogleAccount.status))
        workers_stats = dict(workers_result.all())
    return {
        "status": "ok",
        "workers": {"active_connections": active_workers, "database_stats": workers_stats},
        "queue": {"pending_tasks": pending_tasks},
    }


@router.get("/workers")
async def list_workers_detailed():
    # Returns detailed worker list with uptime and lifecycle status
    detailed = []
    now = datetime.now(timezone.utc)
    for email, info in manager.worker_info.items():
        uptime_seconds = info.get("uptime", 0)
        connected_at = info.get("connected_at")
        detailed.append({
            "email": email,
            "gpu": info.get("gpu"),
            "status": info.get("status"),
            "connected_at": connected_at.isoformat() if connected_at else None,
            "uptime_seconds": uptime_seconds,
            "expiring": info.get("expiring", False),
            "remaining_seconds": max(0, 13500 - uptime_seconds),
        })
    return detailed


@router.get("/stats")
async def stats():
    async with async_session() as db:
        total = await db.execute(select(func.count()).select_from(Task))
        completed = await db.execute(select(func.count()).select_from(Task).where(Task.status == "COMPLETED"))
        failed = await db.execute(select(func.count()).select_from(Task).where(Task.status == "FAILED"))
        pending = await db.execute(select(func.count()).select_from(Task).where(Task.status == "PENDING"))
    return {
        "total_tasks": total.scalar() or 0,
        "completed": completed.scalar() or 0,
        "failed": failed.scalar() or 0,
        "pending": pending.scalar() or 0,
        "active_workers": len(manager.active),
    }
