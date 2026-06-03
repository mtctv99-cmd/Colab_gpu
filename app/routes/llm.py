"""OpenAI-compatible LLM inference routes."""
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["llm"])


# ── OpenAI-compatible request model ───────────────────────────

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="gemma4", description="Tên model, vd: gemma4, gemma4-9b")
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=1024, ge=1, le=8192)
    stream: bool | None = Field(default=False)
    top_p: float | None = Field(default=1.0, ge=0.0, le=1.0)


class ChatChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: Literal["stop", "length", "error"] = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: Usage


# ── POST /v1/chat/completions ────────────────────────────────

@router.post(
    "/chat/completions",
    summary="Chat completion (OpenAI-compatible)",
    response_model=ChatCompletionResponse,
)
async def chat_completions(req: ChatCompletionRequest):
    """
    Gửi prompt đến model LLM đã cấu hình (gemma4, …).
    Tương thích hoàn toàn với OpenAI Chat Completion API.

    - request: {"model":"gemma4","messages":[...]}
    - response: {"id":"chatcmpl-xxx","choices":[{"message":{"role":"assistant","content":"..."}}]}
    - stream: chưa hỗ trợ — sẽ implement sau.
    """

    logger.info("Chat completion request: model=%s, messages=%d", req.model, len(req.messages))

    # TODO: LLM inference logic — sẽ implement ở task riêng
    # - Route theo `req.model` (gemma4, gemma4-9b, …)
    # - Gọi local (ollama/vllm) hoặc dispatch qua Colab worker
    # - Nếu req.stream=True → streaming response

    # Placeholder response
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        created=int(time.time()),
        model=req.model,
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(
                    role="assistant",
                    content=f"Xin chào! Bạn đã gửi {len(req.messages)} tin nhắn cho {req.model}. "
                            "Logic LLM sẽ implement ở task riêng.",
                ),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=len(req.messages), completion_tokens=1, total_tokens=len(req.messages) + 1),
    )