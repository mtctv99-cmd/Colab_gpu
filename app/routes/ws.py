
import time
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update, func

from app.database import async_session
from app.models import GoogleAccount, Task
from app.config import QUOTA_RESET_HOURS, WORKER_MAX_LIFETIME, PROFILES_DIR
from app.automation import play_runner
from pathlib import Path as _Path

logger = logging.getLogger(__name__)

router = APIRouter()

# Dashboard WebSocket
_dashboard_clients: list[WebSocket] = []
_pending_direct_events: dict[str, asyncio.Event] = {}

# Auto-scale settings
SCALE_UP_PENDING_PER_WORKER = 5
SCALE_UP_DELAY_SECONDS = 10
MAX_CONCURRENT_WORKERS = 4
SCALE_DOWN_IDLE_SECONDS = 1800  # 30 minutes idle before scale down
KEEP_WARM_WORKERS = 1          # Always keep at least 1 worker running

_scale_up_requested_at = None
_batch_request_count = 0
SCALE_UP_BATCH_THRESHOLD = 3


@router.websocket("/ws/dashboard")
async def websocket_dashboard(ws: WebSocket):
    await ws.accept()
    _dashboard_clients.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in _dashboard_clients:
            _dashboard_clients.remove(ws)
    except Exception:
        if ws in _dashboard_clients:
            _dashboard_clients.remove(ws)


async def broadcast_to_dashboard(msg: dict):
    dead = []
    for client in _dashboard_clients:
        try:
            await client.send_json(msg)
        except Exception:
            dead.append(client)
    for d in dead:
        if d in _dashboard_clients:
            _dashboard_clients.remove(d)


# Global background task tracking to prevent leaks
_background_tasks: set[asyncio.Task] = set()

