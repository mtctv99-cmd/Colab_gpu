# Orchestrator Redesign — Spec

**Date:** 2026-06-15
**Author:** Agent + User
**Status:** Draft

## Summary

Replace legacy Playwright-based auto-browser worker lifecycle with a clean orchestrator layer using `google-colab-cli` source directly via COPY, not pip. Rewrite frontend as standalone Next.js container. Maximum throughput design: 8 Google accounts, 2 warm workers always, scale up to 8 under load.

## Architecture

```
Browser → Next.js (:3355) → /api/*, /ws/* → FastAPI (:8090) → orchestrator/ → colab_cli/ (source)
                                                     ↓
                                                  DB (SQLite)
```

- Frontend rewrites `/api/*` and `/ws/*` to backend — no CORS
- Orchestrator replaces `app/automation/` + `app/lifecycle/`
- `colab_cli/` copied directly from google-colab-cli source (not pip install)
- Ports: backend `:8090`, frontend `:3355`

## Modules

### `app/orchestrator/constants.py`

```python
# Account status
READY, COOLDOWN, NEEDS_LOGIN, DISABLED
# Runtime status
IDLE, BUSY, WARMING, STARTING, LOST, DRAINING
# Pool config
MAX_WORKERS = 8
WARM_TARGET = 2
POLL_INTERVAL = 15
COOLDOWN_SECONDS = 57600     # 16h — account cooldown after quota exhausted
TASK_MAX_ATTEMPTS = 3         # max total attempts per task (1 original + 2 retries). Guard: attempt >= TASK_MAX_ATTEMPTS → FAILED
TASK_RETRY_BACKOFF_SECONDS = 60  # delay before retry
IDLE_SCALE_DOWN_SECONDS = 1800
KEEP_ALIVE_INTERVAL = 60      # worker keep-alive RPC interval
HEARTBEAT_TIMEOUT = 75        # seconds before marking worker LOST (must be > KEEP_ALIVE_INTERVAL + slack)
LIFETIME_SECONDS = 13500      # 3h45m — begin rotation at this point
MAX_LIFETIME_SECONDS = 14400  # 4h — hard kill if rotation fails
SERVER_URL = "http://localhost:8090"  # used to build voice download URLs for workers. Override via env var or config.
```

### `app/orchestrator/account.py` — AccountManager

Manages 8 Google accounts. Each account has isolated credentials.

```
AccountManager
  .ready_accounts() -> list[Account]  # all READY accounts
  .get_account(email) -> Account
  .auth(email) -> None                # run OAuth2 flow
  .refresh_cooldowns() -> int         # COOLDOWN→READY if quota_reset_at passed
  .mark_needs_login(email)
  .mark_cooldown(email, minutes)
```

Uses `colab_cli.auth.get_credentials(config_path=TOKEN_PATH)` per account.
Token path: `~/.config/colab-cli/token_{safe_email}.json`.

**`auth(email)` flow:** Not automated via API. Admin must run `colab new` in terminal. The API endpoint `POST /api/accounts/{id}/auth` triggers auth URL generation server-side, logs it to server logs, and returns `{"message": "Auth URL printed to server logs"}`. No code-paste flow — full terminal OAuth required.

### `app/colab_cli/` — Source Copy

Direct copy of `src/colab_cli/` from google-colab-cli repo. Pin to commit SHA at copy time (published to PyPI as `google-colab-cli` — version matches pip package).

**Import fix needed:** Internal imports use `from colab_cli.xxx`. After copying to `app/colab_cli/`, these must be rewritten. Single `sed` command handles it:
```
sed -i 's/from colab_cli/from app.colab_cli/g' app/colab_cli/**/*.py
```
This is safe — the pip package is removed, so there's no ambiguity.

**StateStore + DB dual tracking:** StateStore JSON (`~/.config/colab-cli/sessions_*.json`) is required by colab-cli's internal keep-alive daemon and is not replaced. DB `WorkerSession` table is our app-level summary for queries and admin dashboard. They coexist — StateStore is colab-cli's concern, DB is our concern. No sync needed.

### `app/orchestrator/worker.py` — WorkerManager

Per-account runtime lifecycle. No global `colab_cli.common.state` singleton — each account gets its own `Client`, `StateStore`, `ColabRuntime` instances.

