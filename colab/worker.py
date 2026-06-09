
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import httpx
import soundfile as sf
import torch
import websockets

SAMPLE_RATE = 24000
REF_CACHE_DIR = Path("/tmp/omnivoice_refs")
MODEL_ID = "k2-fsa/OmniVoice"
TASK_QUEUE_MAXSIZE = 16
OMNIVOICE_NUM_STEP = int(os.getenv("OMNIVOICE_NUM_STEP", "8"))
OMNIVOICE_GUIDANCE_SCALE = float(os.getenv("OMNIVOICE_GUIDANCE_SCALE", "1.5"))
REF_AUDIO_MAX_SECONDS = float(os.getenv("REF_AUDIO_MAX_SECONDS", "5"))
OMNIVOICE_SPEED = float(os.getenv("OMNIVOICE_SPEED", "1.0"))

executor = ThreadPoolExecutor(max_workers=1)
_voice_prompt_cache: dict[str, Any] = {}


def configure_torch_runtime() -> None:
    """Tune PyTorch defaults for Colab T4 inference without changing model API."""
    try:
        torch.set_grad_enabled(False)
    except Exception:
        pass

    if not torch.cuda.is_available():
        return

    try:
        torch.backends.cudnn.benchmark = True
    except Exception:
        pass

    try:
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    except Exception:
        pass

    try:
        torch.set_float32_matmul_precision("high")
    except Exception:
        pass


def autocast_context():
    if torch.cuda.is_available():
        return torch.autocast(device_type="cuda", dtype=torch.float16)
    return nullcontext()


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
    configure_torch_runtime()
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"✅ GPU: {gpu_name} | VRAM={total_gb:.1f}GB", flush=True)
        return "cuda:0"
    print("⚠️ KHÔNG có GPU! Chạy trên CPU.", flush=True)
    return "cpu"


def cache_generate_signature(model: Any) -> set[str]:
    import inspect

    try:
        params = set(inspect.signature(model.generate).parameters.keys())
    except Exception:
        params = set()
    model._omnivoice_generate_params = params
    print(f"[model] generate params cached: {sorted(params)}", flush=True)
    return params


def build_generate_kwargs(
    params: set[str],
    text: str,
    ref_audio: str,
    ref_text: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}

    if "text" in params:
        kwargs["text"] = text
    elif "prompt" in params:
        kwargs["prompt"] = text
    elif "input_text" in params:
        kwargs["input_text"] = text
    else:
        kwargs["text"] = text

    if "ref_audio" in params:
        kwargs["ref_audio"] = ref_audio
    elif "reference_audio" in params:
        kwargs["reference_audio"] = ref_audio
    elif "reference_wav" in params:
        kwargs["reference_wav"] = ref_audio
    elif "prompt_audio" in params:
        kwargs["prompt_audio"] = ref_audio
    else:
        kwargs["ref_audio"] = ref_audio

    if ref_text:
        if "ref_text" in params:
            kwargs["ref_text"] = ref_text
        elif "reference_text" in params:
            kwargs["reference_text"] = ref_text
        elif "prompt_text" in params:
            kwargs["prompt_text"] = ref_text

    if language:
        if "language" in params:
            kwargs["language"] = language
        elif "lang" in params:
            kwargs["lang"] = language

    if "num_step" in params:
        kwargs["num_step"] = OMNIVOICE_NUM_STEP
    elif "num_steps" in params:
        kwargs["num_steps"] = OMNIVOICE_NUM_STEP

    if "guidance_scale" in params:
        kwargs["guidance_scale"] = OMNIVOICE_GUIDANCE_SCALE

    if "speed" in params:
        kwargs["speed"] = OMNIVOICE_SPEED

    if "use_cache" in params:
        kwargs["use_cache"] = True

    return kwargs


