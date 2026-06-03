"""WebSocket endpoint and ConnectionManager for Colab worker communication."""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update

from app.database import async_session
from app.models import GoogleAccount, Task
from app.config import QUOTA_RESET_HOURS
from app.automation import play_runner

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Dashboard WebSocket (receives broadcasts from worker events) ──
_dashboard_clients: list[WebSocket] = []

# global registry for synchronous task events to bypass circular import
_pending_direct_events: dict[str, asyncio.Event] = {}


@router.websocket("/ws/dashboard")
async def websocket_dashboard(ws: WebSocket):
    await ws.accept()
    _dashboard_clients.append(ws)
    try:
        while True:
            # Keep connection alive; client doesn't send anything
            await ws.receive_text()
    except WebSocketDisconnect:
        _dashboard_clients.remove(ws)
    except Exception:
        if ws in _dashboard_clients:
            _dashboard_clients.remove(ws)


async def broadcast_to_dashboard(msg: dict):
    """Send a message to all connected dashboard clients."""
    dead = []
    for client in _dashboard_clients:
        try:
            await client.send_json(msg)
        except Exception:
            dead.append(client)
    for d in dead:
        _dashboard_clients.remove(d)


class ConnectionManager:
    """Manages active WebSocket connections from Colab workers."""

    def __init__(self):
        self.active: dict[str, WebSocket] = {}  # email -> websocket
        self.worker_info: dict[str, dict[str, Any]] = {}  # email -> metadata
        self.heartbeat_task: asyncio.Task | None = None

    async def connect(self, ws: WebSocket, email: str, gpu: str = ""):
        self.active[email] = ws
        self.worker_info[email] = {"gpu": gpu, "connected_at": datetime.now(timezone.utc)}
        logger.info("Worker connected: %s (GPU: %s)", email, gpu)
        
        # Start heartbeat loop if not already running
        if self.heartbeat_task is None or self.heartbeat_task.done():
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def disconnect(self, email: str):
        self.active.pop(email, None)
        self.worker_info.pop(email, None)
        logger.info("Worker disconnected: %s", email)

    async def send_task(self, email: str, task_id: str, text: str, voice_api_url: str, language: str | None = None):
        ws = self.active.get(email)
        if ws is None:
            return False
        await ws.send_json({
            "action": "run_tts",
            "task_id": task_id,
            "text": text,
            "voice_api_url": voice_api_url,
            "language": language,
        })
        return True

    async def broadcast_status(self, message: dict):
        for ws in self.active.values():
            try:
                await ws.send_json(message)
            except Exception:
                pass
        await broadcast_to_dashboard(message)

    def get_idle_worker(self) -> str | None:
        for email, info in self.worker_info.items():
            if info.get("status", "IDLE") == "IDLE":
                return email
        return None

    async def _heartbeat_loop(self):
        """Periodically ping all active workers to keep connections alive and detect dead sockets."""
        logger.info("Starting WebSocket heartbeat loop...")
        try:
            while True:
                await asyncio.sleep(40)  # Ping every 40 seconds
                if not self.active:
                    break
                
                emails = list(self.active.keys())
                for email in emails:
                    ws = self.active.get(email)
                    if ws:
                        try:
                            await ws.send_json({"action": "ping"})
                        except Exception:
                            logger.warning("Heartbeat failed for worker: %s. Disconnecting...", email)
                            self.disconnect(email)
                            await self.broadcast_status({"event": "worker_disconnected", "email": email})
                            
                            # Cập nhật trạng thái database
                            try:
                                async with async_session() as db:
                                    result = await db.execute(
                                        select(GoogleAccount).where(GoogleAccount.email == email)
                                    )
                                    account = result.scalar_one_or_none()
                                    if account and account.status in ("ACTIVE", "CONNECTING"):
                                        account.status = "OFFLINE"
                                        await db.commit()
                            except Exception as e:
                                logger.error("Failed to update status for disconnected worker %s in heartbeat: %s", email, e)
            
        except asyncio.CancelledError:
            logger.info("Heartbeat loop cancelled.")
        finally:
            logger.info("WebSocket heartbeat loop stopped.")
            self.heartbeat_task = None


