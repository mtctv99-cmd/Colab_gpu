"""API routes for managing voice samples."""

import aiofiles
import anyio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Voice
from app.config import VOICES_DIR

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
    db: AsyncSession = Depends(get_db),
):
    ext = Path(audio.filename).suffix or ".wav"
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = VOICES_DIR / filename

    # Save voice audio file asynchronously.
    async with aiofiles.open(dest, mode="wb") as f:
        await f.write(await audio.read())

    voice = Voice(name=name, audio_path=str(dest), transcript=transcript)
    db.add(voice)
    await db.commit()
    await db.refresh(voice)
    return {"id": voice.id, "name": voice.name, "audio_path": str(dest)}


# ── Delete voice ──────────────────────────────────────────────
@router.delete("/{voice_id}")
async def delete_voice(voice_id: int, db: AsyncSession = Depends(get_db)):
    voice = await db.get(Voice, voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found.")
    # Remove audio file
    audio_file = Path(voice.audio_path)
    if audio_file.exists():
        await anyio.to_thread.run_sync(lambda: audio_file.unlink(missing_ok=True))
    await db.delete(voice)
    await db.commit()
    return {"detail": "Deleted"}
