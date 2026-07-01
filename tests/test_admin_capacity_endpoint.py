"""Test admin capacity endpoint."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_capacity_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/accounts/capacity")
        # Should return 401 since we're not authenticated
        assert resp.status_code in (401,)