def load_model(device: str) -> Any:
    print("🔄 Đang tải model OmniVoice...", flush=True)
    started_at = time.time()

    from omnivoice import OmniVoice

    model = OmniVoice.from_pretrained(
        MODEL_ID,
        device_map=device,
        dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    )
    cache_generate_signature(model)
    import inspect
    try:
        model._omnivoice_prompt_params = set(inspect.signature(model.create_voice_clone_prompt).parameters.keys())
        print(f"[model] voice prompt params cached: {sorted(model._omnivoice_prompt_params)}", flush=True)
    except Exception:
        model._omnivoice_prompt_params = set()
    print(f"✅ Model loaded trong {time.time() - started_at:.1f}s", flush=True)

    print("🔥 Đang warmup model...", flush=True)
    try:
        dummy_ref = "/tmp/warmup.wav"
        if not os.path.exists(dummy_ref):
            import numpy as np
            sf.write(dummy_ref, np.zeros(SAMPLE_RATE, dtype="float32"), SAMPLE_RATE, format="WAV")

        kwargs = build_generate_kwargs(model._omnivoice_generate_params, "Warmup", dummy_ref)
        with torch.inference_mode(), autocast_context():
            model.generate(**kwargs)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        print("✅ Warmup thành công.", flush=True)
    except Exception as exc:
        print(f"⚠️ Warmup lỗi (bỏ qua): {exc}", flush=True)

    return model


def _audio_to_wav_bytes(audio: Any) -> bytes:
    import numpy as np

    if isinstance(audio, bytes):
        return audio

    if isinstance(audio, io.BytesIO):
        audio.seek(0)
        return audio.read()

    if isinstance(audio, dict):
        for key in ("audio", "wav", "output", "samples", "waveform"):
            if key in audio:
                return _audio_to_wav_bytes(audio[key])
        if audio:
            return _audio_to_wav_bytes(audio[next(iter(audio))])

    if isinstance(audio, (list, tuple)):
        if not audio:
            raise ValueError("model.generate returned empty audio list")
        return _audio_to_wav_bytes(audio[0])

    if isinstance(audio, torch.Tensor):
        audio = audio.detach().float().cpu().numpy()

    if isinstance(audio, np.ndarray):
        audio_np = audio.squeeze().astype("float32", copy=False)
        buffer = io.BytesIO()
        sf.write(buffer, audio_np, SAMPLE_RATE, format="WAV")
        return buffer.getvalue()

    raise TypeError(f"Unsupported model.generate output type: {type(audio)!r}")


