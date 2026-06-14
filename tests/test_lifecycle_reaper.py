import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.models import GoogleAccount, Task, Voice
from app.models.user import UsageRecord
from app.lifecycle.reaper import (
    reap_stale_sessions,
    reap_expired_task_leases,
    reset_expired_cooldown_accounts,
    find_scale_down_worker,
)
from app.lifecycle.constants import ACCOUNT_COOLDOWN, ACCOUNT_READY, RUNTIME_LOST, RUNTIME_IDLE, RUNTIME_BUSY
from app.database import async_session, init_db


@pytest.mark.asyncio
async def test_reaper_periodic_maintenance_rules():
    await init_db()
    async with async_session() as db:
        # Cleanup
        await db.execute(UsageRecord.__table__.delete())
        await db.execute(Task.__table__.delete())
        await db.execute(GoogleAccount.__table__.delete())
        await db.execute(Voice.__table__.delete())
        await db.commit()

        voice = Voice(name="reaper_voice", audio_path="mock.wav")
        db.add(voice)
        await db.commit()
        await db.refresh(voice)

        now = datetime.now(timezone.utc)

        # 1. Test reap_stale_sessions
        acc1 = GoogleAccount(
            email="stale@gmail.com",
            profile_name="stale",
            status="READY",
            runtime_status=RUNTIME_IDLE,
            worker_session_id="ws_stale",
            last_heartbeat_at=now - timedelta(seconds=70) # stale > 60s
        )
        acc2 = GoogleAccount(
            email="fresh@gmail.com",
            profile_name="fresh",
            status="READY",
            runtime_status=RUNTIME_IDLE,
            worker_session_id="ws_fresh",
            last_heartbeat_at=now - timedelta(seconds=10) # fresh
        )
        db.add_all([acc1, acc2])
        await db.commit()
        await db.refresh(acc1)
        await db.refresh(acc2)

        stale_emails = await reap_stale_sessions(db)
        assert stale_emails == ["stale@gmail.com"]
        assert acc1.runtime_status == RUNTIME_LOST
        assert acc2.runtime_status == RUNTIME_IDLE

        # 2. Test reap_expired_task_leases
        t1 = Task(
            id="t_stale",
            text="stale",
            voice_id=voice.id,
            status="PROCESSING",
            worker_id=acc1.id,
            worker_session_id="ws_stale",
            lease_expires_at=now - timedelta(seconds=1)
        )
        t2 = Task(
            id="t_fresh",
            text="fresh",
            voice_id=voice.id,
            status="PROCESSING",
            worker_id=acc2.id,
            worker_session_id="ws_fresh",
            lease_expires_at=now + timedelta(seconds=100)
        )
        db.add_all([t1, t2])
        await db.commit()

        requeued = await reap_expired_task_leases(db)
        assert requeued == ["t_stale"]
        assert t1.status == "PENDING"
        assert t1.worker_session_id is None
        assert t2.status == "PROCESSING"

        # 3. Test reset_expired_cooldown_accounts
        acc_cd1 = GoogleAccount(
            email="cd1@gmail.com",
            profile_name="cd1",
            status=ACCOUNT_COOLDOWN,
            quota_reset_at=now - timedelta(seconds=1)
        )
        acc_cd2 = GoogleAccount(
            email="cd2@gmail.com",
            profile_name="cd2",
            status=ACCOUNT_COOLDOWN,
            quota_reset_at=now + timedelta(seconds=100)
        )
        db.add_all([acc_cd1, acc_cd2])
        await db.commit()

        reset_count = await reset_expired_cooldown_accounts(db)
        assert reset_count == 1
        assert acc_cd1.status == ACCOUNT_READY
        assert acc_cd1.quota_reset_at is None
        assert acc_cd2.status == ACCOUNT_COOLDOWN

        # 4. Test find_scale_down_worker
        # Keep warm target = 1 (config.KEEP_WARM_WORKERS = 1)
        # Setup: two active idle workers, no pending work
        await db.execute(Task.__table__.delete())
        await db.commit()

        acc_idle1 = GoogleAccount(
            email="idle1@gmail.com",
            profile_name="i1",
            status="READY",
            runtime_status=RUNTIME_IDLE,
            last_active=now - timedelta(seconds=2000),
            idle_since=now - timedelta(seconds=2000) # idle longer than 1800s
        )
        acc_idle2 = GoogleAccount(
            email="idle2@gmail.com",
            profile_name="i2",
            status="READY",
            runtime_status=RUNTIME_IDLE,
            last_active=now - timedelta(seconds=100),
            idle_since=now - timedelta(seconds=100) # idle 100s
        )
        db.add_all([acc_idle1, acc_idle2])
        await db.commit()

        # active: idle1, idle2, fresh (3 workers)
        # Should pick idle1 (longest idle > 1800s)
        candidate = await find_scale_down_worker(db, ["idle1@gmail.com", "idle2@gmail.com", "fresh@gmail.com"])
        assert candidate == "idle1@gmail.com"

        # If only 1 active worker left, should NOT scale down (respect KEEP_WARM_WORKERS)
        candidate2 = await find_scale_down_worker(db, ["idle1@gmail.com"])
        assert candidate2 is None

        # Cleanup voice
        await db.delete(voice)
        await db.commit()
