def test_lifecycle_constants():
    from app.lifecycle.constants import (
        ACCOUNT_READY,
        ACCOUNT_NEEDS_LOGIN,
        ACCOUNT_COOLDOWN,
        ACCOUNT_DISABLED,
        RUNTIME_STARTING_BROWSER,
        RUNTIME_CONNECTING_RUNTIME,
        RUNTIME_WARMING_MODEL,
        RUNTIME_IDLE,
        RUNTIME_BUSY,
        RUNTIME_DRAINING,
        RUNTIME_STOPPING,
        RUNTIME_LOST,
        WARM_RUNTIME_STATUSES,
        CAPACITY_RUNTIME_STATUSES,
    )

    assert ACCOUNT_READY == "READY"
    assert ACCOUNT_NEEDS_LOGIN == "NEEDS_LOGIN"
    assert ACCOUNT_COOLDOWN == "COOLDOWN"
    assert ACCOUNT_DISABLED == "DISABLED"

    assert RUNTIME_STARTING_BROWSER == "STARTING_BROWSER"
    assert RUNTIME_CONNECTING_RUNTIME == "CONNECTING_RUNTIME"
    assert RUNTIME_WARMING_MODEL == "WARMING_MODEL"
    assert RUNTIME_IDLE == "IDLE"
    assert RUNTIME_BUSY == "BUSY"
    assert RUNTIME_DRAINING == "DRAINING"
    assert RUNTIME_STOPPING == "STOPPING"
    assert RUNTIME_LOST == "LOST"

    assert WARM_RUNTIME_STATUSES == {
        RUNTIME_STARTING_BROWSER,
        RUNTIME_CONNECTING_RUNTIME,
        RUNTIME_WARMING_MODEL,
        RUNTIME_IDLE,
        RUNTIME_BUSY,
    }
    assert CAPACITY_RUNTIME_STATUSES == {
        RUNTIME_STARTING_BROWSER,
        RUNTIME_CONNECTING_RUNTIME,
        RUNTIME_WARMING_MODEL,
        RUNTIME_IDLE,
        RUNTIME_BUSY,
        RUNTIME_DRAINING,
    }

def test_lifecycle_config():
    from app import config

    assert hasattr(config, "KEEP_WARM_WORKERS")
    assert hasattr(config, "MAX_CONCURRENT_WORKERS")
    assert hasattr(config, "SCALE_UP_PENDING_THRESHOLD")
    assert hasattr(config, "SCALE_UP_SUSTAIN_SECONDS")
    assert hasattr(config, "SCALE_DOWN_IDLE_SECONDS")
    assert hasattr(config, "TASK_LEASE_SECONDS")
    assert hasattr(config, "WORKER_HEARTBEAT_TIMEOUT_SECONDS")

    assert config.KEEP_WARM_WORKERS == 1
    assert config.MAX_CONCURRENT_WORKERS == 4
    assert config.SCALE_UP_PENDING_THRESHOLD == 10
    assert config.SCALE_UP_SUSTAIN_SECONDS == 10
    assert config.SCALE_DOWN_IDLE_SECONDS == 1800
    assert config.TASK_LEASE_SECONDS == 300
    assert config.WORKER_HEARTBEAT_TIMEOUT_SECONDS == 60


def test_google_account_columns():
    from app.models import GoogleAccount

    assert GoogleAccount.status.default.arg == "READY"

    assert hasattr(GoogleAccount, "worker_session_id")
    assert hasattr(GoogleAccount, "browser_session_id")
    assert hasattr(GoogleAccount, "runtime_status")
    assert hasattr(GoogleAccount, "current_task_id")
    assert hasattr(GoogleAccount, "last_heartbeat_at")
    assert hasattr(GoogleAccount, "lease_expires_at")


def test_task_columns():
    from app.models import Task

    assert hasattr(Task, "worker_session_id")
    assert hasattr(Task, "attempt")
    assert hasattr(Task, "leased_at")
    assert hasattr(Task, "lease_expires_at")

    assert Task.attempt.default.arg == 0


import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
import sqlalchemy as sa
from datetime import datetime, timezone