def _safe_create_task(coro) -> asyncio.Task:
    """Create a task and track it to prevent GC or leaks."""
    t = asyncio.create_task(coro)
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)
    return t


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}
        self.worker_info: dict[str, dict[str, Any]] = {}
        self.heartbeat_task = None
        self.lifecycle_task = None

    async def connect(self, ws: WebSocket, email: str, gpu: str = "", worker_session_id: str = ""):
        now = datetime.now(timezone.utc)
        self.active[email] = ws
        self.worker_info[email] = {
            "gpu": gpu,
            "connected_at": now,
            "status": "LOADING",  # Explicitly show loading state while loading models
            "last_pong": time.time(),
            "expiring": False,
            "uptime": 0,
            "worker_session_id": worker_session_id,
        }
        logger.info("Worker connected and loading models: %s (GPU: %s)", email, gpu)

        # Update DB to reflect WARMING_MODEL state
        try:
            async with async_session() as db:
                await db.execute(
                    update(GoogleAccount).where(GoogleAccount.email == email)
                    .values(runtime_status="WARMING_MODEL", last_active=now, last_heartbeat_at=now)
                )
                await db.commit()
        except Exception as e:
            logger.error("Failed to update status to WARMING_MODEL: %s", e)

        if self.heartbeat_task is None or self.heartbeat_task.done():
            self.heartbeat_task = _safe_create_task(self._heartbeat_loop())
        if self.lifecycle_task is None or self.lifecycle_task.done():
            self.lifecycle_task = _safe_create_task(self._worker_lifecycle_loop())

    def disconnect(self, email: str):
        self.active.pop(email, None)
        self.worker_info.pop(email, None)
        logger.info("Worker disconnected: %s", email)

    async def send_task(self, email, task_id, text, voice_api_url, language=None, voice_ref_text=None, num_step=None, guidance_scale=None):
        ws = self.active.get(email)
        if ws is None:
            return False
        try:
            msg = {
                "action": "run_tts",
                "task_id": task_id,
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

    async def broadcast_status(self, message: dict):
        for ws in list(self.active.values()):
            try:
                await ws.send_json(message)
            except Exception:
                pass
        await broadcast_to_dashboard(message)

    def get_idle_worker(self) -> str | None:
        candidates = []
        for email, info in self.worker_info.items():
            if info.get("status") == "IDLE":
                candidates.append((email, info.get("expiring", False)))
        if not candidates:
            return None
        # Prioritize non-expiring workers
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    async def _heartbeat_loop(self):
        """Real-time heartbeat: ping every 15s, detect dead workers, scale up immediately."""
        try:
            while True:
                await asyncio.sleep(15)
                now = time.time()
                dead_workers = []

                for email in list(self.active.keys()):
                    ws = self.active.get(email)
                    info = self.worker_info.get(email)
                    if not ws or not info:
                        continue

                    # Check last pong — if > 60s stale, mark dead
                    last_pong = info.get("last_pong", 0)
                    if last_pong and (now - last_pong) > 60:
                        logger.warning("❤️‍🩹 Worker %s heartbeat lost (%.0fs stale). Marking DEAD.", email, now - last_pong)
                        dead_workers.append(email)
                        continue

                    # Send ping
                    try:
                        await ws.send_json({"action": "ping"})
                    except Exception:
                        logger.warning("❤️‍🩹 Worker %s send failed. Marking DEAD.", email)
                        dead_workers.append(email)

                for email in dead_workers:
                    # Force disconnect — cleanup will trigger scale-up
                    try:
                        ws = self.active.get(email)
                        if ws:
                            await ws.close(code=1001)
                    except Exception:
                        pass
                    self.disconnect(email)

                    # Mark account OFFLINE in DB
                    try:
                        async with async_session() as db:
                            res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
                            acc = res.scalar_one_or_none()
                            if acc and acc.status == "ACTIVE":
                                acc.status = "OFFLINE"
                                await db.commit()
                                # Reset any PROCESSING tasks
                                await db.execute(
                                    update(Task).where(Task.worker_id == acc.id, Task.status == "PROCESSING")
                                    .values(status="PENDING", worker_id=None)
                                )
                                await db.commit()
                    except Exception as e:
                        logger.error("Dead worker cleanup error: %s", e)

                    # Scale up replacement immediately
                    _safe_create_task(_maybe_scale_up())
                    await broadcast_to_dashboard({"event": "worker_disconnected", "email": email, "reason": "heartbeat_timeout"})

        except asyncio.CancelledError:
            pass

    async def _worker_lifecycle_loop(self):
        # Monitor worker uptime and handover at 3h45m
        logger.info("Lifecycle loop started (max=%ss)", WORKER_MAX_LIFETIME)
        try:
            while True:
                await asyncio.sleep(15)  # Faster check for smoother handover
                now = datetime.now(timezone.utc)
                for email in list(self.active.keys()):
                    info = self.worker_info.get(email)
                    if not info:
                        continue

                    async with async_session() as db:
                        res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
                        acc = res.scalar_one_or_none()
                        if not acc or not acc.started_at:
                            continue

                        sa = acc.started_at
                        if sa.tzinfo is None:
                            sa = sa.replace(tzinfo=timezone.utc)

                        uptime = (now - sa).total_seconds()
                        info["uptime"] = uptime

                        # 1. Trigger rotation if lifetime reached
                        if uptime >= WORKER_MAX_LIFETIME and not info.get("expiring"):
                            logger.info("🕒 Worker %s expired (%.1fh). Starting replacement...", email, uptime/3600)
                            info["expiring"] = True
                            _safe_create_task(_try_auto_rotate())
                            await broadcast_to_dashboard({"event": "worker_expiring", "email": email})

                        # 2. Check if handover can complete (new worker must be READY/IDLE)
                        if info.get("expiring") and info.get("status") == "IDLE":
                            # Look for a replacement that is NOT expiring and is already IDLE
                            has_ready_replacement = any(
                                e != email and
                                self.worker_info.get(e, {}).get("status") == "IDLE" and
                                not self.worker_info.get(e, {}).get("expiring", False)
                                for e in self.active
                            )

                            if has_ready_replacement:
                                logger.info("✅ Replacement ready. Stopping expired worker %s gracefully.", email)
                                _safe_create_task(stop_expired_worker(email))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Lifecycle loop error: %s", e)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Lifecycle loop error: %s", e)


manager = ConnectionManager()


async def stop_expired_worker(email: str):
    ws = manager.active.get(email)
    if ws:
        try:
            await ws.send_json({"action": "shutdown"})
        except Exception:
            pass
    await asyncio.sleep(5)
    try:
        await play_runner.stop_colab_worker(email)
    except Exception as e:
        logger.warning("stop_expired_worker failed: %s", e)


