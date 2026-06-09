# Colab Worker TTS — Agent Guide

## Quick start

```powershell
run.bat                # creates .venv, installs deps, starts server on :8001
python run.py          # starts directly (kills old :8001 process first)
```

- No tests, no linter, no typecheck. No pytest config found.
- `requirements.txt` is the only dep manifest.

## Architecture

```
run.py → app.main:app (FastAPI on :8001)
         ├── /api/accounts   — manage Google accounts & workers
         ├── /api/voices     — CRUD voice samples (stored data/voices/<slug>/ref.wav)
         ├── /api/tasks      — CRUD TTS tasks (+ direct sync endpoint)
         ├── /api/tts        — /text (sync) and /batch (async+webhook)
         ├── /api/health     — server health, worker list, stats
         ├── /ws/worker      — WebSocket for Colab workers (OmniVoice)
         ├── /ws/dashboard   — WebSocket for live dashboard updates
         └── / (static)      — SPA dashboard (app/static/)
colab/worker.py — runs on Colab GPU, loads OmniVoice, connects via WS
app/automation/play_runner.py — Playwright automation to control Colab browser
```

**Worker lifecycle:** auto-started by server. Max 3h45m lifetime → handover. Scale up when pending > 5× active workers. Scale down after 5min idle.

## Database

- SQLite via `aiosqlite` at `data/db.sqlite3`.
- Idempotent column migrations in `app/database.py:_MIGRATIONS` (ALTER TABLE in try/except).
- .env parsed manually in `app/config.py` (no python-dotenv).

## Key state models

| Model | Fields |
|-------|--------|
| `GoogleAccount` | email, profile_name, status (OFFLINE\|CONNECTING\|ACTIVE\|COOLDOWN\|NEEDS_LOGIN), quota_reset_at, started_at |
| `Voice` | name, audio_path, transcript |
| `Task` | text, voice_id, status (PENDING\|PROCESSING\|COMPLETED\|FAILED), batch_id, webhook_url, result_audio_path |

## Sync TTS flow

1. `POST /api/tts/text` — creates Task, waits up to 30s for idle worker, 120s for result
2. Worker fetches reference audio from `/api/voices/{id}/audio`, runs OmniVoice, uploads result to `/api/tasks/{id}/complete`
3. `_pending_direct_events[task_id]` (asyncio.Event) bridges the worker WS response back to the HTTP request

## Running a worker (Colab side)

```python
# colab/worker.py runs on the Colab notebook
python colab/worker.py --server-url <SERVER_URL> --email <EMAIL>
```

- Connects via WebSocket to `<server_url>/ws/worker`
- Registers with `{action:"register", email, gpu}`
- Receives `run_tts` messages, processes on a ThreadPoolExecutor (1 worker), uploads result WAV
- Auto-reconnects every 5s on WS disconnect
- Config via env vars: `OMNIVOICE_NUM_STEP=8`, `OMNIVOICE_GUIDANCE_SCALE=1.5`, `OMNIVOICE_SPEED=1.0`, `REF_AUDIO_MAX_SECONDS=5`
- `REF_AUDIO_MAX_SECONDS` clamped to [1.0, 30.0] at import time in worker.py. Trimming happens during audio download, not in `run_tts` (cache key includes the limit).

## Conventions & quirks

- **Vietnamese mixed with English** in comments, strings, and error messages throughout (Vietnamese primary language).
- **Playwright only runs on Windows** (browser cleanup uses PowerShell `Get-CimInstance`).
- Two similar sync TTS endpoints: `POST /api/tts/text` (preferred) and `POST /api/tasks/direct` (older, less used).
- Voice audio files stored at `data/voices/<slug>/ref.wav`; transcript at `data/voices/<slug>/ref.txt`.
- Cloudflare tunnel auto-starts when cloudflared is on PATH and `CLOUDFLARED_ENABLED=1` in `.env`.
- Keep-alive JS injected into Colab page clicks "Connect" and dismisses "Run anyway" dialogs every 30s.

## Account setup flow

```
POST /api/accounts/add {email}   → opens headed Chromium for login
                                  → auto-closes when Google SID+SAPISID cookies detected
POST /api/accounts/{id}/start    → opens Colab notebook, selects T4 GPU, queues Run All
```

- Accounts can be in NEEDS_LOGIN state when Google login session expires.
- Quota COOLDOWN is 16h. Cell start failure gives 15min short backoff.