@pytest.mark.asyncio
async def test_db_migration_and_backfill(monkeypatch, tmp_path):
    db_file = tmp_path / "test_db.sqlite3"
    test_db_url = f"sqlite+aiosqlite:///{db_file}"

    test_engine = create_async_engine(test_db_url, echo=False)
    test_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    import app.database
    monkeypatch.setattr(app.database, "engine", test_engine)
    monkeypatch.setattr(app.database, "async_session", test_session)

    async with test_engine.begin() as conn:
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS google_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email VARCHAR UNIQUE NOT NULL,
                profile_name VARCHAR NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'OFFLINE',
                last_active DATETIME,
                quota_reset_at DATETIME,
                colab_pid INTEGER,
                started_at DATETIME
            )
        """))
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS tasks (
                id VARCHAR PRIMARY KEY,
                text TEXT NOT NULL,
                voice_id INTEGER NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'PENDING',
                worker_id INTEGER,
                result_audio_path VARCHAR,
                error_message TEXT,
                language VARCHAR,
                batch_id VARCHAR,
                webhook_url VARCHAR,
                user_id INTEGER,
                created_at DATETIME,
                completed_at DATETIME
            )
        """))

    async with test_session() as session:
        now_str = datetime.now(timezone.utc).isoformat()
        await session.execute(sa.text(
            f"INSERT INTO google_accounts (email, profile_name, status, last_active, started_at) VALUES "
            f"('off@test.com', 'off', 'OFFLINE', '{now_str}', '{now_str}')"
        ))
        await session.execute(sa.text(
            f"INSERT INTO google_accounts (email, profile_name, status, last_active, started_at) VALUES "
            f"('conn@test.com', 'conn', 'CONNECTING', NULL, NULL)"
        ))
        await session.execute(sa.text(
            f"INSERT INTO google_accounts (email, profile_name, status, last_active, started_at) VALUES "
            f"('load@test.com', 'load', 'LOADING', NULL, NULL)"
        ))
        await session.execute(sa.text(
            f"INSERT INTO google_accounts (email, profile_name, status, last_active, started_at) VALUES "
            f"('act@test.com', 'act', 'ACTIVE', '{now_str}', '{now_str}')"
        ))
        await session.execute(sa.text(
            f"INSERT INTO google_accounts (email, profile_name, status, last_active, started_at) VALUES "
            f"('busy@test.com', 'busy', 'BUSY', '{now_str}', '{now_str}')"
        ))
        await session.commit()

    from app.database import init_db
    await init_db()

    async with test_session() as session:
        from app.models import GoogleAccount, Task

        res = await session.execute(sa.select(GoogleAccount).order_by(GoogleAccount.id))
        accounts = res.scalars().all()

        assert len(accounts) == 5

        a_off = next(a for a in accounts if a.email == "off@test.com")
        assert a_off.status == "READY"
        assert a_off.runtime_status is None

        a_conn = next(a for a in accounts if a.email == "conn@test.com")
        assert a_conn.status == "READY"
        assert a_conn.runtime_status == "CONNECTING_RUNTIME"

        a_load = next(a for a in accounts if a.email == "load@test.com")
        assert a_load.status == "READY"
        assert a_load.runtime_status == "WARMING_MODEL"

        a_act = next(a for a in accounts if a.email == "act@test.com")
        assert a_act.status == "READY"
        assert a_act.runtime_status == "IDLE"
        assert a_act.last_heartbeat_at is not None

        a_busy = next(a for a in accounts if a.email == "busy@test.com")
        assert a_busy.status == "READY"
        assert a_busy.runtime_status == "BUSY"
        assert a_busy.last_heartbeat_at is not None

        task_id = "test-task-123"
        new_task = Task(
            id=task_id,
            text="hello world",
            voice_id=1,
            status="PENDING",
            worker_session_id="session-xyz",
            attempt=1,
            leased_at=datetime.now(timezone.utc),
            lease_expires_at=datetime.now(timezone.utc)
        )
        session.add(new_task)
        await session.commit()

        res_task = await session.execute(sa.select(Task).where(Task.id == task_id))
        queried_task = res_task.scalar_one()
        assert queried_task.worker_session_id == "session-xyz"
        assert queried_task.attempt == 1
        assert queried_task.leased_at is not None
        assert queried_task.lease_expires_at is not None

    await test_engine.dispose()
