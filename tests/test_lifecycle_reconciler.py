import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.models import GoogleAccount, Task, Voice
from app.models.user import UsageRecord
from app.lifecycle.reconciler import reconcile_database_on_startup
from app.lifecycle.constants import ACCOUNT_READY, ACCOUNT_COOLDOWN, ACCOUNT_NEEDS_LOGIN, ACCOUNT_DISABLED
from app.database import async_session, init_db


@pytest.mark.asyncio
async def test_reconcile_database_on_startup_resets_states():
    await init_db()
    async with async_session() as db:
        # Clear existing data to prevent collisions
        # Delete usage records, then tasks, then accounts, then voices
        await db.execute(UsageRecord.__table__.delete())
        await db.execute(Task.__table__.delete())
        await db.execute(GoogleAccount.__table__.delete())
        await db.execute(Voice.__table__.delete())
        await db.commit()

        # Create a test voice first since Task requires voice_id
        voice = Voice(name="reconciler_voice", audio_path="mock.wav")
        db.add(voice)
        await db.commit()
        await db.refresh(voice)

        now = datetime.now(timezone.utc)

        # Add accounts in various states
        acc1 = GoogleAccount(
            email="ready@gmail.com",
            profile_name="ready",
            status="READY",
            worker_session_id="ws_1",
            browser_session_id="bs_1",
            runtime_status="BUSY",
            current_task_id="t_1",
            colab_pid=9999,
            idle_since=now
        )
        acc2 = GoogleAccount(
            email="cooldown_expired@gmail.com",
            profile_name="cooldown_exp",
            status="COOLDOWN",
            quota_reset_at=now - timedelta(hours=1),
            worker_session_id="ws_2",
            browser_session_id="bs_2",
            idle_since=now
        )
        acc3 = GoogleAccount(
            email="cooldown_active@gmail.com",
            profile_name="cooldown_act",
            status="COOLDOWN",
            quota_reset_at=now + timedelta(hours=2),
            worker_session_id="ws_3",
            browser_session_id="bs_3",
            idle_since=now
        )
        acc4 = GoogleAccount(
            email="login@gmail.com",
            profile_name="login",
            status="NEEDS_LOGIN",
            worker_session_id="ws_4",
            idle_since=now
        )
        acc5 = GoogleAccount(
            email="disabled@gmail.com",
            profile_name="disabled",
            status="DISABLED"
        )

        db.add_all([acc1, acc2, acc3, acc4, acc5])
        await db.commit()
        await db.refresh(acc1)

        # Add tasks
        task1 = Task(
            id="t_1",
            text="text",
            voice_id=voice.id,
            status="PROCESSING",
            worker_id=acc1.id,
            worker_session_id="ws_1",
            leased_at=now,
            lease_expires_at=now + timedelta(minutes=5)
        )
        task2 = Task(
            id="t_2",
            text="text2",
            voice_id=voice.id,
            status="PENDING"
        )

        db.add_all([task1, task2])
        await db.commit()

    # Run reconciler
    await reconcile_database_on_startup()

    async with async_session() as db:
        # Check accounts
        res = await db.execute(select(GoogleAccount).order_by(GoogleAccount.email))
        accounts = res.scalars().all()

        acc_map = {a.email: a for a in accounts}

        # ready@gmail.com -> READY, runtime fields reset
        assert acc_map["ready@gmail.com"].status == ACCOUNT_READY
        assert acc_map["ready@gmail.com"].worker_session_id is None
        assert acc_map["ready@gmail.com"].browser_session_id is None
        assert acc_map["ready@gmail.com"].runtime_status is None
        assert acc_map["ready@gmail.com"].colab_pid is None
        assert acc_map["ready@gmail.com"].idle_since is None

        # cooldown_expired@gmail.com -> READY, runtime fields reset
        assert acc_map["cooldown_expired@gmail.com"].status == ACCOUNT_READY
        assert acc_map["cooldown_expired@gmail.com"].worker_session_id is None
        assert acc_map["cooldown_expired@gmail.com"].idle_since is None

        # cooldown_active@gmail.com -> COOLDOWN remains, runtime fields reset
        assert acc_map["cooldown_active@gmail.com"].status == ACCOUNT_COOLDOWN
        assert acc_map["cooldown_active@gmail.com"].worker_session_id is None
        assert acc_map["cooldown_active@gmail.com"].idle_since is None

        # login@gmail.com -> NEEDS_LOGIN remains, runtime fields reset
        assert acc_map["login@gmail.com"].status == ACCOUNT_NEEDS_LOGIN
        assert acc_map["login@gmail.com"].worker_session_id is None
        assert acc_map["login@gmail.com"].idle_since is None

        # disabled@gmail.com -> DISABLED remains
        assert acc_map["disabled@gmail.com"].status == ACCOUNT_DISABLED

        # Check tasks
        res_tasks = await db.execute(select(Task).order_by(Task.id))
        tasks = res_tasks.scalars().all()
        task_map = {t.id: t for t in tasks}

        assert task_map["t_1"].status == "PENDING"
        assert task_map["t_1"].worker_id is None
        assert task_map["t_1"].worker_session_id is None
        assert task_map["t_1"].leased_at is None
        assert task_map["t_1"].lease_expires_at is None

        assert task_map["t_2"].status == "PENDING"

        # Cleanup test voice
        await db.delete(voice)
        await db.commit()
