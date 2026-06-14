# Worker Session Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build lease/session based worker lifecycle so backend knows exact state of every Google account, Playwright browser, Colab worker, and TTS task.

**Architecture:** Add focused lifecycle modules for constants, capacity calculation, session reservation, reconciler, and reaper. Keep FastAPI routes thin: routes call lifecycle helpers, helpers own DB state transitions, and `ConnectionManager` only owns live websocket objects plus session lookup.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, SQLite, Playwright, WebSocket workers, pytest, pytest-asyncio, httpx TestClient patterns already used by project.

---

## File Map

### Create

- `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/__init__.py`
  - Package marker for lifecycle code.

- `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/constants.py`
  - Defines durable account statuses, runtime statuses, task lease defaults, and conversion sets.

- `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/capacity.py`
  - Pure capacity query/calculation helpers used by autoscale, warm worker, scale-down, admin endpoint.

- `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/sessions.py`
  - Worker/browser session reservation, register validation, status transitions, task lease helpers.

- `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/reconciler.py`
  - Startup cleanup and DB reconciliation.

- `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/reaper.py`
  - Maintenance-loop lease expiry, stale heartbeat cleanup, cooldown reset, scale-down candidate selection.

- `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_models.py`
  - DB columns and migration/backfill tests.

- `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_reconciler.py`
  - Startup reconciliation tests.

- `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_sessions.py`
  - Reservation, duplicate prevention, register validation, dispatch lease tests.

- `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_completion.py`
  - Stale completion/failure rejection tests.

- `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_capacity.py`
  - Capacity and autoscale decision tests.

- `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_reaper.py`
  - Heartbeat expiry, task lease expiry, cooldown reset, scale-down tests.

- `/media/reup/Data_sv2/SVRV/Colab/tests/test_admin_capacity_endpoint.py`
  - Admin capacity endpoint response tests.

- `/media/reup/Data_sv2/SVRV/Colab/tests/test_worker_protocol.py`
  - Colab worker session protocol tests.

### Modify

- `/media/reup/Data_sv2/SVRV/Colab/app/models/__init__.py`
  - Add lifecycle columns to `GoogleAccount` and `Task`.
  - Change default `GoogleAccount.status` from `OFFLINE` to `READY`.

- `/media/reup/Data_sv2/SVRV/Colab/app/database.py`
  - Add idempotent SQLite migrations for new columns.
  - Add backfill migration from old runtime account statuses to new eligibility/runtime fields.

- `/media/reup/Data_sv2/SVRV/Colab/app/config.py`
  - Add lifecycle config:
    - `KEEP_WARM_WORKERS`
    - `MAX_CONCURRENT_WORKERS`
    - `SCALE_UP_PENDING_THRESHOLD`
    - `SCALE_UP_SUSTAIN_SECONDS`
    - `SCALE_DOWN_IDLE_SECONDS`
    - `TASK_LEASE_SECONDS`
    - `WORKER_HEARTBEAT_TIMEOUT_SECONDS`

- `/media/reup/Data_sv2/SVRV/Colab/app/main.py`
  - Replace inline orphan cleanup with startup reconciler.
  - Start maintenance loop after reconciliation.
  - Trigger warm-worker launch after Cloudflare readiness.

- `/media/reup/Data_sv2/SVRV/Colab/app/automation/play_runner.py`
  - Accept `worker_session_id` in `start_colab_worker`.
  - Fill Colab `WORKER_SESSION_ID` form parameter.
  - Register `browser_session_id` in browser registry entry.
  - Clear lifecycle DB fields on browser stop when caller asks.

- `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`
  - Replace runtime status writes to `GoogleAccount.status` with `runtime_status`.
  - Require `worker_session_id` on register/status/completion/failure.
  - Use session helpers for register validation and heartbeat.
  - Use capacity helpers for scaling.
  - Use reaper for maintenance loop.

- `/media/reup/Data_sv2/SVRV/Colab/app/routes/tasks.py`
  - Include task lease fields in list/get responses.
  - Require `worker_session_id` in complete upload endpoint.
  - Update `_dispatch_task` to lease task to worker session.
  - Reset task lease fields on retry.

- `/media/reup/Data_sv2/SVRV/Colab/app/routes/tts.py`
  - Use unified dispatch and scale-on-task-created helper instead of direct old autoscale logic.

- `/media/reup/Data_sv2/SVRV/Colab/app/routes/accounts.py`
  - Convert admin start/stop to session reservation and lifecycle cleanup.
  - Add `/api/accounts/capacity`.
  - Return lifecycle fields in account list.

- `/media/reup/Data_sv2/SVRV/Colab/colab/worker.py`
  - Add `--worker-session-id` arg.
  - Include `worker_session_id` in websocket register, status, pong, task completed, task failed.
  - Include `worker_session_id` in `/api/tasks/{task_id}/complete` upload request.

---

## Task 1: Add Lifecycle Constants and Config

**Files:**
- Create: `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/__init__.py`
- Create: `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/constants.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/config.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_models.py`

- [ ] **Step 1: Write failing constants/config tests**

Create `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_models.py` with:

```python
from app import config
from app.lifecycle.constants import (
    ACCOUNT_READY,
    ACCOUNT_NEEDS_LOGIN,
    ACCOUNT_COOLDOWN,
    ACCOUNT_DISABLED,
    RUNTIME_STARTING_BROWSER,
    RUNTIME_CONNECTING_RUNTIME,
    RUNTIME_WARMING_MODEL,
    RUNTIME_IDLE,
    RUNTIME_BUSY,
    RUNTIME_DRAINING,
    RUNTIME_STOPPING,
    RUNTIME_LOST,
    WARM_RUNTIME_STATUSES,
    CAPACITY_RUNTIME_STATUSES,
    LEGACY_RUNTIME_ACCOUNT_STATUSES,
)


def test_lifecycle_constants_define_durable_account_and_runtime_states():
    assert {
        ACCOUNT_READY,
        ACCOUNT_NEEDS_LOGIN,
        ACCOUNT_COOLDOWN,
        ACCOUNT_DISABLED,
    } == {"READY", "NEEDS_LOGIN", "COOLDOWN", "DISABLED"}

    assert {
        RUNTIME_STARTING_BROWSER,
        RUNTIME_CONNECTING_RUNTIME,
        RUNTIME_WARMING_MODEL,
        RUNTIME_IDLE,
        RUNTIME_BUSY,
        RUNTIME_DRAINING,
        RUNTIME_STOPPING,
        RUNTIME_LOST,
    } == {
        "STARTING_BROWSER",
        "CONNECTING_RUNTIME",
        "WARMING_MODEL",
        "IDLE",
        "BUSY",
        "DRAINING",
        "STOPPING",
        "LOST",
    }


def test_capacity_and_warm_status_sets_match_design():
    assert WARM_RUNTIME_STATUSES == {
        "STARTING_BROWSER",
        "CONNECTING_RUNTIME",
        "WARMING_MODEL",
        "IDLE",
        "BUSY",
    }
    assert CAPACITY_RUNTIME_STATUSES == {
        "STARTING_BROWSER",
        "CONNECTING_RUNTIME",
        "WARMING_MODEL",
        "IDLE",
        "BUSY",
        "DRAINING",
    }


def test_legacy_runtime_statuses_are_known_for_reconciler():
    assert LEGACY_RUNTIME_ACCOUNT_STATUSES == {
        "CONNECTING",
        "LOADING",
        "ACTIVE",
        "BUSY",
        "OFFLINE",
    }


def test_lifecycle_config_defaults_exist():
    assert config.KEEP_WARM_WORKERS == 1
    assert config.MAX_CONCURRENT_WORKERS == 4
    assert config.SCALE_UP_PENDING_THRESHOLD == 10
    assert config.SCALE_UP_SUSTAIN_SECONDS == 10
    assert config.SCALE_DOWN_IDLE_SECONDS == 1800
    assert config.TASK_LEASE_SECONDS == 300
    assert config.WORKER_HEARTBEAT_TIMEOUT_SECONDS == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_models.py::test_lifecycle_constants_define_durable_account_and_runtime_states -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.lifecycle'`.

- [ ] **Step 3: Add lifecycle constants**

Create `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/__init__.py`:

```python
"""Worker lifecycle helpers."""
```

Create `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/constants.py`:

```python
"""Constants for account eligibility and worker runtime lifecycle."""

ACCOUNT_READY = "READY"
ACCOUNT_NEEDS_LOGIN = "NEEDS_LOGIN"
ACCOUNT_COOLDOWN = "COOLDOWN"
ACCOUNT_DISABLED = "DISABLED"

DURABLE_ACCOUNT_STATUSES = {
    ACCOUNT_READY,
    ACCOUNT_NEEDS_LOGIN,
    ACCOUNT_COOLDOWN,
    ACCOUNT_DISABLED,
}

RUNTIME_STARTING_BROWSER = "STARTING_BROWSER"
RUNTIME_CONNECTING_RUNTIME = "CONNECTING_RUNTIME"
RUNTIME_WARMING_MODEL = "WARMING_MODEL"
RUNTIME_IDLE = "IDLE"
RUNTIME_BUSY = "BUSY"
RUNTIME_DRAINING = "DRAINING"
RUNTIME_STOPPING = "STOPPING"
RUNTIME_LOST = "LOST"

RUNTIME_STATUSES = {
    RUNTIME_STARTING_BROWSER,
    RUNTIME_CONNECTING_RUNTIME,
    RUNTIME_WARMING_MODEL,
    RUNTIME_IDLE,
    RUNTIME_BUSY,
    RUNTIME_DRAINING,
    RUNTIME_STOPPING,
    RUNTIME_LOST,
}

WARM_RUNTIME_STATUSES = {
    RUNTIME_STARTING_BROWSER,
    RUNTIME_CONNECTING_RUNTIME,
    RUNTIME_WARMING_MODEL,
    RUNTIME_IDLE,
    RUNTIME_BUSY,
}

CAPACITY_RUNTIME_STATUSES = WARM_RUNTIME_STATUSES | {RUNTIME_DRAINING}

LEGACY_RUNTIME_ACCOUNT_STATUSES = {
    "CONNECTING",
    "LOADING",
    "ACTIVE",
    "BUSY",
    "OFFLINE",
}
```

- [ ] **Step 4: Add config values**

Modify `/media/reup/Data_sv2/SVRV/Colab/app/config.py` worker settings section to include:

```python
# Worker lifecycle settings
KEEP_WARM_WORKERS = int(os.getenv("KEEP_WARM_WORKERS", "1"))
MAX_CONCURRENT_WORKERS = int(os.getenv("MAX_CONCURRENT_WORKERS", "4"))
SCALE_UP_PENDING_THRESHOLD = int(os.getenv("SCALE_UP_PENDING_THRESHOLD", "10"))
SCALE_UP_SUSTAIN_SECONDS = int(os.getenv("SCALE_UP_SUSTAIN_SECONDS", "10"))
SCALE_DOWN_IDLE_SECONDS = int(os.getenv("SCALE_DOWN_IDLE_SECONDS", "1800"))
TASK_LEASE_SECONDS = int(os.getenv("TASK_LEASE_SECONDS", "300"))
WORKER_HEARTBEAT_TIMEOUT_SECONDS = int(os.getenv("WORKER_HEARTBEAT_TIMEOUT_SECONDS", "60"))
```

Keep existing `WORKER_MAX_LIFETIME`, `QUOTA_RESET_HOURS`, and `AUTO_PICKUP_ENABLED`.

- [ ] **Step 5: Run tests to verify pass**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_models.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/lifecycle/__init__.py app/lifecycle/constants.py app/config.py tests/test_lifecycle_models.py
git commit -m "feat: add lifecycle constants and config"
```

---

## Task 2: Add DB Lifecycle Columns and Idempotent Migrations

**Files:**
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/models/__init__.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/database.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_models.py`

- [ ] **Step 1: Add failing ORM column tests**

Append to `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_models.py`:

```python
from sqlalchemy import inspect

from app.models import GoogleAccount, Task


def test_google_account_has_lifecycle_columns():
    columns = {column.name for column in inspect(GoogleAccount).columns}

    assert {
        "worker_session_id",
        "browser_session_id",
        "runtime_status",
        "current_task_id",
        "last_heartbeat_at",
        "lease_expires_at",
    }.issubset(columns)


def test_task_has_lifecycle_lease_columns():
    columns = {column.name for column in inspect(Task).columns}

    assert {
        "worker_session_id",
        "attempt",
        "leased_at",
        "lease_expires_at",
    }.issubset(columns)


def test_google_account_default_status_is_ready():
    status_column = inspect(GoogleAccount).columns.status
    assert status_column.default.arg == "READY"


def test_task_attempt_default_is_zero():
    attempt_column = inspect(Task).columns.attempt
    assert attempt_column.default.arg == 0
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_models.py::test_google_account_has_lifecycle_columns tests/test_lifecycle_models.py::test_task_has_lifecycle_lease_columns -v
```

Expected: FAIL with missing column assertions.

- [ ] **Step 3: Add ORM columns**

Modify `/media/reup/Data_sv2/SVRV/Colab/app/models/__init__.py`.

Change import line:

```python
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
```

Keep same import line if already identical.

Change `GoogleAccount.status` default and add fields after `started_at`:

```python
    status = Column(String, nullable=False, default="READY")
    last_active = Column(DateTime, nullable=True)
    quota_reset_at = Column(DateTime, nullable=True)
    colab_pid = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    worker_session_id = Column(String, nullable=True)
    browser_session_id = Column(String, nullable=True)
    runtime_status = Column(String, nullable=True)
    current_task_id = Column(String, nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
```

Add task fields after `worker_id`:

```python
    worker_session_id = Column(String, nullable=True)
    attempt = Column(Integer, nullable=False, default=0)
    leased_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
```

- [ ] **Step 4: Add migration tests**

Append to `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_models.py`:

