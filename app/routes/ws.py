"""WebSocket routes for worker communication and dashboard."""
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
from app.services.connection_manager import manager, _dashboard_clients, broadcast_to_dashboard, _requeue_processing_tasks

logger = logging.getLogger(__name__)

router = APIRouter()

_pending_direct_events: dict[str, asyncio.Event] = {}
_rotate_lock = asyncio.Lock()


# ── Dashboard WebSocket ───────────────────────────────────────
@router.websocket("/ws/dashboard")
async def websocket_dashboard(ws: WebSocket):
    # Require JWT token as query param ?token=...
    token_str = ws.query_params.get("token", "")
    if not token_str:
        await ws.close(code=4001)
        return
    from app.services.auth import decode_access_token
    payload = decode_access_token(token_str)
    if not payload or "user_id" not in payload:
        await ws.close(code=4001)
        return
    from app.models.user import User
    async with async_session() as _db:
        user = (await _db.execute(select(User).where(User.id == payload["user_id"], User.is_active == True))).scalar_one_or_none()
        if not user or user.role != "admin":
            await ws.close(code=4001)
            return

    await ws.accept()
    _dashboard_clients.append(ws)
    try:
        while True:
            # Add timeout to catch unclosed connections
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=60.0)
                try:
                    js = json.loads(data)
                    if js.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                except:
                    pass
            except asyncio.TimeoutError:
                # 60s timeout without ping/data -> client is dead
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in _dashboard_clients:
            _dashboard_clients.remove(ws)


# ── Disconnect Cleanup Grace Period ───────────────────────────
async def cleanup_worker_after_delay(email: str, worker_session_id: str):
    """Grace period for temporary disconnects before fully cleaning up from database."""
    await asyncio.sleep(15)
    info = manager.worker_info.get(email)
    if info and info.get("worker_session_id") == worker_session_id:
        logger.info("Worker %s reconnected within grace period. Aborting cleanup.", email)
        return
    try:
        async with async_session() as db:
            res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
            acc = res.scalar_one_or_none()
            if acc and acc.worker_session_id == worker_session_id:
                acc.status = "OFFLINE"
                acc.worker_session_id = None
                acc.runtime_status = None
                acc.colab_pid = None
                acc.current_task_id = None
                acc.idle_since = None
                task_ids = await _requeue_processing_tasks(db, acc.id)
                await db.commit()
                for tid in task_ids:
                    ev = _pending_direct_events.pop(tid, None)
                    if ev:
                        ev.set()
                await manager.broadcast_status({"event": "worker_disconnected", "email": email})
                logger.info("Worker %s fully cleaned up from database (grace period expired)", email)
    except Exception as e:
        logger.error("Deferred disconnect cleanup error for %s: %s", email, e)
    # Trigger rotation/scale check if tasks are pending
    asyncio.create_task(_maybe_scale_up())


# ── Helper functions for validation ────────────────────────────
async def validate_worker_registration(db, email: str, worker_session_id: str) -> bool:
    res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
    acc = res.scalar_one_or_none()
    if acc and acc.worker_session_id == worker_session_id:
        return True
    return False


async def validate_task_ownership(db, task_id: str, email: str, worker_session_id: str) -> bool:
    res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
    acc = res.scalar_one_or_none()
    if acc and acc.worker_session_id == worker_session_id:
        task = await db.get(Task, task_id)
        if task and (task.worker_id == acc.id or task.worker_session_id == worker_session_id):
            return True
    return False


