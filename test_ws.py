import asyncio, json, websockets
from sqlalchemy import create_engine, text

engine = create_engine("sqlite:///data/db.sqlite3")
with engine.connect() as c:
    # Pick first IDLE or READY account
    row = c.execute(
        text("SELECT email, worker_session_id FROM google_accounts WHERE runtime_status='IDLE' LIMIT 1")
    ).fetchone()
    if not row:
        row = c.execute(
            text("SELECT email, worker_session_id FROM google_accounts WHERE status='READY' LIMIT 1")
        ).fetchone()

if not row:
    print("NO ACCOUNT")
    exit(1)

email = row[0]
wsid = row[1] or "debug-wsid-001"

async def main():
    url = "ws://localhost:8090/ws/worker"
    print(f"Connecting {email} (wsid={wsid}) to {url}...")
    async with websockets.connect(url, open_timeout=10, close_timeout=5, ping_interval=None) as ws:
        reg = {"action": "register", "email": email, "worker_session_id": wsid,
               "gpu": "TEST-GPU"}
        print(f"Register: {json.dumps(reg)}")
        await ws.send(json.dumps(reg))
        await ws.send(json.dumps({"action": "status", "status": "IDLE"}))
        print("Sent register + IDLE")

        # Keep listening
        for _ in range(30):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(msg)
                print(f"Inbox: {data}")

                if data.get("action") == "ping":
                    await ws.send(json.dumps(
                        {"action": "pong_status", "status": "IDLE", "worker_session_id": wsid}
                    ))
                    print("Sent pong")

                if data.get("action") == "run_tts":
                    task_id = data.get("task_id")
                    print(f"\n📩 Got TTS task: {task_id}")
                    # Simulate completion (in real worker, you'd process audio here)
                    import httpx
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"http://localhost:8090/api/tasks/{task_id}/complete",
                            data={"worker_session_id": wsid},
                            files={"audio": ("result.wav", b"fake-wav-data", "audio/wav")}
                        )
                    await ws.send(json.dumps({
                        "action": "task_completed",
                        "task_id": task_id,
                        "worker_session_id": wsid
                    }))
                    print("✅ Sent completion!")

            except asyncio.TimeoutError:
                pass

asyncio.run(main())
