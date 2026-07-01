# TTS Dubbing System — Review tổng hợp lỗi & thiếu sót

## Mục lục

- [A. Core Bugs (dừng production ngay nếu chưa fix)](#a-core-bugs-dừng-production-ngay-nếu-chưa-fix)
- [B. Logic Duplicate (tăng chi phí maintain)](#b-logic-duplicate-tăng-chi-phí-maintain)
- [C. Architecture (không scale được)](#c-architecture-không-scale-được)
- [D. Module Status](#d-module-status)
- [E. Priority Roadmap](#e-priority-roadmap)

---

## A. Core Bugs (dừng production ngay nếu chưa fix)

### A1. OUT_OF_QUOTA handler — pending_direct_events không bao giờ fire

| Field | Value |
|---|---|
| File | `app/routes/ws.py:537-543` |
| Mức độ | 🔴 Cao — caller treo 120s rồi timeout |
| Loại | Bug logic |

```python
# Bug: worker_id đã bị set NULL ở dòng 522-525
await db.execute(
    update(Task).where(Task.worker_id == acc.id, Task.status == "PROCESSING")
    .values(status="PENDING", worker_id=None, ...)
)
await db.commit()

# Query này trả về 0 rows vì worker_id = NULL
affected_t = await db.execute(
    select(Task).where(Task.worker_id == acc.id)  # ← sai
)
```

**Cơ chế**: Khi worker báo OUT_OF_QUOTA, handler UPDATE tất cả PROCESSING tasks thành PENDING và set worker_id=NULL. Sau đó SELECT task theo worker_id (đã NULL) → không tìm thấy task nào → `_pending_direct_events` không bao giờ được set → request sync đang chờ task treo đến 120s timeout.

**Fix**: Lưu danh sách task_id vào biến trước khi UPDATE, hoặc query bằng email account thay vì worker_id.

### A2. Worker deploy fail — không unassign Colab runtime

| Field | Value |
|---|---|
| File | `satellite_node/daemon.py:107-138` + `npm-package/core/daemon.py` |
| Mức độ | 🔴 Cao — leak T4 quota 90 phút |
| Loại | Missing cleanup |

```python
# assign() thành công → runtime được cấp
res = await loop.run_in_executor(None, _client.assign, ...)
# ...
try:
    # deploy thất bại
    await loop.run_in_executor(None, lambda: _rt.execute_code(_deploy_code, timeout=300))
except Exception as e:
    await report_status(email, "FAILED", error=str(e))
    return  # ← KHÔNG unassign runtime! Quota mất
```

**So sánh**: Server code `worker_manager.launch()` có cleanup:
```python
# app/orchestrator/worker.py:266-276
try:
    await loop.run_in_executor(None, _client.unassign, endpoint)
except Exception:
    pass
```

### A3. `_consecutive_503` không bao giờ reset

| Field | Value |
|---|---|
| File | `app/orchestrator/worker.py:163` |
| Mức độ | 🔴 Cao — account bị NO_QUOTA vĩnh viễn |
| Loại | Missing state management |

```python
if code == 503:
    self._consecutive_503[email] = self._consecutive_503.get(email, 0) + 1
    fails = self._consecutive_503[email]
    if fails >= 4:
        acc.status = NO_QUOTA
    # raise ở đây
```

Counter KHÔNG reset khi launch thành công. Launch fail 2 lần (counter=2), lần 3 thành công → counter vẫn 2 → lần sau chỉ cần 1 lần 503 là NO_QUOTA.

**Fix**: Reset counter trong khối `try` sau khi assign + deploy thành công.

### A4. Path worker.py sai trong npm-package

| Field | Value |
|---|---|
| File | `satellite_node/daemon.py:109` (giống trong npm-package) |
| Mức độ | 🔴 Cao — crash ngay khi launch worker |
| Loại | Path error |

```python
open(os.path.join(os.path.dirname(__file__), "../colab/worker.py"), "rb")
```

| Context | Kết quả | Status |
|---|---|---|
| `satellite_node/daemon.py` | `satellite_node/../colab/worker.py` = `colab/worker.py` | ✅ |
| `npm-package/core/daemon.py` | `npm-package/core/../colab/worker.py` = `npm-package/colab/worker.py` | ❌ Không tồn tại |

**Fix**: Dùng:
```python
os.path.join(os.path.dirname(__file__), "colab", "worker.py")
```

### A5. Race condition — `select_account_for_launch` trả về cùng email

| Field | Value |
|---|---|
| File | `app/orchestrator/pool.py:63-89` |
| Mức độ | 🔴 Trung bình — launch cùng account 2 lần |
| Loại | Race condition |

```python
async def select_account_for_launch(self, db):
    ...
    for acc in accounts:  # không có FOR UPDATE
        if ...: return acc.email
    return None
```

SQLite không hỗ trợ `SELECT ... FOR UPDATE`. Hai caller đồng thời nhận cùng account. Per-email lock trong `launch()` ngăn chạy song song nhưng vẫn gọi Colab API 2 lần, launch 2 lần không cần thiết.

### A6. `node.py` không validate worker_session_id unique

| Field | Value |
|---|---|
| File | `app/routes/node.py:80` |
| Mức độ | 🔴 Trung bình — session_id có thể trùng |
| Loại | Missing validation |

```python
if data.worker_session_id:
    acc.worker_session_id = data.worker_session_id
```

Không kiểm tra worker_session_id có bị trùng với account khác không.

---

## B. Logic Duplicate (tăng chi phí maintain)

### B1. Task requeue code lặp 3 lần

**File**: `app/routes/ws.py`

| Vị trí | Trigger | Dòng |
|---|---|---|
| Heartbeat loop | Worker timeout | 310-322 |
| Disconnect handler | WS mất kết nối | 470-482 |
| `_handle_status` | OUT_OF_QUOTA | 522-533 |

Cả 3 đều làm: reset PROCESSING → PENDING, clear worker_id/worker_session_id/leased_at, fire `_pending_direct_events`. Extract thành 1 hàm chung.

### B2. Hai scale-up path riêng biệt

| Path | File | Trigger |
|---|---|---|
| `_maybe_scale_up()` | `ws.py:30` | Request handler + `_handle_status` |
| `scale_check()` | `lifecycle.py:259` | Maintenance loop (10s) |

Không có cơ chế phối hợp → có thể launch thừa worker trong cùng 1 chu kỳ.

### B3. Webhook firing duplicate

| File | Function |
|---|---|
| `app/orchestrator/dispatcher.py:205` | `fire_webhook()` |
| `app/routes/tasks.py:230` | `_fire_webhook_if_batch_complete()` |

Logic giống hệt nhau: đếm pending tasks còn lại trong batch, nếu hết thì POST payload lên webhook_url.

### B4. Server code duplicate trong npm-package

| Component | Bản gốc | Bản sao |
|---|---|---|
| colab_cli/ | `app/colab_cli/` (17 files) | `npm-package/core/app/colab_cli/` |
| worker.py | `colab/worker.py` | `npm-package/core/colab/worker.py` |
| daemon.py | `satellite_node/daemon.py` | `npm-package/core/daemon.py` |

### B5. `launch()` vs `launch_llm_worker()` — ~80% giống

| File | Function | Dòng |
|---|---|---|
| `app/orchestrator/worker.py:120` | `launch()` | ~160 dòng |
| `app/orchestrator/worker.py:318` | `launch_llm_worker()` | ~160 dòng |

### B6. `shutdown_immediate()` vs `shutdown_graceful()` — ~95% giống

**File**: `app/orchestrator/worker.py:478` và `:542`

---

## C. Architecture (không scale được)

### C1. Global mutable state

Tất cả đều là module-level singleton, không thể scale ngang:

| Variable | File | Purpose |
|---|---|---|
| `ConnectionManager` instance | `ws.py:348` | active WS, worker_info, heartbeat |
| `_pending_direct_events` | `ws.py:23` | asyncio.Event cho sync TTS callers |
| `_pending_llm_events` | `ws.py:26` | asyncio.Event cho LLM callers |
| `_streaming_queues` | `ws.py:27` | Queue cho LLM streaming |
| `_dashboard_clients` | `ws.py:22` | Dashboard WS clients |
| `_background_tasks` | `ws.py:158` | asyncio.Task tracking |
| `_rate_limit_store` | `main.py:121` | Per-IP rate limit (OrderedDict) |
| `_login_attempts` | `auth.py:141` | Brute force tracking |
| `_login_attempts_ip` | `auth.py:142` | Brute force tracking (IP) |
| `_rotation_state` | `lifecycle.py:101` | Rotation phase tracking |
| `_consecutive_503` | `worker.py:41` | 503 counter per email |

### C2. `ws.py` quá tải — 715 dòng, 10+ trách nhiệm

| Trách nhiệm | Dòng | Nên chuyển đến |
|---|---|---|
| WebSocket `/ws/worker` | 351-502 | `ws/worker.py` |
| WebSocket `/ws/dashboard` | 111-142 | `ws/dashboard.py` |
| Heartbeat loop | 259-346 | `ws/heartbeat.py` |
| Scale-up (TTS) | 30-68 | `orchestrator/` |
| Task completion handler | 591-621 | `ws/handlers.py` |
| Task failure handler | 624-650 | `ws/handlers.py` |
| LLM handlers | 653-715 | `ws/llm.py` |
| `_handle_status` | 505-587 | `ws/handlers.py` |
| Dashboard broadcast | 145-154 | `ws/dashboard.py` |
| `ConnectionManager` class | 168-348 | `services/connection_manager.py` |

### C3. Import circular chain

Hiện tại dùng lazy import (inside function) để tránh crash, nhưng dễ lỗi và khó refactor.

### C4. Route sai file

| Route | File hiện tại | File đúng |
|---|---|---|
| `GET /api/auth/tasks` | `auth.py:481` | `tasks.py` |
| `GET /api/auth/usage` | `auth.py:504` | File riêng (`routes/usage.py`) |

### C5. Config phân tán

| Config | File |
|---|---|
| `DATABASE_URL`, `HOST`, `PORT` | `app/config.py` |
| `SERVER_URL()`, `MAX_WORKERS`, constants | `orchestrator/constants.py` |
| `OMNIVOICE_NUM_STEP`, `OMNIVOICE_GUIDANCE_SCALE` | Env var đọc inline |
| `LLM_DEPLOY_TIMEOUT` | Cả `config.py:62` + `constants.py:38` |

---

## D. Module Status

### D1. Backend Server (`app/`)

| Module | Rating | Lines | Vấn đề chính |
|---|---|---|---|
| `routes/tts.py` | 🟡 Tạm ổn | 311 | Batch không refresh task (dòng 260) |
| `routes/ws.py` | 🔴 Nặng nhất | 715 | Bug A1, 10+ trách nhiệm, global state |
| `routes/auth.py` | 🟡 Ổn | 664 | Sai route tasks/usage, password reset stub |
| `routes/accounts.py` | 🟢 Sạch | 230 | |
| `routes/tasks.py` | 🟢 Ổn | 303 | Webhook duplicate B3 |
| `routes/node.py` | 🟢 Sạch | 84 | Thiếu validate wsid (A6) |
| `orchestrator/worker.py` | 🟡 Ổn | 656 | A3, B5, B6 |
| `orchestrator/lifecycle.py` | 🟡 Rối | 543 | B2, C1 (rotation_state) |
| `orchestrator/pool.py` | 🟢 Ổn | 234 | A5 |
| `orchestrator/dispatcher.py` | 🟢 Sạch | 242 | B3 |
| `database.py` | 🟡 | 114 | Migration try/except pass, không version |
| `config.py` | 🟢 Ổn | 66 | |
| `services/auth.py` | 🟢 Sạch | 116 | |

### D2. Satellite Node (`satellite_node/`)

| File | Rating | Lines | Vấn đề |
|---|---|---|---|
| `daemon.py` | 🔴 Mới, thiếu cleanup | 184 | A2, A4 |
| `install.sh` | 🟡 | 78 | `$USER` vs `$SUDO_USER` (dòng 38) |

### D3. npm-package (`npm-package/`)

| File | Rating | Lines | Vấn đề |
|---|---|---|---|
| `cli.js` | 🟡 | 151 | PID TOCTOU race, `execSync` block event loop |
| `core/daemon.py` | 🔴 | 184 | Giống satellite_node — A2, A4 |
| `core/colab/worker.py` | 🟢 | 679 | Giống hệt bản gốc — nhưng là copy |
| `core/app/colab_cli/` | 🟢 | 17 files | Giống hệt bản gốc — nhưng là copy |

---

## E. Priority Roadmap

### Phase 1 — Hotfix (làm ngay)

| ID | Mức | File | Fix |
|---|---|---|---|
| A1 | 🔴 | `ws.py:537` | Lưu task_id list trước UPDATE, query bằng email |
| A2 | 🔴 | `daemon.py:135` | Thêm try/finally unassign runtime khi deploy fail |
| A3 | 🔴 | `worker.py:163` | Reset `_consecutive_503` sau launch thành công |
| A4 | 🔴 | `daemon.py:109` | Sửa path thành `os.path.join(__dirname, "colab", "worker.py")` |

### Phase 2 — Clean architecture (tuần này)

| ID | Mức | File | Fix |
|---|---|---|---|
| B1 | 🟡 | `ws.py` | Extract task requeue → 1 hàm chung |
| B2 | 🟡 | `ws.py` + `lifecycle.py` | Gộp 2 scale-up path |
| C4 | 🟡 | `auth.py` | Move route tasks/usage về đúng file |
| B3 | 🟡 | `dispatcher.py` + `tasks.py` | Gộp 2 webhook fire |
| A5 | 🟡 | `pool.py` | Atomic claim account |

### Phase 3 — Refactor (tháng này)

| ID | Mức | File | Fix |
|---|---|---|---|
| C2 | 🟠 | `ws.py` | Tách thành `ws/` module |
| B5/B6 | 🟠 | `worker.py` | Gộp launch/shutdown |
| C5 | 🟢 | `config.py` + `constants.py` | Hợp nhất |
| D2/D3 | 🟠 | satellite + npm | Auto-sync code |

### Phase 4 — Dài hạn

| ID | Mức | Mô tả |
|---|---|---|
| C1 | 🔴 | Redis/Cache cho state |
| C3 | 🟠 | Phá vòng circular import |
| A6 | 🟠 | Validate unique worker_session_id |
| D4 | 🟢 | Database migration version tracking |