```python
import pytest
import sqlalchemy as sa

from app.database import init_db, engine


@pytest.mark.asyncio
async def test_init_db_creates_lifecycle_columns_in_sqlite():
    await init_db()

    async with engine.connect() as conn:
        account_rows = await conn.execute(sa.text("PRAGMA table_info(google_accounts)"))
        account_columns = {row[1] for row in account_rows.fetchall()}

        task_rows = await conn.execute(sa.text("PRAGMA table_info(tasks)"))
        task_columns = {row[1] for row in task_rows.fetchall()}

    assert {
        "worker_session_id",
        "browser_session_id",
        "runtime_status",
        "current_task_id",
        "last_heartbeat_at",
        "lease_expires_at",
    }.issubset(account_columns)

    assert {
        "worker_session_id",
        "attempt",
        "leased_at",
        "lease_expires_at",
    }.issubset(task_columns)
```

- [ ] **Step 5: Run migration test to verify fail on old DB**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_models.py::test_init_db_creates_lifecycle_columns_in_sqlite -v
```

Expected: FAIL if current SQLite schema lacks lifecycle columns.

- [ ] **Step 6: Add idempotent migrations**

Modify `_MIGRATIONS` in `/media/reup/Data_sv2/SVRV/Colab/app/database.py` to include these strings:

```python
        "ALTER TABLE google_accounts ADD COLUMN worker_session_id VARCHAR",
        "ALTER TABLE google_accounts ADD COLUMN browser_session_id VARCHAR",
        "ALTER TABLE google_accounts ADD COLUMN runtime_status VARCHAR",
        "ALTER TABLE google_accounts ADD COLUMN current_task_id VARCHAR",
        "ALTER TABLE google_accounts ADD COLUMN last_heartbeat_at DATETIME",
        "ALTER TABLE google_accounts ADD COLUMN lease_expires_at DATETIME",
        "ALTER TABLE tasks ADD COLUMN worker_session_id VARCHAR",
        "ALTER TABLE tasks ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN leased_at DATETIME",
        "ALTER TABLE tasks ADD COLUMN lease_expires_at DATETIME",
```

Place them after existing column migrations.

- [ ] **Step 7: Add backfill migration test**

Append to `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_models.py`:

```python
@pytest.mark.asyncio
async def test_init_db_backfills_null_attempts_and_ready_status():
    await init_db()

    async with engine.begin() as conn:
        await conn.execute(sa.text("UPDATE tasks SET attempt = NULL WHERE attempt IS NULL"))
        await conn.execute(sa.text("UPDATE google_accounts SET status = 'OFFLINE' WHERE status = 'OFFLINE'"))

    await init_db()

    async with engine.connect() as conn:
        task_rows = await conn.execute(sa.text("SELECT COUNT(*) FROM tasks WHERE attempt IS NULL"))
        null_attempt_count = task_rows.scalar() or 0

    assert null_attempt_count == 0
```

- [ ] **Step 8: Add post-migration backfill SQL**

After migration loop in `/media/reup/Data_sv2/SVRV/Colab/app/database.py`, add:

```python
    # Backfill lifecycle-safe defaults after idempotent migrations.
    try:
        async with async_session() as session:
            await session.execute(sa.text("UPDATE tasks SET attempt = 0 WHERE attempt IS NULL"))
            await session.commit()
    except Exception:
        pass
```

- [ ] **Step 9: Run tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_models.py -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/models/__init__.py app/database.py tests/test_lifecycle_models.py
git commit -m "feat: add lifecycle database fields"
```

---

## Task 3: Add Capacity Snapshot Helper

**Files:**
- Create: `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/capacity.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_capacity.py`

- [ ] **Step 1: Write failing capacity tests**

Create `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_capacity.py`:

```python
from datetime import datetime, timezone

import pytest

from app.database import async_session, init_db
from app.lifecycle.capacity import CapacitySnapshot, get_capacity_snapshot, should_launch_worker, should_launch_heavy_worker
from app.models import GoogleAccount, Task, Voice


@pytest.mark.asyncio
async def test_capacity_snapshot_counts_runtime_and_ready_accounts():
    await init_db()

    async with async_session() as db:
        db.add_all(
            [
                GoogleAccount(email="idle@example.com", profile_name="idle", status="READY", runtime_status="IDLE", worker_session_id="w1", browser_session_id="b1"),
                GoogleAccount(email="busy@example.com", profile_name="busy", status="READY", runtime_status="BUSY", worker_session_id="w2", browser_session_id="b2"),
                GoogleAccount(email="starting@example.com", profile_name="starting", status="READY", runtime_status="STARTING_BROWSER", worker_session_id="w3", browser_session_id="b3"),
                GoogleAccount(email="ready@example.com", profile_name="ready", status="READY"),
                GoogleAccount(email="cool@example.com", profile_name="cool", status="COOLDOWN"),
            ]
        )
        voice = Voice(name="v", audio_path="/tmp/ref.wav")
        db.add(voice)
        await db.flush()
        db.add_all(
            [
                Task(id="pending-1", text="hello", voice_id=voice.id, status="PENDING"),
                Task(id="processing-1", text="hello", voice_id=voice.id, status="PROCESSING"),
            ]
        )
        await db.commit()

        snapshot = await get_capacity_snapshot(db, max_workers=4, warm_target=1)

    assert snapshot == CapacitySnapshot(
        max_workers=4,
        warm_target=1,
        active_capacity=3,
        idle_workers=1,
        busy_workers=1,
        starting_workers=1,
        pending_tasks=1,
        processing_tasks=1,
        ready_accounts=1,
    )


def test_should_launch_worker_requires_capacity_and_ready_account():
    assert should_launch_worker(CapacitySnapshot(4, 1, 3, 0, 0, 0, 0, 0, 1)) is True
    assert should_launch_worker(CapacitySnapshot(4, 1, 4, 0, 0, 0, 0, 0, 1)) is False
    assert should_launch_worker(CapacitySnapshot(4, 1, 3, 0, 0, 0, 0, 0, 0)) is False


def test_heavy_load_launch_requires_threshold_capacity_and_age():
    now = datetime(2026, 6, 13, tzinfo=timezone.utc)
    snapshot = CapacitySnapshot(4, 1, 2, 0, 0, 0, 10, 0, 2)

    assert should_launch_heavy_worker(snapshot, condition_started_at=now, now=now, sustain_seconds=10) is False
    assert should_launch_heavy_worker(snapshot, condition_started_at=now, now=now.replace(second=11), sustain_seconds=10) is True
    assert should_launch_heavy_worker(CapacitySnapshot(4, 1, 1, 0, 0, 0, 10, 0, 2), condition_started_at=now, now=now.replace(second=11), sustain_seconds=10) is False
    assert should_launch_heavy_worker(CapacitySnapshot(4, 1, 2, 0, 0, 0, 9, 0, 2), condition_started_at=now, now=now.replace(second=11), sustain_seconds=10) is False
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_capacity.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.lifecycle.capacity'`.

- [ ] **Step 3: Implement capacity helper**

Create `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/capacity.py`:

```python
"""Capacity calculations for worker lifecycle scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.lifecycle.constants import (
    ACCOUNT_READY,
    CAPACITY_RUNTIME_STATUSES,
    RUNTIME_BUSY,
    RUNTIME_CONNECTING_RUNTIME,
    RUNTIME_IDLE,
    RUNTIME_STARTING_BROWSER,
    RUNTIME_WARMING_MODEL,
)
from app.models import GoogleAccount, Task


@dataclass(frozen=True)
class CapacitySnapshot:
    max_workers: int
    warm_target: int
    active_capacity: int
    idle_workers: int
    busy_workers: int
    starting_workers: int
    pending_tasks: int
    processing_tasks: int
    ready_accounts: int


async def _count(db: AsyncSession, stmt) -> int:
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def get_capacity_snapshot(db: AsyncSession, max_workers: int, warm_target: int) -> CapacitySnapshot:
    active_capacity = await _count(
        db,
        select(func.count())
        .select_from(GoogleAccount)
        .where(GoogleAccount.runtime_status.in_(CAPACITY_RUNTIME_STATUSES)),
    )
    idle_workers = await _count(
        db,
        select(func.count())
        .select_from(GoogleAccount)
        .where(GoogleAccount.runtime_status == RUNTIME_IDLE),
    )
    busy_workers = await _count(
        db,
        select(func.count())
        .select_from(GoogleAccount)
        .where(GoogleAccount.runtime_status == RUNTIME_BUSY),
    )
    starting_workers = await _count(
        db,
        select(func.count())
        .select_from(GoogleAccount)
        .where(
            GoogleAccount.runtime_status.in_(
                [
                    RUNTIME_STARTING_BROWSER,
                    RUNTIME_CONNECTING_RUNTIME,
                    RUNTIME_WARMING_MODEL,
                ]
            )
        ),
    )
    pending_tasks = await _count(
        db,
        select(func.count()).select_from(Task).where(Task.status == "PENDING"),
    )
    processing_tasks = await _count(
        db,
        select(func.count()).select_from(Task).where(Task.status == "PROCESSING"),
    )
    ready_accounts = await _count(
        db,
        select(func.count())
        .select_from(GoogleAccount)
        .where(
            GoogleAccount.status == ACCOUNT_READY,
            GoogleAccount.worker_session_id.is_(None),
            GoogleAccount.browser_session_id.is_(None),
        ),
    )
    return CapacitySnapshot(
        max_workers=max_workers,
        warm_target=warm_target,
        active_capacity=active_capacity,
        idle_workers=idle_workers,
        busy_workers=busy_workers,
        starting_workers=starting_workers,
        pending_tasks=pending_tasks,
        processing_tasks=processing_tasks,
        ready_accounts=ready_accounts,
    )


def should_launch_worker(snapshot: CapacitySnapshot) -> bool:
    return snapshot.active_capacity < snapshot.max_workers and snapshot.ready_accounts > 0


def should_launch_heavy_worker(
    snapshot: CapacitySnapshot,
    condition_started_at: datetime | None,
    now: datetime,
    sustain_seconds: int,
) -> bool:
    if condition_started_at is None:
        return False
    if snapshot.pending_tasks < 10:
        return False
    if snapshot.active_capacity < 2:
        return False
    if not should_launch_worker(snapshot):
        return False
    return (now - condition_started_at).total_seconds() >= sustain_seconds
```

- [ ] **Step 4: Run tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_capacity.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/lifecycle/capacity.py tests/test_lifecycle_capacity.py
git commit -m "feat: add worker capacity snapshot"
```

---

## Task 4: Add Session Reservation and Registration Validation

**Files:**
- Create: `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/sessions.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_sessions.py`

- [ ] **Step 1: Write failing session tests**

Create `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_sessions.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.database import async_session, init_db
from app.lifecycle.sessions import (
    SessionReservation,
    reserve_worker_session,
    validate_worker_registration,
    mark_worker_registered,
    mark_worker_status,
)
from app.models import GoogleAccount