# ── Worker WebSocket Endpoint ──────────────────────────────────
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

        async with async_session() as db:
            valid = await validate_worker_registration(db, email, worker_session_id)
            if not valid:
                logger.warning("Worker register rejected for %s (session %s)", email, worker_session_id)
                await ws.close(code=4002)
                return

        wtype = raw.get("type", "tts")
        await manager.connect(ws, email, gpu, worker_session_id, worker_type=wtype)

        # Sync in-memory status to IDLE after registration
        if email in manager.worker_info:
            manager.worker_info[email]["status"] = "IDLE"

        async with async_session() as db:
            res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
            account = res.scalar_one_or_none()
            if account:
                account.status = "ACTIVE"
                account.runtime_status = "IDLE"
                account.last_active = datetime.now(timezone.utc)
                await db.commit()

        # Dispatch next task if idle
        await _handle_status(email, "IDLE")

        await manager.broadcast_status({"event": "worker_connected", "email": email, "gpu": gpu})

        # Loop for tasks and pongs
        last_pong = time.time()
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_json(), timeout=75.0)
            except asyncio.TimeoutError:
                if time.time() - last_pong > 75:
                    logger.warning("Worker %s: heartbeat timeout (no pong in 75s)", email)
                    break
                continue
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
            elif action == "ping" or action == "pong" or action == "pong_status":
                if email in manager.worker_info:
                    last_pong = time.time()
                    manager.worker_info[email]["last_pong"] = last_pong
                    async with async_session() as db:
                        await db.execute(
                            update(GoogleAccount)
                            .where(GoogleAccount.email == email)
                            .values(last_heartbeat_at=datetime.now(timezone.utc))
                        )
                        await db.commit()
                    # Respond to pings from client (or keepalive pong)
                    if action == "ping":
                        try:
                            await ws.send_json({"type": "pong", "timestamp": int(time.time())})
                        except:
                            pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WS error: %s", exc)
    finally:
        if email:
            manager.disconnect(email)
            if worker_session_id:
                asyncio.create_task(cleanup_worker_after_delay(email, worker_session_id))


# ── Status Updates and Task Dispatching ─────────────────────────
async def _handle_status(email: str, status: str):
    async with async_session() as db:
        res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
        acc = res.scalar_one_or_none()
        if acc:
            if status == "OUT_OF_QUOTA":
                from app.config import QUOTA_RESET_HOURS
                acc.status = "COOLDOWN"
                acc.quota_reset_at = datetime.now(timezone.utc) + timedelta(hours=QUOTA_RESET_HOURS)
                acc.worker_session_id = None
                acc.runtime_status = None
                acc.current_task_id = None
                acc.colab_pid = None
                acc.idle_since = None
                acc.assigned_node_id = None

                task_ids = await _requeue_processing_tasks(db, acc.id)
                await db.commit()

                for tid in task_ids:
                    ev = _pending_direct_events.pop(tid, None)
                    if ev:
                        ev.set()
                asyncio.create_task(stop_expired_worker(email))
                asyncio.create_task(_try_auto_rotate())
            else:
                acc.runtime_status = status
                acc.last_heartbeat_at = datetime.now(timezone.utc)
                if status == "IDLE":
                    if acc.idle_since is None:
                        acc.idle_since = datetime.now(timezone.utc)
                else:
                    acc.idle_since = None
                await db.commit()

    from app.routes.tasks import _dispatch_task
    if status == "IDLE":
        info = manager.worker_info.get(email, {})
        if info.get("status") != "IDLE":
            return

        async with async_session() as db:
            res = await db.execute(select(Task).where(Task.status == "PENDING").order_by(Task.created_at.asc()).limit(1))
            task = res.scalar_one_or_none()
            if task:
                await _dispatch_task(task, email, db)
                asyncio.create_task(_maybe_scale_up())

    await manager.broadcast_status({"event": "worker_status", "email": email, "status": status})


async def _handle_task_completed(tid: str, email: str, worker_session_id: str):
    async with async_session() as db:
        # Check if task already completed via HTTP upload
        task = await db.get(Task, tid)
        if task and task.status == "COMPLETED":
            return
        valid = await validate_task_ownership(db, tid, email, worker_session_id)
        if not valid:
            logger.warning("Reject completion for task %s (session mismatch)", tid)
            return

        t = await db.get(Task, tid)
        if t:
            t.status = "COMPLETED"
            t.completed_at = datetime.now(timezone.utc)

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

            acc_res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
            acc = acc_res.scalar_one_or_none()
            if acc:
                acc.runtime_status = "IDLE"
                acc.current_task_id = None

            await db.commit()

    await manager.broadcast_status({"event": "task_failed", "task_id": tid, "error": err})
    
    ev = _pending_direct_events.pop(tid, None)
    if ev:
        ev.set()


# ── Playwright Worker Lifecycle & Auto-scaling Loops ───────────
async def stop_expired_worker(email: str):
    ws = manager.active.get(email)
    if ws:
        try:
            await ws.send_json({"action": "shutdown"})
        except Exception:
            pass
    await asyncio.sleep(5)
    try:
        from app.automation import play_runner
        await play_runner.stop_colab_worker(email)
    except Exception as e:
        logger.warning("stop_expired_worker failed: %s", e)