```
WorkerManager
  .active_workers -> dict[email, WorkerInstance]
  .launch(email) -> worker_session_id
  .shutdown(email) -> None
  .shutdown_all() -> None
  .get_runtime(email) -> ColabRuntime
  .zombie_cleanup() -> int

WorkerInstance = {
  client: Client,
  token_path: str,
  store_path: str,
  session_name: str,
  keep_alive_pid: int | None,
  runtime: ColabRuntime | None,
}
```

**`launch(email)` flow:**
1. Get credentials → `Client(Prod(), creds)`
2. `client.assign(uuid4(), variant=GPU, accelerator=T4)` → res
3. `client.keep_alive_assignment(endpoint)` — pre-flight scope check
4. `from app.colab_cli.commands.session import spawn_keep_alive` → spawn detached keep-alive process → pid
5. Persist to `StateStore(sessions_{safe_email}.json)`
6. Update DB: `WorkerSession` + account fields
7. Return `worker_session_id`

**`shutdown_immediate(email)` flow** (errors, admin stop):
1. Send WS `{"action":"shutdown"}` to worker (fire-and-forget)
2. Kill keep_alive_pid (SIGKILL)
3. `ColabRuntime.stop(shutdown_kernel=True)` — close channels
4. `client.unassign(endpoint)`
5. `store.remove(name)`
6. Clean DB fields, delete WorkerSession row

**`shutdown_graceful(email)` flow** (rotation handover):
1. Mark worker runtime_status = DRAINING in DB (no new tasks dispatched)
2. Wait for replacement worker to reach IDLE (polled via `_rotation_state`)
3. Send WS `{"action":"shutdown"}`
4. Wait up to 5s for WS acknowledgement grace period (not for task completion — in-flight task is protected by MAX_LIFETIME)
5. Kill keep_alive_pid (SIGTERM)
6. `ColabRuntime.stop(shutdown_kernel=True)`
7. `client.unassign(endpoint)`
8. `store.remove(name)`
9. Clean DB fields, delete WorkerSession row

### `app/orchestrator/pool.py` — PoolManager

Scale decisions. Maintains WARM_TARGET=2 workers.

```
PoolManager
  .active_count() -> int               # running workers (excludes DRAINING)
  .ready_account_count() -> int        # accounts available to launch
  .scale_up_if_needed() -> str|None    # returns launched email or None
  .scale_down_if_needed() -> str|None  # returns stopped email or None
  .select_account_for_launch() -> str  # least-recently-used (last_active ASC)
  .select_account_for_shutdown() -> str # longest-idle non-warm account

# active_count includes: STARTING, WARMING, IDLE, BUSY
# active_count excludes: DRAINING (to allow replacement to launch)
# MAX_WORKERS check includes ALL non-STOPPED statuses including DRAINING
```

**Scale-up trigger** (called by lifecycle loop + dispatcher):
- `active_count < MAX_WORKERS AND ready_account_count > 0`
- If `active_count < WARM_TARGET` → scale up immediately
- If `pending_tasks > 0 AND active_count < MAX_WORKERS` → scale up immediately
- Account selection: LRU via `last_active ASC NULLS FIRST` (brand-new accounts with NULL last_active are picked first)

**Scale-down trigger** (called by lifecycle loop):
- `active_count > WARM_TARGET AND pending_tasks == 0`
- Worker `idle_since > IDLE_SCALE_DOWN_SECONDS` → stop longest-idle
- Worker lifetime > `LIFETIME_SECONDS` → start rotation

**Rotation at 3h45m:**
Sequenced across lifecycle loop iterations using `_rotation_state` dict owned by lifecycle.py (in-memory only — server restart mid-rotation orphans replacement until MAX_LIFETIME fires):
```python
_rotation_state: dict[str, dict] = {
  old_email: {"replacement_email": str, "phase": "waiting_idle"|"shutting_down", "started": datetime}
}
```
1. **Iteration N:** worker uptime > LIFETIME_SECONDS, not yet in _rotation_state → mark DRAINING, call `worker.launch(replacement_email)` → set phase="waiting_idle", store in _rotation_state
2. **Iteration N+1..N+M:** each loop checks if replacement worker reached IDLE (runtime_status=IDLE in DB). If yes → call `worker.shutdown_graceful(old_email)` → set phase="shutting_down"
3. **Iteration N+M+1:** cleanup _rotation_state entry