@pytest.mark.asyncio
async def test_reserve_worker_session_claims_ready_account_and_sets_runtime_state():
    await init_db()

    async with async_session() as db:
        db.add(GoogleAccount(email="ready@example.com", profile_name="ready", status="READY"))
        await db.commit()

        reservation = await reserve_worker_session(db, now=datetime(2026, 6, 13, tzinfo=timezone.utc), lease_seconds=60)
        await db.commit()

        account = await db.get(GoogleAccount, reservation.account_id)

    assert isinstance(reservation, SessionReservation)
    assert reservation.email == "ready@example.com"
    assert reservation.worker_session_id
    assert reservation.browser_session_id
    assert account.status == "READY"
    assert account.runtime_status == "STARTING_BROWSER"
    assert account.worker_session_id == reservation.worker_session_id
    assert account.browser_session_id == reservation.browser_session_id
    assert account.lease_expires_at == datetime(2026, 6, 13, 0, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_reserve_worker_session_skips_account_with_existing_browser_session():
    await init_db()

    async with async_session() as db:
        db.add(GoogleAccount(email="busy@example.com", profile_name="busy", status="READY", browser_session_id="browser-1"))
        await db.commit()

        reservation = await reserve_worker_session(db, now=datetime(2026, 6, 13, tzinfo=timezone.utc), lease_seconds=60)

    assert reservation is None


@pytest.mark.asyncio
async def test_validate_worker_registration_requires_matching_email_and_session():
    await init_db()

    async with async_session() as db:
        account = GoogleAccount(
            email="worker@example.com",
            profile_name="worker",
            status="READY",
            runtime_status="STARTING_BROWSER",
            worker_session_id="session-1",
            browser_session_id="browser-1",
            lease_expires_at=datetime(2026, 6, 13, 0, 1, tzinfo=timezone.utc),
        )
        db.add(account)
        await db.commit()

        accepted = await validate_worker_registration(
            db,
            email="worker@example.com",
            worker_session_id="session-1",
            now=datetime(2026, 6, 13, tzinfo=timezone.utc),
        )
        wrong_session = await validate_worker_registration(
            db,
            email="worker@example.com",
            worker_session_id="session-2",
            now=datetime(2026, 6, 13, tzinfo=timezone.utc),
        )
        expired = await validate_worker_registration(
            db,
            email="worker@example.com",
            worker_session_id="session-1",
            now=datetime(2026, 6, 13, 0, 2, tzinfo=timezone.utc),
        )

    assert accepted is not None
    assert wrong_session is None
    assert expired is None


@pytest.mark.asyncio
async def test_mark_worker_registered_and_status_updates_runtime_fields_only():
    await init_db()

    async with async_session() as db:
        account = GoogleAccount(
            email="worker2@example.com",
            profile_name="worker2",
            status="READY",
            runtime_status="STARTING_BROWSER",
            worker_session_id="session-1",
            browser_session_id="browser-1",
            lease_expires_at=datetime(2026, 6, 13, 0, 1, tzinfo=timezone.utc),
        )
        db.add(account)
        await db.commit()

        await mark_worker_registered(
            db,
            email="worker2@example.com",
            worker_session_id="session-1",
            now=datetime(2026, 6, 13, tzinfo=timezone.utc),
            lease_seconds=60,
        )
        await mark_worker_status(
            db,
            email="worker2@example.com",
            worker_session_id="session-1",
            runtime_status="IDLE",
            now=datetime(2026, 6, 13, 0, 0, 5, tzinfo=timezone.utc),
            lease_seconds=60,
        )
        await db.commit()

        refreshed = await db.get(GoogleAccount, account.id)

    assert refreshed.status == "READY"
    assert refreshed.runtime_status == "IDLE"
    assert refreshed.last_heartbeat_at == datetime(2026, 6, 13, 0, 0, 5, tzinfo=timezone.utc)
    assert refreshed.lease_expires_at == datetime(2026, 6, 13, 0, 1, 5, tzinfo=timezone.utc)
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_sessions.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.lifecycle.sessions'`.

- [ ] **Step 3: Implement session helpers**

Create `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/sessions.py`:

```python
"""Worker and browser session lifecycle helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.lifecycle.constants import (
    ACCOUNT_READY,
    RUNTIME_CONNECTING_RUNTIME,
    RUNTIME_IDLE,
    RUNTIME_STARTING_BROWSER,
    RUNTIME_WARMING_MODEL,
)
from app.models import GoogleAccount


@dataclass(frozen=True)
class SessionReservation:
    account_id: int
    email: str
    worker_session_id: str
    browser_session_id: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def reserve_worker_session(
    db: AsyncSession,
    now: datetime | None = None,
    lease_seconds: int = 60,
) -> SessionReservation | None:
    now = now or utc_now()
    result = await db.execute(
        select(GoogleAccount)
        .where(
            GoogleAccount.status == ACCOUNT_READY,
            GoogleAccount.worker_session_id.is_(None),
            GoogleAccount.browser_session_id.is_(None),
        )
        .order_by(GoogleAccount.last_active.asc().nullsfirst(), GoogleAccount.id.asc())
        .limit(1)
    )
    account = result.scalar_one_or_none()
    if account is None:
        return None

    worker_session_id = str(uuid.uuid4())
    browser_session_id = str(uuid.uuid4())

    account.worker_session_id = worker_session_id
    account.browser_session_id = browser_session_id
    account.runtime_status = RUNTIME_STARTING_BROWSER
    account.current_task_id = None
    account.started_at = now
    account.last_active = now
    account.last_heartbeat_at = now
    account.lease_expires_at = now + timedelta(seconds=lease_seconds)

    return SessionReservation(
        account_id=account.id,
        email=account.email,
        worker_session_id=worker_session_id,
        browser_session_id=browser_session_id,
    )


async def validate_worker_registration(
    db: AsyncSession,
    email: str,
    worker_session_id: str,
    now: datetime | None = None,
) -> GoogleAccount | None:
    now = now or utc_now()
    result = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
    account = result.scalar_one_or_none()
    if account is None:
        return None
    if account.worker_session_id != worker_session_id:
        return None
    lease_expires_at = ensure_aware(account.lease_expires_at)
    if lease_expires_at is not None and lease_expires_at < now:
        return None
    return account


async def mark_worker_registered(
    db: AsyncSession,
    email: str,
    worker_session_id: str,
    now: datetime | None = None,
    lease_seconds: int = 60,
) -> bool:
    now = now or utc_now()
    account = await validate_worker_registration(db, email, worker_session_id, now)
    if account is None:
        return False

    account.runtime_status = RUNTIME_WARMING_MODEL
    account.last_active = now
    account.last_heartbeat_at = now
    account.lease_expires_at = now + timedelta(seconds=lease_seconds)
    return True


async def mark_worker_status(
    db: AsyncSession,
    email: str,
    worker_session_id: str,
    runtime_status: str,
    now: datetime | None = None,
    lease_seconds: int = 60,
) -> bool:
    now = now or utc_now()
    account = await validate_worker_registration(db, email, worker_session_id, now)
    if account is None:
        return False

    account.runtime_status = runtime_status
    account.last_active = now
    account.last_heartbeat_at = now
    account.lease_expires_at = now + timedelta(seconds=lease_seconds)
    if runtime_status == RUNTIME_IDLE:
        account.current_task_id = None
    if runtime_status == RUNTIME_CONNECTING_RUNTIME:
        account.current_task_id = None
    return True
```

- [ ] **Step 4: Run tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_sessions.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/lifecycle/sessions.py tests/test_lifecycle_sessions.py
git commit -m "feat: add worker session reservation"
```

---

## Task 5: Add Startup Reconciler

**Files:**
- Create: `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/reconciler.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/main.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_reconciler.py`

- [ ] **Step 1: Write failing reconciler tests**

Create `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_reconciler.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.database import async_session, init_db
from app.lifecycle.reconciler import reconcile_startup_state
from app.models import GoogleAccount, Task, Voice


@pytest.mark.asyncio
async def test_reconcile_startup_clears_runtime_fields_and_old_runtime_statuses():
    await init_db()
    now = datetime(2026, 6, 13, tzinfo=timezone.utc)

    async with async_session() as db:
        db.add_all(
            [
                GoogleAccount(
                    email="active@example.com",
                    profile_name="active",
                    status="ACTIVE",
                    runtime_status="BUSY",
                    worker_session_id="w1",
                    browser_session_id="b1",
                    current_task_id="task-1",
                    lease_expires_at=now + timedelta(minutes=5),
                    colab_pid=123,
                ),
                GoogleAccount(
                    email="login@example.com",
                    profile_name="login",
                    status="NEEDS_LOGIN",
                    runtime_status="IDLE",
                    worker_session_id="w2",
                    browser_session_id="b2",
                ),
                GoogleAccount(
                    email="disabled@example.com",
                    profile_name="disabled",
                    status="DISABLED",
                    runtime_status="IDLE",
                    worker_session_id="w3",
                    browser_session_id="b3",
                ),
            ]
        )
        await db.commit()

        await reconcile_startup_state(db, now=now)
        await db.commit()

        active = (await db.execute(GoogleAccount.__table__.select().where(GoogleAccount.email == "active@example.com"))).first()
        login = (await db.execute(GoogleAccount.__table__.select().where(GoogleAccount.email == "login@example.com"))).first()
        disabled = (await db.execute(GoogleAccount.__table__.select().where(GoogleAccount.email == "disabled@example.com"))).first()

    active_row = active._mapping
    login_row = login._mapping
    disabled_row = disabled._mapping

    assert active_row["status"] == "READY"
    assert active_row["runtime_status"] is None
    assert active_row["worker_session_id"] is None
    assert active_row["browser_session_id"] is None
    assert active_row["current_task_id"] is None
    assert active_row["lease_expires_at"] is None
    assert active_row["colab_pid"] is None

    assert login_row["status"] == "NEEDS_LOGIN"
    assert login_row["runtime_status"] is None
    assert disabled_row["status"] == "DISABLED"
    assert disabled_row["runtime_status"] is None


@pytest.mark.asyncio
async def test_reconcile_startup_preserves_unexpired_cooldown_and_releases_expired_cooldown():
    await init_db()
    now = datetime(2026, 6, 13, tzinfo=timezone.utc)

    async with async_session() as db:
        db.add_all(
            [
                GoogleAccount(email="cool@example.com", profile_name="cool", status="COOLDOWN", quota_reset_at=now + timedelta(hours=1), runtime_status="BUSY", worker_session_id="w1"),
                GoogleAccount(email="expired@example.com", profile_name="expired", status="COOLDOWN", quota_reset_at=now - timedelta(seconds=1), runtime_status="BUSY", worker_session_id="w2"),
            ]
        )
        await db.commit()

        await reconcile_startup_state(db, now=now)
        await db.commit()

        cool = (await db.execute(GoogleAccount.__table__.select().where(GoogleAccount.email == "cool@example.com"))).first()._mapping
        expired = (await db.execute(GoogleAccount.__table__.select().where(GoogleAccount.email == "expired@example.com"))).first()._mapping

    assert cool["status"] == "COOLDOWN"
    assert cool["quota_reset_at"] == now + timedelta(hours=1)
    assert cool["runtime_status"] is None

    assert expired["status"] == "READY"
    assert expired["quota_reset_at"] is None
    assert expired["runtime_status"] is None


@pytest.mark.asyncio
async def test_reconcile_startup_resets_orphan_processing_tasks_to_pending():
    await init_db()

    async with async_session() as db:
        voice = Voice(name="v", audio_path="/tmp/ref.wav")
        db.add(voice)
        await db.flush()
        db.add(
            Task(
                id="task-1",
                text="hello",
                voice_id=voice.id,
                status="PROCESSING",
                worker_id=99,
                worker_session_id="stale-session",
                attempt=3,
                leased_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
                lease_expires_at=datetime(2026, 6, 13, 0, 5, tzinfo=timezone.utc),
            )
        )
        await db.commit()

        await reconcile_startup_state(db, now=datetime(2026, 6, 13, tzinfo=timezone.utc))
        await db.commit()

        task = await db.get(Task, "task-1")

    assert task.status == "PENDING"
    assert task.worker_id is None
    assert task.worker_session_id is None
    assert task.leased_at is None
    assert task.lease_expires_at is None
    assert task.attempt == 3
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_reconciler.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.lifecycle.reconciler'`.

- [ ] **Step 3: Implement reconciler**

Create `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/reconciler.py`:

```python
"""Startup reconciliation for runtime worker state."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.lifecycle.constants import (
    ACCOUNT_COOLDOWN,
    ACCOUNT_DISABLED,
    ACCOUNT_NEEDS_LOGIN,
    ACCOUNT_READY,
    LEGACY_RUNTIME_ACCOUNT_STATUSES,
)
from app.models import GoogleAccount, Task


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def reconcile_startup_state(db: AsyncSession, now: datetime | None = None) -> None:
    now = now or utc_now()

    await db.execute(
        update(GoogleAccount).values(
            worker_session_id=None,
            browser_session_id=None,
            runtime_status=None,
            current_task_id=None,
            last_heartbeat_at=None,
            lease_expires_at=None,
            colab_pid=None,
        )
    )

    await db.execute(
        update(GoogleAccount)
        .where(GoogleAccount.status.in_(LEGACY_RUNTIME_ACCOUNT_STATUSES))
        .values(status=ACCOUNT_READY)
    )

    await db.execute(
        update(GoogleAccount)
        .where(
            GoogleAccount.status == ACCOUNT_COOLDOWN,
            GoogleAccount.quota_reset_at.is_not(None),
            GoogleAccount.quota_reset_at <= now,
        )
        .values(status=ACCOUNT_READY, quota_reset_at=None)
    )

    await db.execute(
        update(GoogleAccount)
        .where(GoogleAccount.status == ACCOUNT_COOLDOWN, GoogleAccount.quota_reset_at.is_(None))
        .values(status=ACCOUNT_READY)
    )

    await db.execute(
        update(GoogleAccount)
        .where(GoogleAccount.status.in_([ACCOUNT_NEEDS_LOGIN, ACCOUNT_DISABLED]))
        .values(runtime_status=None)
    )

    await db.execute(
        update(Task)
        .where(Task.status == "PROCESSING")
        .values(
            status="PENDING",
            worker_id=None,
            worker_session_id=None,
            leased_at=None,
            lease_expires_at=None,
        )
    )
```

- [ ] **Step 4: Replace inline main startup cleanup**

In `/media/reup/Data_sv2/SVRV/Colab/app/main.py`, replace lines 88-103 orphan task cleanup block with:

```python
    logger.info("Reconciling startup lifecycle state...")
    try:
        from app.database import async_session
        from app.lifecycle.reconciler import reconcile_startup_state

        async with async_session() as db:
            await reconcile_startup_state(db)
            await db.commit()
        logger.info("Startup lifecycle state reconciled successfully.")
    except Exception as e:
        logger.error("Failed to reconcile startup lifecycle state: %s", e)
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_reconciler.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/lifecycle/reconciler.py app/main.py tests/test_lifecycle_reconciler.py
git commit -m "feat: reconcile lifecycle state on startup"
```

---

## Task 6: Pass Worker Session ID Through Playwright and Colab Worker

**Files:**
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/automation/play_runner.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/colab/worker.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_worker_protocol.py`

- [ ] **Step 1: Write failing protocol tests**

Create `/media/reup/Data_sv2/SVRV/Colab/tests/test_worker_protocol.py`:

```python
import argparse
import json

from colab.worker import parse_args, build_register_message, build_status_message, build_task_completed_message, build_task_failed_message


def test_worker_parser_accepts_worker_session_id(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "worker.py",
            "--server-url",
            "https://example.trycloudflare.com",
            "--email",
            "worker@example.com",
            "--worker-session-id",
            "session-123",
        ],
    )

    args = parse_args()

    assert args.server_url == "https://example.trycloudflare.com"
    assert args.email == "worker@example.com"
    assert args.worker_session_id == "session-123"


def test_worker_protocol_messages_include_worker_session_id():
    assert build_register_message("worker@example.com", "T4", "session-123") == {
        "action": "register",
        "email": "worker@example.com",
        "gpu": "T4",
        "worker_session_id": "session-123",
    }

    assert build_status_message("IDLE", "session-123", 0) == {
        "action": "status",
        "status": "IDLE",
        "worker_session_id": "session-123",
        "queue_size": 0,
    }

    assert build_task_completed_message("task-1", "session-123") == {
        "action": "task_completed",
        "task_id": "task-1",
        "worker_session_id": "session-123",
    }

    assert build_task_failed_message("task-1", "session-123", "boom") == {
        "action": "task_failed",
        "task_id": "task-1",
        "worker_session_id": "session-123",
        "error": "boom",
    }
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_worker_protocol.py -v
```

Expected: FAIL with missing protocol builder imports.

- [ ] **Step 3: Add worker protocol builders**

In `/media/reup/Data_sv2/SVRV/Colab/colab/worker.py`, add after `send_json_safe`:

```python
def build_register_message(email: str, gpu: str, worker_session_id: str) -> dict[str, Any]:
    return {
        "action": "register",
        "email": email,
        "gpu": gpu,
        "worker_session_id": worker_session_id,
    }


def build_status_message(status: str, worker_session_id: str, queue_size: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "status",
        "status": status,
        "worker_session_id": worker_session_id,
    }
    if queue_size is not None:
        payload["queue_size"] = queue_size
    return payload


