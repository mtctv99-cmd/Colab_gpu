"""Standalone Colab LLM worker dùng HuggingFace Transformers + OpenAI-compatible API.

Hỗ trợ Gemma 4 (multimodal) qua AutoModelForImageTextToText + AutoProcessor.
Fallback về Qwen2.5-1.5B (text-only) nếu model không tải được.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import threading
import time
from typing import Any

import requests
import torch
import uvicorn
import websockets
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("hf_llm_worker")

PORT = 11434

# Bản đồ tên model ngắn → HuggingFace model ID
MODEL_MAP = {
    "gemma4:e2b": "google/gemma-4-E2B-it",
    "gemma4:e4b": "google/gemma-4-E4B-it",
    "gemma4:e2b-it": "google/gemma-4-E2B-it",
    "gemma4:e4b-it": "google/gemma-4-E4B-it",
    "gemma4:12b": "google/gemma-4-12B-it",
    "gemma4:12b-it": "google/gemma-4-12B-it",
    "qwen2.5:1.5b": "Qwen/Qwen2.5-1.5B-Instruct",
    "qwen2.5:3b": "Qwen/Qwen2.5-3B-Instruct",
    "qwen3.5:9b": "Qwen/Qwen3.5-9B-Instruct",
}

# Các model Gemma 4 dùng kiến trúc multimodal (AutoModelForImageTextToText)
GEMMA4_MULTIMODAL_MODELS = {
    "google/gemma-4-E2B-it",
    "google/gemma-4-E4B-it",
    "google/gemma-4-12B-it",
    "google/gemma-4-26B-it",
    "google/gemma-4-31B-it",
}


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatRequest(BaseModel):
    model: str = "gemma4:e4b"
    messages: list[ChatMessage]
    temperature: float | None = 0.7
    max_tokens: int | None = 512
    stream: bool = False
    top_p: float | None = 1.0


def resolve_model(model_name: str) -> str:
    """Phân giải tên model ngắn → HuggingFace model ID."""
    if model_name.startswith("google/") or model_name.startswith("Qwen/"):
        return model_name
    # Fallback về Qwen2.5-1.5B nếu không tìm thấy
    return MODEL_MAP.get(model_name, "Qwen/Qwen2.5-1.5B-Instruct")


def is_gemma4(hf_model_id: str) -> bool:
    """Kiểm tra xem model có phải Gemma 4 (multimodal) không."""
    return hf_model_id in GEMMA4_MULTIMODAL_MODELS or "gemma-4" in hf_model_id.lower()

def has_media_parts(messages: list[dict[str, Any]]) -> bool:
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") in ("image", "image_url", "audio", "video"):
                return True
    return False

def move_inputs_to_device(inputs: Any, device: Any) -> Any:
    """Move processor outputs to model device without casting token ids."""
    for key, value in list(inputs.items()):
        if hasattr(value, "to"):
            inputs[key] = value.to(device)
    return inputs


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chuẩn hóa messages: ép content về dạng list[dict] cho Gemma 4."""
    normalized = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        # Nếu content là string → wrap thành list[dict] dạng Gemma 4
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            # Đảm bảo mỗi phần tử là dict hợp lệ
            cleaned = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        cleaned.append({"type": "text", "text": part.get("text", "")})
                    elif part.get("type") == "image_url":
                        # Hỗ trợ image_url từ OpenAI format
                        url_info = part.get("image_url", {})
                        if isinstance(url_info, dict):
                            url = url_info.get("url", "")
                        else:
                            url = str(url_info)
                        if url:
                            cleaned.append({"type": "image", "url": url})
                    elif part.get("type") in ("image", "audio"):
                        cleaned.append(part)
                elif isinstance(part, str):
                    cleaned.append({"type": "text", "text": part})
            content = cleaned if cleaned else [{"type": "text", "text": ""}]
        normalized.append({"role": role, "content": content})
    return normalized