async def _try_auto_rotate():
    async with _rotate_lock:
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            # 1. Reset accounts in COOLDOWN whose quota reset time has elapsed
            await db.execute(
                update(GoogleAccount)
                .where(GoogleAccount.status == "COOLDOWN", GoogleAccount.quota_reset_at <= now)
                .values(status="OFFLINE", quota_reset_at=None)
            )
            await db.commit()

            # 2. Query for next available OFFLINE/READY account, oldest active first
            res = await db.execute(
                select(GoogleAccount)
                .where(
                    GoogleAccount.status.in_(["OFFLINE", "READY"]),
                    (GoogleAccount.quota_reset_at.is_(None)) | (GoogleAccount.quota_reset_at <= now),
                )
                .order_by(GoogleAccount.last_active.asc().nullsfirst())
                .limit(1)
            )
            acc = res.scalar_one_or_none()
            if not acc:
                logger.info("No eligible account for rotation")
                return

            acc.status = "CONNECTING"
            acc.last_active = now
            email = acc.email
            import uuid
            worker_session_id = str(uuid.uuid4())
            acc.worker_session_id = worker_session_id
            await db.commit()

        try:
            import app.config as cfg
            logger.info("Auto-starting worker for %s -> %s", email, cfg.PUBLIC_SERVER_URL)
            from app.automation import play_runner
            await play_runner.start_colab_worker(email, cfg.PUBLIC_SERVER_URL, worker_session_id)
        except Exception as e:
            logger.error("Rotation failed for %s: %s", email, e)
            async with async_session() as db:
                res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
                acc = res.scalar_one_or_none()
                if acc:
                    if acc.status == "CONNECTING":
                        acc.status = "OFFLINE"
                        acc.worker_session_id = None
                    else:
                        acc.worker_session_id = None
                await db.commit()


async def _maybe_scale_up():
    from app.config import MAX_CONCURRENT_WORKERS, KEEP_WARM_WORKERS
    if _rotate_lock.locked():
        return
    async with async_session() as db:
        res = await db.execute(
            select(func.count()).select_from(Task).where(Task.status.in_(["PENDING", "PROCESSING"]))
        )
        requests_count = res.scalar() or 0
        
        res = await db.execute(
            select(func.count()).select_from(GoogleAccount).where(GoogleAccount.status.in_(["ACTIVE", "CONNECTING"]))
        )
        current_workers = res.scalar() or 0

    if requests_count >= 10:
        target = 5
    elif requests_count > 5:
        target = 2
    elif requests_count >= 1:
        target = 1
    else:
        target = KEEP_WARM_WORKERS

    target = min(target, MAX_CONCURRENT_WORKERS)

    if current_workers < target:
        logger.info("Scale-up: current workers %s < target %s (requests: %s). Scaling up...", current_workers, target, requests_count)
        asyncio.create_task(_try_auto_rotate())


