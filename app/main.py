"""FastAPI application entry point for Clone TTS."""

import sys
import asyncio

import logging
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path as _Path


from app.config import HOST, PORT, STATIC_DIR, CLOUDFLARED_ENABLED
from app.database import init_db
from app.routes import accounts, voices, tasks, ws, tts, health, auth

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_tunnel_process: subprocess.Popen | None = None


def _start_cloudflare_tunnel_sync():
    """Start cloudflared via subprocess.Popen (blocking, runs in a thread).

    This runs in a daemon thread so it does not block the event loop.
    """
    global _tunnel_process

    import shutil
    cf_bin = shutil.which("cloudflared") or str(_Path.home() / ".local" / "bin" / "cloudflared")
    if not _Path(cf_bin).exists():
        cf_bin = "cloudflared"

    try:
        proc = subprocess.Popen(
            [cf_bin, "tunnel", "--url", f"http://localhost:{PORT}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _tunnel_process = proc

        for line in proc.stdout:
            if "trycloudflare.com" in line:
                for word in line.split():
                    if "trycloudflare.com" in word:
                        url = word.strip()
                        if "https://" in url:
                            logger.info("☁️  Cloudflare Tunnel URL: %s", url)
                            import app.config as config
                            config.SERVER_URL = url
                            # Keep reading stdout so cloudflared doesn't hang
                            # (read until EOF, discarding output)
                            for _ in proc.stdout:
                                pass
                            return
        # If we exhaust stdout without finding URL, proc likely failed
        logger.error("Cloudflare tunnel exited without producing a URL (return code: %d)", proc.poll())
    except FileNotFoundError:
        logger.warning("cloudflared not found. Install it or disable CLOUDFLARED_ENABLED.")
    except Exception as exc:
        logger.error("Failed to start Cloudflare tunnel: %s", exc)



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Startup
    from app.lifecycle.reconciler import startup_cleanup_processes, reconcile_database_on_startup
    await startup_cleanup_processes()

    logger.info("Initializing database...")
    await init_db()
    logger.info("Database ready.")

    await reconcile_database_on_startup()

    if CLOUDFLARED_ENABLED:
        import threading
        threading.Thread(target=_start_cloudflare_tunnel_sync, daemon=True).start()

    # Start background maintenance loop
    from app.routes.ws import _maintenance_loop
    asyncio.create_task(_maintenance_loop())
    logger.info("Maintenance background loop started.")

    # Auto-pickup: Start a worker immediately if enabled
    from app.config import AUTO_PICKUP_ENABLED
    if AUTO_PICKUP_ENABLED:
        logger.info("Auto-pickup enabled. Waiting for Cloudflare tunnel before starting initial worker...")
        asyncio.create_task(_delayed_auto_pickup())

    yield

    # Shutdown
    p = _tunnel_process
    if p and p.poll() is None:
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            pass

    # Dispose database engine to close pool connections
    from app.database import engine
    await engine.dispose()
    logger.info("Database engine connections closed.")

    logger.info("Server shutting down.")


async def _delayed_auto_pickup():
    """Delay auto-pickup until Cloudflare tunnel is ready (max 120s)."""
    from app.config import SERVER_URL, CLOUDFLARED_ENABLED
    for i in range(24):
        if not CLOUDFLARED_ENABLED:
            break
        if "localhost" not in SERVER_URL and "127.0.0.1" not in SERVER_URL:
            logger.info("Cloudflare tunnel ready: %s", SERVER_URL)
            break
        await asyncio.sleep(5)
    else:
        logger.warning("Cloudflare tunnel not ready after 120s, proceeding with %s", SERVER_URL)
    from app.routes.ws import _try_auto_rotate
    await _try_auto_rotate()



app = FastAPI(title="Clone TTS", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "message": exc.errors()},
    )

@app.get("/api/ping")
async def ping():
    return {"status": "ok"}

# Register routers
app.include_router(accounts.router)
app.include_router(voices.router)
app.include_router(tasks.router)
app.include_router(ws.router)
app.include_router(tts.router)
app.include_router(health.router)
app.include_router(auth.router)

# Serve static files (admin dashboard at /admin/)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    config = uvicorn.Config("app.main:app", host=HOST, port=PORT, reload=False)
    server = uvicorn.Server(config)
    server.run()
