import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.models import GoogleAccount, Task, Voice
from app.models.user import UsageRecord
from app.lifecycle.sessions import (
    reserve_account_for_browser_launch,
    validate_worker_registration,
    lease_task_to_worker_session,
    validate_task_ownership,
    release_worker_session_after_stop,
)
from app.lifecycle.constants import RUNTIME_STARTING_BROWSER, RUNTIME_IDLE, RUNTIME_BUSY
from app.database import async_session, init_db


@pytest.mark.asyncio
async def test_session_lifecycle_and_verification_rules():
    await init_db()
    async with async_session() as db:
        # Cleanup
        await db.execute(UsageRecord.__table__.delete())
        await db.execute(Task.__table__.delete())
        await db.execute(GoogleAccount.__table__.delete())
        await db.execute(Voice.__table__.delete())
        await db.commit()

        voice = Voice(name="session_voice", audio_path="mock.wav")
        db.add(voice)
        await db.commit()
        await db.refresh(voice)

        # 1. Test reserve_account_for_browser_launch
        # When empty, returns None
        assert await reserve_account_for_browser_launch(db) is None

        # Add mock ready account
        acc = GoogleAccount(email="work@gmail.com", profile_name="work", status="READY")
        db.add(acc)
        await db.commit()
        await db.refresh(acc)

        res = await reserve_account_for_browser_launch(db)
        assert res is not None
        email, browser_sid = res
        assert email == "work@gmail.com"
        assert browser_sid is not None

        # Verify DB updated
        assert acc.browser_session_id == browser_sid
        assert acc.runtime_status == RUNTIME_STARTING_BROWSER

        # Reserve again -> returns None (already reserved)
        assert await reserve_account_for_browser_launch(db) is None

        # 2. Test validate_worker_registration
        # Register with invalid email -> returns False
        assert await validate_worker_registration(db, "invalid@gmail.com", "ws_1") is False

        # Register with correct email -> returns True, updates status
        assert await validate_worker_registration(db, "work@gmail.com", "ws_1") is True
        assert acc.worker_session_id == "ws_1"
        assert acc.runtime_status == RUNTIME_IDLE
        assert acc.started_at is not None

        # 3. Test lease_task_to_worker_session
        task = Task(id="t1", text="text", voice_id=voice.id, status="PENDING")
        db.add(task)
        await db.commit()

        assert await lease_task_to_worker_session(db, task, "work@gmail.com", "ws_1") is True
        assert task.status == "PROCESSING"
        assert task.worker_session_id == "ws_1"
        assert task.worker_id == acc.id
        assert task.attempt == 1
        assert task.leased_at is not None
        assert task.lease_expires_at is not None

        assert acc.runtime_status == RUNTIME_BUSY
        assert acc.current_task_id == "t1"

        # Lease again -> should fail because worker is not IDLE anymore
        task2 = Task(id="t2", text="text", voice_id=voice.id, status="PENDING")
        db.add(task2)
        await db.commit()
        assert await lease_task_to_worker_session(db, task2, "work@gmail.com", "ws_1") is False

        # 4. Test validate_task_ownership
        assert await validate_task_ownership(db, "t1", "work@gmail.com", "ws_1") is True
        # Wrong session id -> False
        assert await validate_task_ownership(db, "t1", "work@gmail.com", "ws_wrong") is False
        # Wrong task id -> False
        assert await validate_task_ownership(db, "t2", "work@gmail.com", "ws_1") is False

        # 5. Test release_worker_session_after_stop
        await release_worker_session_after_stop(db, "work@gmail.com")
        assert acc.worker_session_id is None
        assert acc.browser_session_id is None
        assert acc.runtime_status is None
        assert acc.current_task_id is None
        assert acc.last_heartbeat_at is None
        assert acc.lease_expires_at is None
        assert acc.colab_pid is None

        # Cleanup voice
        await db.delete(voice)
        await db.commit()
