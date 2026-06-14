import pytest
import uuid
import asyncio
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from app.main import app
from app.routes.auth import require_admin
from app.database import init_db, async_session
from app.models import GoogleAccount, Task, Voice
from app.models.user import User, UsageRecord
from app.lifecycle.constants import ACCOUNT_READY, RUNTIME_IDLE, RUNTIME_BUSY


# Mock auth dependency
def mock_require_admin():
    return {"role": "admin"}


@pytest.mark.asyncio
async def test_complete_worker_session_lifecycle_flow():
    app.dependency_overrides[require_admin] = mock_require_admin
    await init_db()

    # Mock profile directory to allow play_runner.start_colab_worker to pass initial checks
    from app.config import PROFILES_DIR
    import shutil
    from pathlib import Path

    mock_profile_path = PROFILES_DIR / "simulated_worker@gmail.com"
    mock_profile_path.mkdir(parents=True, exist_ok=True)

    try:
        with TestClient(app) as client:
            async with async_session() as db:
                # 1. Setup clean state
                await db.execute(UsageRecord.__table__.delete())
                await db.execute(Task.__table__.delete())
                await db.execute(GoogleAccount.__table__.delete())
                await db.execute(Voice.__table__.delete())
                await db.commit()

                voice = Voice(id=1, name="test_voice", audio_path="mock.wav")
                db.add(voice)

                # 2. Add READY GoogleAccount
                acc = GoogleAccount(
                    email="simulated_worker@gmail.com",
                    profile_name="simulated_worker",
                    status=ACCOUNT_READY
                )
                db.add(acc)
                await db.commit()
                await db.refresh(acc)
                acc_id = acc.id

            # 3. Simulate Admin starting worker
            # Mock play_runner.start_colab_worker to avoid actually booting headed Chrome/Playwright in unit test
            from unittest.mock import AsyncMock
            with patch("app.automation.play_runner.start_colab_worker", new_callable=AsyncMock) as mock_start:
                response = client.post(f"/api/accounts/{acc_id}/start")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "STARTING_BACKGROUND"
                browser_sid = data["browser_session_id"]
                assert browser_sid is not None

                # Wait for any background task thread/task to yield
                await asyncio.sleep(0.1)

            # Verify DB reserved state
            async with async_session() as db:
                acc_db = await db.get(GoogleAccount, acc_id)
                assert acc_db.browser_session_id == browser_sid
                assert acc_db.runtime_status == "STARTING_BROWSER"

            # 4. Simulate WebSocket connection & registration
            from app.lifecycle.sessions import validate_worker_registration
            worker_sid = str(uuid.uuid4())
            async with async_session() as db:
                # Registration must succeed since browser_session_id matches
                success = await validate_worker_registration(db, "simulated_worker@gmail.com", worker_sid)
                assert success is True

                acc_db = await db.get(GoogleAccount, acc_id)
                assert acc_db.worker_session_id == worker_sid
                assert acc_db.runtime_status == RUNTIME_IDLE

            # 5. Add pending task and attempt dispatch
            async with async_session() as db:
                task = Task(
                    id="task_sim",
                    text="Hello world simulation",
                    voice_id=1,
                    status="PENDING"
                )
                db.add(task)
                await db.commit()

            # Call ws dispatch
            from app.routes.ws import _try_dispatch_next_task
            from app.routes.ws import manager
            manager.active["simulated_worker@gmail.com"] = "mock_websocket_conn"
            manager.worker_info["simulated_worker@gmail.com"] = {
                "gpu": "cpu",
                "connected_at": datetime.now(timezone.utc),
                "status": "IDLE",
                "worker_session_id": worker_sid
            }

            # Dispatch should run
            # Mock manager.send_task to return True
            with patch.object(manager, "send_task", return_value=True) as mock_send:
                await _try_dispatch_next_task("simulated_worker@gmail.com")
                assert mock_send.called

            # Verify task is now PROCESSING and leased to the worker session
            async with async_session() as db:
                task_db = await db.get(Task, "task_sim")
                assert task_db.status == "PROCESSING"
                assert task_db.worker_session_id == worker_sid
                assert task_db.worker_id == acc_id

                acc_db = await db.get(GoogleAccount, acc_id)
                assert acc_db.runtime_status == RUNTIME_BUSY
                assert acc_db.current_task_id == "task_sim"
                assert manager.worker_info["simulated_worker@gmail.com"]["status"] == "BUSY"

            # 6. Simulate worker complete task with matching session ID
            # Create a mock audio file
            import io
            audio_file = io.BytesIO(b"RIFF....WAVEfmt ....data....")
            response = client.post(
                "/api/tasks/task_sim/complete",
                data={"worker_session_id": worker_sid},
                files={"audio": ("result.wav", audio_file, "audio/wav")}
            )
            assert response.status_code == 200

            # Verify task is COMPLETED and worker status reset to IDLE
            async with async_session() as db:
                task_db = await db.get(Task, "task_sim")
                assert task_db.status == "COMPLETED"
                assert task_db.result_audio_path is not None

                acc_db = await db.get(GoogleAccount, acc_id)
                assert acc_db.runtime_status == RUNTIME_IDLE
                assert acc_db.current_task_id is None
                assert manager.worker_info["simulated_worker@gmail.com"]["status"] == "IDLE"

            # 7. Simulate worker complete task with MISMATCHING session ID (should fail)
            # Setup another task
            async with async_session() as db:
                task2 = Task(
                    id="task_sim2",
                    text="Second simulation",
                    voice_id=1,
                    status="PENDING"
                )
                db.add(task2)
                await db.commit()

            # Dispatch task2
            with patch.object(manager, "send_task", return_value=True) as mock_send:
                await _try_dispatch_next_task("simulated_worker@gmail.com")

            # Complete task2 with WRONG session id
            audio_file2 = io.BytesIO(b"RIFF....WAVEfmt ....data....")
            response = client.post(
                "/api/tasks/task_sim2/complete",
                data={"worker_session_id": "wrong_session_id"},
                files={"audio": ("result.wav", audio_file2, "audio/wav")}
            )
            # Should return 403 Forbidden
            assert response.status_code == 403

            # Verify task2 remains PROCESSING
            async with async_session() as db:
                task2_db = await db.get(Task, "task_sim2")
                assert task2_db.status == "PROCESSING"

            # 8. Simulate worker stop / disconnect
            # Call stop worker API
            with patch("app.automation.play_runner._registry.stop_one", new_callable=AsyncMock) as mock_stop:
                response = client.post(f"/api/accounts/{acc_id}/stop")
                assert response.status_code == 200
                assert mock_stop.called

            # Verify session fields in DB are cleaned up
            async with async_session() as db:
                acc_db = await db.get(GoogleAccount, acc_id)
                assert acc_db.worker_session_id is None
                assert acc_db.browser_session_id is None
                assert acc_db.runtime_status is None
                assert acc_db.colab_pid is None

            # Clean manager state
            manager.disconnect("simulated_worker@gmail.com")

    finally:
        # Cleanup mock profile dir
        if mock_profile_path.exists():
            shutil.rmtree(mock_profile_path)

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ws_handle_status_idle_since_and_last_active():
    from app.routes.ws import _handle_status, manager
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select

    await init_db()
    async with async_session() as db:
        # Cleanup
        await db.execute(UsageRecord.__table__.delete())
        await db.execute(Task.__table__.delete())
        await db.execute(GoogleAccount.__table__.delete())
        await db.execute(Voice.__table__.delete())
        await db.commit()

        # Add Google account
        initial_last_active = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
        acc = GoogleAccount(
            email="ws_status_test@gmail.com",
            profile_name="ws_status_test",
            status="READY",
            runtime_status="CONNECTING_RUNTIME",
            last_active=initial_last_active,
            idle_since=None
        )
        db.add(acc)
        await db.commit()

    # 1. Update status to IDLE (first time)
    # This should set idle_since to now, update last_heartbeat_at, but NOT update last_active
    await _handle_status("ws_status_test@gmail.com", "IDLE")

    async with async_session() as db:
        res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == "ws_status_test@gmail.com"))
        acc_db = res.scalar_one()
        assert acc_db.runtime_status == "IDLE"
        assert acc_db.idle_since is not None
        first_idle_since = acc_db.idle_since
        assert acc_db.last_active == initial_last_active  # UNCHANGED!
        assert acc_db.last_heartbeat_at is not None

    # 2. Update status to IDLE again (heartbeat)
    # This should keep the same idle_since (not update it), and NOT update last_active
    await asyncio.sleep(0.01) # ensure clock could tick
    await _handle_status("ws_status_test@gmail.com", "IDLE")

    async with async_session() as db:
        res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == "ws_status_test@gmail.com"))
        acc_db = res.scalar_one()
        assert acc_db.idle_since == first_idle_since  # UNCHANGED!
        assert acc_db.last_active == initial_last_active  # UNCHANGED!

    # 3. Update status to BUSY (non-IDLE)
    # This should clear idle_since (set to None) and NOT update last_active
    await _handle_status("ws_status_test@gmail.com", "BUSY")

    async with async_session() as db:
        res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == "ws_status_test@gmail.com"))
        acc_db = res.scalar_one()
        assert acc_db.runtime_status == "BUSY"
        assert acc_db.idle_since is None
        assert acc_db.last_active == initial_last_active  # UNCHANGED!

    # 4. Update status to OUT_OF_QUOTA
    # This should clear idle_since (set to None) and set status to COOLDOWN
    # We mock stop_colab_worker to avoid actual system calls
    with patch("app.automation.play_runner.stop_colab_worker", new_callable=AsyncMock) as mock_stop:
        await _handle_status("ws_status_test@gmail.com", "OUT_OF_QUOTA")
        assert mock_stop.called

    async with async_session() as db:
        res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == "ws_status_test@gmail.com"))
        acc_db = res.scalar_one()
        assert acc_db.status == "COOLDOWN"
        assert acc_db.idle_since is None
        assert acc_db.runtime_status is None

