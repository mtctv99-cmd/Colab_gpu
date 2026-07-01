"""FastAPI application entry point for TTS Dubbing."""

import asyncio
import os
import re
import time
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware



from app.config import HOST, PORT, STATIC_DIR
from app.database import init_db
from app.routes import accounts, voices, tasks, ws, tts, health, auth, node, usage

from pathlib import Path
from logging.handlers import RotatingFileHandler
_root_log_file = Path(__file__).resolve().parent.parent / "backend.log"
_file_handler = RotatingFileHandler(str(_root_log_file), maxBytes=50*1024*1024, backupCount=5, encoding='utf-8')
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[
    logging.StreamHandler(),
    _file_handler,
])
logger = logging.getLogger(__name__)
logger.info("Logging to %s", _root_log_file)



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("Cleaning up zombie browser processes...")
    try:
        from app.automation.play_runner import cleanup_zombie_browsers
        killed = await cleanup_zombie_browsers(kill_active=True)
        if killed > 0:
            logger.info("Cleaned up %d leftover browser processes.", killed)
    except Exception as exc:
        logger.warning("Failed to run startup browser cleanup: %s", exc)

    logger.info("Initializing database...")
    await init_db()
    logger.info("Database ready.")

    # Reset any tasks stuck in PROCESSING state to PENDING, and all accounts to OFFLINE
    logger.info("Cleaning up database states...")
    try:
        from sqlalchemy import update
        from app.database import async_session
        from app.models import Task, GoogleAccount
        async with async_session() as db:
            await db.execute(
                update(Task)
                .where(Task.status == "PROCESSING")
                .values(status="PENDING", worker_id=None, worker_session_id=None)
            )
            await db.execute(
                update(GoogleAccount)
                .values(status="OFFLINE", worker_session_id=None, runtime_status=None, current_task_id=None, idle_since=None)
            )
            await db.commit()
        logger.info("Database states cleaned up successfully.")
    except Exception as e:
        logger.error("Failed to clean up database states: %s", e)

    # PUBLIC_SERVER_URL: dùng domain từ env, fallback localhost
    _public_url = os.environ.get("PUBLIC_SERVER_URL", "")
    if not _public_url:
        import socket
        _host_ip = socket.gethostbyname(socket.gethostname())
        _public_url = f"http://{_host_ip}:{PORT}" if not _host_ip.startswith("127.") else f"http://localhost:{PORT}"
    os.environ["PUBLIC_SERVER_URL"] = _public_url
    logger.info("PUBLIC_SERVER_URL = %s", _public_url)

    # Start background loops
    from app.routes.ws import _maintenance_loop, _worker_lifecycle_loop, _try_auto_rotate
    asyncio.create_task(_maintenance_loop())
    asyncio.create_task(_worker_lifecycle_loop())
    logger.info("Maintenance loops started.")

    from app.config import AUTO_PICKUP_ENABLED
    if AUTO_PICKUP_ENABLED:
        logger.info("Auto-pickup enabled. Starting initial worker...")
        asyncio.create_task(_try_auto_rotate())

    yield

    # Shutdown: clean up any active/zombie browser processes
    logger.info("Cleaning up browser processes on shutdown...")
    try:
        from app.automation.play_runner import cleanup_zombie_browsers
        await cleanup_zombie_browsers(kill_active=True)
    except Exception as exc:
        logger.warning("Failed browser cleanup on shutdown: %s", exc)

    from app.database import engine
    await engine.dispose()
    logger.info("Server shutting down.")



app = FastAPI(title="TTS Dubbing", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.[0-9]+\.[0-9]+)(:[0-9]+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


# Rate limiter: per-IP, 100 requests/minute with bounded cleanup
import time as _time
from collections import OrderedDict
_rate_limit_store: OrderedDict[str, list[float]] = OrderedDict()
_last_cleanup: float = 0.0

async def _check_rate_limit_ip(request: Request) -> bool:
    global _last_cleanup
    # Use X-Forwarded-For from trusted proxy (Cloudflare tunnel); fallback to client.host
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"

    if (ip in ("127.0.0.1", "localhost", "::1")
        or ip.startswith("172.")
        or ip.startswith("192.168.")
        or ip.startswith("10.")):
        return True

    now = _time.time()
    window = 60.0
    max_req = 100

    # Periodic cleanup: every 120s remove entries with empty lists
    if now - _last_cleanup > 120.0:
        _last_cleanup = now
        empty_keys = [k for k, v in _rate_limit_store.items() if not v]
        for k in empty_keys:
            del _rate_limit_store[k]

    if ip in _rate_limit_store:
        _rate_limit_store[ip] = [t for t in _rate_limit_store[ip] if now - t < window]
    else:
        _rate_limit_store[ip] = []
    if len(_rate_limit_store[ip]) >= max_req:
        return False
    _rate_limit_store[ip].append(now)
    return True

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        ok = await _check_rate_limit_ip(request)
        if not ok:
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "message": "Quá nhiều yêu cầu. Thử lại sau 60 giây."},
            )
    return await call_next(request)

