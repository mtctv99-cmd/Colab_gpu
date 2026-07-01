#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="${VENV_DIR:-.venv}"
PORT="${PORT:-8090}"
HOST="${HOST:-0.0.0.0}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERR]${NC}  $1"; }

info "=== TTS Dubbing Backend ==="
echo ""

# ── Python ──────────────────────────────────────────────
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    err "Python not found. Install Python 3.12+"
    exit 1
fi

PYVER=$("$PYTHON" --version 2>&1 | grep -oP '\d+\.\d+')
info "Python: $("$PYTHON" --version 2>&1) ($("$PYTHON" -c 'import sys; print(sys.executable)'))"

MAJOR=$(echo "$PYVER" | cut -d. -f1)
MINOR=$(echo "$PYVER" | cut -d. -f2)
if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 10 ]; }; then
    err "Python 3.10+ required, found $PYVER"
    exit 1
fi
ok "Python version OK"

# ── Dependencies ────────────────────────────────────────
info "Installing Python dependencies..."
"$PYTHON" -m pip install --quiet --upgrade pip setuptools wheel 2>/dev/null || true
"$PYTHON" -m pip install --quiet -r requirements.txt 2>/dev/null || warn "pip install failed (try: pip install -r requirements.txt)"
ok "Python dependencies installed"

# ── Cleanup old processes ───────────────────────────────
info "Cleaning up old processes..."

# Kill old uvicorn / run.py on port
if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
    OLD_PID=$(ss -tlnp 2>/dev/null | grep ":$PORT " | grep -oP 'pid=\K\d+' | head -1)
    if [ -n "$OLD_PID" ]; then
        warn "Port $PORT in use (PID=$OLD_PID). Killing SIGTERM..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 2
        if kill -0 "$OLD_PID" 2>/dev/null; then
            warn "SIGTERM failed, sending SIGKILL..."
            kill -9 "$OLD_PID" 2>/dev/null || true
            sleep 1
        fi
    fi
fi





ok "Port $PORT is free"

# ── Token refresh ──────────────────────────────────────
info "Refreshing Google OAuth tokens..."
python3 << 'PYEOF' 2>/dev/null || true
import json, os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
td = os.path.expanduser("~/.config/colab-cli")
ok = 0
for fn in sorted(os.listdir(td)):
    if not fn.startswith("token_") or not fn.endswith(".json"): continue
    fp = os.path.join(td, fn)
    try:
        creds = Credentials.from_authorized_user_file(fp)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
            data = json.load(open(fp))
            data["token"] = creds.token
            data["expiry"] = creds.expiry.isoformat()
            with open(fp, "w") as f: json.dump(data, f, indent=2)
            ok += 1
        elif creds.valid:
            ok += 1
    except: pass
if ok: print(f"  {ok} token(s) refreshed/valid")
PYEOF

# ── Frontend Docker ────────────────────────────────────
if command -v docker &>/dev/null; then
    FRONTEND_RUNNING=$(docker ps --filter "name=tts" --format "{{.Names}}" 2>/dev/null | head -1)
    if [ -z "$FRONTEND_RUNNING" ]; then
        info "Starting frontend Docker..."
        docker compose up -d 2>/dev/null && ok "Frontend started on :3355" || warn "Frontend Docker failed (check docker compose)"
    else
        ok "Frontend already running: $FRONTEND_RUNNING"
    fi
fi



# ── Start ──────────────────────────────────────────────
info "Starting backend on $HOST:$PORT ..."
echo ""

export PORT HOST JWT_SECRET_KEY LLM_WORKER_ENABLED=0
export PYTHONUNBUFFERED=1 RELOAD=1
exec python3 -u run.py --reload
