<div align="center">
  <img src="assets/banner.svg" alt="Elvis Setup banner" width="100%" />

  <p><strong>Con Vợ Bot Của Vỹ</strong> — công cụ dựng Discord server từ template YAML.</p>

  [![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
  [![discord.py](https://img.shields.io/badge/discord.py-2.5%2B-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
  [![CI](https://github.com/elvisnguyenovno411/elvis-setup/actions/workflows/ci.yml/badge.svg)](https://github.com/elvisnguyenovno411/elvis-setup/actions/workflows/ci.yml)
  [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
</div>

## Tiếng Việt

Elvis Setup là Discord bot dùng **một lần khi tạo server mới**. Bot mở menu embed để chọn nhiều chủ đề, xem trước cấu trúc, sau đó tạo category, channel, hai role và permission phù hợp. Mỗi chủ đề được chọn trở thành một category riêng với một text room và một voice room có emoji; chủ đề không chọn sẽ không xuất hiện. Setup xong bạn có thể tắt bot; các bot miễn phí bên ngoài có thể đảm nhiệm auto-role, ticket, moderation và log 24/7.

### Điểm nổi bật

- 13 chủ đề: Gaming, Community, Học tập, Công nghệ, Bán hàng, Doanh nghiệp, Creator, Anime, Âm nhạc, Support, Esports, Bạn bè và Làm đẹp & Makeup.
- Chọn nhiều chủ đề trong một lần; có thể setup tùy chọn, tất cả hoặc chỉ phần mặc định.
- Mỗi category chủ đề có một text room và một voice room với emoji riêng.
- Chỉ Discord ID trong `OWNER_USER_ID` có thể điều khiển bot.
- Hai role duy nhất: `Admin` và `Thành viên`.
- Thành viên được chat/call, chỉ đọc thông báo và không thấy khu vực quản trị/log.
- Xem trước và xác nhận hai bước trước khi xóa cấu trúc cũ.
- Khi lỗi có thể giữ phần đã tạo hoặc hoàn tác tài nguyên mới.
- Báo cáo bằng embed, log trên máy và file JSON.
- Template YAML dễ mở rộng mà không cần sửa code Python.

> [!CAUTION]
> Setup sẽ xóa category, channel và role cũ mà bot có thể quản lý. Nội dung kênh đã xóa không thể khôi phục. Chỉ sử dụng cho server mới hoặc server thử nghiệm.

### Cài đặt nhanh trên Windows

1. Cài [Python 3.11+](https://www.python.org/downloads/) và bật tùy chọn **Add Python to PATH**.
2. Tạo Discord Application/Bot trong Developer Portal.
3. Mời bot vào server với scope `bot`, `applications.commands` và quyền `Administrator`.
4. Bấm đúp `setup.bat`, nhập bot token và Discord user ID của Elvis.
5. Bấm đúp `start.bat`, sau đó dùng `/kiem-tra` rồi `/setup` trong server.

### Cài đặt bằng dòng lệnh

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
# Chỉnh DISCORD_TOKEN và OWNER_USER_ID trong .env
python main.py
```

### Slash commands

| Lệnh | Chức năng |
|---|---|
| `/setup` | Mở menu chọn template và chế độ setup |
| `/templates` | Hiển thị danh sách template |
| `/kiem-tra` | Kiểm tra quyền Administrator và cấu hình YAML |
| `/xoa-kenh` | Xóa toàn bộ channel/category sau hai bước xác nhận |

### Ma trận quyền

| Khu vực | `@everyone` | `Thành viên` | `Admin` |
|---|---:|---:|---:|
| Chat | Ẩn | Xem + gửi tin | Toàn quyền |
| Voice | Ẩn | Xem + kết nối | Toàn quyền |
| Thông báo/Nội quy | Ẩn | Chỉ đọc | Toàn quyền |
| Quản trị/Log | Ẩn | Ẩn | Toàn quyền |

Thành viên mới cần được một bot ngoài cấp role `Thành viên` tự động. Elvis Setup không cần chạy 24/7.

### Tạo template mới

Tạo file `.yml` trong `templates/` và kế thừa cấu trúc lõi:

```yaml
extends: base
name: Tên chủ đề
description: Mô tả ngắn
emoji: "✨"
color: "5865F2"
categories:
  - key: chu-de-rieng
    name: "✨ CHỦ ĐỀ RIÊNG"
    channels:
      - name: "💬・tro-chuyen-rieng"
        type: text
        access: member
```

Giá trị `access` hợp lệ: `member`, `member_read_only`, `admin`. Loại kênh hợp lệ: `text`, `voice`.

### Bảo mật

- Không commit file `.env`; file này đã nằm trong `.gitignore`.
- Không chia sẻ bot token hoặc đưa token vào ảnh chụp màn hình.
- Nếu token từng bị lộ, hãy reset ngay trong Discord Developer Portal.
- Bot từ chối mọi lệnh không đến từ `OWNER_USER_ID`.

### Kiểm thử

```powershell
python -m pip install -e ".[dev]"
ruff check .
pytest --cov=elvis_setup
```

---

## English

Elvis Setup is a **one-shot Discord server builder** powered by Python and editable YAML templates. Users can combine multiple topics in one setup; every selected topic becomes one category with an emoji-styled text room and voice room. It creates the core categories, two roles, and a secure permission layout. Once setup is complete, the bot can be turned off; external bots can handle auto-role, tickets, moderation, and continuous logging.

### Features

- 13 ready-to-use server themes, including Gaming, Study, Technology, Esports, and Beauty & Makeup.
- Multi-topic selection plus custom, all-topics, and base-only setup workflows.
- A protected `/xoa-kenh` command for deleting all channels and categories.
- Owner-ID authorization for every command and interaction.
- A minimal two-role permission model: `Admin` and `Thành viên` (Member).
- Double confirmation before destructive setup.
- Keep-or-rollback recovery when an API step fails.
- Discord summary, local logs, and JSON setup reports.
- Extensible YAML templates with schema validation.
- Automated linting and tests on Python 3.11, 3.12, 3.13, and 3.14.

### Project structure

```text
elvis-setup/
├── assets/                 # README artwork
├── src/elvis_setup/        # Bot, UI, setup engine and reporting
├── templates/              # Editable YAML server templates
├── tests/                  # Unit tests
├── setup.bat               # First-time Windows setup
├── start.bat               # Windows launcher
└── main.py                 # Application entry point
```

### License

Released under the [MIT License](LICENSE). Copyright © 2026 Elvis Nguyen.
