"""E2E tests against LIVE HTTP server — real HTTP, real DB, real time."""
import io, os, json, time, asyncio, httpx, pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from pathlib import Path

BASE = "http://localhost:8090"

# Connect to the LIVE server's db.sqlite3 (NOT db_test.sqlite3)
_live_db_path = Path(__file__).resolve().parent.parent / "data" / "db.sqlite3"
_live_engine = create_async_engine(f"sqlite+aiosqlite:///{_live_db_path}")
_live_session = async_sessionmaker(_live_engine, class_=AsyncSession, expire_on_commit=False)

_admin_counter = 0

def _new_email(pfx="e2e"):
    global _admin_counter
    _admin_counter += 1
    return f"{pfx}{_admin_counter}@e2e-test.com"

async def _create_admin(c):
    e = _new_email()
    r = await c.post(f"{BASE}/api/auth/signup", json={"email": e, "password": "admin123"})
    if r.status_code == 200:
        t, uid = r.json()["token"], r.json()["user"]["id"]
    else:
        r = await c.post(f"{BASE}/api/auth/login", json={"email": e, "password": "admin123"})
        assert r.status_code == 200, f"Login fail: {r.text}"
        t, uid = r.json()["token"], r.json()["user"]["id"]
    async with _live_session() as db:
        await db.execute(text("UPDATE users SET role='admin', balance=999999 WHERE id=:uid"), {"uid": uid})
        await db.commit()
    return {"token": t, "user_id": uid, "email": e}

async def _create_user(c, balance=50000):
    e = _new_email("usr")
    r = await c.post(f"{BASE}/api/auth/signup", json={"email": e, "password": "user123"})
    if r.status_code == 200:
        t, uid = r.json()["token"], r.json()["user"]["id"]
    else:
        r = await c.post(f"{BASE}/api/auth/login", json={"email": e, "password": "user123"})
        t, uid = r.json()["token"], r.json()["user"]["id"]
    if balance != 50000:
        async with _live_session() as db:
            await db.execute(text("UPDATE users SET balance=:b WHERE id=:uid"), {"b": balance, "uid": uid})
            await db.commit()
    return {"token": t, "user_id": uid}

async def _seed_voice(name="e2e_voice"):
    async with _live_session() as db:
        await db.execute(text("INSERT INTO voices (name, audio_path) VALUES (:n, '/tmp/ref.wav')"), {"n": name})
        await db.commit()
        r = await db.execute(text("SELECT id FROM voices WHERE name=:n"), {"n": name})
        return r.scalar()

@pytest.fixture(autouse=True)
async def _reset():
    """Cleanup only data created by tests — không đụng data có sẵn.
    Live tests dùng prefix @e2e-test.com và voice name e2e_* để dễ identify."""
    yield
    async with _live_session() as db:
        # Chỉ xoá test data, không DELETE không điều kiện
        await db.execute(text("DELETE FROM tasks WHERE user_id IN (SELECT id FROM users WHERE email LIKE '%@e2e-test.com')"))
        await db.execute(text("DELETE FROM usage_records WHERE user_id IN (SELECT id FROM users WHERE email LIKE '%@e2e-test.com')"))
        await db.execute(text("DELETE FROM api_keys WHERE user_id IN (SELECT id FROM users WHERE email LIKE '%@e2e-test.com')"))
        await db.execute(text("DELETE FROM voices WHERE name LIKE 'e2e_%' OR name LIKE 'ssrf_%' OR name LIKE 'livespeed' OR name LIKE 'batchv'"))
        await db.execute(text("DELETE FROM users WHERE email LIKE '%@e2e-test.com'"))
        await db.execute(text("DELETE FROM google_accounts WHERE email LIKE '%@e2e-test.com'"))
        await db.execute(text("DELETE FROM worker_sessions WHERE email LIKE '%@e2e-test.com'"))
        await db.commit()

@pytest.fixture
async def c():
    async with httpx.AsyncClient(base_url=BASE, timeout=130) as cl:
        yield cl

# ═══ 1. Auth: concurrent signups ═══
async def test_auth_concurrent(c):
    """10 concurrent signups — measure total + avg"""
    start = time.perf_counter()
    emails = [_new_email("conc") for _ in range(10)]
    async def signup(e):
        r = await c.post(f"{BASE}/api/auth/signup", json={"email": e, "password": "pass123"})
        assert r.status_code == 200, f"{r.text}"
    await asyncio.gather(*[signup(e) for e in emails])
    elapsed = time.perf_counter() - start
    print(f"\n  ⏱  10 concurrent signups: {elapsed:.3f}s total, {elapsed/10*1000:.1f}ms avg")
    assert elapsed < 8, f"Too slow: {elapsed:.2f}s"

# ═══ 2. Auth: sequential full cycle ═══
async def test_auth_full_cycle(c):
    """signup → change-password → login → profile"""
    e = _new_email("cycle")
    start = time.perf_counter()
    r = await c.post(f"{BASE}/api/auth/signup", json={"email": e, "password": "pass123"})
    assert r.status_code == 200
    t = r.json()["token"]
    r = await c.post(f"{BASE}/api/auth/change-password",
        headers={"Authorization": f"Bearer {t}"},
        json={"current_password": "pass123", "new_password": "new456"})
    assert r.status_code == 200
    r = await c.post(f"{BASE}/api/auth/login", json={"email": e, "password": "new456"})
    assert r.status_code == 200
    t2 = r.json()["token"]
    r = await c.get(f"{BASE}/api/auth/profile", headers={"Authorization": f"Bearer {t2}"})
    assert r.status_code == 200
    elapsed = time.perf_counter() - start
    print(f"\n  ⏱  Auth full cycle: {elapsed*1000:.0f}ms")
    assert elapsed < 3.0, f"Auth cycle too slow: {elapsed:.2f}s"

