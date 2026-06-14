import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.auth import require_admin
from app.database import init_db, async_session
from app.models import GoogleAccount, Task
from app.models.user import UsageRecord, User, ApiKey
from app.lifecycle.constants import ACCOUNT_READY, RUNTIME_IDLE


# Mock require_admin dependency to bypass auth during test
def mock_require_admin():
    return {"role": "admin"}


@pytest.mark.asyncio
async def test_admin_capacity_endpoint():
    app.dependency_overrides[require_admin] = mock_require_admin
    await init_db()

    with TestClient(app) as client:
        async with async_session() as db:
            # Cleanup
            await db.execute(UsageRecord.__table__.delete())
            await db.execute(Task.__table__.delete())
            await db.execute(GoogleAccount.__table__.delete())
            await db.commit()

            # Add mock ready account
            acc = GoogleAccount(
                email="capacity_check@gmail.com",
                profile_name="capacity_check",
                status=ACCOUNT_READY,
                runtime_status=RUNTIME_IDLE,
                worker_session_id="ws_cap_check"
            )
            db.add(acc)
            await db.commit()

        response = client.get("/api/accounts/capacity")
        assert response.status_code == 200
        data = response.json()

        assert "max_concurrent_workers" in data
        assert "keep_warm_workers" in data
        assert "active_capacity" in data
        assert "warm_capacity" in data
        assert "idle_capacity" in data
        assert "busy_capacity" in data
        assert "pending_tasks" in data
        assert "processing_tasks" in data
        assert "ready_accounts" in data

        # Check values
        assert data["idle_capacity"] == 1
        assert data["active_capacity"] == 1

        # Test list_accounts endpoint and verify it returns idle_since
        response_list = client.get("/api/accounts")
        assert response_list.status_code == 200
        accounts_data = response_list.json()
        assert len(accounts_data) == 1
        assert "idle_since" in accounts_data[0]
        # In our DB insertion we didn't specify idle_since, so it should be None
        assert accounts_data[0]["idle_since"] is None

        # Add another account with a non-null idle_since to verify it is returned
        from datetime import datetime, timezone
        async with async_session() as db:
            acc2 = GoogleAccount(
                email="capacity_check2@gmail.com",
                profile_name="capacity_check2",
                status=ACCOUNT_READY,
                runtime_status=RUNTIME_IDLE,
                worker_session_id="ws_cap_check2",
                idle_since=datetime.now(timezone.utc)
            )
            db.add(acc2)
            await db.commit()

        response_list = client.get("/api/accounts")
        assert response_list.status_code == 200
        accounts_data = response_list.json()
        assert len(accounts_data) == 2
        acc2_data = next(a for a in accounts_data if a["email"] == "capacity_check2@gmail.com")
        assert acc2_data["idle_since"] is not None

    # Clean dependency overrides
    app.dependency_overrides.clear()
