import httpx
import time
import asyncio

BASE = "http://localhost:8090"

async def main():
    async with httpx.AsyncClient(timeout=60) as c:
        # 1. Signup / Login
        email = f"bench_{int(time.time())}@e2e-test.com"
        print(f"Creating user {email}...")
        r = await c.post(f"{BASE}/api/auth/signup", json={"email": email, "password": "password123"})
        if r.status_code != 200:
            print("Signup failed:", r.text)
            return
        
        token = r.json()["token"]
        uid = r.json()["user"]["id"]
        
        # Cấp balance cho user để chạy TTS
        import sqlite3
        conn = sqlite3.connect("data/db.sqlite3")
        conn.execute("UPDATE users SET balance=1000 WHERE id=?", (uid,))
        conn.commit()
        
        # 2. Gọi API sinh TTS
        print("\nSending TTS request...")
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "text": "Dự án Dubbing hỗ trợ sinh giọng nói tự động chất lượng cao bằng trí tuệ nhân tạo.",
            "voice_id": 1
        }
        
        start = time.perf_counter()
        r_tts = await c.post(f"{BASE}/api/tts/text", headers=headers, json=payload)
        
        if r_tts.status_code != 200:
            print("TTS request failed:", r_tts.text)
            return
            
        task_id = r_tts.json()["id"]
        print(f"Task created: {task_id}")
        
        # 3. Poll trạng thái task cho đến khi COMPLETED
        print("Polling task status...")
        while True:
            r_status = await c.get(f"{BASE}/api/tasks/{task_id}", headers=headers)
            status = r_status.json()["status"]
            print(f" - Status: {status}")
            if status == "COMPLETED":
                elapsed = time.perf_counter() - start
                print(f"\n✅ TTS Task completed successfully!")
                print(f"⏱️ Total processing time (E2E): {elapsed:.2f} seconds")
                break
            elif status == "FAILED":
                print("❌ Task failed:", r_status.json().get("error_message"))
                break
            await asyncio.sleep(0.5)

asyncio.run(main())