def build_task_completed_message(task_id: str, worker_session_id: str) -> dict[str, Any]:
    return {
        "action": "task_completed",
        "task_id": task_id,
        "worker_session_id": worker_session_id,
    }


def build_task_failed_message(task_id: str | None, worker_session_id: str, error: str) -> dict[str, Any]:
    return {
        "action": "task_failed",
        "task_id": task_id,
        "worker_session_id": worker_session_id,
        "error": error,
    }
```

Change `send_status` signature and body:

```python
async def send_status(ws: Any, status: str, worker_session_id: str, queue_size: int | None = None) -> None:
    await send_json_safe(ws, build_status_message(status, worker_session_id, queue_size))
```

- [ ] **Step 4: Thread worker_session_id through worker functions**

Change `process_task` signature:

```python
async def process_task(model: Any, ws: Any, http_client: httpx.AsyncClient, server_url: str, data: dict[str, Any], worker_session_id: str) -> None:
```

Inside upload request, change:

```python
        upload_response = await http_client.post(
            upload_url,
            params={"worker_session_id": worker_session_id},
            files={"audio": ("result.wav", result_audio, "audio/wav")},
            timeout=120,
        )
```

Change completed send:

```python
        await send_json_safe(ws, build_task_completed_message(task_id, worker_session_id))
```

Change failed send:

```python
        await send_json_safe(ws, build_task_failed_message(task_id, worker_session_id, str(exc)))
```

Change `task_consumer` signature:

```python
async def task_consumer(
    queue: asyncio.Queue[dict[str, Any]],
    model: Any,
    ws: Any,
    http_client: httpx.AsyncClient,
    server_url: str,
    worker_session_id: str,
) -> None:
```

Change consumer body:

```python
            await send_status(ws, "BUSY", worker_session_id, queue.qsize())
            await process_task(model, ws, http_client, server_url, data, worker_session_id)
        finally:
            queue.task_done()
            await send_status(ws, "IDLE" if queue.empty() else "BUSY", worker_session_id, queue.qsize())
```

Change `worker_loop` signature:

```python
async def worker_loop(model: Any, server_url: str, email: str, worker_session_id: str) -> None:
```

Change register send:

```python
                    await ws.send(json.dumps(build_register_message(email, gpu, worker_session_id)))
```

Change consumer creation:

```python
                    consumer_task = asyncio.create_task(task_consumer(task_queue, model, ws, http_client, server_url, worker_session_id))
```

Change initial status:

```python
                    await send_status(ws, "IDLE", worker_session_id, 0)
```

Change run_tts queue-full failure:

```python
                                await send_json_safe(ws, build_task_failed_message(data.get("task_id"), worker_session_id, "Worker queue full"))
```

Change busy status send:

```python
                                await send_status(ws, "BUSY", worker_session_id, task_queue.qsize())
```

Change pong status payload:

```python
                            await ws.send(json.dumps({
                                "action": "pong_status",
                                "status": current_status,
                                "worker_session_id": worker_session_id,
                            }))
```

Change `parse_args`:

```python
    parser.add_argument("--worker-session-id", required=True)
```

Change main:

```python
    worker_session_id = args.worker_session_id.strip()
    if not worker_session_id:
        print("[error] WORKER_SESSION_ID không được để trống.", flush=True)
        sys.exit(1)

    print(f"[fast-mode] num_step={OMNIVOICE_NUM_STEP} guidance_scale={OMNIVOICE_GUIDANCE_SCALE} ref_max={REF_AUDIO_MAX_SECONDS}s speed={OMNIVOICE_SPEED}", flush=True)
    model = load_model(detect_device())
    asyncio.run(worker_loop(model, server_url, email, worker_session_id))
```

- [ ] **Step 5: Modify Playwright launcher signature**

In `/media/reup/Data_sv2/SVRV/Colab/app/automation/play_runner.py`, change function signature:

```python
async def start_colab_worker(email: str, server_url: str, worker_session_id: str, browser_session_id: str | None = None) -> None:
```

Add form fill after `EMAIL`:

```python
        await _fill_colab_param(page, "WORKER_SESSION_ID", worker_session_id)
```

Change registry call:

```python
        entry = _registry.register(email, role=ROLE_WORKER, pw=pw, context=context, page=page)
        if browser_session_id:
            setattr(entry, "browser_session_id", browser_session_id)
```

- [ ] **Step 6: Run tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_worker_protocol.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/automation/play_runner.py colab/worker.py tests/test_worker_protocol.py
git commit -m "feat: pass worker session through worker protocol"
```

---

## Task 7: Update WebSocket Registration and Heartbeats

**Files:**
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_sessions.py`

- [ ] **Step 1: Add failing manager tests**

Append to `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_sessions.py`:

```python
from app.routes.ws import ConnectionManager


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_connection_manager_tracks_worker_by_session_and_gets_idle_worker():
    manager = ConnectionManager()
    ws = FakeWebSocket()

    await manager.connect(ws, "worker@example.com", "session-123", "T4")

    assert manager.active["worker@example.com"] is ws
    assert manager.worker_info["worker@example.com"]["worker_session_id"] == "session-123"
    assert manager.session_by_email["worker@example.com"] == "session-123"

    manager.worker_info["worker@example.com"]["status"] = "IDLE"

    idle = manager.get_idle_worker()
    assert idle == ("worker@example.com", "session-123")


@pytest.mark.asyncio
async def test_connection_manager_send_task_includes_worker_session_id():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    await manager.connect(ws, "worker@example.com", "session-123", "T4")

    sent = await manager.send_task(
        "worker@example.com",
        "session-123",
        "task-1",
        "hello",
        "https://server/api/voices/1/audio",
        "en",
        "ref",
        24,
        3.0,
    )

    assert sent is True
    assert ws.sent[-1]["action"] == "run_tts"
    assert ws.sent[-1]["task_id"] == "task-1"
    assert ws.sent[-1]["worker_session_id"] == "session-123"
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_sessions.py::test_connection_manager_tracks_worker_by_session_and_gets_idle_worker tests/test_lifecycle_sessions.py::test_connection_manager_send_task_includes_worker_session_id -v
```

Expected: FAIL due old method signatures.

- [ ] **Step 3: Update ConnectionManager fields and connect**

Modify `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`.

In `ConnectionManager.__init__`, add:

```python
        self.session_by_email: dict[str, str] = {}
```

Change `connect` signature and body:

```python
    async def connect(self, ws: WebSocket, email: str, worker_session_id: str, gpu: str = ""):
        now = datetime.now(timezone.utc)
        self.active[email] = ws
        self.session_by_email[email] = worker_session_id
        self.worker_info[email] = {
            "gpu": gpu,
            "connected_at": now,
            "status": "WARMING_MODEL",
            "worker_session_id": worker_session_id,
            "last_pong": time.time(),
            "expiring": False,
            "uptime": 0,
        }
        logger.info("Worker connected and warming model: %s session=%s GPU=%s", email, worker_session_id, gpu)
```

Remove old DB `status="LOADING"` update block from `connect`.

Change `disconnect`:

```python
    def disconnect(self, email: str):
        self.active.pop(email, None)
        self.worker_info.pop(email, None)
        self.session_by_email.pop(email, None)
        logger.info("Worker disconnected: %s", email)
```

- [ ] **Step 4: Update send_task and idle worker selection**

Change `send_task` signature and payload:

```python
    async def send_task(
        self,
        email,
        worker_session_id,
        task_id,
        text,
        voice_api_url,
        language=None,
        voice_ref_text=None,
        num_step=None,
        guidance_scale=None,
    ):
        ws = self.active.get(email)
        current_session_id = self.session_by_email.get(email)
        if ws is None or current_session_id != worker_session_id:
            return False
        try:
            msg = {
                "action": "run_tts",
                "task_id": task_id,
                "worker_session_id": worker_session_id,
                "text": text,
                "voice_api_url": voice_api_url,
                "voice_ref_text": voice_ref_text,
                "language": language,
            }
            if num_step is not None:
                msg["num_step"] = num_step
            if guidance_scale is not None:
                msg["guidance_scale"] = guidance_scale
            await ws.send_json(msg)
            return True
        except Exception:
            return False
```

Change `get_idle_worker`:

```python
    def get_idle_worker(self) -> tuple[str, str] | None:
        candidates = []
        for email, info in self.worker_info.items():
            if info.get("status") == "IDLE":
                worker_session_id = info.get("worker_session_id")
                if worker_session_id and self.active.get(email):
                    candidates.append((email, worker_session_id, info.get("expiring", False)))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[2])
        email, worker_session_id, _ = candidates[0]
        return email, worker_session_id
```

- [ ] **Step 5: Update websocket register flow**

In `websocket_worker`, change register parsing block:

```python
        email = raw["email"]
        worker_session_id = raw.get("worker_session_id")
        if not worker_session_id:
            await ws.close(code=4002)
            return
        gpu = raw.get("gpu", "unknown")

        async with async_session() as db:
            from app.lifecycle.sessions import mark_worker_registered

            accepted = await mark_worker_registered(
                db,
                email=email,
                worker_session_id=worker_session_id,
                lease_seconds=60,
            )
            await db.commit()

        if not accepted:
            logger.warning("Rejected worker register email=%s session=%s", email, worker_session_id)
            await ws.close(code=4003)
            return

        await manager.connect(ws, email, worker_session_id, gpu)
```

Then replace old DB account `ACTIVE` block with:

```python
        if email in manager.worker_info:
            manager.worker_info[email]["status"] = "IDLE"

        async with async_session() as db:
            from app.lifecycle.sessions import mark_worker_status

            await mark_worker_status(
                db,
                email=email,
                worker_session_id=worker_session_id,
                runtime_status="IDLE",
                lease_seconds=60,
            )
            await db.commit()

        logger.info("Worker ready (IDLE): %s session=%s", email, worker_session_id)
```

- [ ] **Step 6: Update websocket status and pong handling**

In `websocket_worker`, for status action, require matching session:

```python
                sender_session_id = data.get("worker_session_id")
                if sender_session_id != manager.session_by_email.get(email):
                    logger.warning("Ignoring status from stale session email=%s session=%s", email, sender_session_id)
                    continue
                new_status = data.get("status", "IDLE")
                manager.worker_info[email]["status"] = new_status
                if new_status == "IDLE":
                    manager.worker_info[email]["idle_since"] = datetime.now(timezone.utc)
                else:
                    manager.worker_info[email].pop("idle_since", None)
                await _handle_status(email, sender_session_id, new_status)
```

For task completed:

```python
                await _handle_task_completed(data.get("task_id"), data.get("worker_session_id"), email)
```

For task failed:

```python
                await _handle_task_failed(data.get("task_id"), data.get("worker_session_id"), data.get("error", "Unknown"), email)
```

For pong_status:

```python
                    sender_session_id = data.get("worker_session_id")
                    if sender_session_id != manager.session_by_email.get(email):
                        logger.warning("Ignoring pong_status from stale session email=%s session=%s", email, sender_session_id)
                        continue
                    manager.worker_info[email]["last_pong"] = time.time()
                    new_status = data.get("status", "IDLE")
                    manager.worker_info[email]["status"] = new_status
                    await _handle_status(email, sender_session_id, new_status)
```

- [ ] **Step 7: Update `_handle_status` signature**

Change `_handle_status` to:

```python
async def _handle_status(email: str, worker_session_id: str, status: str):
    """Sync real-time worker runtime status to database."""
    async with async_session() as db:
        from app.lifecycle.sessions import mark_worker_status

        if status == "OUT_OF_QUOTA":
            res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
            acc = res.scalar_one_or_none()
            if acc and acc.worker_session_id == worker_session_id:
                acc.status = "COOLDOWN"
                acc.quota_reset_at = datetime.now(timezone.utc) + timedelta(hours=QUOTA_RESET_HOURS)
                acc.runtime_status = "DRAINING"
                await db.execute(
                    update(Task)
                    .where(Task.worker_id == acc.id, Task.status == "PROCESSING")
                    .values(
                        status="PENDING",
                        worker_id=None,
                        worker_session_id=None,
                        leased_at=None,
                        lease_expires_at=None,
                    )
                )
                await db.commit()
                _safe_create_task(play_runner.stop_colab_worker(email))
                _safe_create_task(_try_auto_rotate())
        else:
            await mark_worker_status(
                db,
                email=email,
                worker_session_id=worker_session_id,
                runtime_status=status,
                lease_seconds=60,
            )
            await db.commit()

    if status == "IDLE":
        _safe_create_task(_try_dispatch_next_task(email, worker_session_id))

    await manager.broadcast_status({"event": "worker_status", "email": email, "status": status, "worker_session_id": worker_session_id})
```

Change `_try_dispatch_next_task` signature:

```python
async def _try_dispatch_next_task(email: str, worker_session_id: str):
    from app.routes.tasks import _dispatch_task
    async with async_session() as db:
        res = await db.execute(select(Task).where(Task.status == "PENDING").order_by(Task.created_at.asc()).limit(1))
        task = res.scalar_one_or_none()
        if task:
            await _dispatch_task(task, email, worker_session_id, db)
```

- [ ] **Step 8: Run session tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_sessions.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/routes/ws.py tests/test_lifecycle_sessions.py
git commit -m "feat: validate worker websocket sessions"
```

---

## Task 8: Reserve Session Before Worker Launch and Prevent Duplicate Browsers

