"""End-to-end API tests for all endpoints.

Tests run against a fresh SQLite DB via FastAPI TestClient.
Covers: auth, accounts, voices, tasks, TTS, health.
"""
import io
import os
import json
import pytest
import sys
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from app.database import init_db, async_session



# ── Helpers ───────────────────────────────────────────────────

_admin_counter = 0

def _new_email(prefix="admin") -> str:
    global _admin_counter
    _admin_counter += 1
    return f"{prefix}{_admin_counter}@test.com"


async def _create_admin(c, email=None):
    if email is None:
        email = _new_email("admin")
    r = await c.post("/api/auth/signup", json={"email": email, "password": "admin123"})
    assert r.status_code in (200, 400), f"Signup: {r.text}"
    if r.status_code == 200:
        t, uid = r.json()["token"], r.json()["user"]["id"]
    else:
        r2 = await c.post("/api/auth/login", json={"email": email, "password": "admin123"})
        assert r2.status_code == 200, f"Login: {r2.text}"
        t, uid = r2.json()["token"], r2.json()["user"]["id"]
    async with async_session() as db:
        await db.execute(text("UPDATE users SET role='admin', balance=999999 WHERE id=:uid"), {"uid": uid})
        await db.commit()
    return {"token": t, "user_id": uid, "email": email}


async def _create_user(c, email=None, balance=50000):
    if email is None:
        email = _new_email("usr")
    r = await c.post("/api/auth/signup", json={"email": email, "password": "user123"})
    assert r.status_code in (200, 400), f"Signup: {r.text}"
    if r.status_code == 200:
        t, uid = r.json()["token"], r.json()["user"]["id"]
    else:
        r2 = await c.post("/api/auth/login", json={"email": email, "password": "user123"})
        assert r2.status_code == 200, f"Login: {r2.text}"
        t, uid = r2.json()["token"], r2.json()["user"]["id"]
    async with async_session() as db:
        await db.execute(text("UPDATE users SET balance=:b WHERE id=:uid"), {"b": balance, "uid": uid})
        await db.commit()
    return {"token": t, "user_id": uid}


@pytest.fixture(autouse=True)
async def _reset():
    os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-ci")
    # Safety: không bao giờ chạy cleanup trên production DB
    from app.config import DATABASE_URL
    assert "_test" in str(DATABASE_URL), f"CRITICAL: refusing cleanup on non-test DB: {DATABASE_URL}"
    await init_db()
    yield
    async with async_session() as db:
        for t in ["usage_records", "tasks", "voices", "google_accounts",
                   "worker_sessions", "api_keys", "users"]:
            await db.execute(text(f"DELETE FROM {t}"))
        await db.commit()
    from app.routes.auth import _login_attempts, _login_attempts_ip
    _login_attempts.clear()
    _login_attempts_ip.clear()
    from app.main import _rate_limit_store
    _rate_limit_store.clear()


@pytest.fixture
async def c():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ═══════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════

async def test_signup_login(c):
    e = _new_email("sl")
    r = await c.post("/api/auth/signup", json={"email": e, "password": "pass123"})
    assert r.status_code == 200, r.text
    assert "token" in r.json()
    assert r.json()["user"]["email"] == e

    r2 = await c.post("/api/auth/login", json={"email": e, "password": "pass123"})
    assert r2.status_code == 200, r2.text
    assert "token" in r2.json()

    r3 = await c.post("/api/auth/login", json={"email": e, "password": "wrong"})
    assert r3.status_code in (401, 429)


async def test_profile(c):
    a = await _create_admin(c)
    r = await c.get("/api/auth/profile", headers={"Authorization": f"Bearer {a['token']}"})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


async def test_change_password(c):
    a = await _create_admin(c)
    h = {"Authorization": f"Bearer {a['token']}"}
    r = await c.post("/api/auth/change-password", headers=h,
                     json={"current_password": "admin123", "new_password": "new123"})
    assert r.status_code == 200


async def test_api_key_crud(c):
    a = await _create_admin(c)
    h = {"Authorization": f"Bearer {a['token']}"}
    r = await c.post("/api/auth/api-keys", headers=h, json={"name": "MyKey"})
    assert r.status_code == 200
    raw_key = r.json()["key"]

    r2 = await c.get("/api/auth/api-keys", headers=h)
    assert r2.status_code == 200
    assert len(r2.json()) >= 1

    # Use key for auth
    r3 = await c.get("/api/auth/profile", headers={"Authorization": f"Bearer {raw_key}"})
    assert r3.status_code == 200


