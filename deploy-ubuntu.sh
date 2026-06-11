#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# Clone TTS — Ubuntu Production Deployment Script
# ═══════════════════════════════════════════════════════════════
# Usage:
#   sudo bash deploy-ubuntu.sh                # full deploy
#   sudo bash deploy-ubuntu.sh --update        # pull + restart only
#   sudo bash deploy-ubuntu.sh --uninstall     # remove service + data
# ═══════════════════════════════════════════════════════════════

APP_NAME="clonetts"
APP_DIR="/opt/${APP_NAME}"
APP_USER="www-data"
FRONTEND_PORT=3000
API_PORT=8001
BRANCH="main"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERR]${NC} $1"; exit 1; }

# ── Parse args ──────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    echo "Stopping and removing $APP_NAME service..."
    systemctl stop "$APP_NAME" 2>/dev/null || true
    systemctl disable "$APP_NAME" 2>/dev/null || true
    rm -f "/etc/systemd/system/${APP_NAME}.service"
    systemctl daemon-reload
    rm -rf "$APP_DIR"
    info "Removed $APP_NAME. Data directory preserved at ${APP_DIR}/data (if exists)."
    info "To fully remove data: rm -rf ${APP_DIR}/data"
    exit 0
fi

UPDATE_MODE=false
if [[ "${1:-}" == "--update" ]]; then
    UPDATE_MODE=true
    info "Update mode — pulling latest code and restarting..."
fi

# ── Prerequisites ───────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "Run as root: sudo bash deploy-ubuntu.sh"
fi

if ! $UPDATE_MODE; then
    info "Installing system dependencies..."
    apt update -qq
    apt install -y -qq \
        curl git python3 python3-venv python3-pip \
        nodejs npm \
        libgtk-3-0 libnss3 libxcb1 libatk1.0-0 \
        libcups2 libdrm2 libxcomposite1 libxdamage1 \
        libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
        cloudflared

    # Node.js 20+ if repo version too old
    if ! node --version 2>/dev/null | grep -q "v2[0-9]\|v3[0-9]"; then
        warn "Node.js too old. Installing Node 20 LTS..."
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
        apt install -y nodejs
    fi
fi

# ── Clone / Pull ────────────────────────────────────────────
if $UPDATE_MODE && [[ -d "$APP_DIR" ]]; then
    info "Pulling latest from $BRANCH..."
    cd "$APP_DIR"
    git pull origin "$BRANCH"
else
    if [[ -d "$APP_DIR" ]]; then
        warn "$APP_DIR already exists. Pulling updates..."
        cd "$APP_DIR"
        git pull origin "$BRANCH"
    else
        info "Cloning repository..."
        read -rp "GitHub repo (user/repo): " REPO_URL
        if [[ -z "$REPO_URL" ]]; then
            REPO_URL="mtctv99-cmd/Colab_gpu"  # fallback
        fi
        git clone --branch "$BRANCH" "https://github.com/${REPO_URL}.git" "$APP_DIR"
        cd "$APP_DIR"
    fi
fi

cd "$APP_DIR"

# ── Python venv + deps ─────────────────────────────────────
info "Setting up Python virtual environment..."
if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q --upgrade pip setuptools wheel
pip install -q -r requirements.txt

info "Installing Playwright (Chromium)..."
playwright install chromium 2>/dev/null || warn "Playwright install failed — check system deps above"

# ── Frontend ────────────────────────────────────────────────
info "Building frontend..."
cd frontend
npm install --silent
npm run build
cd "$APP_DIR"

# ── Environment ─────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
    info "Creating .env from template..."
    cat > .env << 'EOF'