@router.websocket("/ws/worker")
async def websocket_worker(ws: WebSocket):
    await ws.accept()
    email = None
    worker_session_id = None
    try:
        raw = await ws.receive_json()
        if raw.get("action") != "register":
            await ws.close(code=4001)
            return
        email = raw["email"]
        worker_session_id = raw.get("worker_session_id")
        gpu = raw.get("gpu", "unknown")

        if not worker_session_id:
            logger.warning("Worker register missing worker_session_id for %s", email)
            await ws.close(code=4001)
            return

        from app.lifecycle.sessions import validate_worker_registration
        async with async_session() as db:
            valid = await validate_worker_registration(db, email, worker_session_id)
            if not valid:
                logger.warning("Worker register rejected for %s (session %s)", email, worker_session_id)
                await ws.close(code=4002)
                return

        await manager.connect(ws, email, gpu, worker_session_id)

        # Sync in-memory status to IDLE after registration
        if email in manager.worker_info:
            manager.worker_info[email]["status"] = "IDLE"

        async with async_session() as db:
            res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
            account = res.scalar_one_or_none()
            if account:
                account.runtime_status = "IDLE"
                account.last_active = datetime.now(timezone.utc)
                await db.commit()

        await manager.broadcast_status({"event": "worker_connected", "email": email, "gpu": gpu})

        # Loop for tasks and pongs
        while True:
            data = await ws.receive_json()
            action = data.get("action")

            # Verify sender session
            msg_sid = data.get("worker_session_id")
            if msg_sid and msg_sid != worker_session_id:
                logger.warning("Session ID mismatch in message from %s: msg %s != connection %s", email, msg_sid, worker_session_id)
                continue

            if action == "status":
                new_status = data.get("status", "IDLE")
                manager.worker_info[email]["status"] = new_status
                if new_status == "IDLE":
                    manager.worker_info[email]["idle_since"] = datetime.now(timezone.utc)
                else:
                    manager.worker_info[email].pop("idle_since", None)
                await _handle_status(email, new_status)
            elif action == "task_completed":
                await _handle_task_completed(data.get("task_id"), email, worker_session_id)
            elif action == "task_failed":
                await _handle_task_failed(data.get("task_id"), data.get("error", "Unknown"), email, worker_session_id)
            elif action == "pong":
                if email in manager.worker_info:
                    manager.worker_info[email]["last_pong"] = time.time()
                    # Update heartbeat in database
                    async with async_session() as db:
                        await db.execute(
                            update(GoogleAccount)
                            .where(GoogleAccount.email == email)
                            .values(last_heartbeat_at=datetime.now(timezone.utc))
                        )
                        await db.commit()
            elif action == "pong_status":
                if email in manager.worker_info:
                    manager.worker_info[email]["last_pong"] = time.time()
                    new_status = data.get("status", "IDLE")
                    manager.worker_info[email]["status"] = new_status
                    await _handle_status(email, new_status)
                    # Update heartbeat in database
                    async with async_session() as db:
                        await db.execute(
                            update(GoogleAccount)
                            .where(GoogleAccount.email == email)
                            .values(last_heartbeat_at=datetime.now(timezone.utc))
                        )
                        await db.commit()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WS error: %s", exc)
    finally:
        if email:
            manager.disconnect(email)
            try:
                async with async_session() as db:
                    res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
                    acc = res.scalar_one_or_none()
                    if acc:
                        acc.worker_session_id = None
                        acc.browser_session_id = None
                        acc.runtime_status = None
                        acc.colab_pid = None
                        acc.current_task_id = None
                        acc.idle_since = None

                        # Requeue tasks owned by this worker
                        res_t = await db.execute(
                            select(Task).where(Task.worker_id == acc.id, Task.status == "PROCESSING")
                        )
                        for pt in res_t.scalars().all():
                            pt.status = "PENDING"
                            pt.worker_id = None
                            pt.worker_session_id = None
                            pt.leased_at = None
                            pt.lease_expires_at = None
                            ev = _pending_direct_events.pop(pt.id, None)
                            if ev:
                                ev.set()
                    await db.commit()
            except Exception as e:
                logger.error("Disconnect cleanup error: %s", e)
            # Trigger recovery if pending tasks remain
            async with async_session() as db:
                res = await db.execute(select(func.count()).select_from(Task).where(Task.status == "PENDING"))
                if (res.scalar() or 0) > 0:
                    _safe_create_task(_maybe_scale_up())
            await manager.broadcast_status({"event": "worker_disconnected", "email": email})