If worker is BUSY at deadline: still mark DRAINING, launch replacement, old worker finishes current task (no new tasks dispatched to DRAINING workers). Lifespan max 4h (hard stop).

### `app/orchestrator/dispatcher.py` — TaskDispatcher

```
TaskDispatcher
  .dispatch(task, email, worker_session_id) -> bool  # lease + WS send
  .complete(task_id, email, session_id) -> None       # validate + update + webhook
  .fail(task_id, email, error, session_id) -> None    # update + requeue (up to 3 attempts)
  .fire_webhook(batch_id, webhook_url) -> None        # POST on batch completion
```

**`complete()` flow:**
1. Validate task ownership (task.worker_session_id matches)
2. Save uploaded audio file, update Task → COMPLETED
3. If `task.batch_id` is set → query DB: `SELECT count(*) FROM tasks WHERE batch_id = X AND status IN ('PENDING','PROCESSING')`. If count = 0 → call `fire_webhook(batch_id, webhook_url)`

**`fire_webhook()` flow:**
1. Query all tasks with matching batch_id
2. Build payload: `{batch_id, status: "COMPLETED", tasks: [{task_id, text, status, audio_url, error_message}]}`
3. POST to webhook_url via httpx, timeout 10s
4. Log success/failure (non-blocking)

**`dispatch()` flow:**
1. `lease_task_to_worker(task, email, session_id)` — DB atomic UPDATE status='PROCESSING', lease timestamps, increment attempt. Task is rejected (not leased) if `task.leased_at` is within `TASK_RETRY_BACKOFF_SECONDS` of now (enforces backoff).
2. Build voice URL: `{SERVER_URL}/api/voices/{voice_id}/audio` (SERVER_URL from config, defaults to `http://localhost:8090`)
3. WS send `run_tts` with task data + params (num_step, guidance_scale)
4. If WS send fails → rollback lease, mark worker LOST, shutdown colab

**Retry policy:**
- `task.attempt >= TASK_MAX_ATTEMPTS (3)` → status = FAILED, not requeued
- `task.attempt < TASK_MAX_ATTEMPTS` → status = PENDING, backoff enforced by lease check above

### `app/orchestrator/lifecycle.py` — Lifecycle loop

Single `asyncio.Task` running every `POLL_INTERVAL` (15s):

**On startup** (before loop begins):
- Mark all `WorkerSession.status = ALIVE` → `LOST` (stale sessions from previous run)
- Set all `GoogleAccount.runtime_status = LOST` for workers that were IDLE/BUSY (no capacity leak)
- Requeue all `Task.status = PROCESSING` → `PENDING`
- Note: This is a clean slate — any mid-rotation replacement workers from a previous orchestrator run are also marked LOST. Acceptable trade-off: restart is rare, and MAX_LIFETIME cleanup handles orphans.

**Loop iterations (15s):**

1. **Heartbeat check** — workers with `last_heartbeat_at < now - HEARTBEAT_TIMEOUT` → mark LOST, call `worker.shutdown_immediate()`, call `dispatcher.fail()` for their active tasks
2. **Task lease reaper** — tasks PROCESSING with `lease_expires_at < now` AND worker is LOST → requeue. Does NOT act on leases where worker is still ALIVE (worker may be slow, not dead). Ownership: lifecycle owns "worker disappeared" recovery; dispatcher owns "WS send failed" recovery.
3. **Cooldown refresh** — `COOLDOWN` with `quota_reset_at < now` → `READY`
4. **Scale check** — `pool.scale_up_if_needed()`, `pool.scale_down_if_needed()`
5. **Rotation check** — worker uptime > `LIFETIME_SECONDS` → manage `_rotation_state` (launch replacement, wait IDLE, shutdown old)
6. **Hard kill check** — worker uptime > `MAX_LIFETIME_SECONDS` → `worker.shutdown_immediate(email)` (failsafe if rotation stalled)

## Protocol & WS Handler (Server ↔ Worker)

Based on actual `colab/worker.py` implementation. Each action maps to an orchestrator method:

