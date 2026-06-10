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


from app.config import HOST, PORT, STATIC_DIR, CLOUDFLARED_ENABLED, GOOGLE_CLIENT_ID
from app.database import init_db
from app.routes import accounts, voices, tasks, ws, tts, health, auth, google_auth

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_tunnel_process = None


async def _start_cloudflare_tunnel():
    """Start cloudflared to create a public HTTPS URL for the local server."""
    global _tunnel_process
    try:
        _tunnel_process = await asyncio.create_subprocess_exec(
            "cloudflared", "tunnel", "--url", f"http://localhost:{PORT}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        
        # Read the tunnel URL asynchronously from stdout
        async for line in _tunnel_process.stdout:  # type: ignore[union-attr]
            line_str = line.decode().strip()
            if "trycloudflare.com" in line_str:
                # Find the URL containing trycloudflare.com
                for word in line_str.split():
                    if "trycloudflare.com" in word:
                        # Clean up protocols (remove console color codes if any)
                        url = word.strip()
                        if "https://" in url:
                            logger.info("☁️  Cloudflare Tunnel URL: %s", url)
                            import app.config as config
                            config.SERVER_URL = url
                            return
    except FileNotFoundError:
        logger.warning("cloudflared not found. Install it or disable CLOUDFLARED_ENABLED.")
    except Exception as exc:
        logger.error("Failed to start Cloudflare tunnel: %s", exc)



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Startup
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

    # Reset any tasks stuck in PROCESSING state to PENDING
    logger.info("Cleaning up orphan tasks...")
    try:
        from sqlalchemy import update
        from app.database import async_session
        from app.models import Task
        async with async_session() as db:
            await db.execute(
                update(Task)
                .where(Task.status == "PROCESSING")
                .values(status="PENDING", worker_id=None)
            )
            await db.commit()
        logger.info("Orphan tasks cleaned up successfully.")
    except Exception as e:
        logger.error("Failed to clean up orphan tasks: %s", e)

    if CLOUDFLARED_ENABLED:
        asyncio.create_task(_start_cloudflare_tunnel())

    # Start background maintenance loop
    from app.routes.ws import _maintenance_loop, _try_auto_rotate
    asyncio.create_task(_maintenance_loop())
    logger.info("Maintenance background loop started.")

    # Auto-pickup: Start a worker immediately if enabled
    from app.config import AUTO_PICKUP_ENABLED
    if AUTO_PICKUP_ENABLED:
        logger.info("Auto-pickup enabled. Starting initial worker...")
        asyncio.create_task(_try_auto_rotate())

    yield

    # Shutdown
    if _tunnel_process:
        _tunnel_process.terminate()
        await _tunnel_process.wait()
    logger.info("Server shutting down.")



app = FastAPI(title="Clone TTS", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# Register routers
app.include_router(accounts.router)
app.include_router(voices.router)
app.include_router(tasks.router)
app.include_router(ws.router)
app.include_router(tts.router)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(google_auth.router)

@app.get("/api/config")
async def get_config():
    return {"google_client_id": GOOGLE_CLIENT_ID}


# HTML page routes (extension-less fallback to .html)
from pathlib import Path as _Path
from fastapi.responses import FileResponse

_HTML_DIR = STATIC_DIR
_PAGE_FILES = {"/login": "login.html", "/signup": "signup.html", "/dashboard": "dashboard.html"}

for _route, _file in _PAGE_FILES.items():
    _path_obj = _HTML_DIR / _file
    if _path_obj.exists():
        app.add_api_route(_route, lambda f=_path_obj: FileResponse(str(f), headers={"Cache-Control": "no-cache, no-store, must-revalidate"}), methods=["GET"], include_in_schema=False)

# Serve static files (admin dashboard at /admin/, landing at /)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)

