"""Quick health check — run with: python test_health.py"""
import httpx, sys

BASE = "http://127.0.0.1:8001"
c = httpx.Client(base_url=BASE, timeout=10)
failed = 0

def check(method, path, expected=200, **kw):
    global failed
    r = c.request(method, path, **kw)
    ok = r.status_code == expected
    print(f"{'OK' if ok else 'FAIL'} {method:4} {path} -> {r.status_code}" + (f" (expected {expected})" if not ok else ""))
    if not ok:
        failed += 1

print(f"=== Clone TTS Health Check ===\n")

check("GET", "/")
check("GET", "/login")
check("GET", "/signup")
check("GET", "/dashboard")
check("GET", "/admin/")
check("GET", "/api/health/")
check("GET", "/api/health/stats")

# Auth flow
r = c.post("/api/auth/signup", json={"email": "health@test.com", "password": "test123456"})
print(f"{'OK' if r.status_code==200 else 'FAIL'} POST /api/auth/signup -> {r.status_code}")
token = r.json().get("token", "")
check("GET", "/api/auth/profile", headers={"Authorization": f"Bearer {token}"})
check("POST", "/api/tts/text", 401, json={"text": "hi", "voice_id": 2})
check("POST", "/api/tts/text", 402, json={"text": "hi", "voice_id": 2}, headers={"Authorization": f"Bearer {token}"})

check("GET", "/api/auth/api-keys", headers={"Authorization": f"Bearer {token}"})
r = c.post("/api/auth/api-keys", json={"name": "Health"}, headers={"Authorization": f"Bearer {token}"})
print(f"{'OK' if r.status_code==200 else 'FAIL'} POST /api/auth/api-keys -> {r.status_code}")

# Admin routes should 403 for regular user
check("GET", "/api/accounts/", 403, headers={"Authorization": f"Bearer {token}"})

print(f"\n{'='*30}\n{failed} tests failed")
sys.exit(1 if failed else 0)
