
import argparse
import asyncio
import hashlib
import io
import json
import os
import sys
import time
from typing import Any
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import httpx
import soundfile as sf
import torch
import websockets

SAMPLE_RATE = 24000
REF_CACHE_DIR = Path("/tmp/omnivoice_refs")
MODEL_ID = "k2-fsa/OmniVoice"

# Toàn cầu hóa executor để dùng chung
executor = ThreadPoolExecutor(max_workers=1)

def normalize_server_url(server_url: str) -> str:
    normalized = (server_url or "").strip().rstrip("/")
    if not normalized.startswith(("http://", "https://")):
        raise ValueError(f"SERVER_URL không hợp lệ: {server_url!r}")
    return normalized

def websocket_url(server_url: str) -> str:
    if server_url.startswith("https://"):
        return "wss://" + server_url.removeprefix("https://") + "/ws/worker"
    return "ws://" + server_url.removeprefix("http://") + "/ws/worker"

def detect_device() -> str:
    if torch.cuda.is_available():
        print(f"✅ GPU: {torch.cuda.get_device_name(0)}", flush=True)
        return "cuda:0"
    print("⚠️ KHÔNG có GPU! Chạy trên CPU.", flush=True)
    return "cpu"

def load_model(device: str) -> Any:
    print("🔄 Đang tải model OmniVoice...", flush=True)
    started_at = time.time()
    from omnivoice import OmniVoice
    model = OmniVoice.from_pretrained(
        MODEL_ID,
        device_map=device,
        dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    )
    print(f"✅ Model loaded trong {time.time() - started_at:.1f}s", flush=True)
    
    # Model Warmup
    print("🔥 Đang Warmup model...", flush=True)
    try:
        # Tạo 1 file trắng giả để warmup
        dummy_ref = "/tmp/warmup.wav"
        if not os.path.exists(dummy_ref):
            import numpy as np
            sf.write(dummy_ref, np.zeros(SAMPLE_RATE), SAMPLE_RATE, format="WAV")
        # Chạy inference giả
        model.generate(text="Warmup", ref_audio=dummy_ref)
        print("✅ Warmup thành công.", flush=True)
    except Exception as e:
        print(f"⚠️ Warmup lỗi (bỏ qua): {e}", flush=True)
        
    return model

def _audio_to_wav_bytes(audio: Any) -> bytes:
    import numpy as np
    if isinstance(audio, bytes): return audio
    if isinstance(audio, io.BytesIO):
        audio.seek(0)
        return audio.read()
    if isinstance(audio, dict):
        for key in ("audio", "wav", "output", "samples"):
            if key in audio: return _audio_to_wav_bytes(audio[key])
        if audio: return _audio_to_wav_bytes(audio[next(iter(audio))])
    if isinstance(audio, (list, tuple)):
        return _audio_to_wav_bytes(audio[0])
    try:
        if isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().numpy()
    except: pass
    if isinstance(audio, np.ndarray):
        audio_np = audio.squeeze()
        buffer = io.BytesIO()
        sf.write(buffer, audio_np, SAMPLE_RATE, format="WAV")
        return buffer.getvalue()
    raise TypeError(f"Unsupported type: {type(audio)}")

def run_tts(model: Any, text: str, ref_audio: str, ref_text: str | None = None, language: str | None = None) -> bytes:
    import inspect
    try:
        sig = inspect.signature(model.generate)
        params = set(sig.parameters.keys())
    except: params = set()

    kwargs = {}
    # Map params động cho OmniVoice
    if "text" in params: kwargs["text"] = text
    elif "prompt" in params: kwargs["prompt"] = text
    
    if "ref_audio" in params: kwargs["ref_audio"] = ref_audio
    elif "reference_audio" in params: kwargs["reference_audio"] = ref_audio
    
    if "ref_text" in params and ref_text: kwargs["ref_text"] = ref_text
    if "language" in params and language: kwargs["language"] = language

    # Thực hiện Inference
    output = model.generate(**kwargs)
    return _audio_to_wav_bytes(output)

async def download_ref_audio(client: httpx.AsyncClient, server_url: str, voice_url: str) -> str:
    REF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.md5(voice_url.encode()).hexdigest()
    local_path = REF_CACHE_DIR / f"{url_hash}.wav"
    
    if local_path.exists():
        return str(local_path)
    
    full_url = f"{server_url}{voice_url}" if voice_url.startswith("/") else voice_url
    resp = await client.get(full_url, timeout=30)
    resp.raise_for_status()
    local_path.write_bytes(resp.content)
    return str(local_path)

async def handle_tts_task(model, ws, http_client, server_url, data):
    task_id = data["task_id"]
    text = data["text"]
    voice_url = data["voice_api_url"]
    ref_text = (data.get("voice_ref_text") or "").strip() or None
    language = data.get("language")

    try:
        await ws.send(json.dumps({"action": "status", "status": "BUSY"}))
        ref_path = await download_ref_audio(http_client, server_url, voice_url)

        # Chạy inference trong thread riêng để không block websocket ping/pong
        loop = asyncio.get_running_loop()
        start_t = time.time()
        result_audio = await loop.run_in_executor(
            executor, run_tts, model, text, ref_path, ref_text, language
        )
        tts_ms = (time.time() - start_t) * 1000

        # Upload kết quả
        upload_url = f"{server_url}/api/tasks/{task_id}/complete"
        await http_client.post(upload_url, files={"audio": ("res.wav", result_audio, "audio/wav")}, timeout=60)
        
        await ws.send(json.dumps({"action": "task_completed", "task_id": task_id}))
        print(f"[OK] {task_id} | {tts_ms:.0f}ms", flush=True)
    except Exception as e:
        print(f"[ERR] {task_id}: {e}", flush=True)
        await ws.send(json.dumps({"action": "task_failed", "task_id": task_id, "error": str(e)}))
    finally:
        await ws.send(json.dumps({"action": "status", "status": "IDLE"}))

async def worker_loop(model, server_url, email):
    ws_url = websocket_url(server_url)
    async with httpx.AsyncClient() as http_client:
        while True:
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
                    await ws.send(json.dumps({"action": "register", "email": email, "gpu": gpu}))
                    print(f"🚀 Connected: {email}", flush=True)
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if data.get("action") == "run_tts":
                            asyncio.create_task(handle_tts_task(model, ws, http_client, server_url, data))
                        elif data.get("action") == "ping":
                            await ws.send(json.dumps({"action": "pong"}))
                        elif data.get("action") == "shutdown":
                            return
            except Exception as e:
                print(f"🔄 Reconnecting... ({e})", flush=True)
                await asyncio.sleep(5)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    
    model = load_model(detect_device())
    asyncio.run(worker_loop(model, normalize_server_url(args.server_url), args.email))

if __name__ == "__main__":
    main()
