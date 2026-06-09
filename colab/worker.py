"""Standalone Colab worker for OmniVoice TTS.

This script is intended to be executed from Google Colab after cloning the repo:

    python colab/worker.py --server-url https://xxx.trycloudflare.com --email user@gmail.com
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import sys
import time
from typing import Any

import httpx
import soundfile as sf
import torch
import websockets

SAMPLE_RATE = 24000
REF_CACHE_DIR = "/tmp/omnivoice_refs"
MODEL_ID = "k2-fsa/OmniVoice"


def normalize_server_url(server_url: str) -> str:
    """Validate and normalize the public server URL."""
    normalized = (server_url or "").strip().rstrip("/")
    if not normalized.startswith(("http://", "https://")):
        raise ValueError(
            f"SERVER_URL không hợp lệ: {server_url!r}. "
            "Hãy nhập URL dạng https://xxx.trycloudflare.com"
        )
    return normalized


def websocket_url(server_url: str) -> str:
    """Convert server HTTP(S) URL to worker WebSocket URL."""
    if server_url.startswith("https://"):
        return "wss://" + server_url.removeprefix("https://") + "/ws/worker"
    return "ws://" + server_url.removeprefix("http://") + "/ws/worker"


def detect_device() -> str:
    """Return the best available torch device string."""
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        print(f"✅ GPU: {gpu_name}", flush=True)
        return "cuda:0"
    print("⚠️ KHÔNG có GPU! Worker sẽ chạy rất chậm trên CPU.", flush=True)
    return "cpu"


def load_model(device: str) -> Any:
    """Load OmniVoice model onto the selected device."""
    print("🔄 Đang tải model OmniVoice...", flush=True)
    started_at = time.time()

    from omnivoice import OmniVoice

    model = OmniVoice.from_pretrained(
        MODEL_ID,
        device_map=device,
        dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    )

    load_ms = round((time.time() - started_at) * 1000, 1)
    print(f"✅ Model loaded trên {device} trong {load_ms:.0f}ms", flush=True)
    return model


def _audio_to_wav_bytes(audio: Any) -> bytes:
    """Normalize OmniVoice output to WAV bytes."""
    import numpy as np

    print(f"[debug] model.generate output type: {type(audio)!r}", flush=True)

    if isinstance(audio, bytes):
        return audio

    if isinstance(audio, io.BytesIO):
        audio.seek(0)
        data = audio.read()
        print(f"[debug] BytesIO output bytes={len(data)} head={data[:12]!r}", flush=True)
        return data

    if isinstance(audio, dict):
        for key in ("audio", "wav", "output", "samples"):
            if key in audio:
                return _audio_to_wav_bytes(audio[key])
        if audio:
            first_key = next(iter(audio))
            return _audio_to_wav_bytes(audio[first_key])

    if isinstance(audio, (list, tuple)):
        if not audio:
            raise ValueError("model.generate returned empty audio list")
        return _audio_to_wav_bytes(audio[0])

    try:
        import torch as _torch
        if isinstance(audio, _torch.Tensor):
            audio = audio.detach().cpu().numpy()
    except Exception:
        pass

    if isinstance(audio, np.ndarray):
        audio_np = audio.squeeze()
        buffer = io.BytesIO()
        sf.write(buffer, audio_np, SAMPLE_RATE, format="WAV")
        return buffer.getvalue()

    raise TypeError(f"Unsupported model.generate output type: {type(audio)!r}")


def run_tts(model: Any, text: str, ref_audio: str, ref_text: str | None = None, language: str | None = None) -> bytes:
    """Generate WAV bytes from text and reference audio.

    OmniVoice package/API has changed across versions. Build kwargs from the
    runtime signature so the reference voice is always passed with the right
    parameter names, instead of silently falling back to a random/default voice.
    """
    import inspect

    try:
        sig = inspect.signature(model.generate)
        params = set(sig.parameters.keys())
        print(f"[debug] model.generate params: {sorted(params)}", flush=True)
    except Exception as exc:
        print(f"[warn] Cannot inspect model.generate signature: {exc}", flush=True)
        params = set()

    kwargs: dict[str, Any] = {}

    if "text" in params:
        kwargs["text"] = text
    elif "prompt" in params:
        kwargs["prompt"] = text
    elif "input_text" in params:
        kwargs["input_text"] = text

    if "ref_audio" in params:
        kwargs["ref_audio"] = ref_audio
    elif "reference_audio" in params:
        kwargs["reference_audio"] = ref_audio
    elif "reference_wav" in params:
        kwargs["reference_wav"] = ref_audio
    elif "prompt_audio" in params:
        kwargs["prompt_audio"] = ref_audio

    if ref_text:
        if "ref_text" in params:
            kwargs["ref_text"] = ref_text
        elif "reference_text" in params:
            kwargs["reference_text"] = ref_text
        elif "prompt_text" in params:
            kwargs["prompt_text"] = ref_text

    if language and "language" in params:
        kwargs["language"] = language

    if kwargs:
        print(f"[debug] model.generate kwargs keys: {sorted(kwargs.keys())}", flush=True)
        audio = model.generate(**kwargs)
    else:
        print("[warn] Signature unknown; trying generate(text, ref_audio=...)", flush=True)
        try:
            audio = model.generate(text, ref_audio=ref_audio, ref_text=ref_text)
        except TypeError:
            audio = model.generate(text, reference_wav=ref_audio)

    return _audio_to_wav_bytes(audio)


async def download_ref_audio(
    http_client: httpx.AsyncClient,
    server_url: str,
    voice_url: str,
) -> str:
    """Download and cache reference audio from the server."""
    os.makedirs(REF_CACHE_DIR, exist_ok=True)
    full_url = voice_url if voice_url.startswith(("http://", "https://")) else f"{server_url}{voice_url}"
    url_hash = hashlib.md5(full_url.encode("utf-8")).hexdigest()[:12]
    cached_path = os.path.join(REF_CACHE_DIR, f"ref_{url_hash}.wav")

    if os.path.exists(cached_path):
        print(f"  [cache] Ref audio: {url_hash}", flush=True)
        return cached_path

    print(f"  [download] {full_url}", flush=True)
    response = await http_client.get(full_url, timeout=30)
    response.raise_for_status()

    # Validate response is actual audio (WAV starts with RIFF)
    if not response.content[:4] == b"RIFF":
        print(f"  [warn] Downloaded ref may not be WAV. First bytes: {response.content[:16]}", flush=True)

    with open(cached_path, "wb") as file:
        file.write(response.content)
    return cached_path


async def send_status(ws: Any, status: str) -> None:
    """Send worker status, ignoring transient socket errors."""
    try:
        await ws.send(json.dumps({"action": "status", "status": status}))
    except Exception:
        pass


async def handle_tts_task(
    model: Any,
    ws: Any,
    http_client: httpx.AsyncClient,
    server_url: str,
    data: dict[str, Any],
) -> None:
    """Run one TTS task and report completion/failure to server."""
    task_id = data["task_id"]
    text = data["text"]
    voice_url = data["voice_api_url"]
    ref_text = (data.get("voice_ref_text") or "").strip() or None
    language = data.get("language")

    short_text = text[:60] + ("..." if len(text) > 60 else "")
    print(f"[task] {task_id} | {short_text}", flush=True)

    try:
        await send_status(ws, "BUSY")
        ref_path = await download_ref_audio(http_client, server_url, voice_url)

        started_at = time.time()
        result_audio = run_tts(model, text, ref_path, ref_text=ref_text, language=language)
        tts_ms = round((time.time() - started_at) * 1000, 1)

        upload_url = f"{server_url}/api/tasks/{task_id}/complete"
        upload_response = await http_client.post(
            upload_url,
            files={"audio": ("result.wav", result_audio, "audio/wav")},
            timeout=120,
        )
        upload_response.raise_for_status()

        await ws.send(json.dumps({"action": "task_completed", "task_id": task_id}))
        duration_seconds = len(result_audio) / (SAMPLE_RATE * 2)
        print(f"[ok] {task_id} TTS={tts_ms}ms audio~{duration_seconds:.1f}s", flush=True)
    except Exception as exc:
        print(f"[fail] {task_id}: {exc}", flush=True)
        try:
            await ws.send(json.dumps({"action": "task_failed", "task_id": task_id, "error": str(exc)}))
        except Exception:
            pass
    finally:
        await send_status(ws, "IDLE")


async def worker_loop(model: Any, server_url: str, email: str) -> None:
    """Connect to the control WebSocket and process tasks forever."""
    ws_url = websocket_url(server_url)
    retry_delay = 5
    max_delay = 60

    async with httpx.AsyncClient() as http_client:
        while True:
            try:
                print(f"[ws] Đang kết nối: {ws_url} ...", flush=True)
                async with websockets.connect(
                    ws_url,
                    open_timeout=30,
                    close_timeout=10,
                    ping_interval=30,
                    ping_timeout=20,
                ) as ws:
                    retry_delay = 5
                    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
                    await ws.send(json.dumps({"action": "register", "email": email, "gpu": gpu_name}))
                    print(f"[ws] Đã đăng ký: {email} (GPU: {gpu_name})", flush=True)
                    await send_status(ws, "IDLE")

                    while True:
                        raw = await ws.recv()
                        data = json.loads(raw)
                        action = data.get("action")

                        if action == "run_tts":
                            await handle_tts_task(model, ws, http_client, server_url, data)
                        elif action == "ping":
                            await ws.send(json.dumps({"action": "pong"}))
                        elif action == "shutdown":
                            print("[ws] Server yêu cầu shutdown.", flush=True)
                            return

            except (websockets.ConnectionClosed, OSError) as exc:
                print(f"[ws] Mất kết nối: {exc}. Thử lại sau {retry_delay}s...", flush=True)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_delay)
            except Exception as exc:
                print(f"[ws] Lỗi: {exc}. Thử lại sau {retry_delay}s...", flush=True)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_delay)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Colab OmniVoice TTS Worker")
    parser.add_argument("--server-url", required=True, help="Server URL, ví dụ https://xxx.trycloudflare.com")
    parser.add_argument("--email", required=True, help="Email Google account đã đăng ký trên dashboard")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        server_url = normalize_server_url(args.server_url)
    except ValueError as exc:
        print(f"[error] {exc}", flush=True)
        sys.exit(1)

    email = args.email.strip()
    if not email:
        print("[error] EMAIL không được để trống.", flush=True)
        sys.exit(1)

    device = detect_device()
    model = load_model(device)
    print("[worker] Sẵn sàng. Đang khởi chạy...", flush=True)
    asyncio.run(worker_loop(model, server_url, email))


if __name__ == "__main__":
    main()
