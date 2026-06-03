"""FastAPI application entry point for Colab Worker TTS."""

import sys
import asyncio

import logging
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


from app.config import HOST, PORT, STATIC_DIR, CLOUDFLARED_ENABLED
from app.database import init_db
from app.routes import accounts, voices, tasks, ws

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

    yield

    # Shutdown
    if _tunnel_process:
        _tunnel_process.terminate()
        await _tunnel_process.wait()
    logger.info("Server shutting down.")



app = FastAPI(title="Colab Worker TTS", version="1.0.0", lifespan=lifespan)

# Register routers
app.include_router(accounts.router)
app.include_router(voices.router)
app.include_router(tasks.router)
app.include_router(ws.router)


# Serve static files (dashboard)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
