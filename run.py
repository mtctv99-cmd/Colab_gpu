import asyncio
import sys
import uvicorn

if sys.platform == "win32":
    # Force ProactorEventLoop on Windows to support subprocesses (required by Playwright and cloudflared)
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=False)
