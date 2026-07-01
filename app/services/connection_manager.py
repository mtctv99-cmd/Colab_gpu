"""Connection manager service to track active workers and broadcast dashboard updates."""
import time
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import WebSocket
from sqlalchemy import select, update

from app.database import async_session
from app.models import GoogleAccount, Task
from app.orchestrator.tts_state import _pending_direct_events
from app.orchestrator.utils import _safe_create_task

logger = logging.getLogger(__name__)

_dashboard_clients: list[WebSocket] = []


async def _requeue_processing_tasks(db, acc_id: int) -> list[str]:
    """Requeue all PROCESSING tasks owned by this worker and return their IDs."""
    res_t = await db.execute(
        select(Task).where(Task.worker_id == acc_id, Task.status == "PROCESSING")
    )
    tasks = res_t.scalars().all()
    t_ids = [t.id for t in tasks]
    for t in tasks:
        t.status = "PENDING"
        t.worker_id = None
        t.worker_session_id = None
        t.leased_at = None
        t.lease_expires_at = None

    return t_ids


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
        self.workers_by_type: dict[str, list[str]] = {"tts": []}
        self.heartbeat_task = None
        self.lifecycle_task = None

    async def connect(self, ws: WebSocket, email: str, gpu: str = "", worker_session_id: str = "", worker_type: str = "tts"):
        now = datetime.now(timezone.utc)
        self.active[email] = ws

        # Update DB to reflect model loading state & determine if it is a local worker
        is_local = True
        try:
            async with async_session() as db:
                res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
                acc = res.scalar_one_or_none()
                if acc:
                    is_local = (acc.assigned_node_id is None)
                    acc.runtime_status = "WARMING"
                    acc.last_active = now
                    acc.last_heartbeat_at = now
                    await db.commit()
        except Exception as e:
            logger.error("Failed to update status to WARMING and fetch node_id: %s", e)

        self.worker_info[email] = {
            "gpu": gpu,
            "connected_at": now,
            "status": "LOADING",  # Explicitly show loading state while loading models
            "last_pong": time.time(),
            "expiring": False,
            "uptime": 0,
            "worker_session_id": worker_session_id,
            "type": worker_type,
            "is_local": is_local,
        }
        self.workers_by_type.setdefault(worker_type, []).append(email)
        logger.info("Worker connected and loading models: %s (GPU: %s, is_local: %s)", email, gpu, is_local)

        if self.heartbeat_task is None or self.heartbeat_task.done():
            self.heartbeat_task = _safe_create_task(self._heartbeat_loop())

    def disconnect(self, email: str):
        info = self.worker_info.get(email, {})
        wtype = info.get("type", "tts")
        if email in self.workers_by_type.get(wtype, []):
            self.workers_by_type[wtype].remove(email)
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

    def get_local_idle_worker(self, type: str = "tts") -> str | None:
        candidates = []
        for email in self.workers_by_type.get(type, []):
            info = self.worker_info.get(email)
            if info and info.get("status") == "IDLE" and info.get("is_local", False):
                candidates.append((email, info.get("expiring", False)))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    def get_satellite_idle_worker(self, type: str = "tts") -> str | None:
        candidates = []
        for email in self.workers_by_type.get(type, []):
            info = self.worker_info.get(email)
            if info and info.get("status") == "IDLE" and not info.get("is_local", False):
                candidates.append((email, info.get("expiring", False)))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    def get_idle_worker(self, type: str = "tts") -> str | None:
        local = self.get_local_idle_worker(type)
        if local:
            return local
        return self.get_satellite_idle_worker(type)

    def get_active_count_by_type(self, type: str = "tts") -> int:
        return len(self.workers_by_type.get(type, []))

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

                    # Check last pong — if > 25s stale, mark dead
                    last_pong = info.get("last_pong", 0)
                    if last_pong and (now - last_pong) > 25:
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

                    # Mark account OFFLINE in DB and reset tasks
                    try:
                        async with async_session() as db:
                            res = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
                            acc = res.scalar_one_or_none()
                            if acc:
                                acc.status = "OFFLINE"
                                acc.worker_session_id = None
                                acc.runtime_status = None
                                acc.colab_pid = None
                                acc.current_task_id = None
                                acc.idle_since = None
                                acc.assigned_node_id = None

                                task_ids = await _requeue_processing_tasks(db, acc.id)
                                await db.commit()

                                for tid in task_ids:
                                    ev = _pending_direct_events.pop(tid, None)
                                    if ev:
                                        ev.set()
                    except Exception as e:
                        logger.error("Dead worker cleanup error: %s", e)

                    await broadcast_to_dashboard({"event": "worker_disconnected", "email": email, "reason": "heartbeat_timeout"})

        except asyncio.CancelledError:
            pass


manager = ConnectionManager()
