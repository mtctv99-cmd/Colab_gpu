# Kiến trúc điều phối Master + Satellite Node

## Hiện trạng

Master không biết satellite nào còn sống. Satellite poll job, master trả đại 1 account `PENDING_NODE`. Nếu satellite chết, account treo vĩnh viễn. `MAX_WORKERS=1` chỉ cho chạy 1 worker tổng cộng — không thể có local + satellite đồng thời.

## Mục tiêu

1. Master luôn có **1 local worker** chạy ổn định
2. **Satellite registry**: Master biết node nào đang online, dung lượng bao nhiêu
3. **Satellite không tự ý launch Colab** — chỉ làm theo lệnh master
4. **Priority dispatch**: Local worker ưu tiên, satellite hỗ trợ khi quá tải
5. **Tiết kiệm quota**: Chỉ launch worker Colab khi có task thực sự

---

## Kiến trúc mới

```
                         MASTER SERVER
┌──────────────────────────────────────────────────────┐
│  SatelliteRegistry           PoolManager              │
│  ├─ node_id → last_seen      ├─ MAX_LOCAL=1          │
│  ├─ capacity                 ├─ MAX_TOTAL=8          │
│  ├─ active_workers           ├─ select_account()     │
│  └─ status                   └─ claim_atomic()       │
│                                                       │
│  Dispatcher (priority-based)                          │
│  ├─ Local worker trước                                │
│  ├─ Nếu BUSY → satellite workers                      │
│  ├─ Nếu không ai rảnh → launch mới                    │
│  └─ FIFO fallback                                     │
│                                                       │
│  Maintenance Loop (2s)                                │
│  ├─ Satellite heartbeat check                         │
│  ├─ PENDING_NODE reaper (>5m)                         │
│  ├─ Dispatch scheduler                                │
│  └─ Scale check                                       │
└──────────────┬───────────────────────────────────────┘
               │
    ┌──────────┴──────────┐
    ▼                     ▼
Local Worker          Satellite Node A
(Colab T4)            (VPS)
    │                     │
    └── WS ──────────────┘ ──► Worker B (Colab T4)
                                  Worker C (Colab T4)
```

---

## Chi tiết thay đổi

### 1. Constants — Tách MAX_WORKERS

**File**: `app/orchestrator/constants.py`

```python
# Giới hạn worker
MAX_LOCAL_WORKERS = 1        # local luôn giữ 1 worker
MAX_WORKERS_PER_NODE = 2     # mỗi satellite tối đa 2 worker
MAX_TOTAL_WORKERS = 8        # tổng toàn hệ thống

# Timeout
PENDING_NODE_TIMEOUT = 300   # 5 phút — reaper cho account PENDING_NODE
SATELLITE_HEARTBEAT_TIMEOUT = 90  # 3 lần miss heartbeat = dead
```

### 2. SatelliteRegistry — class mới

**File**: `app/orchestrator/satellite_registry.py`

```python
class SatelliteRegistry:
    """Track alive satellite nodes and their capacity."""

    def __init__(self):
        self.nodes: dict[str, SatelliteInfo] = {}

    async def heartbeat(self, node_id: str, capacity: int, active_workers: int, version: str = ""):
        """Update node's last_seen timestamp."""

    async def get_healthy_nodes(self) -> list[SatelliteInfo]:
        """Return nodes with last_seen < SATELLITE_HEARTBEAT_TIMEOUT."""

    async def get_total_capacity(self) -> int:
        """Sum of capacities of all healthy nodes."""

    async def cleanup_stale(self):
        """Mark nodes with expired heartbeat as OFFLINE."""

    async def get_node_for_account(self, email: str) -> str | None:
        """Find which node owns a given account."""
```

### 3. Node routes — thêm heartbeat + node list

**File**: `app/routes/node.py`

```python
@router.post("/heartbeat")
async def node_heartbeat(
    data: NodeHeartbeat,
    _=Depends(verify_node_key)
):
    """Satellite gửi heartbeat mỗi 30s."""
    await satellite_registry.heartbeat(
        node_id=data.node_id,
        capacity=data.capacity,
        active_workers=data.active_workers,
        version=data.version
    )
    # Trả về số lượng job available cho node này
    pending = await pool_manager.pending_tasks(db)
    return {
        "jobs_available": pending,
        "max_launch": min(data.capacity - data.active_workers, pending)
    }

@router.get("/list")
async def node_list(admin=Depends(require_admin)):
    """Admin xem danh sách satellite nodes."""
    return satellite_registry.get_all()
```

