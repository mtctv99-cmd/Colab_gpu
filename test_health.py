"""Quick health check — run with: python test_health.py"""
import httpx, sys

BASE = "http://127.0.0.1:8090"
c = httpx.Client(base_url=BASE, timeout=10)
failed = 0

def check(method, path, expected=200, **kw):
    global failed
    r = c.request(method, path, **kw)
    ok = r.status_code == expected
    print(f"{'OK' if ok else 'FAIL'} {method:4} {path} -> {r.status_code}" + (f" (expected {expected})" if not ok else ""))
    if not ok:
        failed += 1

if __name__ == "__main__":
    print(f"=== TTS Dubbing Health Check ===\n")

    # Public static pages checks removed since they are served by the Next.js frontend on port 8091
    check("GET", "/api/health/", 401)
    check("GET", "/api/health/stats", 401)

    # Auth flow
    import uuid
    email = f"health_{uuid.uuid4().hex[:8]}@test.com"
    r = c.post("/api/auth/signup", json={"email": email, "password": "test123456"})
    print(f"{'OK' if r.status_code==200 else 'FAIL'} POST /api/auth/signup -> {r.status_code}")
    token = r.json().get("token", "")
    check("GET", "/api/auth/profile", headers={"Authorization": f"Bearer {token}"})
    # Try to get a valid voice_id
    voices_res = c.get("/api/voices", headers={"Authorization": f"Bearer {token}"})
    voice_id = 2
    if voices_res.status_code == 200:
        try:
            voices_list = voices_res.json()
            if voices_list and isinstance(voices_list, list):
                voice_id = voices_list[0].get("id", 2)
        except Exception:
            pass

    check("POST", "/api/tts/text", 401, json={"text": "hi", "voice_id": voice_id})
    r_tts = c.post("/api/tts/text", json={"text": "hi", "voice_id": voice_id}, headers={"Authorization": f"Bearer {token}"})
    is_ok = r_tts.status_code in (400, 402)
    if not is_ok:
        failed += 1
    print(f"{'OK' if is_ok else 'FAIL'} POST /api/tts/text -> {r_tts.status_code} (expected 400 or 402)")


    check("GET", "/api/auth/api-keys", headers={"Authorization": f"Bearer {token}"})
    r = c.post("/api/auth/api-keys", json={"name": "Health"}, headers={"Authorization": f"Bearer {token}"})
    print(f"{'OK' if r.status_code==200 else 'FAIL'} POST /api/auth/api-keys -> {r.status_code}")

    # Admin routes should 403 for regular user
    check("GET", "/api/accounts/", 403, headers={"Authorization": f"Bearer {token}"})

    print(f"\n{'='*30}\n{failed} tests failed")
    sys.exit(1 if failed else 0)

