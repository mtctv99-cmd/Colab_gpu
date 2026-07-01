# Orchestrator Redesign — Implementation Plan

Based on spec: `docs/superpowers/specs/2026-06-15-orchestrator-redesign.md`

## Phases & Order

Phase 0: Copy colab-cli source
Phase 1: Write orchestrator modules (back-end, no route changes)
Phase 2: Update routes to use orchestrator
Phase 3: Clean up old code
Phase 4: Frontend changes + Docker
Phase 5: Test

Dependencies: Phase 0 → 1 → 2 → 3. Phase 4 independent of 1-3 (can run concurrently).

---

## Phase 0 — Copy Source

### P0.1 Copy google-colab-cli source into project

```bash
# From repo root
unzip /home/reup/Downloads/google-colab-cli-main.zip -d /tmp/gcc
cp -r /tmp/gcc/google-colab-cli-main/src/colab_cli app/colab_cli
sed -i 's/from colab_cli/from app.colab_cli/g' app/colab_cli/**/*.py
```

**Files:**
- `app/colab_cli/` (dir with ~8 .py files + commands/)

---

## Phase 1 — Orchestrator Modules

### P1.1 `app/orchestrator/__init__.py`

Make package importable. Empty init or re-export key classes:
```python
from app.orchestrator.lifecycle import start_lifecycle
```

### P1.2 `app/orchestrator/constants.py`

All constants from spec:
```python
# Account status
READY = "READY"
COOLDOWN = "COOLDOWN"
NEEDS_LOGIN = "NEEDS_LOGIN"
DISABLED = "DISABLED"

# Runtime status
IDLE = "IDLE"
BUSY = "BUSY"
WARMING = "WARMING"
STARTING = "STARTING"
LOST = "LOST"
DRAINING = "DRAINING"

# Pool config
MAX_WORKERS = 8
WARM_TARGET = 2
POLL_INTERVAL = 15
COOLDOWN_SECONDS = 57600
TASK_MAX_ATTEMPTS = 3
TASK_RETRY_BACKOFF_SECONDS = 60
IDLE_SCALE_DOWN_SECONDS = 1800
KEEP_ALIVE_INTERVAL = 60
HEARTBEAT_TIMEOUT = 75
LIFETIME_SECONDS = 13500
MAX_LIFETIME_SECONDS = 14400
SERVER_URL = "http://localhost:8090"

# WorkerSession status
WS_STARTING = "STARTING"
WS_ALIVE = "ALIVE"
WS_STOPPED = "STOPPED"
WS_LOST = "LOST"
```

### P1.3 `app/orchestrator/account.py`

**Class `AccountManager`:**
- `ready_accounts(db) → list[Account]` — `SELECT * FROM google_accounts WHERE status='READY' AND worker_session_id IS NULL`
- `get_account(db, email) → Account`
- `refresh_cooldowns(db) → int` — `SELECT * FROM google_accounts WHERE status='COOLDOWN' AND quota_reset_at <= now`, set each to READY
- `mark_needs_login(db, email)`
- `mark_cooldown(db, email, minutes)`

Uses `from app.colab_cli.auth import get_credentials, AuthProvider` for credential retrieval.

**Dependencies:** none (standalone)

### P1.4 `app/orchestrator/worker.py`

**Class `WorkerManager`:**
- `active_workers: dict[str, WorkerInstance]` — in-memory tracking
- `launch(email) -> str` — see spec launch flow
- `shutdown_immediate(email)` — see spec
- `shutdown_graceful(email)` — see spec
- `shutdown_all()` — iterate active_workers, shutdown_immediate each
- `zombie_cleanup()` — `pgrep -f colab_cli.cli.*keep-alive`, SIGKILL

**`launch()` implementation notes:**
- Use `get_credentials(config_path, provider=AuthProvider.OAUTH2)` → `requests.AuthorizedSession`
- `Client(Prod(), session).assign(uuid4(), variant=GPU, accelerator=T4)`
- `Client(Prod(), session).keep_alive_assignment(endpoint)` — catches 403 scope errors
- `spawn_keep_alive(endpoint, name, auth_provider, config_path)` — from `app.colab_cli.commands.session`
- Create `WorkerSession` record in DB, set `runtime_status = STARTING`