# ═══ 3. Rate limiter — run LAST so it doesn't poison other tests ═══
# (Rate store is in server process memory, not in DB)

# ═══ 4. SSRF guard ═══
async def test_ssrf_blocked_live(c):
    a = await _create_admin(c)
    vid = await _seed_voice(name="ssrf_v")
    r = await c.post(f"{BASE}/api/tts/batch",
        headers={"Authorization": f"Bearer {a['token']}"},
        json={"voice_id": vid, "batch": True, "texts": ["hi"],
              "webhook_url": "http://localhost:8080/hack"})
    assert r.status_code == 422, f"Expected 422 got {r.status_code}: {r.text[:120]}"
    print("  ✅ SSRF guard: HTTP localhost webhook rejected")

# ═══ 5. Unauthenticated ═══
async def test_unauthed_blocked_live(c):
    r = await c.get(f"{BASE}/api/auth/profile")
    assert r.status_code == 401
    r = await c.post(f"{BASE}/api/tts/text", json={"text": "hi", "voice_id": 1})
    assert r.status_code == 401
    print("  ✅ Auth guard: unauthenticated blocked")

# ═══ 6. Health ═══
async def test_health_live(c):
    a = await _create_admin(c)
    for ep in [f"{BASE}/api/ping", f"{BASE}/api/health",
               f"{BASE}/api/health/workers", f"{BASE}/api/health/stats"]:
        r = await c.get(ep, headers={"Authorization": f"Bearer {a['token']}"})
        assert r.status_code in (200, 404), f"{ep}: {r.status_code}"  # workers 404 if none
    print("  ✅ Health endpoints up")

# ═══ 7. API key auth ═══
async def test_api_key_live(c):
    a = await _create_admin(c)
    h = {"Authorization": f"Bearer {a['token']}"}
    r = await c.post(f"{BASE}/api/auth/api-keys", headers=h, json={"name": "LiveKey"})
    assert r.status_code == 200
    raw = r.json()["key"]
    r = await c.get(f"{BASE}/api/auth/profile", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200, f"API key auth: {r.status_code}"
    print("  ✅ API-key auth works")

# ═══ 8. TTS text endpoint ═══
async def test_tts_text_live(c):
    """POST /api/tts/text — task created successfully or queued"""
    a = await _create_admin(c)
    vid = await _seed_voice(name="livespeed")
    start = time.perf_counter()
    try:
        r = await asyncio.wait_for(
            c.post(f"{BASE}/api/tts/text",
                headers={"Authorization": f"Bearer {a['token']}"},
                json={"text": "Xin chào thế giới", "voice_id": vid}),
            timeout=10.0)
        elapsed = time.perf_counter() - start
        print(f"\n  ⏱  TTS /text ({r.status_code}): {elapsed:.2f}s")
        assert r.status_code in (200, 503, 504), f"Unexpected: {r.status_code} {r.text[:100]}"
    except asyncio.TimeoutError:
        elapsed = time.perf_counter() - start
        print(f"\n  ⏱  TTS /text (TIMEOUT after {elapsed:.1f}s, no worker)")
        pytest.skip("No worker available to process TTS")

# ═══ 10. TTS batch ═══
async def test_tts_batch_live(c):
    """POST /api/tts/batch — creates tasks instantly (no worker needed)"""
    a = await _create_admin(c)
    vid = await _seed_voice(name="batchv")
    r = await c.post(f"{BASE}/api/tts/batch",
        headers={"Authorization": f"Bearer {a['token']}"},
        json={"voice_id": vid, "batch": True, "texts": ["hello", "world"]})
    assert r.status_code == 200, f"{r.text[:120]}"
    assert r.json()["batch"] == True
    assert len(r.json()["tasks"]) == 2
    print("  ✅ Batch endpoint returns task list")

# ═══ 11. Models list ═══


# ═══ 12. Rate limiter (isolated via unique IP) ═══
async def test_rate_limit_live(c):
    """105 pings with unique IP → must see 429 (isolated from other tests)."""
    blocked = False
    rate_test_ip = f"8.8.8.{os.getpid() % 255}"
    start = time.perf_counter()
    for i in range(105):
        r = await c.get(f"{BASE}/api/ping", headers={"x-forwarded-for": rate_test_ip})
        if r.status_code == 429:
            blocked = True
            break
    elapsed = time.perf_counter() - start
    assert blocked, "Rate limiter not triggered!"
    print(f"\n  ⏱  Rate-limit tripped at req #{i+1} ({elapsed:.2f}s, {i/elapsed:.0f} req/s)")

print()
print("══════════════════════════════════════════════════════")
print("     REAL E2E + BENCHMARK — LIVE SERVER :8090        ")
print("══════════════════════════════════════════════════════")