### 4. Dispatch priority

**File**: `app/routes/ws.py` — `_handle_status()`

Hiện tại:
```python
if status == "IDLE":
    task = select next PENDING task
    dispatch(task, email, wsid)
```

Sửa thành:
```python
if status == "IDLE":
    info = manager.worker_info.get(email, {})
    is_local = info.get("is_local", False)

    if is_local:
        # Local worker luôn được dispatch ngay
        task = select next PENDING task
        if task:
            dispatch(task, email, wsid)
    else:
        # Satellite worker: chỉ dispatch nếu local worker BUSY
        # hoặc pending queue > threshold
        local_idle = manager.get_local_idle_worker()
        pending_count = count pending tasks
        if not local_idle or pending_count > SATELLITE_DISPATCH_THRESHOLD:
            task = select next PENDING task
            if task:
                dispatch(task, email, wsid)
```

### 5. Scale check — phân luồng local vs satellite

**File**: `app/orchestrator/lifecycle.py` — `scale_check()`

```python
async def scale_check():
    # 1. Local worker: luôn giữ MAX_LOCAL_WORKERS
    local_active = count local WS-connected workers
    if local_active < MAX_LOCAL_WORKERS and ready_accounts > 0:
        launch local worker
        return

    # 2. Satellite: chỉ launch khi có pending tasks
    pending = await pool_manager.pending_tasks(db)
    if pending == 0:
        return

    # 3. Tính capacity khả dụng từ satellite registry
    satellite_capacity = satellite_registry.get_total_capacity()
    satellite_active = count satellite-launched workers
    available = satellite_capacity - satellite_active

    if available > 0 and pending > 0:
        # Mark accounts as PENDING_NODE cho satellite pickup
        to_launch = min(available, pending, MAX_WORKERS_PER_NODE)
        for _ in range(to_launch):
            email = await pool_manager.select_account_for_launch(db)
            if email:
                mark PENDING_NODE, assigned_node_id = ...
```

### 6. PENDING_NODE reaper

**File**: `app/orchestrator/lifecycle.py` — `heartbeat_check()` hoặc function riêng

```python
async def pending_node_reaper():
    """Giải phóng account bị satellite bỏ rơi."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=PENDING_NODE_TIMEOUT)
    async with async_session() as db:
        res = await db.execute(
            select(GoogleAccount).where(
                GoogleAccount.runtime_status == PENDING_NODE,
                GoogleAccount.started_at < cutoff
            )
        )
        for acc in res.scalars().all():
            # Check xem assigned node còn sống không
            node_id = acc.assigned_node_id
            if node_id and satellite_registry.is_alive(node_id):
                continue  # Node còn sống, chờ thêm
            # Node chết hoặc không có node_id → release
            acc.runtime_status = None
            acc.worker_session_id = None
            acc.assigned_node_id = None
            acc.started_at = None
            logger.warning("Reaped stale PENDING_NODE for %s", acc.email)
        await db.commit()
```

### 7. ConnectionManager — phân loại worker local/satellite

**File**: `app/services/connection_manager.py`

```python
class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}
        self.worker_info: dict[str, dict] = {}
        self.workers_by_type: dict[str, list[str]] = {"tts": []}

    def get_local_idle_worker(self) -> str | None:
        """Chỉ tìm worker local (do master tự launch)."""
        ...

    def get_satellite_idle_worker(self) -> str | None:
        """Chỉ tìm worker do satellite launch."""
        ...

    def get_idle_worker(self) -> str | None:
        """Tìm tất cả (local ưu tiên)."""
        local = self.get_local_idle_worker()
        if local:
            return local
        return self.get_satellite_idle_worker()
```

### 8. Satellite Daemon — thêm heartbeat

**File**: `satellite_node/daemon.py` (và `npm-package/core/daemon.py`)

