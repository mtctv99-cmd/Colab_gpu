# Spec: Auto-heal & High-Load Stability Fixes

## 1. Context & Problems
Currently, the Colab worker orchestrator fails under high load and experiences silent hangs due to:
- Timezone issues in uptime calculation (`sa.replace(tzinfo=timezone.utc)` fails on already timezone-aware objects or miscalculates if local time deviates from UTC).
- Lack of WebSocket ping-pong timeouts causing half-open connections.
- Out-of-sync worker code (deploying from Git instead of current local modified workspace code).
- Memory leaks (lack of torch cache flushing and garbage collection in long-running Colab runtimes).
- Heavy resource contention due to lack of concurrent queue backpressure.

## 2. Solution Design

### 2.1 Backend Improvements

#### A. Timezone Sync
Ensure all database timestamps and Python calculations use UTC timezone-aware objects consistently:
- Database schema timestamps must handle timezone strings correctly.
- Uptime calculations: Use `datetime.now(timezone.utc)` for comparisons.

#### B. Robust Heartbeat Loop (`app/routes/ws.py`)
- Check `last_pong` timestamp every 15s.
- Mark dead and force-disconnect if a worker fails to respond to pings within 25 seconds.
- Requeue any active `PROCESSING` tasks owned by the dead worker immediately.

#### C. Local Code Deployment (`app/orchestrator/worker.py`)
Instead of fetching code from a Git repository:
- The deploy command will read local `colab/worker.py` (or `colab/llm_worker.py`) and write their full content directly onto remote instance using base64 transfer to guarantee synchronization. Other static files in `colab/` folder are cloned if needed, but worker logic runs the local code version.

#### D. Scale & Concurrency Limits
- Auto-scale batch limits: limit maximum worker launches to 4 per cycle.
- Queue backpressure: return HTTP 429 if the pending queue exceeds 100 tasks.

### 2.2 Worker Improvements (`colab/worker.py` & `colab/llm_worker.py`)

#### A. Connection Timeout & Auto-Heal
- Reconnection logic: reconnect every 5 seconds.
- If WebSocket ping is not received for 30s, the worker assumes the connection is dead, closes it, and reconnects.
- Exit if disconnected for more than 180s to let keep-alive loop restart the kernel.

#### B. GPU Resource Management
- Call `torch.cuda.empty_cache()` and `gc.collect()` after processing each task to avoid OOM.

---

## 3. Implementation Plan

### Step 1: Fix Timezones and Constants
Update `app/orchestrator/lifecycle.py` and `pool.py` to parse dates correctly:
```python
def utcnow():
    return datetime.now(timezone.utc)
```

### Step 2: Implement Code Sync via Base64/Direct Write
Modify `app/orchestrator/worker.py` to write `colab/worker.py` and `colab/llm_worker.py` contents onto the remote instance dynamically.

### Step 3: Implement Client-Side Resiliency
Update `colab/worker.py` and `colab/llm_worker.py` to include:
- WebSocket ping-pong checks.
- Garbage collection + torch empty cache calls.

### Step 4: Fix WebSocket Connection Manager and Heartbeat
Modify `app/routes/ws.py` to reduce heartbeat check timeout and handle connection terminations safely.