manager = ConnectionManager()


# ── WebSocket endpoint ────────────────────────────────────────
@router.websocket("/ws/worker")
async def websocket_worker(ws: WebSocket):
    await ws.accept()
    email = None
    try:
        # First message must be a register action
        raw = await ws.receive_json()
        if raw.get("action") != "register":
            await ws.close(code=4001, reason="First message must be 'register'")
            return

        email = raw["email"]
        gpu = raw.get("gpu", "unknown")
        await manager.connect(ws, email, gpu)
        manager.worker_info[email]["status"] = "IDLE"

        # Update DB
        async with async_session() as db:
            result = await db.execute(
                select(GoogleAccount).where(GoogleAccount.email == email)
            )
            account = result.scalar_one_or_none()
            if account:
                account.status = "ACTIVE"
                account.last_active = datetime.now(timezone.utc)
                await db.commit()

        # Notify dashboard of new worker
        await manager.broadcast_status({"event": "worker_connected", "email": email, "gpu": gpu})

        # Listen for messages
        while True:
            data = await ws.receive_json()
            action = data.get("action")

            if action == "status":
                new_status = data.get("status", "IDLE")
                manager.worker_info[email]["status"] = new_status
                await _handle_status(email, new_status)

            elif action == "task_completed":
                task_id = data.get("task_id")
                await _handle_task_completed(task_id)

            elif action == "task_failed":
                task_id = data.get("task_id")
                error = data.get("error", "Unknown error")
                await _handle_task_failed(task_id, error)

            elif action == "ping":
                await ws.send_json({"action": "pong"})

            elif action == "pong":
                await _handle_pong(email)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
    finally:
        if email:
            manager.disconnect(email)
            
            # Update database status to OFFLINE on disconnection (except if COOLDOWN)
            # Đồng thời đánh dấu thất bại cho các task đang PROCESSING bởi worker này và giải phóng event direct
            try:
                async with async_session() as db:
                    result = await db.execute(
                        select(GoogleAccount).where(GoogleAccount.email == email)
                    )
                    account = result.scalar_one_or_none()
                    if account:
                        if account.status in ("ACTIVE", "CONNECTING"):
                            account.status = "OFFLINE"
                        
                        # Reset/Fail các task đang processing
                        res_tasks = await db.execute(
                            select(Task).where(Task.worker_id == account.id, Task.status == "PROCESSING")
                        )
                        processing_tasks = res_tasks.scalars().all()
                        for pt in processing_tasks:
                            pt.status = "FAILED"
                            pt.error_message = "Worker disconnected abruptly."
                            pt.completed_at = datetime.now(timezone.utc)
                            
                            # Giải phóng event direct tts
                            event = _pending_direct_events.pop(pt.id, None)
                            if event:
                                event.set()
                                
                        await db.commit()
            except Exception as e:
                logger.error("Failed to handle disconnection for %s: %s", email, e)
                
            await manager.broadcast_status({"event": "worker_disconnected", "email": email})



async def _handle_pong(email: str):
    """Update last active timestamp when a pong is received."""
    async with async_session() as db:
        result = await db.execute(
            select(GoogleAccount).where(GoogleAccount.email == email)
        )
        account = result.scalar_one_or_none()
        if account:
            account.last_active = datetime.now(timezone.utc)
            await db.commit()



async def _try_dispatch_next_task(email: str):
    """Find the oldest PENDING task and dispatch it to this newly idle worker."""
    from app.routes.tasks import _dispatch_task
    from app.models import Task
    
    async with async_session() as db:
        result = await db.execute(
            select(Task)
            .where(Task.status == "PENDING")
            .order_by(Task.created_at.asc())
            .limit(1)
        )
        task = result.scalar_one_or_none()
        if task:
            logger.info("Found pending task %s in queue, auto-dispatching to worker %s", task.id, email)
            await _dispatch_task(task, email, db)



