# Kế Hoạch Chi Tiết: OpenAI-Compatible Chat API cho Server TTS Dubbing

**Dự án**: Mở rộng server FastAPI hiện tại thành AI Provider hỗ trợ OpenAI-compatible API, chạy Gemma 4 12B Coder trên Colab workers.

**Ngày**: 18/06/2026
**Phiên bản**: v1.0

---

## Mục Lục

1. [Tổng Quan Kiến Trúc](#1-tổng-quan-kiến-trúc)
2. [Phân Tích Hiện Trạng](#2-phân-tích-hiện-trạng)
3. [Thiết Kế Chi Tiết](#3-thiết-kế-chi-tiết)
   - 3.1 [Model `LlmTask`](#31-model-llmtask)
   - 3.2 [Worker LLM (`colab/llm_worker.py`)](#32-worker-llm-colabllm_workerpy)
   - 3.3 [OpenAI Routes (`app/routes/openai.py`)](#33-openai-routes-approutesopenaipy)
   - 3.4 [WebSocket Protocol Mở Rộng](#34-websocket-protocol-mở-rộng)
   - 3.5 [Pool Management Type-Aware](#35-pool-management-type-aware)
   - 3.6 [LLM Dispatcher (`app/orchestrator/llm_dispatcher.py`)](#36-llm-dispatcher-apporchestratorllm_dispatcherpy)
   - 3.7 [Streaming Architecture](#37-streaming-architecture)
   - 3.8 [Billing & Token Counting](#38-billing--token-counting)
   - 3.9 [Lifecycle & Rotation](#39-lifecycle--rotation)
   - 3.10 [Database Migrations](#310-database-migrations)
   - 3.11 [Config & Environment Variables](#311-config--environment-variables)
   - 3.12 [Notebook Colab cho LLM](#312-notebook-colab-cho-llm)
4. [Luồng Xử Lý Chi Tiết](#4-luồng-xử-lý-chi-tiết)
5. [Phân Tích Rủi Ro & Giải Pháp](#5-phân-tích-rủi-ro--giải-pháp)
6. [Nâng Cấp Bổ Sung (Future)](#6-nâng-cấp-bổ-sung-future)
7. [Kế Hoạch Triển Khai](#7-kế-hoạch-triển-khai)

---

## 1. Tổng Quan Kiến Trúc

### 1.1 Sơ đồ tổng thể

```
┌─────────────────────────────────────────────────────────────┐
│                     App bên ngoài                            │
│        Gọi OpenAI-compatible API với API key                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                   FastAPI Server (:8090)                      │
│                                                              │
│  ┌─────────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │ POST /v1/chat/  │  │ POST /api/   │  │ GET /api/       │ │
│  │ completions     │  │ tts/text     │  │ voices, tasks,  │ │
│  │ GET /v1/models  │  │ (giữ nguyên) │  │ health...       │ │
│  └────────┬────────┘  └──────┬───────┘  └────────┬────────┘ │
│           │                  │                    │          │
│  ┌────────▼──────────────────▼────────────────────▼────────┐ │
│  │              ConnectionManager                          │ │
│  │  ┌─────────────────────┐  ┌──────────────────────────┐ │ │
│  │  │  TTS Workers Pool   │  │  LLM Workers Pool        │ │ │
│  │  │  type="tts"         │  │  type="llm"              │ │ │
│  │  └─────────────────────┘  └──────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              Orchestrator                                │ │
│  │  PoolManager (type-aware)  ─  WorkerManager              │ │
│  │  LLMDispatcher             ─  TaskDispatcher (TTS)       │ │
│  │  Lifecycle (maintenance loop type-aware)                │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                         │
            ┌────────────┴────────────┐
            │                         │
            ▼                         ▼
┌──────────────────────┐  ┌──────────────────────┐
│  Colab TTS Worker    │  │  Colab LLM Worker    │
│  (type="tts")        │  │  (type="llm")        │
│  OmniVoice           │  │  llama-cpp-python    │
│                      │  │  Gemma 4 12B GGUF    │
│  WS → server         │  │  WS → server         │
└──────────────────────┘  └──────────────────────┘
```

### 1.2 Nguyên tắc thiết kế

1. **Worker riêng biệt**: Mỗi worker chỉ chạy một loại (TTS hoặc LLM). Pool quản lý 2 pool riêng nhưng chia sẻ chung tài khoản Google.
2. **OpenAI-compatible**: Tuân thủ đúng spec OpenAI API để app có thể dùng thư viện OpenAI SDK.
3. **Streaming từ đầu**: Hỗ trợ `stream=true` ngay trong phiên bản đầu.
4. **Shared balance**: Dùng chung balance với TTS, quy đổi token → character.
5. **Kế thừa tối đa**: Tận dụng lại cơ chế deploy (git clone), auth, WebSocket heartbeat, rotation.

---

## 2. Phân Tích Hiện Trạng

### 2.1 Cơ chế deploy worker hiện tại

File `app/orchestrator/worker.py` — method `launch(email)`:

```
1. Tạo OAuth client riêng cho email
2. Gọi Colab API assign (T4 GPU)
3. Spawn keep-alive daemon local
4. Inject Python code qua Jupyter kernel WebSocket:
   - git clone repo từ GitHub vào /content/{REPO}
   - pip install dependencies
   - subprocess.Popen(["python", "colab/worker.py", args])
5. Ghi WorkerSession + GoogleAccount vào DB
```

**Config**: `GITHUB_USER=mtctv99-cmd`, `GITHUB_REPO=Colab_gpu`, `GITHUB_BRANCH=main`

### 2.2 Cấu trúc WebSocket protocol hiện tại

| Action | Hướng | Mô tả |
|--------|-------|-------|
| `register` | Worker → Server | Đăng ký worker |
| `run_tts` | Server → Worker | Gửi task TTS |
| `status` | Worker → Server | Cập nhật trạng thái (IDLE/BUSY) |
| `pong` / `pong_status` | Worker → Server | Heartbeat |
| `task_completed` | Worker → Server | Báo task hoàn thành |
| `task_failed` | Worker → Server | Báo task lỗi |
| `ping` | Server → Worker | Kiểm tra kết nối |
| `shutdown` | Server → Worker | Yêu cầu tắt |

### 2.3 Pool management hiện tại

- `MAX_WORKERS = 4` — tổng số worker tối đa
- `WARM_TARGET = 1` — luôn giữ 1 worker
- Scale-up: khi pending tasks >= 3 (hoặc >=5 nếu aggressive)
- Scale-down: khi idle > 120s và không có pending tasks
- Rotation: 3h45m lifetime, launch replacement, shutdown cũ, cooldown 16h
- `pending_tasks()` chỉ đếm `Task` (TTS), không có LLM

### 2.4 Billing hiện tại

- `User.balance` — số characters còn lại (BigInteger)
- `UsageRecord` — ghi lại số characters đã dùng
- `deduct_balance()` — trừ balance, tạo UsageRecord
- TTS: `count_tts_characters(text)` — đếm ký tự trong text

---

## 3. Thiết Kế Chi Tiết

### 3.1 Model `LlmTask`

**File**: `app/models/llm.py`

```python
"""LlmTask model — OpenAI chat completion tasks."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, Boolean, Float

from app.database import Base


class LlmTask(Base):
    __tablename__ = "llm_tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    messages = Column(Text, nullable=False)          # JSON array of {role, content}
    model = Column(String, nullable=False, default="gemma-4-12b-coder")
    temperature = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    stream = Column(Boolean, default=False)

    status = Column(String, nullable=False, default="PENDING")
    response_text = Column(Text, nullable=True)      # Full response content
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)

    worker_id = Column(Integer, ForeignKey("google_accounts.id"), nullable=True)
    worker_session_id = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    error_message = Column(Text, nullable=True)
    attempt = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    leased_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
```

**Ghi chú**: Không gộp vào `Task` hiện tại vì Task có các field TTS-specific (voice_id, text, language, result_audio_path). `llm_tasks` là bảng riêng, không liên quan đến voices.

### 3.2 Worker LLM (`colab/llm_worker.py`)

**File mới**: `colab/llm_worker.py` (dựa trên cấu trúc `colab/worker.py`)

#### 3.2.1 Cấu trúc tổng thể

```
main()
  ├── parse_args() → --server-url, --email, --worker-session-id
  ├── load_model()
  │   ├── from llama_cpp import Llama
  │   └── Llama.from_pretrained(repo_id, filename, n_ctx, n_gpu_layers=-1)
  ├── detect_device() → thông báo GPU info
  └── worker_loop(model, server_url, email, worker_session_id)
       ├── connect WebSocket
       ├── register {"action": "register", "type": "llm", ...}
       └── message loop:
            ├── "run_llm" → process_chat_completion()
            ├── "ping" → pong_status
            ├── "shutdown" → exit
            └── "cancel_task" → cancel generation
```

#### 3.2.2 Model Loading

```python
MODEL_REPO = os.getenv("LLM_MODEL_REPO", "yuxinlu1/gemma-4-12B-coder-fable5-composer2.5-v1-GGUF")
MODEL_FILE = os.getenv("LLM_MODEL_FILE", "gemma4-coding-Q2_K.gguf")
N_CTX = int(os.getenv("LLM_N_CTX", "8192"))
N_GPU_LAYERS = int(os.getenv("LLM_N_GPU_LAYERS", "-1"))  # -1 = all

def load_model() -> Llama:
    logger.info("Loading Gemma 4 12B Q2_K GGUF...")
    llm = Llama.from_pretrained(
        repo_id=MODEL_REPO,
        filename=MODEL_FILE,
        n_ctx=N_CTX,
        n_gpu_layers=N_GPU_LAYERS,
        verbose=False,
        flash_attn=True,
        cache_type="q8_0",       # KV cache quantization
    )
    return llm
```

#### 3.2.3 Non-streaming Inference

```python
def run_chat_completion(llm: Llama, messages: list, temperature: float, max_tokens: int) -> dict:
    response = llm.create_chat_completion(
        messages=messages,
        temperature=temperature or 0.7,
        max_tokens=max_tokens or 2048,
        stream=False,
    )
    return {
        "response_text": response["choices"][0]["message"]["content"],
        "prompt_tokens": response["usage"]["prompt_tokens"],
        "completion_tokens": response["usage"]["completion_tokens"],
    }
```

#### 3.2.4 Streaming Inference (Thread + Queue)

```python
import threading
from typing import Optional

_cancel_flags: dict[str, bool] = {}  # llm_task_id -> cancel flag

def run_chat_completion_stream(llm, messages, temperature, max_tokens,
                                chunk_queue: asyncio.Queue, task_id: str):
    """Chạy trong ThreadPoolExecutor."""
    _cancel_flags[task_id] = False
    try:
        for chunk in llm.create_chat_completion(
            messages=messages,
            temperature=temperature or 0.7,
            max_tokens=max_tokens or 2048,
            stream=True,
        ):
            if _cancel_flags.get(task_id, False):
                break
            delta = chunk["choices"][0].get("delta", {})
            if delta:
                import asyncio
                asyncio.run_coroutine_threadsafe(
                    chunk_queue.put({"type": "chunk", "delta": delta}),
                    _main_loop
                )

        usage = {
            "prompt_tokens": chunk.get("usage", {}).get("prompt_tokens", 0),
            "completion_tokens": chunk.get("usage", {}).get("completion_tokens", 0),
        }
        asyncio.run_coroutine_threadsafe(
            chunk_queue.put({"type": "done", "usage": usage}),
            _main_loop
        )
    except Exception as e:
        asyncio.run_coroutine_threadsafe(
            chunk_queue.put({"type": "error", "error": str(e)}),
            _main_loop
        )
    finally:
        _cancel_flags.pop(task_id, None)
```

#### 3.2.5 Task Processing

```python
async def process_chat_completion(llm, ws, http_client, server_url, data, worker_session_id):
    task_id = data["llm_task_id"]
    messages = json.loads(data["messages"])  # JSON string → list
    temperature = data.get("temperature")
    max_tokens = data.get("max_tokens")
    stream = data.get("stream", False)

    if stream:
        chunk_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        executor.submit(run_chat_completion_stream, llm, messages, temperature, max_tokens, chunk_queue, task_id)

        while True:
            item = await chunk_queue.get()
            if item["type"] == "chunk":
                await ws.send_json({
                    "action": "llm_chunk",
                    "llm_task_id": task_id,
                    "delta": item["delta"],
                    "worker_session_id": worker_session_id,
                })
            elif item["type"] == "done":
                await ws.send_json({
                    "action": "llm_completed",
                    "llm_task_id": task_id,
                    "usage": item["usage"],
                    "worker_session_id": worker_session_id,
                })
                break
            elif item["type"] == "error":
                await ws.send_json({
                    "action": "llm_failed",
                    "llm_task_id": task_id,
                    "error": item["error"],
                    "worker_session_id": worker_session_id,
                })
                break
    else:
        result = await loop.run_in_executor(executor, run_chat_completion, llm, messages, temperature, max_tokens)
        await ws.send_json({
            "action": "llm_completed",
            "llm_task_id": task_id,
            "response_text": result["response_text"],
            "prompt_tokens": result["prompt_tokens"],
            "completion_tokens": result["completion_tokens"],
            "worker_session_id": worker_session_id,
        })
```

#### 3.2.6 Xử lý Cancel

```python
elif action == "cancel_task":
    tid = data.get("llm_task_id")
    if tid:
        _cancel_flags[tid] = True
        logger.info(f"Cancel requested for task {tid}")
```

### 3.3 OpenAI Routes (`app/routes/openai.py`)

**File mới**: `app/routes/openai.py`

#### 3.3.1 Model List

```python
@router.get("/v1/models")
async def list_models(user: User = Depends(require_user)):
    return {
        "object": "list",
        "data": [
            {
                "id": "gemma-4-12b-coder",
                "object": "model",
                "created": 1718000000,
                "owned_by": "system",
            }
        ]
    }
```

#### 3.3.2 Chat Completion (Non-streaming)

```python
class ChatCompletionRequest(BaseModel):
    model: str = "gemma-4-12b-coder"
    messages: list[dict] = Field(..., min_length=1)
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=2048, ge=1, le=32768)
    stream: bool = False

@router.post("/v1/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if req.stream:
        return await _chat_completions_stream(req, user, db)
    return await _chat_completions_sync(req, user, db)


async def _chat_completions_sync(req, user, db):
    # 1. Estimate token cost (pre-authorize)
    estimated_prompt = sum(len(m.get("content", "")) // 4 for m in req.messages)
    max_completion = req.max_tokens or 2048
    estimated_chars = (estimated_prompt + max_completion) * 4

    if user.role != "admin" and user.balance < estimated_chars:
        raise HTTPException(status_code=402, detail="Insufficient balance")

    # 2. Create LlmTask
    task = LlmTask(
        id=str(uuid.uuid4()),
        messages=json.dumps(req.messages),
        model=req.model,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        stream=False,
        status="PENDING",
        user_id=user.id,
    )
    db.add(task)
    await deduct_balance(user, estimated_chars, "api", db, task_id=task.id)
    await db.commit()
    await db.refresh(task)

    # 3. Dispatch to LLM worker
    event = asyncio.Event()
    _pending_llm_events[task.id] = event

    idle = manager.get_idle_worker(type="llm")
    if idle:
        info = manager.worker_info.get(idle, {})
        wsid = info.get("worker_session_id", "")
        await llm_dispatcher.dispatch(task, idle, wsid, db)
        await manager.broadcast_status({"event": "llm_task_created", "task_id": task.id})
    else:
        asyncio.create_task(_maybe_scale_up())
        await manager.broadcast_status({"event": "llm_task_created", "task_id": task.id})

    # 4. Wait for completion
    try:
        await asyncio.wait_for(event.wait(), timeout=300.0)
    except asyncio.TimeoutError:
        _pending_llm_events.pop(task.id, None)
        raise HTTPException(status_code=504, detail="LLM processing timeout.")

    await db.refresh(task)

    if task.status == "FAILED":
        raise HTTPException(status_code=500, detail=f"LLM task failed: {task.error_message}")

    # 5. Refund unused tokens
    actual_chars = (task.prompt_tokens + task.completion_tokens) * 4
    refund = estimated_chars - actual_chars
    if refund > 0:
        await add_balance(user, refund)

    # 6. Return OpenAI-compatible response
    return {
        "id": f"chatcmpl-{task.id}",
        "object": "chat.completion",
        "created": int(task.created_at.timestamp()),
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": task.response_text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": task.prompt_tokens,
            "completion_tokens": task.completion_tokens,
            "total_tokens": (task.prompt_tokens or 0) + (task.completion_tokens or 0),
        },
    }
```

#### 3.3.3 Chat Completion (Streaming)

```python
_streaming_queues: dict[str, asyncio.Queue] = {}  # llm_task_id -> Queue

async def _chat_completions_stream(req, user, db):
    # Pre-authorize (giống sync)
    estimated_prompt = sum(len(m.get("content", "")) // 4 for m in req.messages)
    max_completion = req.max_tokens or 2048
    estimated_chars = (estimated_prompt + max_completion) * 4

    if user.role != "admin" and user.balance < estimated_chars:
        raise HTTPException(status_code=402, detail="Insufficient balance")

    task = LlmTask(
        id=str(uuid.uuid4()),
        messages=json.dumps(req.messages),
        model=req.model,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        stream=True,
        status="PENDING",
        user_id=user.id,
    )
    db.add(task)
    await deduct_balance(user, estimated_chars, "api", db, task_id=task.id)
    await db.commit()
    await db.refresh(task)

    # Dispatch
    idle = manager.get_idle_worker(type="llm")
    if idle:
        info = manager.worker_info.get(idle, {})
        wsid = info.get("worker_session_id", "")
        await llm_dispatcher.dispatch(task, idle, wsid, db)
    else:
        asyncio.create_task(_maybe_scale_up())

    # Tạo queue cho streaming
    chunk_queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    _streaming_queues[task.id] = chunk_queue

    async def event_generator():
        try:
            # Gửi role chunk đầu tiên
            yield f"data: {json.dumps({'id': f'chatcmpl-{task.id}', 'object': 'chat.completion.chunk', 'created': int(task.created_at.timestamp()), 'model': req.model, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"

            finish_reason = "stop"
            while True:
                try:
                    item = await asyncio.wait_for(chunk_queue.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    finish_reason = "timeout"
                    yield f"data: {json.dumps({'id': f'chatcmpl-{task.id}', 'object': 'chat.completion.chunk', 'created': int(task.created_at.timestamp()), 'model': req.model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'timeout'}]})}\n\n"
                    break

                if item is None:  # sentinel = stream complete
                    break
                elif item.get("type") == "error":
                    finish_reason = "error"
                    break

                yield f"data: {json.dumps({'id': f'chatcmpl-{task.id}', 'object': 'chat.completion.chunk', 'created': int(task.created_at.timestamp()), 'model': req.model, 'choices': [{'index': 0, 'delta': item.get('delta', {}), 'finish_reason': None}]})}\n\n"

            yield f"data: {json.dumps({'id': f'chatcmpl-{task.id}', 'object': 'chat.completion.chunk', 'created': int(task.created_at.timestamp()), 'model': req.model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish_reason}]})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"SSE error: {e}")
        finally:
            _streaming_queues.pop(task.id, None)
            # Refund unused tokens
            await db.refresh(task)
            if task.status == "COMPLETED":
                actual_chars = (task.prompt_tokens + task.completion_tokens) * 4
                refund = estimated_chars - actual_chars
                if refund > 0:
                    await add_balance(user, refund)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 3.4 WebSocket Protocol Mở Rộng

#### 3.4.1 Đăng ký worker với type

Worker gửi thêm field `type` khi register:

```json
{
  "action": "register",
  "email": "user@gmail.com",
  "worker_session_id": "uuid-v4",
  "gpu": "Tesla T4",
  "type": "llm"
}
```

#### 3.4.2 Actions mới

| Action | Hướng | Payload | Mô tả |
|--------|-------|---------|-------|
| `run_llm` | Server → Worker | `{llm_task_id, messages, temperature, max_tokens, stream}` | Gửi task chat completion |
| `llm_chunk` | Worker → Server | `{llm_task_id, delta: {content: "..."}, worker_session_id}` | Streaming chunk |
| `llm_completed` | Worker → Server | `{llm_task_id, response_text, prompt_tokens, completion_tokens, worker_session_id}` | Task hoàn thành |
| `llm_failed` | Worker → Server | `{llm_task_id, error, worker_session_id}` | Task lỗi |
| `cancel_task` | Server → Worker | `{llm_task_id}` | Hủy generation đang chạy |

#### 3.4.3 ConnectionManager mở rộng

Sửa `app/routes/ws.py`:

```python
class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}
        self.worker_info: dict[str, dict] = {}
        self.workers_by_type: dict[str, list[str]] = {"tts": [], "llm": []}

    async def connect(self, ws, email, gpu="", worker_session_id="", worker_type="tts"):
        self.active[email] = ws
        self.worker_info[email] = {
            "gpu": gpu,
            "type": worker_type,
            "status": "LOADING",
            "last_pong": time.time(),
            "worker_session_id": worker_session_id,
        }
        self.workers_by_type.setdefault(worker_type, []).append(email)

    def disconnect(self, email):
        info = self.worker_info.get(email, {})
        wtype = info.get("type", "tts")
        if email in self.workers_by_type.get(wtype, []):
            self.workers_by_type[wtype].remove(email)
        self.active.pop(email, None)
        self.worker_info.pop(email, None)

    def get_idle_worker(self, type="tts") -> str | None:
        candidates = []
        for email in self.workers_by_type.get(type, []):
            info = self.worker_info.get(email)
            if info and info.get("status") == "IDLE":
                candidates.append(email)
        return candidates[0] if candidates else None

    def get_active_count_by_type(self, type="tts") -> int:
        return len(self.workers_by_type.get(type, []))
```

#### 3.4.4 Message loop mở rộng

Trong `websocket_worker()`:

```python
# Sau register:
wtype = raw.get("type", "tts")  # ← MỚI

# Trong message loop:
if action == "run_tts":
    # ... existing code (chỉ cho type="tts")
elif action == "run_llm" and wtype == "llm":
    await _handle_llm_task(data)
elif action == "llm_chunk":
    await _handle_llm_chunk(data)
elif action == "llm_completed":
    await _handle_llm_completed(data)
elif action == "llm_failed":
    await _handle_llm_failed(data)
# ... pong, status, shutdown giữ nguyên
```

### 3.5 Pool Management Type-Aware

**Sửa file**: `app/orchestrator/pool.py`

#### 3.5.1 Các method mới

```python
class PoolManager:
    async def pending_llm_tasks(self, db: AsyncSession) -> int:
        """Đếm LLM tasks PENDING."""
        from app.models.llm import LlmTask
        res = await db.execute(
            select(func.count(LlmTask.id)).where(LlmTask.status == "PENDING")
        )
        return res.scalar() or 0

    async def pending_tts_tasks(self, db: AsyncSession) -> int:
        """Đếm TTS tasks PENDING."""
        res = await db.execute(
            select(func.count(Task.id)).where(Task.status == "PENDING")
        )
        return res.scalar() or 0

    async def active_count_by_type(self, db: AsyncSession, type="tts") -> int:
        """Đếm worker đang chạy theo type."""
        from app.routes.ws import manager
        return manager.get_active_count_by_type(type)

    async def select_account_for_launch(self, db: AsyncSession) -> str | None:
        """Giữ nguyên — chọn account READY bất kỳ."""
        import os as _os
        _token_dir = _os.path.expanduser("~/.config/colab-cli")
        res = await db.execute(
            select(GoogleAccount)
            .where(
                and_(
                    GoogleAccount.status == READY,
                    GoogleAccount.worker_session_id.is_(None),
                )
            )
            .order_by(GoogleAccount.last_active.asc().nullsfirst())
        )
        accounts = res.scalars().all()
        for acc in accounts:
            _safe = acc.email.replace("@", "_at_").replace(".", "_")
            if _os.path.exists(_os.path.join(_token_dir, f"token_{_safe}.json")):
                return acc.email
        return None

    async def scale_up_needed_by_type(self, db: AsyncSession, type="tts") -> int:
        """Tính số worker cần launch cho 1 type cụ thể."""
        ready = await self.ready_account_count(db)
        active = await self.active_count_by_type(db, type)
        if ready == 0:
            return 0
        max_can_launch = min(ready, MAX_WORKERS - active)
        if max_can_launch <= 0:
            return 0

        if type == "llm":
            pending = await self.pending_llm_tasks(db)
        else:
            pending = await self.pending_tts_tasks(db)

        if active < 1 and pending > 0:
            return min(1, max_can_launch)
        if pending >= SCALE_UP_AGGRESSIVE:
            return min(max_can_launch, 2)
        if pending >= SCALE_UP_THRESHOLD:
            return min(1, max_can_launch)
        return 0
```

#### 3.5.2 Chiến lược scale

```
Mỗi chu kỳ maintenance (10s):
1. pending_llm = count_llm_pending()
2. pending_tts = count_tts_pending()
3. active_llm = get_active_count_by_type("llm")
4. active_tts = get_active_count_by_type("tts")
5. ready_accounts = ready_account_count()

6. Nếu ready_accounts > 0:
   a. Nếu total_active < WARM_TARGET (1):
      → Launch worker cho type có pending > 0 (ưu tiên LLM)
   b. Nếu active_llm < 1 và pending_llm > 0:
      → Launch LLM worker
   c. Nếu pending_llm >= SCALE_UP_THRESHOLD:
      → Launch LLM worker
   d. Nếu pending_tts >= SCALE_UP_THRESHOLD và active_llm đủ:
      → Launch TTS worker (nếu còn account)
   e. Nếu total_active >= MAX_WORKERS (4):
      → Không launch thêm
```

### 3.6 LLM Dispatcher (`app/orchestrator/llm_dispatcher.py`)

**File mới**: `app/orchestrator/llm_dispatcher.py`

Giống `dispatcher.py` nhưng dành cho LlmTask:

```python
class LLMTaskDispatcher:
    async def dispatch(self, task: LlmTask, email: str, wsid: str, db: AsyncSession) -> bool:
        from app.routes.ws import manager

        # Lease task
        ok = await self._lease_task(db, task, email, wsid)
        if not ok:
            return False

        # Send via WebSocket
        ws = manager.active.get(email)
        if not ws:
            return False

        msg = {
            "action": "run_llm",
            "llm_task_id": task.id,
            "messages": task.messages,
            "temperature": task.temperature,
            "max_tokens": task.max_tokens,
            "stream": task.stream,
        }
        try:
            await ws.send_json(msg)
            manager.worker_info[email]["status"] = "BUSY"
            return True
        except Exception:
            # Rollback lease
            task.status = "PENDING"
            task.worker_id = None
            task.worker_session_id = None
            task.leased_at = None
            task.lease_expires_at = None
            return False

    async def _lease_task(self, db, task, email, wsid):
        task = await db.get(LlmTask, task.id)
        if not task or task.status != "PENDING":
            return False

        res = await db.execute(
            select(GoogleAccount).where(
                GoogleAccount.email == email,
                GoogleAccount.worker_session_id == wsid,
            )
        )
        acc = res.scalar_one_or_none()
        if not acc:
            return False

        now = datetime.now(timezone.utc)
        task.status = "PROCESSING"
        task.worker_id = acc.id
        task.worker_session_id = wsid
        task.attempt = (task.attempt or 0) + 1
        task.leased_at = now
        task.lease_expires_at = now + timedelta(seconds=LLM_TASK_LEASE_SECONDS)

        acc.runtime_status = "BUSY"
        acc.current_task_id = task.id
        acc.idle_since = None
        await db.commit()
        return True

    async def complete(self, task_id: str, email: str, session_id: str,
                       response_text: str, prompt_tokens: int, completion_tokens: int):
        async with async_session() as db:
            task = await db.get(LlmTask, task_id)
            if not task or task.status != "PROCESSING":
                return

            task.status = "COMPLETED"
            task.response_text = response_text
            task.prompt_tokens = prompt_tokens
            task.completion_tokens = completion_tokens
            task.completed_at = datetime.now(timezone.utc)

            # Release worker
            acc_res = await db.execute(
                select(GoogleAccount).where(GoogleAccount.email == email)
            )
            acc = acc_res.scalar_one_or_none()
            if acc:
                acc.runtime_status = "IDLE"
                acc.current_task_id = None
                acc.idle_since = datetime.now(timezone.utc)
            await db.commit()

        # Signal events
        event = _pending_llm_events.pop(task_id, None)
        if event:
            event.set()

    async def fail(self, task_id: str, error: str, email: str, session_id: str):
        async with async_session() as db:
            task = await db.get(LlmTask, task_id)
            if not task:
                return
            task.status = "FAILED"
            task.error_message = error
            task.completed_at = datetime.now(timezone.utc)

            acc_res = await db.execute(
                select(GoogleAccount).where(GoogleAccount.email == email)
            )
            acc = acc_res.scalar_one_or_none()
            if acc:
                acc.runtime_status = "IDLE"
                acc.current_task_id = None
            await db.commit()
```

### 3.7 Streaming Architecture

#### 3.7.1 Luồng dữ liệu

```
┌─────────┐     POST /v1/chat/completions {stream: true}     ┌──────────┐
│  Client  │ ───────────────────────────────────────────────► │  Server  │
│          │                                                   │          │
│  receive │     (1) Tạo LlmTask + chunk_queue + dispatch      │          │
│  SSE     │     (2) Trả về StreamingResponse                 │          │
│  stream  │ ◄────────────────────────────────────────────── │          │
└──────────┘                                                   └────┬─────┘
                                                                    │
                        ┌───────────────────────────────────────────┘
                        │ WS: {"action": "run_llm", "stream": true}
                        ▼
                  ┌─────────────┐
                  │  LLM Worker │
                  │             │
                  │  for chunk  │
                  │  in llm.    │
                  │  create_    │
                  │  chat_comp- │
                  │  letion()   │
                  │  (stream):  │
                  │             │
                  │   WS send   │
                  │   llm_chunk │─────►──┐
                  │   ...       │        │
                  │   WS send   │        │
                  │   llm_comp- │        │
                  │   leted     │─────►──┤
                  └─────────────┘        │
                                         ▼
                                   ┌──────────────┐
                                   │  Server WS   │
                                   │  handler     │
                                   │              │
                                   │  Nhận chunk  │
                                   │  → put vào   │
                                   │  chunk_queue │
                                   │              │
                                   │  SSE gen     │
                                   │  đọc queue   │
                                   │  → ghi HTTP  │
                                   │  response    │
                                   └──────────────┘
```

#### 3.7.2 Timeout & Error Handling

| Tình huống | Xử lý |
|---|---|
| Client disconnect | SSE generator raise Exception → cleanup queue + gửi `cancel_task` đến worker |
| Worker timeout (60s không chunk) | SSE gửi `finish_reason: "timeout"` + `[DONE]` |
| Worker lỗi | SSE gửi `finish_reason: "error"` + `[DONE]` |
| Full queue (256 items) | `Queue.put_nowait` raise `asyncio.QueueFull` → worker tạm dừng |
| Cancel từ server | Gửi WS `cancel_task` → worker check flag giữa tokens |

### 3.8 Billing & Token Counting

#### 3.8.1 Công thức

```python
TOKEN_TO_CHAR_RATIO = 4  # Configurable: 1 token ≈ 4 chars

def estimate_llm_cost(messages: list[dict], max_tokens: int) -> int:
    """Estimate cost in characters for pre-authorization."""
    prompt_chars = sum(len(m.get("content", "")) for m in messages)
    prompt_tokens = prompt_chars / 4  # approximate
    total_tokens = prompt_tokens + max_tokens
    return int(total_tokens * TOKEN_TO_CHAR_RATIO)

def calculate_actual_cost(prompt_tokens: int, completion_tokens: int) -> int:
    """Calculate actual cost from reported token usage."""
    return (prompt_tokens + completion_tokens) * TOKEN_TO_CHAR_RATIO
```

#### 3.8.2 Pre-authorization + Refund

```python
# Trong openai.py
estimated_cost = estimate_llm_cost(req.messages, req.max_tokens or 2048)

# Deduct trước
await deduct_balance(user, estimated_cost, "api", db, task_id=task.id)

# Khi task hoàn thành:
actual_cost = calculate_actual_cost(prompt_tokens, completion_tokens)
refund = estimated_cost - actual_cost
if refund > 0:
    # Refund lại
    user.balance += refund
    db.add(UsageRecord(user_id=user.id, task_id=task.id, characters=0,
                       cost=-refund, source="api_refund"))
```

### 3.9 Lifecycle & Rotation

**Sửa**: `app/orchestrator/lifecycle.py`

#### 3.9.1 Maintenance loop type-aware

```python
async def scale_check():
    async with async_session() as db:
        pending_llm = await pool_manager.pending_llm_tasks(db)
        pending_tts = await pool_manager.pending_tts_tasks(db)
        ready_accounts = await pool_manager.ready_account_count(db)
        active_llm = await pool_manager.active_count_by_type(db, "llm")
        active_tts = await pool_manager.active_count_by_type(db, "tts")
        total_active = active_llm + active_tts

        if ready_accounts == 0 or total_active >= MAX_WORKERS:
            return

        # Ưu tiên launch worker type có pending task
        need_llm = await pool_manager.scale_up_needed_by_type(db, "llm")
        need_tts = await pool_manager.scale_up_needed_by_type(db, "tts")

        if need_llm > 0:
            email = await pool_manager.select_account_for_launch(db)
            if email:
                await launch_llm_worker(email)
        elif need_tts > 0 and need_llm == 0:
            email = await pool_manager.select_account_for_launch(db)
            if email:
                await worker_manager.launch(email)  # TTS
```

#### 3.9.2 Launch function cho LLM

Thêm method trong `WorkerManager` hoặc function riêng:

```python
async def launch_llm_worker(email: str) -> str:
    """Deploy LLM worker lên Colab (tương tự launch() nhưng khác worker script + deps)."""
    # ... assign Colab runtime (giống hệt launch())
    # ... keep-alive (giống hệt)

    # Deploy code KHÁC:
    _deploy_code = f"""
import subprocess, sys, os
repo_dir = "/content/{GITHUB_REPO}"
if not os.path.exists(repo_dir):
    subprocess.run(["git", "clone", "--branch", "{GITHUB_BRANCH}", "{_repo_url}", repo_dir],
        capture_output=True, timeout=60)
    print("CLONE_OK", flush=True)

subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "llama-cpp-python"], capture_output=True, timeout=300)
print("DEPS_OK", flush=True)

worker_path = os.path.join(repo_dir, "colab", "llm_worker.py")
env = os.environ.copy()
env["LLM_N_CTX"] = "{LLM_N_CTX}"
env["LLM_MODEL_REPO"] = "{LLM_MODEL_REPO}"
env["LLM_MODEL_FILE"] = "{LLM_MODEL_FILE}"

proc = subprocess.Popen([sys.executable, worker_path,
    "--server-url", "{_srv_url}",
    "--email", "{email}",
    "--worker-session-id", "{deploy_wsid}"], env=env, start_new_session=True,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
time.sleep(15)  # LLM model larger, wait longer
ret = proc.poll()
print("DEPLOYED PID=" + str(proc.pid) + " ALIVE=" + str(ret is None), flush=True)
"""
    _rt.execute_code(_deploy_code, timeout=LLM_DEPLOY_TIMEOUT)  # 600s timeout
```

#### 3.9.3 Rotation type-aware

Khi rotation chọn account replacement:
- Nếu worker TTS → replacement launch TTS
- Nếu worker LLM → replacement launch LLM

```python
async def rotation_check():
    expired = await pool_manager.get_expired_workers(db)
    for acc in expired:
        email = acc.email

        # Xác định type của worker cần rotate
        from app.routes.ws import manager
        info = manager.worker_info.get(email, {})
        wtype = info.get("type", "tts")

        # Chọn account replacement
        repl_email = await pool_manager.select_account_for_rotation(db, email)
        if not repl_email:
            continue

        # Launch replacement với đúng type
        if wtype == "llm":
            await launch_llm_worker(repl_email)
        else:
            await worker_manager.launch(repl_email)
```

### 3.10 Database Migrations

#### 3.10.1 Bảng mới: `llm_tasks`

Thêm vào `app/database.py` trong hàm `init_db()`:

```python
# LlmTask table
await conn.exec_driver_sql("""
    CREATE TABLE IF NOT EXISTS llm_tasks (
        id TEXT PRIMARY KEY,
        messages TEXT NOT NULL,
        model TEXT NOT NULL DEFAULT 'gemma-4-12b-coder',
        temperature REAL,
        max_tokens INTEGER,
        stream INTEGER DEFAULT 0,
        status TEXT DEFAULT 'PENDING',
        response_text TEXT,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        worker_id INTEGER REFERENCES google_accounts(id),
        worker_session_id TEXT,
        user_id INTEGER REFERENCES users(id),
        error_message TEXT,
        attempt INTEGER DEFAULT 0,
        created_at TIMESTAMP,
        completed_at TIMESTAMP,
        leased_at TIMESTAMP,
        lease_expires_at TIMESTAMP
    )
""")
```

#### 3.10.2 Thêm `type` vào `usage_records`

Migration:
```sql
ALTER TABLE usage_records ADD COLUMN type TEXT DEFAULT 'tts';
```

### 3.11 Config & Environment Variables

**Thêm vào**: `app/config.py`

```python
# LLM Worker config
LLM_WORKER_ENABLED = os.getenv("LLM_WORKER_ENABLED", "0")  # Toggle feature
LLM_MAX_CONCURRENT = int(os.getenv("LLM_MAX_CONCURRENT", "2"))
LLM_N_CTX = int(os.getenv("LLM_N_CTX", "8192"))
LLM_N_GPU_LAYERS = int(os.getenv("LLM_N_GPU_LAYERS", "-1"))
LLM_MODEL_REPO = os.getenv("LLM_MODEL_REPO", "yuxinlu1/gemma-4-12B-coder-fable5-composer2.5-v1-GGUF")
LLM_MODEL_FILE = os.getenv("LLM_MODEL_FILE", "gemma4-coding-Q2_K.gguf")
LLM_TASK_LEASE_SECONDS = int(os.getenv("LLM_TASK_LEASE_SECONDS", "600"))  # 10 phút
LLM_DEPLOY_TIMEOUT = int(os.getenv("LLM_DEPLOY_TIMEOUT", "600"))  # 10 phút

# Pricing
TOKEN_TO_CHAR_RATIO = int(os.getenv("TOKEN_TO_CHAR_RATIO", "4"))

# Worker pool (type-aware)
LLM_WARM_TARGET = int(os.getenv("LLM_WARM_TARGET", "0"))
```

**Cập nhật constants** (`app/orchestrator/constants.py`):

```python
# LLM-specific
LLM_TASK_LEASE_SECONDS = 600
LLM_DEPLOY_TIMEOUT = 600
```

### 3.12 Notebook Colab cho LLM

**File mới**: `colab/llm_worker.ipynb` (giống `worker.ipynb` nhưng cho LLM)

Cell 1 — Cài đặt:
```python
#@title Cài đặt dependencies & đồng bộ code từ GitHub
GITHUB_USER = "mtctv99-cmd"  #@param {type: "string"}
GITHUB_REPO = "Colab_gpu"    #@param {type: "string"}
BRANCH = "main"              #@param {type: "string"}

import subprocess, sys, os, time

repo_dir = f"/content/{GITHUB_REPO}"
if not os.path.exists(repo_dir):
    subprocess.run(["git", "clone", "--branch", BRANCH,
        f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}.git", repo_dir], check=True)
else:
    subprocess.run(["git", "-C", repo_dir, "fetch"], check=True)
    subprocess.run(["git", "-C", repo_dir, "checkout", BRANCH], check=True)
    subprocess.run(["git", "-C", repo_dir, "pull", "--ff-only"], check=True)

subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "llama-cpp-python"], check=True)

# Check GPU
import torch
print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO GPU'}")
```

Cell 2 — Chạy worker:
```python
#@title Chạy WebSocket Worker
SERVER_URL = "https://your-server.com"  #@param {type: "string"}
EMAIL = "your-email@gmail.com"          #@param {type: "string"}
WORKER_SESSION_ID = ""                  #@param {type: "string"}

import subprocess, sys, os

worker_path = f"/content/Colab_gpu/colab/llm_worker.py"
env = os.environ.copy()
env["LLM_N_CTX"] = "8192"
env["LLM_MODEL_REPO"] = "yuxinlu1/gemma-4-12B-coder-fable5-composer2.5-v1-GGUF"
env["LLM_MODEL_FILE"] = "gemma4-coding-Q2_K.gguf"

proc = subprocess.Popen(
    [sys.executable, worker_path,
     "--server-url", SERVER_URL,
     "--email", EMAIL,
     "--worker-session-id", WORKER_SESSION_ID],
    env=env, start_new_session=True,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT
)

while True:
    line = proc.stdout.readline()
    if not line:
        break
    print(line.decode().strip())
```

---

## 4. Luồng Xử Lý Chi Tiết

### 4.1 Non-streaming Chat Completion

```
Client                          Server                          Worker
  │                               │                               │
  │ POST /v1/chat/completions     │                               │
  │ {model, messages, stream:false}│                              │
  │──────────────────────────────►│                               │
  │                               │                               │
  │                    1. Parse request + auth                    │
  │                    2. Estimate tokens                         │
  │                    3. Deduct balance                          │
  │                    4. Create LlmTask (PENDING)                │
  │                    5. Tìm idle LLM worker                     │
  │                               │                               │
  │                    6. dispatch(task)                          │
  │                               │─── run_llm ────────────────►  │
  │                               │   {llm_task_id, messages}     │
  │                               │                               │
  │                               │                   7. llm.create_
  │                               │                   chat_comp-  │
  │                               │                   letion()    │
  │                               │                               │
  │                               │◄── llm_completed ─────────────│
  │                               │   {response_text, usage}      │
  │                               │                               │
  │                    8. Update DB (COMPLETED)                   │
  │                    9. Refund unused tokens                    │
  │                    10. Trả về response                        │
  │◄──────────────────────────────────────┐                       │
  │ {id, choices, usage}                  │                       │
  │                                       │                       │
```

### 4.2 Streaming Chat Completion

```
Client                          Server                          Worker
  │                               │                               │
  │ POST /v1/chat/completions     │                               │
  │ {model, messages, stream:true}│                               │
  │──────────────────────────────►│                               │
  │                               │                               │
  │                    1-5. Giống non-streaming                   │
  │                    6. Tạo chunk_queue                         │
  │                    7. dispatch(task)                          │
  │                               │─── run_llm ────────────────►  │
  │                               │   {stream: true}              │
  │                               │                               │
  │                    8. Trả về SSE ngay                         │
  │◄───── SSE: data: {..."delta": {"role":"assistant"}}... ──────│
  │                               │                               │
  │                               │                   9. for chunk│
  │                               │                   in stream:  │
  │                               │◄── llm_chunk ──────────────   │
  │◄───── SSE: data: {..."delta": {"content":"Hello"}}... ────────│
  │                               │◄── llm_chunk ──────────────   │
  │◄───── SSE: data: {..."delta": {"content":" world"}}... ───────│
  │                               │         ...                   │
  │                               │                               │
  │                               │◄── llm_completed ─────────────│
  │◄───── SSE: data: {...finish_reason: "stop"}                   │
  │◄───── SSE: data: [DONE]                                      │
  │                               │                               │
  │                    10. Refund unused tokens                   │
```

### 4.3 Worker Deploy (LLM)

```
Server                          Colab API                      Colab VM
  │                               │                               │
  │ 1. client.assign(uuid, T4)    │                               │
  │──────────────────────────────►│                               │
  │◄───── {url, token, endpoint} ──┘                              │
  │                               │                               │
  │ 2. keep_alive_assignment()    │                               │
  │ 3. spawn keep-alive daemon    │                               │
  │ 4. Tạo ColabRuntime(url,token)│                               │
  │                               │                               │
  │ 5. execute_code(deploy_code)  │                               │
  │══════════ Jupyter WS =══════════════════════════════════════► │
  │                               │   git clone {REPO}            │
  │                               │   pip install llama-cpp-python│
  │                               │   python llm_worker.py &      │
  │                               │                               │
  │                               │                   6. Tải model │
  │                               │                   GGUF 4.5GB  │
  │                               │                               │
  │◄══════════ Jupyter WS ════════════════════════════════════════│
  │                               │                               │
  │ 7. Worker kết nối WS /ws/worker                               │
  │◄══ WS connect + register(type="llm") ════════════════════════│
  │                               │                               │
  │ 8. Update DB: status=IDLE     │                               │
```

### 4.4 Xử lý lỗi

```
Tình huống: Worker chết khi đang xử lý task
─────────────────────────────────────────────

Server                          Worker
  │                               │
  │─── run_llm ──────────────────►│
  │                               │ (chết)
  │                               │
  │ [heartbeat timeout 60s]       │
  │ disconnect()                  │
  │                               │
  │ task_lease_reaper()           │
  │ (mỗi 10s)                     │
  │                               │
  │ LlmTask.PROCESSING +          │
  │ lease_expired > now           │
  │ → status = PENDING            │
  │   (nếu attempt < 3)           │
  │ → status = FAILED             │
  │   (nếu attempt >= 3)          │
  │                               │
  │ Refund toàn bộ estimated cost │
```

---

## 5. Phân Tích Rủi Ro & Giải Pháp

### 5.1 Bảng đánh giá rủi ro

| # | Rủi ro | Xác suất | Tác động | Giải pháp |
|---|--------|----------|----------|-----------|
| R1 | Pool management 2 worker type không hiệu quả | Medium | Cao | Type-aware pool với priority-based scaling; fallback về 1 type nếu type kia không có task |
| R2 | Streaming WebSocket → SSE mất chunk | Thấp | Cao | Queue per task + sentinel pattern; timeout mỗi chunk 60s |
| R3 | Client disconnect không cleanup được worker | Medium | Trung bình | SSE generator try/except + gửi `cancel_task`; cancel flag thread-safe |
| R4 | llama.cpp không tương thích gemma4_unified | Thấp | Rất cao | Test trước; cập nhật llama.cpp version; fallback CPU |
| R5 | Deploy timeout vì model 4.5GB | Medium | Trung bình | Tăng timeout lên 600s; dùng HF_HUB_ENABLE_HF_TRANSFER |
| R6 | CUDA OOM trên T4 | Thấp | Cao | Q2_K chỉ ~4.5GB, T4 16GB dư; monitoring VRAM khi start |
| R7 | Token billing không chính xác | Medium | Thấp | Worker report actual tokens; pre-auth + refund pattern |
| R8 | Worker LLM không có task → lãng phí | Thấp | Thấp | Scale-down nếu idle > 120s; LLM_WARM_TARGET có thể 0 |
| R9 | Rotation chọn sai worker type | Thấp | Trung bình | Track worker_type trong worker_info; rotation type-aware |
| R10 | Race condition: 2 worker launch cùng email | Thấp | Cao | `_operation_lock` giống TTS; verify DB constraint |

### 5.2 Giải pháp chi tiết

#### R1: Pool management type-aware

```
Vấn đề: Pool hiện tại không phân biệt worker type.
Khi có 3 pending LLM tasks nhưng 0 pending TTS, pool vẫn launch TTS worker.

Giải pháp:
- Thêm worker_type field trong ConnectionManager (in-memory)
- PoolManager check pending cho từng type
- Priority:
  1. type có pending > threshold
  2. type có pending > 0 và active = 0
  3. cân bằng theo tỉ lệ pending
- Nếu chỉ có 1 account READY: launch theo type có pending cao nhất
```

#### R2: Streaming chunk ordering

```
Vấn đề: Worker gửi chunk qua WS (TCP, in-order).
Server đọc chunk, put vào queue. SSE gen đọc queue.
Có thể xảy ra: worker gửi llm_completed trước khi SSE gen kịp đọc hết queue.

Giải pháp:
- Dùng sentinel: worker gửi chunk cho đến khi hết, rồi gửi {"type": "done"}
- Server SSE gen đọc queue. Khi nhận sentinel → gửi [DONE]
- Queue là FIFO → ordering guaranteed
```

#### R5: Model download speed

```
Vấn đề: GGUF 4.5GB tải mỗi lần deploy worker (~3-5 phút).
Hiện tại execute_code timeout = 300s có thể không đủ.

Giải pháp:
- Tăng LLM deploy timeout → 600s
- Dùng HuggingFace Hub transfer optimization:
  pip install huggingface_hub[hf_transfer]
  os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
```

#### R3: Client disconnect cleanup

```
Vấn đề: Client ngắt kết nối giữa stream.
Server vẫn nhận chunk từ worker và cố gắng ghi vào response đã đóng.

Giải pháp:
async def event_generator():
    try:
        while True:
            item = await chunk_queue.get()
            if item is None:
                break
            await response.write(...)
    except (RuntimeError, ConnectionError):
        # Client disconnected → cancel worker
        await worker_send({"action": "cancel_task", "llm_task_id": tid})
    finally:
        cleanup_queue(tid)
```

---

## 6. Nâng Cấp Bổ Sung (Future)

### 6.1 Hỗ trợ nhiều model

```python
# Trong config
LLM_MODELS = {
    "gemma-4-12b-coder": {
        "repo": "yuxinlu1/gemma-4-12B-coder-fable5-composer2.5-v1-GGUF",
        "file": "gemma4-coding-Q4_K_M.gguf",
        "ctx": 16384,
    },
    "gemma-4-12b-coder-fast": {
        "repo": "yuxinlu1/gemma-4-12B-coder-fable5-composer2.5-v1-GGUF",
        "file": "gemma4-coding-Q2_K.gguf",
        "ctx": 8192,
    }
}
```

### 6.2 Continuous batching

Hiện tại `ThreadPoolExecutor(max_workers=1)` — chỉ xử lý 1 task/worker.
Tương lai: chạy `llama-server` trên Colab thay vì worker.py — server proxy request đến Colab runtime.

```
llama-server -m model.gguf --host 0.0.0.0 --port 8080
→ Colab có OpenAI-compatible endpoint local
→ Server chính proxy: /v1/chat/completions → Colab :8080
```

### 6.3 Function calling / Tool use

```python
{
    "model": "gemma-4-12b-coder",
    "messages": [...],
    "tools": [{"type": "function", "function": {...}}],
    "tool_choice": "auto"
}
```

### 6.4 Embeddings API

```python
POST /v1/embeddings
{
    "model": "gemma-4-12b-coder",
    "input": "The text to embed"
}
```

### 6.5 Admin dashboard cho LLM

Mở rộng dashboard hiện tại:
- LLM task list
- Token usage charts
- Model performance metrics (tokens/sec, latency)

### 6.6 Rate limiting riêng cho LLM

```python
LLM_RATE_LIMIT = int(os.getenv("LLM_RATE_LIMIT", "30"))  # requests/minute
```

---

## 7. Kế Hoạch Triển Khai

### Phase 1: Foundation (1-2 ngày)

| Bước | Mô tả | File |
|------|-------|------|
| 1.1 | Tạo model LlmTask | `app/models/llm.py` |
| 1.2 | DB migration (bảng llm_tasks + ALTER usage_records) | `app/database.py` |
| 1.3 | Config mới cho LLM | `app/config.py` |
| 1.4 | Constants mới (lease timeout, deploy timeout) | `app/orchestrator/constants.py` |

### Phase 2: Worker LLM (2-3 ngày)

| Bước | Mô tả | File |
|------|-------|------|
| 2.1 | Viết `colab/llm_worker.py` — non-streaming | `colab/llm_worker.py` |
| 2.2 | Viết `colab/llm_worker.py` — streaming + cancel | `colab/llm_worker.py` |
| 2.3 | Test thử trên Colab (manual) | Colab notebook |
| 2.4 | Tạo `colab/llm_worker.ipynb` cho manual debug | `colab/llm_worker.ipynb` |

### Phase 3: Server Routes (2 ngày)

| Bước | Mô tả | File |
|------|-------|------|
| 3.1 | OpenAI routes — model list + non-streaming | `app/routes/openai.py` |
| 3.2 | OpenAI routes — streaming | `app/routes/openai.py` |
| 3.3 | LLM Dispatcher | `app/orchestrator/llm_dispatcher.py` |
| 3.4 | WebSocket — type-aware ConnectionManager | `app/routes/ws.py` |
| 3.5 | WebSocket — LLM message handlers | `app/routes/ws.py` |
| 3.6 | Thêm router vào main | `app/main.py` |

### Phase 4: Pool & Lifecycle (2 ngày)

| Bước | Mô tả | File |
|------|-------|------|
| 4.1 | PoolManager type-aware methods | `app/orchestrator/pool.py` |
| 4.2 | WorkerManager — launch_llm_worker() | `app/orchestrator/worker.py` |
| 4.3 | Lifecycle — type-aware scale_check | `app/orchestrator/lifecycle.py` |
| 4.4 | Lifecycle — type-aware rotation | `app/orchestrator/lifecycle.py` |

### Phase 5: Billing & Integration (1 ngày)

| Bước | Mô tả | File |
|------|-------|------|
| 5.1 | Token counting + pre-auth/refund | `app/services/auth.py` |
| 5.2 | OpenAI routes — integrate billing | `app/routes/openai.py` |
| 5.3 | Auth middleware — LLM endpoints | `app/routes/openai.py` |

### Phase 6: Testing & Deployment (1-2 ngày)

| Bước | Mô tả |
|------|-------|
| 6.1 | Test non-streaming: curl → response |
| 6.2 | Test streaming: curl -N → SSE events |
| 6.3 | Test error: worker die, client disconnect, timeout |
| 6.4 | Test scale-up: pending LLM tasks → auto launch |
| 6.5 | Test billing: balance deduction + refund |
| 6.6 | Test rotation: LLM worker hết 3h45m → replacement |
| 6.7 | Deploy lên server thật |

### Tổng thời gian ước tính: **8-12 ngày**

---

*Hết tài liệu kế hoạch.*
