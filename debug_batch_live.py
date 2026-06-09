import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOG = ROOT / "data" / "debug_batch_server.log"
ERR = ROOT / "data" / "debug_batch_server.err.log"
PID = ROOT / "data" / "debug_batch_server.pid"
URL = "http://127.0.0.1:8001"

TEXTS = [
    "Đoạn một: Đây là bài kiểm tra giọng đọc tự động trên hệ thống Colab TTS.",
    "Đoạn hai: Máy chủ đang nhận yêu cầu theo lô và tạo nhiệm vụ xử lý âm thanh.",
    "Đoạn ba: Mỗi đoạn văn bản sẽ được chuyển thành một task độc lập trong cơ sở dữ liệu.",
    "Đoạn bốn: Worker Colab sau khi kết nối sẽ lấy task pending và xử lý lần lượt.",
    "Đoạn năm: Mục tiêu là xác minh luồng batch mười segment hoạt động ổn định.",
    "Đoạn sáu: Chúng ta đang dùng giọng nói có sẵn trong thư viện của server.",
    "Đoạn bảy: Nếu worker online, kết quả sẽ được upload về thư mục data results.",
    "Đoạn tám: Bài test này cũng ghi log debug để kiểm tra lỗi phát sinh.",
    "Đoạn chín: Hệ thống cần phản hồi nhanh và không bị treo request.",
    "Đoạn mười: Kết thúc batch kiểm tra, tổng hợp trạng thái từng task.",
]

def kill_old_server():
    if PID.exists():
        try:
            old_pid = int(PID.read_text().strip())
            subprocess.run(["taskkill", "/PID", str(old_pid), "/F"], capture_output=True)
        except Exception:
            pass

async def wait_ready(client):
    for _ in range(60):
        try:
            r = await client.get(f"{URL}/", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False

async def main():
    kill_old_server()
    LOG.parent.mkdir(exist_ok=True, parents=True)
    for p in [LOG, ERR]:
        if p.exists():
            p.unlink()

    print("[1] Start server debug...")
    out = LOG.open("wb")
    err = ERR.open("wb")
    proc = subprocess.Popen(
        [str(PY), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "debug"],
        cwd=str(ROOT), stdout=out, stderr=err,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    PID.write_text(str(proc.pid), encoding="utf-8")
    print(f"    PID={proc.pid}")

    async with httpx.AsyncClient(timeout=20) as client:
        if not await wait_ready(client):
            print("[FAIL] Server chưa ready sau 30s")
            print(ERR.read_text(errors="ignore")[-2000:] if ERR.exists() else "")
            return
        print("[OK] Server ready")

        print("[2] Get existing voices...")
        r = await client.get(f"{URL}/api/voices/")
        r.raise_for_status()
        voices = r.json()
        if not voices:
            print("[FAIL] Không có voice sẵn trong DB")
            return
        voice = voices[0]
        voice_id = voice["id"]
        print(f"[OK] Using voice id={voice_id}, name={voice.get('name')}")

        print("[3] POST batch 10 segment...")
        t0 = time.perf_counter()
        r = await client.post(f"{URL}/api/tts/batch", json={"voice_id": voice_id, "texts": TEXTS})
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"    HTTP {r.status_code} in {elapsed_ms:.2f} ms")
        print(f"    Response: {r.text[:1000]}")
        r.raise_for_status()
        tasks = r.json()["tasks"]
        ids = [t["task_id"] for t in tasks]
        print(f"[OK] Created {len(ids)} tasks")

        print("[4] Poll statuses 45s...")
        for step in range(15):
            await asyncio.sleep(3)
            statuses = {}
            audio_ready = 0
            for task_id in ids:
                tr = await client.get(f"{URL}/api/tasks/{task_id}")
                task = tr.json()
                statuses[task["status"]] = statuses.get(task["status"], 0) + 1
                if task["status"] == "COMPLETED" and task.get("result_audio_path"):
                    audio_ready += 1
            print(f"    t+{(step+1)*3:02d}s statuses={statuses} audio_ready={audio_ready}")
            if statuses.get("COMPLETED", 0) == len(ids) or statuses.get("FAILED", 0) == len(ids):
                break

        print("[5] Final task details:")
        for task_id in ids:
            task = (await client.get(f"{URL}/api/tasks/{task_id}")).json()
            print(f"    {task_id[:8]} status={task['status']} result={task.get('result_audio_path')} error={task.get('error_message')}")

    print("[LOG] stdout tail:")
    print(LOG.read_text(errors="ignore")[-3000:] if LOG.exists() else "")
    print("[LOG] stderr tail:")
    print(ERR.read_text(errors="ignore")[-3000:] if ERR.exists() else "")
    print("[INFO] Server vẫn đang chạy để debug. PID file:", PID)

if __name__ == "__main__":
    asyncio.run(main())