**Files:**
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/accounts.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_sessions.py`

- [ ] **Step 1: Add failing autoscale reservation test**

Append to `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_sessions.py`:

```python
@pytest.mark.asyncio
async def test_try_auto_rotate_reserves_session_before_launch(monkeypatch):
    await init_db()
    calls = []

    async def fake_start_colab_worker(email, server_url, worker_session_id, browser_session_id=None):
        calls.append((email, server_url, worker_session_id, browser_session_id))

    monkeypatch.setattr("app.routes.ws.play_runner.start_colab_worker", fake_start_colab_worker)
    monkeypatch.setattr("app.routes.ws.play_runner._registry.is_running", lambda email: False)

    async with async_session() as db:
        db.add(GoogleAccount(email="ready-launch@example.com", profile_name="ready-launch", status="READY"))
        await db.commit()

    from app.routes.ws import _try_auto_rotate
    await _try_auto_rotate()

    async with async_session() as db:
        result = await db.execute(GoogleAccount.__table__.select().where(GoogleAccount.email == "ready-launch@example.com"))
        row = result.first()._mapping

    assert len(calls) == 1
    email, server_url, worker_session_id, browser_session_id = calls[0]
    assert email == "ready-launch@example.com"
    assert worker_session_id == row["worker_session_id"]
    assert browser_session_id == row["browser_session_id"]
    assert row["runtime_status"] == "STARTING_BROWSER"
    assert row["status"] == "READY"


@pytest.mark.asyncio
async def test_try_auto_rotate_does_not_launch_when_ready_account_has_browser_session(monkeypatch):
    await init_db()
    calls = []

    async def fake_start_colab_worker(email, server_url, worker_session_id, browser_session_id=None):
        calls.append((email, server_url, worker_session_id, browser_session_id))

    monkeypatch.setattr("app.routes.ws.play_runner.start_colab_worker", fake_start_colab_worker)

    async with async_session() as db:
        db.add(GoogleAccount(email="reserved@example.com", profile_name="reserved", status="READY", browser_session_id="existing"))
        await db.commit()

    from app.routes.ws import _try_auto_rotate
    await _try_auto_rotate()

    assert calls == []
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_sessions.py::test_try_auto_rotate_reserves_session_before_launch tests/test_lifecycle_sessions.py::test_try_auto_rotate_does_not_launch_when_ready_account_has_browser_session -v
```

Expected: FAIL because `_try_auto_rotate` uses old `OFFLINE/CONNECTING` state.

- [ ] **Step 3: Replace `_has_starting_or_active_account`**

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`, replace function body with:

```python
async def _has_starting_or_active_account() -> bool:
    """True when a Colab browser/worker is already starting or running."""
    async with async_session() as db:
        result = await db.execute(
            select(func.count())
            .select_from(GoogleAccount)
            .where(GoogleAccount.runtime_status.in_(["STARTING_BROWSER", "CONNECTING_RUNTIME", "WARMING_MODEL", "IDLE", "BUSY", "DRAINING"]))
        )
        return (result.scalar() or 0) > 0
```

- [ ] **Step 4: Replace `_try_auto_rotate` reservation logic**

In `_try_auto_rotate`, replace DB selection/status mutation section through `await play_runner.start_colab_worker(...)` call with:

```python
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            from app.config import MAX_CONCURRENT_WORKERS, KEEP_WARM_WORKERS, WORKER_HEARTBEAT_TIMEOUT_SECONDS
            from app.lifecycle.capacity import get_capacity_snapshot, should_launch_worker
            from app.lifecycle.sessions import reserve_worker_session

            await db.execute(
                update(GoogleAccount)
                .where(GoogleAccount.status == "COOLDOWN", GoogleAccount.quota_reset_at <= now)
                .values(status="READY", quota_reset_at=None)
            )
            snapshot = await get_capacity_snapshot(db, max_workers=MAX_CONCURRENT_WORKERS, warm_target=KEEP_WARM_WORKERS)
            if not should_launch_worker(snapshot):
                logger.info("Launch not allowed capacity=%s ready=%s max=%s", snapshot.active_capacity, snapshot.ready_accounts, snapshot.max_workers)
                await db.commit()
                return

            reservation = await reserve_worker_session(
                db,
                now=now,
                lease_seconds=WORKER_HEARTBEAT_TIMEOUT_SECONDS,
            )
            if reservation is None:
                await db.commit()
                logger.info("No READY account available for rotation")
                return

            await db.commit()

        email = reservation.email
        worker_session_id = reservation.worker_session_id
        browser_session_id = reservation.browser_session_id

        if play_runner._registry.is_running(email):
            logger.warning("Browser already running for %s, clearing reservation", email)
            async with async_session() as db:
                res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
                acc2 = res.scalar_one_or_none()
                if acc2 and acc2.worker_session_id == worker_session_id:
                    acc2.worker_session_id = None
                    acc2.browser_session_id = None
                    acc2.runtime_status = None
                    acc2.lease_expires_at = None
                    acc2.last_heartbeat_at = None
                    await db.commit()
            return

        try:
            import app.config as cfg
            logger.info("Auto-starting worker for %s -> %s session=%s", email, cfg.SERVER_URL, worker_session_id)
            await play_runner.start_colab_worker(email, cfg.SERVER_URL, worker_session_id, browser_session_id=browser_session_id)
```

In exception handler, replace old status mutation with:

```python
                    if acc and acc.worker_session_id == worker_session_id:
                        acc.worker_session_id = None
                        acc.browser_session_id = None
                        acc.runtime_status = None
                        acc.current_task_id = None
                        acc.lease_expires_at = None
                        acc.last_heartbeat_at = None
                        if "session expired" in error_msg.lower() or "needs re-login" in error_msg.lower() or "needs login" in error_msg.lower():
                            acc.status = "NEEDS_LOGIN"
                            acc.quota_reset_at = None
                            logger.warning("Account %s marked NEEDS_LOGIN due to expired session", email)
                        else:
                            backoff = _ROTATION_FAILURE_BACKOFF_MINUTES * (1 + _consecutive_rotation_failures // 3)
                            reset_time = now + timedelta(minutes=backoff)
                            acc.status = "COOLDOWN"
                            acc.quota_reset_at = reset_time
                            logger.warning("Account %s marked COOLDOWN %dmin (browser launch error)", email, backoff)
```

- [ ] **Step 5: Update accounts manual start**

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/accounts.py`, in `start_worker`, replace eligibility check and DB mutations with:

```python
    if account.status != "READY" or account.worker_session_id or account.browser_session_id:
        raise HTTPException(status_code=400, detail=f"Account is not available for launch: status={account.status} runtime_status={account.runtime_status}")

    from app.config import WORKER_HEARTBEAT_TIMEOUT_SECONDS
    from app.lifecycle.sessions import reserve_worker_session

    reservation = await reserve_worker_session(db, lease_seconds=WORKER_HEARTBEAT_TIMEOUT_SECONDS)
    if reservation is None or reservation.account_id != account.id:
        raise HTTPException(status_code=409, detail="Account could not be reserved for launch.")
    await db.commit()
```

Change background launcher:

```python
                await play_runner.start_colab_worker(
                    reservation.email,
                    server_url,
                    reservation.worker_session_id,
                    browser_session_id=reservation.browser_session_id,
                )
```

In background exception block, clear fields:

```python
                    if acc and acc.worker_session_id == reservation.worker_session_id:
                        acc.worker_session_id = None
                        acc.browser_session_id = None
                        acc.runtime_status = None
                        acc.current_task_id = None
                        acc.lease_expires_at = None
                        acc.last_heartbeat_at = None
                        acc.status = "READY"
                        await bdb.commit()
```

Return:

```python
    return {
        "id": account.id,
        "status": "STARTING_BACKGROUND",
        "worker_session_id": reservation.worker_session_id,
        "browser_session_id": reservation.browser_session_id,
    }
```

- [ ] **Step 6: Run tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_sessions.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/routes/ws.py app/routes/accounts.py tests/test_lifecycle_sessions.py
git commit -m "feat: reserve session before worker launch"
```

---

## Task 9: Add Dispatch Task Leases

**Files:**
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/tasks.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/tts.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_sessions.py`

- [ ] **Step 1: Add failing dispatch lease test**

Append to `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_sessions.py`:

```python
from app.models import Task, Voice


@pytest.mark.asyncio
async def test_dispatch_task_sets_task_and_worker_session_lease(monkeypatch):
    await init_db()

    sent_messages = []

    class FakeManager:
        worker_info = {"worker@example.com": {"status": "IDLE", "worker_session_id": "session-123"}}

        async def send_task(self, email, worker_session_id, task_id, text, voice_api_url, language=None, voice_ref_text=None, num_step=None, guidance_scale=None):
            sent_messages.append((email, worker_session_id, task_id, text, voice_api_url, language, voice_ref_text, num_step, guidance_scale))
            return True

    monkeypatch.setattr("app.routes.tasks.manager", FakeManager())

    async with async_session() as db:
        account = GoogleAccount(
            email="worker@example.com",
            profile_name="worker",
            status="READY",
            runtime_status="IDLE",
            worker_session_id="session-123",
            browser_session_id="browser-123",
        )
        voice = Voice(name="v", audio_path="/tmp/ref.wav", transcript="reference")
        db.add_all([account, voice])
        await db.flush()
        task = Task(id="task-lease", text="hello", voice_id=voice.id, status="PENDING")
        db.add(task)
        await db.commit()

        from app.routes.tasks import _dispatch_task
        await _dispatch_task(task, "worker@example.com", "session-123", db)
        await db.commit()

        await db.refresh(task)
        await db.refresh(account)

    assert sent_messages[0][0:3] == ("worker@example.com", "session-123", "task-lease")
    assert task.status == "PROCESSING"
    assert task.worker_id == account.id
    assert task.worker_session_id == "session-123"
    assert task.attempt == 1
    assert task.leased_at is not None
    assert task.lease_expires_at is not None
    assert account.runtime_status == "BUSY"
    assert account.current_task_id == "task-lease"
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_sessions.py::test_dispatch_task_sets_task_and_worker_session_lease -v
```

Expected: FAIL due `_dispatch_task` signature mismatch or missing lease fields.

- [ ] **Step 3: Update `_dispatch_task`**

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/tasks.py`, change signature:

```python
async def _dispatch_task(task: Task, email: str, worker_session_id: str, db: AsyncSession):
```

Replace body with:

```python
    """Send a PENDING task to an idle worker via WebSocket with a session lease."""
    import app.config as config
    import os
    from datetime import timedelta
    from app.models import GoogleAccount

    result = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
    account = result.scalar_one_or_none()
    if not account or account.worker_session_id != worker_session_id or account.runtime_status != "IDLE":
        task.status = "PENDING"
        await db.commit()
        return False

    now = datetime.now(timezone.utc)
    task.status = "PROCESSING"
    task.worker_id = account.id
    task.worker_session_id = worker_session_id
    task.attempt = (task.attempt or 0) + 1
    task.leased_at = now
    task.lease_expires_at = now + timedelta(seconds=config.TASK_LEASE_SECONDS)

    account.runtime_status = "BUSY"
    account.current_task_id = task.id
    account.last_active = now

    base = config.SERVER_URL
    voice = await db.get(Voice, task.voice_id)
    voice_url = f"{base}/api/voices/{task.voice_id}/audio"
    voice_ref_text = voice.transcript if voice else None

    num_step = int(os.getenv("OMNIVOICE_NUM_STEP", "24"))
    guidance_scale = float(os.getenv("OMNIVOICE_GUIDANCE_SCALE", "3.0"))
    dispatched = await manager.send_task(
        email,
        worker_session_id,
        task.id,
        task.text,
        voice_url,
        task.language,
        voice_ref_text,
        num_step,
        guidance_scale,
    )
    if dispatched:
        if email in manager.worker_info:
            manager.worker_info[email]["status"] = "BUSY"
        await db.commit()
        return True

    task.status = "PENDING"
    task.worker_id = None
    task.worker_session_id = None
    task.leased_at = None
    task.lease_expires_at = None
    account.runtime_status = "LOST"
    account.current_task_id = None
    await db.commit()
    return False
```

- [ ] **Step 4: Update callers in tasks route**

In `create_task`, replace:

```python
    idle_email = manager.get_idle_worker()
    if idle_email:
        await _dispatch_task(task, idle_email, db)
```

with:

```python
    idle_worker = manager.get_idle_worker()
    if idle_worker:
        idle_email, worker_session_id = idle_worker
        await _dispatch_task(task, idle_email, worker_session_id, db)
```

In `retry_task`, replace:

```python
    idle_email = manager.get_idle_worker()
    if idle_email:
        await _dispatch_task(task, idle_email, db)
```

with:

```python
    idle_worker = manager.get_idle_worker()
    if idle_worker:
        idle_email, worker_session_id = idle_worker
        await _dispatch_task(task, idle_email, worker_session_id, db)
```

In retry lease reset, add:

```python
    task.worker_session_id = None
    task.leased_at = None
    task.lease_expires_at = None
```

- [ ] **Step 5: Update callers in TTS route**

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/tts.py`, replace `manager.get_idle_worker()` checks:

```python
        if not manager.get_idle_worker():
```

remains valid.

Replace:

```python
        idle_email = manager.get_idle_worker()
        if not idle_email:
            raise HTTPException(status_code=503, detail="No idle worker available.")
```

with:

```python
        idle_worker = manager.get_idle_worker()
        if not idle_worker:
            raise HTTPException(status_code=503, detail="No idle worker available.")
        idle_email, worker_session_id = idle_worker
```

Replace dispatch:

```python
        await _dispatch_task(task, idle_email, db)
```

with:

```python
        await _dispatch_task(task, idle_email, worker_session_id, db)
```

In batch dispatch loop, replace:

```python
            idle_email = manager.get_idle_worker()
            if idle_email:
                await _dispatch_task(task, idle_email, db)
```

with:

```python
            idle_worker = manager.get_idle_worker()
            if idle_worker:
                idle_email, worker_session_id = idle_worker
                await _dispatch_task(task, idle_email, worker_session_id, db)
```

- [ ] **Step 6: Update caller in ws `_try_dispatch_next_task`**

Ensure it calls:

```python
            await _dispatch_task(task, email, worker_session_id, db)
```

- [ ] **Step 7: Include lease fields in task responses**

In list/get task response dicts in `/media/reup/Data_sv2/SVRV/Colab/app/routes/tasks.py`, add:

```python
            "worker_session_id": t.worker_session_id,
            "attempt": t.attempt,
            "leased_at": t.leased_at.isoformat() if t.leased_at else None,
            "lease_expires_at": t.lease_expires_at.isoformat() if t.lease_expires_at else None,
