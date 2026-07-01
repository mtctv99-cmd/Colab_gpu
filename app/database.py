"""SQLAlchemy database setup with async SQLite engine."""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event

from app.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"timeout": 30})
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables defined by ORM models."""
    # Import all models so they register with Base.metadata
    from app.models import GoogleAccount, Voice, Task, WorkerSession
    from app.models.user import User, ApiKey, UsageRecord

    import sqlalchemy as sa

    async with engine.connect() as conn:
        await conn.execute(sa.text("PRAGMA busy_timeout=30000"))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Drop orphaned llm_tasks table if it exists from legacy version
    try:
        async with async_session() as session:
            await session.execute(sa.text("DROP TABLE IF EXISTS llm_tasks"))
            await session.commit()
    except Exception:
        pass

    # Run manual migrations for SQLite (idempotent)
    _MIGRATIONS = [
        "ALTER TABLE tasks ADD COLUMN language VARCHAR",
        "ALTER TABLE google_accounts ADD COLUMN started_at DATETIME",
        "ALTER TABLE tasks ADD COLUMN user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE users ADD COLUMN last_login_at DATETIME",
        "CREATE INDEX IF NOT EXISTS ix_usage_records_user_id ON usage_records(user_id)",
        "ALTER TABLE google_accounts ADD COLUMN worker_session_id VARCHAR",
        "ALTER TABLE google_accounts ADD COLUMN runtime_status VARCHAR",
        "ALTER TABLE google_accounts ADD COLUMN current_task_id VARCHAR",
        "ALTER TABLE google_accounts ADD COLUMN last_heartbeat_at DATETIME",
        "ALTER TABLE google_accounts ADD COLUMN lease_expires_at DATETIME",
        "ALTER TABLE tasks ADD COLUMN worker_session_id VARCHAR",
        "ALTER TABLE tasks ADD COLUMN attempt INTEGER DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN leased_at DATETIME",
        "ALTER TABLE tasks ADD COLUMN lease_expires_at DATETIME",
        "ALTER TABLE google_accounts ADD COLUMN idle_since DATETIME",
        "ALTER TABLE google_accounts ADD COLUMN assigned_node_id VARCHAR",
        "ALTER TABLE api_keys ADD COLUMN expires_at DATETIME",
        "ALTER TABLE api_keys ADD COLUMN rate_limit INTEGER",
        "ALTER TABLE api_keys ADD COLUMN allowed_ips VARCHAR",
        "ALTER TABLE api_keys ADD COLUMN notes VARCHAR",
        "ALTER TABLE usage_records ADD COLUMN type VARCHAR DEFAULT 'tts'",
        "CREATE INDEX IF NOT EXISTS ix_tasks_status_created_at ON tasks(status, created_at)",
        # Missing indexes — critical for performance as tables grow
        "CREATE INDEX IF NOT EXISTS ix_tasks_voice_id ON tasks(voice_id)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_batch_id ON tasks(batch_id)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_user_id ON tasks(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_api_keys_user_id ON api_keys(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_usage_records_created_at ON usage_records(created_at)",
        "CREATE INDEX IF NOT EXISTS ix_worker_sessions_email ON worker_sessions(email)",
        "CREATE INDEX IF NOT EXISTS ix_google_accounts_status ON google_accounts(status)",
    ]
    for sql in _MIGRATIONS:
        try:
            async with async_session() as session:
                await session.execute(sa.text(sql))
                await session.commit()
        except Exception:
            pass

    # Fix Windows-style paths in voices table for Linux hosts
    from pathlib import Path
    from app.config import VOICES_DIR
    try:
        async with async_session() as session:
            voices = await session.execute(sa.text("SELECT id, audio_path FROM voices"))
            for row in voices.fetchall():
                vid, apath = row
                apath = apath.replace("\\", "/")
                if ":" in apath:
                    parts = apath.split("/")
                    if "voices" in parts:
                        idx = parts.index("voices")
                        slug = parts[idx + 1] if idx + 1 < len(parts) else ""
                        wav = parts[-1] if parts else "ref.wav"
                        fixed = str(VOICES_DIR / slug / wav)
                        await session.execute(sa.text("UPDATE voices SET audio_path = :p WHERE id = :id"), {"p": fixed, "id": vid})
                        logger = __import__("logging").getLogger(__name__)
                        logger.info("Fixed audio_path for voice %s: %s → %s", vid, apath, fixed)
            await session.commit()
    except Exception:
        pass


async def get_db():
    """Dependency that yields a database session."""
    async with async_session() as session:
        yield session