def build_text_prompt(messages: list[dict[str, Any]], tokenizer: Any) -> str:
    """Xây dựng prompt dạng text (dùng cho model text-only như Qwen)."""
    clean_messages = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            content = "\n".join(text_parts)
        clean_messages.append({"role": msg.get("role", "user"), "content": str(content)})
    if hasattr(tokenizer, "apply_chat_template"):
        try:
            return tokenizer.apply_chat_template(
                clean_messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:
            pass
    return "\n".join([f"{m['role']}: {m['content']}" for m in clean_messages]) + "\nassistant:"


# ─── Load Gemma 4 (multimodal) ────────────────────────────────────────────────

def load_gemma4_model(hf_model_id: str):
    """Tải Gemma 4 dùng AutoModelForImageTextToText + AutoProcessor."""
    from transformers import AutoModelForImageTextToText, AutoProcessor

    logger.info("Loading Gemma 4 processor: %s", hf_model_id)
    processor = AutoProcessor.from_pretrained(
        hf_model_id,
        padding_side="left",
        trust_remote_code=True,
    )
    logger.info("Loading Gemma 4 model: %s", hf_model_id)
    model = AutoModelForImageTextToText.from_pretrained(
        hf_model_id,
        device_map="auto",
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    return processor, model


# ─── Load model text-only (Qwen, v.v.) ────────────────────────────────────────

def load_text_model(hf_model_id: str):
    """Tải model text-only dùng AutoModelForCausalLM + AutoTokenizer."""
    from transformers import AutoModelForCausalLM, AutoTokenizer

    logger.info("Loading text model tokenizer: %s", hf_model_id)
    tokenizer = AutoTokenizer.from_pretrained(hf_model_id, trust_remote_code=True)
    logger.info("Loading text model: %s", hf_model_id)
    model = AutoModelForCausalLM.from_pretrained(
        hf_model_id,
        device_map="auto",
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    return tokenizer, model


# ─── FastAPI app ───────────────────────────────────────────────────────────────

def create_app(model_name: str) -> FastAPI:
    hf_model_id = resolve_model(model_name)
    logger.info("Resolved model: %s → %s", model_name, hf_model_id)

    use_gemma4 = is_gemma4(hf_model_id)
    processor = None
    tokenizer = None
    model = None

    # Thử tải model chính
    try:
        if use_gemma4:
            processor, model = load_gemma4_model(hf_model_id)
        else:
            tokenizer, model = load_text_model(hf_model_id)
    except Exception as e:
        # OOM prevention: free GPU memory before fallback
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        import gc; gc.collect()
        # Fallback về Qwen2.5-1.5B
        logger.warning(
            "Không tải được %s: %s. Fallback → Qwen/Qwen2.5-1.5B-Instruct", hf_model_id, e
        )
        hf_model_id = "Qwen/Qwen2.5-1.5B-Instruct"
        use_gemma4 = False
        tokenizer, model = load_text_model(hf_model_id)

    model.eval()
    logger.info("✅ Model loaded: %s (gemma4=%s)", hf_model_id, use_gemma4)

    app = FastAPI()

    @app.get("/")
    async def root():
        return {"status": "ok", "model": hf_model_id, "gemma4": use_gemma4}

    @app.get("/v1/models")
    async def models():
        return {
            "object": "list",
            "data": [{"id": model_name, "object": "model", "owned_by": "hf-colab"}],
        }

    @app.post("/v1/chat/completions")
    async def chat(req: ChatRequest):
        raw_messages = [m.model_dump() for m in req.messages]
        now = int(time.time())

        if use_gemma4 and processor is not None:
            # ── Gemma 4: follow HuggingFace model-card chat template path ─────
            norm_messages = normalize_messages(raw_messages)
            try:
                if has_media_parts(raw_messages):
                    inputs = processor.apply_chat_template(
                        norm_messages,
                        add_generation_prompt=True,
                        tokenize=True,
                        return_dict=True,
                        return_tensors="pt",
                    )
                else:
                    text = processor.apply_chat_template(
                        norm_messages,
                        add_generation_prompt=True,
                        tokenize=False,
                        enable_thinking=False,
                    )
                    inputs = processor(text=text, return_tensors="pt")
                inputs = move_inputs_to_device(inputs, model.device)
            except Exception as e:
                logger.error("Lỗi khi apply_chat_template Gemma 4: %s", e)
                return {
                    "error": str(e),
                    "id": f"chatcmpl-err-{now}",
                    "object": "chat.completion",
                    "created": now,
                    "model": req.model,
                    "choices": [],
                }

            input_len = inputs["input_ids"].shape[-1]
            do_sample = bool(req.temperature and req.temperature > 0)
            generation_kwargs: dict[str, Any] = {
                "max_new_tokens": min(req.max_tokens or 512, 1024),
                "do_sample": do_sample,
                "eos_token_id": getattr(processor, "eos_token_id", None),
            }
            if do_sample:
                generation_kwargs["temperature"] = req.temperature
                generation_kwargs["top_p"] = req.top_p or 1.0
            with torch.inference_mode():
                output_ids = model.generate(
                    **inputs,
                    **{k: v for k, v in generation_kwargs.items() if v is not None},
                )
            generated = output_ids[0][input_len:]
            text = processor.decode(generated, skip_special_tokens=True).strip()

        else:
            # ── Text-only model (Qwen v.v.) ───────────────────────────────────
            prompt = build_text_prompt(raw_messages, tokenizer)
            inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
            do_sample = bool(req.temperature and req.temperature > 0)
            with torch.inference_mode():
                output = model.generate(
                    **inputs,
                    max_new_tokens=req.max_tokens or 512,
                    do_sample=do_sample,
                    temperature=req.temperature or 0.7,
                    top_p=req.top_p or 1.0,
                    pad_token_id=tokenizer.eos_token_id,
                )
            generated = output[0][inputs["input_ids"].shape[-1]:]
            text = tokenizer.decode(generated, skip_special_tokens=True).strip()
            input_len = int(inputs["input_ids"].shape[-1])

        return {
            "id": f"chatcmpl-hf-{now}",
            "object": "chat.completion",
            "created": now,
            "model": req.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": input_len,
                "completion_tokens": int(len(generated)),
                "total_tokens": input_len + int(len(generated)),
            },
        }

    return app


def start_hf_server(model_name: str) -> None:
    app = create_app(model_name)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")


def wait_for_server(timeout: int = 900) -> None:
    for i in range(timeout):
        try:
            resp = requests.get(f"http://127.0.0.1:{PORT}/", timeout=3)
            if resp.status_code == 200:
                logger.info("HF API ready after %ds: %s", i + 1, resp.text[:200])
                return
        except Exception:
            pass
        if i % 30 == 0:
            logger.info("Waiting for HF API... %ds", i + 1)
        time.sleep(1)
    raise RuntimeError(f"HF API did not start within {timeout}s")


async def worker_loop(server_url: str, email: str, model_name: str) -> None:
    thread = threading.Thread(target=start_hf_server, args=(model_name,), daemon=True)
    thread.start()
    wait_for_server()

    ws_url = (
        server_url.rstrip("/")
        .replace("https://", "wss://")
        .replace("http://", "ws://")
        + "/ws/llm_worker"
    )

    logger.info("Starting cloudflared tunnel...")
    cfd = await asyncio.create_subprocess_exec(
        "./cloudflared",
        "tunnel",
        "--url",
        f"http://localhost:{PORT}",
        "--no-autoupdate",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    public_url = None
    async for line_bytes in cfd.stdout:
        line = line_bytes.decode("utf-8", errors="replace").strip()
        print(line, flush=True)
        match = re.search(r"(https://[a-zA-Z0-9.-]+\.trycloudflare\.com)", line)
        if match:
            public_url = match.group(1)
            logger.info("Public tunnel URL: %s", public_url)
            break
    if not public_url:
        raise RuntimeError("Could not find cloudflare tunnel URL")

    retry_delay = 5
    while True:
        try:
            logger.info("Connecting to %s ...", ws_url)
            async with websockets.connect(ws_url, ping_interval=30) as ws:
                gpu_name = (
                    torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
                )
                await ws.send(
                    json.dumps(
                        {
                            "action": "register",
                            "email": email,
                            "gpu": gpu_name,
                            "ollama_url": public_url,
                            "heartbeat_supported": True,
                        }
                    )
                )
                logger.info(
                    "Registered as %s (GPU: %s, URL: %s)", email, gpu_name, public_url
                )
                async def heartbeat_loop() -> None:
                    while True:
                        await asyncio.sleep(30)
                        await ws.send(json.dumps({"action": "heartbeat", "ts": time.time()}))

                heartbeat_task = asyncio.create_task(heartbeat_loop())
                try:
                    while True:
                        data = json.loads(await ws.recv())
                        action = data.get("action")
                        if action == "ping":
                            await ws.send(json.dumps({"action": "pong"}))
                        elif action == "shutdown":
                            return
                finally:
                    heartbeat_task.cancel()
        except Exception as exc:
            logger.error("WS error: %s. Retry in %ds.", exc, retry_delay)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Colab HuggingFace Gemma 4 LLM Worker")
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--model-name", default="gemma4:e4b")
    args = parser.parse_args()
    asyncio.run(
        worker_loop(args.server_url.strip(), args.email.strip(), args.model_name.strip())
    )


if __name__ == "__main__":
    main()
