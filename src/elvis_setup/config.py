from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class Settings:
    token: str
    owner_user_id: int
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(ROOT_DIR / ".env")
        token = os.getenv("DISCORD_TOKEN", "").strip()
        owner_raw = os.getenv("OWNER_USER_ID", "").strip()

        missing = []
        if not token or token == "your_bot_token_here":
            missing.append("DISCORD_TOKEN")
        if not owner_raw or owner_raw == "123456789012345678":
            missing.append("OWNER_USER_ID")
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Thiếu cấu hình: {joined}. Hãy tạo file .env từ .env.example.")

        try:
            owner_id = int(owner_raw)
        except ValueError as exc:
            raise RuntimeError("OWNER_USER_ID phải là một dãy số Discord hợp lệ.") from exc

        return cls(
            token=token,
            owner_user_id=owner_id,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
