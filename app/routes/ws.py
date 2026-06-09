
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
from app.config import QUOTA_RESET_HOURS, WORKER_MAX_LIFETIME
from app.automation import play_runner

logger = logging.getLogger(__name__)

router = APIRouter()

# Dashboard WebSocket
_dashboard_clients: list[WebSocket] = []
_pending_direct_events: dict[str, asyncio.Event] = {}

# Auto-scale settings
SCALE_UP_PENDING_PER_WORKER = 5
SCALE_UP_DELAY_SECONDS = 10
MAX_CONCURRENT_WORKERS = 4
SCALE_DOWN_IDLE_SECONDS = 300
KEEP_WARM_WORKERS = 0

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


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}
        self.worker_info: dict[str, dict[str, Any]] = {}
        self.heartbeat_task = None
        self.lifecycle_task = None

    async def connect(self, ws: WebSocket, email: str, gpu: str = ""):
        now = datetime.now(timezone.utc)
        self.active[email] = ws
        self.worker_info[email] = {
            "gpu": gpu,
            "connected_at": now,
            "status": "READY",
            "last_pong": time.time(),
            "expiring": False,
            "uptime": 0,
        }
        logger.info("Worker connected: %s (GPU: %s)", email, gpu)
        if self.heartbeat_task is None or self.heartbeat_task.done():
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        if self.lifecycle_task is None or self.lifecycle_task.done():
            self.lifecycle_task = asyncio.create_task(self._worker_lifecycle_loop())

    def disconnect(self, email: str):
        self.active.pop(email, None)
        self.worker_info.pop(email, None)
        logger.info("Worker disconnected: %s", email)

    async def send_task(self, email, task_id, text, voice_api_url, language=None, voice_ref_text=None):
        ws = self.active.get(email)
        if ws is None:
            return False
        try:
            await ws.send_json({
                "action": "run_tts",
                "task_id": task_id,
                "text": text,
                "voice_api_url": voice_api_url,
                "voice_ref_text": voice_ref_text,
                "language": language,
            })
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
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    async def _heartbeat_loop(self):
        try:
            while True:
                await asyncio.sleep(45)
                if not self.active:
                    continue
                for email in list(self.active.keys()):
                    ws = self.active.get(email)
                    if ws:
                        try:
                            await ws.send_json({"action": "ping"})
                        except Exception:
                            pass
        except asyncio.CancelledError:
            pass

    async def _worker_lifecycle_loop(self):
        # Monitor worker uptime and handover at 3h45m
        logger.info("Lifecycle loop started (max=%ss)", WORKER_MAX_LIFETIME)
        try:
            while True:
                await asyncio.sleep(60)
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
                        if uptime >= WORKER_MAX_LIFETIME and not info.get("expiring"):
                            logger.info("Worker %s reached max lifetime (%.1fh). Triggering handover.", email, uptime/3600)
                            info["expiring"] = True
                            asyncio.create_task(_try_auto_rotate())
                            await broadcast_to_dashboard({"event": "worker_expiring", "email": email})
                        if info.get("expiring") and info.get("status") == "IDLE" and len(self.active) > 1:
                            ready_replacement = any(
                                e != email and self.worker_info.get(e, {}).get("status") in ("IDLE", "BUSY") and not self.worker_info.get(e, {}).get("expiring", False)
                                for e in self.active
                            )
                            if ready_replacement:
                                logger.info("Graceful handover: stopping expired worker %s", email)
                                asyncio.create_task(stop_expired_worker(email))
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
    try:
        raw = await ws.receive_json()
        if raw.get("action") != "register":
            await ws.close(code=4001)
            return
        email = raw["email"]
        gpu = raw.get("gpu", "unknown")
        await manager.connect(ws, email, gpu)
        async with async_session() as db:
            res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
            account = res.scalar_one_or_none()
            if account:
                account.status = "ACTIVE"
                if not account.started_at:
                    account.started_at = datetime.now(timezone.utc)
                else:
                    sa = account.started_at
                    if sa.tzinfo is None:
                        sa = sa.replace(tzinfo=timezone.utc)
                    if (datetime.now(timezone.utc) - sa).total_seconds() > 3600 * 5:
                        account.started_at = datetime.now(timezone.utc)
                account.last_active = datetime.now(timezone.utc)
                await db.commit()
        await manager.broadcast_status({"event": "worker_connected", "email": email, "gpu": gpu})
        while True:
            data = await ws.receive_json()
            action = data.get("action")
            if action == "status":
                new_status = data.get("status", "IDLE")
                manager.worker_info[email]["status"] = new_status
                if new_status == "IDLE":
                    manager.worker_info[email]["idle_since"] = datetime.now(timezone.utc)
                else:
                    manager.worker_info[email].pop("idle_since", None)
                await _handle_status(email, new_status)
            elif action == "task_completed":
                await _handle_task_completed(data.get("task_id"))
            elif action == "task_failed":
                await _handle_task_failed(data.get("task_id"), data.get("error", "Unknown"))
            elif action == "pong":
                pass
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
                    if acc and acc.status == "ACTIVE":
                        acc.status = "OFFLINE"
                    if acc:
                        res_t = await db.execute(select(Task).where(Task.worker_id == acc.id, Task.status == "PROCESSING"))
                        for pt in res_t.scalars().all():
                            pt.status = "FAILED"
                            pt.error_message = "Disconnected"
                            ev = _pending_direct_events.pop(pt.id, None)
                            if ev:
                                ev.set()
                    await db.commit()
            except Exception as e:
                logger.error("Disconnect cleanup error: %s", e)
            await manager.broadcast_status({"event": "worker_disconnected", "email": email})


