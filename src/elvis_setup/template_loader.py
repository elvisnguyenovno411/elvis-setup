from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .models import ServerTemplate


class TemplateLoader:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def load_all(self) -> dict[str, ServerTemplate]:
        raw_templates: dict[str, dict[str, Any]] = {}
        for path in sorted(self.directory.glob("*.yml")):
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            if not isinstance(data, dict):
                raise ValueError(f"Template {path.name} phải là một YAML object.")
            raw_templates[path.stem] = data

        if "base" not in raw_templates:
            raise ValueError("Thiếu templates/base.yml.")

        result: dict[str, ServerTemplate] = {}
        for key in raw_templates:
            if key == "base":
                continue
            merged = self._resolve(key, raw_templates, set())
            result[key] = ServerTemplate.from_dict(key, merged)
        return result

    def _resolve(
        self,
        key: str,
        templates: dict[str, dict[str, Any]],
        visiting: set[str],
    ) -> dict[str, Any]:
        if key in visiting:
            raise ValueError(f"Phát hiện vòng lặp extends tại template: {key}")
        if key not in templates:
            raise ValueError(f"Không tìm thấy template được kế thừa: {key}")

        visiting.add(key)
        current = deepcopy(templates[key])
        parent_key = current.pop("extends", None)
        if not parent_key:
            visiting.remove(key)
            return current

        parent = self._resolve(str(parent_key), templates, visiting)
        merged = deepcopy(parent)
        for field, value in current.items():
            if field == "categories":
                merged[field] = [*merged.get(field, []), *value]
            else:
                merged[field] = value
        visiting.remove(key)
        return merged