async def _handle_status(email: str, status: str):
    """Sync real-time worker status (IDLE, BUSY, OUT_OF_QUOTA) to the Database."""
    async with async_session() as db:
        res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
        acc = res.scalar_one_or_none()
        if acc:
            if status == "OUT_OF_QUOTA":
                acc.status = "COOLDOWN"
                acc.quota_reset_at = datetime.now(timezone.utc) + timedelta(hours=QUOTA_RESET_HOURS)
                acc.worker_session_id = None
                acc.browser_session_id = None
                acc.runtime_status = None
                acc.current_task_id = None
                acc.colab_pid = None
                acc.idle_since = None

                # Reset processing tasks
                await db.execute(
                    update(Task)
                    .where(Task.worker_id == acc.id, Task.status == "PROCESSING")
                    .values(
                        status="PENDING",
                        worker_id=None,
                        worker_session_id=None,
                        leased_at=None,
                        lease_expires_at=None
                    )
                )
                await db.commit()
                _safe_create_task(play_runner.stop_colab_worker(email))
                _safe_create_task(_try_auto_rotate())
            else:
                # Update DB runtime status to match current activity
                acc.runtime_status = status
                acc.last_heartbeat_at = datetime.now(timezone.utc)
                if status == "IDLE":
                    if acc.idle_since is None:
                        acc.idle_since = datetime.now(timezone.utc)
                else:
                    acc.idle_since = None
                await db.commit()

    if status == "IDLE":
        _safe_create_task(_try_dispatch_next_task(email))

    await manager.broadcast_status({"event": "worker_status", "email": email, "status": status})


async def _try_dispatch_next_task(email: str):
    from app.routes.tasks import _dispatch_task
    async with async_session() as db:
        res = await db.execute(select(Task).where(Task.status == "PENDING").order_by(Task.created_at.asc()).limit(1))
        task = res.scalar_one_or_none()
        if task:
            # Get worker session
            info = manager.worker_info.get(email, {})
            wsid = info.get("worker_session_id")
            await _dispatch_task(task, email, wsid, db)


async def _handle_task_completed(tid: str, email: str, worker_session_id: str):
    from app.lifecycle.sessions import validate_task_ownership
    async with async_session() as db:
        valid = await validate_task_ownership(db, tid, email, worker_session_id)
        if not valid:
            logger.warning("Reject completion for task %s (session mismatch for %s)", tid, email)
            return

        t = await db.get(Task, tid)
        if t:
            t.status = "COMPLETED"
            t.completed_at = datetime.now(timezone.utc)

            # Reset worker runtime status in DB
            acc_res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
            acc = acc_res.scalar_one_or_none()
            if acc:
                acc.runtime_status = "IDLE"
                acc.current_task_id = None

            await db.commit()

    ev = _pending_direct_events.pop(tid, None)
    if ev:
        ev.set()
    await manager.broadcast_status({"event": "task_completed", "task_id": tid})


async def _handle_task_failed(tid: str, err: str, email: str, worker_session_id: str):
    from app.lifecycle.sessions import validate_task_ownership
    async with async_session() as db:
        valid = await validate_task_ownership(db, tid, email, worker_session_id)
        if not valid:
            logger.warning("Reject failure for task %s (session mismatch for %s)", tid, email)
            return

        t = await db.get(Task, tid)
        if t:
            t.status = "FAILED"
            t.error_message = err
            t.completed_at = datetime.now(timezone.utc)

            # Reset worker runtime status in DB
            acc_res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
            acc = acc_res.scalar_one_or_none()
            if acc:
                acc.runtime_status = "IDLE"
                acc.current_task_id = None

            await db.commit()

    ev = _pending_direct_events.pop(tid, None)
    if ev:
        ev.set()
    await manager.broadcast_status({"event": "task_failed", "task_id": tid, "error": err})
    ev = _pending_direct_events.pop(tid, None)
    if ev:
        ev.set()
    await manager.broadcast_status({"event": "task_failed", "task_id": tid, "error": err})


