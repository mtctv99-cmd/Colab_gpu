import os
import subprocess, time, httpx, sys, asyncio
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
VOICES_DIR = BASE_DIR / "data" / "voices"

def ensure_dummy_wav():
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    dummy = VOICES_DIR / "dummy_bench.wav"
    if not dummy.exists():
        dummy.write_bytes(
            b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
            b"\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00"
            b"\x02\x00\x10\x00data\x00\x00\x00\x00"
        )
    return dummy

async def run():
    dummy_wav = ensure_dummy_wav()
    print("[*] Starting server...")
    python_exe = str(Path(".venv") / "Scripts" / "python.exe")
    if not os.path.exists(python_exe):
        python_exe = sys.executable
    srv = subprocess.Popen([python_exe, "run.py"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)

    url = "http://127.0.0.1:8001"
    results = {}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Health check
            t0 = time.perf_counter()
            r = await client.get(f"{url}/")
            results["health_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            print(f"[OK] Health check HTTP {r.status_code} in {results['health_ms']} ms")

            # GET /api/voices/
            t0 = time.perf_counter()
            voices = (await client.get(f"{url}/api/voices/")).json()
            results["list_voices_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            print(f"[OK] GET /api/voices/ in {results['list_voices_ms']} ms ({len(voices)} voices)")

            # Upload dummy voice if needed
            if voices:
                voice_id = voices[0]["id"]
                print(f"[OK] Using existing voice id={voice_id}")
            else:
                with open(dummy_wav, "rb") as f:
                    t0 = time.perf_counter()
                    r = await client.post(f"{url}/api/voices/",
                                          data={"name": "BenchVoice", "transcript": "test"},
                                          files={"audio": ("dummy_bench.wav", f, "audio/wav")})
                    results["upload_voice_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                voice_id = r.json()["id"]
                print(f"[OK] Upload voice id={voice_id} in {results['upload_voice_ms']} ms")

            # GET /api/tasks/
            t0 = time.perf_counter()
            r = await client.get(f"{url}/api/tasks/?limit=20")
            results["list_tasks_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            tasks_count = len(r.json())
            print(f"[OK] GET /api/tasks/ in {results['list_tasks_ms']} ms ({tasks_count} tasks)")

            # Batch POST
            N = 10
            payload = {
                "voice_id": voice_id,
                "texts": [f"Benchmark text {i}: Kiem tra hieu suat API tao hang loat task toc do cao." for i in range(N)]
            }
            t0 = time.perf_counter()
            r = await client.post(f"{url}/api/tts/batch", json=payload)
            results["batch_ms"] = round((time.perf_counter() - t0) * 1000, 2)

            if r.status_code == 200:
                data = r.json()
                created = len(data["tasks"])
                results["tasks_created"] = created
                print(f"[OK] POST /api/tts/batch ({N} tasks) in {results['batch_ms']} ms")
                print(f"     => {created} tasks created, avg {results['batch_ms']/created:.2f} ms/task")
                for t in data["tasks"][:3]:
                    print(f"     id={t['task_id'][:8]}... status={t['status']}")
            else:
                print(f"[FAIL] Batch request: {r.status_code} {r.text}")

            # Summary
            print()
            print("==== BENCHMARK SUMMARY ====")
            for k, v in results.items():
                print(f"  {k:<22}: {v}")
    finally:
        srv.terminate()
        srv.wait()
        print("[*] Server stopped.")

if __name__ == "__main__":
    asyncio.run(run())
