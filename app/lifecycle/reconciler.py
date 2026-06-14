"""Database state reconciler and startup process cleaner."""

import logging
from datetime import datetime, timezone
from sqlalchemy import select, update

from app.database import async_session
from app.models import GoogleAccount, Task
from app.lifecycle.constants import ACCOUNT_READY, ACCOUNT_COOLDOWN, ACCOUNT_NEEDS_LOGIN, ACCOUNT_DISABLED
from app.automation.play_runner import cleanup_zombie_browsers

logger = logging.getLogger(__name__)


async def startup_cleanup_processes() -> int:
    """Kill lingering Chrome/Playwright processes at startup."""
    logger.info("Cleaning up zombie browser processes on startup...")
    try:
        killed = await cleanup_zombie_browsers(kill_active=True)
        if killed > 0:
            logger.info("Cleaned up %d leftover browser processes.", killed)
        return killed
    except Exception as exc:
        logger.warning("Failed to run startup browser cleanup: %s", exc)
        return 0


async def reconcile_database_on_startup():
    """Reset stale worker sessions and requeue orphan tasks in database."""
    logger.info("Reconciling database state on startup...")
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        try:
            # 1. Reconcile Google accounts
            # Fetch accounts to examine status
            res = await db.execute(select(GoogleAccount))
            accounts = res.scalars().all()

            for acc in accounts:
                # Keep NEEDS_LOGIN and DISABLED
                if acc.status in (ACCOUNT_NEEDS_LOGIN, ACCOUNT_DISABLED):
                    # Still reset runtime fields
                    acc.worker_session_id = None
                    acc.browser_session_id = None
                    acc.runtime_status = None
                    acc.current_task_id = None
                    acc.last_heartbeat_at = None
                    acc.lease_expires_at = None
                    acc.colab_pid = None
                    acc.idle_since = None
                    continue

                # Check if COOLDOWN is still valid
                if acc.status == ACCOUNT_COOLDOWN and acc.quota_reset_at:
                    q_reset = acc.quota_reset_at
                    if q_reset.tzinfo is None:
                        q_reset = q_reset.replace(tzinfo=timezone.utc)

                    if q_reset > now:
                        # Keep COOLDOWN but clear active sessions
                        acc.worker_session_id = None
                        acc.browser_session_id = None
                        acc.runtime_status = None
                        acc.current_task_id = None
                        acc.last_heartbeat_at = None
                        acc.lease_expires_at = None
                        acc.colab_pid = None
                        acc.idle_since = None
                        continue

                # Default to READY
                acc.status = ACCOUNT_READY
                acc.worker_session_id = None
                acc.browser_session_id = None
                acc.runtime_status = None
                acc.current_task_id = None
                acc.last_heartbeat_at = None
                acc.lease_expires_at = None
                acc.colab_pid = None
                acc.idle_since = None

            # 2. Requeue stuck tasks
            await db.execute(
                update(Task)
                .where(Task.status == "PROCESSING")
                .values(
                    status="PENDING",
                    worker_id=None,
                    worker_session_id=None,
                    leased_at=None,
                    lease_expires_at=None
                )
            )

            await db.commit()
            logger.info("Database reconciliation completed successfully.")
        except Exception as e:
            await db.rollback()
            logger.error("Failed to reconcile database state: %s", e)
            raise e