async def _handle_status(email: str, status: str):
    if status == "OUT_OF_QUOTA":
        async with async_session() as db:
            res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
            acc = res.scalar_one_or_none()
            if acc:
                acc.status = "COOLDOWN"
                acc.quota_reset_at = datetime.now(timezone.utc) + timedelta(hours=QUOTA_RESET_HOURS)
                await db.execute(update(Task).where(Task.worker_id == acc.id, Task.status == "PROCESSING").values(status="PENDING", worker_id=None))
                await db.commit()
        asyncio.create_task(play_runner.stop_colab_worker(email))
        asyncio.create_task(_try_auto_rotate())
    elif status == "IDLE":
        asyncio.create_task(_try_dispatch_next_task(email))
    await manager.broadcast_status({"event": "worker_status", "email": email, "status": status})


async def _try_dispatch_next_task(email: str):
    from app.routes.tasks import _dispatch_task
    async with async_session() as db:
        res = await db.execute(select(Task).where(Task.status == "PENDING").order_by(Task.created_at.asc()).limit(1))
        task = res.scalar_one_or_none()
        if task:
            await _dispatch_task(task, email, db)


async def _handle_task_completed(tid: str):
    async with async_session() as db:
        t = await db.get(Task, tid)
        if t:
            t.status = "COMPLETED"
            t.completed_at = datetime.now(timezone.utc)
            await db.commit()
    ev = _pending_direct_events.pop(tid, None)
    if ev:
        ev.set()
    await manager.broadcast_status({"event": "task_completed", "task_id": tid})


async def _handle_task_failed(tid: str, err: str):
    async with async_session() as db:
        t = await db.get(Task, tid)
        if t:
            t.status = "FAILED"
            t.error_message = err
            t.completed_at = datetime.now(timezone.utc)
            await db.commit()
    ev = _pending_direct_events.pop(tid, None)
    if ev:
        ev.set()
    await manager.broadcast_status({"event": "task_failed", "task_id": tid, "error": err})


_rotate_lock = asyncio.Lock()


async def _try_auto_rotate():
    async with _rotate_lock:
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            await db.execute(update(GoogleAccount).where(GoogleAccount.status == "COOLDOWN", GoogleAccount.quota_reset_at <= now).values(status="OFFLINE", quota_reset_at=None))
            await db.commit()
            res = await db.execute(
                select(GoogleAccount)
                .where(
                    GoogleAccount.status == "OFFLINE",
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
            await db.commit()
        try:
            import app.config as cfg
            logger.info("Auto-starting worker for %s -> %s", email, cfg.SERVER_URL)
            await play_runner.start_colab_worker(email, cfg.SERVER_URL)
        except Exception as e:
            logger.error("Rotation failed for %s: %s", email, e)
            async with async_session() as db:
                res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
                acc = res.scalar_one_or_none()
                if acc:
                    acc.status = "OFFLINE"
                await db.commit()


async def _maybe_scale_up():
    if _rotate_lock.locked() or len(manager.active) >= MAX_CONCURRENT_WORKERS:
        return
    async with async_session() as db:
        res = await db.execute(select(func.count()).select_from(Task).where(Task.status == "PENDING"))
        pending = res.scalar() or 0
    if pending > SCALE_UP_PENDING_PER_WORKER * max(len(manager.active), 1):
        asyncio.create_task(_try_auto_rotate())


async def _on_batch_request():
    if _rotate_lock.locked() or len(manager.active) >= MAX_CONCURRENT_WORKERS:
        return
    global _batch_request_count
    _batch_request_count += 1
    if _batch_request_count >= SCALE_UP_BATCH_THRESHOLD:
        _batch_request_count = 0
        asyncio.create_task(_try_auto_rotate())


async def _scale_down_loop():
    while True:
        await asyncio.sleep(60)
        if len(manager.active) <= KEEP_WARM_WORKERS:
            continue
        async with async_session() as db:
            res = await db.execute(select(func.count()).select_from(Task).where(Task.status.in_(["PENDING", "PROCESSING"])))
            if (res.scalar() or 0) > 0:
                continue
        now = datetime.now(timezone.utc)
        for em, info in list(manager.worker_info.items()):
            if info.get("status") == "IDLE" and not info.get("expiring"):
                idle_since = info.get("idle_since") or info.get("connected_at") or now
                if (now - idle_since).total_seconds() > SCALE_DOWN_IDLE_SECONDS:
                    logger.info("Scale-down: stopping idle worker %s", em)
                    asyncio.create_task(stop_expired_worker(em))
                    break
