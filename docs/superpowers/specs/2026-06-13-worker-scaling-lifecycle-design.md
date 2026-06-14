# Worker, Browser, and Account Lifecycle Design

Date: 2026-06-13

## Goal

Make server know exact state of every Google account, Playwright browser, Colab worker, and TTS task. Prevent orphan browsers, duplicate workers, stale task completions, and cold-start delays under load.

Chosen approach: lease/session model inside one backend orchestrator process.

## Scope

This design supports one FastAPI backend process acting as orchestrator. It scales Colab workers, not backend replicas.

`uvicorn --workers > 1` is out of scope until a shared queue, distributed locks, and pub/sub are added.

## Current Problems

Current code mixes durable account state and runtime worker state:

- `GoogleAccount.status` currently represents account eligibility, browser startup, worker loading, worker idle, worker busy, quota cooldown, and login state.
- `ConnectionManager.worker_info` stores important runtime truth only in memory.
- `BrowserRegistry` stores Playwright browser ownership only in memory.
- On crash/restart, DB can say account is `ACTIVE`/`BUSY` while browser and websocket are gone.
- A stale worker can reconnect or finish late after a task has been reset or reassigned.
- Capacity math counts only some statuses, so server can over-open or under-open workers.

## State Model

### Durable Account State

`GoogleAccount.status` becomes account eligibility only:

- `READY`: account can be used to launch a worker.
- `NEEDS_LOGIN`: saved browser profile is invalid or expired.
- `COOLDOWN`: account cannot be used until `quota_reset_at`.
- `DISABLED`: admin-disabled account.

Runtime states such as `STARTING`, `LOADING`, `IDLE`, and `BUSY` should not be stored as account eligibility. They belong to worker sessions.

### Runtime Worker State

Each worker session has one of these states:

- `STARTING_BROWSER`: Playwright is launching Colab.
- `CONNECTING_RUNTIME`: Colab browser is open and connecting runtime.
- `WARMING_MODEL`: worker websocket connected, model loading.
- `IDLE`: worker can accept a task.
- `BUSY`: worker is processing a task.
- `DRAINING`: worker should finish current work then stop.
- `STOPPING`: shutdown requested.
- `LOST`: heartbeat expired or websocket disconnected unexpectedly.

### Browser Ownership

Each Playwright browser launch gets `browser_session_id`.

Rules:

- One account can have at most one live `browser_session_id`.
- Startup kills old browsers, then clears all browser session fields.
- Before opening Playwright, scheduler reserves an account with a new `browser_session_id`.
- If account already has a browser session, scheduler must not open another browser for it.

### Worker Ownership

Each worker connection gets `worker_session_id`.

Rules:

- `worker_session_id` is generated before launching worker and passed into the Colab worker process/notebook.
- Worker register message includes `email` and `worker_session_id`.
- Server accepts register only if session matches reserved account.
- Every task dispatch stores `worker_session_id` on the task.
- Completion/failure is accepted only if task `worker_session_id` matches sender session.

## Database Changes

### GoogleAccount

Add:

- `worker_session_id: str | null`
- `browser_session_id: str | null`
- `runtime_status: str | null`
- `current_task_id: str | null`
- `last_heartbeat_at: datetime | null`
- `lease_expires_at: datetime | null`

Keep:

- `status`
- `started_at`
- `quota_reset_at`
- `colab_pid`
- `last_active`

Interpretation:

- `status` = account eligibility.
- `runtime_status` = current worker lifecycle state if session exists.
- `started_at` = when current worker session started. Used for lifetime/cooldown rotation.
- `lease_expires_at` = when stale session can be reaped.

### Task

Add:

- `worker_session_id: str | null`
- `attempt: int default 0`
- `leased_at: datetime | null`
- `lease_expires_at: datetime | null`

Rules:

