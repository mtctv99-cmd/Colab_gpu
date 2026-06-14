import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from app.models import GoogleAccount, Task, Voice
from app.models.user import UsageRecord
from app.lifecycle.capacity import (
    get_active_capacity,
    get_warm_capacity,
    get_idle_capacity,
    get_busy_capacity,
    get_pending_tasks_count,
    get_processing_tasks_count,
    get_ready_accounts_count,
    check_scale_up_trigger,
)
from app.database import async_session, init_db


@pytest.mark.asyncio
async def test_capacity_queries_and_autoscale_trigger():
    await init_db()
    async with async_session() as db:
        # Cleanup
        await db.execute(UsageRecord.__table__.delete())
        await db.execute(Task.__table__.delete())
        await db.execute(GoogleAccount.__table__.delete())
        await db.execute(Voice.__table__.delete())
        await db.commit()

        voice = Voice(name="capacity_voice", audio_path="mock.wav")
        db.add(voice)
        await db.commit()
        await db.refresh(voice)

        # 1. Test query counts when DB empty
        assert await get_active_capacity(db) == 0
        assert await get_warm_capacity(db) == 0
        assert await get_idle_capacity(db) == 0
        assert await get_ready_accounts_count(db) == 0

        # Add mock accounts
        acc1 = GoogleAccount(email="ready1@gmail.com", profile_name="r1", status="READY", runtime_status="IDLE", worker_session_id="ws_1")
        acc2 = GoogleAccount(email="ready2@gmail.com", profile_name="r2", status="READY", runtime_status="BUSY", worker_session_id="ws_2")
        acc3 = GoogleAccount(email="ready3@gmail.com", profile_name="r3", status="READY", runtime_status="STARTING_BROWSER", worker_session_id="ws_3")
        acc4 = GoogleAccount(email="draining@gmail.com", profile_name="dr", status="READY", runtime_status="DRAINING", worker_session_id="ws_4")
        acc5 = GoogleAccount(email="cooldown@gmail.com", profile_name="cd", status="COOLDOWN")
        acc6 = GoogleAccount(email="offline@gmail.com", profile_name="off", status="READY") # ready but no session

        db.add_all([acc1, acc2, acc3, acc4, acc5, acc6])

        # Add tasks
        t1 = Task(id="t1", text="text", voice_id=voice.id, status="PENDING")
        t2 = Task(id="t2", text="text", voice_id=voice.id, status="PROCESSING", worker_id=1, worker_session_id="ws_2")
        db.add_all([t1, t2])
        await db.commit()

        # Test capacity queries
        # active = IDLE, BUSY, STARTING_BROWSER, DRAINING (4)
        assert await get_active_capacity(db) == 4
        # warm = IDLE, BUSY, STARTING_BROWSER (3)
        assert await get_warm_capacity(db) == 3
        # idle = 1
        assert await get_idle_capacity(db) == 1
        # busy = 1
        assert await get_busy_capacity(db) == 1
        # pending tasks = 1
        assert await get_pending_tasks_count(db) == 1
        # processing tasks = 1
        assert await get_processing_tasks_count(db) == 1
        # ready accounts (status=READY and session is null) = offline@gmail.com (1)
        assert await get_ready_accounts_count(db) == 1

        # Cleanup for autoscale trigger test
        await db.execute(Task.__table__.delete())
        await db.execute(GoogleAccount.__table__.delete())
        await db.commit()

        # Autoscale scenario 1: 0 active, 1 ready account, 1 pending task -> should scale up immediately
        acc_r = GoogleAccount(email="r@gmail.com", profile_name="r", status="READY")
        db.add(acc_r)
        task_p = Task(id="tp1", text="t", voice_id=voice.id, status="PENDING")
        db.add(task_p)
        await db.commit()

        assert await check_scale_up_trigger(db) is True

        # Autoscale scenario 2: 1 active, 1 ready, 1 pending -> worker 2 backup -> should scale up
        acc_r.runtime_status = "IDLE"
        acc_r.worker_session_id = "ws_active"
        acc_r2 = GoogleAccount(email="r2@gmail.com", profile_name="r2", status="READY")
        db.add(acc_r2)
        await db.commit()

        assert await check_scale_up_trigger(db) is True

        # Autoscale scenario 3: 2 active, 1 ready, 1 pending -> should NOT scale up (sustain threshold not met)
        acc_r2.runtime_status = "BUSY"
        acc_r2.worker_session_id = "ws_active2"
        acc_r3 = GoogleAccount(email="r3@gmail.com", profile_name="r3", status="READY")
        db.add(acc_r3)
        await db.commit()

        assert await check_scale_up_trigger(db) is False

        # Autoscale scenario 4: 2 active, 1 ready, 10 pending -> first call starts timer, returns False
        for i in range(9):
            db.add(Task(id=f"tp_{i}", text="t", voice_id=voice.id, status="PENDING"))
        await db.commit()

        # Setup mock time
        start_time = 1700000000.0
        with patch("time.time", return_value=start_time):
            # First call starts timer, returns False
            assert await check_scale_up_trigger(db) is False

        # Second call 5s later -> returns False
        with patch("time.time", return_value=start_time + 5.0):
            assert await check_scale_up_trigger(db) is False

        # Third call 10s later -> returns True
        with patch("time.time", return_value=start_time + 10.0):
            assert await check_scale_up_trigger(db) is True

        # Cleanup voice
        await db.delete(voice)
        await db.commit()
