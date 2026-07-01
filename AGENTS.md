# TTS Dubbing — Agent Guide

## Quick start
- `run.bat` (Windows): Installs deps, starts FastAPI (:8001).
- `python run.py`: Runs directly (kills existing :8001 process).
- `cd frontend && npm run dev`: Next.js frontend (:3000).

## Architecture
- **Backend**: FastAPI (:8001).
- **Worker**: `colab/worker.py` (runs on Colab GPU, connects via WS `/ws/worker`).
- **Automation**: `app/automation/play_runner.py` (Playwright).
- **Database**: `data/db.sqlite3` (SQLite/aiosqlite). Migrations: manual ALTER TABLE in `app/database.py`.

## Worker Lifecycle
- Managed by `_maintenance_loop` (30s interval): Handles scale-up/down, stale worker resets, and failed task recovery.
- One worker processes one TTS task at a time (ThreadPoolExecutor max_workers=1). Max 4 workers.
- WS Reconnect: 5s delay.
- Env: `OMNIVOICE_NUM_STEP`, `OMNIVOICE_GUIDANCE_SCALE`, `OMNIVOICE_SPEED`, `REF_AUDIO_MAX_SECONDS` (clamped 1.0-30.0).

## Key State Models
- `GoogleAccount`: `status` (OFFLINE|CONNECTING|ACTIVE|COOLDOWN|NEEDS_LOGIN).
- `Task`: `status` (PENDING|PROCESSING|COMPLETED|FAILED).
- `Voice`: `audio_path` (`data/voices/<slug>/ref.wav`), `transcript` (`ref.txt`).

## Conventions & Quirks
- **Language**: Vietnamese primary (comments, strings, errors).
- **Automation**: Playwright logic for Google login/Colab orchestration is **Windows-only** (relies on PowerShell `Get-CimInstance` for cleanup).
- **Auth**:
  - Web: JWT (7d).
  - API: Bearer <SHA256(key)>.
  - TTS: Requires auth + balance (402 if insufficient).
  - Worker Callbacks: Unauthenticated (rely on task/voice UUID secrecy).
- **Secrets**: `.env` parsed manually in `app/config.py` (no `python-dotenv`).
- **Cloudflare**: Auto-starts if `CLOUDFLARED_ENABLED=1` and `cloudflared` is on PATH.
- **Keep-alive**: JS injected into Colab to click "Connect" and handle "Run anyway" dialogs every 30s.