- `PENDING` tasks must have no active lease.
- `PROCESSING` tasks must have `worker_id`, `worker_session_id`, `leased_at`, and `lease_expires_at`.
- If lease expires, reaper resets task to `PENDING`, clears worker fields, increments/keeps attempt policy.

## Startup Reconciler

On FastAPI startup:

1. Kill all old managed browser processes using `cleanup_zombie_browsers(kill_active=True)`.
2. Initialize DB.
3. Reset old runtime sessions:
   - Clear `worker_session_id`, `browser_session_id`, `runtime_status`, `current_task_id`, `lease_expires_at`, `colab_pid`.
   - For accounts in old runtime states (`CONNECTING`, `LOADING`, `ACTIVE`, `BUSY`, `OFFLINE`), convert to `READY` if not in cooldown and not login-disabled.
   - For `COOLDOWN`, keep cooldown until `quota_reset_at`, then convert to `READY`.
   - Keep `NEEDS_LOGIN` and `DISABLED` unchanged.
4. Reset orphan `PROCESSING` tasks to `PENDING` and clear worker lease fields.
5. Start maintenance loop.
6. Wait for server URL/tunnel if Cloudflare is enabled.
7. Launch workers until warm target is met.

## Warm Worker Rule

Server must keep at least one warm worker.

Warm count includes:

- `IDLE`
- `BUSY`
- `STARTING_BROWSER`
- `CONNECTING_RUNTIME`
- `WARMING_MODEL`

If warm count is 0 and at least one account is `READY`, launch one worker.

## Request-Time Scale Rule

When a request creates a task:

1. Try dispatch immediately to an `IDLE` worker.
2. Ensure one backup worker exists when load begins:
   - If total active/starting workers is 1, launch worker 2 if a `READY` account exists.
3. For worker 3+:
   - If `pending_count >= 10` and total active/starting workers is at least 2, mark heavy-load start time.
   - If condition still holds after 10 seconds, launch one more worker.
   - Repeat while condition persists, capped by `MAX_CONCURRENT_WORKERS` and ready accounts.
4. Never launch more workers than ready accounts or configured max.

## Capacity Formula

Use one scheduler function for all scale decisions:

```text
actual_capacity = count(runtime_status in [STARTING_BROWSER, CONNECTING_RUNTIME, WARMING_MODEL, IDLE, BUSY, DRAINING])
idle_capacity = count(runtime_status == IDLE)
pending_count = count(Task.status == PENDING)
processing_count = count(Task.status == PROCESSING)
ready_accounts = count(GoogleAccount.status == READY and worker_session_id is null and browser_session_id is null)
```

Launch allowed when:

```text
actual_capacity < MAX_CONCURRENT_WORKERS
ready_accounts > 0
```

Heavy-load launch allowed when:

```text
pending_count >= 10
actual_capacity >= 2
condition_age >= 10 seconds
```

## Dispatch Rule

Dispatch only to a fresh `IDLE` worker session:

1. Pick worker with:
   - websocket connected
   - `runtime_status == IDLE`
   - lease not expired
   - not `DRAINING`
2. Claim oldest pending task by priority:
   - direct/sync request priority first if implemented
   - then FIFO by `created_at`
3. Set task fields:
   - `status = PROCESSING`
   - `worker_id = account.id`
   - `worker_session_id = worker.worker_session_id`
   - `attempt += 1`
   - `leased_at = now`
   - `lease_expires_at = now + task timeout`
4. Set worker:
   - `runtime_status = BUSY`
   - `current_task_id = task.id`
5. Send websocket `run_tts` with `task_id` and `worker_session_id`.
6. If websocket send fails:
   - reset task to `PENDING`
   - mark worker `LOST`
   - schedule reaper/scale-up.

## Completion Rule

Worker completion must include:

- `task_id`
- `worker_session_id`

Server accepts completion only when:

- task exists
- task status is `PROCESSING`
- task `worker_session_id` equals sender `worker_session_id`
- sender worker is still connected or session lease is valid

