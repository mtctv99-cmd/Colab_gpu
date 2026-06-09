import asyncio
import time
import httpx
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")
URL = "http://127.0.0.1:8001"

async def measure(client, method, path, **kwargs):
    t = time.perf_counter()
    r = await client.request(method, f"{URL}{path}", **kwargs)
    return r, round((time.perf_counter() - t) * 1000, 2)

async def main():
    print("=" * 70)
    print(" COLAB TTS - BENCHMARK SUITE")
    print("=" * 70)
    
    async with httpx.AsyncClient(timeout=60) as c:
        # 1. Health endpoints
        print("\n[1] HEALTH CHECK")
        for path in ["/api/health/", "/api/health/workers", "/api/health/stats"]:
            r, ms = await measure(c, "GET", path)
            status = "OK" if r.status_code == 200 else f"FAIL({r.status_code})"
            print(f"  {path:<35} {status:<8} {ms:>7.2f}ms")
        
        # 2. Latency benchmark on read endpoints
        print("\n[2] LATENCY (10 requests each)")
        for path in ["/api/health/", "/api/voices/", "/api/accounts/", "/api/health/stats"]:
            samples = []
            for _ in range(10):
                _, ms = await measure(c, "GET", path)
                samples.append(ms)
            avg = statistics.mean(samples)
            p95 = sorted(samples)[int(len(samples)*0.95)-1]
            print(f"  {path:<35} avg={avg:>6.1f}ms p95={p95:>6.1f}ms min={min(samples):>5.1f}ms max={max(samples):>5.1f}ms")
        
        # 3. Concurrent load
        print("\n[3] CONCURRENT LOAD (50 parallel /api/health/ requests)")
        t0 = time.perf_counter()
        results = await asyncio.gather(*[measure(c, "GET", "/api/health/") for _ in range(50)])
        total_ms = (time.perf_counter() - t0) * 1000
        ok = sum(1 for r, _ in results if r.status_code == 200)
        latencies = [m for _, m in results]
        print(f"  total={total_ms:.0f}ms ok={ok}/50 avg={statistics.mean(latencies):.1f}ms")
        print(f"  throughput={50/(total_ms/1000):.1f} req/s")
        
        # 4. Voices list
        print("\n[4] DATA SNAPSHOT")
        r = await c.get(f"{URL}/api/voices/")
        voices = r.json()
        print(f"  voices: {len(voices)}")
        for v in voices:
            print(f"    [{v['id']}] {v['name']}")
        
        r = await c.get(f"{URL}/api/accounts/")
        accs = r.json()
        print(f"  accounts: {len(accs)}")
        for a in accs:
            print(f"    [{a['id']}] {a['email']} - {a['status']}")
        
        # 5. Workers status
        print("\n[5] WORKER LIFECYCLE")
        r = await c.get(f"{URL}/api/health/workers")
        workers = r.json()
        if not workers:
            print("  No active worker connections (server is idle)")
        for w in workers:
            print(f"  {w['email']} - {w['status']} - uptime={w['uptime_seconds']:.0f}s remaining={w['remaining_seconds']:.0f}s expiring={w['expiring']}")
        
        # 6. Batch task creation (without actual TTS execution since no live worker)
        if voices:
            print("\n[6] BATCH TASK CREATION (10 texts, no execution)")
            voice_id = voices[0]["id"]
            payload = {
                "voice_id": voice_id,
                "batch": True,
                "texts": [f"Benchmark TTS {i}" for i in range(10)],
            }
            r, ms = await measure(c, "POST", "/api/tts/batch", json=payload)
            if r.status_code == 200:
                data = r.json()
                print(f"  Created {len(data['tasks'])} tasks in {ms:.1f}ms ({ms/len(data['tasks']):.1f}ms/task)")
            else:
                print(f"  FAIL: {r.status_code} {r.text[:200]}")
    
    print("\n" + "=" * 70)
    print(" BENCHMARK DONE")
    print("=" * 70)

asyncio.run(main())
