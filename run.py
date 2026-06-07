import asyncio
import sys
import uvicorn

from app.config import settings

if sys.platform == "win32":
    # Force ProactorEventLoop để hỗ trợ subprocess (cloudflared) trên Windows
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
