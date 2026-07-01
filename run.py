import os
import sys
import uvicorn

# Triệt để: không bao giờ hiển thị OAuth prompt khi chạy server
os.environ.setdefault("DISABLE_INTERACTIVE_AUTH", "1")

PORT = int(os.getenv("PORT", "8090"))

if __name__ == "__main__":
    # check reload from environment variable or command line
    reload = os.getenv("RELOAD", "0") == "1" or "--reload" in sys.argv
    config = uvicorn.Config("app.main:app", host="0.0.0.0", port=PORT, reload=reload)
    server = uvicorn.Server(config)
    server.run()
