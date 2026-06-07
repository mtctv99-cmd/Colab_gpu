import asyncio
import httpx
import json
import os, sys

sys.path.insert(0, os.path.dirname(__file__))

async def bootstrap_db():
    from app.database import async_session, init_db
    from app.models import Voice
    await init_db()
    async with async_session() as db:
        from sqlalchemy import select
        existing = await db.execute(select(Voice).where(Voice.id == 1))
        if not existing.scalar_one_or_none():
            voice = Voice(id=1, name="Test Voice", audio_path="data/voices/test.wav")
            db.add(voice)
            await db.commit()
            print("[setup] Voice seeded OK")
        else:
            print("[setup] Voice already exists")

async def test():
    await bootstrap_db()

    SERVER = "http://localhost:8000"
    EMAIL = "thanhchuapi2@gmail.com"

    import websockets
    print("\n=== TEST 1: Worker register ===")
    async with websockets.connect(f"ws://localhost:8000/ws/{EMAIL}") as ws:
        await ws.send(json.dumps({"action": "register", "email": EMAIL, "gpu": "RTX4090"}))
        ack = await ws.recv()
        print(f"[WS] Worker registered OK")

        # Goi API TTS
        print("\n=== TEST 2: Create TTS task ===")
        async with httpx.AsyncClient() as cli:
            resp = await cli.post(f"{SERVER}/api/tts/text", json={
                "text": "Xin chao the gioi, day la tieng noi duoc tao boi AI.",
                "voice_id": 1,
                "language": "vi"
            })
            assert resp.status_code == 200, f"TTS API failed: {resp.status_code} - {resp.text}"
            task_id = resp.json()["task_id"]
            print(f"[API] TTS task created: {task_id}")
            assert resp.json()["worker"] == EMAIL

            # Nhan task tu WS
            print("\n=== TEST 3: Worker receives task ===")
            task_msg = await ws.recv()
            task_data = json.loads(task_msg)
            assert task_data["action"] == "run_tts"
            assert task_data["task_id"] == task_id
            print(f"[WS] Task received: {task_data['text'][:50]}...")

            # Upload ket qua gia lap
            print("\n=== TEST 4: Worker uploads audio ===")
            fake_audio = b"\x00\x00\x00\x00" * 1000
            upload = await cli.post(
                f"{SERVER}/api/tasks/{task_id}/complete",
                files={"audio": ("result.wav", fake_audio, "audio/wav")}
            )
            assert upload.status_code == 200, f"Upload failed: {upload.status_code} - {upload.text}"
            print(f"[API] Upload OK: {upload.json()}")

            # Bao completed
            print("\n=== TEST 5: Worker sends complete ===")
            await ws.send(json.dumps({"action": "task_completed", "task_id": task_id}))

            # Verify DB
            from app.database import async_session as db_sess
            from app.models import Task
            async with db_sess() as db:
                task = await db.get(Task, task_id)
                assert task is not None
                assert task.status == "COMPLETED", f"Status={task.status}"
                full_path = os.path.join(os.path.dirname(__file__), "data", "results", f"{task_id}.wav")
                print(f"[DB] Task status: {task.status}")
                print(f"[DB] Result path: {task.result_path}")
                if os.path.exists(full_path):
                    file_size = os.path.getsize(full_path)
                    print(f"[FILE] Audio saved: {full_path} ({file_size} bytes)")
                else:
                    print(f"[WARN] Expected file not found: {full_path}")
                    # fallback relative check
                    rel_path = f"data/results/{task_id}.wav"
                    if os.path.exists(rel_path):
                        print(f"[FILE] Audio saved at relative: {rel_path}")

    print("\n=== ALL TESTS PASSED ===")

if __name__ == "__main__":
    asyncio.run(test())