def prepare_ref_audio(ref_audio: str) -> str:
    """Trim long reference audio to 10s for faster voice prompt/ref encoding."""
    if REF_AUDIO_MAX_SECONDS <= 0:
        return ref_audio

    src = Path(ref_audio)
    if not src.exists():
        return ref_audio

    trim_key = hashlib.md5(
        f"{src}:{src.stat().st_mtime_ns}:{REF_AUDIO_MAX_SECONDS}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    trimmed = REF_CACHE_DIR / f"{trim_key}.trim.wav"
    if trimmed.exists() and trimmed.stat().st_size > 44:
        return str(trimmed)

    try:
        audio, sr = sf.read(str(src), always_2d=False)
        max_samples = int(sr * REF_AUDIO_MAX_SECONDS)
        if len(audio) <= max_samples:
            return ref_audio
        sf.write(str(trimmed), audio[:max_samples], sr, format="WAV")
        print(f"[ref] trimmed {src.name} to {REF_AUDIO_MAX_SECONDS:.1f}s", flush=True)
        return str(trimmed)
    except Exception as exc:
        print(f"[ref] trim skipped: {exc}", flush=True)
        return ref_audio


def build_voice_prompt_kwargs(params: set[str], ref_audio: str, ref_text: str | None = None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if "ref_audio" in params:
        kwargs["ref_audio"] = ref_audio
    elif "reference_audio" in params:
        kwargs["reference_audio"] = ref_audio
    elif "reference_wav" in params:
        kwargs["reference_wav"] = ref_audio
    elif "prompt_audio" in params:
        kwargs["prompt_audio"] = ref_audio
    else:
        kwargs["ref_audio"] = ref_audio

    if ref_text:
        if "ref_text" in params:
            kwargs["ref_text"] = ref_text
        elif "reference_text" in params:
            kwargs["reference_text"] = ref_text
        elif "prompt_text" in params:
            kwargs["prompt_text"] = ref_text
    return kwargs


def get_voice_clone_prompt(model: Any, ref_audio: str, ref_text: str | None = None) -> Any | None:
    """Cache OmniVoice ref-audio encoding when API exposes create_voice_clone_prompt."""
    if not hasattr(model, "create_voice_clone_prompt"):
        return None

    params = getattr(model, "_omnivoice_prompt_params", set())
    if not params:
        return None

    src = Path(ref_audio)
    try:
        mtime = src.stat().st_mtime_ns
    except Exception:
        mtime = 0
    cache_key = hashlib.md5(f"{ref_audio}:{mtime}:{ref_text or ''}".encode(), usedforsecurity=False).hexdigest()
    if cache_key in _voice_prompt_cache:
        return _voice_prompt_cache[cache_key]

    try:
        kwargs = build_voice_prompt_kwargs(params, ref_audio, ref_text)
        started = time.time()
        with torch.inference_mode(), autocast_context():
            prompt = model.create_voice_clone_prompt(**kwargs)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        _voice_prompt_cache[cache_key] = prompt
        print(f"[voice-cache] prompt built in {(time.time() - started) * 1000:.0f}ms", flush=True)
        return prompt
    except Exception as exc:
        print(f"[voice-cache] prompt build skipped: {exc}", flush=True)
        return None


def run_tts(model: Any, text: str, ref_audio: str, ref_text: str | None = None, language: str | None = None) -> bytes:
    params = getattr(model, "_omnivoice_generate_params", set())
    ref_audio = prepare_ref_audio(ref_audio)
    kwargs = build_generate_kwargs(params, text, ref_audio, ref_text=ref_text, language=language)

    voice_prompt = get_voice_clone_prompt(model, ref_audio, ref_text)
    if voice_prompt is not None and "voice_clone_prompt" in params:
        for key in ("ref_audio", "reference_audio", "reference_wav", "prompt_audio", "ref_text", "reference_text", "prompt_text"):
            kwargs.pop(key, None)
        kwargs["voice_clone_prompt"] = voice_prompt

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    with torch.inference_mode(), autocast_context():
        output = model.generate(**kwargs)

    if torch.cuda.is_available():
        torch.cuda.synchronize()

    return _audio_to_wav_bytes(output)


async def download_ref_audio(client: httpx.AsyncClient, server_url: str, voice_url: str) -> str:
    REF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.md5(voice_url.encode(), usedforsecurity=False).hexdigest()
    local_path = REF_CACHE_DIR / f"{url_hash}.wav"

    if local_path.exists() and local_path.stat().st_size > 44:
        return str(local_path)

    full_url = f"{server_url}{voice_url}" if voice_url.startswith("/") else voice_url
    tmp_path = local_path.with_suffix(".tmp")
    resp = await client.get(full_url, timeout=30)
    resp.raise_for_status()
    tmp_path.write_bytes(resp.content)
    tmp_path.replace(local_path)
    return str(local_path)


async def send_json_safe(ws: Any, payload: dict[str, Any]) -> None:
    try:
        await ws.send(json.dumps(payload))
    except Exception:
        pass


async def send_status(ws: Any, status: str, queue_size: int | None = None) -> None:
    payload: dict[str, Any] = {"action": "status", "status": status}
    if queue_size is not None:
        payload["queue_size"] = queue_size
    await send_json_safe(ws, payload)


async def process_task(model: Any, ws: Any, http_client: httpx.AsyncClient, server_url: str, data: dict[str, Any]) -> None:
    task_id = data["task_id"]
    text = data["text"]
    voice_url = data["voice_api_url"]
    ref_text = (data.get("voice_ref_text") or "").strip() or None
    language = data.get("language")

    short_text = text[:70] + ("..." if len(text) > 70 else "")
    print(f"[task] {task_id} | {short_text}", flush=True)

    try:
        ref_started = time.time()
        ref_path = await download_ref_audio(http_client, server_url, voice_url)
        ref_ms = (time.time() - ref_started) * 1000

        loop = asyncio.get_running_loop()
        tts_started = time.time()
        result_audio = await loop.run_in_executor(
            executor, run_tts, model, text, ref_path, ref_text, language
        )
        tts_ms = (time.time() - tts_started) * 1000

        upload_started = time.time()
        upload_url = f"{server_url}/api/tasks/{task_id}/complete"
        upload_response = await http_client.post(
            upload_url,
            files={"audio": ("result.wav", result_audio, "audio/wav")},
            timeout=120,
        )
        upload_response.raise_for_status()
        upload_ms = (time.time() - upload_started) * 1000

        await send_json_safe(ws, {"action": "task_completed", "task_id": task_id})
        audio_seconds = len(result_audio) / (SAMPLE_RATE * 2)
        peak_mb = 0.0
        if torch.cuda.is_available():
            peak_mb = torch.cuda.max_memory_allocated() / 1024**2
        print(
            f"[ok] {task_id} ref={ref_ms:.0f}ms tts={tts_ms:.0f}ms upload={upload_ms:.0f}ms "
            f"audio~{audio_seconds:.1f}s peak={peak_mb:.0f}MB",
            flush=True,
        )
    except Exception as exc:
        print(f"[fail] {task_id}: {exc}", flush=True)
        await send_json_safe(ws, {"action": "task_failed", "task_id": task_id, "error": str(exc)})


async def task_consumer(
    queue: asyncio.Queue[dict[str, Any]],
    model: Any,
    ws: Any,
    http_client: httpx.AsyncClient,
    server_url: str,
) -> None:
    while True:
        data = await queue.get()
        try:
            await send_status(ws, "BUSY", queue.qsize())
            await process_task(model, ws, http_client, server_url, data)
        finally:
            queue.task_done()
            await send_status(ws, "IDLE" if queue.empty() else "BUSY", queue.qsize())


async def worker_loop(model: Any, server_url: str, email: str) -> None:
    ws_url = websocket_url(server_url)
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)

    async with httpx.AsyncClient(limits=limits, http2=True, timeout=60) as http_client:
        while True:
            consumer_task: asyncio.Task | None = None
            task_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=TASK_QUEUE_MAXSIZE)
            try:
                print(f"[ws] Connecting: {ws_url}", flush=True)
                async with websockets.connect(
                    ws_url,
                    open_timeout=30,
                    close_timeout=10,
                    ping_interval=20,
                    ping_timeout=10,
                    max_queue=32,
                ) as ws:
                    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
                    await ws.send(json.dumps({"action": "register", "email": email, "gpu": gpu}))
                    consumer_task = asyncio.create_task(task_consumer(task_queue, model, ws, http_client, server_url))
                    print(f"🚀 Connected: {email} (GPU: {gpu})", flush=True)
                    await send_status(ws, "IDLE", 0)

                    while True:
                        raw = await ws.recv()
                        data = json.loads(raw)
                        action = data.get("action")

                        if action == "run_tts":
                            try:
                                task_queue.put_nowait(data)
                                await send_status(ws, "BUSY", task_queue.qsize())
                            except asyncio.QueueFull:
                                await send_json_safe(ws, {
                                    "action": "task_failed",
                                    "task_id": data.get("task_id"),
                                    "error": "Worker queue full",
                                })
                        elif action == "ping":
                            await ws.send(json.dumps({"action": "pong"}))
                        elif action == "shutdown":
                            print("[ws] Server yêu cầu shutdown.", flush=True)
                            if consumer_task:
                                consumer_task.cancel()
                            return
            except Exception as exc:
                print(f"🔄 Reconnecting... ({exc})", flush=True)
                if consumer_task:
                    consumer_task.cancel()
                    try:
                        await consumer_task
                    except asyncio.CancelledError:
                        pass
                await asyncio.sleep(5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Colab OmniVoice TTS Worker")
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--email", required=True)
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

    print(f"[fast-mode] num_step={OMNIVOICE_NUM_STEP} guidance_scale={OMNIVOICE_GUIDANCE_SCALE} ref_max={REF_AUDIO_MAX_SECONDS}s speed={OMNIVOICE_SPEED}", flush=True)
    model = load_model(detect_device())
    asyncio.run(worker_loop(model, server_url, email))


if __name__ == "__main__":
    main()