async def test_admin_user_mgmt(c):
    a = await _create_admin(c)
    h = {"Authorization": f"Bearer {a['token']}"}
    r = await c.get("/api/auth/admin/users", headers=h)
    assert r.status_code == 200

    r2 = await c.post("/api/auth/admin/users", headers=h,
                      json={"email": "newu@x.com", "password": "pass123", "role": "user"})
    assert r2.status_code == 200
    uid = r2.json()["id"]

    r3 = await c.put(f"/api/auth/admin/users/{uid}", headers=h, json={"balance": 1000})
    assert r3.status_code == 200

    r4 = await c.delete(f"/api/auth/admin/users/{uid}", headers=h)
    assert r4.status_code == 200


async def test_admin_topup(c):
    a = await _create_admin(c)
    h = {"Authorization": f"Bearer {a['token']}"}
    r = await c.post("/api/auth/admin/topup", headers=h,
                     json={"email": a.get("email", "admin1@test.com"), "amount": 500})
    # admin might not have email in our helper, fallback
    if r.status_code == 422:
        async with async_session() as db:
            u = await db.execute(text("SELECT email FROM users WHERE id=:uid"), {"uid": a["user_id"]})
            ue = u.scalar()
        r = await c.post("/api/auth/admin/topup", headers=h,
                         json={"email": ue, "amount": 500})
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 500


async def test_admin_api_key_mgmt(c):
    a = await _create_admin(c)
    h = {"Authorization": f"Bearer {a['token']}"}
    r = await c.post("/api/auth/admin/api-keys", headers=h,
                     json={"user_id": a["user_id"], "name": "AdmKey"})
    assert r.status_code == 200

    r2 = await c.get("/api/auth/admin/api-keys", headers=h)
    assert r2.status_code == 200
    keys = [k for k in r2.json() if k["name"] == "AdmKey"]
    assert len(keys) >= 1
    kid = keys[0]["id"]

    r3 = await c.patch(f"/api/auth/admin/api-keys/{kid}", headers=h, json={"name": "AdmKeyV2"})
    assert r3.status_code == 200

    r4 = await c.get(f"/api/auth/admin/api-keys/{kid}/usage", headers=h)
    assert r4.status_code == 200

    r5 = await c.delete(f"/api/auth/admin/api-keys/{kid}", headers=h)
    assert r5.status_code == 200


async def test_non_admin_blocked(c):
    u = await _create_user(c)
    r = await c.get("/api/auth/admin/users", headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 403


async def test_unauthenticated_blocked(c):
    r = await c.get("/api/auth/profile")
    assert r.status_code == 401
    r2 = await c.post("/api/tts/text", json={"text": "hi", "voice_id": 1})
    assert r2.status_code == 401


# ═══════════════════════════════════════════════════════════════
# ACCOUNTS
# ═══════════════════════════════════════════════════════════════

async def test_accounts_list(c):
    a = await _create_admin(c)
    r = await c.get("/api/accounts", headers={"Authorization": f"Bearer {a['token']}"})
    assert r.status_code == 200


async def test_accounts_capacity(c):
    a = await _create_admin(c)
    r = await c.get("/api/accounts/capacity", headers={"Authorization": f"Bearer {a['token']}"})
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════
# VOICES
# ═══════════════════════════════════════════════════════════════

async def test_voice_crud(c):
    a = await _create_admin(c)
    h = {"Authorization": f"Bearer {a['token']}"}

    # Create voice — requires multipart form with audio file
    fake_audio = io.BytesIO(b"RIFF\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00")
    r = await c.post("/api/voices/", headers=h,
                     data={"name": "TestVoice", "transcript": "hello"},
                     files={"audio": ("test.wav", fake_audio, "audio/wav")})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]

    r2 = await c.get("/api/voices", headers=h)
    assert r2.status_code == 200

    r3 = await c.delete(f"/api/voices/{vid}", headers=h)
    assert r3.status_code == 200


