from fastapi import APIRouter
from sqlalchemy import select, func
from app.database import async_session
from app.models import Task, GoogleAccount
from app.routes.ws import manager

router = APIRouter(prefix="/api/health", tags=["health"])

@router.get("/")
async def health_check():
    """Kiểm tra trạng thái server, worker online và hàng đợi task."""
    active_workers = len(manager.active)
    
    async with async_session() as db:
        # Số task đang chờ xử lý
        pending_result = await db.execute(select(func.count()).select_from(Task).where(Task.status == "PENDING"))
        pending_tasks = pending_result.scalar() or 0
        
        # Lấy trạng thái các worker theo db
        workers_result = await db.execute(select(GoogleAccount.status, func.count()).group_by(GoogleAccount.status))
        workers_stats = dict(workers_result.all())
        
    return {
        "status": "ok",
        "workers": {
            "active_connections": active_workers,
            "database_stats": workers_stats
        },
        "queue": {
            "pending_tasks": pending_tasks
        }
    }
