import asyncio
import logging
import subprocess
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.database import init_db
from app.routes import tts, ws, tasks
from app.config import settings, RESULTS_DIR

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

_tunnel_process = None

async def _start_cloudflare_tunnel():
    """Tự động chạy cloudflared để lấy public URL."""
    global _tunnel_process
    try:
        # Chạy cloudflared tunnel
        _tunnel_process = await asyncio.create_subprocess_exec(
            "cloudflared", "tunnel", "--url", f"http://localhost:{settings.PORT}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        async for line in _tunnel_process.stdout:
            line_str = line.decode().strip()
            if "trycloudflare.com" in line_str:
                for word in line_str.split():
                    if "trycloudflare.com" in word:
                        url = word.strip()
                        if "https://" in url:
                            logger.info(f"☁️  Public Tunnel URL: {url}")
                            # Gán lại SERVER_URL để các route dùng
                            import app.config as config
                            config.settings.SERVER_URL = url
                            return
    except FileNotFoundError:
        logger.warning("cloudflared not found. Vui lòng cài đặt để dùng public URL.")
    except Exception as e:
        logger.error(f"Failed to start Cloudflare tunnel: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("TTS Colab Server starting up...")
    await init_db()

    if settings.CLOUDFLARED_ENABLED:
        asyncio.create_task(_start_cloudflare_tunnel())

    yield
    # Shutdown
    if _tunnel_process:
        _tunnel_process.terminate()
        await _tunnel_process.wait()
    logger.info("TTS Colab Server shutting down...")

app = FastAPI(
    title="TTS Colab Server",
    description="API for managing TTS tasks across Google Colab workers",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(tts.router, tags=["TTS"])
app.include_router(ws.router, tags=["WebSocket"])
app.include_router(tasks.router, tags=["Tasks"])

# Serve kết quả audio (tùy chọn)
app.mount("/results", StaticFiles(directory=str(RESULTS_DIR)), name="results")

@app.get("/")
async def root():
    return {
        "message": "TTS Server is running",
        "status": "ok",
        "public_url": settings.SERVER_URL
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