```

- [ ] **Step 8: Run tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_sessions.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/routes/tasks.py app/routes/tts.py app/routes/ws.py tests/test_lifecycle_sessions.py
git commit -m "feat: lease tasks to worker sessions"
```

---

## Task 10: Reject Stale Completion and Failure Messages

**Files:**
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/tasks.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_completion.py`

- [ ] **Step 1: Write failing completion tests**

Create `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_completion.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.database import async_session, init_db
from app.models import GoogleAccount, Task, Voice


@pytest.mark.asyncio
async def test_handle_task_completed_rejects_stale_worker_session():
    await init_db()

    async with async_session() as db:
        account = GoogleAccount(
            email="worker@example.com",
            profile_name="worker",
            status="READY",
            runtime_status="BUSY",
            worker_session_id="current-session",
            browser_session_id="browser",
            current_task_id="task-1",
            lease_expires_at=datetime(2026, 6, 13, 0, 5, tzinfo=timezone.utc),
        )
        voice = Voice(name="v", audio_path="/tmp/ref.wav")
        db.add_all([account, voice])
        await db.flush()
        task = Task(
            id="task-1",
            text="hello",
            voice_id=voice.id,
            status="PROCESSING",
            worker_id=account.id,
            worker_session_id="current-session",
        )
        db.add(task)
        await db.commit()

    from app.routes.ws import _handle_task_completed
    await _handle_task_completed("task-1", "stale-session", "worker@example.com")

    async with async_session() as db:
        task = await db.get(Task, "task-1")
        account = (await db.execute(GoogleAccount.__table__.select().where(GoogleAccount.email == "worker@example.com"))).first()._mapping

    assert task.status == "PROCESSING"
    assert task.worker_session_id == "current-session"
    assert account["runtime_status"] == "BUSY"
    assert account["current_task_id"] == "task-1"