async def _maintenance_loop():
    """Background loop: reset stale CONNECTING, proactive scale-up, scale-down idle."""
    STALE_CONNECTING_TIMEOUT = 900
    while True:
        try:
            await asyncio.sleep(30)
            now = datetime.now(timezone.utc)

            # 1. Reset stale CONNECTING accounts (browser opened but WS never connected)
            async with async_session() as db:
                stale_cutoff = now - timedelta(seconds=STALE_CONNECTING_TIMEOUT)
                result = await db.execute(
                    select(GoogleAccount).where(
                        GoogleAccount.status == "CONNECTING",
                        GoogleAccount.last_active < stale_cutoff,
                    )
                )
                for acc in result.scalars().all():
                    logger.warning("Resetting stale CONNECTING %s (stuck >%ss)", acc.email, STALE_CONNECTING_TIMEOUT)
                    acc.status = "OFFLINE"
                    acc.worker_session_id = None
                await db.commit()

            # 1.5 Clean up leaked browsers from crashed/failed workers
            from app.automation.play_runner import cleanup_zombie_browsers
            await cleanup_zombie_browsers(kill_active=False)

            # 2. Proactive scale-up when pending tasks pile up
            await _maybe_scale_up()

            # 3. Scale-down idle workers
            from app.config import KEEP_WARM_WORKERS, MAX_CONCURRENT_WORKERS
            async with async_session() as db:
                res = await db.execute(
                    select(func.count()).select_from(Task).where(Task.status.in_(["PENDING", "PROCESSING"]))
                )
                requests_count = res.scalar() or 0

                # Count active/connecting database accounts
                res = await db.execute(
                    select(GoogleAccount.email).where(GoogleAccount.status.in_(["ACTIVE", "CONNECTING"]))
                )
                active_emails = [r[0] for r in res.all()]

                # Exclude expiring ones from the count of active workers to prevent killing replacement workers
                non_expiring_emails = [
                    email for email in active_emails
                    if not manager.worker_info.get(email, {}).get("expiring", False)
                ]
                current_workers = len(non_expiring_emails)

            if requests_count >= 10:
                target = 5
            elif requests_count > 5:
                target = 2
            elif requests_count >= 1:
                target = 1
            else:
                target = KEEP_WARM_WORKERS

            target = min(target, MAX_CONCURRENT_WORKERS)

            excess_count = current_workers - target
            if excess_count > 0:
                for em, info in list(manager.worker_info.items()):
                    if info.get("status") == "IDLE" and not info.get("expiring"):
                        logger.info("Scale-down: stopping excess idle worker %s (current: %s, target: %s)", em, current_workers, target)
                        asyncio.create_task(stop_expired_worker(em))
                        excess_count -= 1
                        if excess_count <= 0:
                            break
        except Exception as e:
            logger.error("Error in maintenance loop: %s", e)


async def _worker_lifecycle_loop():
    """Monitor worker uptime and handover at WORKER_MAX_LIFETIME."""
    from app.config import WORKER_MAX_LIFETIME
    logger.info("Lifecycle loop started (max=%ss)", WORKER_MAX_LIFETIME)
    try:
        while True:
            await asyncio.sleep(60)
            now = datetime.now(timezone.utc)
            for email in list(manager.active.keys()):
                info = manager.worker_info.get(email)
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
                    if uptime >= WORKER_MAX_LIFETIME and not info.get("expiring"):
                        logger.info("Worker %s reached max lifetime (%.1fh). Triggering handover.", email, uptime/3600)
                        info["expiring"] = True
                        
                        # Determine if we actually need a replacement
                        async with async_session() as db:
                            res_tasks = await db.execute(
                                select(func.count()).select_from(Task).where(Task.status.in_(["PENDING", "PROCESSING"]))
                            )
                            req_cnt = res_tasks.scalar() or 0
                        
                        from app.config import KEEP_WARM_WORKERS
                        if req_cnt == 0 and KEEP_WARM_WORKERS == 0:
                            logger.info("No active requests and KEEP_WARM_WORKERS=0. Stopping expired worker %s directly.", email)
                            asyncio.create_task(stop_expired_worker(email))
                        else:
                            asyncio.create_task(_try_auto_rotate())
                            await broadcast_to_dashboard({"event": "worker_expiring", "email": email})

                    if info.get("expiring") and info.get("status") == "IDLE":
                        # If target is 0, we can stop the expired worker immediately
                        async with async_session() as db:
                            res_tasks = await db.execute(
                                select(func.count()).select_from(Task).where(Task.status.in_(["PENDING", "PROCESSING"]))
                            )
                            req_cnt = res_tasks.scalar() or 0
                        from app.config import KEEP_WARM_WORKERS
                        
                        if req_cnt == 0 and KEEP_WARM_WORKERS == 0:
                            logger.info("Graceful handover: stopping expired worker %s (target is 0)", email)
                            asyncio.create_task(stop_expired_worker(email))
                        elif len(manager.active) > 1:
                            ready_replacement = any(
                                e != email and manager.worker_info.get(e, {}).get("status") in ("IDLE", "BUSY") and not manager.worker_info.get(e, {}).get("expiring", False)
                                for e in manager.active
                            )
                            if ready_replacement:
                                logger.info("Graceful handover: stopping expired worker %s", email)
                                asyncio.create_task(stop_expired_worker(email))
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("Lifecycle loop error: %s", e)