async def _handle_status(email: str, status: str):
    """Handle worker status updates."""
    async with async_session() as db:
        result = await db.execute(
            select(GoogleAccount).where(GoogleAccount.email == email)
        )
        account = result.scalar_one_or_none()
        if not account:
            return

        if status == "OUT_OF_QUOTA":
            account.status = "COOLDOWN"
            account.quota_reset_at = datetime.now(timezone.utc) + timedelta(hours=QUOTA_RESET_HOURS)

            # Reset tasks assigned to this worker back to PENDING
            await db.execute(
                update(Task)
                .where(Task.worker_id == account.id, Task.status == "PROCESSING")
                .values(status="PENDING", worker_id=None)
            )
            await db.commit()

            # Stop Playwright browser for this account
            try:
                await play_runner.stop_colab_worker(account.email)
            except Exception as exc:
                logger.warning("Failed to stop worker %s: %s", account.email, exc)

            # Auto-rotate to next OFFLINE account
            try:
                await _try_auto_rotate()
            except Exception as exc:
                logger.error("Auto-rotation failed: %s", exc)
        else:
            # Don't overwrite DB status — worker_info tracks BUSY/IDLE in memory
            account.last_active = datetime.now(timezone.utc)
            await db.commit()
            
            # Auto dispatch next pending task if worker becomes IDLE
            if status == "IDLE":
                asyncio.create_task(_try_dispatch_next_task(email))

    await manager.broadcast_status({"event": "worker_status", "email": email, "status": status})


async def _handle_task_completed(task_id: str):
    """Mark a task as completed."""
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if task:
            task.status = "COMPLETED"
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()
            
    # Giải phóng event nếu đây là direct request
    event = _pending_direct_events.pop(task_id, None)
    if event:
        event.set()
        
    await manager.broadcast_status({"event": "task_completed", "task_id": task_id})


async def _handle_task_failed(task_id: str, error: str):
    """Mark a task as failed."""
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if task:
            task.status = "FAILED"
            task.error_message = error
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()
            
    # Giải phóng event nếu đây là direct request
    event = _pending_direct_events.pop(task_id, None)
    if event:
        event.set()
        
    await manager.broadcast_status({"event": "task_failed", "task_id": task_id, "error": error})


# Concurrency lock for auto-rotation
_rotate_lock = asyncio.Lock()

async def _try_auto_rotate():
    """Find an OFFLINE account and start a new Colab worker. Loops if one fails."""
    from datetime import timedelta
    async with _rotate_lock:
        while True:
            async with async_session() as db:
                result = await db.execute(
                    select(GoogleAccount)
                    .where(GoogleAccount.status == "OFFLINE")
                    .limit(1)
                )
                next_account = result.scalar_one_or_none()
                if not next_account:
                    logger.info("No offline accounts available for rotation.")
                    return

                # Tạm thời set ACTIVE để giành quyền chạy
                next_account.status = "ACTIVE"
                next_account.last_active = datetime.now(timezone.utc)
                email = next_account.email
                await db.commit()

            try:
                import app.config as config
                logger.info("Attempting to auto-start worker for %s...", email)
                await play_runner.start_colab_worker(email, config.SERVER_URL)
                logger.info("Successfully auto-rotated to %s", email)
                return  # Thành công, thoát hàm
            except Exception as exc:
                # Nếu lỗi (ví dụ kẹt đăng nhập), set status thành COOLDOWN trong 1 giờ
                async with async_session() as db:
                    result = await db.execute(
                        select(GoogleAccount).where(GoogleAccount.email == email)
                    )
                    acc = result.scalar_one_or_none()
                    if acc:
                        acc.status = "COOLDOWN"
                        acc.quota_reset_at = datetime.now(timezone.utc) + timedelta(hours=1)
                    await db.commit()
                logger.error("Failed to start worker for %s, trying next available account: %s", email, exc)
                # Tiếp tục vòng lặp để thử tài khoản OFFLINE tiếp theo
