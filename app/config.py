"""Application configuration management."""

import os
from pathlib import Path

# Load .env manually if it exists
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROFILES_DIR = DATA_DIR / "profiles"
VOICES_DIR = DATA_DIR / "voices"
RESULTS_DIR = DATA_DIR / "results"
STATIC_DIR = BASE_DIR / "app" / "static"

# Ensure data directories exist
for d in [DATA_DIR, PROFILES_DIR, VOICES_DIR, RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Server settings
HOST = "0.0.0.0"
PORT = 8090
SERVER_URL = f"http://localhost:{PORT}"
PUBLIC_SERVER_URL = os.getenv("PUBLIC_SERVER_URL", os.getenv("SERVER_URL", f"http://localhost:{PORT}"))

def get_public_server_url() -> str:
    """Return current public server URL (re-reads env for tunnel updates)."""
    return os.getenv("PUBLIC_SERVER_URL") or PUBLIC_SERVER_URL

# Database
# Safety: TESTING=1 env var is explicit. Never auto-detect via sys.argv.
# Production luôn dùng db.sqlite3. Test phải set TESTING=1.
import os as _os
_TESTING = _os.getenv("TESTING", "0") == "1"
if _TESTING:
    DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'db_test.sqlite3'}"
else:
    DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'db.sqlite3'}"

# Worker lifecycle settings (used by accounts/capacity endpoint for display)
KEEP_WARM_WORKERS = int(os.getenv("KEEP_WARM_WORKERS", "0"))
MAX_CONCURRENT_WORKERS = int(os.getenv("MAX_CONCURRENT_WORKERS", "5"))

# Worker settings
WORKER_KEEPALIVE_INTERVAL = 300  # 5 minutes in seconds
QUOTA_RESET_HOURS = 16
WORKER_TIMEOUT = 60  # seconds to wait for page load
WORKER_MAX_LIFETIME = 3.75 * 3600  # 3 hours 45 minutes in seconds
WORKER_HANDOVER_DELAY = 120  # seconds to wait for new worker ready
AUTO_PICKUP_ENABLED = True  # start worker automatically at server boot

# Notebook settings
COLAB_NOTEBOOK_PATH = "colab/worker.ipynb"
GITHUB_USER = os.getenv("GITHUB_USER", "your-github-username")
GITHUB_REPO = os.getenv("GITHUB_REPO", "your-repo-name")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

NODE_API_KEY = os.getenv("NODE_API_KEY", "")
if not NODE_API_KEY:
    if os.getenv("TESTING", "0") == "1":
        NODE_API_KEY = "test-node-key"
    else:
        NODE_API_KEY = "satellite-secret-key-123"
MULTI_VPS_MODE = os.getenv("MULTI_VPS_MODE", "0") == "1"


