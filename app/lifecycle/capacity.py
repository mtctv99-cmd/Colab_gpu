"""Capacity calculations and autoscale decision logic."""

import time
import logging
from datetime import datetime, timezone
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GoogleAccount, Task
from app.config import (
    MAX_CONCURRENT_WORKERS,
    SCALE_UP_PENDING_THRESHOLD,
    SCALE_UP_SUSTAIN_SECONDS
)
from app.lifecycle.constants import (
    ACCOUNT_READY,
    RUNTIME_IDLE,
    RUNTIME_BUSY,
    RUNTIME_STARTING_BROWSER,
    RUNTIME_CONNECTING_RUNTIME,
    RUNTIME_WARMING_MODEL,
    RUNTIME_DRAINING,
    CAPACITY_RUNTIME_STATUSES,
    WARM_RUNTIME_STATUSES
)

logger = logging.getLogger(__name__)

# Track when the heavy load condition started
_heavy_load_start_time = None


async def get_active_capacity(db: AsyncSession) -> int:
    """Count workers currently consuming capacity slot."""
    res = await db.execute(
        select(func.count(GoogleAccount.id))
        .where(GoogleAccount.runtime_status.in_(CAPACITY_RUNTIME_STATUSES))
    )
    return res.scalar() or 0


async def get_warm_capacity(db: AsyncSession) -> int:
    """Count warm workers (active and not draining)."""
    res = await db.execute(
        select(func.count(GoogleAccount.id))
        .where(GoogleAccount.runtime_status.in_(WARM_RUNTIME_STATUSES))
    )
    return res.scalar() or 0


async def get_idle_capacity(db: AsyncSession) -> int:
    """Count idle ready workers."""
    res = await db.execute(
        select(func.count(GoogleAccount.id))
        .where(GoogleAccount.runtime_status == RUNTIME_IDLE)
    )
    return res.scalar() or 0


async def get_busy_capacity(db: AsyncSession) -> int:
    """Count busy workers."""
    res = await db.execute(
        select(func.count(GoogleAccount.id))
        .where(GoogleAccount.runtime_status == RUNTIME_BUSY)
    )
    return res.scalar() or 0


async def get_pending_tasks_count(db: AsyncSession) -> int:
    """Count pending tasks."""
    res = await db.execute(
        select(func.count(Task.id))
        .where(Task.status == "PENDING")
    )
    return res.scalar() or 0


async def get_processing_tasks_count(db: AsyncSession) -> int:
    """Count tasks currently processing."""
    res = await db.execute(
        select(func.count(Task.id))
        .where(Task.status == "PROCESSING")
    )
    return res.scalar() or 0


async def get_ready_accounts_count(db: AsyncSession) -> int:
    """Count eligible accounts ready to launch browser."""
    res = await db.execute(
        select(func.count(GoogleAccount.id))
        .where(
            and_(
                GoogleAccount.status == ACCOUNT_READY,
                GoogleAccount.worker_session_id.is_(None),
                GoogleAccount.browser_session_id.is_(None)
            )
        )
    )
    return res.scalar() or 0


async def check_scale_up_trigger(db: AsyncSession) -> bool:
    """Determine if a new worker should be launched based on current load."""
    global _heavy_load_start_time

    actual = await get_active_capacity(db)
    ready = await get_ready_accounts_count(db)

    # Hard limits
    if actual >= MAX_CONCURRENT_WORKERS or ready == 0:
        _heavy_load_start_time = None
        return False

    pending = await get_pending_tasks_count(db)

    # 1. Warm target: if no workers at all, and tasks are waiting, scale up immediately
    if actual == 0 and pending > 0:
        _heavy_load_start_time = None
        logger.info("Autoscale: 0 active workers, %d tasks pending. Trigger launch.", pending)
        return True

    # 2. Worker 2 backup: if only 1 worker active, and pending task exists, spawn worker 2
    if actual == 1 and pending > 0:
        _heavy_load_start_time = None
        logger.info("Autoscale: 1 active worker, %d tasks pending. Trigger worker 2 backup.", pending)
        return True

    # 3. Worker 3+: Scale under heavy load only (queue >= 10 and holds load for 10 seconds)
    if pending >= SCALE_UP_PENDING_THRESHOLD and actual >= 2:
        now = time.time()
        if _heavy_load_start_time is None:
            _heavy_load_start_time = now
            logger.info(
                "Autoscale: Heavy load detected (%d pending, %d active). Sustain timer started.",
                pending,
                actual
            )
            return False

        duration = now - _heavy_load_start_time
        if duration >= SCALE_UP_SUSTAIN_SECONDS:
            logger.info(
                "Autoscale: Heavy load sustained for %.1fs (%d pending, %d active). Triggering scale-up.",
                duration,
                pending,
                actual
            )
            _heavy_load_start_time = None  # Reset timer for next scale action
            return True
        return False

    # Reset timer if load falls below threshold
    _heavy_load_start_time = None
    return False