If mismatch:

- ignore completion
- log warning
- do not overwrite task result

On accepted completion:

- mark task `COMPLETED`
- clear task lease fields
- set worker `runtime_status = IDLE`
- clear `current_task_id`
- dispatch next pending task if any.

## Failure and Reaper Rules

Maintenance loop runs every 15-30 seconds:

- Expire worker sessions whose heartbeat is stale.
- Mark worker `LOST`.
- Stop associated browser.
- Clear account runtime session fields.
- Reset account to `READY` unless cooldown/login state applies.
- Requeue task currently owned by stale worker.
- Expire processing tasks whose task lease passed `lease_expires_at`.
- Start replacement worker if warm target or pending load requires it.

## Cooldown and Worker Lifetime

Each worker session records `started_at`.

Cooldown starts when:

- worker reports `OUT_OF_QUOTA`
- worker reaches `WORKER_MAX_LIFETIME`
- Colab rejects runtime with quota/session-limit signal

Cooldown action:

1. Set account `status = COOLDOWN`.
2. Set `quota_reset_at = now + QUOTA_RESET_HOURS` or configured backoff.
3. Mark runtime `DRAINING` or `STOPPING`.
4. Stop browser session.
5. Clear worker/browser session fields.
6. Requeue unfinished processing task if any.
7. Launch replacement if capacity needs it.

When `quota_reset_at <= now`, maintenance changes account `COOLDOWN -> READY`.

## Scale Down Rule

When no work exists:

- If idle workers > 1, stop the worker with longest idle time.
- Stop one worker per maintenance interval to avoid oscillation.
- Keep exactly one warm worker if any account is available.

Do not stop:

- `BUSY` workers
- `STARTING_BROWSER` workers
- `CONNECTING_RUNTIME` workers
- `WARMING_MODEL` workers
- worker marked as only warm worker

## Admin Visibility

Add capacity/status endpoint, for example `/api/accounts/capacity` or `/api/admin/capacity`, returning:

- `max_workers`
- `warm_target`
- `active_capacity`
- `idle_workers`
- `busy_workers`
- `starting_workers`
- `pending_tasks`
- `processing_tasks`
- per account:
  - `email`
  - `status`
  - `runtime_status`
  - `worker_session_id`
  - `browser_session_id`
  - `started_at`
  - `last_heartbeat_at`
  - `quota_reset_at`
  - `current_task_id`

## Configuration

Keep or add settings:

- `KEEP_WARM_WORKERS = 1`
- `MAX_CONCURRENT_WORKERS = 4`
- `SCALE_UP_PENDING_THRESHOLD = 10`
- `SCALE_UP_SUSTAIN_SECONDS = 10`
- `SCALE_DOWN_IDLE_SECONDS = 1800`
- `WORKER_MAX_LIFETIME`
- `QUOTA_RESET_HOURS`
- `TASK_LEASE_SECONDS`
- `WORKER_HEARTBEAT_TIMEOUT_SECONDS`

## Implementation Slices

1. Add DB fields and migration/backfill.
2. Add startup reconciler.
3. Add worker/browser session ID reservation on launch.
4. Update websocket register/status/completion protocol to include `worker_session_id`.
5. Update dispatch and completion verification.
6. Rewrite capacity and autoscale logic using unified scheduler function.
7. Add scale-down logic and cooldown lifecycle.
8. Add admin capacity endpoint.
9. Add tests for startup cleanup, duplicate prevention, stale completion rejection, warm worker launch, heavy-load scale-up, and scale-down.

## Non-Goals

- Multi-backend orchestration.
- Redis/Postgres queue migration.
- Reconnect old browsers across backend restart.
- Running multiple Uvicorn worker processes.

## Open Operational Rule

Deployment must run a single backend process:

```bash
uvicorn app.main:app --workers 1
```

If multiple API replicas become required later, build a separate scheduler/control-plane design first.
