# Tài liệu tích hợp API - Clone TTS Server

Tài liệu này hướng dẫn cách kết nối và tích hợp ứng dụng bên thứ ba với hệ thống Clone TTS Server sử dụng API Key không giới hạn vừa được khởi tạo.

---

## 🔑 1. Thông tin xác thực (Authentication)

Tất cả các yêu cầu API phải đính kèm khóa API dưới dạng **Bearer Token** trong tiêu đề `Authorization`:

```http
Authorization: Bearer sk_8207a6dc494425dfa47fc984f900aa05528019681b747f7f743aac5f5fb1f787
```

> [!IMPORTANT]
> Đây là khóa API quyền **Admin (Không giới hạn số ký tự/balance)**. Vui lòng bảo mật kỹ khóa này và không để lộ trong mã nguồn phía Client (Frontend).

---

## 🛰️ 2. Các Endpoint chính

### 🔹 A. Sinh giọng nói đơn lẻ (Đồng bộ)
Chuyển đổi một đoạn văn bản ngắn thành giọng nói. API này là **đồng bộ (synchronous)**: kết nối sẽ giữ nguyên cho đến khi máy ảo Colab tạo xong audio và trả về file `.wav` trực tiếp.

* **Endpoint:** `POST /api/tts/text`
* **Content-Type:** `application/json`
* **Tham số Request:**
  ```json
  {
    "text": "Xin chào thế giới, đây là văn bản chạy thử nghiệm.",
    "voice_id": 1,
    "language": "vi"
  }
  ```
  *(Lưu ý: `language` có thể truyền `"vi"`, `"en"` hoặc `null` để tự động nhận diện).*
* **Phản hồi (Response):** File nhị phân âm thanh `audio/wav` trực tiếp (status `200`).

---

### 🔹 B. Sinh giọng nói hàng loạt (Bất đồng bộ - Đã tối ưu)
Gửi cùng lúc nhiều đoạn văn bản để xử lý song song trên nhiều worker máy ảo Colab cùng lúc (Hỗ trợ tối đa lên đến 8 worker chạy song song).

* **Endpoint:** `POST /api/tts/batch`
* **Content-Type:** `application/json`
* **Tham số Request:**
  ```json
  {
    "voice_id": 1,
    "language": "vi",
    "batch": true,
    "texts": [
      "Đoạn văn bản thứ nhất cần sinh giọng.",
      "Đoạn văn bản thứ hai cần xử lý song song.",
      "Văn bản thứ ba chạy trên một máy ảo khác."
    ],
    "webhook_url": "https://your-server.com/api/tts-callback"
  }
  ```
  *(Lưu ý: `webhook_url` là tùy chọn nhưng **phải sử dụng giao thức HTTPS**).*
* **Phản hồi (Response):** Trả về ngay lập tức danh sách các `task_id` tương ứng với trạng thái ban đầu (`PROCESSING` nếu có worker rảnh để xử lý ngay, hoặc `PENDING` nếu chờ xếp hàng).
  ```json
  {
    "batch": true,
    "voice_id": 1,
    "language": "vi",
    "webhook_url": "https://your-server.com/api/tts-callback",
    "tasks": [
      {
        "text": "Đoạn văn bản thứ nhất cần sinh giọng.",
        "task_id": "806ec001-c81b-4cf7-9a4d-8ff78b2d1002",
        "status": "PROCESSING"
      },
      {
        "text": "Đoạn văn bản thứ hai cần xử lý song song.",
        "task_id": "23fa3001-bc8b-4b11-9a72-7ff72a1d3004",
        "status": "PROCESSING"
      }
    ]
  }
  ```

---

### 🔹 C. Kiểm tra trạng thái Task & Tải file
Sử dụng nếu bạn không dùng Webhook mà muốn chủ động kéo dữ liệu (Polling).

1. **Xem trạng thái chi tiết của Task:**
   * **Endpoint:** `GET /api/tasks/{task_id}`
   * **Phản hồi (Response):**
     ```json
     {
       "id": "806ec001-c81b-4cf7-9a4d-8ff78b2d1002",
       "text": "Đoạn văn bản thứ nhất...",
       "status": "COMPLETED", // PENDING | PROCESSING | COMPLETED | FAILED
       "result_audio_path": "/data/voices/thanh-chua/output/806ec001.wav",
       "error_message": null
     }
     ```

2. **Tải file âm thanh sau khi Task hoàn thành:**
   * **Endpoint:** `GET /api/tasks/{task_id}/audio`
   * **Phản hồi:** File âm thanh `audio/wav` (status `200`).

---

## 🔗 3. Định dạng Webhook Callback
Khi bạn truyền `webhook_url`, server sẽ gửi yêu cầu `POST` với payload dạng JSON đến endpoint của bạn sau khi **toàn bộ các đoạn văn bản trong Batch đã xử lý xong**:

* **Method:** `POST`
* **Payload:**
  ```json
  {
    "batch_id": "879200aa-b892-4af7-a921-2ff72e11a2f0",
    "status": "COMPLETED",
    "tasks": [
      {
        "task_id": "806ec001-c81b-4cf7-9a4d-8ff78b2d1002",
        "text": "Đoạn văn bản thứ nhất cần sinh giọng.",
        "status": "COMPLETED",
        "audio_url": "/api/tasks/806ec001-c81b-4cf7-9a4d-8ff78b2d1002/audio",
        "error_message": null
      },
      {
        "task_id": "23fa3001-bc8b-4b11-9a72-7ff72a1d3004",
        "text": "Đoạn văn bản thứ hai cần xử lý song song.",
        "status": "COMPLETED",
        "audio_url": "/api/tasks/23fa3001-bc8b-4b11-9a72-7ff72a1d3004/audio",
        "error_message": null
      }
    ]
  }
  ```

---

## 💻 4. Ví dụ code mẫu (Integration Examples)

### 🐍 Python (sử dụng `httpx`)
```python
import httpx
import time

SERVER_URL = "http://localhost:8090"  # Thay bằng domain server thực tế
API_KEY = "sk_8207a6dc494425dfa47fc984f900aa05528019681b747f7f743aac5f5fb1f787"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# 1. Gọi TTS đơn lẻ (Đồng bộ)
def generate_single_tts(text: str, voice_id: int):
    url = f"{SERVER_URL}/api/tts/text"
    payload = {"text": text, "voice_id": voice_id}
    
    with httpx.Client(timeout=120.0) as client:
        print("Đang sinh giọng...")
        resp = client.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            with open("output.wav", "wb") as f:
                f.write(resp.content)
            print("Lưu file output.wav thành công!")
        else:
            print(f"Lỗi: {resp.status_code} - {resp.text}")

# 2. Gọi TTS Batch với Polling
def generate_batch_tts(texts: list[str], voice_id: int):
    url = f"{SERVER_URL}/api/tts/batch"
    payload = {"texts": texts, "voice_id": voice_id}
    
    with httpx.Client() as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        batch_data = resp.json()
        tasks = batch_data["tasks"]
        print(f"Khởi tạo Batch thành công với {len(tasks)} tasks.")
        
        # Vòng lặp Polling kiểm tra trạng thái
        completed_files = {}
        pending_task_ids = [t["task_id"] for t in tasks]
        
        while pending_task_ids:
            time.sleep(3) # Polling mỗi 3 giây
            for tid in list(pending_task_ids):
                task_resp = client.get(f"{SERVER_URL}/api/tasks/{tid}", headers=headers)
                task_data = task_resp.json()
                status = task_data["status"]
                print(f"Task {tid}: {status}")
                
                if status == "COMPLETED":
                    # Tải audio
                    audio_resp = client.get(f"{SERVER_URL}/api/tasks/{tid}/audio", headers=headers)
                    completed_files[tid] = audio_resp.content
                    pending_task_ids.remove(tid)
                elif status == "FAILED":
                    print(f"Task {tid} thất bại: {task_data.get('error_message')}")
                    pending_task_ids.remove(tid)
                    
        print(f"Hoàn thành tải {len(completed_files)} file âm thanh!")
```

### 🌐 Node.js (JavaScript / Fetch)
```javascript
const SERVER_URL = "http://localhost:8090";
const API_KEY = "sk_8207a6dc494425dfa47fc984f900aa05528019681b747f7f743aac5f5fb1f787";

// 1. Tạo Batch TTS bất đồng bộ (sử dụng Webhook)
async function createBatchTTS(texts, voiceId, webhookUrl) {
  const url = `${SERVER_URL}/api/tts/batch`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      texts: texts,
      voice_id: voiceId,
      webhook_url: webhookUrl
    })
  });
  
  if (!response.ok) {
    throw new Error(`Lỗi khởi tạo: ${await response.text()}`);
  }
  
  const result = await response.json();
  console.log("Khởi tạo batch thành công, chi tiết tasks:", result.tasks);
  return result;
}
```

---

## ⚡ 5. Các tối ưu hóa hệ thống đã thực hiện
* **Tối đa 8 Worker song song:** Cấu hình hệ thống đã được mở rộng giới hạn `MAX_WORKERS = 8` để hỗ trợ quy mô tải lớn.
* **Tối ưu hóa tốc độ Batch:** Lược bỏ cơ chế ghi và làm mới dữ liệu lặp lại liên tục lên SQLite (`db.refresh(task)` trong vòng lặp), giúp tốc độ phản hồi tạo Batch tăng gấp nhiều lần.
* **Gán luồng thông minh (Instant Routing):** Khi nhận một Batch, hệ thống sẽ ngay lập tức dò tìm các worker rảnh (`IDLE`) đang duy trì kết nối WebSocket để gán trực tiếp dưới dạng tác vụ chạy ngầm bất đồng bộ. Worker sẽ xử lý ngay lập tức thay vì phải chờ đợi vòng quét tuần tự của duy trì bảo trì (Maintenance Loop) như cũ.
