import asyncio
import os
import signal
import socket
import sys

import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

PORT = 8001

def kill_existing_on_port(port: int) -> None:
    """Kill any process currently listening on the given port (Windows only)."""
    if sys.platform != "win32":
        return
    import subprocess
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                pid = int(parts[-1])
                if pid and pid != os.getpid():
                    print(f"[startup] Killing old process on port {port} (PID={pid})")
                    os.kill(pid, signal.SIGTERM)
    except Exception:
        pass

if __name__ == "__main__":
    kill_existing_on_port(PORT)
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=False)
