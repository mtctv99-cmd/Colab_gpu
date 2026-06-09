"""API routes for managing voice samples."""

import aiofiles
import anyio
import re
import unicodedata
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Voice
from app.config import VOICES_DIR
from app.routes.auth import require_admin


def _slugify(name: str) -> str:
    """Convert voice name to safe folder/file name."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[^a-z0-9]+", "_", n).strip("_")
    return n or "voice"

router = APIRouter(prefix="/api/voices", tags=["voices"])


# ── List voices ───────────────────────────────────────────────
@router.get("/")
async def list_voices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Voice))
    voices = result.scalars().all()
    return [
        {
            "id": v.id,
            "name": v.name,
            "audio_path": v.audio_path,
            "transcript": v.transcript,
        }
        for v in voices
    ]


# ── Get single voice (for Colab worker download) ─────────────
@router.get("/{voice_id}")
async def get_voice(voice_id: int, db: AsyncSession = Depends(get_db)):
    voice = await db.get(Voice, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found.")
    return {
        "id": voice.id,
        "name": voice.name,
        "audio_path": voice.audio_path,
        "transcript": voice.transcript,
    }


# ── Download voice audio file ─────────────────────────────────
@router.get("/{voice_id}/audio")
async def download_voice_audio(voice_id: int, db: AsyncSession = Depends(get_db)):
    voice = await db.get(Voice, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found.")
    audio_file = Path(voice.audio_path)
    if not audio_file.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk.")
    return FileResponse(audio_file, media_type="audio/wav", filename=audio_file.name)


# ── Add voice ─────────────────────────────────────────────────
@router.post("/")
async def add_voice(
    name: str = Form(...),
    transcript: str = Form(""),
    audio: UploadFile = File(...),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add a new voice sample.

    Stores the file under ``data/voices/<slug>/ref<ext>``. If a voice with the same
    slug already exists on disk we append a short uuid suffix so files never clash.
    """
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Voice name is required.")

    # Reject duplicate names so the dashboard list stays clean.
    existing = await db.execute(select(Voice).where(Voice.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Voice name '{name}' already exists.")

    ext = (Path(audio.filename).suffix or ".wav").lower()
    if ext not in (".wav", ".mp3", ".flac", ".ogg", ".m4a"):
        raise HTTPException(status_code=400, detail=f"Unsupported audio format: {ext}")

    slug = _slugify(name)
    voice_dir = VOICES_DIR / slug
    if voice_dir.exists():
        slug = f"{slug}_{uuid.uuid4().hex[:6]}"
        voice_dir = VOICES_DIR / slug
    voice_dir.mkdir(parents=True, exist_ok=True)

    dest = voice_dir / f"ref{ext}"
    async with aiofiles.open(dest, mode="wb") as f:
        await f.write(await audio.read())

    # Persist transcript next to the audio so you can edit it later if needed.
    if transcript:
        transcript_path = voice_dir / "ref.txt"
        try:
            async with aiofiles.open(transcript_path, mode="w", encoding="utf-8") as t:
                await t.write(transcript)
        except Exception:
            pass

    voice = Voice(name=name, audio_path=str(dest), transcript=transcript)
    db.add(voice)
    await db.commit()
    await db.refresh(voice)
    return {
        "id": voice.id,
        "name": voice.name,
        "audio_path": str(dest),
        "transcript": voice.transcript,
        "slug": slug,
    }


# ── Delete voice ──────────────────────────────────────────────
@router.delete("/{voice_id}")
async def delete_voice(voice_id: int, _admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    voice = await db.get(Voice, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found.")

    audio_file = Path(voice.audio_path)
    voice_dir = audio_file.parent

    def _cleanup():
        if audio_file.exists():
            audio_file.unlink(missing_ok=True)
        # If file lived inside the new per-voice slug directory under VOICES_DIR,
        # remove transcript and the empty directory itself.
        try:
            if voice_dir.resolve().parent == VOICES_DIR.resolve():
                transcript = voice_dir / "ref.txt"
                if transcript.exists():
                    transcript.unlink(missing_ok=True)
                if voice_dir.exists() and not any(voice_dir.iterdir()):
                    voice_dir.rmdir()
        except Exception:
            pass

    await anyio.to_thread.run_sync(_cleanup)
    await db.delete(voice)
    await db.commit()
    return {"detail": "Deleted"}