# ==========================================
# Clone TTS — Production Config (Ubuntu)
# ==========================================
GITHUB_USER=your-github-username
GITHUB_REPO=your-repo-name
GITHUB_BRANCH=main
COLAB_NOTEBOOK_PATH=colab/worker.ipynb
CLOUDFLARED_ENABLED=1
BROWSER_VISIBLE=1
AUTO_START_WORKER_ON_STARTUP=1
PORT=8001
HOST=0.0.0.0
GOOGLE_CLIENT_ID=
JWT_SECRET_KEY=
WEBHOOK_SECRET=
EOF
    warn "=== EDIT .env ==="
    warn "  vi $APP_DIR/.env"
    warn "  Set: GITHUB_USER, GITHUB_REPO, JWT_SECRET_KEY (64 hex chars)"
    warn "  Run: openssl rand -hex 32   (to generate JWT_SECRET_KEY)"
    err "Edit .env first, then re-run this script"
fi

# Generate JWT key if empty
if grep -q "JWT_SECRET_KEY=$" .env; then
    NEW_KEY=$(openssl rand -hex 32)
    sed -i "s/JWT_SECRET_KEY=$/JWT_SECRET_KEY=$NEW_KEY/" .env
    info "Generated JWT_SECRET_KEY"
fi

# Generate WEBHOOK_SECRET if empty
if grep -q "WEBHOOK_SECRET=$" .env; then
    NEW_WH=$(openssl rand -hex 16)
    sed -i "s/WEBHOOK_SECRET=$/WEBHOOK_SECRET=$NEW_WH/" .env
    info "Generated WEBHOOK_SECRET"
fi

# ── systemd: API server ────────────────────────────────────
info "Installing systemd service..."
cat > "/etc/systemd/system/${APP_NAME}.service" << SERVICEEOF
[Unit]
Description=Clone TTS API Server
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$APP_DIR/.venv/bin:/usr/local/bin:/usr/bin
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $API_PORT
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
SERVICEEOF

# ── systemd: Frontend (Next.js) ─────────────────────────────
cat > "/etc/systemd/system/${APP_NAME}-frontend.service" << FRONTEOF
[Unit]
Description=Clone TTS Frontend (Next.js)
After=network.target ${APP_NAME}.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/frontend
Environment=NODE_ENV=production
Environment=NEXT_TELEMETRY_DISABLED=1
ExecStart=/usr/bin/node $APP_DIR/frontend/node_modules/.bin/next start -p $FRONTEND_PORT
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
FRONTEOF

# ── Permissions ────────────────────────────────────────────
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chmod 755 "$APP_DIR"
chmod 640 "$APP_DIR/.env"

# ── Enable + Start ─────────────────────────────────────────
systemctl daemon-reload
systemctl enable "$APP_NAME" "${APP_NAME}-frontend"
systemctl restart "$APP_NAME"
info "Waiting for API to be ready..."
for i in $(seq 1 15); do
    if curl -s "http://localhost:${API_PORT}/api/health/" >/dev/null 2>&1; then
        info "API ready on http://localhost:${API_PORT}"
        break
    fi
    sleep 2
done

systemctl restart "${APP_NAME}-frontend"
info "Frontend starting on http://localhost:${FRONTEND_PORT}"

# ── Status ─────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Clone TTS Deployment Complete${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo "  API:         http://localhost:${API_PORT}"
echo "  API Health:  http://localhost:${API_PORT}/api/health/"
echo "  Frontend:    http://localhost:${FRONTEND_PORT}"
echo "  Admin:       http://localhost:${FRONTEND_PORT}/admin"
echo "  Tunnel:      watch 'journalctl -u ${APP_NAME} -f | grep trycloudflare'"
echo ""
echo "  Logs:"
echo "    journalctl -u ${APP_NAME} -f          # API logs"
echo "    journalctl -u ${APP_NAME}-frontend -f # Frontend logs"
echo ""
echo "  Commands:"
echo "    systemctl restart ${APP_NAME}         # restart API"
echo "    systemctl restart ${APP_NAME}-frontend"
echo "    sudo bash deploy-ubuntu.sh --update   # pull + restart"
echo ""