```python
HEARTBEAT_INTERVAL = 30
CAPACITY = int(os.getenv("NODE_CAPACITY", "2"))  # mỗi node chạy tối đa 2 worker

async def heartbeat_loop():
    while True:
        payload = {
            "node_id": NODE_ID,
            "capacity": CAPACITY,
            "active_workers": len(running_workers),
            "version": VERSION
        }
        try:
            res = await client.post(
                f"{MASTER_URL}/api/node/heartbeat",
                json=payload, headers=HEADERS
            )
            if res.status_code == 200:
                data = res.json()
                jobs_available = data.get("jobs_available", 0)
                max_launch = data.get("max_launch", 0)
                # Master bảo có thể launch thêm
                if max_launch > 0 and len(running_workers) < CAPACITY:
                    # Kích hoạt poll job nhanh hơn
                    poll_interval = 2
        except Exception:
            pass
        await asyncio.sleep(HEARTBEAT_INTERVAL)

async def main():
    asyncio.create_task(heartbeat_loop())
    # Poll job interval linh hoạt dựa trên heartbeat response
    ...
```

---

## Luồng xử lý mới

### Khi có task mới đến

```
Request TTS đến master
  ├─ Tạo Task(PENDING), deduct balance
  ├─ get_idle_worker() → ưu tiên local
  │
  ├─ [Local IDLE] → dispatch ngay (~3-5s)
  │
  ├─ [Local BUSY, satellite có IDLE] → dispatch cho satellite
  │
  ├─ [Không ai rảnh, có pending task]
  │   ├─ scale_check() gọi launch local worker nếu thiếu
  │   └─ Nếu local đã đủ → mark PENDING_NODE cho satellite
  │
  └─ [Chờ] event-driven wait 120s, nếu timeout → 504
```

### Khi satellite heartbeat

```
Satellite gửi heartbeat (30s/lần)
  ├─ Master cập nhật last_seen + capacity
  ├─ Master kiểm tra: có pending task không?
  │   ├─ Có → mark thêm account PENDING_NODE
  │   └─ Không → không làm gì (tiết kiệm quota)
  └─ Trả về: jobs_available, max_launch
```

### Khi satellite chết

```
Maintenance loop (10s)
  ├─ SatelliteRegistry.cleanup_stale()
  │   └─ Node last_seen > 90s → mark OFFLINE
  │
  ├─ pending_node_reaper()
  │   └─ Account PENDING_NODE > 5 phút → release
  │
  └─ Worker cũ do satellite launch vẫn sống
      (WS trực tiếp với master, không phụ thuộc satellite)
```

---

## Các file cần thay đổi

| File | Thay đổi | Ưu tiên |
|---|---|---|
| `app/orchestrator/satellite_registry.py` | **MỚI** — class SatelliteRegistry | P0 |
| `app/orchestrator/constants.py` | Thêm MAX_LOCAL, MAX_PER_NODE, timeout | P0 |
| `app/routes/node.py` | Thêm `/heartbeat`, `/list` | P0 |
| `app/orchestrator/lifecycle.py` | Sửa scale_check, thêm pending_node_reaper | P0 |
| `app/routes/ws.py` | Sửa _handle_status — priority dispatch | P1 |
| `app/services/connection_manager.py` | Thêm get_local/satellite_idle_worker | P1 |
| `satellite_node/daemon.py` | Thêm heartbeat_loop + CAPACITY | P0 |
| `npm-package/core/daemon.py` | Giống satellite_node | P0 |

---

## Rủi ro & Lưu ý

1. **Worker local vs satellite conflict**: Account có thể bị cả local và satellite cùng claim. Cần atomic CLAIM + kiểm tra `assigned_node_id`.

2. **WS trực tiếp giữa worker và master**: Worker trên Colab kết nối WS thẳng master, không qua satellite. Nếu satellite chết, worker vẫn sống.

3. **Token đồng bộ**: Master cần track account nào đã được satellite fetch token. Tránh local launch account đang chờ satellite.

4. **Capacity ảo**: Satellite báo capacity=2 nhưng Colab có thể từ chối (503). Cần failover cơ chế.

5. **Backward compatible**: Node cũ (không heartbeat) vẫn poll job bình thường. Heartbeat là optional — node cũ chỉ không được ưu tiên dispatch.