@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    _404_path = STATIC_DIR / "404.html"
    if _404_path.exists():
        return HTMLResponse(_404_path.read_text(encoding="utf-8"), status_code=404)
    return JSONResponse({"error": "not_found", "message": "Not found"}, status_code=404)

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        error = detail.get("error", "http_error")
        message = detail.get("message", str(detail))
    else:
        error = "http_error"
        message = str(detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error, "message": message},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # exc.errors() can contain non-JSON-serializable objects (ValueError etc.)
    # Convert to safe dicts before serializing
    safe_errors = []
    for err in exc.errors():
        safe_errors.append({
            "type": str(err.get("type", "")),
            "loc": [str(l) for l in err.get("loc", [])],
            "msg": str(err.get("msg", "")),
        })
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "message": safe_errors},
    )

@app.get("/api/ping")
async def ping():
    return {"status": "ok"}

@app.get("/api/config")
async def config():
    from app.config import MAX_CONCURRENT_WORKERS
    return {
        "public_url": os.environ.get("PUBLIC_SERVER_URL", f"http://localhost:{PORT}"),
        "max_workers": MAX_CONCURRENT_WORKERS,
    }

# Register routers
app.include_router(accounts.router)
app.include_router(voices.router)
app.include_router(tasks.router)
app.include_router(tasks.user_tasks_router)
app.include_router(ws.router)
app.include_router(tts.router)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(usage.router)
app.include_router(node.router)

# ── Serve built frontend ─────────────────────────────────────
# Frontend build paths (try multiple locations for Docker vs local)
_frontend_candidates = [
    os.path.join(os.path.dirname(__file__), "..", "frontend", ".next", "standalone"),  # local dev
    os.path.join(os.path.dirname(__file__), "..", "frontend", ".next", "standalone", "frontend", ".next", "standalone"),  # Docker nested
    "/app/frontend/.next/standalone",  # Docker explicit
]
_frontend_dir = None
for _p in _frontend_candidates:
    if os.path.exists(os.path.join(_p, ".next", "server", "app", "index.html")):
        _frontend_dir = _p
        break

if _frontend_dir:
    _static_candidates = [
        os.path.join(_frontend_dir, ".next", "static"),               # standalone output
        os.path.join(_frontend_dir, "..", "static"),                  # actual next build output
        "/app/frontend/.next/static",                                  # Docker
    ]
    _static_dir = None
    for _sp in _static_candidates:
        if os.path.exists(_sp):
            _static_dir = _sp
            break
    if _static_dir:
        app.mount("/_next/static", StaticFiles(directory=_static_dir), name="next_static")
        logger.info("Serving frontend static from %s", _static_dir)
    else:
        logger.warning("Frontend static dir not found (tried %s)", _static_candidates)
else:
    logger.warning("No frontend build found; API-only mode. Run: cd frontend && npx next build")

@app.get("/{path:path}")
async def serve_frontend(path: str):
    # Skip API routes
    if path.startswith("api/") or path.startswith("ws/"):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    if _frontend_dir is None:
        return JSONResponse(status_code=404, content={"detail": "Frontend not built. Run: cd frontend && npx next build"})

    _server_app = os.path.join(_frontend_dir, ".next", "server", "app")

    # Try exact path match first
    _html_path = path.strip("/") or "index"
    _file = os.path.join(_server_app, f"{_html_path}.html")
    if os.path.exists(_file):
        return FileResponse(_file, media_type="text/html")

    # For nested routes (e.g. /admin/apikeys), try index.html in subdir
    _dir_file = os.path.join(_server_app, _html_path, "index.html")
    if os.path.exists(_dir_file):
        return FileResponse(_dir_file, media_type="text/html")

    # Fallback to index.html for client-side routing
    _index = os.path.join(_server_app, "index.html")
    if os.path.exists(_index):
        return FileResponse(_index, media_type="text/html")

    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404, content={"detail": "Frontend not built. Run: cd frontend && npx next build"})


if __name__ == "__main__":
    import uvicorn
    config = uvicorn.Config("app.main:app", host=HOST, port=PORT, reload=False)
    server = uvicorn.Server(config)
    server.run()
