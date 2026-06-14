"""Maintenance reaper for expiring leases, stale heartbeats, cooldown reset, and scale-down."""

import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GoogleAccount, Task
from app.config import (
    WORKER_HEARTBEAT_TIMEOUT_SECONDS,
    KEEP_WARM_WORKERS,
    SCALE_DOWN_IDLE_SECONDS
)
from app.lifecycle.constants import (
    ACCOUNT_READY,
    ACCOUNT_COOLDOWN,
    RUNTIME_LOST,
    RUNTIME_IDLE
)

logger = logging.getLogger(__name__)


async def reap_stale_sessions(db: AsyncSession) -> list[str]:
    """
    Find workers with stale heartbeats.
    Marks runtime_status as LOST and returns list of emails to stop.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=WORKER_HEARTBEAT_TIMEOUT_SECONDS)

    res = await db.execute(
        select(GoogleAccount)
        .where(
            and_(
                GoogleAccount.worker_session_id.is_not(None),
                GoogleAccount.last_heartbeat_at < cutoff
            )
        )
    )
    stale_accounts = res.scalars().all()
    emails_to_stop = []

    for acc in stale_accounts:
        logger.warning(
            "Reaper: worker %s heartbeat stale (last: %s, cutoff: %s). Marking LOST.",
            acc.email,
            acc.last_heartbeat_at,
            cutoff
        )
        acc.runtime_status = RUNTIME_LOST
        emails_to_stop.append(acc.email)

    if stale_accounts:
        await db.commit()

    return emails_to_stop


async def reap_expired_task_leases(db: AsyncSession) -> list[str]:
    """
    Find tasks stuck in PROCESSING past their lease expiry.
    Resets status to PENDING and returns list of task IDs.
    """
    now = datetime.now(timezone.utc)

    # Find tasks past lease expiry
    res = await db.execute(
        select(Task)
        .where(
            and_(
                Task.status == "PROCESSING",
                Task.lease_expires_at <= now
            )
        )
    )
    stale_tasks = res.scalars().all()
    requeued_ids = []

    for task in stale_tasks:
        logger.warning("Reaper: task %s lease expired. Requeuing.", task.id)
        task.status = "PENDING"
        task.worker_id = None
        task.worker_session_id = None
        task.leased_at = None
        task.lease_expires_at = None
        requeued_ids.append(task.id)

    if stale_tasks:
        await db.commit()

    return requeued_ids


async def reset_expired_cooldown_accounts(db: AsyncSession) -> int:
    """Reset accounts from COOLDOWN to READY if quota_reset_at passed."""
    now = datetime.now(timezone.utc)

    res = await db.execute(
        select(GoogleAccount)
        .where(
            and_(
                GoogleAccount.status == ACCOUNT_COOLDOWN,
                GoogleAccount.quota_reset_at <= now
            )
        )
    )
    expired_accounts = res.scalars().all()
    count = 0

    for acc in expired_accounts:
        logger.info("Reaper: resetting expired COOLDOWN for %s -> READY", acc.email)
        acc.status = ACCOUNT_READY
        acc.quota_reset_at = None
        count += 1

    if expired_accounts:
        await db.commit()

    return count


async def find_scale_down_worker(db: AsyncSession, active_emails: list[str]) -> str | None:
    """
    Find an IDLE worker candidate for scale-down.
    Target must be IDLE for longer than SCALE_DOWN_IDLE_SECONDS.
    Ensures at least KEEP_WARM_WORKERS remain.
    Returns email to scale down, or None.
    """
    if len(active_emails) <= KEEP_WARM_WORKERS:
        return None

    # Check if there are pending/processing tasks
    # Scale down only when queue is empty
    res_tasks = await db.execute(
        select(func.count(Task.id))
        .where(Task.status.in_(["PENDING", "PROCESSING"]))
    )
    if (res_tasks.scalar() or 0) > 0:
        return None

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=SCALE_DOWN_IDLE_SECONDS)

    # Get accounts that are IDLE and active
    res = await db.execute(
        select(GoogleAccount)
        .where(
            and_(
                GoogleAccount.email.in_(active_emails),
                GoogleAccount.runtime_status == RUNTIME_IDLE,
                GoogleAccount.last_active < cutoff
            )
        )
        .order_by(GoogleAccount.last_active.asc())
        .limit(1)
    )
    acc = res.scalar_one_or_none()
    return acc.email if acc else None
