"""SQLAlchemy database setup with async SQLite engine."""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables defined by ORM models."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Run manual migration for SQLite: Add language column to tasks if missing
    try:
        from sqlalchemy import text
        async with async_session() as session:
            # Check if language column exists in tasks
            await session.execute(text("ALTER TABLE tasks ADD COLUMN language VARCHAR"))
            await session.commit()
    except Exception:
        # Silently ignore if column already exists
        pass


async def get_db():
    """Dependency that yields a database session."""
    async with async_session() as session:
        yield session
