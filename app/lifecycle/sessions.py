"""Worker and browser session management, registration, and task leasing."""

import uuid
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GoogleAccount, Task
from app.config import TASK_LEASE_SECONDS
from app.lifecycle.constants import (
    ACCOUNT_READY,
    RUNTIME_STARTING_BROWSER,
    RUNTIME_CONNECTING_RUNTIME,
    RUNTIME_WARMING_MODEL,
    RUNTIME_IDLE,
    RUNTIME_BUSY
)

logger = logging.getLogger(__name__)


async def reserve_account_for_browser_launch(db: AsyncSession, email: str = None) -> tuple[str, str] | None:
    """
    Atomically reserve a READY account.
    Generates a browser_session_id and sets runtime_status to STARTING_BROWSER.
    """
    now = datetime.now(timezone.utc)
    if email:
        res = await db.execute(
            select(GoogleAccount)
            .where(
                and_(
                    GoogleAccount.email == email,
                    GoogleAccount.status == ACCOUNT_READY,
                    GoogleAccount.worker_session_id.is_(None),
                    GoogleAccount.browser_session_id.is_(None)
                )
            )
        )
        acc = res.scalar_one_or_none()
    else:
        # Find oldest used eligible account
        res = await db.execute(
            select(GoogleAccount)
            .where(
                and_(
                    GoogleAccount.status == ACCOUNT_READY,
                    GoogleAccount.worker_session_id.is_(None),
                    GoogleAccount.browser_session_id.is_(None)
                )
            )
            .order_by(GoogleAccount.last_active.asc().nullsfirst())
            .limit(1)
        )
        acc = res.scalar_one_or_none()

    if not acc:
        return None

    browser_sid = str(uuid.uuid4())
    acc.browser_session_id = browser_sid
    acc.runtime_status = RUNTIME_STARTING_BROWSER
    acc.last_active = now

    await db.commit()
    logger.info("Reserved account %s with browser_session_id %s", acc.email, browser_sid)
    return acc.email, browser_sid


async def validate_worker_registration(db: AsyncSession, email: str, worker_session_id: str) -> bool:
    """
    Verify worker register request.
    Valid only if browser_session_id exists and matches target account.
    Sets runtime_status to RUNTIME_IDLE, initializes worker_session_id and started_at.
    """
    now = datetime.now(timezone.utc)
    res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
    acc = res.scalar_one_or_none()

    if not acc or not acc.browser_session_id:
        logger.warning("Worker registration rejected: no active browser lease for %s", email)
        return False

    acc.worker_session_id = worker_session_id
    acc.runtime_status = RUNTIME_IDLE
    acc.last_heartbeat_at = now

    # Reset started_at if fresh worker session (not connecting/loading)
    sa = acc.started_at
    if sa and sa.tzinfo is None:
        sa = sa.replace(tzinfo=timezone.utc)

    if not sa or (now - sa).total_seconds() > 3600 * 4:
        acc.started_at = now
        logger.info("Initialized started_at for worker session %s", email)

    await db.commit()
    logger.info("Worker registration successful for %s (session %s)", email, worker_session_id)
    return True


async def lease_task_to_worker_session(db: AsyncSession, task: Task, email: str, worker_session_id: str) -> bool:
    """
    Lease a pending task to a specific worker session.
    Increments task attempt counter and updates lease timestamps.
    """
    res = await db.execute(
        select(GoogleAccount)
        .where(
            and_(
                GoogleAccount.email == email,
                GoogleAccount.worker_session_id == worker_session_id,
                GoogleAccount.runtime_status == RUNTIME_IDLE
            )
        )
    )
    acc = res.scalar_one_or_none()

    if not acc:
        logger.warning("Lease task %s failed: worker %s session not IDLE or mismatch", task.id, email)
        return False

    now = datetime.now(timezone.utc)
    task.status = "PROCESSING"
    task.worker_id = acc.id
    task.worker_session_id = worker_session_id
    task.attempt = getattr(task, "attempt", 0) + 1
    task.leased_at = now
    task.lease_expires_at = now + timedelta(seconds=TASK_LEASE_SECONDS)

    acc.runtime_status = RUNTIME_BUSY
    acc.current_task_id = task.id

    await db.commit()
    logger.info("Task %s leased to %s (session %s, attempt %d)", task.id, email, worker_session_id, task.attempt)
    return True


async def validate_task_ownership(db: AsyncSession, task_id: str, email: str, worker_session_id: str) -> bool:
    """
    Verify if worker owns the task session.
    Used before accepting completed or failed status.
    """
    res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
    acc = res.scalar_one_or_none()
    if not acc or acc.worker_session_id != worker_session_id:
        return False

    task = await db.get(Task, task_id)
    if not task or task.status != "PROCESSING" or task.worker_session_id != worker_session_id:
        return False

    return True


async def release_worker_session_after_stop(db: AsyncSession, email: str):
    """Clean up account worker/browser session fields after stopped or closed."""
    res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
    acc = res.scalar_one_or_none()
    if acc:
        acc.worker_session_id = None
        acc.browser_session_id = None
        acc.runtime_status = None
        acc.current_task_id = None
        acc.last_heartbeat_at = None
        acc.lease_expires_at = None
        acc.colab_pid = None
        await db.commit()
        logger.info("Released worker session fields for %s", email)
