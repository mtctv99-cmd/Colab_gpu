import pytest
import uuid
import asyncio
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from app.main import app
from app.database import init_db, async_session
from app.models import GoogleAccount, Task, Voice
from app.routes.ws import validate_worker_registration, validate_task_ownership

ACCOUNT_READY = "READY"
RUNTIME_IDLE = "IDLE"
RUNTIME_BUSY = "BUSY"


@pytest.mark.asyncio
async def test_orchestrator_constants():
    assert ACCOUNT_READY == "READY"
    assert RUNTIME_IDLE == "IDLE"
    assert RUNTIME_BUSY == "BUSY"


@pytest.mark.asyncio
async def test_validate_worker_registration():
    await init_db()

    wsid = str(uuid.uuid4())
    async with async_session() as db:
        acc = GoogleAccount(
            email=f"test_{uuid.uuid4().hex[:4]}@test.com",
            profile_name="test",
            status="CONNECTING",
            worker_session_id=wsid,
        )
        db.add(acc)
        await db.commit()

        valid = await validate_worker_registration(db, acc.email, wsid)
        assert valid is True

        invalid = await validate_worker_registration(db, acc.email, "wrong-sid")
        assert invalid is False


@pytest.mark.asyncio
async def test_validate_task_ownership():
    await init_db()

    wsid = str(uuid.uuid4())
    async with async_session() as db:
        acc = GoogleAccount(
            email=f"test_{uuid.uuid4().hex[:4]}@test.com",
            profile_name="test",
            status="ACTIVE",
            worker_session_id=wsid,
        )
        db.add(acc)
        await db.commit()

        voice = Voice(name="test", audio_path="/tmp/test.wav", transcript="hello")
        db.add(voice)
        await db.commit()

        task = Task(
            id=str(uuid.uuid4()),
            text="test",
            voice_id=voice.id,
            status="PROCESSING",
            worker_id=acc.id,
            worker_session_id=wsid,
        )
        db.add(task)
        await db.commit()

        valid = await validate_task_ownership(db, task.id, acc.email, wsid)
        assert valid is True

        invalid = await validate_task_ownership(db, task.id, acc.email, "wrong-sid")
        assert invalid is False
