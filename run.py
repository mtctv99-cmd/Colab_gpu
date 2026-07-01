import asyncio
import os
import sys
import subprocess
import uvicorn

# Triệt để: không bao giờ hiển thị OAuth prompt khi chạy server
os.environ.setdefault("DISABLE_INTERACTIVE_AUTH", "1")

PORT = int(os.getenv("PORT", "8090"))
WORKER_PATH = os.path.join(os.path.dirname(__file__), "colab", "worker.py")


def _start_local_worker():
    """Start local GPU worker if CUDA is available."""
    try:
        import torch
        if not torch.cuda.is_available():
            print("[INFO] No CUDA GPU found, skipping local worker")
            return None
        gpu_name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(f"[OK]   GPU: {gpu_name} ({vram:.1f}GB) — starting local worker")

        import sqlite3
        db_path = os.path.join(os.path.dirname(__file__), "data", "db.sqlite3")
        email = "local@local"
        session_id = "local"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT OR REPLACE INTO google_accounts (email, status, worker_session_id) VALUES (?, 'ACTIVE', ?)",
            (email, session_id),
        )
        conn.commit()
        conn.close()

        proc = subprocess.Popen(
            [sys.executable, WORKER_PATH,
             "--server-url", f"http://localhost:{PORT}",
             "--email", email,
             "--worker-session-id", session_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[OK]   Local worker PID={proc.pid}")
        return proc
    except Exception as e:
        print(f"[WARN] Failed to start local worker: {e}")
        return None


if __name__ == "__main__":
    worker_proc = _start_local_worker()

    reload = os.getenv("RELOAD", "0") == "1" or "--reload" in sys.argv
    config = uvicorn.Config("app.main:app", host="0.0.0.0", port=PORT, reload=reload)
    server = uvicorn.Server(config)
    try:
        server.run()
    finally:
        if worker_proc:
            worker_proc.terminate()
            worker_proc.wait(timeout=5)