# ═══════════════════════════════════════════════════════════════
# TASKS
# ═══════════════════════════════════════════════════════════════

async def test_task_list_admin(c):
    a = await _create_admin(c)
    r = await c.get("/api/tasks", headers={"Authorization": f"Bearer {a['token']}"})
    assert r.status_code == 200


async def test_task_list_non_admin_blocked(c):
    u = await _create_user(c)
    r = await c.get("/api/tasks", headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 403


async def test_task_detail_requires_admin(c):
    a = await _create_admin(c)
    r = await c.get("/api/tasks/nonexistent", headers={"Authorization": f"Bearer {a['token']}"})
    assert r.status_code == 404
    u = await _create_user(c)
    r2 = await c.get("/api/tasks/nonexistent", headers={"Authorization": f"Bearer {u['token']}"})
    assert r2.status_code == 403


async def test_task_audio_requires_admin(c):
    u = await _create_user(c)
    r = await c.get("/api/tasks/x/audio", headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 403  # requires admin
    a = await _create_admin(c)
    r2 = await c.get("/api/tasks/x/audio", headers={"Authorization": f"Bearer {a['token']}"})
    assert r2.status_code == 404


async def _seed_voice(db, name="test_voice"):
    await db.execute(text("INSERT INTO voices (name, audio_path) VALUES (:n, '/tmp/ref.wav')"), {"n": name})
    await db.commit()
    row = await db.execute(text("SELECT id FROM voices WHERE name=:n"), {"n": name})
    return row.scalar()


async def test_task_complete_no_worker_session_rejected(c):
    """Task with no worker_session_id can't be completed — gets 400."""
    a = await _create_admin(c)
    async with async_session() as db:
        vid = await _seed_voice(db)
        await db.execute(text("INSERT INTO tasks (id, text, voice_id, status, user_id, attempt) VALUES (:tid, 'hi', :vid, 'PENDING', :uid, 0)"),
                         {"tid": "t1", "vid": vid, "uid": a["user_id"]})
        # Seed a real worker session so WS validation passes, then check task.wsid mismatch
        await db.execute(text("INSERT INTO worker_sessions (email, worker_session_id, status) VALUES (:email, :wsid, 'ALIVE')"),
                         {"email": a["email"], "wsid": "wsid-valid"})
        await db.commit()
    audio = io.BytesIO(b"RIFF....")
    r = await c.post("/api/tasks/t1/complete",
                     data={"worker_session_id": "wsid-valid"},
                     files={"audio": ("t.wav", audio, "audio/wav")})
    assert r.status_code == 400, f"Expected 400 (no assigned session), got {r.status_code}: {r.text}"


async def test_task_complete_wrong_session_rejected(c):
    """Wrong worker_session_id → 403."""
    a = await _create_admin(c)
    async with async_session() as db:
        vid = await _seed_voice(db)
        await db.execute(text("INSERT INTO tasks (id, text, voice_id, status, worker_session_id, user_id, attempt) VALUES (:tid, 'hi', :vid, 'PROCESSING', 'wsid-real', :uid, 0)"),
                         {"tid": "t2", "vid": vid, "uid": a["user_id"]})
        # Seed a real worker session so validation reaches task.session mismatch check
        await db.execute(text("INSERT INTO worker_sessions (email, worker_session_id, status) VALUES (:email, :wsid, 'ALIVE')"),
                         {"email": a["email"], "wsid": "wsid-real"})
        await db.commit()
    audio = io.BytesIO(b"RIFF....")
    r = await c.post("/api/tasks/t2/complete",
                     data={"worker_session_id": "wsid-wrong"},
                     files={"audio": ("t.wav", audio, "audio/wav")})
    assert r.status_code == 403


async def test_task_complete_success(c):
    """Matching worker_session_id → 200."""
    a = await _create_admin(c)
    async with async_session() as db:
        vid = await _seed_voice(db)
        await db.execute(text("INSERT INTO tasks (id, text, voice_id, status, worker_session_id, user_id, attempt) VALUES (:tid, 'hi', :vid, 'PROCESSING', 'wsid-ok', :uid, 0)"),
                         {"tid": "t3", "vid": vid, "uid": a["user_id"]})
        # Seed worker session so validation passes
        await db.execute(text("INSERT INTO worker_sessions (email, worker_session_id, status) VALUES (:email, :wsid, 'ALIVE')"),
                         {"email": a["email"], "wsid": "wsid-ok"})
        await db.commit()
    audio = io.BytesIO(b"RIFF....")
    r = await c.post("/api/tasks/t3/complete",
                     data={"worker_session_id": "wsid-ok"},
                     files={"audio": ("t.wav", audio, "audio/wav")})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "COMPLETED"


async def test_user_own_tasks(c):
    u = await _create_user(c)
    r = await c.get("/api/auth/tasks", headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 200


async def test_usage_history(c):
    u = await _create_user(c)
    r = await c.get("/api/auth/usage", headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 200
    assert "balance" in r.json()


async def test_retry_task_not_found(c):
    a = await _create_admin(c)
    r = await c.post("/api/tasks/nonexistent/retry",
                     headers={"Authorization": f"Bearer {a['token']}"})
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════
# TTS
# ═══════════════════════════════════════════════════════════════

async def test_tts_text_empty_rejected(c):
    u = await _create_user(c)
    r = await c.post("/api/tts/text",
                     headers={"Authorization": f"Bearer {u['token']}"},
                     json={"text": "", "voice_id": 999})
    assert r.status_code in (400, 422), r.text


async def test_tts_text_nonexistent_voice(c):
    u = await _create_user(c)
    r = await c.post("/api/tts/text",
                     headers={"Authorization": f"Bearer {u['token']}"},
                     json={"text": "hello", "voice_id": 99999})
    assert r.status_code == 400


async def test_tts_text_insufficient_balance(c):
    u = await _create_user(c, balance=0)
    async with async_session() as db:
        vid = await _seed_voice(db, name="insuf_v")
    r = await c.post("/api/tts/text",
                     headers={"Authorization": f"Bearer {u['token']}"},
                     json={"text": "hello world", "voice_id": vid})
    assert r.status_code == 402, f"Expected 402 insufficient balance, got {r.status_code}: {r.text}"


async def test_tts_batch_nonexistent_voice(c):
    u = await _create_user(c)
    r = await c.post("/api/tts/batch",
                     headers={"Authorization": f"Bearer {u['token']}"},
                     json={"voice_id": 99999, "batch": True, "texts": ["hi"]})
    assert r.status_code == 400


async def test_tts_batch_ssrf_blocked(c):
    a = await _create_admin(c)
    async with async_session() as db:
        vid = await _seed_voice(db, name="ssrf_v")
        await db.commit()
    r = await c.post("/api/tts/batch",
                     headers={"Authorization": f"Bearer {a['token']}"},
                     json={"voice_id": vid, "batch": True, "texts": ["hi"],
                           "webhook_url": "http://localhost:8080/hack"})
    # SSRF guard rejects HTTP webhook URLs
    assert r.status_code == 422, r.text


# ═══════════════════════════════════════════════════════════════
# HEALTH + PING
# ═══════════════════════════════════════════════════════════════

async def test_ping(c):
    r = await c.get("/api/ping")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_health(c):
    a = await _create_admin(c)
    r = await c.get("/api/health", headers={"Authorization": f"Bearer {a['token']}"})
    assert r.status_code == 200


async def test_health_workers(c):
    a = await _create_admin(c)
    r = await c.get("/api/health/workers", headers={"Authorization": f"Bearer {a['token']}"})
    assert r.status_code == 200


async def test_health_stats(c):
    a = await _create_admin(c)
    r = await c.get("/api/health/stats", headers={"Authorization": f"Bearer {a['token']}"})
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════
# FRONTEND
# ═══════════════════════════════════════════════════════════════

async def test_frontend_not_built(c):
    r = await c.get("/some-random-path")
    # When no frontend, returns 404 JSON. When frontend exists, returns HTML.
    assert r.status_code in (404, 200)


# ═══════════════════════════════════════════════════════════════
# RATE LIMITING
# ═══════════════════════════════════════════════════════════════

async def test_rate_limit(c):
    blocked = False
    ip = f"rate-test-{id(c)}"
    for i in range(105):
        r = await c.get("/api/ping", headers={"x-forwarded-for": ip})
        if r.status_code == 429:
            blocked = True
            break
    assert blocked, "Rate limiter did not trigger after 105 requests"