**`shutdown_immediate()` implementation notes:**
- Send WS shutdown (fire-and-forget)
- `os.kill(pid, signal.SIGKILL)`
- Get `ColabRuntime` from store, call `.stop(shutdown_kernel=True)`
- `client.unassign(endpoint)`
- `store.remove(name)`
- Delete `WorkerSession` record

**Dependencies:** AccountManager, DB models

### P1.5 `app/orchestrator/pool.py`

**Class `PoolManager`:**
- `active_count(db) -> int` — count workers with runtime_status in [STARTING, WARMING, IDLE, BUSY]
- `ready_account_count(db) -> int` — count GoogleAccount where status=READY and worker_session_id IS NULL
- `pending_tasks(db) -> int` — count Task where status=PENDING
- `scale_up_if_needed(db, worker_mgr, account_mgr) -> str|None`
- `scale_down_if_needed(db, worker_mgr) -> str|None`
- `select_account_for_launch(db) -> str` — `SELECT ... ORDER BY last_active ASC NULLS FIRST LIMIT 1`
- `select_account_for_shutdown(db, active_emails) -> str|None` — longest idle non-warm

**Scale logic implementation:**
```python
async def scale_up_if_needed(db, worker_mgr, account_mgr):
    active = await active_count(db)
    ready = await ready_account_count(db)
    pending = await pending_tasks(db)
    
    if active >= MAX_WORKERS or ready == 0:
        return None
    if active < WARM_TARGET:
        email = await select_account_for_launch(db)
        return await worker_mgr.launch(email)
    if pending > 0 and active < MAX_WORKERS:
        email = await select_account_for_launch(db)
        return await worker_mgr.launch(email)
    return None
```

**Dependencies:** AccountManager, WorkerManager

### P1.6 `app/orchestrator/dispatcher.py`

**Class `TaskDispatcher`:**
- `dispatch(db, task, email, wsid) -> bool`
- `complete(db, task_id, email, session_id) -> None`
- `fail(db, task_id, error, session_id) -> None`
- `fire_webhook(db, batch_id, webhook_url) -> None`

**Lease implementation:**
```python
async def lease_task(db, task, email, wsid):
    # SELECT FOR UPDATE / atomic UPDATE on task
    # Check attempt >= TASK_MAX_ATTEMPTS → fail
    # Check leased_at < now - TASK_RETRY_BACKOFF_SECONDS → skip (backoff)
    # UPDATE task SET status='PROCESSING', worker_id=..., 
    #   worker_session_id=wsid, attempt=attempt+1, leased_at=now,
    #   lease_expires_at=now+TASK_LEASE_SECONDS
    # UPDATE account SET runtime_status='BUSY'
```

**WS send:** Use `ConnectionManager.send_task()` from existing `ws.py` (refactor later — keep existing for now).

**Dependencies:** WS ConnectionManager, accounts, DB

### P1.7 `app/orchestrator/lifecycle.py`

**`start_lifecycle(app_state)`:**
1. On startup: cleanup stale sessions, reset PROCESSING tasks
2. Start `asyncio.create_task(_main_loop())`

**`_main_loop()`:** Every 15s:
1. Heartbeat check — `SELECT * WHERE last_heartbeat_at < now - HEARTBEAT_TIMEOUT` → shutdown_immediate
2. Task lease reaper — `SELECT * WHERE status='PROCESSING' AND lease_expires_at < now` → only if worker is LOST → requeue
3. Cooldown refresh
4. Scale up/down
5. Rotation check (manage `_rotation_state`)
6. Hard kill check (MAX_LIFETIME)

**Rotation state machine:**
```python
_rotation_state: dict[str, dict] = {}  # old_email → meta
# Phase "waiting_idle": replacement launched, polling for IDLE
# Phase "shutting_down": shutdown_graceful called
```