| Direction | Message | Handler | DB Effect |
|---|---|---|---|
| Worker → Server | `{"action":"register","email":"...","worker_session_id":"...","gpu":"..."}` | `lifecycle.on_register(email, wsid)` | WorkerSession → ALIVE, GoogleAccount.runtime_status → WARMING |
| Worker → Server | `{"action":"pong_status","status":"...","worker_session_id":"..."}` | `lifecycle.on_pong(email, status)` | GoogleAccount.last_heartbeat_at = now, runtime_status = status, WorkerSession.last_alive_at = now |
| Worker → Server | `{"action":"status","status":"...","queue_size":N,"worker_session_id":"..."}` | `lifecycle.on_status(email, status)` | GoogleAccount.runtime_status = status |
| Worker → Server | `{"action":"task_completed","task_id":"...","worker_session_id":"..."}` | NOTIFICATION only — WS informs server task is done. Actual upload uses `POST /api/tasks/{id}/complete`. | None via WS (upload endpoint handles DB) |
| Worker → Server | `{"action":"task_failed","task_id":"...","error":"...","worker_session_id":"..."}` | `dispatcher.fail(task_id, error)` | Task → FAILED, attempt counter |
| Server → Worker | `{"action":"ping"}` | — | Worker responds with `pong_status` |
| Server → Worker | `{"action":"run_tts","task_id":"...","text":"...","voice_api_url":"...","num_step":...,"guidance_scale":...,"language":"...","voice_ref_text":"..."}` | `dispatcher.dispatch()` | Task → PROCESSING (via lease) |
| Server → Worker | `{"action":"shutdown"}` | `worker.shutdown_graceful()` or `worker.shutdown_immediate()` | WorkerSession → STOPPED |

**Canonical task completion path:**
1. Worker finishes TTS → POST `{server_url}/api/tasks/{task_id}/complete` with audio file + `worker_session_id`
2. Backend saves audio, updates Task → COMPLETED
3. After upload success → worker sends WS `task_completed` (best-effort notification for dashboard)
4. If POST fails → worker sends WS `task_failed`
  
The audio upload POST is the single source of truth. WS `task_completed` is advisory (dashboard refresh).

## Database

### GoogleAccount — remove fields
- `browser_session_id` (vestige of Playwright era)
- `lease_expires_at` (belongs on Task only)

Keep all other fields — they're actively used:
- `id`, `email`, `profile_name`, `status`, `last_active`, `quota_reset_at`
- `worker_session_id`, `runtime_status`, `current_task_id`, `last_heartbeat_at`, `started_at`, `colab_pid`, `idle_since`

### New table: `WorkerSession`

Tracks colab-cli session lifecycle. Separate from `runtime_status` on `GoogleAccount`:

| Field | Purpose |
|---|---|
| `WorkerSession.status` | Session-level: `STARTING → ALIVE → STOPPED / LOST` |
| `GoogleAccount.runtime_status` | Pool-level: `WARMING → IDLE → BUSY → DRAINING` |

Mapping: `STARTING` = no runtime_status yet, `ALIVE` = pool decides runtime_status, `STOPPED`/`LOST` = cleanup.

```python
class WorkerSession(Base):
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    worker_session_id = Column(String, unique=True, nullable=False)
    colab_endpoint = Column(String)
    colab_token = Column(String)
    session_name = Column(String)
    kernel_id = Column(String)
    keep_alive_pid = Column(Integer)  # best-effort, may be stale after restart
    started_at = Column(DateTime, default=now)
    last_alive_at = Column(DateTime)
    status = Column(String, default="STARTING")  # STARTING/ALIVE/STOPPED/LOST
```

