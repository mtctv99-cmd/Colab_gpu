# Kế hoạch Triển khai Multi-VPS (Kiến trúc Phân tán)

Mục tiêu của kế hoạch này là tách biệt việc khởi tạo và duy trì kết nối Colab (Worker) ra khỏi Server chính, phân bổ công việc này cho nhiều máy chủ vệ tinh (Satellite VPS) có IP khác nhau. Điều này giúp qua mặt cơ chế kiểm tra IP của Google Colab, cho phép scale lên nhiều Worker chạy song song.

## User Review Required
> [!IMPORTANT]
> **Quyết định Mô hình Kiến trúc**
> Có 2 cách để dùng Multi-VPS. Anh cần xem qua và quyết định chọn cách nào để em bắt đầu code:
> 
> 1. **Cách 1 (Proxy qua VPS - Khuyên dùng vì dễ nhất):** Server chính vẫn chạy toàn bộ code. Ta chỉ cài phần mềm Proxy (vd: `squid` hoặc `3proxy`) lên các VPS phụ. Server chính sẽ điều khiển `colab-cli` đi qua các Proxy này. Không cần sửa lại Database hay tách code.
> 2. **Cách 2 (Satellite Daemon - Kiến trúc Microservice):** Tách phần code `colab-cli` ra thành một Tool nhỏ (Daemon). Các VPS phụ sẽ tải Tool này về chạy. VPS phụ sẽ gọi API về Server Chính để xin lệnh "Đăng nhập tài khoản A", sau đó tự nó bắn API lên Google.

Kế hoạch dưới đây được viết tập trung cho **Cách 2 (Satellite Daemon)** vì nó thể hiện đúng bản chất "Phân tán" (Distributed) mà anh yêu cầu.

## Kiến trúc Tổng quan (Cách 2)

```mermaid
graph TD
    Client[Người dùng] -->|Request TTS| Main[Server Chính - FastAPI]
    Main -->|Lưu DB| DB[(SQLite)]
    
    subgraph Vùng VPS Vệ tinh (IP Sạch)
        VPS1[VPS 1 - Daemon]
        VPS2[VPS 2 - Daemon]
        VPS3[VPS 3 - Daemon]
    end
    
    VPS1 <-->|REST API: Nhận Job & Báo cáo| Main
    VPS2 <-->|REST API: Nhận Job & Báo cáo| Main
    VPS3 <-->|REST API: Nhận Job & Báo cáo| Main
    
    VPS1 -->|colab-cli API| Google1[Google Colab 1]
    VPS2 -->|colab-cli API| Google2[Google Colab 2]
    VPS3 -->|colab-cli API| Google3[Google Colab 3]
    
    Google1 -->|WebSocket Audio| Main
    Google2 -->|WebSocket Audio| Main
    Google3 -->|WebSocket Audio| Main
```

### Các thành phần:
1. **Main Server (Master):** Chạy DB SQLite, giao diện Web, xử lý logic TTS. Đóng vai trò là trung tâm điều phối (Orchestrator API).
2. **Satellite VPS (Node):** Một máy chủ Linux cấu hình thấp (1GB RAM là đủ). Chạy một script Python duy nhất có nhiệm vụ:
   - Polling API từ Master để nhận task: "Mày hãy chạy tài khoản `admin@gmail.com` đi".
   - Kéo file `token.json` tương ứng từ Master về.
   - Chạy `colab-cli` bằng IP của chính nó.
   - Truyền tham số `PUBLIC_SERVER_URL` của Master vào đoạn mã khởi chạy trên Colab để Colab Worker biết đường cắm WebSocket ngược về Master.

## Các bước triển khai (Proposed Changes)

---

### Phase 1: Xây dựng Orchestrator API trên Server Chính

Cần mở thêm một số Endpoints bảo mật (dùng một `NODE_API_KEY` cố định) để các Node vệ tinh giao tiếp.

#### [NEW] `app/routes/node.py`
Tạo router mới chứa các API:
- `GET /api/node/jobs`: Node gọi để lấy thông tin tài khoản Google đang rảnh cần được khởi chạy.
- `GET /api/node/token/{email}`: Tải file token OAuth của tài khoản để Node dùng.
- `POST /api/node/status`: Node báo cáo trạng thái (đã chạy thành công, PID keep-alive, bị lỗi 403, lỗi 503...).

#### [MODIFY] `app/main.py`
- Đăng ký `app.include_router(node.router)`.
- Vô hiệu hóa tính năng tự động chạy `WorkerManager` nội bộ nếu đang bật chế độ Multi-VPS.

---

### Phase 2: Chỉnh sửa Database & Logic Phân phát

#### [MODIFY] `app/models/user.py` (Bảng GoogleAccount)
- Thêm trường `assigned_node_id` (String): Ghi nhận tài khoản này đang được Node vệ tinh nào quản lý để tránh việc 2 Node cùng chạy 1 tài khoản.

#### [MODIFY] `app/orchestrator/lifecycle.py`
- Sửa lại hàm `_maintenance_loop`: Thay vì gọi trực tiếp `worker_manager.launch()`, hàm này chỉ đổi trạng thái của Account thành `PENDING_NODE`, chờ các Node vệ tinh gọi `GET /api/node/jobs` để bốc việc đi làm.

---

### Phase 3: Viết Script cho VPS Vệ tinh (Satellite Daemon)

#### [NEW] `satellite/daemon.py`
Tạo một thư mục mới độc lập chứa code cho vệ tinh. Đoạn code này là một vòng lặp `while True` liên tục:
1. Gửi request `GET {MASTER_URL}/api/node/jobs`.
2. Nếu có Job, gọi API lấy `token.json` lưu vào ổ cứng local (`~/.config/colab-cli/`).
3. Dùng nguyên xi logic gọi `Client(Prod(), _creds)` như cũ để assign GPU T4.
4. Gửi đoạn mã Python lên Colab, ép Colab phải connect WebSocket về `{MASTER_URL}`.
5. Cập nhật trạng thái thành công/thất bại về Master.

---

### Phase 4: Thiết lập Hạ tầng thực tế (Phần việc của Anh)
1. Mua 2-3 VPS giá rẻ (như Cloudzy, Vultr, DigitalOcean gói 4$/tháng).
2. Cài đặt Python 3.10+ trên các VPS này.
3. Chép thư mục `satellite/` lên VPS và chạy lệnh: 
   `python daemon.py --master-url https://api.ttsdubbing.com --api-key SECRET_KEY`
4. Dùng lệnh `tmux` hoặc `systemd` để treo Daemon chạy ngầm 24/7.

## Verification Plan

### Bắt buộc review trước khi code:
Anh vui lòng xác nhận xem anh muốn em code theo **Kiến trúc Daemon (Cách 2)** này, hay anh thích em hướng dẫn anh **Cài đặt Proxy lên VPS (Cách 1)** để giữ cho code hiện tại đơn giản không bị xé lẻ ra?