**Dependencies:** PoolManager, WorkerManager, Dispatcher

---

## Phase 2 — Route Updates

### P2.1 `app/routes/ws.py` — rewrite

**Changes:**
- Replace `colab_cli_runner` imports with `WorkerManager`
- `websocket_worker()` handler uses `WorkerManager` for shutdown, `TaskDispatcher` for completion/failure
- `websocket_dashboard()` — keep as-is
- `maintenance_loop()` → delegate to `lifecycle.py`'s startup
- Remove: `_try_dispatch_next_task`, old scale logic, old heartbeat loop
- Keep: `ConnectionManager`, `manager` singleton (still needed for WS send)

### P2.2 `app/routes/accounts.py` — update

**Changes:**
- `add_account()` → keep, remove `finish_login` endpoint
- `start_worker()` → use `WorkerManager.launch()`
- `stop_worker()` → use `WorkerManager.shutdown_immediate()`
- remove `finish-login` route
- remove `runner` import from `colab_cli_runner`

### P2.3 `app/routes/tasks.py` — update

**Changes:**
- Replace `runner.stop_colab_worker` import with `WorkerManager.shutdown_immediate`
- `create_task()` → call `Dispatcher.dispatch()`

### P2.4 `app/main.py` — rewrite

**Changes:**
- Remove `StaticFiles` mount + SPA catch-all route
- Remove `Cloudflare tunnel` startup
- Remove `_delayed_auto_pickup`
- Remove `app/lifecycle/reconciler` imports
- Startup: call `lifecycle.start_lifecycle()` only
- Keep: all route registrations, CORS, exception handlers, `ping`

---

## Phase 3 — Cleanup

### P3.1 Delete old files

- `app/automation/colab_cli_runner.py`
- `app/automation/cli_runner.py`
- `app/lifecycle/` (entire dir)
- `app/main_backup.py`
- Remove `google-colab-cli` from `requirements.txt`
- Remove `app.routes.google_auth` from any imports (already gone)

---

## Phase 4 — Frontend + Docker

### P4.1 `frontend/next.config.ts` — add rewrites

```typescript
const nextConfig = {
  // ... existing
  rewrites: async () => [
    { source: '/api/:path*', destination: 'http://backend:8090/api/:path*' },
    { source: '/ws/:path*', destination: 'http://backend:8090/ws/:path*' },
  ],
}
```

### P4.2 `Dockerfile.frontend` — update port

```diff
- EXPOSE 3000
+ EXPOSE 3355
- CMD ["npm", "start"]
+ CMD ["npm", "start", "--", "-p", "3355"]
```

### P4.3 `docker-compose.yml` — add frontend

Add frontend service, update backend ports/volumes.

---

## Phase 5 — Test

### P5.1 Unit test — orchestrator modules

Test each module in isolation:
- AccountManager: cooldown refresh, ready_accounts
- WorkerManager: launch flow (mock colab_cli), shutdown
- PoolManager: scale logic with mock counts

### P5.2 Integration test — 1 account

1. Boot server
2. Auth 1 account (via terminal `colab new`)
3. Create task → verify dispatch → worker registers → task completes → audio returned

### P5.3 Test — multiple accounts

1. Scale to 2+ accounts
2. Dispatch multiple tasks concurrently
3. Verify rotation at 3h45m

---

## File Creation Order

```
 1  app/colab_cli/                           (copy + sed)
 2  app/orchestrator/__init__.py
 3  app/orchestrator/constants.py
 4  app/orchestrator/account.py
 5  app/orchestrator/worker.py
 6  app/orchestrator/pool.py
 7  app/orchestrator/dispatcher.py
 8  app/orchestrator/lifecycle.py
 9  app/routes/ws.py                          (update)
10  app/routes/accounts.py                    (update)
11  app/routes/tasks.py                       (update)
12  app/main.py                               (rewrite)
13  Requirements, Docker, docker-compose       (update)
14  Delete old files
```
