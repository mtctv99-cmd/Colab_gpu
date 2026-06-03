import asyncio, os, signal, subprocess, sys, time, json, re
from pathlib import Path
import httpx

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOG = ROOT / "data" / "final_e2e_server.log"
ERR = ROOT / "data" / "final_e2e_server.err.log"
PID_FILE = ROOT / "data" / "final_e2e_server.pid"
URL = "http://127.0.0.1:8001"

TEXTS = [
    f"Đoạn {i+1}: Kiểm tra tính năng tự động vượt rào bảo mật và điền form của Colab TTS với mười segment."
    for i in range(10)
]

async def db_reset():
    import sqlite3
    db_path = ROOT / "data" / "db.sqlite3"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("UPDATE google_accounts SET status='OFFLINE', colab_pid=NULL")
    conn.commit()
    conn.close()
    print("[1] Database reset: All accounts set to OFFLINE")

async def wait_for_cloudflare(log_path):
    print("[3] Waiting for Cloudflare Tunnel URL...")
    for _ in range(60):
        if log_path.exists():
            content = log_path.read_text(errors="ignore")
            match = re.search(r"trycloudflare\.com", content)
            if match:
                url_match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
                if url_match:
                    print(f"    Cloudflare URL found: {url_match.group(0)}")
                    return url_match.group(0)
        await asyncio.sleep(1)
    print("    Timeout waiting for Cloudflare, using localhost fallback")
    return URL

async def main():
    await db_reset()
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            subprocess.run(["taskkill", "/PID", str(old_pid), "/F", "/T"], capture_output=True)
        except: pass
    
    for f in [LOG, ERR]:
        if f.exists(): f.unlink()

    print("[2] Starting Server Debug...")
    out = LOG.open("wb")
    err = ERR.open("wb")
    proc = subprocess.Popen(
        [str(PY), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "debug"],
        cwd=str(ROOT), stdout=out, stderr=err, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )
    PID_FILE.write_text(str(proc.pid))
    
    async with httpx.AsyncClient(timeout=30) as client:
        # Wait server ready
        for _ in range(30):
            try:
                if (await client.get(URL)).status_code == 200: break
            except: pass
            await asyncio.sleep(1)
        
        public_url = await wait_for_cloudflare(LOG)
        
        # Get voice
        voices = (await client.get(f"{URL}/api/voices/")).json()
        voice_id = voices[0]["id"] if voices else 1
        print(f"[4] Using Voice ID: {voice_id}")

        print("[5] Posting Batch (Triggering Auto-rotation)...")
        r = await client.post(f"{URL}/api/tasks/batch", json={"voice_id": voice_id, "texts": TEXTS})
        task_ids = [t["id"] for t in r.json()["tasks"]]
        print(f"    Batch created: {len(task_ids)} tasks PENDING")

        print("[6] Monitoring Worker Automation & Processing (10 minutes)...")
        print("    Checking automation logs for deep input fallback and Run anyway...")
        
        start_time = time.time()
        max_time = 600 # 10 mins
        last_log_size = 0
        
        while time.time() - start_time < max_time:
            # Poll status
            statuses = {}
            for tid in task_ids:
                ts = (await client.get(f"{URL}/api/tasks/{tid}")).json()
                s = ts["status"]
                statuses[s] = statuses.get(s, 0) + 1
            
            # Print status summary
            elapsed = int(time.time() - start_time)
            print(f"    t+{elapsed:03d}s Statuses: {statuses}", end="\r")
            
            # Print new log lines if any
            if LOG.exists():
                curr_size = LOG.stat().st_size
                if curr_size > last_log_size:
                    with LOG.open("r", errors="ignore") as f:
                        f.seek(last_log_size)
                        new_lines = f.readlines()
                        for line in new_lines:
                            if any(x in line for x in ["Filled", "Dismissed", "Connected", "task", "worker"]):
                                sys.stdout.write("      " + line)
                    last_log_size = curr_size
            
            if statuses.get("COMPLETED", 0) == len(task_ids):
                print(f"\n🎉 All tasks COMPLETED in {elapsed}s!")
                break
            if statuses.get("FAILED", 0) > 0:
                print(f"\n⚠️ Some tasks FAILED.")
                break
                
            await asyncio.sleep(5)
            
        print("\n[7] FINAL RESULTS:")
        for tid in task_ids:
            ts = (await client.get(f"{URL}/api/tasks/{tid}")).json()
            print(f"    {tid[:8]} {ts['status']} | Audio: {ts.get('result_audio_path')} | Err: {ts.get('error_message')}")
            
    print(f"\n[INFO] Server logs: {LOG}")
    print(f"[INFO] Server PID: {proc.pid}. Kill manually or let next test clean it.")

if __name__ == "__main__":
    asyncio.run(main())