_rotate_lock = asyncio.Lock()
_consecutive_rotation_failures = 0
_ROTATION_FAILURE_BACKOFF_MINUTES = 2


async def _try_auto_rotate():
    global _consecutive_rotation_failures
    async with _rotate_lock:
        now = datetime.now(timezone.utc)
        from app.lifecycle.sessions import reserve_account_for_browser_launch
        async with async_session() as db:
            res = await reserve_account_for_browser_launch(db)
            if not res:
                logger.info("No eligible account for rotation")
                return
            email, browser_session_id = res

        try:
            import app.config as cfg
            logger.info("Auto-starting worker for %s (session: %s) -> %s", email, browser_session_id, cfg.SERVER_URL)
            await play_runner.start_colab_worker(email, cfg.SERVER_URL, browser_session_id)
            _consecutive_rotation_failures = 0
        except Exception as e:
            _consecutive_rotation_failures += 1
            logger.error("Rotation failed for %s: %s", email, e)
            error_msg = str(e)
            async with async_session() as db:
                from app.lifecycle.constants import ACCOUNT_NEEDS_LOGIN, ACCOUNT_COOLDOWN
                res_acc = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
                acc = res_acc.scalar_one_or_none()
                if acc:
                    # Clear session on failure
                    acc.worker_session_id = None
                    acc.browser_session_id = None
                    acc.runtime_status = None

                    if "session expired" in error_msg.lower() or "needs re-login" in error_msg.lower() or "needs login" in error_msg.lower():
                        acc.status = ACCOUNT_NEEDS_LOGIN
                        acc.quota_reset_at = None
                        logger.warning("Account %s marked NEEDS_LOGIN due to expired session", email)
                    else:
                        backoff = _ROTATION_FAILURE_BACKOFF_MINUTES * (1 + _consecutive_rotation_failures // 3)
                        reset_time = now + timedelta(minutes=backoff)
                        acc.status = ACCOUNT_COOLDOWN
                        acc.quota_reset_at = reset_time
                        logger.warning("Account %s marked COOLDOWN %dmin (browser launch error)", email, backoff)
                        # Clean up any zombie browser processes for this profile
                        try:
                            await play_runner.stop_colab_worker(email)
                        except Exception:
                            pass
                        try:
                            await play_runner.cleanup_zombie_browsers(kill_active=False)
                        except Exception:
                            pass
                await db.commit()


async def _maybe_scale_up():
    if _consecutive_rotation_failures >= 3:
        return
    if _rotate_lock.locked():
        return
    from app.lifecycle.capacity import check_scale_up_trigger
    async with async_session() as db:
        should_scale = await check_scale_up_trigger(db)
        if should_scale:
            _safe_create_task(_try_auto_rotate())


async def _on_batch_request():
    # Deprecated/Forward to unified scale-up trigger
    _safe_create_task(_maybe_scale_up())


async def _maintenance_loop():
    """30s loop: stale heartbeats, expired task leases, expired cooldown reset, scale-down."""
    from app.lifecycle.reaper import (
        reap_stale_sessions,
        reap_expired_task_leases,
        reset_expired_cooldown_accounts,
        find_scale_down_worker
    )
    while True:
        await asyncio.sleep(30)
        try:
            # 1. Expire stale heartbeats
            async with async_session() as db:
                stale_emails = await reap_stale_sessions(db)
                for email in stale_emails:
                    logger.warning("Stale heartbeat detected for %s. Stopping worker.", email)
                    _safe_create_task(play_runner.stop_colab_worker(email))

            # 2. Reap expired task leases
            async with async_session() as db:
                await reap_expired_task_leases(db)

            # 3. Reset expired cooldowns
            async with async_session() as db:
                await reset_expired_cooldown_accounts(db)

            # 4. Scale down idle workers if target met
            async with async_session() as db:
                active_emails = list(manager.active.keys())
                candidate = await find_scale_down_worker(db, active_emails)
                if candidate:
                    logger.info("Scale-down: stopping idle worker %s", candidate)
                    _safe_create_task(play_runner.stop_colab_worker(candidate))

            # 5. Check autoscale (keep warm / pending queue)
            await _maybe_scale_up()

        except Exception as e:
            logger.error("Error in maintenance loop: %s", e)
