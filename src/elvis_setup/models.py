from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ChannelKind = Literal["text", "voice"]
AccessKind = Literal["member", "member_read_only", "admin"]


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    name: str
    kind: ChannelKind
    access: AccessKind
    topic: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChannelSpec:
        kind = data.get("type", "text")
        access = data.get("access", "member")
        if kind not in {"text", "voice"}:
            raise ValueError(f"Loại kênh không hợp lệ: {kind}")
        if access not in {"member", "member_read_only", "admin"}:
            raise ValueError(f"Quyền truy cập không hợp lệ: {access}")
        return cls(
            name=str(data["name"]),
            kind=kind,
            access=access,
            topic=data.get("topic"),
        )


@dataclass(frozen=True, slots=True)
class CategorySpec:
    key: str
    name: str
    channels: tuple[ChannelSpec, ...]
    required: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CategorySpec:
        return cls(
            key=str(data["key"]),
            name=str(data["name"]),
            channels=tuple(ChannelSpec.from_dict(item) for item in data.get("channels", [])),
            required=bool(data.get("required", False)),
        )


@dataclass(frozen=True, slots=True)
class ServerTemplate:
    key: str
    name: str
    description: str
    emoji: str
    color: int
    categories: tuple[CategorySpec, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, key: str, data: dict[str, Any]) -> ServerTemplate:
        raw_color = str(data.get("color", "5865F2")).removeprefix("#")
        return cls(
            key=key,
            name=str(data["name"]),
            description=str(data.get("description", "")),
            emoji=str(data.get("emoji", "🧩")),
            color=int(raw_color, 16),
            categories=tuple(CategorySpec.from_dict(item) for item in data.get("categories", [])),
        )
