"""API routes for user usage history."""

import logging
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from app.database import get_db
from app.models.user import User, UsageRecord
from app.routes.auth import require_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/usage", tags=["usage"])


@router.get("")
@router.get("/")
async def get_usage(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UsageRecord)
        .where(UsageRecord.user_id == user.id)
        .order_by(UsageRecord.created_at.desc())
        .limit(50)
    )
    total_result = await db.execute(
        select(func.coalesce(func.sum(UsageRecord.cost), 0))
        .where(UsageRecord.user_id == user.id)
    )
    total_used = total_result.scalar() or 0
    return {
        "balance": user.balance,
        "total_used": total_used,
        "records": [
            {
                "id": r.id,
                "characters": r.characters,
                "cost": r.cost,
                "source": r.source,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in result.scalars().all()
        ],
    }
