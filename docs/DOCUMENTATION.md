# Tài liệu hệ thống TTS Dubbing (v3)

Hệ thống đã được refactor toàn diện từ kiến trúc v2 (dùng browser automation) sang v3 (dùng official google-colab-cli).

## 1. Thay đổi cốt lõi (Backend)
- **Engine quản lý Worker**: Thay thế hoàn toàn Playwright browser automation bằng `google-colab-cli`.
- **Độ ổn định**: CLI giúp worker kết nối trực tiếp đến kernel Colab, không bị treo do trình duyệt, giảm sử dụng RAM.
- **Tích hợp CLI**: 
    - CLI Runner: Quản lý session, heartbeat, runtime kernel trực tiếp qua `colab_cli.runtime`.
    - Tự động hóa: Cơ chế Scaling và Rotation giữ nguyên logic từ v2 nhưng gọi CLI API.
    - Quản lý tài khoản: Sử dụng file config riêng cho mỗi email (trong `~/.config/colab-cli/`) để cách ly token.

## 2. Thay đổi giao diện (Frontend)
- **Thiết kế**: Chuyển toàn bộ sang Shadcn UI + Tailwind CSS.
- **Layout**: Sidebar Navigation đồng bộ trên cả Dashboard và Admin Panel.
- **Components**: Thay thế 100% các table, button, input legacy bằng components tiêu chuẩn (professional look).
- **Trải nghiệm**: Dùng `AlertDialog` cho các thao tác nguy hiểm (xóa/stop/deactivate).

## 3. Cấu trúc lưu trữ
- DB `GoogleAccount`: Cột `colab_pid` lưu trữ process ID của CLI keep-alive daemon.
- Cấu hình CLI: Mỗi tài khoản lưu `token_{email}.json` và `sessions_{email}.json`.