Rationale: app-level tracking table for admin queries and dashboard. Populated independently from StateStore (which is owned by colab-cli's keep-alive daemon). No sync needed — they serve different purposes.

## Migration Strategy

### colab_cli_runner → orchestrator

Old `colab_cli_runner.py` imports pip-installed `colab_cli.*` modules. New code uses `app/colab_cli/` source copy. These are incompatible — they're the same package from different paths.

- **During rollout:** `colab_cli_runner.py` stays temporarily, continues using pip package
- **After orchestrator is wired:** delete `colab_cli_runner.py`, remove pip-installed `google-colab-cli` from requirements
- **No dual import needed** — orchestrator and old runner never coexist at runtime

## Deployment

- Backend container: `:8090`
- Frontend container (Next.js): `:3355`
- `docker-compose.yml` for both
- Frontend `next.config.ts` rewrites `/api/*`, `/ws/*` to backend container
- Cloudflare tunnel handled by frontend or external proxy, not in backend
- Docker volume mount `~/.config/colab-cli:/root/.config/colab-cli` on backend container to persist OAuth tokens across restarts
- `docker-compose.yml` structure:
  - backend: volumes `./data:/app/data` + `~/.config/colab-cli:/root/.config/colab-cli`
  - frontend: depends_on backend, port 3355

## Changes to Existing Files

| File | Change |
|---|---|
| `app/main.py` | Remove StaticFiles mount, SPA catch-all, Cloudflare tunnel, `_delayed_auto_pickup`, old lifespan imports |
| `app/routes/ws.py` | Remove browser_session_id refs, replace runner calls with orchestrator |
| `app/routes/accounts.py` | Remove `finish-login` endpoint, replace runner calls with orchestrator |
| `app/routes/tasks.py` | Replace runner.stop import with orchestrator |
| `Dockerfile.frontend` | Expose 3355 |
| `next.config.ts` | Add rewrites |
| `docker-compose.yml` | Add frontend service, expose 8090+3355 |
| `requirements.txt` | Remove `google-colab-cli` pip dep (replaced by source copy) |
| `run.py` / `run.bat` | Update default port to 8090 |
| `app/__init__.py` | Ensure orchestrator module importable |

## Deleted Files

- `app/lifecycle/` (reaper.py, reconciler.py, sessions.py, capacity.py, constants.py)
- `app/automation/cli_runner.py` (dead stub)
- `app/automation/colab_cli_runner.py` (migration complete)
- `main_backup.py`
- `app/routes/google_auth.py` (already dead ref)

## States

### Account lifecycle
```
READY → [launch worker] → ... worker finishes → COOLDOWN (16h) → READY
READY → [auth expired] → NEEDS_LOGIN → [re-auth via terminal] → READY
```

### Runtime lifecycle
```
STARTING → (worker WS connect) → WARMING → (model loaded) → IDLE
IDLE → (task assigned) → BUSY → (task done) → IDLE
IDLE → (lifetime exceeded) → DRAINING → replacement starts → STOPPED
BUSY → (lifetime exceeded + force) → DRAINING → STOPPED (finishes current task)
STOPPED → account back to READY for next launch
```

### Runtime statuses consuming capacity
STARTING, WARMING, IDLE, BUSY count toward `active_count` (scale-up/scale-down).
DRAINING excluded from `active_count` (replacement can launch), but counted toward MAX_WORKERS limit to prevent over-provisioning.

## Task Flow (TTS)

1. User calls `POST /api/tts/text` or `/batch` → Task created (status=PENDING)
2. `create_task()` → calls `pool.scale_up_if_needed()` + `dispatcher.dispatch()`
3. `dispatcher.dispatch()` → leases task (DB), sends WS `run_tts` to idle worker
4. Worker notebook executes TTS, saves audio, POSTs to `/api/tasks/{id}/complete`
5. Backend receives upload → saves WAV → updates DB (status=COMPLETED)
6. If batch + webhook_url → `dispatcher.fire_webhook()` when all tasks in batch done
7. On failure (WS timeout, worker disconnect, upload error) → `dispatcher.fail()` → requeue PENDING up to 3 attempts, then FAILED

## Rollout

1. Copy `src/colab_cli/` → `app/colab_cli/`
2. Write `app/orchestrator/constants.py`, `account.py`, `worker.py`, `pool.py`, `dispatcher.py`, `lifecycle.py`
3. Update routes (`ws.py`, `accounts.py`, `tasks.py`) to use orchestrator
4. Update `app/main.py` — remove old lifecycle, StaticFiles, SPA catch-all
5. DB migration — add WorkerSession table, drop `browser_session_id`, `lease_expires_at`
6. Frontend — update port, rewrites, Dockerfile
7. Update `docker-compose.yml`
8. Remove `colab_cli_runner.py`, `google-colab-cli` from requirements
9. Remove `app/automation/cli_runner.py`, `app/lifecycle/`
10. Test: 1 account boots + dispatches task → 2 accounts → 8 accounts
    - Success criteria: Worker launches, WS register, task dispatched, audio returned, webhook fired, cooldown rotates
    - Verify: no orphan colab-cli keep-alive processes after shutdown
    - Verify: task retries max 3 times then FAILED
    - Verify: rotation launches replacement before stopping old (no downtime)
    - Verify: scale-down keeps at least WARM_TARGET workers