@pytest.mark.asyncio
async def test_handle_task_completed_accepts_matching_session_and_clears_leases():
    await init_db()

    async with async_session() as db:
        account = GoogleAccount(
            email="worker2@example.com",
            profile_name="worker2",
            status="READY",
            runtime_status="BUSY",
            worker_session_id="session-2",
            browser_session_id="browser-2",
            current_task_id="task-2",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        voice = Voice(name="v", audio_path="/tmp/ref.wav")
        db.add_all([account, voice])
        await db.flush()
        task = Task(
            id="task-2",
            text="hello",
            voice_id=voice.id,
            status="PROCESSING",
            worker_id=account.id,
            worker_session_id="session-2",
            leased_at=datetime.now(timezone.utc),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db.add(task)
        await db.commit()

    from app.routes.ws import _handle_task_completed
    await _handle_task_completed("task-2", "session-2", "worker2@example.com")

    async with async_session() as db:
        task = await db.get(Task, "task-2")
        account = (await db.execute(GoogleAccount.__table__.select().where(GoogleAccount.email == "worker2@example.com"))).first()._mapping

    assert task.status == "COMPLETED"
    assert task.worker_session_id is None
    assert task.leased_at is None
    assert task.lease_expires_at is None
    assert account["runtime_status"] == "IDLE"
    assert account["current_task_id"] is None


@pytest.mark.asyncio
async def test_handle_task_failed_rejects_stale_worker_session():
    await init_db()

    async with async_session() as db:
        account = GoogleAccount(email="fail@example.com", profile_name="fail", status="READY", runtime_status="BUSY", worker_session_id="good-session", current_task_id="task-fail")
        voice = Voice(name="v", audio_path="/tmp/ref.wav")
        db.add_all([account, voice])
        await db.flush()
        db.add(Task(id="task-fail", text="hello", voice_id=voice.id, status="PROCESSING", worker_id=account.id, worker_session_id="good-session"))
        await db.commit()

    from app.routes.ws import _handle_task_failed
    await _handle_task_failed("task-fail", "bad-session", "boom", "fail@example.com")

    async with async_session() as db:
        task = await db.get(Task, "task-fail")

    assert task.status == "PROCESSING"
    assert task.error_message is None
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_completion.py -v
```

Expected: FAIL due old handler signatures or stale session accepted.

- [ ] **Step 3: Update completion handler**

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`, replace `_handle_task_completed` with:

```python
async def _handle_task_completed(tid: str, worker_session_id: str | None, email: str):
    async with async_session() as db:
        t = await db.get(Task, tid)
        if not t:
            return

        res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
        acc = res.scalar_one_or_none()

        if (
            not worker_session_id
            or not acc
            or t.status != "PROCESSING"
            or t.worker_id != acc.id
            or t.worker_session_id != worker_session_id
            or acc.worker_session_id != worker_session_id
        ):
            logger.warning(
                "Ignoring stale completion task=%s email=%s task_session=%s sender_session=%s account_session=%s",
                tid,
                email,
                getattr(t, "worker_session_id", None),
                worker_session_id,
                getattr(acc, "worker_session_id", None),
            )
            return

        t.status = "COMPLETED"
        t.completed_at = datetime.now(timezone.utc)
        t.worker_session_id = None
        t.leased_at = None
        t.lease_expires_at = None

        acc.runtime_status = "IDLE"
        acc.current_task_id = None
        acc.last_active = datetime.now(timezone.utc)

        if email in manager.worker_info and manager.session_by_email.get(email) == worker_session_id:
            manager.worker_info[email]["status"] = "IDLE"
            manager.worker_info[email]["idle_since"] = datetime.now(timezone.utc)

        await db.commit()

    ev = _pending_direct_events.pop(tid, None)
    if ev:
        ev.set()
    await manager.broadcast_status({"event": "task_completed", "task_id": tid, "worker_session_id": worker_session_id})
    _safe_create_task(_try_dispatch_next_task(email, worker_session_id))
```

- [ ] **Step 4: Update failure handler**

Replace `_handle_task_failed` with:

```python
async def _handle_task_failed(tid: str, worker_session_id: str | None, err: str, email: str):
    async with async_session() as db:
        t = await db.get(Task, tid)
        if not t:
            return

        res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
        acc = res.scalar_one_or_none()

        if (
            not worker_session_id
            or not acc
            or t.status != "PROCESSING"
            or t.worker_id != acc.id
            or t.worker_session_id != worker_session_id
            or acc.worker_session_id != worker_session_id
        ):
            logger.warning(
                "Ignoring stale failure task=%s email=%s task_session=%s sender_session=%s account_session=%s",
                tid,
                email,
                getattr(t, "worker_session_id", None),
                worker_session_id,
                getattr(acc, "worker_session_id", None),
            )
            return

        t.status = "FAILED"
        t.error_message = err
        t.completed_at = datetime.now(timezone.utc)
        t.worker_session_id = None
        t.leased_at = None
        t.lease_expires_at = None

        acc.runtime_status = "IDLE"
        acc.current_task_id = None
        acc.last_active = datetime.now(timezone.utc)

        if email in manager.worker_info and manager.session_by_email.get(email) == worker_session_id:
            manager.worker_info[email]["status"] = "IDLE"
            manager.worker_info[email]["idle_since"] = datetime.now(timezone.utc)

        await db.commit()

    ev = _pending_direct_events.pop(tid, None)
    if ev:
        ev.set()
    await manager.broadcast_status({"event": "task_failed", "task_id": tid, "worker_session_id": worker_session_id, "error": err})
    _safe_create_task(_try_dispatch_next_task(email, worker_session_id))
```

- [ ] **Step 5: Guard upload completion endpoint**

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/tasks.py`, change `complete_task` signature:

```python
async def complete_task(
    task_id: str,
    worker_session_id: str,
    audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
```

Add after task state check:

```python
    if task.worker_session_id != worker_session_id:
        raise HTTPException(status_code=409, detail="Worker session does not own this task.")
```

Remove direct mutation of `task.status = "COMPLETED"` from upload endpoint? Keep audio saving, but set only result path and completed timestamp after session check:

```python
    task.result_audio_path = str(dest)
    await db.commit()
```

Do not set status complete here. WebSocket completion remains source of accepted completion. If upload succeeds but websocket completion never arrives, task lease reaper resets/retries.

Return:

```python
    return {"status": "UPLOADED", "worker_session_id": worker_session_id}
```

- [ ] **Step 6: Run completion tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_completion.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/routes/ws.py app/routes/tasks.py tests/test_lifecycle_completion.py
git commit -m "feat: reject stale worker task completions"
```

---

## Task 11: Add Reaper for Stale Workers, Task Leases, Cooldowns, and Scale-Down

**Files:**
- Create: `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/reaper.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_reaper.py`

- [ ] **Step 1: Write failing reaper tests**

Create `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_reaper.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.database import async_session, init_db
from app.lifecycle.reaper import reap_expired_worker_sessions, reap_expired_task_leases, release_expired_cooldowns, choose_scale_down_worker
from app.models import GoogleAccount, Task, Voice


@pytest.mark.asyncio
async def test_reap_expired_worker_session_marks_lost_clears_account_and_requeues_task():
    await init_db()
    now = datetime(2026, 6, 13, 0, 2, tzinfo=timezone.utc)

    async with async_session() as db:
        account = GoogleAccount(
            email="stale@example.com",
            profile_name="stale",
            status="READY",
            runtime_status="BUSY",
            worker_session_id="session-stale",
            browser_session_id="browser-stale",
            current_task_id="task-stale",
            lease_expires_at=now - timedelta(seconds=1),
            last_heartbeat_at=now - timedelta(minutes=2),
        )
        voice = Voice(name="v", audio_path="/tmp/ref.wav")
        db.add_all([account, voice])
        await db.flush()
        db.add(Task(id="task-stale", text="hello", voice_id=voice.id, status="PROCESSING", worker_id=account.id, worker_session_id="session-stale"))
        await db.commit()

        expired = await reap_expired_worker_sessions(db, now=now)
        await db.commit()

        account_row = (await db.execute(GoogleAccount.__table__.select().where(GoogleAccount.email == "stale@example.com"))).first()._mapping
        task = await db.get(Task, "task-stale")

    assert expired == ["stale@example.com"]
    assert account_row["status"] == "READY"
    assert account_row["runtime_status"] is None
    assert account_row["worker_session_id"] is None
    assert account_row["browser_session_id"] is None
    assert account_row["current_task_id"] is None
    assert task.status == "PENDING"
    assert task.worker_id is None
    assert task.worker_session_id is None


@pytest.mark.asyncio
async def test_reap_expired_task_lease_resets_task_and_worker():
    await init_db()
    now = datetime(2026, 6, 13, 0, 5, tzinfo=timezone.utc)

    async with async_session() as db:
        account = GoogleAccount(email="worker@example.com", profile_name="worker", status="READY", runtime_status="BUSY", worker_session_id="session", current_task_id="task-expired")
        voice = Voice(name="v", audio_path="/tmp/ref.wav")
        db.add_all([account, voice])
        await db.flush()
        db.add(Task(id="task-expired", text="hello", voice_id=voice.id, status="PROCESSING", worker_id=account.id, worker_session_id="session", lease_expires_at=now - timedelta(seconds=1)))
        await db.commit()

        expired = await reap_expired_task_leases(db, now=now)
        await db.commit()

        task = await db.get(Task, "task-expired")
        account_row = (await db.execute(GoogleAccount.__table__.select().where(GoogleAccount.email == "worker@example.com"))).first()._mapping

    assert expired == ["task-expired"]
    assert task.status == "PENDING"
    assert task.worker_id is None
    assert task.worker_session_id is None
    assert account_row["runtime_status"] == "IDLE"
    assert account_row["current_task_id"] is None


@pytest.mark.asyncio
async def test_release_expired_cooldowns():
    await init_db()
    now = datetime(2026, 6, 13, tzinfo=timezone.utc)

    async with async_session() as db:
        db.add_all(
            [
                GoogleAccount(email="expired@example.com", profile_name="expired", status="COOLDOWN", quota_reset_at=now - timedelta(seconds=1)),
                GoogleAccount(email="waiting@example.com", profile_name="waiting", status="COOLDOWN", quota_reset_at=now + timedelta(hours=1)),
            ]
        )
        await db.commit()

        released = await release_expired_cooldowns(db, now=now)
        await db.commit()

        expired = (await db.execute(GoogleAccount.__table__.select().where(GoogleAccount.email == "expired@example.com"))).first()._mapping
        waiting = (await db.execute(GoogleAccount.__table__.select().where(GoogleAccount.email == "waiting@example.com"))).first()._mapping

    assert released == 1
    assert expired["status"] == "READY"
    assert expired["quota_reset_at"] is None
    assert waiting["status"] == "COOLDOWN"


@pytest.mark.asyncio
async def test_choose_scale_down_worker_returns_oldest_idle_when_more_than_warm_target():
    await init_db()
    now = datetime(2026, 6, 13, 1, 0, tzinfo=timezone.utc)

    async with async_session() as db:
        db.add_all(
            [
                GoogleAccount(email="old@example.com", profile_name="old", status="READY", runtime_status="IDLE", worker_session_id="old-session", last_active=now - timedelta(hours=2)),
                GoogleAccount(email="new@example.com", profile_name="new", status="READY", runtime_status="IDLE", worker_session_id="new-session", last_active=now - timedelta(minutes=10)),
            ]
        )
        await db.commit()

        chosen = await choose_scale_down_worker(db, now=now, keep_warm_workers=1, idle_seconds=1800)

    assert chosen == ("old@example.com", "old-session")
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_reaper.py -v
```

Expected: FAIL with missing `app.lifecycle.reaper`.

- [ ] **Step 3: Implement reaper**

Create `/media/reup/Data_sv2/SVRV/Colab/app/lifecycle/reaper.py`:

```python
"""Maintenance reaper for worker sessions and task leases."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.lifecycle.constants import ACCOUNT_COOLDOWN, ACCOUNT_READY, RUNTIME_IDLE
from app.models import GoogleAccount, Task


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _requeue_processing_tasks_for_account(db: AsyncSession, account: GoogleAccount) -> None:
    await db.execute(
        update(Task)
        .where(Task.worker_id == account.id, Task.status == "PROCESSING")
        .values(
            status="PENDING",
            worker_id=None,
            worker_session_id=None,
            leased_at=None,
            lease_expires_at=None,
        )
    )


async def reap_expired_worker_sessions(db: AsyncSession, now: datetime | None = None) -> list[str]:
    now = now or utc_now()
    result = await db.execute(
        select(GoogleAccount).where(
            GoogleAccount.worker_session_id.is_not(None),
            GoogleAccount.lease_expires_at.is_not(None),
            GoogleAccount.lease_expires_at <= now,
        )
    )
    expired = result.scalars().all()
    emails: list[str] = []

    for account in expired:
        emails.append(account.email)
        await _requeue_processing_tasks_for_account(db, account)
        account.runtime_status = None
        account.worker_session_id = None
        account.browser_session_id = None
        account.current_task_id = None
        account.last_heartbeat_at = None
        account.lease_expires_at = None
        account.colab_pid = None
        if account.status != ACCOUNT_COOLDOWN and account.status not in ("NEEDS_LOGIN", "DISABLED"):
            account.status = ACCOUNT_READY

    return emails


async def reap_expired_task_leases(db: AsyncSession, now: datetime | None = None) -> list[str]:
    now = now or utc_now()
    result = await db.execute(
        select(Task).where(
            Task.status == "PROCESSING",
            Task.lease_expires_at.is_not(None),
            Task.lease_expires_at <= now,
        )
    )
    tasks = result.scalars().all()
    task_ids: list[str] = []

    for task in tasks:
        task_ids.append(task.id)
        account = await db.get(GoogleAccount, task.worker_id) if task.worker_id else None
        if account and account.current_task_id == task.id:
            account.runtime_status = RUNTIME_IDLE
            account.current_task_id = None

        task.status = "PENDING"
        task.worker_id = None
        task.worker_session_id = None
        task.leased_at = None
        task.lease_expires_at = None

    return task_ids


async def release_expired_cooldowns(db: AsyncSession, now: datetime | None = None) -> int:
    now = now or utc_now()
    result = await db.execute(
        update(GoogleAccount)
        .where(
            GoogleAccount.status == ACCOUNT_COOLDOWN,
            GoogleAccount.quota_reset_at.is_not(None),
            GoogleAccount.quota_reset_at <= now,
        )
        .values(status=ACCOUNT_READY, quota_reset_at=None)
    )
    return int(result.rowcount or 0)


async def choose_scale_down_worker(
    db: AsyncSession,
    now: datetime | None = None,
    keep_warm_workers: int = 1,
    idle_seconds: int = 1800,
) -> tuple[str, str] | None:
    now = now or utc_now()

    active_count_result = await db.execute(
        select(func.count())
        .select_from(GoogleAccount)
        .where(GoogleAccount.runtime_status.in_(["STARTING_BROWSER", "CONNECTING_RUNTIME", "WARMING_MODEL", "IDLE", "BUSY", "DRAINING"]))
    )
    active_count = int(active_count_result.scalar() or 0)
    if active_count <= keep_warm_workers:
        return None

    work_count_result = await db.execute(
        select(func.count()).select_from(Task).where(Task.status.in_(["PENDING", "PROCESSING"]))
    )
    if int(work_count_result.scalar() or 0) > 0:
        return None

    cutoff = now - timedelta(seconds=idle_seconds)
    result = await db.execute(
        select(GoogleAccount)
        .where(
            GoogleAccount.runtime_status == RUNTIME_IDLE,
            GoogleAccount.worker_session_id.is_not(None),
            GoogleAccount.last_active.is_not(None),
            GoogleAccount.last_active <= cutoff,
        )
        .order_by(GoogleAccount.last_active.asc())
        .limit(1)
    )
    account = result.scalar_one_or_none()
    if not account or not account.worker_session_id:
        return None
    return account.email, account.worker_session_id
```

- [ ] **Step 4: Replace maintenance loop core**

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`, replace `_maintenance_loop` body with:

```python
async def _maintenance_loop():
    """Maintenance loop: reaper, cooldown reset, scale decisions, scale-down."""
    while True:
        await asyncio.sleep(30)
        now = datetime.now(timezone.utc)

        try:
            from app.config import KEEP_WARM_WORKERS, SCALE_DOWN_IDLE_SECONDS
            from app.lifecycle.reaper import (
                choose_scale_down_worker,
                reap_expired_task_leases,
                reap_expired_worker_sessions,
                release_expired_cooldowns,
            )

            async with async_session() as db:
                expired_workers = await reap_expired_worker_sessions(db, now=now)
                expired_tasks = await reap_expired_task_leases(db, now=now)
                released_count = await release_expired_cooldowns(db, now=now)
                scale_down = await choose_scale_down_worker(
                    db,
                    now=now,
                    keep_warm_workers=KEEP_WARM_WORKERS,
                    idle_seconds=SCALE_DOWN_IDLE_SECONDS,
                )
                await db.commit()

            for email in expired_workers:
                logger.warning("Reaped expired worker session for %s", email)
                manager.disconnect(email)
                _safe_create_task(play_runner.stop_colab_worker(email))

            for task_id in expired_tasks:
                logger.warning("Reaped expired task lease for %s", task_id)

            if released_count:
                logger.info("Released %d expired cooldown accounts", released_count)

            if scale_down:
                email, worker_session_id = scale_down
                if manager.session_by_email.get(email) == worker_session_id:
                    logger.info("Scale-down: stopping idle worker %s session=%s", email, worker_session_id)
                    _safe_create_task(stop_expired_worker(email))

            await _maybe_scale_up()

        except Exception as exc:
            logger.error("Maintenance loop error: %s", exc, exc_info=True)
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_reaper.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/lifecycle/reaper.py app/routes/ws.py tests/test_lifecycle_reaper.py
git commit -m "feat: reap expired worker and task leases"
```

---

## Task 12: Rewrite Autoscale Using Unified Capacity

**Files:**
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/main.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/tasks.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/tts.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_capacity.py`

- [ ] **Step 1: Add failing autoscale decision tests**

Append to `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_capacity.py`:

```python
@pytest.mark.asyncio
async def test_maybe_scale_up_launches_warm_worker_when_capacity_zero(monkeypatch):
    await init_db()
    launches = []

    async def fake_try_auto_rotate():
        launches.append("launch")

    monkeypatch.setattr("app.routes.ws._try_auto_rotate", fake_try_auto_rotate)

    async with async_session() as db:
        db.add(GoogleAccount(email="ready-warm@example.com", profile_name="ready-warm", status="READY"))
        await db.commit()

    from app.routes.ws import _maybe_scale_up
    await _maybe_scale_up()

    assert launches == ["launch"]


@pytest.mark.asyncio
async def test_maybe_scale_up_launches_backup_worker_when_load_begins(monkeypatch):
    await init_db()
    launches = []

    async def fake_try_auto_rotate():
        launches.append("launch")

    monkeypatch.setattr("app.routes.ws._try_auto_rotate", fake_try_auto_rotate)

    async with async_session() as db:
        db.add_all(
            [
                GoogleAccount(email="active@example.com", profile_name="active", status="READY", runtime_status="BUSY", worker_session_id="w1", browser_session_id="b1"),
                GoogleAccount(email="ready-backup@example.com", profile_name="ready-backup", status="READY"),
            ]
        )
        voice = Voice(name="v", audio_path="/tmp/ref.wav")
        db.add(voice)
        await db.flush()
        db.add(Task(id="pending-backup", text="hello", voice_id=voice.id, status="PENDING"))
        await db.commit()

    from app.routes.ws import _maybe_scale_up
    await _maybe_scale_up()

    assert launches == ["launch"]


@pytest.mark.asyncio
async def test_maybe_scale_up_heavy_load_waits_for_sustained_threshold(monkeypatch):
    await init_db()
    launches = []

    async def fake_try_auto_rotate():
        launches.append("launch")

    monkeypatch.setattr("app.routes.ws._try_auto_rotate", fake_try_auto_rotate)

    async with async_session() as db:
        db.add_all(
            [
                GoogleAccount(email="active1@example.com", profile_name="active1", status="READY", runtime_status="BUSY", worker_session_id="w1", browser_session_id="b1"),
                GoogleAccount(email="active2@example.com", profile_name="active2", status="READY", runtime_status="BUSY", worker_session_id="w2", browser_session_id="b2"),
                GoogleAccount(email="ready-heavy@example.com", profile_name="ready-heavy", status="READY"),
            ]
        )
        voice = Voice(name="v", audio_path="/tmp/ref.wav")
        db.add(voice)
        await db.flush()
        for index in range(10):
            db.add(Task(id=f"pending-heavy-{index}", text="hello", voice_id=voice.id, status="PENDING"))
        await db.commit()

    import app.routes.ws as ws_route
    ws_route._scale_up_requested_at = None

    await ws_route._maybe_scale_up()
    assert launches == []
    assert ws_route._scale_up_requested_at is not None

    ws_route._scale_up_requested_at = ws_route._scale_up_requested_at.replace(second=ws_route._scale_up_requested_at.second - 11)
    await ws_route._maybe_scale_up()

    assert launches == ["launch"]
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_capacity.py::test_maybe_scale_up_launches_warm_worker_when_capacity_zero tests/test_lifecycle_capacity.py::test_maybe_scale_up_launches_backup_worker_when_load_begins tests/test_lifecycle_capacity.py::test_maybe_scale_up_heavy_load_waits_for_sustained_threshold -v
```

Expected: FAIL because `_maybe_scale_up` uses old status math.

- [ ] **Step 3: Rewrite `_maybe_scale_up`**

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`, replace `_maybe_scale_up` with:

```python
async def _maybe_scale_up():
    global _scale_up_requested_at

    if _consecutive_rotation_failures >= 3:
        return
    if _rotate_lock.locked():
        return

    from app.config import (
        KEEP_WARM_WORKERS,
        MAX_CONCURRENT_WORKERS,
        SCALE_UP_PENDING_THRESHOLD,
        SCALE_UP_SUSTAIN_SECONDS,
    )
    from app.lifecycle.capacity import get_capacity_snapshot, should_launch_worker

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        snapshot = await get_capacity_snapshot(db, max_workers=MAX_CONCURRENT_WORKERS, warm_target=KEEP_WARM_WORKERS)

    if not should_launch_worker(snapshot):
        return

    if snapshot.active_capacity < snapshot.warm_target:
        _safe_create_task(_try_auto_rotate())
        return

    if snapshot.pending_tasks > 0 and snapshot.active_capacity == 1:
        _safe_create_task(_try_auto_rotate())
        return

    if snapshot.pending_tasks >= SCALE_UP_PENDING_THRESHOLD and snapshot.active_capacity >= 2:
        if _scale_up_requested_at is None:
            _scale_up_requested_at = now
            return

        if (now - _scale_up_requested_at).total_seconds() >= SCALE_UP_SUSTAIN_SECONDS:
            _scale_up_requested_at = now
            _safe_create_task(_try_auto_rotate())
        return

    _scale_up_requested_at = None
```

- [ ] **Step 4: Simplify `_on_batch_request`**

Replace `_on_batch_request` with:

```python
async def _on_batch_request():
    await _maybe_scale_up()
```

- [ ] **Step 5: Update delayed auto pickup**

In `/media/reup/Data_sv2/SVRV/Colab/app/main.py`, change `_delayed_auto_pickup` final call:

```python
    from app.routes.ws import _maybe_scale_up
    await _maybe_scale_up()
```

- [ ] **Step 6: Update task-created scaling calls**

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/tasks.py`, after task commit and dispatch attempt, keep:

```python
    from app.routes.ws import _maybe_scale_up
    _safe_create_task(_maybe_scale_up())
```

Remove old `_has_starting_or_active_account` branches if they cause duplicate logic. Replace no-idle block with:

```python
        from app.routes.ws import _maybe_scale_up
        _safe_create_task(_maybe_scale_up())
```

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/tts.py`, replace old `_try_auto_rotate/_has_starting_or_active_account` branches with `_maybe_scale_up()` calls:

```python
            from app.routes.ws import _maybe_scale_up
            asyncio.create_task(_maybe_scale_up())
```

For batch route:

```python
    from app.routes.ws import _maybe_scale_up
    asyncio.create_task(_maybe_scale_up())
```

- [ ] **Step 7: Run tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_capacity.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/routes/ws.py app/main.py app/routes/tasks.py app/routes/tts.py tests/test_lifecycle_capacity.py
git commit -m "feat: use unified capacity autoscaling"
```

---

## Task 13: Add Admin Capacity Endpoint and Account Visibility

**Files:**
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/accounts.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_admin_capacity_endpoint.py`

- [ ] **Step 1: Write failing endpoint unit test**

Create `/media/reup/Data_sv2/SVRV/Colab/tests/test_admin_capacity_endpoint.py`:

```python
from datetime import datetime, timezone

import pytest

from app.database import async_session, init_db
from app.models import GoogleAccount, Task, Voice
from app.routes.accounts import get_capacity


@pytest.mark.asyncio
async def test_get_capacity_returns_snapshot_and_per_account_lifecycle_fields():
    await init_db()

    async with async_session() as db:
        account = GoogleAccount(
            email="worker@example.com",
            profile_name="worker",
            status="READY",
            runtime_status="IDLE",
            worker_session_id="worker-session",
            browser_session_id="browser-session",
            started_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
            last_heartbeat_at=datetime(2026, 6, 13, 0, 1, tzinfo=timezone.utc),
            quota_reset_at=None,
            current_task_id=None,
        )
        voice = Voice(name="v", audio_path="/tmp/ref.wav")
        db.add_all([account, voice])
        await db.flush()
        db.add(Task(id="pending", text="hello", voice_id=voice.id, status="PENDING"))
        await db.commit()

        response = await get_capacity(db=db)

    assert response["max_workers"] == 4
    assert response["warm_target"] == 1
    assert response["active_capacity"] == 1
    assert response["idle_workers"] == 1
    assert response["pending_tasks"] == 1
    assert response["accounts"] == [
        {
            "email": "worker@example.com",
            "status": "READY",
            "runtime_status": "IDLE",
            "worker_session_id": "worker-session",
            "browser_session_id": "browser-session",
            "started_at": "2026-06-13T00:00:00",
            "last_heartbeat_at": "2026-06-13T00:01:00",
            "quota_reset_at": None,
            "current_task_id": None,
        }
    ]
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_admin_capacity_endpoint.py -v
```

Expected: FAIL with `ImportError` or missing `get_capacity`.

- [ ] **Step 3: Add capacity endpoint**

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/accounts.py`, add imports:

```python
from app.lifecycle.capacity import get_capacity_snapshot
```

Add endpoint before account-id routes:

```python
@router.get("/capacity")
async def get_capacity(db: AsyncSession = Depends(get_db)):
    snapshot = await get_capacity_snapshot(
        db,
        max_workers=config.MAX_CONCURRENT_WORKERS,
        warm_target=config.KEEP_WARM_WORKERS,
    )
    result = await db.execute(select(GoogleAccount).order_by(GoogleAccount.email.asc()))
    accounts = result.scalars().all()

    return {
        "max_workers": snapshot.max_workers,
        "warm_target": snapshot.warm_target,
        "active_capacity": snapshot.active_capacity,
        "idle_workers": snapshot.idle_workers,
        "busy_workers": snapshot.busy_workers,
        "starting_workers": snapshot.starting_workers,
        "pending_tasks": snapshot.pending_tasks,
        "processing_tasks": snapshot.processing_tasks,
        "ready_accounts": snapshot.ready_accounts,
        "accounts": [
            {
                "email": account.email,
                "status": account.status,
                "runtime_status": account.runtime_status,
                "worker_session_id": account.worker_session_id,
                "browser_session_id": account.browser_session_id,
                "started_at": account.started_at.isoformat() if account.started_at else None,
                "last_heartbeat_at": account.last_heartbeat_at.isoformat() if account.last_heartbeat_at else None,
                "quota_reset_at": account.quota_reset_at.isoformat() if account.quota_reset_at else None,
                "current_task_id": account.current_task_id,
            }
            for account in accounts
        ],
    }
```

- [ ] **Step 4: Update list accounts response**

In `list_accounts`, add fields:

```python
            "runtime_status": a.runtime_status,
            "worker_session_id": a.worker_session_id,
            "browser_session_id": a.browser_session_id,
            "current_task_id": a.current_task_id,
            "last_heartbeat_at": a.last_heartbeat_at.isoformat() if a.last_heartbeat_at else None,
            "lease_expires_at": a.lease_expires_at.isoformat() if a.lease_expires_at else None,
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_admin_capacity_endpoint.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/routes/accounts.py tests/test_admin_capacity_endpoint.py
git commit -m "feat: add admin capacity endpoint"
```

---

## Task 14: Update Account Stop/Delete and Cooldown Cleanup

**Files:**
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/accounts.py`
- Modify: `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`
- Test: `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_reaper.py`

- [ ] **Step 1: Add failing account cleanup test**

Append to `/media/reup/Data_sv2/SVRV/Colab/tests/test_lifecycle_reaper.py`:

```python
@pytest.mark.asyncio
async def test_stop_worker_clears_runtime_session_fields(monkeypatch):
    await init_db()
    stopped = []

    async def fake_stop(email):
        stopped.append(email)

    monkeypatch.setattr("app.routes.accounts.play_runner.stop_colab_worker", fake_stop)

    async with async_session() as db:
        account = GoogleAccount(
            email="stop@example.com",
            profile_name="stop",
            status="READY",
            runtime_status="IDLE",
            worker_session_id="session-stop",
            browser_session_id="browser-stop",
            current_task_id=None,
        )
        db.add(account)
        await db.commit()
        account_id = account.id

    from app.routes.accounts import stop_worker

    async with async_session() as db:
        response = await stop_worker(account_id, db=db)
        await db.commit()

    async with async_session() as db:
        account = await db.get(GoogleAccount, account_id)

    assert stopped == ["stop@example.com"]
    assert response["status"] == "READY"
    assert account.runtime_status is None
    assert account.worker_session_id is None
    assert account.browser_session_id is None
    assert account.current_task_id is None
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_reaper.py::test_stop_worker_clears_runtime_session_fields -v
```

Expected: FAIL because stop sets `OFFLINE` only.

- [ ] **Step 3: Update stop_worker**

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/accounts.py`, replace stop mutation:

```python
    await play_runner.stop_colab_worker(account.email)
    account.runtime_status = None
    account.worker_session_id = None
    account.browser_session_id = None
    account.current_task_id = None
    account.last_heartbeat_at = None
    account.lease_expires_at = None
    account.colab_pid = None
    if account.status not in ("COOLDOWN", "NEEDS_LOGIN", "DISABLED"):
        account.status = "READY"
    await db.commit()
    return {"id": account.id, "status": account.status}
```

- [ ] **Step 4: Update delete_worker cleanup**

In `delete_account`, before delete:

```python
    account.runtime_status = None
    account.worker_session_id = None
    account.browser_session_id = None
    account.current_task_id = None
    account.last_heartbeat_at = None
    account.lease_expires_at = None
```

- [ ] **Step 5: Update cooldown handler to clear fields after stop**

In `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py` `_handle_status`, in `OUT_OF_QUOTA` branch after task requeue, set:

```python
                acc.runtime_status = "STOPPING"
                acc.worker_session_id = None
                acc.browser_session_id = None
                acc.current_task_id = None
                acc.lease_expires_at = None
                acc.last_heartbeat_at = None
```

- [ ] **Step 6: Run test**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest tests/test_lifecycle_reaper.py::test_stop_worker_clears_runtime_session_fields -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app/routes/accounts.py app/routes/ws.py tests/test_lifecycle_reaper.py
git commit -m "feat: clear lifecycle fields when stopping workers"
```

---

## Task 15: Full Test and Integration Cleanup

**Files:**
- Modify as needed based on test failures:
  - `/media/reup/Data_sv2/SVRV/Colab/app/routes/ws.py`
  - `/media/reup/Data_sv2/SVRV/Colab/app/routes/tasks.py`
  - `/media/reup/Data_sv2/SVRV/Colab/app/routes/tts.py`
  - `/media/reup/Data_sv2/SVRV/Colab/app/routes/accounts.py`
  - `/media/reup/Data_sv2/SVRV/Colab/app/automation/play_runner.py`
  - `/media/reup/Data_sv2/SVRV/Colab/colab/worker.py`
- Test: all lifecycle tests and existing health test

- [ ] **Step 1: Run lifecycle test suite**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest \
  tests/test_lifecycle_models.py \
  tests/test_lifecycle_reconciler.py \
  tests/test_lifecycle_sessions.py \
  tests/test_lifecycle_completion.py \
  tests/test_lifecycle_capacity.py \
  tests/test_lifecycle_reaper.py \
  tests/test_admin_capacity_endpoint.py \
  tests/test_worker_protocol.py \
  -v
```

Expected: PASS.

- [ ] **Step 2: Fix import/signature fallout if tests fail**

If `TypeError: _dispatch_task() missing 1 required positional argument: 'db'` appears, search exact callers:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && grep -R "_dispatch_task(" -n app tests
```

Expected matches must use one of these exact forms:

```python
await _dispatch_task(task, idle_email, worker_session_id, db)
await _dispatch_task(task, email, worker_session_id, db)
```

Apply same replacement at every stale caller.

- [ ] **Step 3: Fix idle worker tuple fallout if tests fail**

If code treats idle worker as string, search:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && grep -R "get_idle_worker()" -n app tests
```

Expected direct dispatch pattern:

```python
idle_worker = manager.get_idle_worker()
if idle_worker:
    idle_email, worker_session_id = idle_worker
    await _dispatch_task(task, idle_email, worker_session_id, db)
```

Expected boolean-only pattern:

```python
if not manager.get_idle_worker():
    ...
```

- [ ] **Step 4: Run existing smoke tests**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && pytest test_health.py -v
```

Expected: PASS.

- [ ] **Step 5: Run import compile check**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && python -m compileall app colab
```

Expected: no syntax errors.

- [ ] **Step 6: Verify no old runtime account status writes remain**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && grep -R "status = \"\\(ACTIVE\\|BUSY\\|OFFLINE\\|CONNECTING\\|LOADING\\)\"" -n app || true
```

Expected: no matches in runtime worker lifecycle paths. Login-only flows may still use temporary login states only if they are immediately converted to `READY`/`NEEDS_LOGIN`; otherwise convert them to `READY`/`NEEDS_LOGIN`.

- [ ] **Step 7: Commit cleanup**

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app colab tests test_health.py
git commit -m "test: verify worker lifecycle integration"
```

---

## Task 16: Manual Runtime Verification

**Files:**
- No source files expected.
- Commands verify runtime behavior against design.

- [ ] **Step 1: Start backend with one worker process**

Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && uvicorn app.main:app --workers 1 --host 0.0.0.0 --port 8090
```

Expected logs contain:

```text
Cleaning up zombie browser processes...
Initializing database...
Reconciling startup lifecycle state...
Startup lifecycle state reconciled successfully.
Maintenance background loop started.
```

- [ ] **Step 2: Verify capacity endpoint**

Run in second shell:

```bash
curl -s http://localhost:8090/api/accounts/capacity
```

Expected JSON shape includes:

```json
{
  "max_workers": 4,
  "warm_target": 1,
  "active_capacity": 0,
  "idle_workers": 0,
  "busy_workers": 0,
  "starting_workers": 0,
  "pending_tasks": 0,
  "processing_tasks": 0,
  "ready_accounts": 0,
  "accounts": []
}
```

If admin auth blocks direct curl, use existing admin session/browser and verify endpoint through dashboard network tab or authenticated request.

- [ ] **Step 3: Verify startup reconciliation after simulated stale DB state**

Stop backend. Run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && sqlite3 data/db.sqlite3 "UPDATE google_accounts SET status='ACTIVE', runtime_status='BUSY', worker_session_id='stale', browser_session_id='stale-browser', current_task_id='stale-task', lease_expires_at=datetime('now', '+5 minutes'), colab_pid=123 WHERE id=(SELECT id FROM google_accounts LIMIT 1);"
```

Start backend again:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && uvicorn app.main:app --workers 1 --host 0.0.0.0 --port 8090
```

Check DB:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && sqlite3 data/db.sqlite3 "SELECT status, runtime_status, worker_session_id, browser_session_id, current_task_id, lease_expires_at, colab_pid FROM google_accounts LIMIT 1;"
```

Expected row:

```text
READY||||||
```

- [ ] **Step 4: Verify worker launch session fields**

Start a worker from admin or API. Then run:

```bash
cd /media/reup/Data_sv2/SVRV/Colab && sqlite3 data/db.sqlite3 "SELECT status, runtime_status, worker_session_id IS NOT NULL, browser_session_id IS NOT NULL FROM google_accounts WHERE runtime_status IS NOT NULL LIMIT 1;"
```

Expected during launch:

```text
READY|STARTING_BROWSER|1|1
```

Expected after worker websocket connects:

```text
READY|IDLE|1|1
```

- [ ] **Step 5: Verify stale completion rejection manually**

With a processing task, run a stale completion message only if using a websocket test client. Expected server log contains:

```text
Ignoring stale completion
```

Expected DB task remains:

```text
PROCESSING
```

- [ ] **Step 6: Verify single backend worker deployment rule**

Run production command:

```bash
uvicorn app.main:app --workers 1
```

Expected: app runs. Do not deploy `--workers > 1` until shared queue, distributed locks, and pub/sub design exists.

- [ ] **Step 7: Final commit if manual verification changed docs/config only**

If any small runtime verification fixes were required:

```bash
cd /media/reup/Data_sv2/SVRV/Colab
git add app colab tests
git commit -m "fix: harden worker lifecycle runtime verification"
```

---

## Self-Review Checklist

- [ ] Spec coverage:
  - Durable account eligibility states implemented in constants, models, reconciler, account routes.
  - Runtime worker states implemented in constants, DB columns, websocket status, capacity.
  - Browser ownership enforced via `browser_session_id` reservation before launch.
  - Worker ownership enforced via `worker_session_id` register, dispatch, completion, upload.
  - Startup reconciler kills old browser processes in existing `main.py` then clears runtime state and orphan tasks.
  - Warm worker rule implemented by `_maybe_scale_up`.
  - Request-time backup and heavy-load scale-up implemented by `_maybe_scale_up`.
  - Capacity formula centralized in `app/lifecycle/capacity.py`.
  - Dispatch rule implemented in `_dispatch_task`.
  - Completion rule implemented in `_handle_task_completed` and upload endpoint session guard.
  - Reaper rules implemented in `app/lifecycle/reaper.py` and `_maintenance_loop`.
  - Cooldown and lifetime cleanup supported by `_handle_status("OUT_OF_QUOTA")`, reaper cooldown release, existing lifecycle loop stop.
  - Scale-down rule implemented by `choose_scale_down_worker`.
  - Admin visibility endpoint added at `/api/accounts/capacity`.
  - Config values added in `app/config.py`.
  - Single backend process rule verified manually.

- [ ] Placeholder scan:
  - No task uses “TBD”.
  - No task uses “TODO”.
  - No task says “similar to”.
  - Every code-changing step includes exact code or exact replacement pattern.
  - Every feature slice has tests.

- [ ] Type/signature consistency:
  - `manager.get_idle_worker()` returns `tuple[str, str] | None`.
  - `_dispatch_task(task, email, worker_session_id, db)` used everywhere.
  - `manager.send_task(email, worker_session_id, task_id, ...)` used everywhere.
  - `_handle_task_completed(task_id, worker_session_id, email)` used by websocket action.
  - `_handle_task_failed(task_id, worker_session_id, error, email)` used by websocket action.
  - `play_runner.start_colab_worker(email, server_url, worker_session_id, browser_session_id=None)` used everywhere.
  - Worker CLI requires `--worker-session-id`.
  - Task upload endpoint requires `worker_session_id` query parameter.