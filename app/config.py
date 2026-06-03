"""Application configuration management."""

import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROFILES_DIR = DATA_DIR / "profiles"
VOICES_DIR = DATA_DIR / "voices"
RESULTS_DIR = DATA_DIR / "results"
STATIC_DIR = BASE_DIR / "app" / "static"
COLAB_DIR = BASE_DIR / "colab"

# Ensure data directories exist
for d in [DATA_DIR, PROFILES_DIR, VOICES_DIR, RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Server settings
HOST = "0.0.0.0"
PORT = 8001
SERVER_URL = f"http://localhost:{PORT}"  # Will be dynamically updated if Cloudflare Tunnel is used

# Database
DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'db.sqlite3'}"

# Google Colab / GitHub settings
GITHUB_USER = os.getenv("GITHUB_USER", "mtctv99-cmd")
GITHUB_REPO = os.getenv("GITHUB_REPO", "Colab_tts")
COLAB_NOTEBOOK_PATH = "colab/worker.ipynb"

# Cloudflare Tunnel
CLOUDFLARED_ENABLED = True

# Worker settings
WORKER_KEEPALIVE_INTERVAL = 300  # 5 minutes in seconds
QUOTA_RESET_HOURS = 16
WORKER_TIMEOUT = 60  # seconds to wait for page load

